import json
import logging
import os
import urllib.error
import urllib.request
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

DEFAULT_HOSTED_API_URL = "https://your-hosted-server-url.com"

_SERVER_BUSY_MESSAGE = (
    "Server is currently busy or unreachable. "
    "You can also run locally by providing your own API key: "
    "export GROQ_API_KEY='your-key'"
)

SYSTEM_PROMPT = (
    "You are a senior software engineer conducting a thorough code review. "
    "You must respond ONLY in valid JSON matching the requested structure. "
    "Do not include markdown formatting like ```json or plain text outside the JSON."
)


class Analyzer:
    """Analyzes source files using the Groq LLM API or a hosted review backend.

    Two operating modes are supported:

    - Direct mode: requires ``GROQ_API_KEY`` and calls the Groq API directly.
    - Client mode: configured via ``api_url`` (or the ``AI_REVIEW_API_URL``
      environment variable). The analyzer sends review requests to a hosted
      backend (see ``reviewer/server.py``), so users never need their own
      Groq key.
    """

    def __init__(
        self,
        timeout: int = 60,
        max_tokens: int = 6000,
        api_url: str | None = None,
        api_token: str | None = None,
    ) -> None:
        """Initializes the Analyzer in direct, custom-hosted, or default-hosted mode.

        Resolution order:
        1. If *api_url* is passed → Custom hosted mode (always).
        2. ``GROQ_API_KEY`` is set → Direct mode (Groq API).
        3. ``AI_REVIEW_API_URL`` is set → Custom hosted mode.
        4. Otherwise → Default hosted mode (uses ``DEFAULT_HOSTED_API_URL``).
        """
        self.timeout = timeout
        self.max_tokens = max_tokens
        self.model = "llama-3.3-70b-versatile"
        self._using_default_server = False

        # Explicit api_url parameter always wins → custom hosted mode
        explicit_url = (api_url or "").strip().rstrip("/")
        if explicit_url:
            self.client = None
            self.api_url = explicit_url
            self.api_token = api_token or os.environ.get("AI_REVIEW_API_TOKEN") or ""
            return

        # Tier 1: GROQ_API_KEY → direct Groq mode
        api_key = os.environ.get("GROQ_API_KEY")
        if api_key:
            self.client = Groq(api_key=api_key)
            self.api_url = ""
            self.api_token = api_token or os.environ.get("AI_REVIEW_API_TOKEN") or ""
            return

        # Tier 2: AI_REVIEW_API_URL env → custom hosted mode
        env_url = (os.environ.get("AI_REVIEW_API_URL") or "").strip().rstrip("/")
        if env_url:
            self.client = None
            self.api_url = env_url
            self.api_token = api_token or os.environ.get("AI_REVIEW_API_TOKEN") or ""
            return

        # Tier 3: no key, no URL → default hosted mode
        self.client = None
        self.api_url = DEFAULT_HOSTED_API_URL.rstrip("/")
        self.api_token = api_token or os.environ.get("AI_REVIEW_API_TOKEN") or ""
        self._using_default_server = True

    def check_health(self, timeout: int = 5) -> bool:
        """Pings the hosted backend's ``/health`` endpoint.

        Returns ``True`` if the backend responds with HTTP 200, ``False``
        on any connection or response error.  Only meaningful in client mode;
        in direct mode this always returns ``True``.
        """
        if not self.api_url:
            return True

        url = f"{self.api_url}/health"
        headers = {}
        if self.api_token:
            headers["Authorization"] = f"Bearer {self.api_token}"

        request = urllib.request.Request(url, headers=headers, method="GET")
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return response.status == 200
        except Exception:
            logger.debug("Health check failed for %s", url, exc_info=True)
            return False

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

        if not self.client:
            return self._remote_file_review(resolved_path, code_content, guidelines)

        return self._review_content(resolved_path, code_content, guidelines)

    def _review_content(self, path: str, content: str, guidelines: str) -> CodeReviewResult:
        """Chunks ``content``, reviews each chunk via the LLM, and merges the results."""
        chunks = chunk_code(content, max_tokens=self.max_tokens)

        if len(chunks) == 1:
            prompt = build_review_prompt(
                chunks[0].content,
                path,
                guidelines=guidelines,
            )
            return self._request_review(prompt)

        results = []
        for chunk in chunks:
            prompt = build_review_prompt(
                chunk.content,
                path,
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

        if not self.client:
            return self._remote_diff_review(file_diffs, guidelines)

        prompt = build_diff_review_prompt(file_diffs, guidelines=guidelines)
        return self._request_review(prompt)

    def _remote_file_review(self, path: str, content: str, guidelines: str) -> CodeReviewResult:
        """Sends a whole-file review request to the hosted backend."""
        payload = {
            "path": path,
            "content": content,
            "guidelines": guidelines,
            "max_tokens": self.max_tokens,
        }
        return self._http_post("/api/review/file", payload)

    def _remote_diff_review(
        self,
        file_diffs: list["FileDiff"],
        guidelines: str,
    ) -> CodeReviewResult:
        """Sends a git-diff review request to the hosted backend."""
        payload = {
            "file_diffs": [
                {"file_path": d.file_path, "hunks": d.hunks} for d in file_diffs
            ],
            "guidelines": guidelines,
        }
        return self._http_post("/api/review/diff", payload)

    def _http_post(self, endpoint: str, payload: dict) -> CodeReviewResult:
        """POSTs a JSON payload to the hosted backend and validates the response."""
        url = f"{self.api_url}{endpoint}"
        headers = {"Content-Type": "application/json"}
        if self.api_token:
            headers["Authorization"] = f"Bearer {self.api_token}"

        request = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                data = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", errors="replace") if e.fp else str(e)
            if self._using_default_server and e.code == 429:
                raise RuntimeError(_SERVER_BUSY_MESSAGE) from e
            raise RuntimeError(f"Review backend returned HTTP {e.code}: {detail}") from e
        except urllib.error.URLError as e:
            if self._using_default_server:
                raise RuntimeError(_SERVER_BUSY_MESSAGE) from e
            raise RuntimeError(f"Could not reach review backend at {url}: {e.reason}") from e
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            raise RuntimeError(f"Review backend returned an unreadable response: {e}") from e

        try:
            return CodeReviewResult.model_validate(data)
        except ValidationError as e:
            raise RuntimeError(f"Review backend returned an invalid review: {e}") from e

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
