# AI Code Reviewer (`ai-code-reviewer`)

An intelligent, AST-aware CLI tool and CI action for automated code reviews powered by LLMs (Groq / Llama 3.3). Built for speed, precision, and seamless integration into developer workflows.

---

## Key Features

- **Git Diff Analysis:** Review only modified lines (`git diff` or specific commit refs) to save tokens and focus on actual changes.
- **AST-Aware Parsing & Chunking:** Uses `tree-sitter` to split large files logically along function and class boundaries without losing context.
- **Custom Team Guidelines:** Enforce project-specific standards via `.ai-review.toml` or `guidelines.md`.
- **CI Mode & Exit Codes:** Non-interactive plain text or JSON output with non-zero exit codes (`exit 1`) for high-severity findings to block PR merges.
- **Robust & Hardened:** Pydantic schema validation, path traversal defense, API timeouts, and automatic retry handling.

---

## Installation

### Local Installation

```bash
pip install ai-code-reviewer
```

> **Note:** The package name on PyPI is `ai-code-reviewer`; the executable is `ai-code-review`. Install from source if the package is not yet published:

```bash
git clone https://github.com/epicnellson/ai-code-reviewer.git
cd ai-code-reviewer
python -m pip install -e .
```

### Requirements

- Python 3.10 or newer
- A Groq API key (set as `GROQ_API_KEY`)

### Configuration

Copy `.env.example` to `.env` and add your API key:

```bash
cp .env.example .env
```

The tool reads `GROQ_API_KEY` from your environment or `.env` (via `python-dotenv`). The GitHub Actions workflow instead uses the `GROQ_API_KEY` repository secret.

---

## Usage

### Review a Single File

```bash
ai-code-review --file path/to/your/file.py
```

For projects hosted under a different root directory, restrict path resolution:

```bash
ai-code-review --file src/app.py --base-dir ./src
```

### Review a Git Diff

Compare the working tree against a branch or commit ref:

```bash
# Against a remote branch (e.g. in CI)
ai-code-review --diff origin/main

# Against a commit ref
ai-code-review --diff HEAD~1

# Against local staged/unstaged changes (no value)
ai-code-review --diff
```

This analyzes only modified lines, saving tokens and focusing the review on actual changes.

### Adjust Chunking Budget

Very large files are split along function and class boundaries using `tree-sitter`. Tune the rough per-chunk token budget:

```bash
ai-code-review --file app.py --max-tokens 8000
```

---

## Custom Team Guidelines

Enforce project-specific standards by adding either a `.ai-review.toml` or a `guidelines.md` file in your repository root, or point to a file explicitly:

```bash
ai-code-review --file app.py --guidelines ./docs/code-standards.toml
```

`.ai-review.toml` supports a top-level string or list, or a `[review]` table:

```toml
guidelines = "Never use eval(). Every function needs a docstring."
```

```toml
guidelines = [
  "Never use eval().",
  "Every function needs a docstring.",
]
```

```toml
[review]
guidelines = "Prefer async over thread pools."
```

Guidelines are injected into every review prompt as authoritative rules and the reviewer flags violations.

---

## CI Mode & Exit Codes

Use `--ci` for non-interactive output:

```bash
ai-code-review --diff origin/main --ci --format text
```

- `--format text` prints human-readable output (default).
- `--format json` emits machine-readable structured results.
- The process exits with code `1` when high-severity bugs are found (in CI mode), so the step fails and blocks the PR merge. It exits `0` when the review is clean or only low/medium issues are found.

---

## GitHub Actions Integration

`.github/workflows/ai-review.yml` runs the review on every PR to `main`/`master`, comparing against the target branch and passing the `GROQ_API_KEY` secret:

```yaml
permissions:
  contents: read

concurrency:
  group: ${{ github.workflow }}-${{ github.ref }}
  cancel-in-progress: true

steps:
  - uses: actions/checkout@v4
    with:
      fetch-depth: 0
  - uses: actions/setup-python@v5
    with:
      python-version: '3.11'
  - run: pip install -e .
  - run: ai-code-review --diff origin/${{ github.base_ref }} --ci --format text
    env:
      GROQ_API_KEY: ${{ secrets.GROQ_API_KEY }}
```

Because the job exits non-zero on high-severity findings, a failing review automatically blocks PR merge checks. Add the job to your branch protection rules as a required status check for full enforcement.

---

## Release Automation

`.github/workflows/publish.yml` builds an sdist and wheel and publishes to PyPI via Trusted Publishers (OIDC) whenever a GitHub Release is published:

```bash
gh release create v1.0.0 \
  --title "v1.0.0 — AI Code Reviewer Initial Release" \
  --notes "Initial v1.0.0 production release."
```

Configure a Trusted Publisher on PyPI pointing at this repository before your first publish.

---

## Development

Run the test suite:

```bash
python -m pytest
```

### Project Structure

```
reviewer/
  analyzer.py        Review orchestration, chunked analysis, result merging
  parser.py          tree-sitter AST extraction and logical chunking
  prompt_builder.py  LLM prompt construction with schema + guidelines
  guidelines.py      .ai-review.toml / guidelines.md loading
  git_utils.py       Git diff extraction and repo root resolution
  reporter.py        text / JSON output formatting
main.py              CLI entry point (ai-code-review)
tests/               Unit + integration tests (pytest)
```
