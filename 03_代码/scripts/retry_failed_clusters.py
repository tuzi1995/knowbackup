#!/usr/bin/env python3
"""
补跑生成失败的聚类标题和答案。
支持增量保存和断点续跑。
"""

import sys
import os
import json
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))
from paths import RUNTIME_DIR
from search_engine import SearchEngine
from build_clusters import get_representative, generate_title_and_summary


def main():
    clusters_path = os.path.join(RUNTIME_DIR, "clusters.json")
    with open(clusters_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    engine = SearchEngine()
    raw_data = engine.data

    # 找出失败的簇
    failed = []
    for c in data["clusters"]:
        if "生成失败" in c["title"] or c["title"] == "未命名" or not c.get("answer"):
            failed.append(c)

    print(f"需要补跑: {len(failed)} 个簇")
    if not failed:
        print("全部已完成，无需补跑")
        return

    success = 0
    still_failed = 0
    for i, c in enumerate(failed):
        member_ids = set(c.get("member_ids", []))
        members = [idx for idx, item in enumerate(raw_data) if item["conv_id"] in member_ids]
        if not members:
            continue

        samples = get_representative(raw_data, members)
        title, answer = generate_title_and_summary(samples)

        if "生成失败" not in title and title != "未命名" and answer:
            c["title"] = title
            c["answer"] = answer
            success += 1
        else:
            still_failed += 1

        print(f"  [{i+1}/{len(failed)}] {c['size']}条 -> {title[:60]}")

        # 每 10 个保存一次
        if (i + 1) % 10 == 0:
            with open(clusters_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            print(f"  --- 已保存（成功 {success}, 失败 {still_failed}）---")

        time.sleep(1)

    # 最终保存
    with open(clusters_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"\n完成！成功 {success}, 仍失败 {still_failed}")


if __name__ == "__main__":
    main()
