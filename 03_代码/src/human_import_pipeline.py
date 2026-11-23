"""Build and validate a complete human index before publishing it."""

import os
import tempfile

from paths import INDEX_DIR, PARSED_CONVERSATIONS_PATH, RUNTIME_DIR


def rebuild_human_index(xlsx_path, progress_cb=None, stage_cb=None):
    from parse_conversations import process_file
    from build_index import build_index
    from search_engine import SearchEngine

    def report(stage, message, pct):
        if stage_cb:
            stage_cb(stage)
        if progress_cb:
            progress_cb(message, pct)

    os.makedirs(RUNTIME_DIR, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="human-index-", dir=RUNTIME_DIR) as work_dir:
        parsed_stage = os.path.join(work_dir, "parsed.json")
        index_stage = os.path.join(work_dir, "index")
        report("parse", "解析人工会话并检查质量...", 0)
        data = process_file(xlsx_path, parsed_stage,
                            progress_cb=lambda m, p: report("parse", m, int((p or 0) * .35)))
        if not data:
            raise ValueError("没有符合检索质量规则的会话，当前检索库未修改")
        report("index", f"准备为 {len(data)} 条会话构建索引...", 30)
        build_index(parsed_stage, index_dir=index_stage,
                    progress_cb=lambda m, p: report("index", m, 30 + int((p or 0) * .65)))
        report("reload", "校验新索引，成功后切换数据...", 96)
        new_engine = SearchEngine(index_dir=index_stage)
        if new_engine.faiss_index.ntotal != len(new_engine.data):
            raise ValueError("新索引向量数量与会话数量不一致，当前检索库未修改")
        publish_human_index(index_stage, parsed_stage, work_dir)
        new_engine.index_dir = INDEX_DIR
        return new_engine


def publish_human_index(index_stage, parsed_stage, work_dir):
    """Roll back the directory switch if publication fails."""
    old_index = os.path.join(work_dir, "previous_index")
    had_index = os.path.isdir(INDEX_DIR)
    os.makedirs(os.path.dirname(PARSED_CONVERSATIONS_PATH), exist_ok=True)
    if had_index:
        os.replace(INDEX_DIR, old_index)
    installed = False
    try:
        os.replace(index_stage, INDEX_DIR)
        installed = True
        os.replace(parsed_stage, PARSED_CONVERSATIONS_PATH)
    except BaseException:
        if installed:
            os.replace(INDEX_DIR, index_stage)
        if had_index:
            os.replace(old_index, INDEX_DIR)
        raise
