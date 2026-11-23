#!/usr/bin/env python3
"""
语义聚类：将人工会话按问题相似度分组，并用 LLM 生成标题和标准答案。
流程：FAISS k-NN 图 → Leiden 社区发现 → LLM 命名+总结
输出：09_运行数据与缓存/clusters.json
"""

import json
import os
import sys
import time
import numpy as np

# 将 src 加入路径
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))
from paths import INDEX_DIR, RUNTIME_DIR

import faiss
import igraph as ig
import leidenalg


# ---------- 参数 ----------
K_NEIGHBORS = 25          # 每个节点连接的最近邻数
MIN_CLUSTER_SIZE = 5      # 小于此数的簇归入噪声
LEIDEN_RESOLUTION = 0.08  # 越大簇越多越细，越小簇越少越粗
SIMILARITY_THRESHOLD = 0.4 # 低于此相似度的边不建（减少噪声连接）
LLM_BATCH_SIZE = 5        # 每批并发总结的簇数
TOP_SAMPLES = 8           # 每个簇取多少条代表问题给 LLM


def load_index():
    """加载 FAISS 索引和数据"""
    print("加载索引和数据...")
    index = faiss.read_index(os.path.join(INDEX_DIR, "faiss.index"))
    with open(os.path.join(INDEX_DIR, "data.json"), "r", encoding="utf-8") as f:
        data = json.load(f)
    print(f"  共 {len(data)} 条会话，向量维度 {index.d}")
    return index, data


def build_knn_graph(index, n):
    """用 FAISS 构建 k-NN 相似度图"""
    print(f"构建 k-NN 图（k={K_NEIGHBORS}）...")
    # 重建向量矩阵（IndexFlatIP 可以直接 reconstruct）
    vectors = index.reconstruct_n(0, n)

    # 批量搜索邻居
    edges = []
    weights = []
    batch_size = 1000
    for start in range(0, n, batch_size):
        end = min(start + batch_size, n)
        batch = vectors[start:end]
        scores, indices = index.search(batch, K_NEIGHBORS + 1)  # +1 因为包含自己
        for i in range(end - start):
            global_i = start + i
            for j in range(len(indices[i])):
                global_j = int(indices[i][j])
                sim = float(scores[i][j])
                if global_j == global_i:
                    continue
                if sim < SIMILARITY_THRESHOLD:
                    continue
                edges.append((global_i, global_j))
                weights.append(sim)
        if (start // batch_size) % 5 == 0:
            print(f"  {end}/{n}...")

    print(f"  边数: {len(edges)}")
    return edges, weights


def run_leiden(n, edges, weights):
    """Leiden 社区发现"""
    print("运行 Leiden 社区发现...")
    g = ig.Graph(n)
    g.add_edges(edges)
    g.es['weight'] = weights

    partition = leidenalg.find_partition(
        g,
        leidenalg.CPMVertexPartition,
        weights='weight',
        resolution_parameter=LEIDEN_RESOLUTION,
        n_iterations=-1,
    )

    clusters = {}
    noise = []
    for idx, cluster_id in enumerate(partition.membership):
        if cluster_id not in clusters:
            clusters[cluster_id] = []
        clusters[cluster_id].append(idx)

    # 过滤小簇
    valid_clusters = []
    for members in clusters.values():
        if len(members) >= MIN_CLUSTER_SIZE:
            valid_clusters.append(members)
        else:
            noise.extend(members)

    # 按大小排序
    valid_clusters.sort(key=len, reverse=True)
    print(f"  发现 {len(valid_clusters)} 个有效簇（≥{MIN_CLUSTER_SIZE}条），噪声 {len(noise)} 条")
    return valid_clusters, noise


def get_representative(data, members, vectors=None):
    """获取簇的代表性问题（取前 TOP_SAMPLES 条，按问题长度适中优先）"""
    items = [data[i] for i in members]
    # 按问题文本长度排序，取适中长度的（太短信息量少，太长可能是多问题混杂）
    items.sort(key=lambda x: abs(len(x.get("problem_text", "")) - 80))
    samples = items[:TOP_SAMPLES]
    return samples


def call_llm(messages, max_tokens=1024):
    """调用 LLM API"""
    import requests
    from api_config import load_config, get_llm_key, normalize_llm_api_url

    cfg = load_config()
    key = get_llm_key()
    if not key:
        return None

    resp = requests.post(
        normalize_llm_api_url(cfg.get("llm_api_url")),
        json={
            "model": cfg.get("llm_model", "deepseek-ai/DeepSeek-V3"),
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": 0.3,
        },
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
        },
        timeout=60,
    )
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"]


def generate_title_and_summary(samples):
    """用 LLM 为簇生成标题和标准答案"""
    problems = []
    solutions = []
    for i, s in enumerate(samples):
        problems.append(f"{i+1}. {s.get('problem_text', '')[:200]}")
        sol = s.get("solution_text", "")[:500]
        solutions.append(f"--- 会话{i+1}解答 ---\n{sol}")

    prompt = f"""以下是多条用户与人工客服的会话，它们属于同一类问题。

用户问题：
{chr(10).join(problems)}

客服解答：
{chr(10).join(solutions)}

请完成两件事：
1. 用不超过15个字概括这类问题的标题（如"扫地机错误1排查"、"洗衣机异响处理"）
2. 综合所有客服解答，写出标准解答方案（排查步骤+解决方案+注意事项，Markdown格式，简洁专业）

请严格按以下格式输出：
标题：xxx
解答：
（Markdown内容）"""

    try:
        result = call_llm(
            [{"role": "user", "content": prompt}],
            max_tokens=1500,
        )
        if not result:
            return "未命名", "（LLM 未配置，无法生成总结）"

        # 解析标题和解答
        title = "未命名"
        answer = result
        if "标题：" in result:
            parts = result.split("解答：", 1)
            if len(parts) == 2:
                title_part = parts[0].replace("标题：", "").strip()
                title = title_part.split("\n")[0].strip()
                answer = parts[1].strip()
        return title, answer
    except Exception as e:
        return f"生成失败({e})", ""


def main():
    t0 = time.time()
    index, data = load_index()
    n = len(data)

    # 1. 构建 k-NN 图
    edges, weights = build_knn_graph(index, n)

    # 2. Leiden 聚类
    valid_clusters, noise = run_leiden(n, edges, weights)

    # 3. 为每个簇生成标题和总结（并发）
    from concurrent.futures import ThreadPoolExecutor, as_completed

    def process_cluster(args):
        i, members = args
        samples = get_representative(data, members)
        title, answer = generate_title_and_summary(samples)
        all_models = set()
        all_errors = set()
        for idx in members:
            all_models.update(data[idx].get("models", []))
            all_errors.update(data[idx].get("error_codes", []))
        return {
            "id": i,
            "title": title,
            "answer": answer,
            "size": len(members),
            "models": sorted(all_models)[:10],
            "error_codes": sorted(all_errors)[:10],
            "member_ids": [data[idx]["conv_id"] for idx in members[:100]],
            "sample_problems": [s.get("problem_text", "")[:150] for s in samples[:3]],
        }

    print(f"\n开始为 {len(valid_clusters)} 个簇生成标题和总结（8 并发）...")
    clusters_out = [None] * len(valid_clusters)
    done_count = 0
    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = {executor.submit(process_cluster, (i, m)): i
                   for i, m in enumerate(valid_clusters)}
        for future in as_completed(futures):
            result = future.result()
            clusters_out[result["id"]] = result
            done_count += 1
            if done_count % 20 == 0 or done_count == len(valid_clusters):
                print(f"  已处理 {done_count}/{len(valid_clusters)}")

    # 5. 保存
    output = {
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "total_conversations": n,
        "total_clusters": len(clusters_out),
        "noise_count": len(noise),
        "clusters": clusters_out,
    }

    os.makedirs(RUNTIME_DIR, exist_ok=True)
    output_path = os.path.join(RUNTIME_DIR, "clusters.json")
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    elapsed = round(time.time() - t0, 1)
    print(f"\n完成！耗时 {elapsed}s")
    print(f"  有效簇: {len(clusters_out)}")
    print(f"  噪声: {len(noise)} 条")
    print(f"  保存到: {output_path}")

    # 打印前10个簇预览
    print(f"\n前10个簇预览：")
    for c in clusters_out[:10]:
        print(f"  [{c['size']:4d}条] {c['title']}")


if __name__ == "__main__":
    main()
