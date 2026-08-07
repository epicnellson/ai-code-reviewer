import os
import shutil
import tempfile
import unittest

from git import Repo

from reviewer.git_utils import _parse_diff_text, get_file_diffs


class ParseDiffTextTests(unittest.TestCase):
    def test_parses_multiple_files_and_new_paths(self):
        raw = (
            "diff --git a/one.py b/one.py\n"
            "index 111..222 100644\n"
            "--- a/one.py\n"
            "+++ b/one.py\n"
            "@@ -1,3 +1,4 @@\n"
            " def foo():\n"
            "-    return 1\n"
            "+    return 2\n"
            "diff --git a/two.py b/two.py\n"
            "index 333..444 100644\n"
            "--- a/two.py\n"
            "+++ b/two.py\n"
            "@@ -5 +5 @@\n"
            "-x = 1\n"
            "+x = 2\n"
        )
        diffs = _parse_diff_text(raw)

        self.assertEqual(len(diffs), 2)
        self.assertEqual(diffs[0].file_path, "one.py")
        self.assertIn("+    return 2", diffs[0].hunks)
        self.assertEqual(diffs[1].file_path, "two.py")
        self.assertIn("-x = 1", diffs[1].hunks)

    def test_skips_binary_files(self):
        raw = (
            "diff --git a/img.png b/img.png\n"
            "index 111..222 100644\n"
            "Binary files a/img.png and b/img.png differ\n"
        )
        self.assertEqual(_parse_diff_text(raw), [])

    def test_handles_new_files(self):
        raw = (
            "diff --git a/new.py b/new.py\n"
            "new file mode 100644\n"
            "index 0000000..abc1234\n"
            "--- /dev/null\n"
            "+++ b/new.py\n"
            "@@ -0,0 +1 @@\n"
            "+print('hi')\n"
        )
        diffs = _parse_diff_text(raw)

        self.assertEqual(len(diffs), 1)
        self.assertEqual(diffs[0].file_path, "new.py")
        self.assertIn("+print('hi')", diffs[0].hunks)

    def test_empty_diff(self):
        self.assertEqual(_parse_diff_text(""), [])

    def test_hunk_content_that_matches_separator_is_not_split(self):
        raw = (
            "diff --git a/one.py b/one.py\n"
            "index 111..222 100644\n"
            "--- a/one.py\n"
            "+++ b/one.py\n"
            "@@ -1 +1 @@\n"
            "-diff --git a/fake.py b/fake.py\n"
            "+diff --git a/fake.py b/fake.py\n"
        )
        diffs = _parse_diff_text(raw)

        self.assertEqual(len(diffs), 1)
        self.assertEqual(diffs[0].file_path, "one.py")


class GetFileDiffsTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.repo = Repo.init(self.temp_dir)
        with self.repo.config_writer() as cw:
            cw.set_value("user", "email", "test@example.com")
            cw.set_value("user", "name", "Test User")

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _write(self, name, content):
        path = os.path.join(self.temp_dir, name)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        return path

    def _commit_all(self, message):
        self.repo.index.add("*")
        return self.repo.index.commit(message)

    def test_local_unstaged_changes(self):
        self._write("a.txt", "hello\n")
        self._commit_all("initial")
        self._write("a.txt", "hello world\n")

        diffs = get_file_diffs(self.temp_dir)

        self.assertEqual(len(diffs), 1)
        self.assertEqual(diffs[0].file_path, "a.txt")
        self.assertIn("+hello world", diffs[0].hunks)

    def test_ref_based_diff(self):
        self._write("a.txt", "one\n")
        self._commit_all("first")
        self._write("a.txt", "one\nchanged\n")
        self._commit_all("second")

        diffs = get_file_diffs(self.temp_dir, ref="HEAD~1")

        self.assertEqual(len(diffs), 1)
        self.assertIn("+changed", diffs[0].hunks)

    def test_staged_changes_without_commits(self):
        self._write("a.txt", "staged\n")
        self.repo.index.add("a.txt")

        diffs = get_file_diffs(self.temp_dir)

        self.assertEqual(len(diffs), 1)
        self.assertEqual(diffs[0].file_path, "a.txt")
        self.assertIn("+staged", diffs[0].hunks)

    def test_clean_working_tree_returns_no_diffs(self):
        self._write("a.txt", "hello\n")
        self._commit_all("initial")

        self.assertEqual(get_file_diffs(self.temp_dir), [])

    def test_not_a_repository(self):
        with tempfile.TemporaryDirectory() as not_repo:
            with self.assertRaises(ValueError):
                get_file_diffs(not_repo)


if __name__ == "__main__":
    unittest.main()
