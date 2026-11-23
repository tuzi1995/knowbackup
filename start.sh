#!/bin/bash
# Restored Mac environment (2026-10-09)
source "/Users/tuzi/个人项目/One/.restore/runtime.sh"
# KnowBackup - 人工客服知识库检索工具
# 启动脚本：在项目根目录运行 ./start.sh
set -e

cd "$(dirname "$0")"

if command -v uv >/dev/null 2>&1; then
    exec uv run --no-dev python 03_代码/src/web_app.py
fi

exec python3 03_代码/src/web_app.py
