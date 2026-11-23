#!/usr/bin/env python3
"""
回填媒体素材汇总（media_summary）到已有的解析结果 / 索引 data.json。
- 完全基于每条记录已有的 turns 现算，不重新解析 Excel、不重建向量。
- 用法: python backfill_media.py [json路径 ...]
  不传参则默认回填 parsed_conversations.json 与 index_data/data.json。
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))
from parse_conversations import build_media_summary  # noqa: E402
from paths import PARSED_CONVERSATIONS_PATH, INDEX_DIR  # noqa: E402


def backfill(path: str) -> None:
    if not os.path.exists(path):
        print(f"[跳过] 不存在: {path}")
        return
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    updated = 0
    has_agent = 0
    for item in data:
        turns = item.get("turns")
        if not turns:
            continue
        ms = item.get("media_summary")
        if not ms:
            ms = build_media_summary(turns)
            item["media_summary"] = ms
            updated += 1
        if ms.get("has_agent_media"):
            has_agent += 1

    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    os.replace(tmp, path)
    print(f"[完成] {path}")
    print(f"   共 {len(data)} 条 | 新回填 {updated} 条 | 含客服素材 {has_agent} 条 "
          f"({has_agent / max(len(data),1) * 100:.1f}%)")


if __name__ == "__main__":
    if len(sys.argv) > 1:
        targets = sys.argv[1:]
    else:
        targets = [
            PARSED_CONVERSATIONS_PATH,
            os.path.join(INDEX_DIR, "data.json"),
        ]
    for p in targets:
        backfill(p)
