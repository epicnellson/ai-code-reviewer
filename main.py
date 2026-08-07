import argparse
import json
import logging
import sys

from rich.console import Console

from reviewer.analyzer import Analyzer
from reviewer.git_utils import get_file_diffs, get_repo_root
from reviewer.prompt_builder import CodeReviewResult
from reviewer.reporter import print_review, print_review_plain

console = Console()


def build_parser() -> argparse.ArgumentParser:
    """Builds the CLI argument parser."""
    parser = argparse.ArgumentParser(description="AI-powered Code Review Agent")
    parser.add_argument("--file", type=str, default=None, help="Path to the file to review")
    parser.add_argument(
        "--diff",
        type=str,
        nargs="?",
        const="",
        default=None,
        help="Git reference to diff against (e.g. HEAD~1 or main). "
        "With no value, reviews local staged/unstaged changes.",
    )
    parser.add_argument(
        "--base-dir",
        type=str,
        default=None,
        help="Directory that file paths must resolve within (defaults to the current working directory)",
    )
    parser.add_argument(
        "--guidelines",
        type=str,
        default=None,
        help="Path to a custom guidelines file (.ai-review.toml or guidelines.md). "
        "Defaults to searching the repository root.",
    )
    parser.add_argument(
        "--max-tokens",
        type=int,
        default=6000,
        help="Rough per-chunk token budget for large-file splitting (default: 6000)",
    )
    parser.add_argument(
        "--ci",
        action="store_true",
        help="CI mode: plain output and exit code 1 if any high-severity bugs are found",
    )
    parser.add_argument(
        "--format",
        choices=["text", "json"],
        default="text",
        help="Output format (default: text)",
    )
    return parser


def _ci_exit_code(review_result: CodeReviewResult, ci: bool) -> int:
    """Returns the process exit code: 1 in CI mode if a high-severity bug exists, else 0."""
    if ci and any(bug.severity == "high" for bug in review_result.bugs):
        return 1
    return 0


def _print_json(review_result: CodeReviewResult) -> None:
    """Prints the review result as pretty-printed JSON to stdout."""
    print(json.dumps(review_result.model_dump(), indent=2))


def main() -> None:
    """Main CLI entry point for the AI Code Reviewer."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    parser = build_parser()
    args = parser.parse_args()

    if not args.file and args.diff is None:
        parser.error("one of --file or --diff is required")

    is_json = args.format == "json"
    label = args.file or args.diff or "working tree changes"

    try:
        analyzer = Analyzer(max_tokens=args.max_tokens)

        if args.file:
            if not is_json and not args.ci:
                console.print(f"[bold green]Analyzing file:[/] {args.file}...")
                with console.status("[bold cyan]Waiting for LLM analysis...[/]"):
                    review_result = analyzer.analyze_file(
                        args.file,
                        target_root=args.base_dir,
                        guidelines_path=args.guidelines,
                    )
            else:
                review_result = analyzer.analyze_file(
                    args.file,
                    target_root=args.base_dir,
                    guidelines_path=args.guidelines,
                )
        else:
            diff_ref = args.diff or None
            file_diffs = get_file_diffs(repo_path=".", ref=diff_ref)

            if not file_diffs:
                if is_json:
                    print(json.dumps(CodeReviewResult(summary="No changes to review.", score=10, bugs=[]).model_dump(), indent=2))
                else:
                    print("No changes to review.")
                sys.exit(0)

            repo_root = get_repo_root(".")

            if not is_json and not args.ci:
                console.print(f"[bold green]Analyzing git diff ({label})...[/]")
                with console.status("[bold cyan]Waiting for LLM analysis...[/]"):
                    review_result = analyzer.analyze_diffs(
                        file_diffs,
                        guidelines_path=args.guidelines,
                        repo_path=repo_root,
                    )
            else:
                review_result = analyzer.analyze_diffs(
                    file_diffs,
                    guidelines_path=args.guidelines,
                    repo_path=repo_root,
                )

    except FileNotFoundError as e:
        console.print(f"\n[bold red]Error:[/] {e}")
        sys.exit(1)
    except ValueError as e:
        console.print(f"\n[bold red]Configuration Error:[/] {e}")
        sys.exit(1)
    except RuntimeError as e:
        console.print(f"\n[bold red]Review failed:[/] {e}")
        sys.exit(1)
    except Exception as e:
        console.print(f"\n[bold red]Unexpected Error:[/] {e}")
        sys.exit(1)

    if is_json:
        _print_json(review_result)
    elif args.ci:
        print_review_plain(review_result, label)
    else:
        print_review(review_result, label)

    sys.exit(_ci_exit_code(review_result, args.ci))


if __name__ == "__main__":
    main()
