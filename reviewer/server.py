"""Hosted review backend.

The server holds the Groq API key and answers review requests from CLI
clients, so end users never need their own key. Run it with the
``ai-review-server`` console script:

    GROQ_API_KEY=... ai-review-server

Set ``AI_REVIEW_API_TOKEN`` to require clients to authenticate with a
shared bearer token.
"""

import logging
import os

import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, Field

from .analyzer import Analyzer, _merge_results
from .git_utils import FileDiff
from .parser import chunk_code
from .prompt_builder import (
    CodeReviewResult,
    build_diff_review_prompt,
    build_review_prompt,
)

load_dotenv()

logger = logging.getLogger(__name__)

app = FastAPI(title="AI Code Reviewer API", version="1.0.0")


class FileReviewRequest(BaseModel):
    """A request to review a full file by content."""

    path: str = Field(..., description="Path of the file being reviewed.")
    content: str = Field(..., description="Full source code of the file.")
    guidelines: str = Field(default="", description="Team review rules to enforce.")
    max_tokens: int = Field(default=6000, ge=1)


class DiffFile(BaseModel):
    """A single per-file diff as parsed by the client."""

    file_path: str
    hunks: str


class DiffReviewRequest(BaseModel):
    """A request to review a set of per-file diffs."""

    file_diffs: list[DiffFile] = Field(default_factory=list)
    guidelines: str = Field(default="")


def _require_auth(request: Request) -> None:
    """Rejects requests that do not carry the configured client token."""
    token = os.environ.get("AI_REVIEW_API_TOKEN")
    if token and request.headers.get("Authorization") != f"Bearer {token}":
        raise HTTPException(status_code=401, detail="Invalid or missing API token.")


def _analyzer() -> Analyzer:
    """Returns a direct-mode Analyzer using the server-side GROQ_API_KEY."""
    return Analyzer()


@app.get("/health")
def health() -> dict:
    """Health-check endpoint used by monitoring and clients."""
    return {"status": "ok", "service": "ai-code-reviewer"}


@app.post("/api/review/file")
def review_file(payload: FileReviewRequest, request: Request) -> CodeReviewResult:
    """Chunks, prompts, and reviews a file's content via the LLM."""
    _require_auth(request)
    try:
        if not payload.content.strip():
            return CodeReviewResult(
                summary="The file is empty; nothing to review.",
                score=1,
                bugs=[],
            )

        analyzer = _analyzer()
        chunks = chunk_code(payload.content, max_tokens=payload.max_tokens)
        results = []
        for chunk in chunks:
            prompt = build_review_prompt(
                chunk.content,
                payload.path,
                guidelines=payload.guidelines,
                chunk_header=chunk.header if len(chunks) > 1 else None,
            )
            results.append(analyzer._request_review(prompt))

        return _merge_results(results)
    except Exception as e:
        logger.exception("File review failed")
        raise HTTPException(status_code=500, detail=f"Review failed: {e}") from e


@app.post("/api/review/diff")
def review_diff(payload: DiffReviewRequest, request: Request) -> CodeReviewResult:
    """Reviews a set of per-file git diffs via the LLM."""
    _require_auth(request)
    try:
        if not payload.file_diffs:
            return CodeReviewResult(
                summary="No changes to review.",
                score=10,
                bugs=[],
            )

        file_diffs = [
            FileDiff(file_path=d.file_path, hunks=d.hunks) for d in payload.file_diffs
        ]
        analyzer = _analyzer()
        prompt = build_diff_review_prompt(file_diffs, guidelines=payload.guidelines)
        return analyzer._request_review(prompt)
    except Exception as e:
        logger.exception("Diff review failed")
        raise HTTPException(status_code=500, detail=f"Review failed: {e}") from e


def run() -> None:
    """Entry point for the ``ai-review-server`` console script."""
    host = os.environ.get("AI_REVIEW_HOST", "0.0.0.0")
    port = int(os.environ.get("AI_REVIEW_PORT", "8000"))
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    run()
