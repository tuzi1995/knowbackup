#!/usr/bin/env python3
"""
人工客服知识库检索 - 本地网页工具
启动后浏览器打开 http://127.0.0.1:59968
"""

import os
import sys
import json
import time
import uuid
import shutil
from flask import Flask, request, jsonify, render_template_string, send_file
from werkzeug.utils import secure_filename

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
# scripts 目录（build_index / build_clusters 所在）也加入路径，供页面"数据更新"调用
sys.path.insert(0, os.path.abspath(os.path.join(_HERE, "..", "scripts")))
from search_engine import SearchEngine

app = Flask(__name__)
engine = None        # 人工客服会话引擎
ai_engine = None     # 智能客服问答引擎（索引未构建时为 None）
media_store = None   # 客服图片素材库（未构建时为空对象）


def get_engine(corpus):
    """按语料返回对应引擎：human=人工客服，ai=智能客服"""
    return ai_engine if corpus == "ai" else engine

HTML_PAGE = r"""
<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>人工客服知识库检索</title>
<style>
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif;
         background: #f5f6f8; color: #1a1a1a; line-height: 1.6; }
  .header { background: #fff; border-bottom: 1px solid #e8e8e8; padding: 20px 0; position: sticky; top: 0; z-index: 100;
            box-shadow: 0 1px 4px rgba(0,0,0,0.04); }
  .container { max-width: 900px; margin: 0 auto; padding: 0 20px; }
  .header h1 { font-size: 20px; font-weight: 600; margin-bottom: 12px; display: flex; justify-content: space-between; align-items: center; }
  .btn-settings { padding: 5px 12px; background: #f5f5f5; border: 1px solid #d9d9d9; border-radius: 6px;
                  font-size: 13px; color: #666; cursor: pointer; transition: all 0.2s; }
  .btn-settings:hover { border-color: #4f7cff; color: #4f7cff; }
  .status-badge { display: inline-block; padding: 2px 8px; border-radius: 10px; font-size: 11px; font-weight: normal; margin-left: 8px; }
  .status-api { background: #e8f8ee; color: #2ba471; }
  .status-local { background: #f0f0f0; color: #888; }
  .search-bar { display: flex; gap: 10px; }
  .search-bar input[type="text"] { flex: 1; padding: 10px 14px; border: 1px solid #d9d9d9; border-radius: 8px;
                                    font-size: 15px; outline: none; transition: border-color 0.2s; }
  .search-bar input[type="text"]:focus { border-color: #4f7cff; }
  .search-bar button { padding: 10px 24px; background: #4f7cff; color: #fff; border: none; border-radius: 8px;
                        font-size: 15px; cursor: pointer; transition: background 0.2s; }
  .search-bar button:hover { background: #3a66e8; }
  .search-bar button:disabled { background: #a0b4f0; cursor: not-allowed; }
  .filters { display: flex; gap: 12px; margin-top: 10px; align-items: center; font-size: 13px; color: #666; }
  .filters input { padding: 6px 10px; border: 1px solid #d9d9d9; border-radius: 6px; font-size: 13px; width: 120px; }
  .filters label { display: flex; align-items: center; gap: 4px; }
  .status-bar { display: flex; flex-wrap: wrap; gap: 16px; margin-top: 12px; padding-top: 10px;
                border-top: 1px solid #f0f0f0; font-size: 12px; color: #999; }
  .status-item { display: flex; align-items: center; gap: 4px; }
  .status-dot { width: 7px; height: 7px; border-radius: 50%; background: #2ba471; display: inline-block; }
  .status-item b { color: #666; font-weight: 500; }
  .main-tabs { display: flex; gap: 0; margin-bottom: 14px; border-bottom: 2px solid #f0f0f0; }
  .main-tab { padding: 8px 20px; cursor: pointer; font-size: 14px; color: #999; border-bottom: 2px solid transparent;
              margin-bottom: -2px; transition: all 0.2s; }
  .main-tab:hover { color: #4f7cff; }
  .main-tab.active { color: #4f7cff; border-bottom-color: #4f7cff; font-weight: 500; }
  .cluster-card { background: #fff; border: 1px solid #e8e8e8; border-radius: 10px; padding: 16px 20px;
                  margin-bottom: 12px; cursor: pointer; transition: all 0.2s; }
  .cluster-card:hover { border-color: #4f7cff; box-shadow: 0 2px 12px rgba(79,124,255,0.1); }
  .cluster-card-header { display: flex; justify-content: space-between; align-items: flex-start; gap: 12px; }
  .cluster-title { font-size: 15px; font-weight: 600; color: #1a1a1a; flex: 1; }
  .cluster-size { flex-shrink: 0; font-size: 12px; color: #999; background: #f5f6f8; padding: 2px 8px; border-radius: 10px; }
  .cluster-preview { font-size: 13px; color: #666; margin-top: 8px; line-height: 1.6;
    display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
  .cluster-tags { margin-top: 8px; display: flex; flex-wrap: wrap; gap: 6px; }
  .cluster-detail { margin-top: 12px; padding-top: 12px; border-top: 1px solid #f0f0f0; display: none; }
  .cluster-card.expanded .cluster-detail { display: block; }
  .cluster-card.expanded { cursor: default; }
  .cluster-card.expanded .cluster-preview { display: none; }
  .cluster-answer { font-size: 14px; line-height: 1.8; color: #333; white-space: normal; }
  .cluster-answer h4 { margin: 10px 0 4px; color: #2c3e50; }
  .cluster-sources { margin-top: 14px; }
  .cluster-source { background: #f9f9fb; border-radius: 6px; padding: 10px 14px; margin-bottom: 8px; font-size: 13px; }
  .cluster-source-problem { color: #4f7cff; margin-bottom: 4px; }
  .cluster-source-solution { color: #666; white-space: pre-wrap; }
  .results { padding: 20px 0 60px; }
  .stats { color: #999; font-size: 13px; margin-bottom: 16px; display: flex; justify-content: space-between; align-items: center; }
  .btn-ai-summary { padding: 6px 16px; background: linear-gradient(135deg, #667eea, #764ba2); color: #fff;
    border: none; border-radius: 6px; font-size: 13px; cursor: pointer; font-weight: 500; }
  .btn-ai-summary:hover { opacity: 0.9; }
  .ai-summary-card { background: #fff; border: 1px solid #d4c5f9; border-radius: 10px; padding: 18px 22px;
    margin-bottom: 18px; box-shadow: 0 2px 12px rgba(102,126,234,0.1); }
  .ai-summary-header { display: flex; align-items: center; gap: 8px; margin-bottom: 12px; }
  .ai-badge { display: inline-block; padding: 2px 8px; background: linear-gradient(135deg, #667eea, #764ba2);
    color: #fff; border-radius: 4px; font-size: 11px; font-weight: 600; }
  .ai-summary-meta { color: #999; font-size: 12px; margin-left: auto; }
  .ai-summary-close { background: none; border: none; font-size: 18px; color: #999; cursor: pointer; padding: 0 4px; }
  .ai-summary-close:hover { color: #333; }
  .ai-summary-body { font-size: 14px; line-height: 1.8; color: #333; white-space: normal; }
  .ai-summary-body h4:first-child { margin-top: 0; }
  .card { background: #fff; border: 1px solid #e8e8e8; border-radius: 10px; padding: 18px 20px; margin-bottom: 14px;
          transition: box-shadow 0.2s; }
  .card:hover { box-shadow: 0 2px 12px rgba(0,0,0,0.08); }
  .card-meta { display: flex; flex-wrap: wrap; gap: 8px; font-size: 12px; color: #999; margin-bottom: 10px; align-items: center; }
  .tag { display: inline-block; padding: 2px 8px; border-radius: 4px; font-size: 12px; }
  .tag-model { background: #eef4ff; color: #4f7cff; }
  .tag-error { background: #fff3e8; color: #e8870e; }
  .tag-agent { background: #f0f0f0; color: #666; }
  .tag-score { background: #e8f8ee; color: #2ba471; }
  .score-bar { display: flex; align-items: center; gap: 8px; margin-bottom: 10px; font-size: 12px; color: #999; }
  .score-bar-label { flex-shrink: 0; min-width: 36px; }
  .score-bar-track { flex: 1; height: 6px; background: #f0f0f0; border-radius: 3px; overflow: hidden; }
  .score-bar-fill { display: block; height: 100%; border-radius: 3px; transition: width 0.4s ease; }
  .score-bar-val { flex-shrink: 0; min-width: 42px; text-align: right; font-variant-numeric: tabular-nums; color: #666; }
  .section-label { font-size: 12px; font-weight: 600; color: #999; text-transform: uppercase; letter-spacing: 0.5px;
                    margin-bottom: 6px; margin-top: 12px; }
  .problem { background: #f9f9fb; border-left: 3px solid #4f7cff; padding: 10px 14px; border-radius: 0 6px 6px 0;
              font-size: 14px; white-space: pre-wrap; word-break: break-word; }
  .solution { white-space: pre-wrap; word-break: break-word; font-size: 14px; }
  .solution-step { padding: 8px 0; border-bottom: 1px dashed #f0f0f0; }
  .solution-step:last-child { border-bottom: none; }
  .step-num { display: inline-block; width: 22px; height: 22px; line-height: 22px; text-align: center;
              background: #4f7cff; color: #fff; border-radius: 50%; font-size: 12px; margin-right: 8px; }
  .card-actions { margin-top: 14px; padding-top: 10px; border-top: 1px solid #f0f0f0; }
  .btn-raw { padding: 5px 14px; background: #fff; border: 1px solid #d9d9d9; border-radius: 6px; font-size: 13px;
             color: #555; cursor: pointer; transition: all 0.2s; }
  .btn-raw:hover { border-color: #4f7cff; color: #4f7cff; }
  .loading { text-align: center; padding: 40px; color: #999; }
  .welcome { text-align: center; padding: 60px 20px; color: #999; }
  .welcome h2 { font-size: 18px; color: #666; margin-bottom: 10px; }
  .welcome p { font-size: 14px; }
  .examples { margin-top: 20px; }
  .example-btn { display: inline-block; margin: 4px; padding: 6px 14px; background: #fff; border: 1px solid #d9d9d9;
                  border-radius: 20px; font-size: 13px; cursor: pointer; color: #555; transition: all 0.2s; }
  .example-btn:hover { border-color: #4f7cff; color: #4f7cff; }

  /* 模态框 */
  .modal-overlay { display: none; position: fixed; top: 0; left: 0; width: 100%; height: 100%;
                    background: rgba(0,0,0,0.4); z-index: 200; justify-content: center; align-items: flex-start;
                    padding: 40px 20px; overflow-y: auto; }
  .modal-overlay.active { display: flex; }
  .modal { background: #fff; border-radius: 12px; max-width: 800px; width: 100%; padding: 24px;
           box-shadow: 0 8px 32px rgba(0,0,0,0.15); }
  .modal-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px;
                  padding-bottom: 12px; border-bottom: 1px solid #f0f0f0; }
  .modal-header h3 { font-size: 17px; font-weight: 600; }
  .modal-close { width: 30px; height: 30px; border: none; background: #f5f5f5; border-radius: 50%;
                 font-size: 18px; cursor: pointer; color: #999; line-height: 1; }
  .modal-close:hover { background: #eee; color: #333; }
  .modal-meta { font-size: 12px; color: #999; margin-bottom: 16px; }
  .turn { padding: 10px 14px; margin-bottom: 8px; border-radius: 8px; font-size: 14px; white-space: pre-wrap;
          word-break: break-word; }
  .turn-visitor { background: #eef4ff; }
  .turn-agent { background: #f0f9f2; }
  .turn-bot { background: #f5f5f5; color: #666; }
  .turn-system { background: #fafafa; color: #999; font-size: 13px; }
  .turn-role { font-weight: 600; font-size: 12px; margin-bottom: 4px; }
  .turn-visitor .turn-role { color: #4f7cff; }
  .turn-agent .turn-role { color: #2ba471; }
  .turn-time { font-weight: normal; color: #aaa; margin-left: 8px; }
  .media-link { display: inline-block; margin-top: 6px; margin-right: 8px; padding: 3px 10px;
                background: rgba(79,124,255,0.1); color: #4f7cff; border-radius: 4px;
                font-size: 12px; text-decoration: none; }
  .media-link:hover { background: rgba(79,124,255,0.2); }
  .media-img { display: block; max-width: 280px; max-height: 200px; margin-top: 8px; border-radius: 6px;
               cursor: zoom-in; border: 1px solid #e8e8e8; object-fit: contain; background: #f9f9f9; }
  .media-img:hover { border-color: #4f7cff; }
  .media-video { display: block; max-width: 320px; max-height: 240px; margin-top: 8px; border-radius: 6px; }
  .media-audio { display: block; margin-top: 8px; height: 36px; }

  /* 图片灯箱 */
  .lightbox { display: none; position: fixed; top: 0; left: 0; width: 100%; height: 100%;
              background: rgba(0,0,0,0.85); z-index: 300; justify-content: center; align-items: center;
              cursor: zoom-out; }
  .lightbox.active { display: flex; }
  .lightbox img { max-width: 92%; max-height: 92%; border-radius: 8px; box-shadow: 0 4px 24px rgba(0,0,0,0.5); }

  /* 设置面板 */
  .form-group { margin-bottom: 14px; }
  .form-group label { display: block; font-size: 13px; font-weight: 600; color: #555; margin-bottom: 4px; }
  .form-group input { width: 100%; padding: 8px 12px; border: 1px solid #d9d9d9; border-radius: 6px; font-size: 13px; outline: none; }
  .form-group input:focus { border-color: #4f7cff; }
  .form-group select { width:100%; padding:8px 12px; border:1px solid #d9d9d9; border-radius:6px; background:#fff; font-size:13px; }
  .form-group .hint { font-size: 11px; color: #aaa; margin-top: 3px; }
  .form-row { display: flex; gap: 12px; }
  .form-row .form-group { flex: 1; }
  .form-section { font-size: 13px; font-weight: 600; color: #333; margin: 16px 0 8px; padding-bottom: 6px; border-bottom: 1px solid #f0f0f0; }
  .form-actions { display: flex; gap: 10px; margin-top: 18px; padding-top: 14px; border-top: 1px solid #f0f0f0; }
  .btn-primary { padding: 8px 20px; background: #4f7cff; color: #fff; border: none; border-radius: 6px; font-size: 13px; cursor: pointer; }
  .btn-primary:hover { background: #3a66e8; }
  .btn-secondary { padding: 8px 20px; background: #fff; color: #666; border: 1px solid #d9d9d9; border-radius: 6px; font-size: 13px; cursor: pointer; }
  .btn-secondary:hover { border-color: #999; color: #333; }
  .config-status { font-size: 12px; padding: 8px 12px; border-radius: 6px; margin-bottom: 12px; }
  .config-ok { background: #e8f8ee; color: #2ba471; }
  .config-warn { background: #fff8e6; color: #b8860b; }
  .test-result { font-size: 12px; margin-top: 8px; padding: 6px 10px; border-radius: 4px; display: none; }
  .test-ok { background: #e8f8ee; color: #2ba471; display: block; }
  .test-err { background: #ffeef0; color: #e54545; display: block; }

  /* 关键词高亮 */
  .hl { background: #fff3a3; padding: 0 1px; border-radius: 2px; font-weight: 600; }

  /* 筛选标签 */
  .filter-tags { margin: 10px 0 14px; }
  .filter-tags-title { font-size: 12px; color: #999; margin-bottom: 6px; }
  .filter-tag { display: inline-block; padding: 3px 10px; margin: 2px 4px 2px 0; border: 1px solid #d9d9d9;
                border-radius: 14px; font-size: 12px; color: #555; cursor: pointer; transition: all 0.15s;
                background: #fff; }
  .filter-tag:hover { border-color: #4f7cff; color: #4f7cff; }
  .filter-tag.active { background: #4f7cff; color: #fff; border-color: #4f7cff; }
  .filter-tag .ft-count { color: #aaa; font-size: 11px; margin-left: 3px; }
  .filter-tag.active .ft-count { color: rgba(255,255,255,0.7); }
  .filter-clear { font-size: 12px; color: #999; cursor: pointer; margin-left: 8px; }
  .filter-clear:hover { color: #e54545; }

  /* 折叠 */
  .solution.collapsed { max-height: 200px; overflow: hidden; position: relative; }
  .solution.collapsed::after { content: ''; position: absolute; bottom: 0; left: 0; right: 0;
                               height: 40px; background: linear-gradient(transparent, #fff); }
  .btn-expand { display: block; margin: 8px auto 0; padding: 4px 16px; background: none; border: 1px solid #d9d9d9;
                border-radius: 6px; font-size: 12px; color: #666; cursor: pointer; }
  .btn-expand:hover { border-color: #4f7cff; color: #4f7cff; }

  /* 低质量标签 */
  .tag-lowq { background: #fff0f0; color: #e54545; }
  /* 客服素材标签 */
  .tag-media { background: #eafaf1; color: #1a9e5a; border: 1px solid #bfe8d2; }

  /* 图片素材库 */
  .media-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(260px, 1fr)); gap: 12px; margin-top: 14px; }
  .media-card { background: #fff; border: 1px solid #eee; border-radius: 8px; overflow: hidden; display: flex; flex-direction: column; }
  .media-thumb { width: 100%; height: 180px; object-fit: contain; background: #fafafa; cursor: zoom-in; border-bottom: 1px solid #f0f0f0; }
  .media-body { padding: 9px 11px; font-size: 12.5px; display: flex; flex-direction: column; gap: 5px; flex: 1; }
  .media-desc { font-weight: 600; font-size: 13px; color: #222; }
  .media-ocr { color: #555; background: #fafafa; border-radius: 5px; padding: 6px 8px; max-height: 96px; overflow: hidden; position: relative; white-space: pre-wrap; line-height: 1.5; }
  .media-ocr.expanded { max-height: none; }
  .media-ctx { color: #888; font-size: 11.5px; border-top: 1px dashed #eee; padding-top: 5px; }
  .media-ctx b { color: #4f7cff; font-weight: 500; }
  .media-foot { display: flex; align-items: center; gap: 6px; margin-top: auto; padding-top: 4px; }
  .media-type { font-size: 11px; padding: 1px 8px; border-radius: 10px; background: #eef4ff; color: #4f7cff; }
  .btn-src { margin-left: auto; font-size: 11.5px; padding: 3px 10px; background: #f5f5f5; border: 1px solid #ddd; border-radius: 6px; cursor: pointer; color: #555; }
  .btn-src:hover { border-color: #4f7cff; color: #4f7cff; }
  .media-more { text-align: center; margin: 16px 0; }

  /* 词典管理 */
  .dict-section { margin-top: 12px; }
  .dict-section h4 { font-size: 13px; font-weight: 600; margin-bottom: 8px; }
  .dict-input-row { display: flex; gap: 6px; margin-bottom: 8px; }
  .dict-input-row input { flex: 1; padding: 6px 10px; border: 1px solid #d9d9d9; border-radius: 6px; font-size: 13px; }
  .dict-input-row button { padding: 6px 14px; background: #4f7cff; color: #fff; border: none; border-radius: 6px;
                           font-size: 13px; cursor: pointer; white-space: nowrap; }
  .dict-list { max-height: 180px; overflow-y: auto; border: 1px solid #f0f0f0; border-radius: 6px; padding: 6px; }
  .dict-item { display: inline-block; padding: 3px 8px; margin: 2px; background: #f5f5f5; border-radius: 4px;
               font-size: 12px; }
  .dict-item.builtin { background: #eef4ff; color: #4f7cff; }
  .dict-item .dict-del { cursor: pointer; color: #ccc; margin-left: 4px; }
  .dict-item .dict-del:hover { color: #e54545; }
  .syn-group { margin-bottom: 8px; padding: 8px; background: #fafafa; border-radius: 6px; }
  .syn-key { font-weight: 600; font-size: 13px; color: #333; }
  .syn-words { margin-top: 4px; }
  .tabs { display: flex; gap: 0; margin-bottom: 12px; border-bottom: 1px solid #f0f0f0; }
  .tab { padding: 8px 16px; font-size: 13px; cursor: pointer; color: #999; border-bottom: 2px solid transparent; }
  .tab.active { color: #4f7cff; border-bottom-color: #4f7cff; font-weight: 600; }
  .tab-panel { display: none; }
  .tab-panel.active { display: block; }

  /* ===== 顶部数据源切换 ===== */
  .corpus-switch { display:flex; gap:4px; background:#eef1f7; border-radius:10px; padding:4px; width:fit-content; margin-bottom:14px; }
  .corpus-btn { padding:7px 18px; font-size:14px; border-radius:8px; cursor:pointer; color:#666; font-weight:500; user-select:none; transition:all .15s; }
  .corpus-btn.active { background:#fff; color:#4f7cff; font-weight:600; box-shadow:0 1px 4px rgba(0,0,0,.08); }
  .ai-only { display:none; }
  body.corpus-ai .ai-only { display:block; }
  body.corpus-ai .human-only { display:none !important; }
  body.corpus-ai h1 .title-human { display:none; }
  h1 .title-ai { display:none; }
  body.corpus-ai h1 .title-ai { display:inline; }

  /* AI 结果卡片 */
  .ai-meta-row { display:flex; flex-wrap:wrap; gap:6px; align-items:center; margin-bottom:8px; }
  .tag-cat { background:#eef4ff; color:#3a6bd8; }
  .tag-qtype { background:#f3edff; color:#7a4fd0; }
  .tag-bad { background:#fdeeee; color:#d04848; }
  .tag-good { background:#e9f7ef; color:#2ba471; }
  .tag-hidden { background:#f2f2f2; color:#999; }
  .ai-qsrc { font-size:12px; color:#999; margin:2px 0 6px; }
  .ai-kb { margin-top:8px; font-size:12px; color:#888; background:#fafafb; border-radius:6px; padding:8px 10px; }
  .ai-kb summary { cursor:pointer; color:#666; font-weight:500; }
  .ai-kb-list { margin:6px 0 0; padding-left:4px; list-style:none; }
  .ai-kb-list li { font-family:monospace; font-size:11px; color:#7a8aa0; }
  .ai-filters { display:flex; flex-wrap:wrap; gap:10px; align-items:center; margin-top:10px; }
  .ai-filters select, .ai-filters input[type=text] { padding:6px 8px; border:1px solid #e0e0e6; border-radius:6px; font-size:13px; }
  .chip-group { display:flex; gap:6px; flex-wrap:wrap; }
  .qchip { padding:4px 10px; font-size:12px; border-radius:14px; background:#f4f5f8; color:#666; cursor:pointer; user-select:none; border:1px solid transparent; }
  .qchip.active { background:#e8efff; color:#4f7cff; border-color:#b9cfff; }
</style>
</head>
<body>

<div class="header">
  <div class="container">
    <h1><span class="title-human">人工客服知识库</span><span class="title-ai">智能客服问答库</span> <button class="btn-settings" onclick="openSettings()">设置</button></h1>

    <div class="corpus-switch">
      <div class="corpus-btn active" id="corpus-human" onclick="switchCorpus('human')">人工客服解答</div>
      <div class="corpus-btn" id="corpus-ai" onclick="switchCorpus('ai')">智能客服解答</div>
    </div>

    <div class="human-only">
    <div class="main-tabs">
      <div class="main-tab active" id="tab-search-btn" onclick="switchMainTab('search')">会话检索</div>
      <div class="main-tab" id="tab-cluster-btn" onclick="switchMainTab('cluster')">问题库</div>
      <div class="main-tab" id="tab-media-btn" onclick="switchMainTab('media')">图片素材</div>
    </div>

    <!-- 会话检索 -->
    <div id="panel-search">
    <div class="search-bar">
      <input type="text" id="query" placeholder="输入问题，如：洗衣机异响震动、扫地机报错E1、洗地机不出水..."
             autofocus onkeydown="if(event.key==='Enter')doSearch()">
      <button id="searchBtn" onclick="doSearch()">搜索</button>
    </div>
    <div class="filters">
      <label>型号筛选 <input type="text" id="modelFilter" placeholder="如 G10S" onkeydown="if(event.key==='Enter'){currentFilters.model='';doSearch()}"></label>
      <label>结果数 <input type="number" id="topK" value="10" min="1" max="50" style="width:60px"></label>
      <label style="display:flex;align-items:center;gap:3px;cursor:pointer">
        <input type="checkbox" id="includeLq" style="width:auto"> 显示低质量
      </label>
      <label style="display:flex;align-items:center;gap:3px;cursor:pointer" title="只看客服发送过操作图片/视频等素材的会话">
        <input type="checkbox" id="agentMediaOnly" style="width:auto"> 只看带客服素材
      </label>
    </div>
    </div>

    <!-- 问题库 -->
    <div id="panel-cluster" style="display:none">
    <div class="search-bar">
      <input type="text" id="clusterQuery" placeholder="搜索问题库，如：异响、错误1、延保..."
             onkeydown="if(event.key==='Enter')searchClusters()">
      <button onclick="searchClusters()">搜索</button>
    </div>
    </div>

    <!-- 图片素材库 -->
    <div id="panel-media" style="display:none">
      <div class="search-bar">
        <input type="text" id="mediaQuery" placeholder="搜索客服图片素材，如：安装尺寸、拆滚刷、基站功能、错误1图示..."
               onkeydown="if(event.key==='Enter')doMediaSearch()">
        <button id="mediaSearchBtn" onclick="doMediaSearch()">搜索</button>
      </div>
      <div class="filters" id="mediaFilters" style="flex-wrap:wrap">
        <span style="font-size:12px;color:#999">类型：</span>
        <span class="qchip active" data-t="" onclick="setMediaType(this)">全部</span>
        <span class="qchip" data-t="操作教程或界面指引" onclick="setMediaType(this)">操作教程/界面</span>
        <span class="qchip" data-t="商品参数图" onclick="setMediaType(this)">商品参数图</span>
        <span id="mediaStat" style="margin-left:auto;font-size:12px;color:#999"></span>
      </div>
      <div id="mediaResults" class="media-grid"></div>
      <div class="media-more" id="mediaMoreWrap" style="display:none">
        <button class="btn-expand" onclick="loadMoreMedia()">加载更多 ▼</button>
      </div>
    </div>

    <div class="status-bar" id="statusBar">
      <span class="status-item"><span class="status-dot"></span>加载中...</span>
    </div>
    </div><!-- /human-only -->

    <!-- 智能客服检索 -->
    <div class="ai-only" id="panel-ai">
      <div class="search-bar">
        <input type="text" id="aiQuery" placeholder="输入问题，检索智能客服（转人工前）大模型是怎么回答的..."
               onkeydown="if(event.key==='Enter')doAiSearch()">
        <button id="aiSearchBtn" onclick="doAiSearch()">搜索</button>
      </div>
      <div class="ai-filters">
        <label>产品 <input type="text" id="aiProduct" placeholder="如 P20 Ultra" style="width:120px"
               onkeydown="if(event.key==='Enter')doAiSearch()"></label>
        <label>结果数 <input type="number" id="aiTopK" value="10" min="1" max="50" style="width:56px"></label>
        <span style="font-size:12px;color:#999">快捷视角：</span>
        <div class="chip-group" id="aiChips">
          <span class="qchip" data-k="eff_recall" data-v="0" onclick="toggleAiChip(this)">只看无效召回</span>
          <span class="qchip" data-k="to_human" data-v="1" onclick="toggleAiChip(this)">只看转人工</span>
          <span class="qchip" data-k="vote" data-v="down" onclick="toggleAiChip(this)">只看被踩</span>
        </div>
        <label style="display:flex;align-items:center;gap:3px;cursor:pointer;font-size:13px">
          <input type="checkbox" id="aiIncludeHidden" style="width:auto"> 显示转人工/识图类
        </label>
      </div>
      <div class="status-bar" id="aiStatusBar" style="margin-top:10px">
        <span class="status-item"><span class="status-dot"></span>加载中...</span>
      </div>
    </div>
  </div>
</div>

<div class="container">
  <div id="summaryArea" class="human-only"></div>
  <div class="results human-only" id="results">
    <div class="welcome">
      <h2>输入问题，检索人工客服的真实解答</h2>
      <p>基于历史人工会话，返回完整的问题排查与解决过程</p>
      <div class="examples">
        <span class="example-btn" onclick="setQuery('洗衣机异响震动')">洗衣机异响震动</span>
        <span class="example-btn" onclick="setQuery('扫地机报错E1')">扫地机报错E1</span>
        <span class="example-btn" onclick="setQuery('洗地机不出水')">洗地机不出水</span>
        <span class="example-btn" onclick="setQuery('如何申请延保')">如何申请延保</span>
        <span class="example-btn" onclick="setQuery('退货退款政策')">退货退款政策</span>
        <span class="example-btn" onclick="setQuery('扫地机无法回充')">扫地机无法回充</span>
      </div>
    </div>
  </div>
  <div class="results human-only" id="clusterResults" style="display:none"></div>

  <!-- 智能客服结果 -->
  <div class="results ai-only" id="aiResults">
    <div class="welcome">
      <h2>输入问题，看智能客服（大模型）当时怎么回答</h2>
      <p>基于转人工前的 AI 问答日志，返回大模型答案、召回 KB 与质量标注</p>
      <div class="examples">
        <span class="example-btn" onclick="setAiQuery('地图白线怎么去掉')">地图白线怎么去掉</span>
        <span class="example-btn" onclick="setAiQuery('一次性尘袋要自己准备吗')">尘袋要自己准备吗</span>
        <span class="example-btn" onclick="setAiQuery('清洁液加在哪里')">清洁液加在哪里</span>
        <span class="example-btn" onclick="setAiQuery('无法连接wifi')">无法连接wifi</span>
        <span class="example-btn" onclick="setAiQuery('保修多久')">保修多久</span>
      </div>
    </div>
  </div>
</div>

<!-- 原始对话模态框 -->
<div class="modal-overlay" id="modal" onclick="if(event.target===this)closeModal()">
  <div class="modal">
    <div class="modal-header">
      <h3>原始对话</h3>
      <button class="modal-close" onclick="closeModal()">&times;</button>
    </div>
    <div class="modal-meta" id="modalMeta"></div>
    <div id="modalContent"></div>
  </div>
</div>

<!-- 图片灯箱 -->
<div class="lightbox" id="lightbox" onclick="closeLightbox()">
  <img id="lightboxImg" src="">
</div>

<!-- API 设置模态框 -->
<div class="modal-overlay" id="settingsModal" onclick="if(event.target===this)closeSettings()">
  <div class="modal" style="max-width:600px">
    <div class="modal-header">
      <h3>设置</h3>
      <button class="modal-close" onclick="closeSettings()">&times;</button>
    </div>
    <div class="tabs">
      <div class="tab active" onclick="switchTab('api')">API 配置</div>
      <div class="tab" onclick="switchTab('dict')">词典维护</div>
      <div class="tab" onclick="switchTab('update')">数据更新</div>
    </div>

    <!-- API 配置 -->
    <div class="tab-panel active" id="tab-api">
    <div id="configStatus"></div>
    <div class="form-section">Embedding（语义向量）</div>
    <div class="form-group">
      <label>API 地址</label>
      <input type="text" id="cfgEmbUrl" placeholder="https://api.siliconflow.cn/v1/embeddings">
    </div>
    <div class="form-row">
      <div class="form-group">
        <label>API Key</label>
        <input type="password" id="cfgEmbKey" placeholder="sk-...">
      </div>
      <div class="form-group" style="max-width:100px">
        <label>维度</label>
        <input type="number" id="cfgEmbDim" value="1024">
      </div>
    </div>
    <div class="form-group">
      <label>模型名称</label>
      <input type="text" id="cfgEmbModel" placeholder="Pro/BAAI/bge-m3">
    </div>

    <div class="form-section">Reranker（精排）</div>
    <div class="form-group">
      <label>API 地址</label>
      <input type="text" id="cfgRerankUrl" placeholder="https://api.siliconflow.cn/v1/rerank">
    </div>
    <div class="form-group">
      <label>API Key（不填则复用 Embedding Key）</label>
      <input type="password" id="cfgRerankKey" placeholder="留空则使用 Embedding Key">
    </div>
    <div class="form-group">
      <label>模型名称</label>
      <input type="text" id="cfgRerankModel" placeholder="BAAI/bge-reranker-v2-m3">
    </div>

    <div class="form-section">AI 总结（LLM 问答生成）</div>
    <div class="form-group">
      <label>API 地址</label>
      <input type="text" id="cfgLlmUrl" placeholder="https://api.siliconflow.cn/v1/chat/completions">
      <div class="hint">支持填写基础地址（如 Ark 的 /api/coding/v3），系统会自动补全 /chat/completions。</div>
    </div>
    <div class="form-group">
      <label>API Key（不填则复用 Embedding Key）</label>
      <input type="password" id="cfgLlmKey" placeholder="留空则使用 Embedding Key">
    </div>
    <div class="form-row">
      <div class="form-group">
        <label>模型名称</label>
        <input type="text" id="cfgLlmModel" placeholder="deepseek-ai/DeepSeek-V3">
      </div>
      <div class="form-group" style="max-width:90px">
        <label>温度</label>
        <input type="number" id="cfgLlmTemp" value="0.3" step="0.1" min="0" max="2">
      </div>
    </div>

    <div id="testResult"></div>
    <div class="form-actions">
      <button class="btn-secondary" onclick="testConfig()">测试连接</button>
      <button class="btn-primary" onclick="saveConfig()">保存</button>
    </div>
    <div class="hint" style="margin-top:10px;color:#999;font-size:11px">
      保存后 Reranker 立即生效；Embedding 需在终端运行 python3 update.py 重建索引。
    </div>
    </div>

    <!-- 词典维护 -->
    <div class="tab-panel" id="tab-dict">
      <div class="dict-section">
        <h4>自定义分词（型号、部件名、错误码等）</h4>
        <div class="dict-input-row">
          <input type="text" id="newWord" placeholder="输入新词，如 G40S Ultra、激光模组" onkeydown="if(event.key==='Enter')addWord()">
          <button onclick="addWord()">添加</button>
        </div>
        <div class="dict-list" id="wordList"><div class="loading" style="padding:10px">加载中...</div></div>
      </div>
      <div class="dict-section">
        <h4>同义词组（输入任一词可互召回）</h4>
        <div class="dict-input-row">
          <input type="text" id="newSynKey" placeholder="标准词，如 异响" style="max-width:120px">
          <input type="text" id="newSynWords" placeholder="同义词，逗号分隔，如 噪音,声音大,咔咔响">
          <button onclick="addSynonym()">添加</button>
        </div>
        <div id="synList"><div class="loading" style="padding:10px">加载中...</div></div>
      </div>
      <div class="form-actions">
        <button class="btn-primary" onclick="saveDict()">保存并重建索引</button>
      </div>
      <div class="hint" style="margin-top:8px;color:#999;font-size:11px">
        蓝色为内置词不可删除，黑色为自定义词可删除。保存后自动重建 BM25 索引（约 10 秒）。
      </div>
    </div>

    <!-- 数据更新 -->
    <div class="tab-panel" id="tab-update">
      <div class="form-section">每周数据更新</div>
      <p style="font-size:13px;color:#666;margin-bottom:14px">
        人工会话先预检，可下载整合后的 Excel，再选择是否更新检索库。更新会替换当前检索数据；构建期间仍可搜索旧数据。
      </p>

      <div class="form-group">
        <label>更新哪类数据</label>
        <div class="corpus-switch" style="margin-bottom:0">
          <div class="corpus-btn active" id="upd-human" onclick="setUpdateCorpus('human')">人工客服会话</div>
          <div class="corpus-btn" id="upd-ai" onclick="setUpdateCorpus('ai')">智能客服问答</div>
          <div class="corpus-btn" id="upd-media" onclick="setUpdateCorpus('media')">图片素材库</div>
        </div>
      </div>

      <div id="fileUpdateOpt">
      <div class="form-group" id="humanFormatOpt">
        <label>人工会话输入格式</label>
        <select id="humanInputFormat" onchange="invalidateConversion()">
          <option value="auto">自动识别</option>
          <option value="detail">逐句明细（一行一句）</option>
          <option value="session">历史会话记录（七列）</option>
        </select>
      </div>
      <div class="form-group">
        <label>方式一：填写本地文件路径</label>
        <input type="text" id="updateFilePath" oninput="invalidateConversion()" placeholder="/Volumes/ORICO/会话记录/每周会话/会话记录_xxx.xlsx">
      </div>

      <div class="form-group">
        <label>方式二：上传 Excel 文件</label>
        <input type="file" id="updateFile" accept=".xlsx" onchange="invalidateConversion()" style="font-size:13px">
      </div>
      </div>

      <div class="form-group" id="humanUpdateOpt">
        <label style="display:flex;align-items:center;gap:6px;cursor:pointer;font-weight:normal">
          <input type="checkbox" id="rebuildClusters" style="width:auto"> 同时重建问题库（额外耗时 15-20 分钟，仅人工会话）
        </label>
      </div>
      <div class="form-group" id="humanConvertOpt">
        <div class="form-section">人工会话预检与导出</div>
        <p style="font-size:12px;color:#666;margin-bottom:10px">
          使用上方选择的文件或本地路径。逐句明细按会话聚合为七列；历史会话记录直接预检。上传文件优先于本地路径。
        </p>
        <div class="form-actions" style="margin-top:10px">
          <button class="btn-primary" id="btnConvert" onclick="previewConversion()">预检并生成表格</button>
        </div>
        <div id="conversionResult" style="display:none;margin-top:12px;padding:12px;background:#f7f9fc;border:1px solid #e2e8f0;border-radius:6px">
          <div id="conversionSummary" style="font-size:13px;color:#344054;white-space:pre-line"></div>
          <div class="form-actions" style="margin-top:10px">
            <a id="conversionDownload" class="btn-primary" style="display:none;text-decoration:none" href="#">下载整合后的 Excel</a>
            <button id="btnIndexConverted" class="btn-primary" style="display:none" onclick="indexConvertedWorkbook()">用转换结果更新检索库</button>
          </div>
        </div>
      </div>
      <div class="form-group" id="aiUpdateHint" style="display:none">
        <div class="hint" style="color:#999;font-size:12px">智能客服约 7-8 万条问答，向量化耗时较长（约 1-1.5 小时），请耐心等待进度条完成。</div>
      </div>
      <div class="form-group" id="mediaUpdateOpt" style="display:none">
        <label style="font-weight:normal">从<b>当前已解析的人工会话</b>中用视觉模型重建图片素材库（无需上传文件），严格只留操作教程/参数图、自动剔除隐私工单。</label>
        <label style="margin-top:8px;font-weight:normal;display:flex;align-items:center;gap:6px;font-size:13px">
          保留可入库素材张数 <input type="number" id="mediaTarget" value="2000" min="100" max="11383" style="width:90px">
          （凑够即停，约 1-2 小时）
        </label>
        <div class="hint" style="color:#e8870e;font-size:12px;margin-top:6px">建议顺序：先更新「人工客服会话」，再更新「图片素材库」，素材才会来自最新一周。</div>
      </div>

      <div class="form-actions">
        <button class="btn-primary" id="btnStartUpdate" style="display:none" onclick="startUpdate()">开始更新</button>
      </div>

      <div id="updateProgress" style="display:none;margin-top:16px">
        <div style="display:flex;justify-content:space-between;font-size:13px;margin-bottom:6px">
          <span id="updateStep">准备中...</span>
          <span id="updatePct">0%</span>
        </div>
        <div style="background:#f0f0f0;border-radius:4px;height:8px;overflow:hidden">
          <div id="updateBar" style="background:#4f7cff;height:100%;width:0%;transition:width 0.3s;border-radius:4px"></div>
        </div>
        <div id="updateLogs" style="margin-top:10px;max-height:200px;overflow-y:auto;background:#f9f9fb;border-radius:6px;padding:10px;font-size:12px;color:#666;font-family:monospace;white-space:pre-wrap"></div>
      </div>
    </div>
  </div>
</div>

<script>
function setQuery(q) {
  document.getElementById('query').value = q;
  doSearch();
}

let currentFilters = { model: '', error: '' };
let currentTerms = [];
let lastQuery = '';
let lastResults = [];
let maxScore = 1;

async function doSearch() {
  const query = document.getElementById('query').value.trim();
  if (!query) return;
  lastQuery = query;

  const topK = document.getElementById('topK').value || 10;
  const modelFilter = currentFilters.model || document.getElementById('modelFilter').value.trim();
  const errorFilter = currentFilters.error || '';
  const includeLq = document.getElementById('includeLq').checked ? '1' : '0';
  const agentMediaOnly = document.getElementById('agentMediaOnly').checked ? '1' : '0';

  const btn = document.getElementById('searchBtn');
  const resultsDiv = document.getElementById('results');

  btn.disabled = true;
  btn.textContent = '搜索中...';
  resultsDiv.innerHTML = '<div class="loading">正在检索人工客服解答...</div>';
  document.getElementById('summaryArea').innerHTML = '';
  lastResults = [];
  lastQuery = query;

  try {
    const params = new URLSearchParams({ q: query, top_k: topK, include_lq: includeLq, agent_media_only: agentMediaOnly });
    if (modelFilter) params.append('model', modelFilter);
    if (errorFilter) params.append('error', errorFilter);
    const resp = await fetch('/api/search?' + params.toString());
    const data = await resp.json();
    if (data.error) throw new Error(data.error);
    currentTerms = data.highlight_terms || [];
    lastResults = data.results || [];
    maxScore = lastResults.length ? Math.max.apply(null, lastResults.map(function(r){return r.score;})) : 1;

    if (lastResults.length === 0) {
      resultsDiv.innerHTML = '<div class="welcome"><h2>未找到相关解答</h2><p>试试换个关键词或去掉型号筛选</p></div>';
    } else {
      let html = '<div class="stats"><span>找到 ' + (data.total || lastResults.length) + ' 条相关人工解答，耗时 ' + (data.took || 0) + 's' +
                 (data.reranker_used ? '（Reranker 精排）' : '') + '</span>' +
                 '<button class="btn-ai-summary" onclick="aiSummarize()">AI 总结答案</button></div>';
      html += renderFilterTags(data.filter_tags);
      lastResults.forEach(function(r) {
        html += renderCard(r);
      });
      resultsDiv.innerHTML = html;
    }
  } catch (e) {
    resultsDiv.innerHTML = '<div class="welcome"><h2>检索出错</h2><p>' + e.message + '</p></div>';
  }

  btn.disabled = false;
  btn.textContent = '搜索';
}

// ---------- AI 总结 ----------
async function aiSummarize() {
  if (!lastResults.length) return;
  const area = document.getElementById('summaryArea');
  area.innerHTML = '<div class="ai-summary-card"><div class="ai-summary-header"><span class="ai-badge">AI</span> 正在基于 ' +
    lastResults.length + ' 条人工会话生成总结...</div></div>';
  area.scrollIntoView({behavior: 'smooth', block: 'start'});

  try {
    const resp = await fetch('/api/summarize', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({query: lastQuery, results: lastResults}),
    });
    const data = await resp.json();
    if (data.error) throw new Error(data.error);

    area.innerHTML = '<div class="ai-summary-card">' +
      '<div class="ai-summary-header"><span class="ai-badge">AI</span><b>标准解答总结</b>' +
      '<span class="ai-summary-meta">基于 ' + data.based_on + ' 条人工会话综合</span>' +
      '<button class="ai-summary-close" onclick="closeSummary()">&times;</button></div>' +
      '<div class="ai-summary-body">' + renderMarkdown(data.answer) + '</div></div>';
  } catch (e) {
    area.innerHTML = '<div class="ai-summary-card"><div class="ai-summary-header"><span class="ai-badge">AI</span> 总结失败</div>' +
      '<div class="ai-summary-body" style="color:#e74c3c">' + e.message + '<br><br>请在"API 设置"中检查 AI 总结（LLM）配置。</div></div>';
  }
}

function closeSummary() {
  document.getElementById('summaryArea').innerHTML = '';
}

function renderMarkdown(text) {
  let html = escapeHtml(text);
  html = html.replace(/^## (.+)$/gm, '<h4 style="margin:12px 0 6px;color:#2c3e50">$1</h4>');
  html = html.replace(/^### (.+)$/gm, '<h5 style="margin:10px 0 4px;color:#34495e">$1</h5>');
  html = html.replace(/\*\*(.+?)\*\*/g, '<b>$1</b>');
  html = html.replace(/^(\d+)\. /gm, '<b>$1.</b> ');
  html = html.replace(/\n/g, '<br>');
  return html;
}

function renderFilterTags(tags) {
  if (!tags) return '';
  let html = '';
  if (tags.models && tags.models.length) {
    html += '<div class="filter-tags"><div class="filter-tags-title">型号：</div>';
    tags.models.forEach(function(m) {
      const active = currentFilters.model === m ? ' active' : '';
      html += '<span class="filter-tag' + active + '" onclick="toggleFilter(\'model\',\'' + escapeHtml(m) + '\')">' +
              escapeHtml(m) + '</span>';
    });
    if (currentFilters.model) {
      html += '<span class="filter-clear" onclick="clearFilter(\'model\')">清除筛选</span>';
    }
    html += '</div>';
  }
  if (tags.error_codes && tags.error_codes.length) {
    html += '<div class="filter-tags"><div class="filter-tags-title">错误码：</div>';
    tags.error_codes.forEach(function(e) {
      const active = currentFilters.error === e ? ' active' : '';
      html += '<span class="filter-tag' + active + '" onclick="toggleFilter(\'error\',\'' + escapeHtml(e) + '\')">' +
              escapeHtml(e) + '</span>';
    });
    if (currentFilters.error) {
      html += '<span class="filter-clear" onclick="clearFilter(\'error\')">清除筛选</span>';
    }
    html += '</div>';
  }
  return html;
}

function toggleFilter(type, value) {
  if (currentFilters[type] === value) {
    currentFilters[type] = '';
  } else {
    currentFilters[type] = value;
    if (type === 'model') document.getElementById('modelFilter').value = '';
  }
  doSearch();
}

function clearFilter(type) {
  currentFilters[type] = '';
  if (type === 'model') document.getElementById('modelFilter').value = '';
  doSearch();
}

function escapeHtml(s) {
  const d = document.createElement('div');
  d.textContent = s;
  return d.innerHTML;
}

function highlightText(text) {
  let html = escapeHtml(text);
  if (currentTerms && currentTerms.length) {
    currentTerms.forEach(function(term) {
      if (!term || term.length < 2) return;
      const escaped = term.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
      const re = new RegExp('(' + escaped + ')', 'gi');
      html = html.replace(re, '<span class="hl">$1</span>');
    });
  }
  return html;
}

function renderCard(r) {
  let tags = '';
  if (r.models && r.models.length) {
    r.models.forEach(function(m) { tags += '<span class="tag tag-model">' + escapeHtml(m) + '</span>'; });
  }
  if (r.error_codes && r.error_codes.length) {
    r.error_codes.forEach(function(c) { tags += '<span class="tag tag-error">' + escapeHtml(c) + '</span>'; });
  }
  tags += '<span class="tag tag-agent">' + escapeHtml(r.agent_name || '未知') + '</span>';
  if (r.low_quality) {
    tags += '<span class="tag tag-lowq">低质量</span>';
  }
  const ms = r.media_summary || {};
  if (ms.has_agent_media) {
    let mlabel = '客服素材';
    if (ms.agent_img) mlabel += ' 🖼' + ms.agent_img;
    if (ms.agent_video) mlabel += ' 🎬' + ms.agent_video;
    tags += '<span class="tag tag-media" title="客服在解答中发送了操作图片/视频，点查看原始对话可看">' + mlabel + '</span>';
  }
  const scoreVal = r.rerank_score !== null && r.rerank_score !== undefined ? r.rerank_score : r.score;
  const scorePct = Math.min(100, Math.round(scoreVal / maxScore * 100));
  const scoreColor = scorePct >= 70 ? '#2ba471' : scorePct >= 40 ? '#e8870e' : '#999';
  const scoreLabel = r.rerank_score !== null && r.rerank_score !== undefined ? '精排' : '相关度';

  const steps = r.solution_text.split('\n---\n').filter(function(s){ return s.trim(); });
  let solutionHtml = '';
  const longSolution = r.solution_text.length > 400 || steps.length > 6;
  steps.forEach(function(step, i) {
    const stepHtml = highlightText(step.trim()).replace(/\n/g, '<br>');
    solutionHtml += '<div class="solution-step"><span class="step-num">' + (i+1) + '</span>' + stepHtml + '</div>';
  });

  const cardId = 'sol-' + r.rank + '-' + Math.random().toString(36).substr(2,6);
  const collapseHtml = longSolution ?
    '<div class="solution collapsed" id="' + cardId + '">' + solutionHtml + '</div>' +
    '<button class="btn-expand" onclick="toggleExpand(\'' + cardId + '\', this)">展开全部 ▼</button>' :
    '<div class="solution">' + solutionHtml + '</div>';

  const problemHtml = highlightText(r.problem_text).replace(/\n/g, '<br>');

  return '<div class="card">' +
    '<div class="card-meta">' + tags +
      '<span>' + escapeHtml(r.start_time || '') + '</span>' +
      '<span>' + escapeHtml(r.channel || '') + '</span>' +
    '</div>' +
    '<div class="score-bar" title="' + scoreLabel + ' ' + scoreVal.toFixed(4) + '">' +
      '<span class="score-bar-label">' + scoreLabel + '</span>' +
      '<span class="score-bar-track"><span class="score-bar-fill" style="width:' + scorePct + '%;background:' + scoreColor + '"></span></span>' +
      '<span class="score-bar-val">' + scoreVal.toFixed(3) + '</span>' +
    '</div>' +
    '<div class="section-label">用户问题</div>' +
    '<div class="problem">' + problemHtml + '</div>' +
    '<div class="section-label">人工客服解答（完整过程）</div>' +
    collapseHtml +
    '<div class="card-actions">' +
      '<button class="btn-raw" onclick="showRaw(\'' + r.conv_id + '\')">查看原始对话</button>' +
    '</div>' +
  '</div>';
}

function toggleExpand(id, btn) {
  const el = document.getElementById(id);
  if (el.classList.contains('collapsed')) {
    el.classList.remove('collapsed');
    btn.textContent = '收起 ▲';
  } else {
    el.classList.add('collapsed');
    btn.textContent = '展开全部 ▼';
  }
}

async function showRaw(convId) {
  const modal = document.getElementById('modal');
  const content = document.getElementById('modalContent');
  const meta = document.getElementById('modalMeta');
  document.querySelector('#modal h3').textContent = '原始对话';
  modal.classList.add('active');
  content.innerHTML = '<div class="loading">加载中...</div>';
  meta.textContent = '';

  try {
    const resp = await fetch('/api/conversation/' + encodeURIComponent(convId));
    const data = await resp.json();
    if (data.error) {
      content.innerHTML = '<div class="loading">' + escapeHtml(data.error) + '</div>';
      return;
    }
    meta.textContent = '会话ID: ' + data.conv_id + ' | ' + (data.start_time||'') + ' | 客服: ' + (data.agent_name||'') +
                       ' | 共 ' + data.turns.length + ' 轮';
    const roleNames = { visitor: '访客', agent: '人工客服', bot: '机器人', system: '系统' };
    let html = '';
    data.turns.forEach(function(t) {
      let mediaHtml = '';
      if (t.media && t.media.length) {
        t.media.forEach(function(url) {
          const ext = (url.split('?')[0].split('.').pop() || '').toLowerCase();
          if (['mov', 'mp4', 'avi', 'mkv', 'm4v'].includes(ext)) {
            const isMov = ext === 'mov';
            mediaHtml += '<video src="' + escapeHtml(url) + '" controls class="media-video" preload="metadata" ' +
                         'onerror="this.style.display=\'none\'"></video>' +
                         '<a href="' + escapeHtml(url) + '" target="_blank" class="media-link" download>' +
                         (isMov ? '🎬 视频（.mov 浏览器可能无法播放，点击下载用系统播放器打开）' : '🎬 在新窗口打开视频') + '</a>';
          } else if (['wav', 'amr', 'mp3', 'm4a'].includes(ext)) {
            mediaHtml += '<audio src="' + escapeHtml(url) + '" controls class="media-audio"></audio>';
          } else if (['jpg', 'jpeg', 'png', 'gif', 'webp', 'bmp', 'heic'].includes(ext)) {
            mediaHtml += '<img src="' + escapeHtml(url) + '" class="media-img" loading="lazy" ' +
                         'onclick="showImage(this.src)" onerror="this.style.display=\'none\';this.nextElementSibling.style.display=\'inline\'">' +
                         '<a href="' + escapeHtml(url) + '" target="_blank" class="media-link" style="display:none">🖼️ 图片（新窗口打开）</a>';
          } else {
            mediaHtml += '<a href="' + escapeHtml(url) + '" target="_blank" rel="noopener" class="media-link">打开附件或资源链接</a>';
          }
        });
      }
      html += '<div class="turn turn-' + t.role + '">' +
        '<div class="turn-role">' + roleNames[t.role] + '<span class="turn-time">' + (t.time||'') + '</span></div>' +
        escapeHtml(t.text) + mediaHtml + '</div>';
    });
    content.innerHTML = html;
  } catch (e) {
    content.innerHTML = '<div class="loading">加载失败: ' + escapeHtml(e.message) + '</div>';
  }
}

function closeModal() {
  document.getElementById('modal').classList.remove('active');
}

function showImage(src) {
  document.getElementById('lightboxImg').src = src;
  document.getElementById('lightbox').classList.add('active');
}

function closeLightbox() {
  document.getElementById('lightbox').classList.remove('active');
  document.getElementById('lightboxImg').src = '';
}

document.addEventListener('keydown', function(e) {
  if (e.key === 'Escape') { closeModal(); closeLightbox(); closeSettings(); }
});

// ---------- API 设置 ----------
async function openSettings() {
  const modal = document.getElementById('settingsModal');
  modal.classList.add('active');
  document.getElementById('testResult').className = 'test-result';
  document.getElementById('testResult').textContent = '';
  try {
    const resp = await fetch('/api/config');
    const cfg = await resp.json();
    document.getElementById('cfgEmbUrl').value = cfg.embedding_api_url || '';
    document.getElementById('cfgEmbKey').value = cfg.embedding_api_key || '';
    document.getElementById('cfgEmbDim').value = cfg.embedding_dimensions || 1024;
    document.getElementById('cfgEmbModel').value = cfg.embedding_model || '';
    document.getElementById('cfgRerankUrl').value = cfg.reranker_api_url || '';
    document.getElementById('cfgRerankKey').value = cfg.reranker_api_key || '';
    document.getElementById('cfgRerankModel').value = cfg.reranker_model || '';
    document.getElementById('cfgLlmUrl').value = cfg.llm_api_url || '';
    document.getElementById('cfgLlmKey').value = cfg.llm_api_key || '';
    document.getElementById('cfgLlmModel').value = cfg.llm_model || '';
    document.getElementById('cfgLlmTemp').value = cfg.llm_temperature ?? 0.3;

    const status = document.getElementById('configStatus');
    if (cfg.embedding_api_key) {
      status.innerHTML = '<div class="config-status config-ok">当前使用 API Embedding' +
        (cfg.reranker_api_key ? ' + Reranker 精排' : '') +
        (cfg.llm_api_key ? ' + AI 总结' : '') +
        '。修改 Key 后需重建索引生效。</div>';
    } else {
      status.innerHTML = '<div class="config-status config-warn">当前使用本地模型（bge-small-zh），配置 API Key 并重建索引后可获得更好效果。</div>';
    }
  } catch (e) {
    document.getElementById('configStatus').innerHTML =
      '<div class="config-status config-warn">加载配置失败: ' + e.message + '</div>';
  }
}

function closeSettings() {
  document.getElementById('settingsModal').classList.remove('active');
}

function collectConfig() {
  const embKey = document.getElementById('cfgEmbKey').value.trim();
  const rerankKey = document.getElementById('cfgRerankKey').value.trim() || embKey;
  const llmKey = document.getElementById('cfgLlmKey').value.trim() || embKey;
  return {
    embedding_api_url: document.getElementById('cfgEmbUrl').value.trim(),
    embedding_api_key: embKey,
    embedding_dimensions: parseInt(document.getElementById('cfgEmbDim').value) || 1024,
    embedding_model: document.getElementById('cfgEmbModel').value.trim(),
    reranker_api_url: document.getElementById('cfgRerankUrl').value.trim(),
    reranker_api_key: rerankKey,
    reranker_model: document.getElementById('cfgRerankModel').value.trim(),
    reranker_top_n: 50,
    llm_api_url: document.getElementById('cfgLlmUrl').value.trim(),
    llm_api_key: llmKey,
    llm_model: document.getElementById('cfgLlmModel').value.trim(),
    llm_temperature: parseFloat(document.getElementById('cfgLlmTemp').value) || 0.3,
    llm_max_tokens: 2048,
  };
}

async function saveConfig() {
  const cfg = collectConfig();
  try {
    const resp = await fetch('/api/config', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(cfg),
    });
    const data = await resp.json();
    if (data.ok) {
      const tr = document.getElementById('testResult');
      tr.className = 'test-result test-ok';
      tr.textContent = '配置已保存。' + (cfg.embedding_api_key ? '请在终端运行 python3 update.py <xlsx路径> 重建索引以使用 API。' : '');
    } else {
      throw new Error(data.error || '保存失败');
    }
  } catch (e) {
    const tr = document.getElementById('testResult');
    tr.className = 'test-result test-err';
    tr.textContent = '保存失败: ' + e.message;
  }
}

async function testConfig() {
  const cfg = collectConfig();
  const tr = document.getElementById('testResult');
  tr.className = 'test-result';
  tr.textContent = '测试中...';
  try {
    await fetch('/api/config', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(cfg),
    });
    const resp = await fetch('/api/test-config');
    const data = await resp.json();
    if (data.ok) {
      tr.className = 'test-result test-ok';
      tr.textContent = '连接成功！Embedding 维度: ' + (data.embedding_dim || '?') +
        (data.reranker_ok ? '，Reranker 正常' : '，Reranker 未配置或不可用') +
        (data.llm_ok ? '，AI 总结正常' : '，AI 总结未配置或不可用');
    } else {
      tr.className = 'test-result test-err';
      tr.textContent = '连接失败: ' + (data.error || '未知错误');
    }
  } catch (e) {
    tr.className = 'test-result test-err';
    tr.textContent = '测试失败: ' + e.message;
  }
}

// ---------- Tab 切换 ----------
function switchTab(name) {
  document.querySelectorAll('.tab').forEach(function(t) { t.classList.remove('active'); });
  document.querySelectorAll('.tab-panel').forEach(function(p) { p.classList.remove('active'); });
  event.target.classList.add('active');
  document.getElementById('tab-' + name).classList.add('active');
  if (name === 'dict') loadDict();
}

// ---------- 词典维护 ----------
let dictData = { words: [], synonyms: [] };
let userWords = [];
let userSynonyms = {};

async function loadDict() {
  try {
    const resp = await fetch('/api/dict');
    dictData = await resp.json();
    userWords = dictData.words.filter(function(w){ return !w.builtin; }).map(function(w){ return w.word; });
    userSynonyms = {};
    dictData.synonyms.forEach(function(s) {
      if (!s.builtin) userSynonyms[s.key] = s.words;
    });
    renderWordList();
    renderSynList();
  } catch (e) {
    document.getElementById('wordList').innerHTML = '<span style="color:#e54545;font-size:12px">加载失败: ' + e.message + '</span>';
  }
}

function renderWordList() {
  let html = '';
  dictData.words.forEach(function(w) {
    const cls = w.builtin ? 'builtin' : '';
    const del = w.builtin ? '' : '<span class="dict-del" onclick="removeWord(\'' + escapeHtml(w.word).replace(/'/g,"\\'") + '\')">×</span>';
    html += '<span class="dict-item ' + cls + '">' + escapeHtml(w.word) + del + '</span>';
  });
  document.getElementById('wordList').innerHTML = html;
}

function renderSynList() {
  let html = '';
  dictData.synonyms.forEach(function(s) {
    const delKey = s.builtin ? '' : '<span class="dict-del" onclick="removeSyn(\'' + escapeHtml(s.key).replace(/'/g,"\\'") + '\')">删除组</span>';
    html += '<div class="syn-group"><span class="syn-key">' + escapeHtml(s.key) + '</span> ' + delKey +
            '<div class="syn-words">' + s.words.map(escapeHtml).join('、') + '</div></div>';
  });
  document.getElementById('synList').innerHTML = html;
}

function addWord() {
  const input = document.getElementById('newWord');
  const w = input.value.trim();
  if (!w) return;
  if (dictData.words.find(function(x){ return x.word === w; })) {
    input.value = ''; return;
  }
  dictData.words.push({ word: w, builtin: false });
  userWords.push(w);
  renderWordList();
  input.value = '';
}

function removeWord(w) {
  dictData.words = dictData.words.filter(function(x){ return x.word !== w; });
  userWords = userWords.filter(function(x){ return x !== w; });
  renderWordList();
}

function addSynonym() {
  const key = document.getElementById('newSynKey').value.trim();
  const wordsStr = document.getElementById('newSynWords').value.trim();
  if (!key || !wordsStr) return;
  const words = wordsStr.split(/[,，、]/).map(function(s){ return s.trim(); }).filter(Boolean);
  if (!words.length) return;
  // 如果已存在同名组，追加
  const existing = dictData.synonyms.find(function(s){ return s.key === key; });
  if (existing) {
    words.forEach(function(w){ if (existing.words.indexOf(w) < 0) existing.words.push(w); });
    if (!existing.builtin) userSynonyms[key] = existing.words;
  } else {
    dictData.synonyms.push({ key: key, words: words, builtin: false });
    userSynonyms[key] = words;
  }
  renderSynList();
  document.getElementById('newSynKey').value = '';
  document.getElementById('newSynWords').value = '';
}

function removeSyn(key) {
  dictData.synonyms = dictData.synonyms.filter(function(s){ return s.key !== key; });
  delete userSynonyms[key];
  renderSynList();
}

async function saveDict() {
  try {
    const resp = await fetch('/api/dict', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ custom_words: userWords, user_synonyms: userSynonyms }),
    });
    const data = await resp.json();
    if (data.ok) {
      alert('词典已保存，BM25 索引已重建');
    }
  } catch (e) {
    alert('保存失败: ' + e.message);
  }
}

// ---------- 顶部数据状态栏 ----------

// ---------- 主 Tab 切换 ----------
function switchMainTab(tab) {
  document.querySelectorAll('.main-tab').forEach(function(t){ t.classList.remove('active'); });
  const panels = {search:'panel-search', cluster:'panel-cluster', media:'panel-media'};
  Object.keys(panels).forEach(function(k){
    document.getElementById(panels[k]).style.display = (k === tab) ? '' : 'none';
  });
  document.getElementById('tab-' + tab + '-btn').classList.add('active');
  // 会话检索相关区域只在 search 显示
  const isSearch = tab === 'search';
  document.getElementById('results').style.display = isSearch ? '' : 'none';
  document.getElementById('summaryArea').style.display = isSearch ? '' : 'none';
  document.getElementById('statusBar').style.display = isSearch ? '' : 'none';
  document.getElementById('clusterResults').style.display = (tab === 'cluster') ? '' : 'none';
  if (tab === 'cluster' && !clustersLoaded) loadClusters();
  if (tab === 'media' && !mediaLoaded) { loadMediaStats(); doMediaSearch(); }
}

// ---------- 图片素材库 ----------
let mediaLoaded = false;
let mediaType = '';
let mediaOffset = 0;
const MEDIA_LIMIT = 60;
let mediaTotal = 0;

async function loadMediaStats() {
  try {
    const s = await (await fetch('/api/media/stats')).json();
    const el = document.getElementById('mediaStat');
    if (!s.available) { el.textContent = '素材库尚未生成'; return; }
    el.textContent = '共 ' + s.total + ' 张可入库素材（含文字 ' + s.with_ocr + ' 张）';
  } catch (e) {}
}

function setMediaType(el) {
  document.querySelectorAll('#mediaFilters .qchip').forEach(function(c){ c.classList.remove('active'); });
  el.classList.add('active');
  mediaType = el.dataset.t || '';
  doMediaSearch();
}

async function doMediaSearch() {
  mediaOffset = 0;
  document.getElementById('mediaResults').innerHTML = '<div class="loading">加载素材中...</div>';
  await appendMedia(true);
  mediaLoaded = true;
}

async function loadMoreMedia() { mediaOffset += MEDIA_LIMIT; await appendMedia(false); }

async function appendMedia(replace) {
  const q = document.getElementById('mediaQuery').value.trim();
  const p = new URLSearchParams({q: q, limit: MEDIA_LIMIT, offset: mediaOffset});
  if (mediaType) p.append('type', mediaType);
  let data;
  try {
    const resp = await fetch('/api/media/search?' + p.toString());
    data = await resp.json();
    if (!resp.ok) throw new Error(data.error || '加载失败');
  } catch (e) {
    if (replace) document.getElementById('mediaResults').innerHTML =
      '<div class="welcome"><p>' + escapeHtml(e.message) + '</p></div>';
    return;
  }
  currentTerms = data.highlight_terms || [];
  mediaTotal = data.total || 0;
  const box = document.getElementById('mediaResults');
  const mediaResults = data.results || [];
  const html = mediaResults.map(renderMediaCard).join('');
  box.innerHTML = replace ? html : box.innerHTML + html;
  if (replace && !mediaResults.length) {
    box.innerHTML = '<div class="welcome"><p>没有匹配的素材，换个关键词试试</p></div>';
  }
  document.getElementById('mediaMoreWrap').style.display =
    (mediaOffset + mediaResults.length < mediaTotal) ? '' : 'none';
}

function renderMediaCard(a) {
  const ocr = (a.ocr || '').trim();
  const models = (a.models || []).map(function(m){return '<span class="tag tag-model">'+escapeHtml(m)+'</span>';}).join('');
  let ocrHtml = '';
  if (ocr) {
    const cid = 'ocr-' + Math.random().toString(36).substr(2,6);
    const clickable = ocr.length > 160;
    ocrHtml = '<div class="media-ocr'+(clickable?'':'')+'" id="'+cid+'"'+
      (clickable?' onclick="this.classList.toggle(\'expanded\')" title="点击展开/收起"':'')+'>' +
      highlightText(ocr).replace(/\n/g,'<br>') + '</div>';
  }
  const ctxParts = [];
  if (a.question) ctxParts.push('<div>用户问题：<b>'+escapeHtml(a.question)+'</b></div>');
  if (a.caption && a.caption.replace(/\[图片\]/g,'').trim()) ctxParts.push('<div>客服配文：'+escapeHtml(a.caption)+'</div>');
  return '<div class="media-card">'+
    '<img class="media-thumb" loading="lazy" src="'+escapeHtml(a.url)+'" onclick="showImage(this.src)" onerror="this.style.opacity=.3;this.alt=\'图片加载失败\'">'+
    '<div class="media-body">'+
      '<div class="media-desc">'+highlightText(a.desc||'')+'</div>'+
      (models?'<div>'+models+'</div>':'')+
      ocrHtml+
      (ctxParts.length?'<div class="media-ctx">'+ctxParts.join('')+'</div>':'')+
      '<div class="media-foot"><span class="media-type">'+escapeHtml(a.type||'')+'</span>'+
      '<button class="btn-src" onclick="showRaw(\''+a.conv_id+'\')" title="打开这张图所在的完整人工会话">🔗 反查来源会话</button></div>'+
    '</div></div>';
}

// ---------- 问题库 ----------
let clustersLoaded = false;
let allClusters = [];

async function loadClusters() {
  const area = document.getElementById('clusterResults');
  area.innerHTML = '<div class="loading">正在加载问题库...</div>';
  try {
    const resp = await fetch('/api/clusters?per_page=200');
    const data = await resp.json();
    if (data.error) {
      area.innerHTML = '<div class="welcome"><h2>问题库尚未生成</h2><p>' + data.error + '</p></div>';
      return;
    }
    allClusters = data.clusters || [];
    clustersLoaded = true;
    renderClusters(allClusters, data.total);
  } catch (e) {
    area.innerHTML = '<div class="welcome"><h2>加载失败</h2><p>' + e.message + '</p></div>';
  }
}

async function searchClusters() {
  const q = document.getElementById('clusterQuery').value.trim();
  const area = document.getElementById('clusterResults');
  area.innerHTML = '<div class="loading">搜索中...</div>';
  try {
    const params = new URLSearchParams({per_page: 100});
    if (q) params.append('q', q);
    const resp = await fetch('/api/clusters?' + params.toString());
    const data = await resp.json();
    renderClusters(data.clusters || [], data.total, q);
  } catch (e) {
    area.innerHTML = '<div class="welcome"><h2>搜索失败</h2><p>' + e.message + '</p></div>';
  }
}

function renderClusters(clusters, total, query) {
  const area = document.getElementById('clusterResults');
  if (!clusters.length) {
    area.innerHTML = '<div class="welcome"><h2>未找到匹配的问题组</h2><p>试试其他关键词</p></div>';
    return;
  }
  let html = '<div class="stats">共 ' + total + ' 个问题组' + (query ? '（关键词：' + escapeHtml(query) + '）' : '') + '</div>';
  clusters.forEach(function(c) {
    let tags = '';
    if (c.models && c.models.length) {
      c.models.slice(0, 4).forEach(function(m){ tags += '<span class="tag tag-model">' + escapeHtml(m) + '</span>'; });
    }
    if (c.error_codes && c.error_codes.length) {
      c.error_codes.slice(0, 3).forEach(function(e){ tags += '<span class="tag tag-error">' + escapeHtml(e) + '</span>'; });
    }
    html += '<div class="cluster-card" id="cluster-' + c.id + '" onclick="toggleCluster(' + c.id + ', this)">' +
      '<div class="cluster-card-header">' +
        '<div class="cluster-title">' + escapeHtml(c.title) + '</div>' +
        '<span class="cluster-size">' + c.size + ' 条会话</span>' +
      '</div>' +
      '<div class="cluster-preview">' + escapeHtml(c.answer_preview || '') + '</div>' +
      (tags ? '<div class="cluster-tags">' + tags + '</div>' : '') +
      '<div class="cluster-detail" id="cluster-detail-' + c.id + '"><div class="loading">加载中...</div></div>' +
    '</div>';
  });
  area.innerHTML = html;
}

async function toggleCluster(id, el) {
  const detail = document.getElementById('cluster-detail-' + id);
  if (el.classList.contains('expanded')) {
    el.classList.remove('expanded');
    return;
  }
  el.classList.add('expanded');
  try {
    const resp = await fetch('/api/clusters/' + id);
    const data = await resp.json();
    let html = '<div class="cluster-answer">' + renderMarkdown(data.answer) + '</div>';
    html += '<div class="section-label" style="margin-top:14px">原始会话（' + data.conversations.length + '/' + data.size + '）</div>';
    html += '<div class="cluster-sources">';
    data.conversations.forEach(function(conv) {
      html += '<div class="cluster-source">' +
        '<div class="cluster-source-problem">' + escapeHtml(conv.problem_text.substring(0, 150)) + '</div>' +
        '<div class="cluster-source-solution">' + escapeHtml(conv.solution_text.substring(0, 300)) + '...</div>' +
        '<button class="btn-raw" style="margin-top:6px" onclick="event.stopPropagation();showRaw(\'' + conv.conv_id + '\')">查看完整对话</button>' +
      '</div>';
    });
    html += '</div>';
    detail.innerHTML = html;
  } catch (e) {
    detail.innerHTML = '<div style="color:#e74c3c">加载失败: ' + e.message + '</div>';
  }
}

// ---------- 数据更新 ----------
let updatePolling = null;

let updateCorpus = 'human';
function setUpdateCorpus(c) {
  updateCorpus = c;
  document.getElementById('upd-human').classList.toggle('active', c === 'human');
  document.getElementById('upd-ai').classList.toggle('active', c === 'ai');
  document.getElementById('upd-media').classList.toggle('active', c === 'media');
  // 图片素材库不需要上传文件
  document.getElementById('fileUpdateOpt').style.display = c === 'media' ? 'none' : '';
  document.getElementById('humanUpdateOpt').style.display = c === 'human' ? '' : 'none';
  document.getElementById('humanConvertOpt').style.display = c === 'human' ? '' : 'none';
  document.getElementById('humanFormatOpt').style.display = c === 'human' ? '' : 'none';
  document.getElementById('btnStartUpdate').style.display = c === 'human' ? 'none' : '';
  document.getElementById('aiUpdateHint').style.display = c === 'ai' ? '' : 'none';
  document.getElementById('mediaUpdateOpt').style.display = c === 'media' ? '' : 'none';
  document.getElementById('updateFilePath').placeholder = c === 'ai'
    ? '/Users/.../近一周会话数据.xlsx'
    : '/Volumes/ORICO/会话记录/每周会话/会话记录_xxx.xlsx';
}

let convertedWorkbookToken = null;
let conversionGeneration = 0;
function invalidateConversion() {
  conversionGeneration++;
  convertedWorkbookToken = null;
  document.getElementById('conversionResult').style.display = 'none';
}
async function previewConversion() {
  const input = document.getElementById('updateFile');
  const path = document.getElementById('updateFilePath').value.trim();
  if (!input.files.length && !path) {
    alert('请选择 Excel 文件或填写本地文件路径');
    return;
  }
  const button = document.getElementById('btnConvert');
  const generation = conversionGeneration;
  const result = document.getElementById('conversionResult');
  const summary = document.getElementById('conversionSummary');
  button.disabled = true;
  button.textContent = '正在转换...';
  result.style.display = '';
  summary.textContent = '正在读取工作表并聚合会话，请稍候。';
  document.getElementById('conversionDownload').style.display = 'none';
  document.getElementById('btnIndexConverted').style.display = 'none';
  try {
    const form = new FormData();
    if (input.files.length) form.append('file', input.files[0]);
    else form.append('path', path);
    form.append('input_format', document.getElementById('humanInputFormat').value);
    const response = await fetch('/api/human-conversion/preview', {method: 'POST', body: form});
    const data = await response.json();
    if (generation !== conversionGeneration) return;
    if (!response.ok) throw new Error(data.error || '转换失败');
    convertedWorkbookToken = data.token;
    const s = data.stats;
    summary.textContent = `预检完成，识别为${s.input_format === 'detail' ? '逐句明细' : '历史会话记录'}\n工作表：${s.sheet_count} 个\n会话：${s.session_count.toLocaleString()} 条，导出记录：${s.output_row_count.toLocaleString()} 行\n可入检索库：${s.indexed_count.toLocaleString()} 条，质量规则过滤：${s.filtered_count.toLocaleString()} 条`;
    if (s.input_format === 'detail') summary.textContent += `\n消息：${s.message_count.toLocaleString()} 条\n自动拆分超长会话：${s.split_sessions.toLocaleString()} 条，生成 ${s.split_parts.toLocaleString()} 段\n跨工作表重复会话ID：${s.duplicate_session_ids_across_sheets.toLocaleString()} 个\n缺少会话ID而跳过：${s.missing_session_id.toLocaleString()} 条\n媒体链接替换：空内容 ${s.empty_content_media.toLocaleString()}、占位内容 ${s.placeholder_media.toLocaleString()}、文字追加 ${s.text_media.toLocaleString()}`;
    summary.textContent += '\n下载包含全部有效会话；更新仅纳入符合检索质量规则的会话。';
    const link = document.getElementById('conversionDownload');
    link.href = data.download_url;
    link.style.display = '';
    document.getElementById('btnIndexConverted').style.display = '';
    document.getElementById('btnIndexConverted').disabled = !s.indexed_count;
  } catch (error) {
    convertedWorkbookToken = null;
    summary.textContent = '转换失败：' + error.message;
  } finally {
    button.disabled = false;
    button.textContent = '预检并生成表格';
  }
}

async function indexConvertedWorkbook() {
  if (!convertedWorkbookToken) return;
  const button = document.getElementById('btnIndexConverted');
  button.disabled = true;
  button.textContent = '正在启动...';
  let started = false;
  try {
    const response = await fetch(`/api/human-conversion/${convertedWorkbookToken}/update`, {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({rebuild_clusters: document.getElementById('rebuildClusters').checked}),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || '启动失败');
    started = true;
    button.textContent = '检索库更新中...';
    document.getElementById('updateProgress').style.display = '';
    document.getElementById('updateLogs').textContent = '';
    document.getElementById('updateBar').style.background = '#4f7cff';
    if (updatePolling) clearInterval(updatePolling);
    updatePolling = setInterval(pollUpdateStatus, 1500);
    pollUpdateStatus();
  } catch (error) {
    alert('更新失败: ' + error.message);
  } finally {
    if (!started) {
      button.disabled = false;
      button.textContent = '用转换结果更新检索库';
    }
  }
}

async function startUpdate() {
  const filePath = document.getElementById('updateFilePath').value.trim();
  const fileInput = document.getElementById('updateFile');
  const rebuildClusters = document.getElementById('rebuildClusters').checked;
  const btn = document.getElementById('btnStartUpdate');

  // 图片素材库无需文件，直接启动
  if (updateCorpus !== 'media' && !filePath && !fileInput.files.length) {
    alert('请填写文件路径或选择 Excel 文件');
    return;
  }

  btn.disabled = true;
  btn.textContent = '更新中...';
  document.getElementById('updateProgress').style.display = '';
  document.getElementById('updateLogs').textContent = '';
  document.getElementById('updateBar').style.background = '#4f7cff';

  try {
    let resp;
    if (updateCorpus === 'media') {
      const mediaTarget = parseInt(document.getElementById('mediaTarget').value || '2000', 10);
      const formData = new FormData();
      formData.append('corpus', 'media');
      formData.append('media_target', mediaTarget);
      resp = await fetch('/api/update', {method: 'POST', body: formData});
    } else if (fileInput.files.length) {
      const formData = new FormData();
      formData.append('file', fileInput.files[0]);
      formData.append('rebuild_clusters', rebuildClusters);
      formData.append('corpus', updateCorpus);
      resp = await fetch('/api/update', {method: 'POST', body: formData});
    } else {
      resp = await fetch('/api/update', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({path: filePath, rebuild_clusters: rebuildClusters, corpus: updateCorpus}),
      });
    }
    const data = await resp.json();
    if (!resp.ok) throw new Error(data.error || '启动失败');

    if (updatePolling) clearInterval(updatePolling);
    updatePolling = setInterval(pollUpdateStatus, 1500);
    pollUpdateStatus();
  } catch (e) {
    alert('更新失败: ' + e.message);
  } finally {
    btn.disabled = false;
    btn.textContent = '开始更新';
  }
}

async function pollUpdateStatus() {
  try {
    const resp = await fetch('/api/update-status');
    const s = await resp.json();

    const stepNames = {parse: '解析 Excel', index: '构建索引', cluster: '重建问题库', media: '构建图片素材库', reload: '重载索引'};
    document.getElementById('updateStep').textContent =
      (stepNames[s.step] || s.step || '') + (s.message ? ' - ' + s.message : '');
    document.getElementById('updatePct').textContent = s.progress + '%';
    document.getElementById('updateBar').style.width = s.progress + '%';

    const logsEl = document.getElementById('updateLogs');
    logsEl.textContent = s.logs.join('\n');
    logsEl.scrollTop = logsEl.scrollHeight;
    if (s.done || s.error || !s.running) {
      const convertedButton = document.getElementById('btnIndexConverted');
      convertedButton.disabled = false;
      convertedButton.textContent = '用转换结果更新检索库';
    }

    if (s.error) {
      clearInterval(updatePolling);
      document.getElementById('updateStep').textContent = '失败: ' + s.error;
      document.getElementById('updateBar').style.background = '#e74c3c';
      const btn = document.getElementById('btnStartUpdate');
      btn.disabled = false;
      btn.textContent = '开始更新';
    } else if (s.done) {
      clearInterval(updatePolling);
      document.getElementById('updateStep').textContent = '更新完成！';
      document.getElementById('updateBar').style.background = '#2ba471';
      const btn = document.getElementById('btnStartUpdate');
      btn.disabled = false;
      btn.textContent = '开始更新';
      loadStats();
      if (s.corpus === 'ai') loadAiStats();
      if (s.corpus === 'media') { loadMediaStats(); mediaLoaded = false; doMediaSearch(); }
    } else if (!s.running) {
      // 兜底：后台已停止但既没完成也没报错，避免按钮永远停在"更新中..."
      clearInterval(updatePolling);
      document.getElementById('updateStep').textContent = '更新已中断（未完成），可重新点击开始更新';
      document.getElementById('updateBar').style.background = '#e74c3c';
      const btn = document.getElementById('btnStartUpdate');
      btn.disabled = false;
      btn.textContent = '开始更新';
    }
  } catch (e) {
    // 忽略轮询错误
  }
}

async function loadStats() {
  try {
    const resp = await fetch('/api/stats');
    const s = await resp.json();
    const modelLabel = s.use_api ? 'API 向量' : '本地模型';
    const rerankLabel = s.reranker_enabled ? ' + Reranker' : '';
    document.getElementById('statusBar').innerHTML =
      '<span class="status-item"><span class="status-dot"></span>数据周期 <b>' + s.date_range + '</b></span>' +
      '<span class="status-item">会话 <b>' + s.total.toLocaleString() + '</b> 条</span>' +
      '<span class="status-item">型号 <b>' + s.model_count + '</b> · 错误码 <b>' + s.error_count + '</b></span>' +
      '<span class="status-item">索引更新 <b>' + s.index_updated + '</b></span>' +
      '<span class="status-item">检索模式 <b>' + modelLabel + rerankLabel + '</b></span>';
  } catch (e) {
    document.getElementById('statusBar').innerHTML =
      '<span class="status-item" style="color:#e74c3c">状态加载失败</span>';
  }
}
loadStats();

// ==================== 智能客服（AI）问答检索 ====================
let currentCorpus = 'human';
let aiFilters = {product:'', category:'', cat3:''};
let aiChipFilter = {};   // 快捷视角
let lastAiResults = [];
let aiMaxScore = 1;

function switchCorpus(c) {
  currentCorpus = c;
  document.body.classList.toggle('corpus-ai', c === 'ai');
  document.getElementById('corpus-human').classList.toggle('active', c === 'human');
  document.getElementById('corpus-ai').classList.toggle('active', c === 'ai');
  if (c === 'ai') loadAiStats();
}

function setAiQuery(q) {
  document.getElementById('aiQuery').value = q;
  doAiSearch();
}

function toggleAiChip(el) {
  const k = el.dataset.k, v = el.dataset.v;
  if (aiChipFilter[k] === v) { delete aiChipFilter[k]; el.classList.remove('active'); }
  else { aiChipFilter[k] = v; el.classList.add('active');
    document.querySelectorAll('#aiChips .qchip').forEach(function(x){ if(x!==el) x.classList.remove('active'); }); }
  doAiSearch();
}

function toggleAiFacet(type, value) {
  aiFilters[type] = (aiFilters[type] === value) ? '' : value;
  if (type === 'product') document.getElementById('aiProduct').value = '';
  doAiSearch();
}
function clearAiFacet(type) { aiFilters[type] = ''; doAiSearch(); }

async function doAiSearch() {
  const query = document.getElementById('aiQuery').value.trim();
  if (!query) return;
  const topK = document.getElementById('aiTopK').value || 10;
  const includeHidden = document.getElementById('aiIncludeHidden').checked ? '1' : '0';
  const btn = document.getElementById('aiSearchBtn');
  const box = document.getElementById('aiResults');
  btn.disabled = true; btn.textContent = '搜索中...';
  box.innerHTML = '<div class="loading">正在检索智能客服问答...</div>';

  const params = new URLSearchParams({q: query, top_k: topK, include_hidden: includeHidden});
  const prodText = document.getElementById('aiProduct').value.trim();
  // 产品筛选：优先用输入框，否则用结果标签点选
  if (prodText) params.append('product', prodText);
  else if (aiFilters.product) params.append('product', aiFilters.product);
  if (aiFilters.category) params.append('category', aiFilters.category);
  if (aiFilters.cat3) params.append('cat3', aiFilters.cat3);
  Object.keys(aiChipFilter).forEach(function(k){ params.append(k, aiChipFilter[k]); });

  try {
    const resp = await fetch('/api/ai/search?' + params.toString());
    const data = await resp.json();
    if (data.error) throw new Error(data.error);
    currentTerms = data.highlight_terms || [];
    lastAiResults = data.results || [];
    aiMaxScore = lastAiResults.length ? Math.max.apply(null, lastAiResults.map(r=>r.score)) : 1;
    if (!lastAiResults.length) {
      box.innerHTML = '<div class="welcome"><h2>未找到相关问答</h2><p>试试换个关键词、清除筛选或勾选"显示转人工/识图类"</p></div>';
    } else {
      let html = '<div class="stats"><span>找到 ' + (data.total || lastAiResults.length) + ' 条智能客服问答，耗时 ' + (data.took || 0) + 's' +
                 (data.reranker_used ? '（Reranker 精排）' : '') + '</span></div>';
      html += renderAiFacets(data.facets);
      lastAiResults.forEach(function(r){ html += renderAiCard(r); });
      box.innerHTML = html;
    }
  } catch (e) {
    box.innerHTML = '<div class="welcome"><h2>检索出错</h2><p>' + escapeHtml(e.message) + '</p></div>';
  }
  btn.disabled = false; btn.textContent = '搜索';
}

function renderAiFacets(f) {
  if (!f) return '';
  let html = '';
  function facetRow(title, key, arr) {
    if (!arr || !arr.length) return '';
    let s = '<div class="filter-tags"><div class="filter-tags-title">' + title + '：</div>';
    arr.forEach(function(v){
      const active = aiFilters[key] === v ? ' active' : '';
      s += '<span class="filter-tag' + active + '" onclick="toggleAiFacet(\'' + key + '\',\'' + escapeHtml(String(v).replace(/'/g,"\\'")) + '\')">' + escapeHtml(v) + '</span>';
    });
    if (aiFilters[key]) s += '<span class="filter-clear" onclick="clearAiFacet(\'' + key + '\')">清除筛选</span>';
    return s + '</div>';
  }
  html += facetRow('产品', 'product', f.products);
  html += facetRow('品类', 'category', f.categories);
  html += facetRow('三级分类', 'cat3', f.cat3);
  return html;
}

function renderAiCard(r) {
  let tags = '';
  if (r.product) tags += '<span class="tag tag-model">' + escapeHtml(r.product) + '</span>';
  if (r.product_category) tags += '<span class="tag tag-cat">' + escapeHtml(r.product_category) + '</span>';
  if (r.cat3) tags += '<span class="tag tag-cat">' + escapeHtml(r.cat3) + '</span>';
  if (r.qtype) tags += '<span class="tag tag-qtype">' + escapeHtml(r.qtype) + '</span>';
  if (r.eff_recall === '1') tags += '<span class="tag tag-good">有效召回</span>';
  else if (r.eff_recall === '0') tags += '<span class="tag tag-bad">无效召回</span>';
  if (r.to_human === '1') tags += '<span class="tag tag-bad">已转人工</span>';
  if (r.vote === 'up') tags += '<span class="tag tag-good">赞</span>';
  if (r.vote === 'down') tags += '<span class="tag tag-bad">踩' + (r.vote_reason ? '·'+escapeHtml(r.vote_reason) : '') + '</span>';
  if (r.hidden) tags += '<span class="tag tag-hidden">转人工/识图类</span>';

  const scoreVal = (r.rerank_score !== null && r.rerank_score !== undefined) ? r.rerank_score : r.score;
  const pct = Math.min(100, Math.round(scoreVal / aiMaxScore * 100));
  const color = pct >= 70 ? '#2ba471' : pct >= 40 ? '#e8870e' : '#999';
  const sLabel = (r.rerank_score !== null && r.rerank_score !== undefined) ? '精排' : '相关度';

  let answerHtml = renderMarkdown(r.answer || '（无答案文本）');
  const long = (r.answer || '').length > 500;
  const cid = 'aians-' + r.rank + '-' + Math.random().toString(36).substr(2,6);
  const answerBlock = long
    ? '<div class="solution collapsed" id="' + cid + '">' + answerHtml + '</div>' +
      '<button class="btn-expand" onclick="toggleExpand(\'' + cid + '\', this)">展开全部 ▼</button>'
    : '<div class="solution">' + answerHtml + '</div>';

  let kb = '';
  if (r.adopted_kb && r.adopted_kb.length) {
    kb = '<details class="ai-kb"><summary>采纳的知识库 KB（' + r.adopted_kb.length + '）</summary><ul class="ai-kb-list">' +
         r.adopted_kb.slice(0, 30).map(function(k){return '<li>'+escapeHtml(k)+'</li>';}).join('') + '</ul></details>';
  }

  const rewrite = (r.rewrite && r.rewrite !== r.question)
    ? '<div class="ai-qsrc">改写：' + highlightText(escapeHtml(r.rewrite)) + '</div>' : '';

  return '<div class="card">' +
    '<div class="card-meta">' + tags +
      '<span>' + escapeHtml(r.date || '') + '</span><span>' + escapeHtml(r.channel || '') + '</span></div>' +
    '<div class="score-bar" title="' + sLabel + ' ' + scoreVal.toFixed(4) + '">' +
      '<span class="score-bar-label">' + sLabel + '</span>' +
      '<span class="score-bar-track"><span class="score-bar-fill" style="width:' + pct + '%;background:' + color + '"></span></span>' +
      '<span class="score-bar-val">' + scoreVal.toFixed(3) + '</span></div>' +
    '<div class="section-label">用户问题</div><div class="problem">' + highlightText(escapeHtml(r.question)) + '</div>' +
    rewrite +
    '<div class="section-label">智能客服（大模型）回答</div>' + answerBlock + kb +
    '<div class="card-actions"><button class="btn-raw" onclick="showAiSession(\'' + escapeHtml(r.session_id) + '\')">查看同会话上下文</button></div>' +
  '</div>';
}

async function showAiSession(sid) {
  const modal = document.getElementById('modal');
  document.querySelector('#modal h3').textContent = '同会话问答（' + sid + '）';
  document.getElementById('modalMeta').innerHTML = '';
  const content = document.getElementById('modalContent');
  content.innerHTML = '<div class="loading">加载中...</div>';
  modal.classList.add('active');
  try {
    const resp = await fetch('/api/ai/session/' + encodeURIComponent(sid));
    const data = await resp.json();
    if (data.error) throw new Error(data.error);
    let html = '';
    data.turns.forEach(function(t, i){
      const tags = (t.product ? '<span class="tag tag-model">'+escapeHtml(t.product)+'</span>' : '') +
                   (t.cat3 ? '<span class="tag tag-cat">'+escapeHtml(t.cat3)+'</span>' : '') +
                   (t.hidden ? '<span class="tag tag-hidden">'+escapeHtml(t.qtype||'')+'</span>' : '');
      html += '<div class="solution-step"><span class="step-num">' + (i+1) + '</span>' +
        '<div style="color:#999;font-size:12px;margin-bottom:4px">' + escapeHtml(t.date||'') + ' ' + tags + '</div>' +
        '<div><b>问：</b>' + escapeHtml(t.question) + '</div>' +
        '<div style="margin-top:6px"><b>答：</b>' + renderMarkdown(t.answer||'（无）') + '</div></div>';
    });
    content.innerHTML = html || '<div class="loading">该会话无更多内容</div>';
  } catch (e) {
    content.innerHTML = '<div style="color:#e74c3c">' + escapeHtml(e.message) + '</div>';
  }
}

async function loadAiStats() {
  const bar = document.getElementById('aiStatusBar');
  try {
    const resp = await fetch('/api/ai/stats');
    const s = await resp.json();
    if (!s.available) {
      bar.innerHTML = '<span class="status-item" style="color:#e8870e">智能客服索引尚未构建，请在 设置→数据更新 中上传智能客服 Excel</span>';
      return;
    }
    bar.innerHTML =
      '<span class="status-item"><span class="status-dot"></span>数据周期 <b>' + s.date_range + '</b></span>' +
      '<span class="status-item">问答 <b>' + s.visible_count.toLocaleString() + '</b> 条（另隐藏 ' + s.hidden_count.toLocaleString() + '）</span>' +
      '<span class="status-item">会话 <b>' + s.session_count.toLocaleString() + '</b></span>' +
      '<span class="status-item">产品 <b>' + s.product_count + '</b> · 三级分类 <b>' + s.cat3_count + '</b></span>' +
      '<span class="status-item">索引更新 <b>' + (s.index_updated||'') + '</b></span>';
  } catch (e) {
    bar.innerHTML = '<span class="status-item" style="color:#e74c3c">状态加载失败</span>';
  }
}
</script>
</body>
</html>
"""


@app.route("/")
def index():
    return render_template_string(HTML_PAGE)


@app.route("/api/stats")
def api_stats():
    """返回索引数据概况：会话数、日期范围、更新时间、模型信息"""
    import os
    from paths import INDEX_DIR
    data = engine.data
    times = [item.get("start_time", "") for item in data if item.get("start_time")]
    times.sort()
    date_min = times[0][:10] if times else ""
    date_max = times[-1][:10] if times else ""

    all_models = set()
    all_errors = set()
    for item in data:
        all_models.update(item.get("models", []))
        all_errors.update(item.get("error_codes", []))

    # 索引文件修改时间
    index_mtime = ""
    faiss_path = os.path.join(INDEX_DIR, "faiss.index")
    if os.path.exists(faiss_path):
        import datetime
        index_mtime = datetime.datetime.fromtimestamp(
            os.path.getmtime(faiss_path)
        ).strftime("%Y-%m-%d %H:%M")

    return jsonify({
        "total": len(data),
        "date_range": f"{date_min} ~ {date_max}" if date_min else "未知",
        "index_updated": index_mtime,
        "model_count": len(all_models),
        "error_count": len(all_errors),
        "use_api": engine._use_api,
        "reranker_enabled": engine._reranker_enabled,
        "low_quality_count": len(engine._low_quality),
    })


_clusters_cache = None

def load_clusters():
    """加载聚类结果（带缓存）"""
    global _clusters_cache
    import os
    from paths import RUNTIME_DIR
    path = os.path.join(RUNTIME_DIR, "clusters.json")
    if not os.path.exists(path):
        return None
    if _clusters_cache is None:
        with open(path, "r", encoding="utf-8") as f:
            _clusters_cache = json.load(f)
    return _clusters_cache


@app.route("/api/clusters")
def api_clusters():
    """问题库：聚类列表，支持关键词搜索"""
    clusters_data = load_clusters()
    if not clusters_data:
        return jsonify({"error": "聚类数据不存在，请先运行 build_clusters.py", "clusters": []}), 200

    q = request.args.get("q", "").strip().lower()
    page = int(request.args.get("page", 1))
    per_page = int(request.args.get("per_page", 30))

    clusters = clusters_data["clusters"]

    if q:
        filtered = []
        for c in clusters:
            searchable = (c["title"] + " " + c.get("answer", "") + " " +
                          " ".join(c.get("sample_problems", [])) + " " +
                          " ".join(c.get("models", [])) + " " +
                          " ".join(c.get("error_codes", []))).lower()
            if q in searchable:
                filtered.append(c)
        clusters = filtered
    else:
        clusters = sorted(clusters, key=lambda x: x["size"], reverse=True)

    total = len(clusters)
    start = (page - 1) * per_page
    page_clusters = clusters[start:start + per_page]

    # 返回精简信息（不含完整 answer，只返回前 200 字）
    result = []
    for c in page_clusters:
        result.append({
            "id": c["id"],
            "title": c["title"],
            "answer_preview": c.get("answer", "")[:200],
            "size": c["size"],
            "models": c.get("models", []),
            "error_codes": c.get("error_codes", []),
            "sample_problems": c.get("sample_problems", []),
        })

    return jsonify({
        "total": total,
        "page": page,
        "per_page": per_page,
        "generated_at": clusters_data.get("generated_at", ""),
        "noise_count": clusters_data.get("noise_count", 0),
        "clusters": result,
    })


@app.route("/api/clusters/<int:cluster_id>")
def api_cluster_detail(cluster_id):
    """问题库：单个聚类详情，含标准答案和原始会话"""
    clusters_data = load_clusters()
    if not clusters_data:
        return jsonify({"error": "聚类数据不存在"}), 404

    cluster = None
    for c in clusters_data["clusters"]:
        if c["id"] == cluster_id:
            cluster = c
            break
    if not cluster:
        return jsonify({"error": "聚类不存在"}), 404

    # 获取成员会话
    member_ids = cluster.get("member_ids", [])
    conversations = []
    for item in engine.data:
        if item["conv_id"] in member_ids:
            conversations.append({
                "conv_id": item["conv_id"],
                "start_time": item.get("start_time", ""),
                "agent_name": item.get("agent_name", ""),
                "models": item.get("models", []),
                "error_codes": item.get("error_codes", []),
                "problem_text": item.get("problem_text", "")[:300],
                "solution_text": item.get("solution_text", "")[:500],
            })
        if len(conversations) >= 20:
            break

    return jsonify({
        "id": cluster["id"],
        "title": cluster["title"],
        "answer": cluster.get("answer", ""),
        "size": cluster["size"],
        "models": cluster.get("models", []),
        "error_codes": cluster.get("error_codes", []),
        "conversations": conversations,
    })


@app.route("/api/search")
def api_search():
    import time
    q = request.args.get("q", "").strip()
    top_k = int(request.args.get("top_k", 10))
    model_filter = request.args.get("model", "").strip() or None
    error_filter = request.args.get("error", "").strip() or None
    include_lq = request.args.get("include_lq", "0") == "1"
    agent_media_only = request.args.get("agent_media_only", "0") == "1"

    if not q:
        return jsonify({"error": "请输入查询内容"}), 400

    t0 = time.time()
    try:
        results, filter_tags = engine.search(
            q, top_k=top_k, model_filter=model_filter, error_filter=error_filter,
            include_low_quality=include_lq, agent_media_only=agent_media_only
        )
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"error": f"检索失败: {e}"}), 500
    took = round(time.time() - t0, 2)

    # 返回查询关键词用于前端高亮
    from text_utils import get_query_terms
    terms = get_query_terms(q)

    return jsonify({
        "query": q,
        "total": len(results),
        "took": took,
        "reranker_used": engine._reranker_enabled,
        "filter_tags": filter_tags,
        "highlight_terms": terms,
        "results": results,
    })


@app.route("/api/summarize", methods=["POST"])
def api_summarize():
    """基于搜索结果调用 LLM 生成结构化问答总结"""
    from api_client import call_llm
    data = request.get_json(force=True)
    query = data.get("query", "").strip()
    results = data.get("results", [])

    if not query:
        return jsonify({"error": "缺少查询内容"}), 400
    if not results:
        return jsonify({"error": "没有可总结的搜索结果"}), 400

    # 取 Top 8 条结果构建上下文
    top_results = results[:8]
    context_parts = []
    for i, r in enumerate(top_results, 1):
        models = ", ".join(r.get("models", [])) or "未提及"
        errors = ", ".join(r.get("error_codes", [])) or "无"
        context_parts.append(
            f"【会话{i}】\n"
            f"用户问题：{r.get('problem_text', '')}\n"
            f"涉及型号：{models}\n"
            f"错误码：{errors}\n"
            f"客服解答：\n{r.get('solution_text', '')}"
        )
    context = "\n\n---\n\n".join(context_parts)

    system_prompt = (
        "你是石头科技客服知识库助手。根据多条人工客服与用户的真实会话记录，"
        "总结出该问题的标准解答方案。要求：\n"
        "1. 只基于提供的会话内容总结，不要编造不存在的步骤或政策\n"
        "2. 排查步骤按从简单到复杂的顺序排列，用编号列出\n"
        "3. 如果不同会话给出了不同方案，都列出并说明适用场景\n"
        "4. 语言简洁专业，像客服手册\n"
        "5. 如果会话中没有有效解答，直接说明\n\n"
        "请按以下格式输出（Markdown）：\n"
        "## 问题概述\n"
        "（一句话描述用户遇到的问题）\n\n"
        "## 排查步骤\n"
        "1. ...\n"
        "2. ...\n\n"
        "## 解决方案\n"
        "（根据排查结果给出的最终处理方案，如更换配件、上门维修、退货换货等）\n\n"
        "## 注意事项\n"
        "（特殊情况、前提条件、需要用户配合的事项等，没有则写'无'）"
    )

    user_prompt = f"用户问题：{query}\n\n以下是相关的人工客服会话记录：\n\n{context}"

    try:
        answer = call_llm([
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ])
        return jsonify({
            "query": query,
            "answer": answer,
            "based_on": len(top_results),
        })
    except Exception as e:
        return jsonify({"error": f"AI 总结失败: {e}"}), 500


@app.route("/api/conversation/<conv_id>")
def api_conversation(conv_id):
    item = engine.get_conversation(conv_id)
    if item is None:
        return jsonify({"error": "未找到该会话"}), 404
    return jsonify(item)


# ==================== 智能客服（AI）问答检索 ====================
@app.route("/api/ai/stats")
def api_ai_stats():
    if ai_engine is None:
        return jsonify({"available": False}), 200
    s = ai_engine.stats()
    import os as _os, datetime as _dt
    from paths import AI_INDEX_DIR
    faiss_path = _os.path.join(AI_INDEX_DIR, "faiss.index")
    s["available"] = True
    s["index_updated"] = (_dt.datetime.fromtimestamp(_os.path.getmtime(faiss_path))
                          .strftime("%Y-%m-%d %H:%M")) if _os.path.exists(faiss_path) else ""
    s["date_range"] = f"{s['date_min']} ~ {s['date_max']}" if s["date_min"] else "未知"
    return jsonify(s)


@app.route("/api/ai/search")
def api_ai_search():
    import time as _time
    if ai_engine is None:
        return jsonify({"error": "智能客服索引尚未构建，请在 设置→数据更新 中上传智能客服 Excel"}), 400
    q = request.args.get("q", "").strip()
    if not q:
        return jsonify({"error": "请输入查询内容"}), 400
    top_k = int(request.args.get("top_k", 10))
    include_hidden = request.args.get("include_hidden", "0") == "1"
    filters = {
        "product": request.args.get("product", "").strip(),
        "category": request.args.get("category", "").strip(),
        "cat3": request.args.get("cat3", "").strip(),
        "qtype": request.args.get("qtype", "").strip(),
        "eff_recall": request.args.get("eff_recall", "").strip(),
        "relevant": request.args.get("relevant", "").strip(),
        "to_human": request.args.get("to_human", "").strip(),
        "vote": request.args.get("vote", "").strip(),
    }
    filters = {k: v for k, v in filters.items() if v}

    t0 = _time.time()
    try:
        results, facets = ai_engine.search(q, top_k=top_k, filters=filters,
                                           include_hidden=include_hidden)
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"error": f"检索失败: {e}"}), 500
    took = round(_time.time() - t0, 2)
    from text_utils import get_query_terms
    return jsonify({
        "query": q, "total": len(results), "took": took,
        "reranker_used": ai_engine._reranker_enabled,
        "facets": facets, "highlight_terms": get_query_terms(q),
        "results": results,
    })


@app.route("/api/ai/session/<path:session_id>")
def api_ai_session(session_id):
    if ai_engine is None:
        return jsonify({"error": "智能客服索引尚未构建"}), 400
    item = ai_engine.get_session(session_id)
    if item is None:
        return jsonify({"error": "未找到该会话"}), 404
    return jsonify(item)


@app.route("/api/media/stats")
def api_media_stats():
    if media_store is None:
        return jsonify({"available": False})
    return jsonify(media_store.stats())


@app.route("/api/media/search")
def api_media_search():
    if media_store is None:
        return jsonify({"error": "图片素材库尚未构建"}), 400
    q = request.args.get("q", "").strip()
    mtype = request.args.get("type", "").strip()
    limit = min(int(request.args.get("limit", 60)), 200)
    offset = int(request.args.get("offset", 0))
    items, total = media_store.search(q, mtype=mtype, limit=limit, offset=offset)
    from text_utils import get_query_terms
    return jsonify({
        "query": q, "total": total, "limit": limit, "offset": offset,
        "highlight_terms": get_query_terms(q) if q else [],
        "results": items,
    })


@app.route("/api/config", methods=["GET", "POST"])
def api_config():
    from api_config import load_config, save_config
    if request.method == "POST":
        cfg = request.get_json(force=True)
        saved = save_config(cfg)
        return jsonify({"ok": True, "config": saved})
    return jsonify(load_config())


@app.route("/api/test-config")
def api_test_config():
    """测试 embedding 和 reranker API 是否可用"""
    from api_config import load_config, normalize_llm_api_url
    cfg = load_config()
    result = {"ok": False}

    # 测试 embedding
    if not cfg.get("embedding_api_key", "").strip():
        return jsonify({"ok": False, "error": "未填写 Embedding API Key"}), 400
    try:
        import requests
        resp = requests.post(
            cfg["embedding_api_url"].rstrip("/"),
            json={"model": cfg["embedding_model"], "input": "测试"},
            headers={
                "Authorization": f"Bearer {cfg['embedding_api_key'].strip()}",
                "Content-Type": "application/json",
            },
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        emb = data["data"][0]["embedding"]
        result["ok"] = True
        result["embedding_dim"] = len(emb)
    except Exception as e:
        return jsonify({"ok": False, "error": f"Embedding: {e}"}), 400

    # 测试 reranker（可选）
    rerank_key = cfg.get("reranker_api_key", "").strip()
    if rerank_key:
        try:
            resp = requests.post(
                cfg["reranker_api_url"].rstrip("/"),
                json={
                    "model": cfg["reranker_model"],
                    "query": "测试",
                    "documents": ["测试文档"],
                    "top_n": 1,
                },
                headers={
                    "Authorization": f"Bearer {rerank_key}",
                    "Content-Type": "application/json",
                },
                timeout=30,
            )
            resp.raise_for_status()
            result["reranker_ok"] = True
        except Exception as e:
            result["reranker_ok"] = False
            result["reranker_error"] = str(e)
    else:
        result["reranker_ok"] = False

    # 测试 LLM（可选）
    llm_key = cfg.get("llm_api_key", "").strip() or cfg.get("embedding_api_key", "").strip()
    if llm_key:
        try:
            resp = requests.post(
                normalize_llm_api_url(cfg.get("llm_api_url")),
                json={
                    "model": cfg.get("llm_model", "deepseek-ai/DeepSeek-V3"),
                    "messages": [{"role": "user", "content": "你好"}],
                    "max_tokens": 10,
                },
                headers={
                    "Authorization": f"Bearer {llm_key}",
                    "Content-Type": "application/json",
                },
                timeout=30,
            )
            resp.raise_for_status()
            result["llm_ok"] = True
        except Exception as e:
            result["llm_ok"] = False
            result["llm_error"] = str(e)
    else:
        result["llm_ok"] = False

    return jsonify(result)


@app.route("/api/dict", methods=["GET", "POST"])
def api_dict():
    """获取或保存自定义词典"""
    from dict_manager import load_dict, save_dict
    if request.method == "POST":
        data = request.get_json(force=True)
        save_dict(
            custom_words=data.get("custom_words"),
            user_synonyms=data.get("user_synonyms"),
        )
        # 重新加载词典并重建 BM25
        from text_utils import load_custom_dict
        load_custom_dict()
        engine.rebuild_bm25()
        return jsonify({"ok": True})
    d = load_dict()
    # 返回给前端：默认词和用户词分开标注
    default_words_set = set()
    from dict_manager import DEFAULT_CUSTOM_WORDS, DEFAULT_SYNONYMS
    default_words_set = set(DEFAULT_CUSTOM_WORDS)
    default_syn_keys = set(DEFAULT_SYNONYMS.keys())
    words_info = [
        {"word": w, "builtin": w in default_words_set}
        for w in d["custom_words"]
    ]
    syns_info = []
    for k, v in d["synonyms"].items():
        syns_info.append({
            "key": k,
            "words": v,
            "builtin": k in default_syn_keys,
        })
    return jsonify({"words": words_info, "synonyms": syns_info})


# ---------- 数据更新 ----------
import threading
update_lock = threading.Lock()

update_status = {
    "running": False,
    "step": "",
    "message": "",
    "progress": 0,
    "logs": [],
    "error": None,
    "done": False,
}


def _update_log(msg, pct=None):
    update_status["logs"].append(msg)
    if len(update_status["logs"]) > 200:
        update_status["logs"] = update_status["logs"][-200:]
    update_status["message"] = msg
    if pct is not None:
        update_status["progress"] = pct
    print(f"[更新] {msg}")


def _run_ai_pipeline(xlsx_path):
    """智能客服：解析问答 Excel → 构建 BM25+FAISS → 重载 AI 引擎"""
    update_status["step"] = "parse"
    from parse_ai_logs import process_file as process_ai
    from paths import PARSED_AI_PATH
    _update_log(f"开始解析智能客服文件: {xlsx_path}", 0)
    process_ai(xlsx_path, PARSED_AI_PATH, progress_cb=_update_log)

    update_status["step"] = "index"
    _update_log("开始构建智能客服检索索引（向量化耗时较长）...", 85)
    from build_ai_index import build_ai_index
    build_ai_index(PARSED_AI_PATH, progress_cb=_update_log)

    update_status["step"] = "reload"
    _update_log("正在重载智能客服索引...", 99)
    global ai_engine
    from ai_search_engine import AISearchEngine
    ai_engine = AISearchEngine()
    _update_log("智能客服索引更新完成！", 100)


def _run_media_pipeline(target=2000):
    """图片素材库：基于【当前已解析的人工会话】用 VLM 重建素材，无需上传 Excel"""
    update_status["step"] = "media"
    from build_media_assets import build_media_assets
    _update_log(f"开始从当前人工会话构建图片素材库（目标 {target} 张，耗时较长）...", 1)
    # 每周换新数据后重建，忽略旧检查点
    n = build_media_assets(target=target, workers=8, progress_cb=_update_log, reset=True)

    update_status["step"] = "reload"
    _update_log("正在重载图片素材库...", 99)
    global media_store
    from media_store import MediaStore
    media_store = MediaStore()
    _update_log(f"图片素材库更新完成！共 {n} 张", 100)


def _cleanup_old_human_conversions(source_path):
    """Keep the successful import's download artifacts and remove older tasks."""
    from paths import RUNTIME_DIR

    conversions_dir = os.path.join(RUNTIME_DIR, "human_conversions")
    if not os.path.isdir(conversions_dir):
        return 0

    try:
        source_dir = os.path.realpath(os.path.dirname(source_path))
        root = os.path.realpath(conversions_dir)
        keep_dir = source_dir if os.path.commonpath([root, source_dir]) == root else None
    except (OSError, ValueError):
        keep_dir = None

    removed = 0
    for name in os.listdir(conversions_dir):
        task_dir = os.path.join(conversions_dir, name)
        if os.path.realpath(task_dir) == keep_dir:
            continue
        if os.path.isdir(task_dir):
            shutil.rmtree(task_dir)
            removed += 1
        elif os.path.isfile(task_dir) or os.path.islink(task_dir):
            os.remove(task_dir)
            removed += 1
    return removed


def _run_update(xlsx_path, rebuild_clusters=False, corpus="human", media_target=2000):
    """后台执行：解析 Excel → 重建索引 →（人工可选聚类）→ 重载引擎"""
    global engine
    try:
        update_status["running"] = True
        update_status["done"] = False
        update_status["error"] = None
        update_status["logs"] = []
        update_status["progress"] = 0
        update_status["corpus"] = corpus

        if corpus == "ai":
            _run_ai_pipeline(xlsx_path)
            update_status["done"] = True
            return

        if corpus == "media":
            _run_media_pipeline(target=media_target)
            update_status["done"] = True
            return

        # Build separately; keep the current index intact until validation succeeds.
        from human_import_pipeline import rebuild_human_index
        engine = rebuild_human_index(
            xlsx_path, progress_cb=_update_log,
            stage_cb=lambda stage: update_status.update(step=stage),
        )

        # 3. 可选重建聚类
        if rebuild_clusters:
            update_status["step"] = "cluster"
            _update_log("开始重建问题库（耗时较长）...", 92)
            try:
                from build_clusters import load_index, build_knn_graph, run_leiden
                from build_clusters import get_representative, generate_title_and_summary
                from paths import RUNTIME_DIR
                from concurrent.futures import ThreadPoolExecutor, as_completed

                idx, data = load_index()
                edges, weights = build_knn_graph(idx, len(data))
                valid_clusters, noise = run_leiden(len(data), edges, weights)
                _update_log(f"发现 {len(valid_clusters)} 个问题组，开始生成标题...", 94)

                def proc_cluster(args):
                    i, members = args
                    samples = get_representative(data, members)
                    title, answer = generate_title_and_summary(samples)
                    all_models, all_errors = set(), set()
                    for mi in members:
                        all_models.update(data[mi].get("models", []))
                        all_errors.update(data[mi].get("error_codes", []))
                    return {"id": i, "title": title, "answer": answer, "size": len(members),
                            "models": sorted(all_models)[:10], "error_codes": sorted(all_errors)[:10],
                            "member_ids": [data[mi]["conv_id"] for mi in members[:100]],
                            "sample_problems": [s.get("problem_text", "")[:150] for s in samples[:3]]}

                clusters_out = [None] * len(valid_clusters)
                done = 0
                with ThreadPoolExecutor(max_workers=4) as ex:
                    futs = {ex.submit(proc_cluster, (i, m)): i for i, m in enumerate(valid_clusters)}
                    for fut in as_completed(futs):
                        r = fut.result()
                        clusters_out[r["id"]] = r
                        done += 1
                        if done % 20 == 0:
                            _update_log(f"问题库进度: {done}/{len(valid_clusters)}", 94 + int(5 * done / len(valid_clusters)))

                cluster_data = {
                    "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                    "total_conversations": len(data),
                    "total_clusters": len(clusters_out),
                    "noise_count": len(noise),
                    "clusters": clusters_out,
                }
                with open(os.path.join(RUNTIME_DIR, "clusters.json"), "w", encoding="utf-8") as f:
                    json.dump(cluster_data, f, ensure_ascii=False, indent=2)
                _update_log(f"问题库重建完成: {len(clusters_out)} 个问题组", 99)
            except Exception as e:
                _update_log(f"问题库重建失败（不影响检索）: {e}")

        # 4. 重载引擎
        update_status["step"] = "reload"
        _update_log("正在重载索引...", 99)
        try:
            removed = _cleanup_old_human_conversions(xlsx_path)
            if removed:
                _update_log(f"已清理 {removed} 个较早的人工会话转换任务")
        except OSError as cleanup_error:
            _update_log(f"较早的转换文件清理失败，可稍后手动删除: {cleanup_error}")
        _update_log("更新完成！", 100)
        update_status["done"] = True

    except Exception as e:
        import traceback
        tb = traceback.format_exc()
        traceback.print_exc()
        update_status["error"] = str(e)
        update_status["traceback"] = tb
        _update_log(f"更新失败: {e}")
    except BaseException as e:  # SystemExit / KeyboardInterrupt 等也不能让界面静默卡死
        import traceback
        tb = traceback.format_exc()
        update_status["error"] = f"{type(e).__name__}: {e}"
        update_status["traceback"] = tb
        _update_log(f"更新中断: {type(e).__name__}: {e}")
    finally:
        # 兜底：只要没正常完成且没记录错误，也标记为失败，避免前端永远停在"更新中..."
        if not update_status["done"] and not update_status["error"]:
            update_status["error"] = "更新异常中断，请查看服务端日志"
        update_status["running"] = False


def _conversion_workbook_path(token):
    from paths import RUNTIME_DIR
    try:
        token = uuid.UUID(hex=token).hex
    except (ValueError, AttributeError):
        return None
    return os.path.join(RUNTIME_DIR, "human_conversions", token, "会话记录_整合.xlsx")


@app.route("/api/human-conversion/preview", methods=["POST"])
def api_human_conversion_preview():
    """Convert a raw one-message-per-row workbook and retain it for download/indexing."""
    from paths import RUNTIME_DIR
    from conversation_converter import prepare_human_import

    uploaded = request.files.get("file")
    body = request.get_json(silent=True) if request.is_json else request.form
    body = body or {}
    local_path = str(body.get("path", "")).strip()
    filename = uploaded.filename if uploaded and uploaded.filename else local_path
    if not filename or not filename.lower().endswith(".xlsx"):
        return jsonify({"error": "请选择 .xlsx 文件或填写本地文件路径"}), 400
    if not uploaded and not os.path.isfile(local_path):
        return jsonify({"error": "本地文件不存在，请检查路径"}), 400

    token = uuid.uuid4().hex
    work_dir = os.path.join(RUNTIME_DIR, "human_conversions", token)
    os.makedirs(work_dir, exist_ok=True)
    source_path = os.path.join(work_dir, "source.xlsx")
    output_path = os.path.join(work_dir, "会话记录_整合.xlsx")
    try:
        if uploaded and uploaded.filename:
            uploaded.save(source_path)
        else:
            shutil.copy2(local_path, source_path)
        stats = prepare_human_import(source_path, output_path, body.get("input_format", "auto"))
        with open(os.path.join(work_dir, "stats.json"), "w", encoding="utf-8") as f:
            json.dump(stats, f, ensure_ascii=False)
    except Exception as exc:
        shutil.rmtree(work_dir, ignore_errors=True)
        return jsonify({"error": str(exc)}), 400

    return jsonify({
        "ok": True,
        "token": token,
        "stats": stats,
        "download_url": f"/api/human-conversion/{token}/download",
    })


@app.route("/api/human-conversion/<token>/download")
def api_human_conversion_download(token):
    path = _conversion_workbook_path(token)
    if not path or not os.path.isfile(path):
        return jsonify({"error": "转换文件不存在或已失效，请重新转换"}), 404
    return send_file(path, as_attachment=True, download_name="会话记录_整合.xlsx")


@app.route("/api/human-conversion/<token>/update", methods=["POST"])
def api_human_conversion_update(token):
    if update_status["running"]:
        return jsonify({"error": "已有更新任务在运行中，请等待完成"}), 409
    path = _conversion_workbook_path(token)
    if not path or not os.path.isfile(path):
        return jsonify({"error": "转换文件不存在或已失效，请重新转换"}), 404
    with open(os.path.join(os.path.dirname(path), "stats.json"), encoding="utf-8") as f:
        stats = json.load(f)
    if not stats["indexed_count"]:
        return jsonify({"error": "转换表格可下载，但没有符合检索质量规则的会话，当前检索库未修改"}), 400
    body = request.get_json(silent=True) or {}
    if not _start_update(path, bool(body.get("rebuild_clusters", False)), "human"):
        return jsonify({"error": "已有更新任务在运行中，请等待完成"}), 409
    return jsonify({"ok": True, "message": "检索库更新任务已启动"})


def _start_update(path, rebuild_clusters=False, corpus="human", media_target=2000):
    with update_lock:
        if update_status["running"]:
            return False
        update_status.update(running=True, done=False, error=None, step="parse",
                             logs=[], progress=0, message="准备中...", corpus=corpus)
        try:
            threading.Thread(target=_run_update,
                             args=(path, rebuild_clusters, corpus, media_target), daemon=True).start()
        except Exception:
            update_status["running"] = False
            raise
    return True


@app.route("/api/update", methods=["POST"])
def api_update():
    """启动数据更新。接受 JSON {"path": "/path/to/file.xlsx", "rebuild_clusters": false}
    或 multipart 文件上传。"""
    if update_status["running"]:
        return jsonify({"error": "已有更新任务在运行中，请等待完成"}), 409

    rebuild_clusters = request.form.get("rebuild_clusters", "false") == "true"
    corpus = request.form.get("corpus", "human")
    media_target = int(request.form.get("media_target", "2000") or 2000)
    if request.is_json:
        body = request.get_json()
        xlsx_path = body.get("path", "").strip()
        rebuild_clusters = body.get("rebuild_clusters", False)
        corpus = body.get("corpus", "human")
        media_target = int(body.get("media_target", 2000) or 2000)
    else:
        xlsx_path = request.form.get("path", "").strip()
    if corpus not in ("human", "ai", "media"):
        corpus = "human"

    # 图片素材库不需要上传 Excel（基于当前已解析的人工会话构建）
    if corpus == "media":
        if not _start_update("", False, "media", media_target):
            return jsonify({"error": "已有更新任务在运行中，请等待完成"}), 409
        return jsonify({"ok": True, "message": "图片素材库构建任务已启动"})

    # 文件上传
    if "file" in request.files:
        f = request.files["file"]
        if f.filename:
            from paths import RUNTIME_DIR
            upload_dir = os.path.join(RUNTIME_DIR, "uploads")
            os.makedirs(upload_dir, exist_ok=True)
            # 不同语料分目录存放，避免重名覆盖
            upload_dir = os.path.join(upload_dir, corpus, uuid.uuid4().hex)
            os.makedirs(upload_dir, exist_ok=True)
            if not f.filename.lower().endswith(".xlsx"):
                return jsonify({"error": "当前只支持 .xlsx 文件"}), 400
            xlsx_path = os.path.join(upload_dir, secure_filename(f.filename) or "source.xlsx")
            f.save(xlsx_path)

    if not xlsx_path:
        return jsonify({"error": "请提供 Excel 文件路径或上传文件"}), 400
    if not os.path.isfile(xlsx_path):
        return jsonify({"error": f"文件不存在: {xlsx_path}"}), 400

    if not _start_update(xlsx_path, rebuild_clusters, corpus):
        return jsonify({"error": "已有更新任务在运行中，请等待完成"}), 409
    return jsonify({"ok": True, "message": "更新任务已启动"})


@app.route("/api/update-status")
def api_update_status():
    return jsonify({
        "running": update_status["running"],
        "step": update_status["step"],
        "message": update_status["message"],
        "progress": update_status["progress"],
        "logs": update_status["logs"][-30:],
        "error": update_status["error"],
        "done": update_status["done"],
        "corpus": update_status.get("corpus", "human"),
    })


if __name__ == "__main__":
    print("正在加载人工客服索引，请稍候...")
    engine = SearchEngine()
    # 智能客服索引（可选，未构建时不阻塞启动）
    try:
        from paths import AI_INDEX_DIR
        if os.path.exists(os.path.join(AI_INDEX_DIR, "data.json")):
            print("正在加载智能客服问答索引...")
            from ai_search_engine import AISearchEngine
            ai_engine = AISearchEngine()
        else:
            print("未发现智能客服索引（可在 设置→数据更新 中上传构建）")
    except Exception as e:
        print(f"智能客服索引加载失败（不影响人工检索）: {e}")
    # 客服图片素材库（可选，未构建时不阻塞）
    try:
        from media_store import MediaStore
        media_store = MediaStore()
    except Exception as e:
        print(f"图片素材库加载失败（不影响其他功能）: {e}")
    print("\n启动网页服务: http://127.0.0.1:59968")
    app.run(host="127.0.0.1", port=59968, debug=False)
