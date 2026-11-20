"""The launcher answers its own page and local tools only (guard.py; review, 20 Nov 2026). Run from the launcher
folder: .venv\\Scripts\\python.exe -m unittest discover tests"""
import asyncio
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from guard import refusal  # noqa: E402

OWN = {"host": "localhost:9000", "origin": "http://localhost:9000", "sec-fetch-site": "same-origin"}
NOT_OWN_PAGE = "The launcher takes changes only from its own page."


class Guard(unittest.TestCase):
    def test_the_launchers_own_page_may_read_and_change(self):
        self.assertIsNone(refusal("GET", {"host": "localhost:9000"}))
        self.assertIsNone(refusal("POST", OWN))
        self.assertIsNone(refusal("POST", {"host": "127.0.0.1:9000", "origin": "http://127.0.0.1:9000"}))
        self.assertIsNone(refusal("POST", {"host": "[::1]:9000", "origin": "http://[::1]:9000"}))

    def test_a_local_tool_with_no_browser_headers_may_change(self):
        """curl or a script on this PC sends neither Origin nor Sec-Fetch-Site; a browser always sends Origin on a
        cross-site POST."""
        self.assertIsNone(refusal("POST", {"host": "127.0.0.1:9000"}))

    def test_another_page_may_not_stop_or_start_anything(self):
        """It could stop the paper cycle mid-window, or start one past the two-PC fence."""
        cases = [
            {**OWN, "origin": "https://example.com", "sec-fetch-site": "cross-site"},  # any page on the web
            {**OWN, "origin": "https://example.com"},
            {"host": "localhost:9000", "sec-fetch-site": "cross-site"},
            {**OWN, "origin": "http://localhost:5181", "sec-fetch-site": "same-site"},  # another local page
            {**OWN, "origin": "http://localhost:5181"},
            {**OWN, "origin": "null"},  # a sandboxed frame or a local file
            {**OWN, "origin": "http://localhost:notaport"},
        ]
        for headers in cases:
            with self.subTest(headers=headers):
                self.assertEqual(refusal("POST", headers), NOT_OWN_PAGE)
                self.assertIsNone(refusal("GET", headers))  # reading its own address is still the page's business

    def test_a_name_that_is_not_this_computer_is_refused_even_to_read(self):
        """DNS rebinding: a page's own name pointed at 127.0.0.1 reaches the launcher under that name."""
        for host in ["evil.example:9000", "", "192.168.1.20:9000", "localhost.evil.example:9000"]:
            with self.subTest(host=host):
                self.assertIn("only on this computer", refusal("GET", {"host": host}) or "")
                self.assertIn(
                    "only on this computer", refusal("POST", {"host": host, "origin": f"http://{host}"}) or ""
                )


class App(unittest.TestCase):
    """The middleware in app.py, driven as ASGI (the venv has no HTTP test client)."""

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        root = Path(self.dir.name)
        (root / "tasks.yaml").write_text("[]")
        self.env = {k: os.environ.get(k) for k in ("LAUNCHER_TASKS", "LAUNCHER_LOGS")}
        os.environ["LAUNCHER_TASKS"], os.environ["LAUNCHER_LOGS"] = str(root / "tasks.yaml"), str(root / "logs")
        sys.modules.pop("app", None)
        import app as launcher

        self.app = launcher.app

    def tearDown(self):
        sys.modules.pop("app", None)
        for key, value in self.env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        self.dir.cleanup()

    def call(self, method: str, path: str, headers: dict[str, str]) -> tuple[int, bytes]:
        scope = {
            "type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": method, "path": path,
            "raw_path": path.encode(), "query_string": b"", "scheme": "http", "server": ("127.0.0.1", 9000),
            "client": ("127.0.0.1", 50000), "root_path": "",
            "headers": [(k.encode(), v.encode()) for k, v in headers.items()],
        }  # fmt: skip
        sent: list[dict] = []

        async def receive():
            return {"type": "http.request", "body": b"", "more_body": False}

        async def send(message):
            sent.append(message)

        asyncio.run(self.app(scope, receive, send))
        status = next(m["status"] for m in sent if m["type"] == "http.response.start")
        return status, b"".join(m.get("body", b"") for m in sent if m["type"] == "http.response.body")

    def test_the_app_refuses_another_page_with_403_and_still_serves_its_own(self):
        self.assertEqual(self.call("GET", "/api/tasks", {"host": "localhost:9000"})[0], 200)
        status, body = self.call("POST", "/api/tasks/run-all", {"host": "localhost:9000", "origin": "https://x.example"})
        self.assertEqual(status, 403)
        self.assertIn(b"own page", body)
        own = {"host": "localhost:9000", "origin": "http://localhost:9000", "sec-fetch-site": "same-origin"}
        self.assertEqual(self.call("POST", "/api/tasks/run-all", own)[0], 200)
        self.assertEqual(self.call("GET", "/api/tasks", {"host": "evil.example:9000"})[0], 403)


if __name__ == "__main__":
    unittest.main()
