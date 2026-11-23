#!/usr/bin/env python3
"""
第 1 步小试点：客服图片素材 → 视觉大模型理解
- 样本：files.roborock.com 官方图片（全取）+ 随机 N 张客服(agent)发送的图片
- 流程（不落地二进制）：下载 → 感知哈希(phash)去重分析 → 缩放 → VLM(描述/OCR/隐私判定) → 释放
- 产出（09_运行数据与缓存/media_pilot/）：
    pilot_results.json  每张图的结构化结果
    pilot_report.md     分布/去重率/全量估算
    pilot_gallery.html  缩略图+判定结果，供人工抽检（缩略图直连CDN，不占本地）
用法: python media_pilot.py [每类样本数=200] [VLM模型]
"""
import base64
import io
import json
import os
import random
import re
import sys
import time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
from PIL import Image
import imagehash

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))
from paths import PARSED_CONVERSATIONS_PATH  # noqa: E402
from api_config import load_config  # noqa: E402

OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "09_运行数据与缓存", "media_pilot")
OUT_DIR = os.path.abspath(OUT_DIR)
IMG_EXT = (".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp")

VLM_PROMPT = """你是客服知识库素材分析器。请判断这张由【人工客服】发送的图片属于哪一类，并提取其中文字。
只输出 JSON，不要多余解释，格式：
{"类型": "操作教程或界面指引 | 故障现象照片 | 售后工单或隐私截图 | 商品参数图 | 聊天记录截图 | 其他",
 "是否含个人隐私": true或false,
 "是否适合入知识库": true或false,
 "画面描述": "不超过40字",
 "图中文字": "逐字提取图中关键文字/步骤/错误码，没有则留空"}
判定要点：含姓名/电话/地址/SN/订单号等个人信息的工单或聊天截图，含隐私=true、适合入知识库=false；操作步骤、App界面指引、产品结构/参数图适合入知识库。"""


def is_image_url(u: str) -> bool:
    return u.split("?")[0].lower().endswith(IMG_EXT)


def collect_samples(n_agent: int):
    with open(PARSED_CONVERSATIONS_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
    agent_imgs, official_imgs = set(), set()
    for item in data:
        for t in item.get("turns", []):
            for u in (t.get("media") or []):
                if not is_image_url(u):
                    continue
                if "files.roborock.com" in u:
                    official_imgs.add(u)
                elif t.get("role") == "agent":
                    agent_imgs.add(u)
    agent_imgs = sorted(agent_imgs)
    random.seed(42)
    random.shuffle(agent_imgs)
    pick_agent = agent_imgs[:n_agent]
    samples = [("official", u) for u in sorted(official_imgs)] + [("agent", u) for u in pick_agent]
    return samples, len(agent_imgs), len(official_imgs)


def vlm_chat(session, cfg, model, b64, mime):
    base = cfg["embedding_api_url"].replace("/embeddings", "").rstrip("/")
    url = base + "/chat/completions"
    headers = {"Authorization": f"Bearer {cfg['embedding_api_key'].strip()}",
               "Content-Type": "application/json"}
    content = [
        {"type": "text", "text": VLM_PROMPT},
        {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}},
    ]
    payload = {"model": model, "messages": [{"role": "user", "content": content}],
               "temperature": 0.1, "max_tokens": 500}
    for attempt in range(3):
        try:
            r = session.post(url, headers=headers, json=payload, timeout=90)
            if r.status_code != 200:
                raise RuntimeError(f"HTTP {r.status_code}: {r.text[:150]}")
            txt = r.json()["choices"][0]["message"]["content"].strip()
            return parse_json_lenient(txt)
        except Exception as e:
            if attempt == 2:
                raise
            time.sleep(1.5 * (attempt + 1))


def parse_json_lenient(txt):
    txt = re.sub(r"^```(?:json)?|```$", "", txt.strip(), flags=re.MULTILINE).strip()
    m = re.search(r"\{.*\}", txt, flags=re.DOTALL)
    if m:
        return json.loads(m.group(0))
    return json.loads(txt)


def process_one(args):
    source, url, model = args
    t0 = time.time()
    rec = {"source": source, "url": url, "ok": False}
    try:
        cfg = load_config()
        s = requests.Session()
        resp = s.get(url, allow_redirects=True, timeout=30)
        resp.raise_for_status()
        raw = resp.content
        rec["bytes"] = len(raw)
        img = Image.open(io.BytesIO(raw))
        rec["width"], rec["height"] = img.size
        rec["phash"] = str(imagehash.phash(img.convert("RGB")))
        # 缩放到最长边 1280 供 VLM（省带宽，文字仍清晰）
        im = img.convert("RGB")
        im.thumbnail((1280, 1280))
        buf = io.BytesIO()
        im.save(buf, format="JPEG", quality=85)
        b64 = base64.b64encode(buf.getvalue()).decode()
        out = vlm_chat(s, cfg, model, b64, "image/jpeg")
        rec.update({
            "type": out.get("类型", "未知"),
            "pii": bool(out.get("是否含个人隐私", False)),
            "suitable": bool(out.get("是否适合入知识库", False)),
            "desc": out.get("画面描述", ""),
            "ocr": out.get("图中文字", ""),
        })
        rec["ok"] = True
    except Exception as e:
        rec["error"] = str(e)[:200]
    rec["latency"] = round(time.time() - t0, 2)
    return rec


def dedup_stats(records):
    """phash 汉明距离<=4 视为近重复，统计去重率"""
    hashes = [(r["phash"], imagehash.hex_to_hash(r["phash"])) for r in records if r.get("phash")]
    n = len(hashes)
    parent = list(range(n))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    for i in range(n):
        for j in range(i + 1, n):
            if hashes[i][1] - hashes[j][1] <= 4:
                union(i, j)
    groups = defaultdict(list)
    for i in range(n):
        groups[find(i)].append(i)
    dup_pairs = sum(len(g) - 1 for g in groups.values() if len(g) > 1)
    return n, len(groups), dup_pairs, groups, hashes


def build_gallery(records, path):
    order = {"操作教程或界面指引": 0, "商品参数图": 1, "故障现象照片": 2,
             "聊天记录截图": 3, "售后工单或隐私截图": 4, "其他": 5}
    records = sorted(records, key=lambda r: (order.get(r.get("type"), 9), not r.get("suitable")))
    rows = []
    for r in records:
        if not r.get("ok"):
            rows.append(f'<div class="card err"><div class="t">失败</div><div class="e">{esc(r.get("error",""))}</div><div class="u">{esc(r["url"])}</div></div>')
            continue
        cls = "good" if r["suitable"] else ("pii" if r["pii"] else "no")
        rows.append(
            f'<div class="card {cls}">'
            f'<img loading="lazy" src="{esc(r["url"])}" onclick="window.open(this.src)">'
            f'<div class="badges"><span class="b">{esc(r["type"])}</span>'
            f'{"<span class=b-pii>隐私</span>" if r["pii"] else ""}'
            f'{"<span class=b-ok>可入库</span>" if r["suitable"] else "<span class=b-no>不入库</span>"}</div>'
            f'<div class="desc">{esc(r["desc"])}</div>'
            f'<div class="ocr">{esc(r["ocr"][:300])}</div>'
            f'<div class="meta">{r["width"]}×{r["height"]} · {r["bytes"]//1024}KB · {r["latency"]}s · {esc(r["source"])}</div>'
            f'</div>')
    html = """<!doctype html><html lang=zh><head><meta charset=utf-8>
<title>客服图片素材试点抽检</title><style>
body{font-family:-apple-system,'PingFang SC',sans-serif;margin:20px;background:#f5f6f8;color:#222}
h1{font-size:20px}.toolbar{margin:10px 0;position:sticky;top:0;background:#f5f6f8;padding:8px 0;z-index:2}
.toolbar button{margin-right:8px;padding:5px 12px;border:1px solid #ccc;background:#fff;border-radius:6px;cursor:pointer}
.toolbar button.on{background:#4f7cff;color:#fff;border-color:#4f7cff}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(240px,1fr));gap:12px}
.card{background:#fff;border-radius:8px;padding:10px;border:1px solid #eee;border-top:3px solid #ccc}
.card.good{border-top-color:#1a9e5a}.card.pii{border-top-color:#e54545}.card.no{border-top-color:#bbb}.card.err{border-top-color:#e8870e}
.card img{width:100%;max-height:220px;object-fit:contain;background:#fafafa;border-radius:4px;cursor:zoom-in}
.badges{margin:6px 0;display:flex;gap:4px;flex-wrap:wrap}.b,.b-pii,.b-ok,.b-no{font-size:11px;padding:2px 7px;border-radius:10px;background:#eef1f5}
.b-pii{background:#ffecec;color:#e54545}.b-ok{background:#e7f7ee;color:#1a9e5a}.b-no{background:#f0f0f0;color:#888}
.desc{font-size:13px;font-weight:600;margin:4px 0}.ocr{font-size:11px;color:#555;background:#fafafa;padding:6px;border-radius:4px;max-height:110px;overflow:auto;white-space:pre-wrap}
.meta{font-size:10px;color:#999;margin-top:5px}.e{color:#e8870e;font-size:12px}.u{font-size:10px;word-break:break-all;color:#aaa}
</style></head><body>
<h1>客服图片素材 · VLM 试点抽检</h1>
<div class=toolbar>
<button class=on onclick="flt('all',this)">全部</button>
<button onclick="flt('good',this)">仅可入库</button>
<button onclick="flt('pii',this)">仅含隐私</button>
<button onclick="flt('no',this)">仅不入库</button>
<button onclick="flt('err',this)">失败</button></div>
<div class=grid>__ROWS__</div>
<script>
function flt(k,b){document.querySelectorAll('.toolbar button').forEach(x=>x.classList.remove('on'));b.classList.add('on');
document.querySelectorAll('.card').forEach(c=>{c.style.display=(k==='all'||c.classList.contains(k))?'':'none'})}
</script></body></html>"""
    with open(path, "w", encoding="utf-8") as f:
        f.write(html.replace("__ROWS__", "".join(rows)))


def esc(s):
    return (str(s) if s is not None else "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def main():
    n_agent = int(sys.argv[1]) if len(sys.argv) > 1 else 200
    model = sys.argv[2] if len(sys.argv) > 2 else "Qwen/Qwen3-VL-8B-Instruct"
    os.makedirs(OUT_DIR, exist_ok=True)

    samples, total_agent, total_official = collect_samples(n_agent)
    print(f"客服图片全量(去URL): {total_agent} 张；官方图片: {total_official} 张；本次试点: {len(samples)} 张")
    print(f"VLM 模型: {model}，并发 10")

    results = []
    t_start = time.time()
    done = 0
    with ThreadPoolExecutor(max_workers=10) as ex:
        futs = [ex.submit(process_one, (src, u, model)) for src, u in samples]
        for fut in as_completed(futs):
            results.append(fut.result())
            done += 1
            if done % 20 == 0:
                print(f"  已处理 {done}/{len(samples)}，用时 {time.time()-t_start:.0f}s")

    wall = time.time() - t_start
    ok = [r for r in results if r.get("ok")]
    fail = [r for r in results if not r.get("ok")]
    type_c = Counter(r.get("type", "失败") for r in results)
    n_pii = sum(1 for r in ok if r["pii"])
    n_fit = sum(1 for r in ok if r["suitable"])
    n, n_cluster, n_dup, _, _ = dedup_stats(ok)
    lat = sorted(r["latency"] for r in ok)
    avg_lat = sum(lat) / max(len(lat), 1)

    with open(os.path.join(OUT_DIR, "pilot_results.json"), "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    build_gallery(results, os.path.join(OUT_DIR, "pilot_gallery.html"))

    # 全量估算（wall 已含 10 并发，按实测吞吐外推同等并发下的墙钟时间）
    est_wall_min = total_agent * (wall / max(len(results), 1)) / 60

    lines = []
    lines.append("# 客服图片素材 VLM 试点报告\n")
    lines.append(f"- 试点样本：{len(results)} 张（官方 {total_official} + 随机客服 {min(n_agent,total_agent)}），成功 {len(ok)}、失败 {len(fail)}")
    lines.append(f"- VLM 模型：{model}；总耗时 {wall:.0f}s，单张平均 {avg_lat:.1f}s（10 并发）")
    lines.append(f"\n## 类型分布\n")
    for t, c in type_c.most_common():
        lines.append(f"- {t}: {c} ({c/len(results)*100:.1f}%)")
    lines.append(f"\n## 可用性\n")
    lines.append(f"- 判定**适合入知识库**：{n_fit} 张（{n_fit/max(len(ok),1)*100:.1f}%）")
    lines.append(f"- 判定**含个人隐私**（工单/聊天截图，需剔除）：{n_pii} 张（{n_pii/max(len(ok),1)*100:.1f}%）")
    lines.append(f"\n## 感知哈希去重\n")
    lines.append(f"- 成功计算 phash：{n} 张；近重复聚类后唯一：{n_cluster} 张；可合并重复：{n_dup} 张")
    lines.append(f"- 试点去重率：{n_dup/max(n,1)*100:.1f}%")
    lines.append(f"\n## 全量（{total_agent} 张客服图）估算\n")
    lines.append(f"- 按本次实测吞吐（10 并发）约需 **{est_wall_min:.0f} 分钟**；若 API 支持、提到 20 并发约 {est_wall_min/2:.0f} 分钟")
    lines.append(f"- 预计可入库素材 ≈ {int(total_agent*n_fit/max(len(ok),1))} 张，隐私剔除 ≈ {int(total_agent*n_pii/max(len(ok),1))} 张（试点比例外推，仅供参考）")
    lines.append(f"\n## 失败样本\n")
    for r in fail[:10]:
        lines.append(f"- {r.get('error')} | {r['url'][:90]}")
    report = "\n".join(lines)
    with open(os.path.join(OUT_DIR, "pilot_report.md"), "w", encoding="utf-8") as f:
        f.write(report)
    print("\n" + report)
    print(f"\n产出目录: {OUT_DIR}")


if __name__ == "__main__":
    main()
