"""Loading of custom review guidelines from .ai-review.toml or guidelines.md."""

import os
import tomllib

GUIDELINES_FILE_NAMES = (".ai-review.toml", "guidelines.md")


def load_guidelines(guidelines_path: str | None = None, repo_path: str | None = None) -> str:
    """
    Loads custom review guidelines from an explicit file or a repo-root file.

    Search order:
        1. An explicit ``guidelines_path`` (e.g. passed via ``--guidelines``).
        2. ``.ai-review.toml`` in ``repo_path`` (or the current directory).
        3. ``guidelines.md`` in ``repo_path`` (or the current directory).

    Args:
        guidelines_path: Explicit path to a guidelines file. Takes precedence.
        repo_path: Directory to search for ``.ai-review.toml`` / ``guidelines.md``.

    Returns:
        The guidelines text, or ``""`` if no guidelines are configured.

    Raises:
        ValueError: If an explicit path is given but does not exist or is not valid UTF-8.
    """
    if guidelines_path:
        if not os.path.exists(guidelines_path):
            raise ValueError(f"Guidelines file not found: {guidelines_path}")
        return _read_guidelines_file(guidelines_path)

    root = repo_path or os.getcwd()
    for name in GUIDELINES_FILE_NAMES:
        candidate = os.path.join(root, name)
        if os.path.isfile(candidate):
            return _read_guidelines_file(candidate)

    return ""


def _read_guidelines_file(path: str) -> str:
    """Reads a guidelines file, parsing TOML files by extension and raw text otherwise."""
    if path.lower().endswith(".toml"):
        return _read_toml_guidelines(path)
    return _read_text(path)


def _read_toml_guidelines(path: str) -> str:
    """Extracts the ``guidelines`` value from a TOML file (top-level or ``[review]`` table)."""
    with open(path, "rb") as f:
        data = tomllib.load(f)

    value = data.get("guidelines")
    if value is None:
        review = data.get("review", {})
        if isinstance(review, dict):
            value = review.get("guidelines")

    if value is None:
        return ""
    if isinstance(value, list):
        return "\n".join(str(item) for item in value)
    return str(value).strip()


def _read_text(path: str) -> str:
    """Reads a plain text guidelines file."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read().strip()
    except UnicodeDecodeError as e:
        raise ValueError(f"Guidelines file is not valid UTF-8 text: {path} ({e})") from e
