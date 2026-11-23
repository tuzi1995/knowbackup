#!/usr/bin/env python3
"""
项目统一路径定义。
所有模块通过本文件获取项目内各目录的绝对路径，避免文件移动后路径失效。
"""

import os

# 项目根目录：knowbackup/
PROJECT_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)

# 数据
DATA_DIR = os.path.join(PROJECT_ROOT, "02_数据")
PROCESSED_DATA_DIR = os.path.join(DATA_DIR, "processed")
PARSED_CONVERSATIONS_PATH = os.path.join(PROCESSED_DATA_DIR, "parsed_conversations.json")
# 智能客服（转人工前）问答数据
PARSED_AI_PATH = os.path.join(PROCESSED_DATA_DIR, "parsed_ai_qa.json")
# 客服图片素材库（VLM 理解后的可入库图片，关联来源会话）
MEDIA_ASSETS_PATH = os.path.join(PROCESSED_DATA_DIR, "media_assets.json")

# 代码
SRC_DIR = os.path.join(PROJECT_ROOT, "03_代码", "src")
SCRIPTS_DIR = os.path.join(PROJECT_ROOT, "03_代码", "scripts")

# 配置
CONFIG_DIR = os.path.join(PROJECT_ROOT, "05_配置与环境")
API_CONFIG_PATH = os.path.join(CONFIG_DIR, "api_config.json")
CUSTOM_DICT_PATH = os.path.join(CONFIG_DIR, "custom_dict.json")

# 文档
DOCS_DIR = os.path.join(PROJECT_ROOT, "06_文档与报告")

# 运行数据与缓存
RUNTIME_DIR = os.path.join(PROJECT_ROOT, "09_运行数据与缓存")
INDEX_DIR = os.path.join(RUNTIME_DIR, "index_data")
# 智能客服问答索引（独立于人工会话索引）
AI_INDEX_DIR = os.path.join(RUNTIME_DIR, "ai_index_data")
