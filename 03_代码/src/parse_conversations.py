#!/usr/bin/env python3
"""
解析人工客服会话 Excel，输出结构化 JSON。
每条索引 = 一次完整的问题解决过程：
  - problem_text: 用户所有发言拼接（问题描述+型号+错误码），用于检索
  - solution_text: 客服完整解答链路，按时间顺序，用于展示
"""

import openpyxl
import re
import json
import sys
import os

# ---------- 角色解析 ----------

ROLE_PATTERN = re.compile(
    r'^(.+?)\s+(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2})\s*$',
    re.MULTILINE
)

def classify_role(role: str) -> str:
    role = role.strip()
    if role == "机器人":
        return "bot"
    if role == "系统":
        return "system"
    if role == "访客" or role.startswith("访客(") or role.startswith("访客（"):
        return "visitor"
    if role == "坐席" or role.startswith("坐席(") or role.startswith("坐席（"):
        return "agent"
    if re.search(r'[（(]\d{3,5}[）)]', role):
        return "agent"
    return "other"

def extract_agent_info(role: str):
    """从客服角色名提取工号和姓名，如 '邯郸-李国亮(4052)' -> ('4052', '邯郸-李国亮')"""
    m = re.search(r'[（(](\d{3,5})[）)]\s*$', role.strip())
    if m:
        agent_id = m.group(1)
        name = role[:m.start()].strip()
        # 去掉团队前缀中的括号部分，如 "马平(成都扫地机-9155)" -> "马平"
        name = re.sub(r'[（(].*?[）)]', '', name).strip().rstrip('-').strip()
        return agent_id, name
    return None, role.strip()

# ---------- 文本清洗 ----------

def clean_text(text: str):
    """清洗文本，返回 (清洗后文本, 媒体URL列表)
    - HTML 标签去除
    - 图片/视频 URL 替换为 [图片]/[视频] 标记，URL 保留在 media 列表中
    - 图片 JSON 替换为 [图片]
    """
    media = []
    # Extract link targets before stripping HTML tags.
    text = re.sub(r'<(?:img|video)\b[^>]*?src=[\"\']([^\"\']+)[\"\'][^>]*>',
                  lambda m: m.group(1), text, flags=re.I)
    text = re.sub(r'<a\b[^>]*?href=[\"\']([^\"\']+)[\"\'][^>]*>(.*?)</a>',
                  lambda m: m.group(2) + "\n" + m.group(1), text, flags=re.I | re.S)
    # 去除 HTML 标签
    text = re.sub(r'<[^>]+>', '', text)
    # 图片/视频 JSON: {"image.jpg":"8010331_...jpg"}
    def _json_repl(m):
        media.append(m.group(0))
        return '[图片]'
    text = re.sub(
        r'\{["\']?[\w.-]+\.(?:jpg|jpeg|png|gif|mov|mp4|wav|amr)["\']?\s*:\s*["\'][^"\']+["\']\}',
        _json_repl, text
    )
    # 图片/视频 URL 替换为标记
    def _url_repl(m):
        url = m.group(0)
        media.append(url)
        kind = _media_kind(url)
        return {"video": "[视频]", "audio": "[语音]", "image": "[图片]"}.get(kind, "[链接]")
    # Retain signed links, attachments and resources without recognizable extensions.
    text = re.sub(r'https?://[^\s<>\"\']+', _url_repl, text)
    media = list(dict.fromkeys(media))
    # 去除满意度评价结果行
    text = re.sub(r'\[满意度评价结果\]', '', text)
    # 合并多余空白
    text = re.sub(r'[ \t]+', ' ', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip(), media

# ---------- 客套话过滤 ----------

BOILERPLATE_PATTERNS = [
    r'^(您好|你好|哈喽)[，。！!~～]*$',
    r'^(好的|好|嗯|嗯嗯|哦哦|收到|ok|OK|行|可以)[，。！!~～.。]*$',
    r'^(辛苦您?|麻烦您?|请稍等|稍等|您稍等)[，。！!~～]*$',
    r'^(感谢|谢谢|多谢|不客气|应该的)[，。！!~～]*$',
    r'^(抱歉|对不起|不好意思)[，。！!~～]*$',
    r'^请问还有其他.*[嘛吗呢]?[~～]*$',
    r'^后续有任何问题.*$',
    r'^祝您生活愉快.*$',
    r'^您客气了.*$',
    r'^工号\d+客服为您服务.*$',
    r'^访客接入座席.*$',
    r'^请对我本次服务.*$',
    r'^您好，长时间未收到您的回复.*$',
    r'^系统超时关闭会话.*$',
    r'^座席.*关闭会话.*$',
    r'^这边就先关闭对话.*$',
    r'^为您服务，请描述您现在遇到的问题.*$',
    r'^您好，可以简单描述下您的问题.*$',
    r'^正在为您转接.*$',
    r'^访客触发转人工服务.*$',
    # 标准开场/流程话术
    r'^您好，?麻烦提供.*(机型|SN码?|型号).*$',
    r'^您好，?麻烦提供.*(机器型号|具体机型).*$',
    r'^辛苦您?提供.*(机型|SN码?|型号|订单截图).*$',
    r'^机器(是有)?什么使用问题.*$',
    r'^机器型号是什么.*$',
    r'^您(稍等|先稍等).*$',
    r'^小客服正在.*核查.*$',
    r'^您好，?请您稍等.*$',
    r'^辛苦您先试一下.*$',
    r'^辛苦核对下?哦?[。！!~～]*$',
    r'^好的 您稍等.*$',
    r'^您的预约已提交.*$',
    r'^辛苦您(一并|一起)寄回.*$',
    r'^收到[，。！!~～]*$',
]

BOILERPLATE_RE = re.compile('|'.join(BOILERPLATE_PATTERNS))

def is_boilerplate(text: str) -> bool:
    t = text.strip()
    if not t:
        return True
    if len(t) <= 4:
        return True
    return bool(BOILERPLATE_RE.match(t))

# ---------- 型号/错误码提取 ----------

# 石头科技产品型号：产品系列字母 + 数字，可选 S，可选 1~2 个已知后缀
_MODEL_SUFFIX = r'(?:Ultra|Pro|Plus|MAX|Max|Combo|Steam|Pure|Air|Lite|SE|Neo|CE)'
MODEL_RE = re.compile(
    r'\b([GPAQSTVCBFHMZ]\d{1,2}[Ss]?(?:\s?' + _MODEL_SUFFIX + r'){0,2})\b',
    re.IGNORECASE
)
# Q Revo 特殊型号
Q_REVO_RE = re.compile(r'\bQ\s?Revo\b', re.IGNORECASE)

# 非型号黑名单（技术术语等）
MODEL_BLACKLIST = {"4G", "5G", "3D", "3C", "2D", "P2P", "2K", "4K", "APP"}

def extract_models(text: str):
    models = set()
    for m in MODEL_RE.findall(text):
        clean = re.sub(r'\s+', '', m).upper()
        if clean not in MODEL_BLACKLIST and len(clean) >= 2:
            models.add(clean)
    for _ in Q_REVO_RE.findall(text):
        models.add("Q Revo")
    return list(models)

# 错误码模式：E1/E02（E前缀），中文"错误7""报错3"（1~3位数字）
# 注意：H1/H50 等是吸尘器/洗衣机型号，不作为错误码
ERROR_CODE_RE = re.compile(r'\bE\d{1,2}\b|错误\s?(\d{1,3})|报错\s?(\d{1,3})', re.IGNORECASE)

def extract_error_codes(text: str):
    codes = set()
    for m in ERROR_CODE_RE.finditer(text):
        if m.group(1):
            codes.add(f"错误{m.group(1)}")
        elif m.group(2):
            codes.add(f"错误{m.group(2)}")
        else:
            codes.add(m.group(0).upper())
    return list(codes)

# ---------- 媒体素材汇总 ----------

_IMG_EXT = ("jpg", "jpeg", "png", "gif", "webp", "bmp", "heic")
_VIDEO_EXT = ("mp4", "mov", "avi", "mkv", "m4v")
_AUDIO_EXT = ("wav", "amr", "mp3", "m4a")

def _media_kind(url: str) -> str:
    """根据 URL 后缀判断媒体类型：image / video /audio / other"""
    path = url.split("?")[0].lower()
    ext = path.rsplit(".", 1)[-1] if "." in path.rsplit("/", 1)[-1] else ""
    if ext in _IMG_EXT:
        return "image"
    if ext in _VIDEO_EXT:
        return "video"
    if ext in _AUDIO_EXT:
        return "audio"
    # JSON 形式 {"xxx.jpg": "..."}
    m = re.search(r'\.(jpg|jpeg|png|gif|webp|mp4|mov|wav|amr)\b', path)
    if m:
        e = m.group(1)
        if e in _IMG_EXT:
            return "image"
        if e in _VIDEO_EXT:
            return "video"
        return "audio"
    return "other"

def build_media_summary(turns: list[dict]) -> dict:
    """从完整轮次中统计客服/用户发送的图片、视频数量（不存二进制，只计数）。
    turns: [{"role","time","text","media":[url...]}, ...]
    """
    cat = {
        "agent_img": 0, "agent_video": 0, "agent_audio": 0,
        "visitor_img": 0, "visitor_video": 0, "visitor_audio": 0,
    }
    for t in turns:
        role = t.get("role")
        if role not in ("agent", "visitor"):
            continue
        for u in (t.get("media") or []):
            kind = _media_kind(u)
            if kind == "image":
                cat[f"{role}_img"] += 1
            elif kind == "video":
                cat[f"{role}_video"] += 1
            elif kind == "audio":
                cat[f"{role}_audio"] += 1
    agent_total = cat["agent_img"] + cat["agent_video"] + cat["agent_audio"]
    visitor_total = cat["visitor_img"] + cat["visitor_video"] + cat["visitor_audio"]
    return {
        "has_agent_media": agent_total > 0,
        "agent_img": cat["agent_img"],
        "agent_video": cat["agent_video"],
        "agent_audio": cat["agent_audio"],
        "agent_total": agent_total,
        "visitor_img": cat["visitor_img"],
        "visitor_video": cat["visitor_video"],
        "visitor_total": visitor_total,
        "total": agent_total + visitor_total,
    }

# ---------- 会话解析 ----------

def _normalize(text):
    """去除空白和标点，用于重复比较"""
    return re.sub(r"[\]\[\s，。！？、；：""''（）()【】.~～!?,;:·\-—…]", '', text)

def _is_duplicate(a, b):
    """判断两条客服消息是否高度重复（连续发送的相同内容）"""
    na, nb = _normalize(a), _normalize(b)
    if not na or not nb:
        return False
    # 完全相同
    if na == nb:
        return True
    # 较短的是较长的子串，且长度接近
    shorter, longer = (na, nb) if len(na) <= len(nb) else (nb, na)
    if len(shorter) >= 10 and shorter in longer and len(shorter) / len(longer) > 0.85:
        return True
    # 字符级 Jaccard 相似度 > 0.9
    sa, sb = set(na), set(nb)
    if sa and sb and len(sa & sb) / len(sa | sb) > 0.9:
        return True
    return False

def parse_turns(content: str):
    """把聊天内容解析成 [(role_raw, role_type, timestamp, text), ...]"""
    matches = list(ROLE_PATTERN.finditer(content))
    turns = []
    for idx, m in enumerate(matches):
        role_raw = m.group(1).strip()
        ts = m.group(2)
        start = m.end()
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(content)
        raw_text = content[start:end].strip()
        text, media = clean_text(raw_text)
        role_type = classify_role(role_raw)
        turns.append((role_raw, role_type, ts, text, media))
    return turns

def parse_conversation(row):
    """解析一行会话，返回结构化索引条目，无价值则返回 None"""
    conv_id = str(row[0]) if row[0] else ""
    channel = str(row[1]) if row[1] else ""
    start_time = str(row[2]) if row[2] else ""
    end_time = str(row[3]) if row[3] else ""
    transfer = str(row[4]) if row[4] else ""
    extra = str(row[5]) if row[5] else ""
    content = str(row[6]) if row[6] else ""

    if not content or len(content.strip()) < 20:
        return None

    turns = parse_turns(content)

    # 必须有人工客服
    agent_turns = [(r, rt, ts, t, m) for r, rt, ts, t, m in turns if rt == "agent"]
    if not agent_turns:
        return None

    # 提取客服信息
    agent_id, agent_name = extract_agent_info(agent_turns[0][0])

    # 收集访客发言（过滤客套话和纯图片）
    visitor_msgs = []
    for r, rt, ts, t, m in turns:
        if rt == "visitor" and t and not is_boilerplate(t):
            visitor_msgs.append(t)

    if not visitor_msgs:
        return None

    # 收集客服实质性解答（过滤客套话 + 连续重复去重）
    solution_parts = []
    for r, rt, ts, t, m in turns:
        if rt == "agent" and t and not is_boilerplate(t):
            # 与上一条客服解答比较，高度重复则跳过
            if solution_parts and _is_duplicate(t, solution_parts[-1]):
                continue
            solution_parts.append(t)

    if not solution_parts:
        return None

    # 组装问题文本（用户所有发言拼接）
    problem_text = "\n".join(visitor_msgs)

    # 组装解决过程（客服解答按顺序拼接，保留时间线）
    solution_text = "\n---\n".join(solution_parts)

    # 提取型号和错误码（从用户和客服全文中提取）
    full_text = problem_text + "\n" + solution_text
    models = extract_models(full_text)
    error_codes = extract_error_codes(full_text)

    # 如果问题文本太短（少于5个有效字符），跳过
    if len(re.sub(r'\s', '', problem_text)) < 5:
        return None

    # 完整对话轮次（用于"查看原始对话"）
    all_turns = []
    for r, rt, ts, t, m in turns:
        if rt in ("visitor", "agent", "bot", "system") and t:
            all_turns.append({"role": rt, "time": ts, "text": t, "media": m})

    # 媒体素材汇总（客服发送的操作图/视频等，用于筛选与徽标）
    media_summary = build_media_summary(all_turns)

    return {
        "conv_id": conv_id,
        "channel": channel,
        "start_time": start_time,
        "end_time": end_time,
        "transfer": transfer,
        "agent_id": agent_id,
        "agent_name": agent_name,
        "problem_text": problem_text,
        "solution_text": solution_text,
        "models": models,
        "error_codes": error_codes,
        "visitor_msg_count": len(visitor_msgs),
        "agent_msg_count": len(solution_parts),
        "media_summary": media_summary,
        "turns": all_turns,
    }


def process_file(filepath: str, output_path: str, max_rows: int = None, progress_cb=None):
    def log(msg, pct=None):
        print(msg)
        if progress_cb:
            progress_cb(msg, pct)

    log(f"读取文件: {filepath}", 1)
    wb = openpyxl.load_workbook(filepath, read_only=True, data_only=True)
    expected = ["会话id", "来源渠道", "会话开始时间", "会话结束时间", "是否转人工", "拓展信息", "聊天内容"]
    target_sheets = []
    for ws in wb.worksheets:
        headers = [str(v).strip().lower() if v is not None else ""
                   for v in next(ws.iter_rows(min_row=1, max_row=1, values_only=True), ())]
        if set(expected).issubset(headers):
            target_sheets.append(ws)
    if not target_sheets:
        wb.close()
        from conversation_converter import detect_workbook_format, convert_detail_workbook
        if detect_workbook_format(filepath) == "detail":
            import tempfile
            with tempfile.TemporaryDirectory() as tmp:
                converted_path = os.path.join(tmp, "会话记录.xlsx")
                convert_detail_workbook(filepath, converted_path)
                return process_file(converted_path, output_path, max_rows, progress_cb)
        raise ValueError("未识别到会话记录表，需包含完整七列表头：" + "、".join(expected))

    results = []
    total = 0
    skipped_no_agent = 0
    skipped_no_visitor = 0
    skipped_no_solution = 0
    split_groups = {}

    def parse_and_collect(normalized_row):
        nonlocal skipped_no_agent, skipped_no_visitor, skipped_no_solution
        item = parse_conversation(normalized_row)
        if item is not None:
            results.append(item)
            return
        content = str(normalized_row[6]) if normalized_row[6] else ""
        turns = parse_turns(content) if content else []
        has_agent = any(rt == "agent" for _, rt, _, _, _ in turns)
        if not has_agent:
            skipped_no_agent += 1
        elif not any(rt == "visitor" and t and not is_boilerplate(t) for _, rt, _, t, _ in turns):
            skipped_no_visitor += 1
        else:
            skipped_no_solution += 1

    for ws in target_sheets:
        headers = [str(v).strip().lower() if v is not None else ""
                   for v in next(ws.iter_rows(min_row=1, max_row=1, values_only=True), ())]
        header_idx = {name: i for i, name in enumerate(headers) if name}
        indexes = [header_idx[name] for name in expected]
        for i, row in enumerate(ws.iter_rows(min_row=2, values_only=True)):
            if max_rows and total >= max_rows:
                break
            normalized_row = tuple(row[j] if j < len(row) else None for j in indexes)
            if all(v is None or not str(v).strip() for v in normalized_row):
                continue
            total += 1
            extra = str(normalized_row[5]) if normalized_row[5] else ""
            original_match = re.search(r"(?:^|\n)原会话ID=(.*?)(?:\n|$)", extra)
            part_match = re.search(r"(?:^|\n)分段=(\d+)/(\d+)(?:\n|$)", extra)
            if original_match and part_match:
                original_id = original_match.group(1)
                split_groups.setdefault(original_id, []).append(
                    (int(part_match.group(1)), int(part_match.group(2)), normalized_row)
                )
            else:
                parse_and_collect(normalized_row)
            if total % 5000 == 0:
                log(f"  已解析 {total} 行...", None)

    wb.close()

    for original_id, parts in split_groups.items():
        parts.sort(key=lambda part: part[0])
        first, last = parts[0][2], parts[-1][2]
        merged_row = (
            original_id, first[1], first[2], last[3], first[4], last[5],
            "".join(str(part[2][6] or "") for part in parts),
        )
        parse_and_collect(merged_row)

    log(f"解析完成: 总{total}条, 有效{len(results)}条, 跳过{skipped_no_agent + skipped_no_visitor + skipped_no_solution}条", 80)

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    log(f"  已保存: {output_path}", 85)

    return results


if __name__ == "__main__":
    filepath = sys.argv[1] if len(sys.argv) > 1 else \
        "/Volumes/ORICO/会话记录/每周会话/会话记录_8010331_8228500346949875530.xlsx"
    from paths import PARSED_CONVERSATIONS_PATH
    output = sys.argv[2] if len(sys.argv) > 2 else PARSED_CONVERSATIONS_PATH
    process_file(filepath, output)
