#!/usr/bin/env python3
"""
Embedding & Reranker API 客户端
支持 OpenAI 兼容格式的 /embeddings 和 /rerank 接口
"""

import time
import requests
from api_config import load_config, normalize_llm_api_url


def call_embeddings(texts: list[str], batch_size: int = 32, max_retries: int = 3) -> list[list[float]]:
    """
    批量调用 embedding API，返回向量列表。
    :param texts: 待编码文本列表
    :param batch_size: 每批最大条数
    :return: list of vectors (list[float])
    """
    cfg = load_config()
    url = cfg["embedding_api_url"].rstrip("/")
    key = cfg["embedding_api_key"].strip()
    model = cfg["embedding_model"].strip()

    if not key:
        raise RuntimeError("Embedding API Key 未配置，请在网页设置中填写")

    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }

    # bge-m3 最大 8192 tokens，中文约 4000 字，截断到 2000 字保险
    MAX_CHARS = 2000
    all_embeddings = []
    total = len(texts)

    for i in range(0, total, batch_size):
        batch = [t[:MAX_CHARS] for t in texts[i:i + batch_size]]
        payload = {
            "model": model,
            "input": batch,
        }
        # dimensions 参数仅部分模型支持（如 Qwen3），bge-m3 不支持，不传
        dims = cfg.get("embedding_dimensions", 0)
        if dims and model.lower().startswith("qwen"):
            payload["dimensions"] = dims

        for attempt in range(max_retries):
            try:
                resp = requests.post(url, json=payload, headers=headers, timeout=120)
                if resp.status_code != 200:
                    raise RuntimeError(f"HTTP {resp.status_code}: {resp.text[:200]}")
                data = resp.json()
                items = sorted(data["data"], key=lambda x: x.get("index", 0))
                all_embeddings.extend([item["embedding"] for item in items])
                done = min(i + batch_size, total)
                print(f"  Embedding 进度: {done}/{total}")
                break
            except Exception as e:
                if attempt < max_retries - 1:
                    wait = 2 ** attempt
                    print(f"  Embedding 请求失败({e})，{wait}秒后重试...")
                    time.sleep(wait)
                else:
                    raise RuntimeError(f"Embedding API 调用失败: {e}") from e

    return all_embeddings


def call_rerank(query: str, documents: list[str], top_n: int = None) -> list[dict]:
    """
    调用 reranker API 对候选文档精排。
    :param query: 查询文本
    :param documents: 候选文档列表
    :param top_n: 返回前 N 条（默认用配置中的 reranker_top_n）
    :return: [{"index": int, "relevance_score": float}, ...] 按分数降序
    """
    cfg = load_config()
    url = cfg["reranker_api_url"].rstrip("/")
    key = cfg["reranker_api_key"].strip()
    model = cfg["reranker_model"].strip()

    if not key:
        raise RuntimeError("Reranker API Key 未配置，请在网页设置中填写")

    if top_n is None:
        top_n = cfg.get("reranker_top_n", 50)
    top_n = min(top_n, len(documents))

    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model,
        "query": query,
        "documents": documents,
        "top_n": top_n,
        "return_documents": False,
    }

    for attempt in range(3):
        try:
            resp = requests.post(url, json=payload, headers=headers, timeout=60)
            resp.raise_for_status()
            data = resp.json()
            results = data.get("results", [])
            return sorted(
                [{"index": int(r["index"]), "relevance_score": float(r["relevance_score"])}
                 for r in results],
                key=lambda x: x["relevance_score"],
                reverse=True,
            )
        except Exception as e:
            if attempt < 2:
                time.sleep(2 ** attempt)
            else:
                raise RuntimeError(f"Reranker API 调用失败: {e}") from e


def get_embedding_dim() -> int:
    """获取配置的向量维度"""
    return load_config().get("embedding_dimensions", 1024)


def call_llm(messages: list[dict], max_tokens: int = None, temperature: float = None) -> str:
    """
    调用 LLM Chat Completions API（OpenAI 兼容格式）。
    :param messages: [{"role": "system/user", "content": "..."}]
    :return: 模型回复文本
    """
    cfg = load_config()
    url = normalize_llm_api_url(cfg.get("llm_api_url"))
    key = cfg.get("llm_api_key", "").strip() or cfg.get("embedding_api_key", "").strip()
    model = cfg.get("llm_model", "deepseek-ai/DeepSeek-V3").strip()

    if not key:
        raise RuntimeError("LLM API Key 未配置，请在网页 AI 设置中填写")

    if max_tokens is None:
        max_tokens = cfg.get("llm_max_tokens", 2048)
    if temperature is None:
        temperature = cfg.get("llm_temperature", 0.3)

    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }

    for attempt in range(3):
        try:
            resp = requests.post(url, json=payload, headers=headers, timeout=120)
            resp.raise_for_status()
            data = resp.json()
            return data["choices"][0]["message"]["content"].strip()
        except Exception as e:
            if attempt < 2:
                time.sleep(2 ** attempt)
            else:
                raise RuntimeError(f"LLM API 调用失败: {e}") from e
