#!/usr/bin/env python3
"""
构建客服图片素材库（正式，非试点）：
- 只保留【严格可入库】：类型∈{操作教程或界面指引, 商品参数图} 且 不含个人隐私
- 凑够 TARGET 张（默认 2000）即停止，不跑全量
- 感知哈希(phash)近重复去重；每张图关联来源会话（conv_id/客服配文/用户问题/型号），便于反查
- 二进制不落地：下载→phash→缩放→VLM→释放，只保存文字与原始URL
- 断点续跑：每批写 checkpoint，中断后重跑自动接续
产出: 02_数据/processed/media_assets.json
用法: python build_media_assets.py [目标张数=2000] [并发=16]
"""
import base64
import io
import json
import os
import random
import re
import sys
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor

import requests
from PIL import Image
import imagehash

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))
from paths import PARSED_CONVERSATIONS_PATH, MEDIA_ASSETS_PATH, RUNTIME_DIR  # noqa: E402
from api_config import load_config  # noqa: E402
from search_engine import mask_pii  # noqa: E402

IMG_EXT = (".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp")
GOOD_TYPES = {"操作教程或界面指引", "商品参数图"}
MODEL = "Qwen/Qwen3-VL-8B-Instruct"
CKPT = os.path.join(RUNTIME_DIR, "media_assets.ckpt.json")

VLM_PROMPT = """你是客服知识库素材分析器。请判断这张由【人工客服】发送的图片属于哪一类，并提取其中文字。
只输出 JSON，不要多余解释，格式：
{"类型": "操作教程或界面指引 | 故障现象照片 | 售后工单或隐私截图 | 商品参数图 | 产品铭牌或条码标签 | 店铺商品或订单价格页 | 聊天记录截图 | 其他",
 "是否含个人隐私": true或false,
 "画面描述": "不超过40字",
 "图中文字": "逐字提取图中关键文字/步骤/错误码/尺寸参数，没有则留空"}

八类定义：
1. 操作教程或界面指引：操作步骤图、App/机器界面指引、拆装/清洁/维护教程、功能流程示意（可入库）。
2. 故障现象照片：用户实拍的故障、损坏、报错现象（不入库）。
3. 售后工单或隐私截图：工单/售后单/聊天截图，含姓名、电话、地址、SN、订单号等（不入库，含隐私=true）。
4. 商品参数图：品牌为讲解而制作的安装尺寸图、结构/爆炸图、功能示意图、参数对照表（可入库）。
5. 产品铭牌或条码标签：【实拍机器本体上贴的纸质铭牌/标签】，内容是型号、额定电压功率、制造商、MIT/3C等认证编号、条形码或二维码，没有操作步骤也没有尺寸/结构示意（不入库）。
6. 店铺商品或订单价格页：电商店铺商品详情页、下单/订单/支付/服务保障/物流页面截图，出现价格、实付款、划线价、优惠、订单信息、服务保障、商品推荐/配件列表等（不入库；若同时出现姓名/电话/地址则含隐私=true）。
7. 聊天记录截图：微信/旺旺/客服对话记录截图（不入库）。
8. 其他：不属于以上任何一类。

关键区分（避免误判为“商品参数图”）：
- 实拍机器上贴着的、带条形码和制造商/认证编号的铭牌标签 → 必须判“产品铭牌或条码标签”，不是商品参数图。
- 带价格/实付/订单/服务保障/商品列表的电商或订单截图 → 必须判“店铺商品或订单价格页”，不是商品参数图。
- 只有品牌绘制的、用于说明安装尺寸/结构/功能/参数对照的示意图，才判“商品参数图”。"""


def is_image_url(u):
    return u.split("?")[0].lower().endswith(IMG_EXT)


def parse_json_lenient(txt):
    txt = re.sub(r"^```(?:json)?|```$", "", txt.strip(), flags=re.MULTILINE).strip()
    m = re.search(r"\{.*\}", txt, flags=re.DOTALL)
    return json.loads(m.group(0) if m else txt)


def build_url_index(data):
    """图片URL -> 来源会话上下文（客服图基本唯一，仍按list稳妥处理）"""
    idx = {}
    for item in data:
        problem = (item.get("problem_text") or "").replace("\n", " ")
        question = problem[:160]
        for t in item.get("turns", []):
            if t.get("role") != "agent":
                continue
            for u in (t.get("media") or []):
                if not is_image_url(u):
                    continue
                idx.setdefault(u, {
                    "conv_id": item.get("conv_id"),
                    "caption": (t.get("text") or "").replace("\n", " ")[:300],
                    "question": question,
                    "models": item.get("models", []),
                    "agent_name": item.get("agent_name", ""),
                    "start_time": item.get("start_time", ""),
                })
    return idx


def vlm(session, b64):
    cfg = load_config()
    base = cfg["embedding_api_url"].replace("/embeddings", "").rstrip("/")
    headers = {"Authorization": f"Bearer {cfg['embedding_api_key'].strip()}",
               "Content-Type": "application/json"}
    content = [{"type": "text", "text": VLM_PROMPT},
               {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}}]
    payload = {"model": MODEL, "messages": [{"role": "user", "content": content}],
               "temperature": 0.1, "max_tokens": 500}
    last = None
    for attempt in range(3):
        try:
            r = session.post(base + "/chat/completions", headers=headers, json=payload, timeout=90)
            if r.status_code != 200:
                raise RuntimeError(f"HTTP {r.status_code}: {r.text[:120]}")
            return parse_json_lenient(r.json()["choices"][0]["message"]["content"])
        except Exception as e:
            last = e
            time.sleep(1.5 * (attempt + 1))
    raise last


def worker(url):
    """下载→phash→VLM，返回结构化结果（不含会话上下文，由主线程合并）"""
    out = {"url": url, "ok": False}
    try:
        s = requests.Session()
        resp = s.get(url, allow_redirects=True, timeout=30)
        resp.raise_for_status()
        img = Image.open(io.BytesIO(resp.content))
        out["width"], out["height"] = img.size
        out["phash"] = str(imagehash.phash(img.convert("RGB")))
        im = img.convert("RGB")
        im.thumbnail((1280, 1280))
        buf = io.BytesIO()
        im.save(buf, format="JPEG", quality=85)
        v = vlm(s, base64.b64encode(buf.getvalue()).decode())
        out["type"] = v.get("类型", "其他")
        out["pii"] = bool(v.get("是否含个人隐私", False))
        out["desc"] = (v.get("画面描述") or "").strip()
        out["ocr"] = (v.get("图中文字") or "").strip()
        out["ok"] = True
    except Exception as e:
        out["error"] = str(e)[:160]
    return out


def is_acceptable(rec):
    return rec.get("ok") and rec.get("type") in GOOD_TYPES and not rec.get("pii")


def load_ckpt():
    if os.path.exists(CKPT):
        with open(CKPT, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"accepted": [], "seen_urls": [], "counters": {}}


def save_ckpt(state):
    tmp = CKPT + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False)
    os.replace(tmp, CKPT)


def build_media_assets(target=2000, workers=16, progress_cb=None, reset=False):
    """构建素材库。progress_cb(accepted, seen, target, counters)。
    reset=True 时忽略旧检查点重新构建（每周换新数据时用）。返回入库张数。"""
    def emit(msg, pct=None):
        print(msg)
        if progress_cb:
            progress_cb(msg, pct)

    emit("加载解析会话并建立 图片→会话 映射...", 1)
    with open(PARSED_CONVERSATIONS_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
    url_idx = build_url_index(data)
    all_urls = sorted(url_idx.keys())
    random.seed(42)
    random.shuffle(all_urls)
    emit(f"客服图片共 {len(all_urls)} 张，目标入库 {target} 张，并发 {workers}", 2)

    if reset and os.path.exists(CKPT):
        os.remove(CKPT)
    state = load_ckpt()
    accepted = state["accepted"]
    seen = set(state["seen_urls"])
    counters = Counter(state.get("counters", {}))
    acc_hashes = [imagehash.hex_to_hash(a["phash"]) for a in accepted]
    if len(accepted) or len(seen):
        emit(f"断点续跑：已入库 {len(accepted)}，已处理 {len(seen)}")

    def near_dup(ph):
        for h in acc_hashes:
            if ph - h <= 5:
                return True
        return False

    BATCH = workers * 4
    pending = [u for u in all_urls if u not in seen]
    t0 = time.time()
    i = 0
    with ThreadPoolExecutor(max_workers=workers) as ex:
        while i < len(pending) and len(accepted) < target:
            batch = pending[i:i + BATCH]
            i += BATCH
            for rec in ex.map(worker, batch):
                u = rec["url"]
                seen.add(u)
                if not rec.get("ok"):
                    counters["fail"] += 1
                    continue
                counters[f"type::{rec.get('type')}"] += 1
                if rec.get("pii"):
                    counters["pii"] += 1
                if not is_acceptable(rec):
                    counters["rejected"] += 1
                    continue
                ph = imagehash.hex_to_hash(rec["phash"])
                if near_dup(ph):
                    counters["dup"] += 1
                    continue
                ctx = url_idx.get(u, {})
                asset = {
                    "url": u,
                    "phash": rec["phash"],
                    "width": rec["width"], "height": rec["height"],
                    "type": rec["type"],
                    "desc": mask_pii(rec["desc"]),
                    "ocr": mask_pii(rec["ocr"]),
                    "conv_id": ctx.get("conv_id"),
                    "caption": mask_pii(ctx.get("caption", "")),
                    "question": mask_pii(ctx.get("question", "")),
                    "models": ctx.get("models", []),
                    "agent_name": ctx.get("agent_name", ""),
                    "start_time": ctx.get("start_time", ""),
                }
                accepted.append(asset)
                acc_hashes.append(ph)
                counters["accepted"] += 1
            state = {"accepted": accepted, "seen_urls": list(seen), "counters": dict(counters)}
            save_ckpt(state)
            rate = len(seen) / max(time.time() - t0, 1)
            pct = min(99, int(100 * len(accepted) / max(target, 1)))
            emit(f"已处理 {len(seen)} | 入库 {len(accepted)}/{target} | "
                 f"隐私{counters['pii']} 重复{counters['dup']} 失败{counters['fail']} | {rate:.1f}张/秒", pct)

    os.makedirs(os.path.dirname(MEDIA_ASSETS_PATH), exist_ok=True)
    with open(MEDIA_ASSETS_PATH, "w", encoding="utf-8") as f:
        json.dump(accepted, f, ensure_ascii=False)
    emit(f"完成：素材库 {len(accepted)} 张 -> {MEDIA_ASSETS_PATH}", 100)
    emit(f"类型分布: {dict(Counter(a['type'] for a in accepted))}")
    if os.path.exists(CKPT):
        os.remove(CKPT)
    return len(accepted)


def main():
    target = int(sys.argv[1]) if len(sys.argv) > 1 else 2000
    workers = int(sys.argv[2]) if len(sys.argv) > 2 else 16
    reset = (len(sys.argv) > 3 and sys.argv[3] == "reset")
    build_media_assets(target, workers, reset=reset)


if __name__ == "__main__":
    main()
