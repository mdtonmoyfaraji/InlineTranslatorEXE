import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer as HTTPServer

from app.ai import (AIClient, AIError, build_translation_messages, clean_translation,
                    normalize_chat_completions_url, validate_api_config)
from app.settings import ApiConfig


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    connections = set()
    mode = "ok"

    def log_message(self, *a):
        pass

    def do_POST(self):
        Handler.connections.add(self.client_address)
        n = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(n))
        mode = Handler.mode
        if mode == "401":
            return self._send(401, {"error": {"message": "bad key sk-TESTKEY123"}})
        if mode == "429":
            return self._send(429, {"error": {"message": "slow down"}})
        if mode == "html":
            return self._send(200, None, raw=b"<html>hi</html>")
        if mode == "empty":
            return self._send(200, {"choices": [{"message": {"content": ""}, "finish_reason": "length"}]})
        user = body["messages"][1]["content"]
        text = user.replace("<text>\n", "").replace("\n</text>", "")
        auth = self.headers.get("Authorization")
        out = f"<think>x</think>[{auth}] {text.upper()}"
        self._send(200, {"choices": [{"message": {"content": out}}]})

    def _send(self, code, obj, raw=None):
        data = raw if raw is not None else json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


class AiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = HTTPServer(("127.0.0.1", 0), Handler)
        cls.port = cls.srv.server_address[1]
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()

    def setUp(self):
        Handler.mode = "ok"
        Handler.connections.clear()
        self.cfg = ApiConfig(base_url=f"http://127.0.0.1:{self.port}", model="m", api_key="sk-TESTKEY123", proxy_mode="none")

    def test_url_normalisation(self):
        n = normalize_chat_completions_url
        self.assertEqual(n("https://api.openai.com"), "https://api.openai.com/v1/chat/completions")
        self.assertEqual(n("https://api.openai.com/v1/"), "https://api.openai.com/v1/chat/completions")
        self.assertEqual(n("https://h/openai/v1"), "https://h/openai/v1/chat/completions")
        self.assertEqual(n("https://x.ai/v1/chat/completions"), "https://x.ai/v1/chat/completions")
        self.assertEqual(n("localhost:11434/v1"), "http://localhost:11434/v1/chat/completions")
        with self.assertRaises(AIError):
            n("http://example.com")
        with self.assertRaises(AIError):
            n("https://user:pw@example.com")

    def test_validate(self):
        self.assertEqual(validate_api_config(self.cfg), [])
        self.assertTrue(validate_api_config(ApiConfig(base_url="https://x.com", model="m")))

    def test_translate_and_cleanup(self):
        out = AIClient().translate(self.cfg, "hello", "en", "fr")
        self.assertEqual(out, "[Bearer sk-TESTKEY123] HELLO")

    def test_keep_alive_reuses_connection(self):
        c = AIClient()
        c.translate(self.cfg, "a", "en", "fr")
        c.translate(self.cfg, "b", "en", "fr")
        c.translate(self.cfg, "c", "en", "fr")
        self.assertEqual(len(Handler.connections), 1)

    def test_warm_then_translate_uses_same_connection(self):
        c = AIClient()
        c.warm(self.cfg)
        c.translate(self.cfg, "a", "en", "fr")
        self.assertEqual(len(Handler.connections), 1)

    def test_recovers_from_dropped_idle_connection(self):
        c = AIClient()
        c.translate(self.cfg, "a", "en", "fr")
        c._pooled.conn.sock.close()  # simulate the server closing an idle connection
        self.assertIn("B", c.translate(self.cfg, "b", "en", "fr"))

    def test_errors_and_key_redaction(self):
        Handler.mode = "401"
        with self.assertRaises(AIError) as cm:
            AIClient().translate(self.cfg, "x", "en", "fr")
        self.assertEqual(cm.exception.code, "auth")
        self.assertNotIn("sk-TESTKEY123", cm.exception.message)
        Handler.mode = "429"
        with self.assertRaises(AIError) as cm:
            AIClient().translate(self.cfg, "x", "en", "fr")
        self.assertEqual(cm.exception.code, "rate_limit")
        Handler.mode = "html"
        with self.assertRaises(AIError) as cm:
            AIClient().translate(self.cfg, "x", "en", "fr")
        self.assertEqual(cm.exception.code, "bad_response")
        Handler.mode = "empty"
        with self.assertRaises(AIError) as cm:
            AIClient().translate(self.cfg, "x", "en", "fr")
        self.assertIn("length", cm.exception.message)

    def test_unreachable(self):
        cfg = ApiConfig(base_url="http://127.0.0.1:9", model="m", proxy_mode="none")
        with self.assertRaises(AIError) as cm:
            AIClient().translate(cfg, "x", "en", "fr")
        self.assertEqual(cm.exception.code, "network")

    def test_input_validation(self):
        c = AIClient()
        with self.assertRaises(AIError):
            c.translate(self.cfg, "  ", "en", "fr")
        with self.assertRaises(AIError):
            c.translate(self.cfg, "x", "en", "auto")
        with self.assertRaises(AIError):
            c.translate(self.cfg, "x" * 9000, "en", "fr")

    def test_test_connection(self):
        ok, msg = AIClient().test_connection(self.cfg)
        self.assertTrue(ok, msg)

    def test_tone_and_tone_only_requests(self):
        c = AIClient()
        self.assertIn("HELLO", c.translate(self.cfg, "hello", "en", "fr", "viking"))
        self.assertIn("HELLO", c.translate(self.cfg, "hello", "auto", "none", "zen"))
        with self.assertRaises(AIError):
            c.translate(self.cfg, "hello", "auto", "none")  # tone only needs a tone
        with self.assertRaises(AIError):
            c.translate(self.cfg, "hello", "en", "fr", "not-a-tone")

    def test_prompt_and_clean(self):
        m = build_translation_messages("hi", "auto", "bn")
        self.assertIn("Bengali", m[0]["content"])
        self.assertIn("detect it automatically", m[0]["content"])
        self.assertEqual(clean_translation("<text>\n hello \n</text>"), "hello")


if __name__ == "__main__":
    unittest.main()
