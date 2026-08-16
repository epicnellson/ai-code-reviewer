import io
import json
import os
import tempfile
import unittest
import urllib.error
from unittest.mock import MagicMock, patch

from reviewer.analyzer import Analyzer
from reviewer.prompt_builder import CodeReviewResult


class ClientModeInitTests(unittest.TestCase):
    def test_api_url_does_not_require_groq_key(self):
        with patch.dict(os.environ, {"AI_REVIEW_API_URL": "http://localhost:8000"}, clear=True):
            analyzer = Analyzer()
            self.assertIsNone(analyzer.client)
            self.assertEqual(analyzer.api_url, "http://localhost:8000")

    def test_missing_key_and_url_raise(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(ValueError) as ctx:
                Analyzer()
            self.assertIn("GROQ_API_KEY", str(ctx.exception))
            self.assertIn("AI_REVIEW_API_URL", str(ctx.exception))

    def test_token_read_from_env(self):
        with patch.dict(
            os.environ,
            {"AI_REVIEW_API_URL": "http://x", "AI_REVIEW_API_TOKEN": "tok"},
            clear=True,
        ):
            self.assertEqual(Analyzer().api_token, "tok")


class ClientModeRequestTests(unittest.TestCase):
    def setUp(self):
        self.analyzer = Analyzer(api_url="http://localhost:8000", api_token="tok")
        self.result = CodeReviewResult(summary="ok", score=7, bugs=[])

    def test_http_post_sends_bearer_token_and_parses_result(self):
        mock_response = MagicMock()
        mock_response.__enter__.return_value = mock_response
        mock_response.read.return_value = json.dumps(self.result.model_dump()).encode()

        with patch("urllib.request.urlopen", return_value=mock_response) as mock_open:
            result = self.analyzer._http_post("/api/review/file", {"content": "x"})

        request = mock_open.call_args.args[0]
        self.assertEqual(request.full_url, "http://localhost:8000/api/review/file")
        self.assertEqual(request.headers["Authorization"], "Bearer tok")
        self.assertEqual(result, self.result)

    def test_http_post_raises_runtime_error_on_http_401(self):
        error = urllib.error.HTTPError(
            "http://localhost:8000/api/review/file", 401, "Unauthorized", {}, io.BytesIO(b'{"detail":"bad"}')
        )
        with patch("urllib.request.urlopen", side_effect=error):
            with self.assertRaises(RuntimeError) as ctx:
                self.analyzer._http_post("/api/review/file", {})
        self.assertIn("HTTP 401", str(ctx.exception))
        self.assertIn("bad", str(ctx.exception))

    def test_http_post_raises_runtime_error_on_unreachable(self):
        error = urllib.error.URLError("connection refused")
        with patch("urllib.request.urlopen", side_effect=error):
            with self.assertRaises(RuntimeError) as ctx:
                self.analyzer._http_post("/api/review/file", {})
        self.assertIn("Could not reach review backend", str(ctx.exception))

    def test_analyze_file_sends_content_to_backend(self):
        with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as f:
            f.write("def f():\n    pass\n")
            path = f.name
        try:
            with patch.object(self.analyzer, "_http_post", return_value=self.result) as mock_post:
                result = self.analyzer.analyze_file(path, target_root=os.path.dirname(path))

            payload = mock_post.call_args.args[1]
            self.assertEqual(payload["path"], os.path.abspath(path))
            self.assertIn("def f()", payload["content"])
            self.assertEqual(result, self.result)
        finally:
            os.unlink(path)

    def test_analyze_diffs_sends_diff_payload(self):
        from reviewer.git_utils import FileDiff

        diffs = [FileDiff(file_path="a.py", hunks="+x")]

        with patch.object(self.analyzer, "_http_post", return_value=self.result) as mock_post:
            result = self.analyzer.analyze_diffs(diffs)

        payload = mock_post.call_args.args[1]
        self.assertEqual(payload["file_diffs"], [{"file_path": "a.py", "hunks": "+x"}])
        self.assertEqual(result, self.result)


if __name__ == "__main__":
    unittest.main()
