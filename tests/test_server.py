import os
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from reviewer.prompt_builder import BugReport, CodeReviewResult
from reviewer.server import app, limiter

client = TestClient(app)


class FakeAnalyzer:
    def __init__(self, results):
        self.results = results
        self.prompts = []

    def _request_review(self, prompt):
        self.prompts.append(prompt)
        if len(self.results) == 1:
            return self.results[0]
        return self.results[min(len(self.prompts), len(self.results)) - 1]


def _result(summary, score, severities):
    return CodeReviewResult(
        summary=summary,
        score=score,
        bugs=[
            BugReport(line=i + 1, severity=s, description=f"issue {i}", suggested_fix="fix")
            for i, s in enumerate(severities)
        ],
    )


class HealthTests(unittest.TestCase):
    def test_health_ok(self):
        response = client.get("/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "ok")


class ReviewFileTests(unittest.TestCase):
    @patch("reviewer.server._analyzer")
    def test_reviews_content_and_merges_chunks(self, mock_analyzer_factory):
        fake = FakeAnalyzer([_result("part one", 5, ["high"]), _result("part two", 7, ["low"])])
        mock_analyzer_factory.return_value = fake

        code = "".join(f"def func_{i}():\n    x = {i}\n    return x\n\n" for i in range(8))
        response = client.post(
            "/api/review/file",
            json={"path": "app.py", "content": code, "max_tokens": 60},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(fake.prompts), 2)
        for prompt in fake.prompts:
            self.assertIn("app.py", prompt)
        body = response.json()
        self.assertEqual(body["score"], 6)
        self.assertEqual(len(body["bugs"]), 2)

    @patch("reviewer.server._analyzer")
    def test_empty_content_returns_empty_result(self, mock_analyzer_factory):
        mock_analyzer_factory.return_value = FakeAnalyzer([_result("x", 10, [])])
        response = client.post(
            "/api/review/file",
            json={"path": "empty.py", "content": "   \n  ", "max_tokens": 6000},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["bugs"], [])
        mock_analyzer_factory.assert_not_called()

    @patch("reviewer.server._analyzer")
    def test_guidelines_are_injected(self, mock_analyzer_factory):
        fake = FakeAnalyzer([_result("ok", 9, [])])
        mock_analyzer_factory.return_value = fake

        response = client.post(
            "/api/review/file",
            json={
                "path": "app.py",
                "content": "def f():\n    pass\n",
                "guidelines": "Never use eval().",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("Never use eval().", fake.prompts[0])


class ReviewDiffTests(unittest.TestCase):
    @patch("reviewer.server._analyzer")
    def test_reviews_diffs(self, mock_analyzer_factory):
        fake = FakeAnalyzer([_result("diff review", 4, ["medium"])])
        mock_analyzer_factory.return_value = fake

        response = client.post(
            "/api/review/diff",
            json={
                "file_diffs": [
                    {"file_path": "app.py", "hunks": "+print('x')\n-print('y')"},
                ],
                "guidelines": "",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("app.py", fake.prompts[0])
        self.assertEqual(response.json()["score"], 4)

    @patch("reviewer.server._analyzer")
    def test_empty_diffs_return_no_changes(self, mock_analyzer_factory):
        mock_analyzer_factory.return_value = FakeAnalyzer([_result("x", 10, [])])
        response = client.post("/api/review/diff", json={"file_diffs": []})
        self.assertEqual(response.status_code, 200)
        self.assertIn("No changes", response.json()["summary"])
        mock_analyzer_factory.assert_not_called()


class AuthTests(unittest.TestCase):
    @patch.dict("os.environ", {"AI_REVIEW_API_TOKEN": "secret-token"}, clear=False)
    def test_requires_token_when_configured(self):
        response = client.post(
            "/api/review/file",
            json={"path": "app.py", "content": "def f():\n    pass\n"},
        )
        self.assertEqual(response.status_code, 401)

    @patch.dict("os.environ", {"AI_REVIEW_API_TOKEN": "secret-token"}, clear=False)
    @patch("reviewer.server._analyzer")
    def test_accepts_valid_token(self, mock_analyzer_factory):
        fake = FakeAnalyzer([_result("ok", 8, [])])
        mock_analyzer_factory.return_value = fake

        response = client.post(
            "/api/review/file",
            json={"path": "app.py", "content": "def f():\n    pass\n"},
            headers={"Authorization": "Bearer secret-token"},
        )
        self.assertEqual(response.status_code, 200)

    @patch("reviewer.server._analyzer")
    def test_no_token_configured_allows_access(self, mock_analyzer_factory):
        fake = FakeAnalyzer([_result("ok", 8, [])])
        mock_analyzer_factory.return_value = fake
        response = client.post(
            "/api/review/file",
            json={"path": "app.py", "content": "def f():\n    pass\n"},
        )
        self.assertEqual(response.status_code, 200)


class ExceptionSanitizationTests(unittest.TestCase):
    @patch("reviewer.server._analyzer")
    def test_file_review_500_hides_internal_detail(self, mock_analyzer_factory):
        mock_analyzer_factory.side_effect = RuntimeError(
            "Groq key=gsk_secret123 connection failed at internal.host:443"
        )
        response = client.post(
            "/api/review/file",
            json={"path": "app.py", "content": "def f():\n    pass\n"},
        )
        self.assertEqual(response.status_code, 500)
        body = response.json()
        self.assertIn("detail", body)
        self.assertEqual(
            body["detail"],
            "An error occurred while processing the review request.",
        )
        self.assertNotIn("gsk_secret123", body["detail"])
        self.assertNotIn("internal.host", body["detail"])

    @patch("reviewer.server._analyzer")
    def test_diff_review_500_hides_internal_detail(self, mock_analyzer_factory):
        mock_analyzer_factory.side_effect = ValueError(
            "path=/etc/passwd not accessible"
        )
        response = client.post(
            "/api/review/diff",
            json={"file_diffs": [{"file_path": "a.py", "hunks": "+x"}]},
        )
        self.assertEqual(response.status_code, 500)
        body = response.json()
        self.assertEqual(
            body["detail"],
            "An error occurred while processing the review request.",
        )
        self.assertNotIn("/etc/passwd", body["detail"])


class RateLimitTests(unittest.TestCase):
    def setUp(self):
        limiter.reset()

    def test_file_review_rate_limit_enforced(self):
        @patch("reviewer.server._analyzer")
        def _run(mock_factory):
            mock_factory.return_value = FakeAnalyzer([_result("ok", 8, [])])
            payload = {"path": "x.py", "content": "print(1)\n"}

            for _ in range(30):
                resp = client.post("/api/review/file", json=payload)
                self.assertEqual(resp.status_code, 200)

            resp = client.post("/api/review/file", json=payload)
            self.assertEqual(resp.status_code, 429)
            self.assertIn("Rate limit", resp.json()["detail"])

        _run()

    def test_diff_review_rate_limit_enforced(self):
        @patch("reviewer.server._analyzer")
        def _run(mock_factory):
            mock_factory.return_value = FakeAnalyzer([_result("ok", 8, [])])
            payload = {"file_diffs": [{"file_path": "a.py", "hunks": "+x"}]}

            for _ in range(30):
                resp = client.post("/api/review/diff", json=payload)
                self.assertEqual(resp.status_code, 200)

            resp = client.post("/api/review/diff", json=payload)
            self.assertEqual(resp.status_code, 429)
            self.assertIn("Rate limit", resp.json()["detail"])

        _run()

    def test_health_endpoint_not_rate_limited(self):
        for _ in range(50):
            resp = client.get("/health")
            self.assertEqual(resp.status_code, 200)


class HealthCheckTests(unittest.TestCase):
    def test_check_health_returns_true_when_no_url(self):
        from reviewer.analyzer import Analyzer

        analyzer = Analyzer.__new__(Analyzer)
        analyzer.api_url = ""
        analyzer.api_token = ""
        self.assertTrue(analyzer.check_health())

    @patch("urllib.request.urlopen")
    def test_check_health_pings_backend(self, mock_urlopen):
        from reviewer.analyzer import Analyzer

        mock_response = mock_urlopen.return_value.__enter__.return_value
        mock_response.status = 200

        with patch.dict(os.environ, {"AI_REVIEW_API_URL": "http://localhost:9999"}, clear=True):
            analyzer = Analyzer()
            self.assertTrue(analyzer.check_health(timeout=3))

        request = mock_urlopen.call_args.args[0]
        self.assertEqual(request.full_url, "http://localhost:9999/health")
        self.assertEqual(request.method, "GET")

    @patch("urllib.request.urlopen")
    def test_check_health_returns_false_on_failure(self, mock_urlopen):
        from reviewer.analyzer import Analyzer
        import urllib.error

        mock_urlopen.side_effect = urllib.error.URLError("connection refused")

        with patch.dict(os.environ, {"AI_REVIEW_API_URL": "http://localhost:9999"}, clear=True):
            analyzer = Analyzer()
            self.assertFalse(analyzer.check_health())

    @patch("urllib.request.urlopen")
    def test_check_health_sends_bearer_token(self, mock_urlopen):
        from reviewer.analyzer import Analyzer

        mock_response = mock_urlopen.return_value.__enter__.return_value
        mock_response.status = 200

        with patch.dict(
            os.environ,
            {"AI_REVIEW_API_URL": "http://localhost:9999", "AI_REVIEW_API_TOKEN": "tok123"},
            clear=True,
        ):
            analyzer = Analyzer()
            analyzer.check_health()

        request = mock_urlopen.call_args.args[0]
        self.assertEqual(request.headers["Authorization"], "Bearer tok123")


if __name__ == "__main__":
    unittest.main()
