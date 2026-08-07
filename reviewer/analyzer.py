import json
import logging
import os
from pathlib import Path
from typing import TYPE_CHECKING

from dotenv import load_dotenv
from groq import Groq
from pydantic import ValidationError

from .guidelines import load_guidelines
from .parser import chunk_code
from .prompt_builder import (
    CodeReviewResult,
    build_diff_review_prompt,
    build_review_prompt,
)

if TYPE_CHECKING:
    from .git_utils import FileDiff

load_dotenv()

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = (
    "You are a senior software engineer conducting a thorough code review. "
    "You must respond ONLY in valid JSON matching the requested structure. "
    "Do not include markdown formatting like ```json or plain text outside the JSON."
)


class Analyzer:
    """Analyzes source files using the Groq LLM API."""

    def __init__(self, timeout: int = 60, max_tokens: int = 6000) -> None:
        """Initializes the Analyzer with the Groq API client."""
        api_key = os.environ.get("GROQ_API_KEY")
        if not api_key:
            raise ValueError("GROQ_API_KEY is missing from environment variables.")
        self.client = Groq(api_key=api_key)
        # Using Llama 3 for structured JSON output compatibility on Groq
        self.model = "llama-3.3-70b-versatile"
        self.timeout = timeout
        self.max_tokens = max_tokens

    def analyze_file(
        self,
        file_path: str,
        target_root: str | None = None,
        guidelines_path: str | None = None,
    ) -> CodeReviewResult:
        """
        Reads a file and sends it to the Groq API for review.

        Large files are split into structurally-bounded chunks (see parser.py),
        each reviewed separately and merged into a single result.

        Args:
            file_path: The path to the file to be analyzed.
            target_root: Directory that file paths must resolve within.
                Defaults to the current working directory.
            guidelines_path: Optional explicit path to a custom guidelines file.

        Returns:
            A validated CodeReviewResult model.

        Raises:
            FileNotFoundError: If the resolved file does not exist.
            ValueError: If the path is unsafe, unreadable, or not valid UTF-8 text.
            RuntimeError: If the API call or response parsing fails.
        """
        resolved_path = self._resolve_safe_path(file_path, target_root)

        if not os.path.exists(resolved_path):
            raise FileNotFoundError(f"File not found: {resolved_path}")

        try:
            with open(resolved_path, "r", encoding="utf-8", errors="strict") as f:
                code_content = f.read()
        except UnicodeDecodeError as e:
            raise ValueError(
                f"File is not valid UTF-8 text and cannot be reviewed: {resolved_path} ({e})"
            ) from e
        except OSError as e:
            raise ValueError(f"Could not read file: {resolved_path} ({e})") from e

        if not code_content.strip():
            logger.info("File %s is empty; skipping LLM analysis.", resolved_path)
            return CodeReviewResult(
                summary="The file is empty; nothing to review.",
                score=1,
                bugs=[],
            )

        guidelines = load_guidelines(guidelines_path, repo_path=target_root or os.getcwd())
        chunks = chunk_code(code_content, max_tokens=self.max_tokens)

        if len(chunks) == 1:
            prompt = build_review_prompt(
                chunks[0].content,
                resolved_path,
                guidelines=guidelines,
            )
            return self._request_review(prompt)

        results = []
        for chunk in chunks:
            prompt = build_review_prompt(
                chunk.content,
                resolved_path,
                guidelines=guidelines,
                chunk_header=chunk.header,
            )
            results.append(self._request_review(prompt))

        return _merge_results(results)

    def analyze_diffs(
        self,
        file_diffs: list["FileDiff"],
        guidelines_path: str | None = None,
        repo_path: str | None = None,
    ) -> CodeReviewResult:
        """
        Sends parsed git diffs to the Groq API for review.

        Args:
            file_diffs: The parsed per-file diffs to review.
            guidelines_path: Optional explicit path to a custom guidelines file.
            repo_path: Repository root to search for default guidelines files.

        Returns:
            A validated CodeReviewResult model.

        Raises:
            RuntimeError: If the API call or response parsing fails.
        """
        if not file_diffs:
            return CodeReviewResult(
                summary="No changes to review.",
                score=10,
                bugs=[],
            )

        guidelines = load_guidelines(guidelines_path, repo_path=repo_path or os.getcwd())
        prompt = build_diff_review_prompt(file_diffs, guidelines=guidelines)
        return self._request_review(prompt)

    def _request_review(self, prompt: str) -> CodeReviewResult:
        """Sends a prepared prompt to the LLM and validates the JSON response."""
        try:
            response = self.client.chat.completions.create(
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                model=self.model,
                response_format={"type": "json_object"},
                temperature=0.2,
                timeout=self.timeout,
            )
        except Exception as e:
            raise RuntimeError(f"Error during API call: {e}") from e

        result_text = response.choices[0].message.content
        if not result_text:
            raise RuntimeError("The LLM returned an empty response.")

        return self._parse_response(result_text)

    @staticmethod
    def _resolve_safe_path(file_path: str, target_root: str | None = None) -> str:
        """
        Validates that a file path is safe and resolves within the target directory.

        Args:
            file_path: The path to validate.
            target_root: The root directory the path must resolve within.

        Returns:
            The resolved absolute path.

        Raises:
            ValueError: If the path contains path traversal components or resolves
                outside the target directory.
        """
        base = os.path.abspath(os.path.expanduser(target_root or os.getcwd()))

        if ".." in Path(file_path).parts:
            raise ValueError(f"Path traversal detected in file path: {file_path}")

        resolved = os.path.realpath(os.path.abspath(os.path.expanduser(file_path)))
        base_real = os.path.realpath(base)

        if resolved != base_real and not resolved.startswith(base_real + os.sep):
            raise ValueError(
                f"File path resolves outside the target directory: {file_path}"
            )

        return resolved

    @staticmethod
    def _parse_response(result_text: str) -> CodeReviewResult:
        """
        Parses and validates the raw LLM response against the CodeReviewResult schema.

        Args:
            result_text: The raw text returned by the LLM.

        Returns:
            A validated CodeReviewResult model.

        Raises:
            RuntimeError: If the response is not valid JSON or fails schema validation.
        """
        try:
            data = json.loads(result_text)
        except json.JSONDecodeError as e:
            logger.error("LLM returned invalid JSON. Raw response:\n%s", result_text)
            raise RuntimeError(
                "The LLM returned a response that is not valid JSON. "
                "The raw response has been logged for debugging."
            ) from e

        try:
            return CodeReviewResult.model_validate(data)
        except ValidationError as e:
            logger.error("LLM response failed schema validation. Raw response:\n%s", result_text)
            raise RuntimeError(
                f"The LLM returned a response that does not match the expected schema: {e}"
            ) from e


def _merge_results(results: list[CodeReviewResult]) -> CodeReviewResult:
    """Merges per-chunk review results into a single CodeReviewResult."""
    if not results:
        raise RuntimeError("No review results to merge.")
    if len(results) == 1:
        return results[0]

    summary = "\n\n".join(result.summary for result in results)
    score = round(sum(result.score for result in results) / len(results))
    score = max(1, min(10, score))

    bugs = []
    for result in results:
        bugs.extend(result.bugs)

    return CodeReviewResult(summary=summary, score=score, bugs=bugs)
