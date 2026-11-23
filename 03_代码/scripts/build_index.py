#!/usr/bin/env python3
"""
构建混合检索索引：
  - 语义向量索引（FAISS，支持本地模型或 API embedding）
  - 关键词索引（jieba 分词 + BM25，含自定义产品词典）
"""

import json
import os
import sys
import pickle
import numpy as np
import jieba
from rank_bm25 import BM25Okapi

# 将 src 目录加入导入路径
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))
from paths import INDEX_DIR, PARSED_CONVERSATIONS_PATH

# ---------- 配置 ----------
LOCAL_MODEL_NAME = "BAAI/bge-small-zh-v1.5"
BATCH_SIZE = 64

# 自定义分词词典：型号、部件名、错误码、业务术语
CUSTOM_WORDS = [
    # 产品型号
    "G20S Ultra", "G20S", "P20 Pro", "P20 Ultra", "P20", "A30 Pro", "A30",
    "G10", "G10S", "G20", "T8", "T7", "Q Revo", "S8", "S7",
    "Z1 Plus", "Z1", "M1", "H50 Ultra", "H50",
    "A20", "A10", "Q5", "Q8", "V20", "P10",
    # 洗地机/洗衣机型号
    "A30 Pro Combo", "A30 Combo", "F25", "F10",
    # 部件/功能
    "激光雷达", "激光头", "激光测距", "LDS", "回充", "回充座", "充电桩",
    "滚刷", "主刷", "边刷", "拖布", "滤网", "尘盒", "水箱",
    "基站", "自清洁", "热风烘干", "自动集尘", "上下水",
    "旋转轴", "主轮", "万向轮", "弹片", "充电触片",
    "悬崖传感器", "沿墙传感器", "碰撞传感器", "ToF",
    "内筒", "底脚", "运输螺杆", "脱水", "烘干",
    # 错误/状态
    "错误1", "错误2", "错误3", "错误4", "错误5", "错误6", "错误7", "错误8",
    "错误9", "错误10", "错误61", "报错", "异响", "噪音", "震动",
    # 业务
    "延保", "保修卡", "序列号", "SN码", "以旧换新", "开箱扫码",
    "退换货", "补发", "备件", "上门维修", "寄修", "工单",
]


def load_custom_dict():
    """加载自定义分词词典"""
    for word in CUSTOM_WORDS:
        jieba.add_word(word, freq=10000)


def build_index(parsed_path: str, progress_cb=None, index_dir=None):
    index_dir = index_dir or INDEX_DIR
    def log(msg, pct=None):
        print(msg)
        if progress_cb:
            progress_cb(msg, pct)

    os.makedirs(index_dir, exist_ok=True)
    load_custom_dict()

    log(f"加载解析数据: {parsed_path}", 5)
    with open(parsed_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    log(f"  共 {len(data)} 条", 10)
    if not data:
        raise ValueError("没有符合检索质量规则的会话，未构建索引")

    # ---------- 构建检索文本 ----------
    texts_for_embedding = []
    texts_for_bm25 = []

    for item in data:
        # 语义匹配用：问题描述 + 型号 + 错误码
        embed_text = item["problem_text"]
        if item["models"]:
            embed_text += "\n型号: " + " ".join(item["models"])
        if item["error_codes"]:
            embed_text += "\n错误码: " + " ".join(item["error_codes"])
        # 客服发送了操作图/视频时，给语义检索一个素材提示，便于搜"图示/操作视频"
        ms = item.get("media_summary") or {}
        if ms.get("has_agent_media"):
            hints = []
            if ms.get("agent_img"):
                hints.append(f"{ms['agent_img']}张操作示意图")
            if ms.get("agent_video"):
                hints.append(f"{ms['agent_video']}个操作演示视频")
            if hints:
                embed_text += "\n客服提供了" + "、".join(hints)
        texts_for_embedding.append(embed_text)

        # BM25 用：问题 + 解答全文
        bm25_text = item["problem_text"] + "\n" + item["solution_text"]
        texts_for_bm25.append(bm25_text)

    # ---------- 1. BM25 索引 ----------
    log("\n构建 BM25 关键词索引（含自定义词典）...", 15)
    tokenized_corpus = [list(jieba.cut(t)) for t in texts_for_bm25]
    bm25 = BM25Okapi(tokenized_corpus)
    log("  BM25 索引完成", 20)

    # ---------- 2. 语义向量索引 ----------
    # 优先使用 API embedding，未配置则用本地模型
    use_api = False
    try:
        from api_config import is_api_configured, load_config
        if is_api_configured():
            use_api = True
    except ImportError:
        pass

    if use_api:
        from api_client import call_embeddings
        from api_config import load_config as load_api_config
        api_cfg = load_api_config()
        log(f"\n使用 API Embedding: {api_cfg['embedding_model']}", 25)

        # 分批调用以便报告进度
        all_embeddings = []
        total_batches = (len(texts_for_embedding) + BATCH_SIZE - 1) // BATCH_SIZE
        for bi in range(0, len(texts_for_embedding), BATCH_SIZE):
            batch = texts_for_embedding[bi:bi + BATCH_SIZE]
            vecs = call_embeddings(batch, batch_size=BATCH_SIZE)
            all_embeddings.extend(vecs)
            batch_num = bi // BATCH_SIZE + 1
            pct = 25 + int(65 * batch_num / total_batches)
            if batch_num % 5 == 0 or batch_num == total_batches:
                log(f"  向量化进度: {bi + len(batch)}/{len(texts_for_embedding)}", pct)

        embeddings = np.array(all_embeddings, dtype=np.float32)
        norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        embeddings = embeddings / norms
        dim = embeddings.shape[1]
        model_name = api_cfg["embedding_model"]
        log(f"  向量矩阵: {embeddings.shape}", 90)
    else:
        log(f"\n使用本地模型: {LOCAL_MODEL_NAME}", 25)
        from sentence_transformers import SentenceTransformer
        model = SentenceTransformer(LOCAL_MODEL_NAME)
        dim = model.get_sentence_embedding_dimension()
        log(f"  模型加载完成，向量维度: {dim}", 30)

        log("生成向量嵌入...", 35)
        embeddings = model.encode(
            texts_for_embedding,
            batch_size=BATCH_SIZE,
            show_progress_bar=True,
            normalize_embeddings=True,
            convert_to_numpy=True,
        )
        model_name = LOCAL_MODEL_NAME
        log(f"  向量矩阵: {embeddings.shape}", 90)

    # FAISS 内积索引（向量已归一化，内积=余弦相似度）
    import faiss
    index = faiss.IndexFlatIP(dim)
    index.add(embeddings.astype(np.float32))
    log(f"  FAISS 索引完成，共 {index.ntotal} 条向量", 93)

    # ---------- 3. 保存 ----------
    log("保存索引文件...", 95)
    faiss_path = os.path.join(index_dir, "faiss.index")
    bm25_path = os.path.join(index_dir, "bm25.pkl")
    data_path = os.path.join(index_dir, "data.json")
    model_path = os.path.join(index_dir, "model_info.json")

    faiss.write_index(index, faiss_path)
    with open(bm25_path, "wb") as f:
        pickle.dump(bm25, f)
    with open(data_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    with open(model_path, "w", encoding="utf-8") as f:
        json.dump({
            "model_name": model_name,
            "dim": dim,
            "use_api": use_api,
        }, f, ensure_ascii=False)

    log(f"索引保存完成！共 {len(data)} 条", 100)


if __name__ == "__main__":
    parsed = sys.argv[1] if len(sys.argv) > 1 else PARSED_CONVERSATIONS_PATH
    build_index(parsed)
