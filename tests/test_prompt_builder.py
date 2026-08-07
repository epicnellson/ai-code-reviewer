import unittest

from reviewer.git_utils import FileDiff
from reviewer.prompt_builder import build_diff_review_prompt, build_review_prompt


class BuildDiffReviewPromptTests(unittest.TestCase):
    def test_includes_file_paths_and_hunks(self):
        diffs = [
            FileDiff(file_path="app.py", hunks="@@ -1,2 +1,3 @@\n-print('x')\n+print('y')"),
            FileDiff(file_path="utils.py", hunks="@@ -9 +9 @@\n-old\n+new"),
        ]

        prompt = build_diff_review_prompt(diffs)

        self.assertIn("File: `app.py`", prompt)
        self.assertIn("+print('y')", prompt)
        self.assertIn("File: `utils.py`", prompt)
        self.assertIn("+new", prompt)
        self.assertEqual(prompt.count("```diff"), 2)

    def test_contains_schema_and_new_file_line_note(self):
        diffs = [FileDiff(file_path="app.py", hunks="@@ -1 +1 @@\n-old\n+new")]

        prompt = build_diff_review_prompt(diffs)

        self.assertIn('"score"', prompt)
        self.assertIn('"bugs"', prompt)
        self.assertIn("NEW version", prompt)

    def test_empty_diffs_produce_valid_prompt(self):
        prompt = build_diff_review_prompt([])

        self.assertIn("No changes to review.", prompt)

    def test_whole_file_prompt_contains_code_and_schema(self):
        prompt = build_review_prompt("print('hi')\n", "sample.py")

        self.assertIn("sample.py", prompt)
        self.assertIn("print('hi')", prompt)
        self.assertIn('"bugs"', prompt)


if __name__ == "__main__":
    unittest.main()
