#!/usr/bin/env python3
"""
API 配置管理：读取/保存 embedding 和 reranker 的 API 配置
配置文件：api_config.json（与本脚本同目录）
"""

import json
import os
from paths import API_CONFIG_PATH as CONFIG_PATH

DEFAULT_CONFIG = {
    "embedding_api_url": "https://api.siliconflow.cn/v1/embeddings",
    "embedding_api_key": "",
    "embedding_model": "Pro/BAAI/bge-m3",
    "embedding_dimensions": 1024,
    "reranker_api_url": "https://api.siliconflow.cn/v1/rerank",
    "reranker_api_key": "",
    "reranker_model": "BAAI/bge-reranker-v2-m3",
    "reranker_top_n": 50,
    "llm_api_url": "https://api.siliconflow.cn/v1/chat/completions",
    "llm_api_key": "",
    "llm_model": "deepseek-ai/DeepSeek-V3",
    "llm_temperature": 0.3,
    "llm_max_tokens": 2048,
}


def normalize_llm_api_url(url: str) -> str:
    """Return an OpenAI-compatible chat completions endpoint.

    The Ark and other OpenAI-compatible services document a base URL (for
    example ``.../api/coding/v3``), while callers need to POST to the
    ``/chat/completions`` resource. Accept either form in the UI/config file.
    """
    normalized = (url or DEFAULT_CONFIG["llm_api_url"]).strip().rstrip("/")
    if not normalized:
        normalized = DEFAULT_CONFIG["llm_api_url"]
    if not normalized.lower().endswith("/chat/completions"):
        normalized += "/chat/completions"
    return normalized


def load_config() -> dict:
    """读取 API 配置，文件不存在则返回默认值"""
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                saved = json.load(f)
            # 合并默认值（防止新增字段缺失）
            cfg = dict(DEFAULT_CONFIG)
            cfg.update(saved)
            return cfg
        except (json.JSONDecodeError, IOError):
            pass
    return dict(DEFAULT_CONFIG)


def save_config(cfg: dict) -> dict:
    """保存 API 配置，只保留已知字段"""
    clean = {}
    for key in DEFAULT_CONFIG:
        if key in cfg:
            clean[key] = cfg[key]
    # 确保 dimensions 是 int
    if "embedding_dimensions" in clean:
        try:
            clean["embedding_dimensions"] = int(clean["embedding_dimensions"])
        except (ValueError, TypeError):
            clean["embedding_dimensions"] = DEFAULT_CONFIG["embedding_dimensions"]
    if "reranker_top_n" in clean:
        try:
            clean["reranker_top_n"] = int(clean["reranker_top_n"])
        except (ValueError, TypeError):
            clean["reranker_top_n"] = DEFAULT_CONFIG["reranker_top_n"]
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(clean, f, ensure_ascii=False, indent=2)
    return clean


def is_api_configured() -> bool:
    """是否已配置 embedding API（有 key 才算配置完成）"""
    cfg = load_config()
    return bool(cfg.get("embedding_api_key", "").strip())


def is_reranker_configured() -> bool:
    """是否已配置 reranker API"""
    cfg = load_config()
    return bool(cfg.get("reranker_api_key", "").strip())


def is_llm_configured() -> bool:
    """是否已配置 LLM API"""
    cfg = load_config()
    return bool(cfg.get("llm_api_key", "").strip())


def get_llm_key() -> str:
    """获取 LLM Key，未配置则回退到 embedding key"""
    cfg = load_config()
    return cfg.get("llm_api_key", "").strip() or cfg.get("embedding_api_key", "").strip()


if __name__ == "__main__":
    cfg = load_config()
    print(json.dumps(cfg, ensure_ascii=False, indent=2))
