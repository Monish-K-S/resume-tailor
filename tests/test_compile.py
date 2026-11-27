from __future__ import annotations

from pathlib import Path

import pytest

from tailorlib.compile import cleanup_aux, compile_document, pdflatex_available
from tailorlib.tex import join_tex, split_tex

FIXTURE = Path(__file__).parent / "fixtures" / "minimal.tex"

pytestmark = pytest.mark.skipif(
    not pdflatex_available(), reason="pdflatex is not installed"
)


def test_compile_dummy_body(tmp_path: Path):
    doc = split_tex(FIXTURE.read_text(encoding="utf-8"))
    result = compile_document(join_tex(doc), tmp_path, base_dir=tmp_path)

    assert result.error is None, result.error
    assert result.pdf_path is not None and result.pdf_path.exists()
    assert result.pages == 1
    assert 1 <= result.runs <= 2
    assert result.overflow_text == ""

    cleanup_aux(tmp_path)
    assert (tmp_path / "resume.tex").exists()
    assert (tmp_path / "resume.pdf").exists()
    assert not (tmp_path / "resume.log").exists()
    assert not (tmp_path / "resume.aux").exists()


def test_compile_reports_latex_error(tmp_path: Path):
    bad = (
        "\\documentclass{article}\n"
        "\\begin{document}\n"
        "\\thisCommandDoesNotExist\n"
        "\\end{document}\n"
    )
    result = compile_document(bad, tmp_path, base_dir=tmp_path)

    assert not result.ok
    assert result.error is not None
    assert "thisCommandDoesNotExist" in result.error or "Undefined control sequence" in result.error
