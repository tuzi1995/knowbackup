#!/usr/bin/env python3
"""
混合检索引擎：语义向量(FAISS) + 关键词(BM25)，RRF 融合排序 + Reranker 精排
支持本地模型或 API embedding/reranker
"""

import json
import os
import re
import pickle
import numpy as np
import jieba
from rank_bm25 import BM25Okapi
from text_utils import load_custom_dict, expand_query, get_query_terms, is_low_quality
from paths import INDEX_DIR

# 初始化自定义词典
load_custom_dict()


def mask_pii(text: str) -> str:
    """脱敏：手机号、身份证号"""
    if not text:
        return text
    text = re.sub(r'1[3-9]\d{9}', lambda m: m.group(0)[:3] + '****' + m.group(0)[-4:], text)
    text = re.sub(r'\b\d{17}[\dXx]\b', lambda m: m.group(0)[:6] + '********' + m.group(0)[-4:], text)
    return text


class SearchEngine:
    def __init__(self, index_dir: str = INDEX_DIR):
        self.index_dir = index_dir
        self._use_api = False
        self._api_cfg = None
        self._load()

    def _load(self):
        import faiss

        with open(os.path.join(self.index_dir, "model_info.json"), "r") as f:
            info = json.load(f)

        print(f"加载数据...")
        with open(os.path.join(self.index_dir, "data.json"), "r", encoding="utf-8") as f:
            self.data = json.load(f)

        print(f"加载 FAISS 索引...")
        self.faiss_index = faiss.read_index(os.path.join(self.index_dir, "faiss.index"))

        print(f"加载 BM25 索引...")
        with open(os.path.join(self.index_dir, "bm25.pkl"), "rb") as f:
            self.bm25 = pickle.load(f)

        # 判断是否使用 API
        self._use_api = info.get("use_api", False)
        if self._use_api:
            try:
                from api_config import load_config, is_api_configured
                if is_api_configured():
                    self._api_cfg = load_config()
                    print(f"使用 API Embedding: {self._api_cfg['embedding_model']}")
                else:
                    print("警告: 索引使用 API 构建但当前未配置 API Key，回退到本地模型")
                    self._use_api = False
            except ImportError:
                self._use_api = False

        if not self._use_api:
            print(f"加载本地向量模型: {info['model_name']}")
            from sentence_transformers import SentenceTransformer
            self.model = SentenceTransformer(info["model_name"])

        # Reranker 配置
        self._reranker_enabled = False
        try:
            from api_config import is_reranker_configured
            if is_reranker_configured():
                self._reranker_enabled = True
                print("Reranker 精排: 已启用")
        except ImportError:
            pass

        # 预计算低质量标记
        self._low_quality = set()
        for i, item in enumerate(self.data):
            if is_low_quality(item.get("problem_text", ""), item.get("solution_text", "")):
                self._low_quality.add(i)
        print(f"低质量会话过滤: {len(self._low_quality)} 条（默认隐藏）")

        print(f"就绪，共 {len(self.data)} 条索引")

    def rebuild_bm25(self):
        """词典更新后重建 BM25 索引（不重建向量索引）"""
        print("重建 BM25 索引...")
        texts = []
        for item in self.data:
            texts.append(item["problem_text"] + "\n" + item["solution_text"])
        tokenized = [list(jieba.cut(t)) for t in texts]
        self.bm25 = BM25Okapi(tokenized)
        bm25_path = os.path.join(self.index_dir, "bm25.pkl")
        with open(bm25_path, "wb") as f:
            pickle.dump(self.bm25, f)
        print(f"BM25 重建完成，共 {len(self.data)} 条")

    def _encode_query(self, query: str) -> np.ndarray:
        """将查询文本编码为向量"""
        if self._use_api and self._api_cfg:
            from api_client import call_embeddings
            vecs = call_embeddings([query], batch_size=1)
            vec = np.array(vecs[0], dtype=np.float32)
            norm = np.linalg.norm(vec)
            if norm > 0:
                vec = vec / norm
            return vec.reshape(1, -1)
        else:
            return self.model.encode(
                [query], normalize_embeddings=True, convert_to_numpy=True
            ).astype(np.float32)

    def search(self, query: str, top_k: int = 10,
               semantic_weight: float = 0.5, bm25_weight: float = 0.5,
               model_filter: str = None, error_filter: str = None,
               use_reranker: bool = True, include_low_quality: bool = False,
               agent_media_only: bool = False):
        """
        混合检索 + Reranker 精排
        """
        n = len(self.data)
        recall_n = min(top_k * 10, n) if (use_reranker and self._reranker_enabled) else min(top_k * 5, n)

        # ---------- 1. 语义检索 ----------
        query_vec = self._encode_query(query)
        sem_scores, sem_indices = self.faiss_index.search(query_vec, recall_n)
        sem_scores = sem_scores[0]
        sem_indices = sem_indices[0]
        # 防御：FAISS 索引与 data 数量不一致时，过滤掉超出范围的索引
        valid_mask = sem_indices < n
        sem_indices = sem_indices[valid_mask]
        sem_scores = sem_scores[valid_mask]

        # ---------- 2. BM25 检索（同义词扩展） ----------
        expanded_query = expand_query(query)
        tokenized_query = list(jieba.cut(expanded_query))
        bm25_scores = self.bm25.get_scores(tokenized_query)
        bm25_top = np.argsort(bm25_scores)[::-1][:recall_n]

        # ---------- 3. RRF 融合 ----------
        rrf_k = 60
        fused_scores = np.zeros(n, dtype=np.float64)

        for rank, idx in enumerate(sem_indices):
            fused_scores[idx] += semantic_weight / (rrf_k + rank + 1)
        for rank, idx in enumerate(bm25_top):
            if bm25_scores[idx] > 0:
                fused_scores[idx] += bm25_weight / (rrf_k + rank + 1)

        # 取融合后的候选集
        candidate_indices = np.where(fused_scores > 0)[0]
        candidate_indices = candidate_indices[np.argsort(fused_scores[candidate_indices])[::-1]]
        candidate_indices = candidate_indices[:recall_n]

        # ---------- 4. Reranker 精排 ----------
        rerank_scores = {}
        if use_reranker and self._reranker_enabled and len(candidate_indices) > 0:
            try:
                from api_client import call_rerank
                docs = []
                valid_candidates = []
                for idx in candidate_indices:
                    item = self.data[idx]
                    doc = item["problem_text"]
                    if item["models"]:
                        doc += "\n型号: " + " ".join(item["models"])
                    if item["error_codes"]:
                        doc += "\n错误码: " + " ".join(item["error_codes"])
                    sol = item["solution_text"][:800]
                    doc += "\n" + sol
                    docs.append(doc)
                    valid_candidates.append(idx)

                results = call_rerank(query, docs, top_n=min(recall_n, len(docs)))
                for r in results:
                    orig_idx = valid_candidates[r["index"]]
                    rerank_scores[orig_idx] = r["relevance_score"]
            except Exception as e:
                print(f"Reranker 调用失败，回退 RRF 排序: {e}")

        # ---------- 5. 组装结果 ----------
        if rerank_scores:
            sorted_indices = sorted(rerank_scores.keys(),
                                    key=lambda x: rerank_scores[x], reverse=True)
        else:
            sorted_indices = candidate_indices

        # 收集结果中出现的型号和错误码（用于前端筛选标签）
        agg_models = {}
        agg_errors = {}
        results = []
        for idx in sorted_indices:
            item = self.data[idx]
            if model_filter and model_filter.upper() not in [m.upper() for m in item["models"]]:
                continue
            if error_filter and error_filter not in item["error_codes"]:
                continue

            is_lq = idx in self._low_quality
            if is_lq and not include_low_quality:
                continue

            ms = item.get("media_summary", {})
            if agent_media_only and not ms.get("has_agent_media"):
                continue

            sem_score = 0.0
            if idx in sem_indices:
                sem_score = float(sem_scores[list(sem_indices).index(idx)])

            for m in item["models"]:
                agg_models[m] = agg_models.get(m, 0) + 1
            for e in item["error_codes"]:
                agg_errors[e] = agg_errors.get(e, 0) + 1

            results.append({
                "rank": len(results) + 1,
                "score": round(float(rerank_scores.get(idx, fused_scores[idx])), 6),
                "semantic_score": round(sem_score, 4),
                "bm25_score": round(float(bm25_scores[idx]), 4),
                "rerank_score": round(float(rerank_scores.get(idx, 0)), 4) if rerank_scores else None,
                "low_quality": is_lq,
                "conv_id": item["conv_id"],
                "channel": item["channel"],
                "start_time": item["start_time"],
                "agent_name": item["agent_name"],
                "agent_id": item["agent_id"],
                "models": item["models"],
                "error_codes": item["error_codes"],
                "media_summary": ms,
                "problem_text": mask_pii(item["problem_text"]),
                "solution_text": mask_pii(item["solution_text"]),
            })
            if len(results) >= top_k:
                break

        # 筛选标签：按频次排序
        filter_tags = {
            "models": sorted(agg_models.keys(), key=lambda x: agg_models[x], reverse=True)[:15],
            "error_codes": sorted(agg_errors.keys(), key=lambda x: agg_errors[x], reverse=True)[:10],
        }

        return results, filter_tags

    def get_conversation(self, conv_id: str):
        """按会话 ID 获取完整原始对话轮次"""
        for item in self.data:
            if item["conv_id"] == conv_id:
                turns = item.get("turns", [])
                for t in turns:
                    t["text"] = mask_pii(t["text"])
                return {
                    "conv_id": item["conv_id"],
                    "start_time": item["start_time"],
                    "agent_name": item["agent_name"],
                    "channel": item["channel"],
                    "turns": turns,
                }
        return None


if __name__ == "__main__":
    engine = SearchEngine()
    queries = [
        "洗衣机异响震动",
        "扫地机报错E1",
        "如何申请延保",
        "洗地机不出水",
    ]
    for q in queries:
        print(f"\n{'='*60}")
        print(f"查询: {q}")
        print(f"{'='*60}")
        results, _ = engine.search(q, top_k=3)
        for r in results:
            print(f"\n#{r['rank']} [score={r['score']}] 客服:{r['agent_name']} 型号:{r['models']} 错误码:{r['error_codes']}")
            print(f"  问题: {r['problem_text'][:100]}")
            print(f"  解答: {r['solution_text'][:150]}...")
