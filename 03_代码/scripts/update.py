#!/usr/bin/env python3
"""
每周更新脚本：用最新一周的 Excel 文件重建索引。
用法：python3 update.py <新一周的xlsx文件路径>

示例：
  python3 update.py "/Volumes/ORICO/会话记录/每周会话/会话记录_8010331_8228500346949875530.xlsx"

执行后：
  1. 解析新文件 → parsed_conversations.json
  2. 重建 FAISS + BM25 索引 → index_data/
  3. 重启网页服务即可看到新数据
"""

import sys
import os

# 将 src 目录加入导入路径
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))
from human_import_pipeline import rebuild_human_index


def main():
    if len(sys.argv) < 2:
        print("用法: python3 update.py <xlsx文件路径>")
        print('示例: python3 update.py "/Volumes/ORICO/会话记录/每周会话/会话记录_xxx.xlsx"')
        sys.exit(1)

    xlsx_path = sys.argv[1]
    if not os.path.exists(xlsx_path):
        print(f"文件不存在: {xlsx_path}")
        sys.exit(1)

    rebuild_human_index(xlsx_path, progress_cb=lambda msg, pct: print(msg))

    print("\n" + "=" * 50)
    print("更新完成！重启网页服务生效：")
    print("  1. 关闭当前运行的网页窗口（或 Ctrl+C 停止服务）")
    print("  2. 重新运行: python3 03_代码/src/web_app.py")
    print("=" * 50)


if __name__ == "__main__":
    main()
