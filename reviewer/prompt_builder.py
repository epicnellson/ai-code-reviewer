import json
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field, field_validator

if TYPE_CHECKING:
    from .git_utils import FileDiff


class BugReport(BaseModel):
    """A single issue found during code review."""

    line: int = Field(..., ge=0, description="Line number in the reviewed file where the issue occurs.")
    severity: str = Field(..., description="Severity of the issue: 'low', 'medium', or 'high'.")
    description: str = Field(..., description="Description of the issue found.")
    suggested_fix: str = Field(..., description="Suggested fix or remediation for the issue.")

    @field_validator("severity")
    @classmethod
    def _normalize_severity(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in {"low", "medium", "high"}:
            raise ValueError(f"severity must be one of 'low', 'medium', 'high'; got '{value}'")
        return normalized


class CodeReviewResult(BaseModel):
    """Structured output expected from the LLM for a code review."""

    summary: str = Field(..., description="Brief overall assessment of the code.")
    score: int = Field(..., ge=1, le=10, description="Overall code quality score from 1 to 10.")
    bugs: list[BugReport] = Field(
        default_factory=list,
        description="List of issues found in the code.",
    )


def build_review_prompt(
    code: str,
    file_path: str,
    guidelines: str = "",
    chunk_header: str | None = None,
) -> str:
    """
    Builds the prompt string to send to the LLM for a whole-file review.

    Args:
        code: The source code (or a chunk of it) to review.
        file_path: The name or path of the file.
        guidelines: Optional team-specific review rules to enforce.
        chunk_header: Optional structural header identifying the code section.

    Returns:
        The formatted prompt string asking for a structured JSON response
        that conforms to the CodeReviewResult schema.
    """
    scope = f" from the file `{file_path}`"
    if chunk_header:
        scope += f", section: {chunk_header}"

    parts = [
        f"Please review the following code{scope}.",
        "",
        "Code:",
        "```",
        code,
        "```",
    ]

    parts.extend(_guidelines_section(guidelines))
    parts.extend(["", _schema_instructions()])

    return "\n".join(parts)


def build_diff_review_prompt(
    file_diffs: list["FileDiff"],
    guidelines: str = "",
) -> str:
    """
    Builds the prompt string to send to the LLM for a git diff review.

    Args:
        file_diffs: The parsed per-file diffs to review, hunks and line context only.
        guidelines: Optional team-specific review rules to enforce.

    Returns:
        The formatted prompt string asking for a structured JSON response
        that conforms to the CodeReviewResult schema.
    """
    sections = []
    for file_diff in file_diffs:
        sections.append(f"File: `{file_diff.file_path}`\n```diff\n{file_diff.hunks}\n```")

    if not sections:
        sections.append("(No changes to review.)")

    diff_text = "\n\n".join(sections)

    parts = [
        "Please review the following git diff. Focus on the changed lines, using the surrounding hunk context to understand intent.",
        "",
        diff_text,
    ]

    parts.extend(_guidelines_section(guidelines))
    parts.extend(["", _schema_instructions()])
    parts.extend(
        [
            "",
            "Guidelines:",
            "- Line numbers in the review refer to line numbers in the NEW version of each file.",
        ]
    )

    return "\n".join(parts)


def _guidelines_section(guidelines: str) -> list[str]:
    """Returns the project-rules section of a prompt, if any guidelines are set."""
    if not guidelines.strip():
        return []
    return [
        "",
        "Project review rules (these are authoritative - flag any violations):",
        guidelines,
    ]


def _schema_instructions() -> str:
    """Returns the JSON schema and output rules section shared by all prompts."""
    schema = json.dumps(CodeReviewResult.model_json_schema(), indent=2)
    return f"""Return your review strictly as JSON that conforms to this JSON Schema:
```json
{schema}
```

Guidelines:
- "score" must be an integer between 1 and 10.
- "severity" must be exactly one of: "low", "medium", "high".
- Only include real, actionable issues in the "bugs" array.
- The response must be ONLY valid JSON. No markdown formatting, no commentary outside the JSON."""
