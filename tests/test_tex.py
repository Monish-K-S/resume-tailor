from __future__ import annotations

from pathlib import Path

import pytest

from tailorlib.errors import TexError
from tailorlib.tex import (
    DOC_BEGIN,
    DOC_END,
    check_balanced,
    extract_sections,
    join_tex,
    normalize_llm_body,
    split_tex,
    strip_comments,
)

FIXTURE = Path(__file__).parent / "fixtures" / "minimal.tex"


def test_split_join_roundtrip_is_byte_identical():
    text = FIXTURE.read_text(encoding="utf-8")
    doc = split_tex(text)
    assert doc.preamble + doc.body == text
    assert join_tex(doc) == text
    assert doc.preamble.startswith("\\documentclass")
    assert doc.body.startswith(DOC_BEGIN)
    assert doc.body.rstrip().endswith(DOC_END)


def test_split_requires_begin_and_end():
    with pytest.raises(TexError, match="begin"):
        split_tex("\\documentclass{article}\n")
    with pytest.raises(TexError, match="end"):
        split_tex("\\begin{document}\nhi\n")


def test_split_rejects_duplicate_markers():
    with pytest.raises(TexError, match="more than one"):
        split_tex("\\begin{document}a\\begin{document}b\\end{document}")


def test_normalize_strips_fences_and_wraps_inner_body():
    raw = "```latex\n\\section{Professional Summary}\nHi.\n```"
    body = normalize_llm_body(raw)
    assert body.startswith(DOC_BEGIN)
    assert body.rstrip().endswith(DOC_END)
    assert "```" not in body


def test_normalize_rejects_preamble_content():
    with pytest.raises(TexError, match="preamble"):
        normalize_llm_body(
            "\\documentclass{article}\n\\begin{document}x\\end{document}"
        )
    with pytest.raises(TexError, match="preamble"):
        normalize_llm_body(
            "\\usepackage{geometry}\n\\begin{document}x\\end{document}"
        )


def test_normalize_rejects_trailing_commentary():
    with pytest.raises(TexError, match="after"):
        normalize_llm_body("\\begin{document}x\\end{document}\nHere is what I changed.")


def test_strip_comments_keeps_escaped_percent():
    assert strip_comments("50\\% done % drop me\nnext") == "50\\% done \nnext"


def test_balanced_braces():
    assert check_balanced("\\textbf{ok} {\\it fine}") == []
    assert check_balanced("\\textbf{broken")
    assert check_balanced("a } b")


def test_escaped_braces_are_not_groups():
    assert check_balanced(r"\textbf{\{literal\}}") == []


def test_begin_end_pairs():
    assert check_balanced("\\begin{itemize}\\item x\\end{itemize}") == []
    assert check_balanced("\\begin{itemize}\\item x\\end{enumerate}")


def test_sections_extracted_in_order():
    titles = extract_sections(FIXTURE.read_text(encoding="utf-8"))
    assert titles == [
        "Professional Summary",
        "Projects",
        "Education",
        "Achievements",
    ]
