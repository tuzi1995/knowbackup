import os
import sys
import unittest


SRC_DIR = os.path.join(os.path.dirname(__file__), "..", "03_代码", "src")
sys.path.insert(0, os.path.abspath(SRC_DIR))

from api_config import normalize_llm_api_url


class ApiConfigTest(unittest.TestCase):
    def test_appends_chat_completions_to_base_url(self):
        self.assertEqual(
            normalize_llm_api_url("https://ark.cn-beijing.volces.com/api/coding/v3"),
            "https://ark.cn-beijing.volces.com/api/coding/v3/chat/completions",
        )

    def test_preserves_complete_endpoint_and_trims_slash(self):
        self.assertEqual(
            normalize_llm_api_url("https://api.example/v1/chat/completions/"),
            "https://api.example/v1/chat/completions",
        )

    def test_empty_url_uses_default_endpoint(self):
        self.assertEqual(
            normalize_llm_api_url(""),
            "https://api.siliconflow.cn/v1/chat/completions",
        )


if __name__ == "__main__":
    unittest.main()
