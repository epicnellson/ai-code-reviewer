from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from .prompt_builder import BugReport, CodeReviewResult

console = Console()

_SEVERITY_ORDER = {"high": 0, "medium": 1, "low": 2}
_SEVERITY_STYLES = {"high": "bold red", "medium": "bold yellow", "low": "bold green"}


def print_review(review_result: CodeReviewResult, file_path: str) -> None:
    """
    Prints the structured code review to the console using Rich.

    Args:
        review_result: The validated review result to display.
        file_path: The name or path of the file that was reviewed.
    """
    console.print(f"\n[bold blue]Code Review for:[/] {file_path}")
    console.print(f"[bold]Score:[/] {review_result.score}/10\n")

    console.print(Panel(review_result.summary, title="Summary", expand=False))
    console.print()

    _print_bugs(review_result.bugs)


def print_review_plain(review_result: CodeReviewResult, file_path: str) -> None:
    """
    Prints the structured code review as plain, dependency-free text (CI friendly).

    Args:
        review_result: The validated review result to display.
        file_path: The name or path of the file that was reviewed.
    """
    print(f"Code Review for: {file_path}")
    print(f"Score: {review_result.score}/10")
    print()
    print(f"Summary: {review_result.summary}")
    print()

    bugs = _sorted_bugs(review_result.bugs)
    if not bugs:
        print("No bugs found.")
        return

    print("Bugs:")
    for bug in bugs:
        print(f"  [{bug.severity.upper()}] Line {bug.line}: {bug.description}")
        print(f"    Fix: {bug.suggested_fix}")


def _sorted_bugs(bugs: list[BugReport]) -> list[BugReport]:
    """Returns bugs ordered by severity (high first, then medium, then low)."""
    return sorted(bugs, key=lambda b: _SEVERITY_ORDER.get(b.severity, 3))


def _print_bugs(bugs: list[BugReport]) -> None:
    """Prints the bugs section, ordering high-severity issues first."""
    sorted_bugs = _sorted_bugs(bugs)

    if not sorted_bugs:
        console.print("[green]✔ No bugs found.[/green]\n")
        return

    table = Table(title="Bugs", title_style="bold red", header_style="bold red", show_header=True)
    table.add_column("Line", justify="right", style="cyan", no_wrap=True)
    table.add_column("Severity")
    table.add_column("Description")
    table.add_column("Suggested Fix")

    for bug in sorted_bugs:
        table.add_row(
            str(bug.line),
            f"[{_SEVERITY_STYLES.get(bug.severity, 'bold white')}]{bug.severity.upper()}[/]",
            bug.description,
            bug.suggested_fix,
        )

    console.print(table)
    console.print()
