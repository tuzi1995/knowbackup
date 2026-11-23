#!/usr/bin/env python3
"""
按最新口径清理已生成的素材库 media_assets.json：
- 用关键词先圈出"产品铭牌/条码标签""店铺商品/订单价格页"可疑候选
- 对候选逐张重新调 VLM（最新八类口径）复核
- 仅删除被新模型明确判为这两类的素材；网络失败/其他类型一律保留
- 被删清单写入 09_运行数据与缓存/media_removed.json 便于审计
用法: python clean_media_assets.py [并发=28] [--dry]
"""
import json
import os
import sys
from collections import Counter
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__))))
import build_media_assets as B  # noqa: E402
from paths import MEDIA_ASSETS_PATH, RUNTIME_DIR  # noqa: E402

REMOVE_TYPES = {"产品铭牌或条码标签", "店铺商品或订单价格页"}
LABEL_KW = ["条形码", "条码", "二维码", "铭牌", "制造商", "生产商", "MIT", "认证编号",
            "额定电压", "额定功率", "产品标签", "标签显示", "CCC", "3C "]
PRICE_KW = ["实付", "划线", "到手价", "券后", "售价", "¥", "￥", "优惠", "服务保障",
            "订单信息", "商品详情", "详情页", "下单", "支付", "包邮", "旗舰店", "店铺",
            "价格", "原价", "现价", "活动价", "凑单", "推荐", "配件", "促销", "赠品", "礼盒"]


def main():
    workers = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].isdigit() else 28
    dry = "--dry" in sys.argv

    with open(MEDIA_ASSETS_PATH, "r", encoding="utf-8") as f:
        assets = json.load(f)
    by_url = {a["url"]: a for a in assets}

    cand_urls, why = [], {}
    for a in assets:
        text = (a.get("desc", "") + " " + a.get("ocr", ""))
        hits = [k for k in LABEL_KW + PRICE_KW if k in text]
        if hits:
            cand_urls.append(a["url"])
            why[a["url"]] = hits
    print(f"总素材 {len(assets)}，关键词可疑候选 {len(cand_urls)}，开始 VLM 复核（并发 {workers}）...")

    results = {}
    done = 0
    with ThreadPoolExecutor(max_workers=workers) as ex:
        for rec in ex.map(B.worker, cand_urls):
            results[rec["url"]] = rec
            done += 1
            if done % 40 == 0:
                print(f"  复核 {done}/{len(cand_urls)}")

    remove, kept_other, failed = [], [], []
    new_type_counter = Counter()
    for u in cand_urls:
        rec = results.get(u, {})
        if not rec.get("ok"):
            failed.append(u)  # 网络/识别失败：保留，不误删
            continue
        t = rec.get("type", "其他")
        new_type_counter[t] += 1
        orig = by_url[u]
        item = {"url": u, "old_type": orig.get("type"), "new_type": t,
                "pii": rec.get("pii"), "old_desc": orig.get("desc"), "new_desc": rec.get("desc"),
                "kw": why.get(u)}
        if t in REMOVE_TYPES:
            remove.append(item)
        else:
            kept_other.append(item)  # 新口径下仍可入库或属其他非目标类，保留

    remove_urls = {x["url"] for x in remove}
    cleaned = [a for a in assets if a["url"] not in remove_urls]

    print("\n===== 复核结果 =====")
    print("候选新类型分布:", dict(new_type_counter))
    print(f"确认删除（两类）: {len(remove)}")
    for t in REMOVE_TYPES:
        sub = [x for x in remove if x["new_type"] == t]
        print(f"  - {t}: {len(sub)}")
        for x in sub[:5]:
            print(f"      · {x['old_desc'][:42]}")
    print(f"候选但保留: {len(kept_other)} | 复核失败保留: {len(failed)}")
    print(f"清理后素材数: {len(assets)} -> {len(cleaned)}")

    if dry:
        print("\n[--dry] 未写文件。")
        return

    out_removed = os.path.join(RUNTIME_DIR, "media_removed.json")
    with open(out_removed, "w", encoding="utf-8") as f:
        json.dump(remove, f, ensure_ascii=False, indent=2)
    with open(MEDIA_ASSETS_PATH, "w", encoding="utf-8") as f:
        json.dump(cleaned, f, ensure_ascii=False)
    print(f"\n已写回 {MEDIA_ASSETS_PATH}；删除清单 -> {out_removed}")


if __name__ == "__main__":
    main()
