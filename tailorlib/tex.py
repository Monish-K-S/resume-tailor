"""Split, join, normalise and structurally inspect LaTeX documents.

Everything here is pure text handling: no I/O, no subprocesses.
"""

from __future__ import annotations

import re

from .errors import TexError
from .models import Severity, TexDoc, Violation

DOC_BEGIN = r"\begin{document}"
DOC_END = r"\end{document}"

_COMMAND_RE = re.compile(r"\\([A-Za-z@]+)")
_SECTION_RE = re.compile(r"\\section\*?\s*\{")
_ENV_RE = re.compile(r"\\(begin|end)\s*\{([^{}]*)\}")
_FENCE_HEAD_RE = re.compile(r"^```[A-Za-z]*\s*")
_FENCE_TAIL_RE = re.compile(r"\s*```$")


# --------------------------------------------------------------------------- #
# split / join
# --------------------------------------------------------------------------- #


def split_tex(text: str) -> TexDoc:
    """Split at the single ``\\begin{document}``; body keeps the trailing bytes."""
    first = text.find(DOC_BEGIN)
    if first == -1:
        raise TexError(f"resume is missing {DOC_BEGIN}")
    if text.find(DOC_BEGIN, first + len(DOC_BEGIN)) != -1:
        raise TexError(f"resume contains more than one {DOC_BEGIN}")

    end = text.find(DOC_END, first + len(DOC_BEGIN))
    if end == -1:
        raise TexError(f"resume is missing {DOC_END}")
    if text.find(DOC_END, end + len(DOC_END)) != -1:
        raise TexError(f"resume contains more than one {DOC_END}")

    return TexDoc(preamble=text[:first], body=text[first:])


def join_tex(doc: TexDoc) -> str:
    """Re-attach the frozen preamble. Byte-for-byte, by construction."""
    return doc.preamble + doc.body


def normalize_llm_body(raw: str) -> str:
    """Turn whatever the model returned into a body we can safely join.

    Accepts fenced output and inner-only bodies; rejects anything that tries to
    smuggle in preamble content or commentary after ``\\end{document}``.
    """
    text = raw.strip()
    if text.startswith("```"):
        text = _FENCE_HEAD_RE.sub("", text, count=1)
    if text.endswith("```"):
        text = _FENCE_TAIL_RE.sub("", text, count=1)
    text = text.strip()

    clean = strip_comments(text)
    for forbidden in (r"\documentclass", r"\usepackage"):
        if forbidden in clean:
            raise TexError(
                f"model returned preamble content ({forbidden}); the preamble is frozen"
            )

    if text.count(DOC_BEGIN) > 1:
        raise TexError("model returned more than one \\begin{document}")
    if text.count(DOC_END) > 1:
        raise TexError("model returned more than one \\end{document}")

    end = text.rfind(DOC_END)
    begin = text.find(DOC_BEGIN)

    if end == -1:
        if begin != -1:
            raise TexError("model output has \\begin{document} but no \\end{document}")
        # Inner body only: wrap it in the required markers.
        text = f"{DOC_BEGIN}\n{text.strip()}\n{DOC_END}"
        begin, end = 0, text.rfind(DOC_END)
    elif begin == -1:
        inner = text[:end].strip()
        text = f"{DOC_BEGIN}\n{inner}\n{DOC_END}"
        begin, end = 0, text.rfind(DOC_END)
    elif begin > end:
        raise TexError("model output has \\begin{document} after \\end{document}")

    trailing = text[end + len(DOC_END) :]
    if trailing.strip():
        raise TexError("model output has content after \\end{document}")

    return text[begin : end + len(DOC_END)] + "\n"


# --------------------------------------------------------------------------- #
# text inspection
# --------------------------------------------------------------------------- #


def strip_comments(text: str) -> str:
    """Remove ``%`` comments, keeping escaped ``\\%`` and newlines."""
    out: list[str] = []
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        if ch == "\\" and i + 1 < n:
            out.append(text[i : i + 2])
            i += 2
            continue
        if ch == "%":
            newline = text.find("\n", i)
            if newline == -1:
                break
            i = newline
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def scan_commands(text: str) -> list[tuple[str, int]]:
    """Return ``(command_name, line_number)`` for every backslash command."""
    clean = strip_comments(text)
    return [(m.group(1), _line_of(clean, m.start())) for m in _COMMAND_RE.finditer(clean)]


def _line_of(text: str, index: int) -> int:
    return text.count("\n", 0, index) + 1


def _read_group(text: str, open_index: int) -> tuple[str, int]:
    """Read a balanced ``{...}`` group starting at ``open_index``."""
    depth = 0
    i = open_index
    while i < len(text):
        ch = text[i]
        if ch == "\\":
            i += 2
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[open_index + 1 : i], i + 1
        i += 1
    raise TexError("unbalanced braces while reading a LaTeX group")


def extract_sections(text: str) -> list[str]:
    """Section titles in document order, whitespace-normalised."""
    clean = strip_comments(text)
    titles: list[str] = []
    for match in _SECTION_RE.finditer(clean):
        content, _ = _read_group(clean, match.end() - 1)
        titles.append(re.sub(r"\s+", " ", content).strip())
    return titles


def check_balanced(text: str) -> list[Violation]:
    """Check brace balance and ``\\begin``/``\\end`` pairing."""
    clean = strip_comments(text)
    issues: list[Violation] = []

    depth = 0
    i = 0
    while i < len(clean):
        ch = clean[i]
        if ch == "\\":
            j = i + 1
            if j < len(clean) and (clean[j].isalpha() or clean[j] == "@"):
                while j < len(clean) and (clean[j].isalpha() or clean[j] == "@"):
                    j += 1
                i = j
                continue
            # control symbol: skip the escaped character (\% \{ \} \\ etc.)
            i = min(j + 1, len(clean))
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth < 0:
                issues.append(
                    Violation(
                        "brace",
                        f"unmatched '}}' on line {_line_of(clean, i)}",
                    )
                )
                depth = 0
        i += 1
    if depth:
        issues.append(Violation("brace", f"{depth} unclosed '{{' at end of body"))

    stack: list[tuple[str, int]] = []
    for match in _ENV_RE.finditer(clean):
        kind, name = match.group(1), match.group(2).strip()
        line = _line_of(clean, match.start())
        if kind == "begin":
            stack.append((name, line))
            continue
        if not stack:
            issues.append(
                Violation("env", f"\\end{{{name}}} on line {line} has no matching \\begin")
            )
        elif stack[-1][0] != name:
            open_name, open_line = stack.pop()
            issues.append(
                Violation(
                    "env",
                    f"\\end{{{name}}} on line {line} closes \\begin{{{open_name}}} "
                    f"from line {open_line}",
                )
            )
        else:
            stack.pop()
    for name, line in stack:
        issues.append(
            Violation("env", f"\\begin{{{name}}} on line {line} is never closed")
        )

    return issues
