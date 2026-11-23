#!/usr/bin/env python3
"""Convert one-message-per-row customer service workbooks to session rows."""

import os
import re
import html
from collections import OrderedDict
from datetime import date, datetime

import openpyxl
from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side


MEDIA_COLS = ("图片", "视频", "附件", "语音")
PLACEHOLDERS = {
    "图片", "视频", "图文", "语音", "附件", "文件", "照片", "动图", "表情",
    "[图片]", "[视频]",
}
DETAIL_REQUIRED = {"会话id", "消息内容", "消息发送者", "创建时间"}
SESSION_HEADERS = [
    "会话ID", "来源渠道", "会话开始时间", "会话结束时间",
    "是否转人工", "拓展信息", "聊天内容",
]
EXCEL_CELL_LIMIT = 32767
CHAT_SEPARATOR = "\n\n"


def _excel_text_length(value):
    return len(value.encode("utf-16-le")) // 2


def _split_message(message):
    """Return rendered message blocks that each fit in an Excel chat cell."""
    prefix = f"{message['name']} {message['time']}"
    body = message["body"]
    available = EXCEL_CELL_LIMIT - _excel_text_length(prefix + "\n") - _excel_text_length(CHAT_SEPARATOR)
    if available < 1 and body:
        raise ValueError("消息发送者或时间字段过长，无法放入 Excel 单元格")
    if not body:
        return [(prefix, message)]

    pieces = []
    start = 0
    while start < len(body):
        end, units = start, 0
        while end < len(body):
            char_units = 2 if ord(body[end]) > 0xFFFF else 1
            if units + char_units > available:
                break
            units += char_units
            end += 1
        if end == start:
            raise ValueError("单条消息无法安全拆分到 Excel 单元格")
        pieces.append((prefix + "\n" + body[start:end], message))
        start = end
    return pieces


def _chunk_messages(messages):
    chunks, current, current_length = [], [], 0
    for message in messages:
        for block, source_message in _split_message(message):
            block_length = _excel_text_length(block)
            added_length = block_length + _excel_text_length(CHAT_SEPARATOR)
            if current and current_length + added_length > EXCEL_CELL_LIMIT:
                chunks.append(current)
                current, current_length = [], 0
            if added_length > EXCEL_CELL_LIMIT:
                raise ValueError("单条消息超过 Excel 单元格的 32767 字符限制，无法拆分")
            current.append((block, source_message))
            current_length += added_length
    if current:
        chunks.append(current)
    return chunks


def _text(value):
    if value is None:
        return ""
    if isinstance(value, (datetime, date)):
        return value.strftime("%Y-%m-%d %H:%M:%S")
    return str(value).strip()


def _extract_inline_media(content, stats):
    urls = []

    def replace_tag(match, kind):
        src = re.search(r"src=[\"']?([^\"'\s>]+)", match.group(0), re.I)
        if src and src.group(1).lower().startswith(("http://", "https://")):
            urls.append(html.unescape(src.group(1)))
            stats["inline_video" if kind == "video" else "inline_img"] += 1
            return html.unescape(src.group(1))
        if kind == "video":
            stats["inline_video_nohttp"] += 1
            return "[视频]"
        stats["emoji"] += 1
        return "[表情]"

    content = re.sub(
        r"<video\b[^>]*>.*?</video\s*>",
        lambda m: replace_tag(m, "video"), content, flags=re.I | re.S,
    )
    content = re.sub(
        r"<img\b[^>]*>", lambda m: replace_tag(m, "img"), content, flags=re.I,
    )
    return content.strip(), urls


def _build_body(content, media_urls, stats):
    raw = _text(content)
    text, inline_urls = _extract_inline_media(raw, stats)
    urls = list(dict.fromkeys(u for u in inline_urls + media_urls if u))

    if not raw:
        if urls:
            stats["empty_content_media"] += 1
        else:
            stats["empty_msg"] += 1
        return "\n".join(urls)
    if raw in PLACEHOLDERS:
        if urls:
            stats["placeholder_media"] += 1
            return "\n".join(urls)
        return raw
    if urls:
        stats["text_media"] += 1
        appended = [u for u in urls if u not in text]
        return text + ("\n" + "\n".join(appended) if appended else "")
    return text


def _speaker_name(sender, nickname):
    sender, nickname = _text(sender), _text(nickname)
    if sender in ("坐席", "访客"):
        return f"{sender}({nickname})" if nickname else sender
    return f"{sender}({nickname})" if sender and nickname else (sender or "未知")


def _detail_sheets(workbook):
    matches = []
    for ws in workbook.worksheets:
        headers = [_text(v) for v in next(ws.iter_rows(min_row=1, max_row=1, values_only=True), ())]
        positions = {name: idx for idx, name in enumerate(headers) if name}
        if "会话ID" in positions:
            positions["会话id"] = positions["会话ID"]
        if DETAIL_REQUIRED.issubset(positions):
            matches.append((ws, positions))
    return matches


def convert_detail_workbook(input_path, output_path):
    """Convert detail sheets and return validation/processing counters."""
    wb = openpyxl.load_workbook(input_path, read_only=True, data_only=True)
    sheets = _detail_sheets(wb)
    if not sheets:
        wb.close()
        raise ValueError("未识别到逐句明细表，至少需要会话id、消息内容、消息发送者、创建时间列")

    sessions = OrderedDict()
    stats = {
        "sheet_count": len(sheets), "message_count": 0, "session_count": 0,
        "missing_session_id": 0, "duplicate_session_ids_across_sheets": 0,
        "empty_content_media": 0, "placeholder_media": 0, "text_media": 0,
        "inline_img": 0, "inline_video": 0, "inline_video_nohttp": 0,
        "emoji": 0, "empty_msg": 0, "truncated_sessions": 0,
        "split_sessions": 0, "split_parts": 0, "output_row_count": 0,
    }
    session_sheets = {}
    duplicate_session_ids = set()
    sequence = 0

    try:
        for ws, positions in sheets:
            for row_number, row in enumerate(ws.iter_rows(min_row=2, values_only=True), 2):
                if all(v is None or not _text(v) for v in row):
                    continue
                sid = _text(row[positions["会话id"]]) if positions["会话id"] < len(row) else ""
                if not sid:
                    stats["missing_session_id"] += 1
                    continue
                if sid in session_sheets and session_sheets[sid] != ws.title:
                    duplicate_session_ids.add(sid)
                else:
                    session_sheets[sid] = ws.title

                stats["message_count"] += 1
                sequence += 1
                media_urls = []
                for col in MEDIA_COLS:
                    idx = positions.get(col)
                    value = _text(row[idx]) if idx is not None and idx < len(row) else ""
                    if value:
                        media_urls.extend(u.strip() for u in re.split(r",\s*(?=https?://)", value) if u.strip())

                sender_idx = positions["消息发送者"]
                sender = row[sender_idx] if sender_idx < len(row) else ""
                nick_idx = positions.get("发送者昵称")
                nickname = row[nick_idx] if nick_idx is not None and nick_idx < len(row) else ""
                time_idx = positions["创建时间"]
                message_time = _text(row[time_idx]) if time_idx < len(row) else ""
                try:
                    message_time = datetime.fromisoformat(message_time).strftime("%Y-%m-%d %H:%M:%S")
                except ValueError:
                    raise ValueError(f"工作表 {ws.title}，第 {row_number} 行的创建时间无效：{message_time or '空值'}")
                visitor_id_idx = positions.get("访客ID")
                visitor_id = _text(row[visitor_id_idx]) if visitor_id_idx is not None and visitor_id_idx < len(row) else ""
                content_idx = positions["消息内容"]
                content = row[content_idx] if content_idx < len(row) else ""
                body = _build_body(content, list(dict.fromkeys(media_urls)), stats)

                sessions.setdefault(sid, []).append({
                    "time": message_time, "seq": sequence,
                    "name": _speaker_name(sender, nickname),
                    "sender": _text(sender), "nickname": _text(nickname),
                    "visitor_id": visitor_id, "body": body,
                })
    finally:
        wb.close()

    if not sessions:
        raise ValueError("没有找到包含有效会话ID的消息")
    stats["duplicate_session_ids_across_sheets"] = len(duplicate_session_ids)

    out_wb = Workbook(write_only=False)
    out_ws = out_wb.active
    out_ws.title = "会话记录"
    out_ws.append(SESSION_HEADERS)
    for sid, messages in sessions.items():
        messages.sort(key=lambda m: (m["time"], m["seq"]))
        visitor_id = next((m["visitor_id"] for m in messages if m["visitor_id"]), "")
        visitor_name = next((m["nickname"] for m in messages
                             if m["sender"] == "访客" and m["nickname"]), "")
        chunks = _chunk_messages(messages)
        if len(chunks) > 1:
            stats["split_sessions"] += 1
            stats["split_parts"] += len(chunks)
        for part_index, chunk in enumerate(chunks, 1):
            chunk_messages = [message for _, message in chunk]
            chat = CHAT_SEPARATOR.join(block for block, _ in chunk) + CHAT_SEPARATOR
            if _excel_text_length(chat) > EXCEL_CELL_LIMIT:
                raise ValueError(f"会话 {sid} 的自动分段超过 Excel 单元格限制")

            extra = [f"访客ID={visitor_id}"]
            if visitor_name:
                extra.append(f"访客名称={visitor_name}")
            if len(chunks) > 1:
                extra.extend([f"原会话ID={sid}", f"分段={part_index}/{len(chunks)}"])

            out_ws.append([
                sid, "", chunk_messages[0]["time"], chunk_messages[-1]["time"],
                "是" if any(m["sender"] == "坐席" for m in chunk_messages) else "否",
                "\n".join(extra), chat,
            ])

    header_fill = PatternFill("solid", fgColor="17365D")
    header_font = Font(name="微软雅黑", bold=True, color="FFFFFF", size=11)
    cell_font = Font(name="微软雅黑", size=10)
    thin = Side(style="thin", color="B8C7D9")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)
    for cell in out_ws[1]:
        cell.fill, cell.font = header_fill, header_font
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        cell.border = border
    for col, width in {"A": 40, "B": 10, "C": 20, "D": 20, "E": 10, "F": 34, "G": 70}.items():
        out_ws.column_dimensions[col].width = width
    out_ws.freeze_panes = "A2"
    for row in out_ws.iter_rows(min_row=2, max_row=out_ws.max_row, max_col=len(SESSION_HEADERS)):
        for cell in row:
            cell.font = cell_font
            if isinstance(cell.value, str):
                cell.data_type = "s"
            cell.border = border
            cell.alignment = Alignment(
                horizontal="center" if cell.column in (2, 5) else "left",
                vertical="top", wrap_text=True,
            )
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    out_wb.save(output_path)
    stats["session_count"] = len(sessions)
    stats["output_row_count"] = out_ws.max_row - 1
    return stats


def detect_workbook_format(input_path):
    """Recognize source format from headers rather than sheet names."""
    wb = openpyxl.load_workbook(input_path, read_only=True, data_only=True)
    try:
        formats = set()
        for ws in wb.worksheets:
            headers = {_text(v).lower() for v in next(ws.iter_rows(max_row=1, values_only=True), ())}
            if {name.lower() for name in DETAIL_REQUIRED}.issubset(headers):
                formats.add("detail")
            if {name.lower() for name in SESSION_HEADERS}.issubset(headers):
                formats.add("session")
        if len(formats) > 1:
            raise ValueError("文件同时包含逐句明细和历史会话记录，请选择输入格式")
        if not formats:
            raise ValueError("无法识别表头：逐句明细需包含会话id、消息内容、消息发送者、创建时间；历史格式需包含完整七列")
        return formats.pop()
    finally:
        wb.close()


def prepare_human_import(input_path, output_path, input_format="auto"):
    """Prepare a downloadable workbook and count conversations eligible for search."""
    import shutil
    from parse_conversations import process_file

    if input_format not in ("auto", "detail", "session"):
        raise ValueError("输入格式必须为自动识别、逐句明细或历史会话记录")
    selected = detect_workbook_format(input_path) if input_format == "auto" else input_format
    if selected == "detail":
        stats = convert_detail_workbook(input_path, output_path)
    else:
        wb = openpyxl.load_workbook(input_path, read_only=True, data_only=True)
        count, sheets = 0, 0
        try:
            for ws in wb.worksheets:
                headers = {_text(v).lower() for v in next(ws.iter_rows(max_row=1, values_only=True), ())}
                if not {h.lower() for h in SESSION_HEADERS}.issubset(headers):
                    continue
                sheets += 1
                count += sum(any(_text(v) for v in row) for row in ws.iter_rows(min_row=2, values_only=True))
        finally:
            wb.close()
        if not sheets or not count:
            raise ValueError("未找到有效历史会话记录，请检查完整七列表头及数据")
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        shutil.copy2(input_path, output_path)
        stats = dict.fromkeys(("message_count", "missing_session_id",
                               "duplicate_session_ids_across_sheets", "empty_content_media",
                               "placeholder_media", "text_media", "inline_img", "inline_video",
                               "inline_video_nohttp", "emoji", "empty_msg", "truncated_sessions",
                               "split_sessions", "split_parts", "output_row_count"), 0)
        stats.update(sheet_count=sheets, session_count=count, output_row_count=count)
    parsed_path = os.path.join(os.path.dirname(output_path), "预检解析.json")
    parsed = process_file(output_path, parsed_path)
    stats.update(input_format=selected, indexed_count=len(parsed),
                 filtered_count=stats["session_count"] - len(parsed))
    return stats
