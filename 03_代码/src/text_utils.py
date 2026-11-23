#!/usr/bin/env python3
"""
文本处理工具：自定义分词词典、同义词扩展、低质量会话检测
词典数据从 dict_manager 读取，支持页面维护。
"""

import re
import jieba
from dict_manager import get_all_words, get_all_synonyms


def load_custom_dict():
    """加载自定义词典到 jieba"""
    for word in get_all_words():
        jieba.add_word(word, freq=10000)


def expand_query(query: str) -> str:
    """
    同义词扩展：将查询中的词扩展为同义词，用空格连接。
    用于 BM25 检索，提升召回。
    """
    synonyms = get_all_synonyms()
    expanded_terms = [query]
    for standard, syns in synonyms.items():
        all_terms = [standard] + syns
        for term in all_terms:
            if term in query:
                for t in all_terms:
                    if t not in query:
                        expanded_terms.append(t)
                break
    return " ".join(expanded_terms)


def get_query_terms(query: str) -> list:
    """获取查询的关键词（含同义词），用于前端高亮"""
    synonyms = get_all_synonyms()
    terms = set()
    for w in jieba.cut(query):
        w = w.strip()
        if len(w) >= 2:
            terms.add(w)
    for standard, syns in synonyms.items():
        all_terms = [standard] + syns
        for term in all_terms:
            if term in query:
                for t in all_terms:
                    terms.add(t)
                break
    for m in re.findall(r'[A-Za-z]\d{1,3}[A-Za-z]{0,10}(?:\s*(?:Ultra|Pro|Plus|Combo|Max))*', query):
        if len(m) >= 2:
            terms.add(m)
    for m in re.findall(r'错误\d+|E\d+', query, re.I):
        terms.add(m)
    return sorted(terms, key=len, reverse=True)


# ---------- 低质量会话检测 ----------

_NON_ANSWER_PATTERNS = [
    r"稍等", r"耐心等待", r"马上为您转接", r"转接.{0,6}处理",
    r"为您服务", r"工号\d+", r"欢迎光临",
    r"请问有什么可以帮您", r"有什么可以帮到您",
    r"正在确认", r"正在查询", r"帮您查看",
    r"感谢您的理解", r"给您带来了不便",
    r"请问.{0,4}机型", r"提供一下.{0,6}手机号",
    r"您的问题已记录", r"稍后回复",
]

_NON_ANSWER_RE = re.compile("|".join(_NON_ANSWER_PATTERNS))


def is_low_quality(problem_text: str, solution_text: str) -> bool:
    """
    判断会话是否低质量（客服没有给出实质解答）。
    """
    if not solution_text or len(solution_text.strip()) < 10:
        return True

    cleaned = _NON_ANSWER_RE.sub("", solution_text)
    cleaned = re.sub(r"[\s—\-–]+", "", cleaned)

    if len(cleaned) < 20:
        return True

    solution_keywords = [
        "查看", "检查", "清理", "擦拭", "重置", "重启", "更换", "重新",
        "尝试", "建议", "步骤", "操作", "按下", "长按", "打开", "关闭",
        "取出", "放回", "安装", "拆卸", "旋转", "拨动",
        "补发", "寄修", "上门", "退货", "换货", "退款", "保修",
        "视频", "截图", "照片", "提供",
        "报错", "错误", "故障", "异常",
        "可以", "需要", "请", "辛苦",
    ]
    has_substance = any(kw in cleaned for kw in solution_keywords)
    if not has_substance:
        return True

    return False
