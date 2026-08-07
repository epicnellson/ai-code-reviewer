import os
import tempfile
import unittest
from unittest.mock import patch

from reviewer.analyzer import Analyzer, _merge_results
from reviewer.parser import chunk_code, extract_definitions
from reviewer.prompt_builder import BugReport, CodeReviewResult

CODE = (
    "import os\n\n\n"
    "def top():\n"
    "    x = 1\n"
    "    return x\n\n\n"
    "class Foo:\n"
    "    def bar(self):\n"
    "        return 1\n\n"
    "    def baz(self):\n"
    "        return 2\n\n\n"
    "def another():\n"
    "    pass\n"
)


def _many_functions(count, lines_per_function):
    parts = []
    for i in range(count):
        parts.append(f"def func_{i}():\n")
        parts.append("    # filler\n" * lines_per_function)
        parts.append("    pass\n\n")
    return "".join(parts)


class ExtractDefinitionsTests(unittest.TestCase):
    def test_extracts_functions_classes_and_methods(self):
        definitions = extract_definitions(CODE)

        summary = {(d.kind, d.name, d.start_line, d.end_line) for d in definitions}

        self.assertIn(("function", "top", 4, 6), summary)
        self.assertIn(("class", "Foo", 9, 14), summary)
        self.assertIn(("function", "bar", 10, 11), summary)
        self.assertIn(("function", "baz", 13, 14), summary)
        self.assertIn(("function", "another", 17, 18), summary)

    def test_returns_empty_for_unparseable_input(self):
        self.assertEqual(extract_definitions(""), [])


class ChunkCodeTests(unittest.TestCase):
    def test_small_file_is_single_chunk(self):
        chunks = chunk_code(CODE, max_tokens=6000)

        self.assertEqual(len(chunks), 1)
        self.assertEqual(chunks[0].header, "entire file")
        self.assertEqual(chunks[0].content, CODE)

    def test_empty_code_single_chunk(self):
        chunks = chunk_code("")

        self.assertEqual(len(chunks), 1)
        self.assertEqual(chunks[0].content, "")

    def test_large_file_chunked_at_definition_boundaries(self):
        code = _many_functions(6, 4)
        chunks = chunk_code(code, max_tokens=50)

        self.assertGreaterEqual(len(chunks), 2)

        def_start_lines = {d.start_line for d in extract_definitions(code)}
        for chunk in chunks:
            self.assertIn(chunk.start_line, def_start_lines)
            self.assertTrue(chunk.content)

        self.assertTrue(chunks[0].header.startswith("function `func_0`"))
        self.assertIn("def func_5", chunks[-1].content)

    def test_chunks_reconstruct_original_code(self):
        code = _many_functions(6, 4)
        chunks = chunk_code(code, max_tokens=50)

        self.assertEqual("".join(c.content for c in chunks), code)

    def test_oversized_single_function_falls_back_to_slicing(self):
        code = "def huge():\n" + "".join(f"    x = {i}\n" for i in range(500)) + "    return x\n"
        chunks = chunk_code(code, max_tokens=50)

        self.assertGreater(len(chunks), 1)
        self.assertEqual("".join(c.content for c in chunks), code)
        self.assertTrue(chunks[0].header.startswith("function `huge`"))


class MergeResultsTests(unittest.TestCase):
    def test_merges_summaries_scores_and_bugs(self):
        r1 = CodeReviewResult(
            summary="first half",
            score=5,
            bugs=[BugReport(line=1, severity="high", description="x", suggested_fix="y")],
        )
        r2 = CodeReviewResult(summary="second half", score=9, bugs=[])

        merged = _merge_results([r1, r2])

        self.assertEqual(merged.score, 7)
        self.assertEqual(len(merged.bugs), 1)
        self.assertIn("first half", merged.summary)
        self.assertIn("second half", merged.summary)

    def test_merge_clamps_score_to_bounds(self):
        r1 = CodeReviewResult(summary="a", score=1, bugs=[])
        r2 = CodeReviewResult(summary="b", score=1, bugs=[])

        merged = _merge_results([r1, r2])
        self.assertEqual(merged.score, 1)


class AnalyzerChunkingTests(unittest.TestCase):
    def test_analyze_file_chunks_and_merges(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "big.py")
            with open(path, "w", encoding="utf-8") as f:
                f.write(_many_functions(6, 4))

            analyzer = Analyzer.__new__(Analyzer)
            analyzer.max_tokens = 50
            calls = {"n": 0}

            def fake_request(prompt):
                calls["n"] += 1
                return CodeReviewResult(
                    summary=f"part {calls['n']}",
                    score=5,
                    bugs=[
                        BugReport(line=1, severity="medium", description="x", suggested_fix="y")
                    ],
                )

            with patch.object(analyzer, "_request_review", side_effect=fake_request):
                result = analyzer.analyze_file(path, target_root=tmp)

            self.assertGreaterEqual(calls["n"], 2)
            self.assertEqual(len(result.bugs), calls["n"])
            self.assertIn("part 1", result.summary)


if __name__ == "__main__":
    unittest.main()
