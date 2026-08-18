"""Utilities for extracting git diffs using GitPython."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class FileDiff:
    """A parsed diff for a single file."""

    file_path: str
    hunks: str


def get_file_diffs(repo_path: str = ".", ref: str | None = None) -> list[FileDiff]:
    """
    Extracts per-file diffs from a git repository.

    Args:
        repo_path: Path to the repository (searches parent directories).
        ref: Optional commit or branch reference (e.g. ``HEAD~1`` or ``main``).
            When ``None``, extracts local staged and unstaged changes.

    Returns:
        A list of ``FileDiff`` objects, one per changed text file.

    Raises:
        ValueError: If ``repo_path`` is not inside a git repository.
    """
    from git import GitCommandError, InvalidGitRepositoryError, Repo

    try:
        repo = Repo(repo_path, search_parent_directories=True)
    except InvalidGitRepositoryError:
        raise ValueError(f"Not a git repository (or any parent directory): {repo_path}")

    try:
        raw = repo.git.diff(ref) if ref else repo.git.diff("HEAD")
    except GitCommandError:
        raw = _diff_without_head(repo)

    return _parse_diff_text(raw)


def get_repo_root(repo_path: str = ".") -> str:
    """
    Returns the working-tree root of the git repository containing ``repo_path``.

    Args:
        repo_path: Path inside the repository (searches parent directories).

    Returns:
        The absolute path of the repository root.

    Raises:
        ValueError: If ``repo_path`` is not inside a git repository.
    """
    from git import InvalidGitRepositoryError, Repo

    try:
        repo = Repo(repo_path, search_parent_directories=True)
    except InvalidGitRepositoryError:
        raise ValueError(f"Not a git repository (or any parent directory): {repo_path}")
    return repo.working_tree_dir


def _diff_without_head(repo) -> str:
    """Collects staged and unstaged changes in a repository that has no commits yet."""
    from git import GitCommandError
    parts = []
    for args in (("--cached",), ()):
        try:
            output = repo.git.diff(*args)
            if output:
                parts.append(output)
        except GitCommandError:
            continue
    return "\n".join(parts)


def _parse_diff_text(raw: str) -> list[FileDiff]:
    """Splits raw git diff output into per-file ``FileDiff`` objects."""
    result: list[FileDiff] = []
    # Normalize so every file chunk starts right after a "diff --git " separator,
    # and never split on hunk content lines (they are prefixed with ' ', '+' or '-').
    chunks = [c for c in ("\n" + raw).split("\ndiff --git ") if c.strip()]

    for chunk in chunks:
        lines = chunk.splitlines()
        if not lines:
            continue
        if " b/" not in lines[0]:
            continue

        new_path = lines[0].split(" b/", 1)[1].strip()
        body = "\n".join(lines[1:])

        if "Binary files" in body or "GIT binary patch" in body:
            continue

        result.append(FileDiff(file_path=new_path, hunks=body))

    return result
