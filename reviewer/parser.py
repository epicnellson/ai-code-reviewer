"""AST-aware parsing and chunking using tree-sitter.

Provides structural extraction of functions, classes and top-level definitions,
plus a chunking utility that splits oversized files on definition boundaries
instead of raw line slicing.
"""

from dataclasses import dataclass

DEFAULT_MAX_TOKENS = 6000
DEFAULT_CHARS_PER_TOKEN = 4

_parser = None


def _get_parser():
    """Lazily builds the shared tree-sitter parser."""
    global _parser
    if _parser is None:
        from tree_sitter import Language, Parser
        import tree_sitter_python

        _parser = Parser(Language(tree_sitter_python.language()))
    return _parser


def _parse(code: str):
    """Parses code, returning the tree, or None if parsing is unavailable/fails."""
    try:
        return _get_parser().parse(code.encode("utf-8"))
    except Exception:
        return None


@dataclass
class Definition:
    """A structural definition extracted from the AST."""

    kind: str
    name: str
    start_line: int
    end_line: int


@dataclass
class CodeChunk:
    """A logically-bounded slice of a source file."""

    header: str
    content: str
    start_line: int
    end_line: int


def extract_definitions(code: str) -> list[Definition]:
    """
    Extracts top-level functions, classes, and class methods with line numbers.

    Args:
        code: The source code to parse.

    Returns:
        A list of Definition objects sorted by start line. Returns an empty
        list if the code cannot be parsed.
    """
    tree = _parse(code)
    if tree is None:
        return []

    definitions: list[Definition] = []
    root = tree.root_node

    for child in root.named_children:
        if child.type in ("function_definition", "class_definition"):
            definitions.append(_to_definition(child))
            if child.type == "class_definition":
                body = child.child_by_field_name("body")
                if body is not None:
                    for member in body.named_children:
                        if member.type == "function_definition":
                            definitions.append(_to_definition(member))

    return definitions


def chunk_code(
    code: str,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    chars_per_token: int = DEFAULT_CHARS_PER_TOKEN,
) -> list[CodeChunk]:
    """
    Splits code into logically-bounded chunks that fit within a token budget.

    Chunks are cut on class/function boundaries. If a single definition alone
    exceeds the budget it is split further, preferring blank-line cut points,
    so large files are never sliced in the middle of a logical unit.

    Args:
        code: The source code to chunk.
        max_tokens: Rough token budget per chunk.
        chars_per_token: Approximate characters per token for estimation.

    Returns:
        A list of CodeChunk objects covering the whole file in order. A file
        within the budget is returned as a single chunk.
    """
    lines = code.splitlines(keepends=True)
    if not lines:
        return [CodeChunk(header="entire file", content="", start_line=1, end_line=1)]

    if _estimate_tokens(code, chars_per_token) <= max_tokens:
        return [CodeChunk(header="entire file", content=code, start_line=1, end_line=len(lines))]

    definitions = extract_definitions(code)
    boundaries = sorted({d.start_line for d in definitions})

    segments = _build_segments(boundaries, len(lines))

    final_segments = []
    for start, end in segments:
        text = "".join(lines[start - 1:end])
        if _estimate_tokens(text, chars_per_token) <= max_tokens:
            final_segments.append((start, end))
        else:
            final_segments.extend(_split_oversized(lines, start, end, max_tokens, chars_per_token))

    return _merge_segments(lines, final_segments, definitions, max_tokens, chars_per_token)


def _to_definition(node) -> Definition:
    """Converts a tree-sitter definition node into a Definition object."""
    name_node = node.child_by_field_name("name")
    name = (
        name_node.text.decode("utf-8", errors="replace")
        if name_node is not None
        else "<anonymous>"
    )
    kind = "class" if node.type == "class_definition" else "function"
    return Definition(
        kind=kind,
        name=name,
        start_line=node.start_point.row + 1,
        end_line=node.end_point.row + 1,
    )


def _build_segments(boundaries: list[int], total_lines: int) -> list[tuple[int, int]]:
    """Builds (start, end) line segments cut at every definition boundary."""
    if not boundaries:
        return [(1, total_lines)]

    segments = []
    if boundaries[0] > 1:
        segments.append((1, boundaries[0] - 1))

    for i, boundary in enumerate(boundaries):
        end = boundaries[i + 1] - 1 if i + 1 < len(boundaries) else total_lines
        if end >= boundary:
            segments.append((boundary, end))

    return segments


def _split_oversized(
    lines: list[str],
    start: int,
    end: int,
    max_tokens: int,
    chars_per_token: int,
) -> list[tuple[int, int]]:
    """Splits an oversized segment by token budget, preferring blank-line cuts."""
    budget_chars = max_tokens * chars_per_token
    segments = []

    seg_start = start
    while seg_start <= end:
        consumed = 0
        count = 0
        for idx in range(seg_start - 1, end):
            if consumed + len(lines[idx]) > budget_chars:
                break
            consumed += len(lines[idx])
            count += 1

        if count == 0:
            count = 1

        seg_end = seg_start + count - 1

        cut = None
        for idx in range(seg_start - 1, seg_end):
            if lines[idx].strip() == "":
                cut = idx + 1
        if cut is not None:
            seg_end = cut

        segments.append((seg_start, seg_end))
        seg_start = seg_end + 1

    return segments


def _merge_segments(
    lines: list[str],
    segments: list[tuple[int, int]],
    definitions: list[Definition],
    max_tokens: int,
    chars_per_token: int,
) -> list[CodeChunk]:
    """Greedily merges adjacent segments while staying within the token budget."""
    merged = []
    for start, end in segments:
        tokens = _estimate_tokens("".join(lines[start - 1:end]), chars_per_token)
        if merged and merged[-1][2] + tokens <= max_tokens:
            prev_start, _, prev_tokens = merged[-1]
            merged[-1] = (prev_start, end, prev_tokens + tokens)
        else:
            merged.append((start, end, tokens))

    return [_make_chunk(lines, s, e, definitions) for s, e, _ in merged]


def _make_chunk(lines: list[str], start: int, end: int, definitions: list[Definition]) -> CodeChunk:
    content = "".join(lines[start - 1:end])
    return CodeChunk(
        header=_header_for(definitions, start, end),
        content=content,
        start_line=start,
        end_line=end,
    )


def _header_for(definitions: list[Definition], start_line: int, end_line: int) -> str:
    """Builds a structural header for a chunk, naming the definition it begins with."""
    for definition in definitions:
        if definition.start_line == start_line:
            return f"{definition.kind} `{definition.name}` (lines {definition.start_line}-{definition.end_line})"
    return f"module-level code (lines {start_line}-{end_line})"


def _estimate_tokens(text: str, chars_per_token: int) -> int:
    """Rough token estimate for prompt-budget purposes."""
    return max(1, len(text) // chars_per_token)
