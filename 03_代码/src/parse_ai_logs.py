#!/usr/bin/env python3
"""
智能客服（转人工前）问答日志解析。
与人工会话不同：每一行 = 一个用户问题 + 一条大模型答案，同一「用户会话ID」表示同一轮会话。
输出结构化 JSON，供 build_ai_index.py 构建检索索引。
"""

import os
import sys
import json
import datetime
import openpyxl

# 列名 -> 列序号（按导出表头固定位置；解析时按下标取，不依赖表头文字）
COL = {
    "date": 0, "row_id": 1, "user_id": 2, "session_id": 3, "qid": 4,
    "source": 5, "channel": 6, "svc_ver": 7, "device_list": 8,
    "product_category": 9, "product": 10, "question": 11, "rewrite": 12,
    "is_product_service": 13, "is_recall": 14, "answer": 15, "is_relevant": 16,
    "kb_count": 17, "kb1": 18, "matched_qid": 23, "recall_links": 24,
    "adopted_kb": 25, "qtype": 26, "llm": 27, "eff_recall": 28,
    "eff_annotation": 29, "eff_kb_count": 30, "vote": 32, "vote_reason": 33,
    "cat1": 34, "cat2": 35, "cat3": 36, "to_human": 37, "is_bm25": 41,
}

# 默认隐藏的 query 类型（无实质知识问答）
HIDDEN_QTYPES = {"transfer", "pet_photo"}


def _s(row, key):
    """安全取单元格为去空白字符串"""
    idx = COL[key]
    if idx >= len(row):
        return ""
    v = row[idx]
    if v is None:
        return ""
    if isinstance(v, (datetime.datetime, datetime.date)):
        return v.strftime("%Y-%m-%d %H:%M:%S") if isinstance(v, datetime.datetime) else v.strftime("%Y-%m-%d")
    return str(v).strip()


def _parse_list(raw):
    """把 '["a","b"]' 解析成 list，失败返回 []"""
    raw = (raw or "").strip()
    if not raw:
        return []
    try:
        v = json.loads(raw)
        return v if isinstance(v, list) else [str(v)]
    except Exception:
        return [x.strip() for x in raw.strip("[]").replace('"', '').split(",") if x.strip()]


def parse_row(row):
    """解析一行问答；无有效问题返回 None"""
    question = _s(row, "question")
    if not question or len(question) < 1:
        return None

    qtype = _s(row, "qtype").lower()
    answer = _s(row, "answer")
    hidden = qtype in HIDDEN_QTYPES

    def short(key, limit=800):
        t = _s(row, key)
        return t[:limit]

    adopted = _parse_list(_s(row, "adopted_kb"))

    return {
        # 标识
        "qid": _s(row, "qid") or _s(row, "row_id"),
        "row_id": _s(row, "row_id"),
        "session_id": _s(row, "session_id"),
        "date": _s(row, "date"),
        # 来源/产品
        "source": _s(row, "source"),
        "channel": _s(row, "channel"),
        "svc_ver": _s(row, "svc_ver"),
        "device_list": _s(row, "device_list"),
        "product_category": _s(row, "product_category"),
        "product": _s(row, "product"),
        # 问答主体
        "question": question,
        "rewrite": _s(row, "rewrite"),
        "answer": answer,
        # 召回/质量
        "qtype": qtype,
        "llm": _s(row, "llm"),
        "is_product_service": _s(row, "is_product_service"),
        "is_recall": _s(row, "is_recall"),
        "is_relevant": _s(row, "is_relevant"),
        "kb_count": _s(row, "kb_count"),
        "kb1": short("kb1", 800),
        "matched_qid": _s(row, "matched_qid"),
        "adopted_kb": adopted,
        "eff_recall": _s(row, "eff_recall"),
        "eff_annotation": short("eff_annotation", 800),
        "eff_kb_count": _s(row, "eff_kb_count"),
        "vote": _s(row, "vote"),
        "vote_reason": _s(row, "vote_reason"),
        # 分类/转人工
        "cat1": _s(row, "cat1"),
        "cat2": _s(row, "cat2"),
        "cat3": _s(row, "cat3"),
        "to_human": _s(row, "to_human"),
        "is_bm25": _s(row, "is_bm25"),
        # 检索控制
        "hidden": hidden,
    }


def process_file(filepath: str, output_path: str, max_rows: int = None, progress_cb=None):
    def log(msg, pct=None):
        print(msg)
        if progress_cb:
            progress_cb(msg, pct)

    log(f"读取智能客服文件: {filepath}", 1)
    wb = openpyxl.load_workbook(filepath, read_only=True, data_only=True)
    ws = wb["Sheet1"] if "Sheet1" in wb.sheetnames else wb[wb.sheetnames[0]]

    results = []
    total = 0
    skip_empty = 0
    hidden_count = 0
    qtype_counter = {}

    for i, row in enumerate(ws.iter_rows(min_row=2, values_only=True)):
        if max_rows and i >= max_rows:
            break
        total += 1
        item = parse_row(row)
        if item is None:
            skip_empty += 1
            continue
        if item["hidden"]:
            hidden_count += 1
        qtype_counter[item["qtype"] or "(空)"] = qtype_counter.get(item["qtype"] or "(空)", 0) + 1
        results.append(item)
        if total % 10000 == 0:
            log(f"  已解析 {total} 行...", None)

    wb.close()

    log(f"解析完成: 总{total}行, 有效问答{len(results)}条 "
        f"(默认隐藏{hidden_count}条 transfer/pet_photo, 跳过空问题{skip_empty}条)", 80)
    log("  类型分布: " + ", ".join(f"{k}:{v}" for k, v in
        sorted(qtype_counter.items(), key=lambda x: -x[1])[:6]))

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False)
    log(f"  已保存: {output_path}", 85)
    return results


if __name__ == "__main__":
    from paths import PARSED_AI_PATH
    fp = sys.argv[1] if len(sys.argv) > 1 else "/Users/guoying/Downloads/近一周会话数据.xlsx"
    out = sys.argv[2] if len(sys.argv) > 2 else PARSED_AI_PATH
    process_file(fp, out)
