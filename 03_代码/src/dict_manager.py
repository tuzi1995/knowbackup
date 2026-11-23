#!/usr/bin/env python3
"""
自定义词典管理：自定义分词、同义词、低质过滤词的增删查改
配置文件：custom_dict.json（与本脚本同目录）
在页面上维护，保存后自动重建 BM25 索引。
"""

import json
import os
from paths import CUSTOM_DICT_PATH as DICT_PATH

# ---------- 默认词典（内置，不可删除，用户可在此基础上追加） ----------
DEFAULT_CUSTOM_WORDS = [
    # 扫地机型号
    "G20S Ultra", "G20S", "G30S Pro", "G30S Ultra", "G30S", "G30", "G20", "G10S", "G10",
    "P20 Ultra Plus", "P20 Ultra", "P20 Max", "P20 Pro", "P20 Plus", "P20",
    "P10S Pro", "P10S", "P10 Pro", "P10", "P30 Pro", "P30",
    "Q Revo", "Q8", "Q5", "S8", "S7", "S5", "T8", "T7S", "T7", "V20", "C10", "B2",
    # 洗地机型号
    "A30 Pro Combo", "A30 Pro Ultra", "A30 Pro Steam", "A30 Pro", "A30 Combo", "A30",
    "A20 Pro", "A20", "A10 Plus", "A10", "F25", "F10",
    # 洗衣机型号
    "Z1 Plus", "Z1", "M1S", "M1", "H1",
    # 其他
    "H50 Ultra", "H50",
    # 部件/功能
    "激光雷达", "激光头", "激光测距", "激光测距传感器", "LDS", "回充", "回充座", "充电桩",
    "滚刷", "主刷", "主刷罩", "边刷", "拖布", "滤网", "尘盒", "水箱", "清水箱", "污水箱",
    "基站", "自清洁", "热风烘干", "自动集尘", "上下水", "自动上下水",
    "旋转轴", "主轮", "万向轮", "弹片", "充电触片", "充电弹片",
    "悬崖传感器", "沿墙传感器", "碰撞传感器", "ToF", "传感器",
    "内筒", "底脚", "运输螺杆", "脱水", "烘干", "漂洗",
    "配网", "联网", "WiFi", "蓝牙", "重置系统", "Reset",
    "电子保修卡", "保修卡", "序列号", "SN码",
    # 错误/状态
    "错误1", "错误2", "错误3", "错误4", "错误5", "错误6", "错误7", "错误8",
    "错误9", "错误10", "错误13", "错误15", "错误16", "错误23", "错误42",
    "错误44", "错误48", "错误52", "错误53", "错误55", "错误61",
    "报错", "异响", "噪音", "震动", "抖动", "卡顿", "离线", "失联",
    # 业务
    "延保", "以旧换新", "开箱扫码", "退换货", "补发", "备件", "上门维修", "寄修", "工单",
    "7天无理由", "质量问题", "售后政策",
]

DEFAULT_SYNONYMS = {
    "异响": ["噪音", "声音大", "咔咔响", "咯吱响", "响声", "杂音", "声音异常", "异常声音", "声响"],
    "震动": ["抖动", "晃动", "晃", "震", "抖", "振动"],
    "回充": ["回不了充", "回不去", "找不到充电桩", "回充失败", "回不到基站"],
    "充不了电": ["充不进电", "无法充电", "充电失败", "充电接触不良", "充不上电"],
    "离线": ["失联", "连不上", "掉线", "离线了", "设备离线"],
    "联网": ["配网", "连网", "连接WiFi", "连接网络", "连不上网"],
    "报错": ["故障", "出错误", "提示错误", "报警", "错误代码", "故障代码"],
    "不出水": ["不喷水", "不出水了", "无水", "水出不来", "不下水"],
    "不转": ["不转动", "转不动", "卡住", "卡死", "停转"],
    "激光雷达": ["激光头", "LDS", "激光测距", "雷达"],
    "滚刷": ["主刷"],
    "拖布": ["抹布", "拖布盘"],
    "延保": ["延长保修", "延保卡", "保修延期"],
    "退货": ["退款", "退了", "退回", "7天无理由"],
    "换货": ["换新", "更换", "换一个"],
    "补发": ["补寄", "重新发", "再发一个"],
    "上门维修": ["上门", "师傅上门", "安排师傅", "上门服务"],
    "寄修": ["寄回", "寄回去修", "返厂", "寄回维修"],
    "序列号": ["SN码", "SN", "串号", "机器编码"],
    "重置": ["重启", "恢复出厂", "Reset", "复位"],
    "配网模式": ["联网模式", "配对模式", "热点模式"],
    "基站": ["基座", "充电座", "底座"],
    "尘盒": ["尘袋", "集尘盒", "灰尘盒"],
    "滤网": ["过滤器", "滤芯", "HEPA"],
    "运输螺杆": ["运输螺栓", "固定螺丝", "后背螺丝"],
    "底脚": ["地脚", "调节脚", "脚垫"],
}


def load_dict() -> dict:
    """加载词典（默认 + 用户自定义合并）"""
    user_words = []
    user_synonyms = {}
    if os.path.exists(DICT_PATH):
        try:
            with open(DICT_PATH, "r", encoding="utf-8") as f:
                saved = json.load(f)
            user_words = saved.get("custom_words", [])
            user_synonyms = saved.get("synonyms", {})
        except (json.JSONDecodeError, IOError):
            pass

    # 合并：默认词 + 用户词（去重）
    all_words = list(dict.fromkeys(DEFAULT_CUSTOM_WORDS + user_words))

    # 合并同义词：默认组 + 用户组（用户可以给已有标准词追加同义词）
    all_synonyms = {}
    for k, v in DEFAULT_SYNONYMS.items():
        all_synonyms[k] = list(dict.fromkeys(v))
    for k, v in user_synonyms.items():
        if k in all_synonyms:
            all_synonyms[k] = list(dict.fromkeys(all_synonyms[k] + v))
        else:
            all_synonyms[k] = list(dict.fromkeys(v))

    return {
        "custom_words": all_words,
        "user_words": user_words,
        "synonyms": all_synonyms,
        "user_synonyms": user_synonyms,
    }


def save_dict(custom_words: list = None, user_synonyms: dict = None) -> dict:
    """保存用户自定义词典（只保存用户新增的部分）"""
    current = {}
    if os.path.exists(DICT_PATH):
        try:
            with open(DICT_PATH, "r", encoding="utf-8") as f:
                current = json.load(f)
        except (json.JSONDecodeError, IOError):
            pass

    if custom_words is not None:
        # 只保存非默认的词
        default_set = set(DEFAULT_CUSTOM_WORDS)
        current["custom_words"] = [w for w in custom_words if w not in default_set]
    if user_synonyms is not None:
        current["synonyms"] = user_synonyms

    with open(DICT_PATH, "w", encoding="utf-8") as f:
        json.dump(current, f, ensure_ascii=False, indent=2)
    return current


def get_all_words() -> list:
    """获取全部自定义词（默认+用户）"""
    return load_dict()["custom_words"]


def get_all_synonyms() -> dict:
    """获取全部同义词（默认+用户）"""
    return load_dict()["synonyms"]
