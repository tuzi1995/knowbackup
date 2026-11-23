#!/usr/bin/env python3
"""
构建智能客服问答检索索引：
  - 语义向量索引（FAISS，API embedding 或本地模型）
  - 关键词索引（jieba + BM25，复用自定义产品词典）
索引单元 = 一条问答（一行）。transfer/pet_photo 仍建索引但记录 hidden 标记，检索时默认隐藏。
输出到 AI_INDEX_DIR。
"""

import json
import os
import sys
import pickle
import numpy as np
import jieba
from rank_bm25 import BM25Okapi

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))
from paths import AI_INDEX_DIR, PARSED_AI_PATH
from text_utils import load_custom_dict

BATCH_SIZE = 64


def _embed_text(item):
    t = item.get("rewrite") or item.get("question", "")
    if item.get("product"):
        t += "\n产品: " + item["product"]
    if item.get("cat3"):
        t += "\n分类: " + item["cat3"]
    return t


def _bm25_text(item):
    return item.get("question", "") + "\n" + item.get("answer", "")


def build_ai_index(parsed_path: str = PARSED_AI_PATH, progress_cb=None):
    def log(msg, pct=None):
        print(msg)
        if progress_cb:
            progress_cb(msg, pct)

    os.makedirs(AI_INDEX_DIR, exist_ok=True)
    load_custom_dict()

    log(f"加载智能客服解析数据: {parsed_path}", 5)
    with open(parsed_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    log(f"  共 {len(data)} 条问答（其中默认隐藏 "
        f"{sum(1 for d in data if d.get('hidden'))} 条）", 10)

    embed_texts = [_embed_text(d) for d in data]
    bm25_texts = [_bm25_text(d) for d in data]

    # ---------- 1. BM25 ----------
    log("构建 BM25 关键词索引...", 15)
    tokenized = [list(jieba.cut(t)) for t in bm25_texts]
    bm25 = BM25Okapi(tokenized)
    log("  BM25 完成", 20)

    # ---------- 2. 向量 ----------
    use_api = False
    try:
        from api_config import is_api_configured
        use_api = is_api_configured()
    except ImportError:
        pass

    if use_api:
        from api_client import call_embeddings
        from api_config import load_config
        cfg = load_config()
        log(f"使用 API Embedding: {cfg['embedding_model']}", 25)
        all_vecs = []
        total_batches = (len(embed_texts) + BATCH_SIZE - 1) // BATCH_SIZE
        for bi in range(0, len(embed_texts), BATCH_SIZE):
            batch = embed_texts[bi:bi + BATCH_SIZE]
            all_vecs.extend(call_embeddings(batch, batch_size=BATCH_SIZE))
            bn = bi // BATCH_SIZE + 1
            pct = 25 + int(65 * bn / total_batches)
            if bn % 10 == 0 or bn == total_batches:
                log(f"  向量化进度: {bi + len(batch)}/{len(embed_texts)}", pct)
        embeddings = np.array(all_vecs, dtype=np.float32)
        norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        embeddings = embeddings / norms
        dim = embeddings.shape[1]
        model_name = cfg["embedding_model"]
    else:
        log("使用本地模型", 25)
        from sentence_transformers import SentenceTransformer
        from build_index import LOCAL_MODEL_NAME
        model = SentenceTransformer(LOCAL_MODEL_NAME)
        embeddings = model.encode(embed_texts, batch_size=BATCH_SIZE,
                                  normalize_embeddings=True, convert_to_numpy=True)
        dim = embeddings.shape[1]
        model_name = LOCAL_MODEL_NAME
    log(f"  向量矩阵: {embeddings.shape}", 90)

    # ---------- 3. FAISS ----------
    import faiss
    index = faiss.IndexFlatIP(dim)
    index.add(embeddings.astype(np.float32))
    log(f"  FAISS 完成，共 {index.ntotal} 条", 93)

    # ---------- 4. 保存 ----------
    log("保存索引文件...", 95)
    faiss.write_index(index, os.path.join(AI_INDEX_DIR, "faiss.index"))
    with open(os.path.join(AI_INDEX_DIR, "bm25.pkl"), "wb") as f:
        pickle.dump(bm25, f)
    with open(os.path.join(AI_INDEX_DIR, "data.json"), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    with open(os.path.join(AI_INDEX_DIR, "model_info.json"), "w", encoding="utf-8") as f:
        json.dump({"model_name": model_name, "dim": dim, "use_api": use_api,
                   "corpus": "ai_qa"}, f, ensure_ascii=False)
    log(f"智能客服索引保存完成！共 {len(data)} 条", 100)


if __name__ == "__main__":
    parsed = sys.argv[1] if len(sys.argv) > 1 else PARSED_AI_PATH
    build_ai_index(parsed)
