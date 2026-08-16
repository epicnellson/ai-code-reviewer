import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from reviewer.prompt_builder import BugReport, CodeReviewResult
from reviewer.server import app

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
        mock_analyzer_factory.return_value = FakeAnalyzer([_result("ok", 8, [])])
        response = client.post(
            "/api/review/file",
            json={"path": "app.py", "content": "def f():\n    pass\n"},
        )
        self.assertEqual(response.status_code, 200)


if __name__ == "__main__":
    unittest.main()
