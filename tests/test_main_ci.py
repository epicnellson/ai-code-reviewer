import contextlib
import io
import json
import sys
import unittest
from unittest.mock import patch

import main as main_module
from main import _ci_exit_code
from reviewer.prompt_builder import BugReport, CodeReviewResult


def _result_with_bugs(severities, score=5):
    bugs = [
        BugReport(line=i + 1, severity=s, description=f"issue {i + 1}", suggested_fix=f"fix {i + 1}")
        for i, s in enumerate(severities)
    ]
    return CodeReviewResult(summary="reviewed", score=score, bugs=bugs)


class CiExitCodeTests(unittest.TestCase):
    def test_ci_high_severity_returns_1(self):
        result = _result_with_bugs(["high"])
        self.assertEqual(_ci_exit_code(result, ci=True), 1)

    def test_ci_mixed_severity_with_high_returns_1(self):
        result = _result_with_bugs(["low", "high", "medium"])
        self.assertEqual(_ci_exit_code(result, ci=True), 1)

    def test_ci_no_high_severity_returns_0(self):
        result = _result_with_bugs(["low", "medium"])
        self.assertEqual(_ci_exit_code(result, ci=True), 0)

    def test_ci_no_bugs_returns_0(self):
        result = CodeReviewResult(summary="clean", score=9, bugs=[])
        self.assertEqual(_ci_exit_code(result, ci=True), 0)

    def test_non_ci_ignores_high_severity(self):
        result = _result_with_bugs(["high"])
        self.assertEqual(_ci_exit_code(result, ci=False), 0)


class MainCiBehaviorTests(unittest.TestCase):
    def _run_main(self, argv, mock_analyzer_cls):
        stdout = io.StringIO()
        with patch.object(sys, "argv", ["ai-code-review"] + argv):
            with contextlib.redirect_stdout(stdout):
                with self.assertRaises(SystemExit) as ctx:
                    main_module.main()
        return ctx.exception.code, stdout.getvalue()

    def test_ci_mode_exits_1_on_high_severity_bug(self):
        with patch("main.Analyzer") as mock_analyzer_cls:
            mock_analyzer_cls.return_value.analyze_file.return_value = _result_with_bugs(["high"])

            code, output = self._run_main(["--file", "sample.py", "--ci"], mock_analyzer_cls)

        self.assertEqual(code, 1)
        self.assertIn("[HIGH]", output)

    def test_ci_mode_exits_0_when_clean(self):
        with patch("main.Analyzer") as mock_analyzer_cls:
            mock_analyzer_cls.return_value.analyze_file.return_value = _result_with_bugs([], score=9)

            code, output = self._run_main(["--file", "sample.py", "--ci"], mock_analyzer_cls)

        self.assertEqual(code, 0)
        self.assertIn("No bugs found.", output)

    def test_non_ci_mode_ignores_high_severity_for_exit_code(self):
        with patch("main.Analyzer") as mock_analyzer_cls:
            mock_analyzer_cls.return_value.analyze_file.return_value = _result_with_bugs(["high"])

            code, _ = self._run_main(["--file", "sample.py"], mock_analyzer_cls)

        self.assertEqual(code, 0)

    def test_json_format_output_is_valid_json(self):
        with patch("main.Analyzer") as mock_analyzer_cls:
            mock_analyzer_cls.return_value.analyze_file.return_value = _result_with_bugs(["medium"])

            code, output = self._run_main(
                ["--file", "sample.py", "--format", "json"], mock_analyzer_cls
            )

        self.assertEqual(code, 0)
        data = json.loads(output)
        self.assertEqual(data["score"], 5)
        self.assertEqual(data["bugs"][0]["severity"], "medium")

    def test_diff_mode_with_no_changes_exits_0(self):
        with patch("main.Analyzer") as mock_analyzer_cls, patch(
            "main.get_file_diffs", return_value=[]
        ):
            code, output = self._run_main(["--diff", "--ci"], mock_analyzer_cls)

        self.assertEqual(code, 0)
        self.assertIn("No changes to review.", output)

    def test_missing_both_file_and_diff_is_usage_error(self):
        with patch("main.Analyzer") as mock_analyzer_cls:
            with patch.object(
                sys, "argv", ["ai-code-review", "--ci"]
            ), self.assertRaises(SystemExit) as ctx:
                with contextlib.redirect_stdout(io.StringIO()):
                    main_module.main()

        self.assertEqual(ctx.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
