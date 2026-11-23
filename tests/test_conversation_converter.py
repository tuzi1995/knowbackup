import os
import sys
import tempfile
import unittest
from unittest.mock import patch
from datetime import datetime

import openpyxl

SRC_DIR = os.path.join(os.path.dirname(__file__), "..", "03_代码", "src")
sys.path.insert(0, os.path.abspath(SRC_DIR))

from conversation_converter import convert_detail_workbook, prepare_human_import
from parse_conversations import process_file, clean_text, classify_role


class ConversationConverterTest(unittest.TestCase):
    def test_convert_detail_sheets_and_parse_export(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            source_path = os.path.join(temp_dir, "detail.xlsx")
            output_path = os.path.join(temp_dir, "会话记录_整合.xlsx")
            parsed_path = os.path.join(temp_dir, "parsed.json")

            wb = openpyxl.Workbook()
            first = wb.active
            first.title = "sheet"
            headers = ["会话id", "访客ID", "消息内容", "附件", "视频", "语音", "图片",
                       "消息发送者", "发送者昵称", "创建时间"]
            first.append(headers)
            first.append(["sid-1", "visitor-1", "我的扫地机器人一直无法回充", None, None, None, None,
                          "访客", "小王", "2026-10-12 10:00:00"])
            first.append(["sid-1", "visitor-1", "图片", None, None, None,
                          "https://example.test/guide.jpg", "坐席", "2035",
                          "2026-10-12 10:01:00"])
            second = wb.create_sheet("sheet(1)")
            second.append(headers)
            second.append(["sid-1", "visitor-1", "请检查充电触点", None, None, None,
                           None, "坐席", "2035", "2026-10-12 10:02:00"])
            wb.save(source_path)

            stats = convert_detail_workbook(source_path, output_path)
            self.assertEqual(stats["message_count"], 3)
            self.assertEqual(stats["session_count"], 1)
            self.assertEqual(stats["duplicate_session_ids_across_sheets"], 1)
            self.assertEqual(stats["placeholder_media"], 1)

            converted = openpyxl.load_workbook(output_path, read_only=True, data_only=True)
            ws = converted["会话记录"]
            self.assertEqual(next(ws.iter_rows(values_only=True)), (
                "会话ID", "来源渠道", "会话开始时间", "会话结束时间",
                "是否转人工", "拓展信息", "聊天内容",
            ))
            row = next(ws.iter_rows(min_row=2, values_only=True))
            self.assertEqual(row[0], "sid-1")
            self.assertIn("https://example.test/guide.jpg", row[6])
            self.assertLess(row[6].index("无法回充"), row[6].index("请检查充电触点"))
            converted.close()

            parsed = process_file(output_path, parsed_path)
            self.assertEqual(len(parsed), 1)
            self.assertIn("我的扫地机器人一直无法回充", parsed[0]["problem_text"])
            self.assertIn("请检查充电触点", parsed[0]["solution_text"])
            self.assertEqual(parsed[0]["media_summary"]["agent_img"], 1)
            self.assertEqual(len(process_file(source_path, parsed_path)), 1)

    def test_media_and_unnamed_roles(self):
        self.assertEqual(classify_role("访客"), "visitor")
        self.assertEqual(classify_role("坐席"), "agent")
        self.assertEqual(classify_role("坐席(客服小王)"), "agent")
        for url, marker in [("https://example.test/voice.mp3", "[语音]"),
                            ("https://example.test/file?token=123", "[链接]"),
                            ("https://example.test/guide.webp", "[图片]")]:
            text, media = clean_text(url)
            self.assertEqual(text, marker)
            self.assertEqual(media, [url])

    def test_no_message_or_formula_loss(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = os.path.join(tmp, "source.xlsx")
            output = os.path.join(tmp, "export.xlsx")
            wb = openpyxl.Workbook()
            ws = wb.active
            ws.append(["会话ID", "消息内容", "消息发送者", "创建时间", "图片", "视频"])
            ws.append(["=1+1", "图文", "坐席", datetime(2026, 10, 12, 10),
                       "https://e.test/img.jpg", "https://e.test/v.mp4"])
            ws.cell(2, 1).data_type = "s"
            ws.append(["=1+1", '<img src="https://e.test/img.jpg">', "坐席", "2026-10-12 10:01:00"])
            ws.cell(3, 1).data_type = "s"
            wb.save(source)
            stats = convert_detail_workbook(source, output)
            self.assertEqual(stats["session_count"], 1)
            exported = openpyxl.load_workbook(output)
            self.assertEqual(exported.active.cell(2, 1).data_type, "s")
            chat = exported.active.cell(2, 7).value
            self.assertEqual(chat.count("https://e.test/img.jpg"), 2)
            self.assertIn("https://e.test/v.mp4", chat)
            exported.close()

    def test_overlong_conversation_is_split_without_losing_messages(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = os.path.join(tmp, "source.xlsx")
            output = os.path.join(tmp, "export.xlsx")
            wb = openpyxl.Workbook()
            ws = wb.active
            ws.append(["会话id", "消息内容", "消息发送者", "创建时间"])
            ws.append(["long-session", "文字" * 16000, "访客", "2026-10-12 10:00:00"])
            ws.append(["long-session", "内容" * 16000, "坐席", "2026-10-12 10:01:00"])
            wb.save(source)
            stats = convert_detail_workbook(source, output)
            self.assertEqual(stats["session_count"], 1)
            self.assertEqual(stats["output_row_count"], 2)
            self.assertEqual(stats["split_sessions"], 1)
            self.assertEqual(stats["split_parts"], 2)

            exported = openpyxl.load_workbook(output, read_only=True, data_only=True)
            rows = list(exported["会话记录"].iter_rows(min_row=2, values_only=True))
            self.assertEqual(len(rows), 2)
            self.assertEqual({row[0] for row in rows}, {"long-session"})
            self.assertTrue(all("原会话ID=long-session" in row[5] for row in rows))
            self.assertEqual(sum(row[6].count("文") for row in rows), 16000)
            self.assertEqual(sum(row[6].count("字") for row in rows), 16000)
            self.assertEqual(sum(row[6].count("内") for row in rows), 16000)
            self.assertEqual(sum(row[6].count("容") for row in rows), 16000)
            self.assertTrue(all(len(row[6].encode("utf-16-le")) // 2 <= 32767 for row in rows))
            exported.close()

            parsed = process_file(output, os.path.join(tmp, "parsed.json"))
            self.assertEqual(len(parsed), 1)
            self.assertEqual(parsed[0]["conv_id"], "long-session")
            self.assertTrue(parsed[0]["problem_text"])
            self.assertTrue(parsed[0]["solution_text"])

    def test_history_header_mapping_and_sheet_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            source, output = (os.path.join(tmp, name) for name in ("source.xlsx", "output.xlsx"))
            wb = openpyxl.Workbook()
            ws = wb.active
            ws.title = "任意名字"
            ws.append(["聊天内容", "拓展信息", "是否转人工", "会话结束时间", "会话开始时间", "来源渠道", "会话ID"])
            chat = "访客 2026-10-12 10:00:00\n扫地机器人无法回充怎么办\n\n坐席 2026-10-12 10:01:00\n请清洁充电触点并检查基站电源\n\n"
            ws.append([chat, "", "是", "2026-10-12 10:01:00", "2026-10-12 10:00:00", "", "session"])
            wb.save(source)
            stats = prepare_human_import(source, output)
            self.assertEqual(stats["input_format"], "session")
            self.assertEqual(stats["indexed_count"], 1)


class HumanImportAPITest(unittest.TestCase):
    def setUp(self):
        import web_app
        self.web = web_app
        self.tmp = tempfile.TemporaryDirectory()
        self.runtime_patch = patch("paths.RUNTIME_DIR", self.tmp.name)
        self.runtime_patch.start()
        self.client = web_app.app.test_client()
        self.source = os.path.join(self.tmp.name, "detail.xlsx")
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.append(["会话id", "消息内容", "消息发送者", "创建时间"])
        ws.append(["sid", "我的扫地机器人无法回充", "访客", "2026-10-12 10:00:00"])
        ws.append(["sid", "请清洁充电触点并检查基站电源", "坐席", "2026-10-12 10:01:00"])
        wb.save(self.source)

    def tearDown(self):
        self.runtime_patch.stop()
        self.tmp.cleanup()

    def test_upload_download_and_update_handoff(self):
        with open(self.source, "rb") as f:
            response = self.client.post("/api/human-conversion/preview", data={"file": (f, "../../明细.xlsx")})
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertEqual(data["stats"]["indexed_count"], 1)
        response = self.client.get(data["download_url"])
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.headers["Content-Disposition"].startswith("attachment"))
        response.close()
        with patch.object(self.web, "_start_update", return_value=True) as start:
            response = self.client.post(f"/api/human-conversion/{data['token']}/update", json={"rebuild_clusters": True})
            self.assertEqual(response.status_code, 200)
            self.assertTrue(start.call_args.args[1])
        with patch.object(self.web, "_start_update", return_value=False):
            response = self.client.post(f"/api/human-conversion/{data['token']}/update")
            self.assertEqual(response.status_code, 409)

    def test_path_and_validation(self):
        response = self.client.post("/api/human-conversion/preview", json={"path": self.source})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.client.get("/api/human-conversion/invalid/download").status_code, 404)
        self.assertEqual(self.client.post("/api/human-conversion/preview").status_code, 400)
        with open(self.source, "rb") as f:
            self.assertEqual(self.client.post("/api/human-conversion/preview", data={"file": (f, "file.xls")}).status_code, 400)

    def test_empty_quality_result_is_downloadable_but_cannot_update(self):
        wb = openpyxl.load_workbook(self.source)
        wb.active.cell(3, 3, "访客")
        wb.save(self.source)
        response = self.client.post("/api/human-conversion/preview", json={"path": self.source})
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertEqual(data["stats"]["indexed_count"], 0)
        self.assertEqual(self.client.post(f"/api/human-conversion/{data['token']}/update").status_code, 400)

    def test_successful_import_cleanup_keeps_current_task_only(self):
        conversions = os.path.join(self.tmp.name, "human_conversions")
        old_dir = os.path.join(conversions, "old-task")
        current_dir = os.path.join(conversions, "current-task")
        os.makedirs(old_dir)
        os.makedirs(current_dir)
        with open(os.path.join(old_dir, "source.xlsx"), "wb") as f:
            f.write(b"old")

        removed = self.web._cleanup_old_human_conversions(
            os.path.join(current_dir, "会话记录_整合.xlsx")
        )

        self.assertEqual(removed, 1)
        self.assertFalse(os.path.exists(old_dir))
        self.assertTrue(os.path.isdir(current_dir))


class PublicationTest(unittest.TestCase):
    def _source(self, tmp):
        source = os.path.join(tmp, "source.xlsx")
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.append(["会话id", "消息内容", "消息发送者", "创建时间"])
        ws.append(["sid", "我的扫地机器人一直无法回充", "访客", "2026-10-12 10:00:00"])
        ws.append(["sid", "请清洁充电触点并检查基站电源", "坐席", "2026-10-12 10:01:00"])
        wb.save(source)
        return source

    def test_model_failure_keeps_existing_data(self):
        import human_import_pipeline as pipeline
        with tempfile.TemporaryDirectory() as tmp:
            source = self._source(tmp)
            old_index = os.path.join(tmp, "active")
            os.mkdir(old_index)
            marker = os.path.join(old_index, "marker")
            old_parsed = os.path.join(tmp, "parsed.json")
            for path in (marker, old_parsed):
                with open(path, "w") as f:
                    f.write("original")
            with patch.object(pipeline, "INDEX_DIR", old_index), patch.object(pipeline, "PARSED_CONVERSATIONS_PATH", old_parsed), patch.object(pipeline, "RUNTIME_DIR", tmp):
                with patch("api_config.is_api_configured", return_value=True), patch("api_config.load_config", return_value={"embedding_model": "test"}), patch("api_client.call_embeddings", side_effect=RuntimeError("model unavailable")):
                    with self.assertRaisesRegex(RuntimeError, "model unavailable"):
                        pipeline.rebuild_human_index(source)
            for path in (marker, old_parsed):
                with open(path) as f:
                    self.assertEqual(f.read(), "original")

    def test_staged_index_roundtrip_and_publication(self):
        import human_import_pipeline as pipeline
        import json
        with tempfile.TemporaryDirectory() as tmp:
            source = self._source(tmp)
            active = os.path.join(tmp, "active")
            os.mkdir(active)
            parsed = os.path.join(tmp, "parsed.json")
            with patch.object(pipeline, "INDEX_DIR", active), patch.object(pipeline, "PARSED_CONVERSATIONS_PATH", parsed), patch.object(pipeline, "RUNTIME_DIR", tmp):
                with patch("api_config.is_api_configured", return_value=True), patch("api_config.is_reranker_configured", return_value=False), patch("api_config.load_config", return_value={"embedding_model": "test"}), patch("api_client.call_embeddings", return_value=[[1.0, 0.0]]):
                    engine = pipeline.rebuild_human_index(source)
            self.assertEqual(engine.faiss_index.ntotal, 1)
            self.assertEqual(engine.index_dir, active)
            self.assertEqual(engine.data[0]["conv_id"], "sid")
            self.assertTrue(os.path.isfile(os.path.join(active, "bm25.pkl")))
            with open(parsed) as f:
                self.assertEqual(len(json.load(f)), 1)

    def test_failed_publication_restores_previous_index(self):
        import human_import_pipeline as pipeline
        with tempfile.TemporaryDirectory() as tmp:
            old_index = os.path.join(tmp, "active")
            stage_index = os.path.join(tmp, "stage")
            os.mkdir(old_index)
            os.mkdir(stage_index)
            old_parsed = os.path.join(tmp, "parsed.json")
            with open(os.path.join(old_index, "marker"), "w") as f:
                f.write("original")
            with open(old_parsed, "w") as f:
                f.write("original")
            with patch.object(pipeline, "INDEX_DIR", old_index), patch.object(pipeline, "PARSED_CONVERSATIONS_PATH", old_parsed):
                with self.assertRaises(FileNotFoundError):
                    pipeline.publish_human_index(stage_index, os.path.join(tmp, "missing.json"), tmp)
            with open(os.path.join(old_index, "marker")) as f:
                self.assertEqual(f.read(), "original")
            with open(old_parsed) as f:
                self.assertEqual(f.read(), "original")


if __name__ == "__main__":
    unittest.main()
