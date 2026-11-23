#!/usr/bin/env python3
"""
智能客服问答混合检索引擎：FAISS 语义 + BM25 关键词，RRF 融合 + Reranker 精排。
字段与筛选维度针对智能客服日志设计，独立于人工会话 SearchEngine。
"""

import json
import os
import pickle
import numpy as np
import jieba
from rank_bm25 import BM25Okapi
from text_utils import load_custom_dict, expand_query
from paths import AI_INDEX_DIR
from search_engine import mask_pii

load_custom_dict()


class AISearchEngine:
    def __init__(self, index_dir: str = AI_INDEX_DIR):
        self.index_dir = index_dir
        self._use_api = False
        self._api_cfg = None
        self._reranker_enabled = False
        self._load()

    def _load(self):
        import faiss
        with open(os.path.join(self.index_dir, "model_info.json"), "r") as f:
            info = json.load(f)
        print("[AI] 加载问答数据...")
        with open(os.path.join(self.index_dir, "data.json"), "r", encoding="utf-8") as f:
            self.data = json.load(f)
        print("[AI] 加载 FAISS...")
        self.faiss_index = faiss.read_index(os.path.join(self.index_dir, "faiss.index"))
        print("[AI] 加载 BM25...")
        with open(os.path.join(self.index_dir, "bm25.pkl"), "rb") as f:
            self.bm25 = pickle.load(f)

        self._use_api = info.get("use_api", False)
        if self._use_api:
            try:
                from api_config import is_api_configured, load_config
                if is_api_configured():
                    self._api_cfg = load_config()
                    print(f"[AI] API Embedding: {self._api_cfg['embedding_model']}")
                else:
                    self._use_api = False
            except ImportError:
                self._use_api = False
        if not self._use_api:
            from sentence_transformers import SentenceTransformer
            self.model = SentenceTransformer(info["model_name"])

        try:
            from api_config import is_reranker_configured
            if is_reranker_configured():
                self._reranker_enabled = True
                print("[AI] Reranker: 已启用")
        except ImportError:
            pass

        # 默认隐藏集合（transfer / pet_photo）
        self._hidden = {i for i, d in enumerate(self.data) if d.get("hidden")}
        # 会话 -> 行下标（查看同会话上下文）
        self._session = {}
        for i, d in enumerate(self.data):
            sid = d.get("session_id", "")
            if sid:
                self._session.setdefault(sid, []).append(i)
        for sid in self._session:
            self._session[sid].sort(key=lambda i: self.data[i].get("date", ""))
        print(f"[AI] 就绪，共 {len(self.data)} 条问答，默认隐藏 {len(self._hidden)} 条，"
              f"{len(self._session)} 个会话")

    def rebuild_bm25(self):
        texts = [d.get("question", "") + "\n" + d.get("answer", "") for d in self.data]
        tokenized = [list(jieba.cut(t)) for t in texts]
        self.bm25 = BM25Okapi(tokenized)
        with open(os.path.join(self.index_dir, "bm25.pkl"), "wb") as f:
            pickle.dump(self.bm25, f)
        print(f"[AI] BM25 重建完成，共 {len(self.data)} 条")

    def _encode_query(self, query):
        if self._use_api and self._api_cfg:
            from api_client import call_embeddings
            vec = np.array(call_embeddings([query], batch_size=1)[0], dtype=np.float32)
            norm = np.linalg.norm(vec)
            if norm > 0:
                vec = vec / norm
            return vec.reshape(1, -1)
        return self.model.encode([query], normalize_embeddings=True,
                                 convert_to_numpy=True).astype(np.float32)

    @staticmethod
    def _match_filters(item, filters):
        """返回 True 表示通过筛选"""
        f = filters or {}
        prod = f.get("product")
        if prod and prod.lower() not in (item.get("product", "") + " " + item.get("device_list", "")).lower():
            return False
        if f.get("category") and item.get("product_category", "") != f["category"]:
            return False
        if f.get("cat3") and item.get("cat3", "") != f["cat3"]:
            return False
        if f.get("qtype") and item.get("qtype", "") != f["qtype"]:
            return False
        if f.get("eff_recall") in ("1", "0") and item.get("eff_recall", "") != f["eff_recall"]:
            return False
        if f.get("relevant") in ("1", "0") and item.get("is_relevant", "") != f["relevant"]:
            return False
        if f.get("to_human") == "1" and item.get("to_human", "") != "1":
            return False
        if f.get("vote") and item.get("vote", "") != f["vote"]:
            return False
        return True

    def search(self, query, top_k=10, filters=None, include_hidden=False, use_reranker=True):
        n = len(self.data)
        recall_n = min(top_k * 10, n) if (use_reranker and self._reranker_enabled) else min(top_k * 6, n)

        # 1. 语义
        qvec = self._encode_query(query)
        sem_scores, sem_idx = self.faiss_index.search(qvec, recall_n)
        sem_scores, sem_idx = sem_scores[0], sem_idx[0]

        # 2. BM25（同义词扩展）
        tok = list(jieba.cut(expand_query(query)))
        bm25_scores = self.bm25.get_scores(tok)
        bm25_top = np.argsort(bm25_scores)[::-1][:recall_n]

        # 3. RRF
        rrf_k = 60
        fused = np.zeros(n, dtype=np.float64)
        for rank, idx in enumerate(sem_idx):
            fused[idx] += 0.5 / (rrf_k + rank + 1)
        for rank, idx in enumerate(bm25_top):
            if bm25_scores[idx] > 0:
                fused[idx] += 0.5 / (rrf_k + rank + 1)

        cand = np.where(fused > 0)[0]
        cand = cand[np.argsort(fused[cand])[::-1]][:recall_n]

        # 4. Reranker
        rerank = {}
        if use_reranker and self._reranker_enabled and len(cand):
            try:
                from api_client import call_rerank
                docs, valid = [], []
                for idx in cand:
                    d = self.data[idx]
                    doc = d.get("rewrite") or d.get("question", "")
                    doc += "\n" + d.get("question", "")
                    if d.get("product"):
                        doc += "\n产品: " + d["product"]
                    doc += "\n" + d.get("answer", "")[:800]
                    docs.append(doc)
                    valid.append(idx)
                rr = call_rerank(query, docs, top_n=min(recall_n, len(docs)))
                for r in rr:
                    rerank[valid[r["index"]]] = r["relevance_score"]
            except Exception as e:
                print(f"[AI] Reranker 失败，回退 RRF: {e}")

        ordered = sorted(rerank.keys(), key=lambda x: rerank[x], reverse=True) if rerank else list(cand)

        # 5. 组装 + 筛选
        agg = {"products": {}, "categories": {}, "cat3": {}}
        results = []
        sem_idx_list = list(sem_idx)
        for idx in ordered:
            d = self.data[idx]
            if idx in self._hidden and not include_hidden:
                continue
            if not self._match_filters(d, filters):
                continue

            for key, field in (("products", "product"), ("categories", "product_category"), ("cat3", "cat3")):
                v = d.get(field, "")
                if v:
                    agg[key][v] = agg[key].get(v, 0) + 1

            sem_s = float(sem_scores[sem_idx_list.index(idx)]) if idx in sem_idx_list else 0.0
            results.append({
                "rank": len(results) + 1,
                "score": round(float(rerank.get(idx, fused[idx])), 6),
                "semantic_score": round(sem_s, 4),
                "bm25_score": round(float(bm25_scores[idx]), 4),
                "rerank_score": round(float(rerank[idx]), 4) if rerank else None,
                "hidden": bool(d.get("hidden")),
                "qid": d.get("qid", ""),
                "session_id": d.get("session_id", ""),
                "date": d.get("date", ""),
                "channel": d.get("channel", ""),
                "product_category": d.get("product_category", ""),
                "product": d.get("product", ""),
                "question": mask_pii(d.get("question", "")),
                "rewrite": mask_pii(d.get("rewrite", "")),
                "answer": mask_pii(d.get("answer", "")),
                "qtype": d.get("qtype", ""),
                "eff_recall": d.get("eff_recall", ""),
                "is_relevant": d.get("is_relevant", ""),
                "is_recall": d.get("is_recall", ""),
                "adopted_kb": d.get("adopted_kb", []),
                "kb1": d.get("kb1", ""),
                "cat1": d.get("cat1", ""),
                "cat2": d.get("cat2", ""),
                "cat3": d.get("cat3", ""),
                "to_human": d.get("to_human", ""),
                "vote": d.get("vote", ""),
                "vote_reason": d.get("vote_reason", ""),
            })
            if len(results) >= top_k:
                break

        facets = {
            "products": sorted(agg["products"], key=lambda x: agg["products"][x], reverse=True)[:15],
            "categories": sorted(agg["categories"], key=lambda x: agg["categories"][x], reverse=True)[:8],
            "cat3": sorted(agg["cat3"], key=lambda x: agg["cat3"][x], reverse=True)[:15],
        }
        return results, facets

    def get_session(self, session_id):
        """返回同一会话内按时间排序的全部问答"""
        idxs = self._session.get(session_id, [])
        turns = []
        for i in idxs:
            d = self.data[i]
            turns.append({
                "date": d.get("date", ""),
                "product": d.get("product", ""),
                "product_category": d.get("product_category", ""),
                "question": mask_pii(d.get("question", "")),
                "rewrite": mask_pii(d.get("rewrite", "")),
                "answer": mask_pii(d.get("answer", "")),
                "qtype": d.get("qtype", ""),
                "cat3": d.get("cat3", ""),
                "qid": d.get("qid", ""),
                "hidden": bool(d.get("hidden")),
            })
        return {"session_id": session_id, "turns": turns} if turns else None

    def stats(self):
        dates = sorted(d.get("date", "") for d in self.data if d.get("date"))
        products, cats, cat3 = set(), set(), set()
        for d in self.data:
            if d.get("product"):
                products.add(d["product"])
            if d.get("product_category"):
                cats.add(d["product_category"])
            if d.get("cat3"):
                cat3.add(d["cat3"])
        return {
            "total": len(self.data),
            "hidden_count": len(self._hidden),
            "visible_count": len(self.data) - len(self._hidden),
            "session_count": len(self._session),
            "date_min": dates[0][:10] if dates else "",
            "date_max": dates[-1][:10] if dates else "",
            "product_count": len(products),
            "category_count": len(cats),
            "cat3_count": len(cat3),
            "use_api": self._use_api,
            "reranker_enabled": self._reranker_enabled,
        }
