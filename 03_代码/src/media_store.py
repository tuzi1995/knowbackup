#!/usr/bin/env python3
"""
客服图片素材库检索（轻量 BM25）。
素材来自 build_media_assets.py：仅严格可入库的操作教程/参数图，每张关联来源会话。
"""
import json
import os
import jieba
from rank_bm25 import BM25Okapi
from text_utils import load_custom_dict, expand_query
from paths import MEDIA_ASSETS_PATH

load_custom_dict()


class MediaStore:
    def __init__(self, path: str = MEDIA_ASSETS_PATH):
        self.path = path
        self.assets = []
        self.bm25 = None
        self._load()

    def _load(self):
        if not os.path.exists(self.path):
            print("未发现图片素材库（media_assets.json）")
            return
        with open(self.path, "r", encoding="utf-8") as f:
            self.assets = json.load(f)
        corpus = [self._doc(a) for a in self.assets]
        self.bm25 = BM25Okapi([list(jieba.cut(t)) for t in corpus])
        print(f"图片素材库就绪：{len(self.assets)} 张")

    def reload(self):
        self._load()

    @staticmethod
    def _doc(a):
        parts = [a.get("desc", ""), a.get("ocr", ""), a.get("caption", ""),
                 a.get("question", ""), " ".join(a.get("models", []))]
        return "\n".join(p for p in parts if p)

    def stats(self):
        if not self.assets:
            return {"available": False}
        types = {}
        with_ocr = 0
        for a in self.assets:
            types[a.get("type", "其他")] = types.get(a.get("type", "其他"), 0) + 1
            if len((a.get("ocr") or "").strip()) >= 8:
                with_ocr += 1
        return {
            "available": True,
            "total": len(self.assets),
            "types": types,
            "with_ocr": with_ocr,
        }

    def search(self, query: str = "", mtype: str = "", limit: int = 60, offset: int = 0):
        if not self.assets:
            return [], 0
        # 候选顺序：有查询走 BM25，无查询按时间倒序浏览
        if query.strip():
            tokens = list(jieba.cut(expand_query(query)))
            scores = self.bm25.get_scores(tokens)
            order = sorted(range(len(self.assets)), key=lambda i: scores[i], reverse=True)
            order = [i for i in order if scores[i] > 0]
        else:
            order = sorted(range(len(self.assets)),
                           key=lambda i: self.assets[i].get("start_time", ""), reverse=True)

        if mtype:
            order = [i for i in order if self.assets[i].get("type") == mtype]

        total = len(order)
        page = [self._view(self.assets[i]) for i in order[offset:offset + limit]]
        return page, total

    @staticmethod
    def _view(a):
        return {
            "url": a.get("url"),
            "type": a.get("type"),
            "desc": a.get("desc", ""),
            "ocr": a.get("ocr", ""),
            "conv_id": a.get("conv_id"),
            "caption": a.get("caption", ""),
            "question": a.get("question", ""),
            "models": a.get("models", []),
            "agent_name": a.get("agent_name", ""),
            "start_time": a.get("start_time", ""),
            "width": a.get("width"),
            "height": a.get("height"),
        }
