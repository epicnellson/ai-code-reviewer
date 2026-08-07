import os
import tempfile
import unittest

from reviewer.git_utils import FileDiff
from reviewer.guidelines import load_guidelines
from reviewer.prompt_builder import build_diff_review_prompt, build_review_prompt


class LoadGuidelinesTests(unittest.TestCase):
    def test_markdown_file_explicit(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "custom.md")
            with open(path, "w", encoding="utf-8") as f:
                f.write("# Rules\n- No eval\n- Add docstrings\n")

            result = load_guidelines(guidelines_path=path)

        self.assertIn("No eval", result)
        self.assertIn("Add docstrings", result)

    def test_toml_top_level_guidelines_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, ".ai-review.toml")
            with open(path, "w", encoding="utf-8") as f:
                f.write('guidelines = "Never use eval."\n')

            result = load_guidelines(guidelines_path=path)

        self.assertEqual(result, "Never use eval.")

    def test_toml_review_table(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, ".ai-review.toml")
            with open(path, "w", encoding="utf-8") as f:
                f.write('[review]\nguidelines = "Use type hints."\n')

            result = load_guidelines(guidelines_path=path)

        self.assertEqual(result, "Use type hints.")

    def test_toml_list_of_rules(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, ".ai-review.toml")
            with open(path, "w", encoding="utf-8") as f:
                f.write('guidelines = ["Rule one.", "Rule two."]\n')

            result = load_guidelines(guidelines_path=path)

        self.assertIn("Rule one.", result)
        self.assertIn("Rule two.", result)

    def test_repo_root_search_prefers_toml(self):
        with tempfile.TemporaryDirectory() as tmp:
            with open(os.path.join(tmp, ".ai-review.toml"), "w", encoding="utf-8") as f:
                f.write('guidelines = "TOML rules"\n')
            with open(os.path.join(tmp, "guidelines.md"), "w", encoding="utf-8") as f:
                f.write("markdown rules\n")

            result = load_guidelines(repo_path=tmp)

        self.assertEqual(result, "TOML rules")

    def test_repo_root_markdown_fallback(self):
        with tempfile.TemporaryDirectory() as tmp:
            with open(os.path.join(tmp, "guidelines.md"), "w", encoding="utf-8") as f:
                f.write("markdown rules\n")

            result = load_guidelines(repo_path=tmp)

        self.assertEqual(result, "markdown rules")

    def test_explicit_path_takes_precedence(self):
        with tempfile.TemporaryDirectory() as tmp:
            with open(os.path.join(tmp, ".ai-review.toml"), "w", encoding="utf-8") as f:
                f.write('guidelines = "repo rules"\n')
            explicit = os.path.join(tmp, "custom.md")
            with open(explicit, "w", encoding="utf-8") as f:
                f.write("explicit rules\n")

            result = load_guidelines(guidelines_path=explicit, repo_path=tmp)

        self.assertEqual(result, "explicit rules")

    def test_no_guidelines_found(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(load_guidelines(repo_path=tmp), "")

    def test_missing_explicit_path_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                load_guidelines(guidelines_path=os.path.join(tmp, "nope.md"))


class PromptInjectionTests(unittest.TestCase):
    def test_full_file_prompt_injects_guidelines(self):
        prompt = build_review_prompt("print('x')\n", "a.py", guidelines="Never use eval.")

        self.assertIn("Project review rules", prompt)
        self.assertIn("Never use eval.", prompt)

    def test_full_file_prompt_omits_guidelines_when_empty(self):
        prompt = build_review_prompt("print('x')\n", "a.py")

        self.assertNotIn("Project review rules", prompt)

    def test_diff_prompt_injects_guidelines(self):
        diffs = [FileDiff(file_path="a.py", hunks="@@ -1 +1 @@\n-old\n+new")]

        prompt = build_diff_review_prompt(diffs, guidelines="No bare excepts.")

        self.assertIn("No bare excepts.", prompt)

    def test_chunk_header_included_in_prompt(self):
        prompt = build_review_prompt(
            "code\n", "a.py", chunk_header="function `foo` (lines 1-3)"
        )

        self.assertIn("section: function `foo` (lines 1-3)", prompt)


if __name__ == "__main__":
    unittest.main()
