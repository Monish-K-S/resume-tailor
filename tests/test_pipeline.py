from __future__ import annotations

from pathlib import Path

import pytest

from tailorlib.errors import CompileError, PageLimitError, ValidationError
from tailorlib.models import CompileResult, TailorRequest
from tailorlib.pipeline import estimate_cut_lines, run


class ScriptedLLM:
    def __init__(self, bodies: list[str]) -> None:
        self.bodies = list(bodies)
        self.calls: list[list] = []

    def complete(self, *, system, messages, schema, temperature=0.2, max_tokens=4096):
        self.calls.append(list(messages))
        if not self.bodies:
            raise AssertionError("unexpected extra LLM call")
        return {"body": self.bodies.pop(0)}


class FakeCompiler:
    def __init__(self, results: list[CompileResult]) -> None:
        self.results = list(results)
        self.calls = 0

    def __call__(self, full_tex, out_dir, *, base_dir=None, timeout=60):
        self.calls += 1
        outcome = self.results.pop(0)
        if outcome.error is None:
            pdf = Path(out_dir) / "resume.pdf"
            pdf.write_bytes(b"%PDF-1.4\nfake\n")
            outcome.pdf_path = pdf
        return outcome


def make_request(tmp_path: Path, base_doc, **overrides) -> TailorRequest:
    values = dict(
        company="acme",
        jd="We are hiring a Python backend engineer.",
        base=base_doc,
        profile={"skills": ["Python"]},
        prompt="SYSTEM PROMPT",
        out_dir=tmp_path / "out",
        base_dir=tmp_path,
    )
    values.update(overrides)
    return TailorRequest(**values)


def test_success_first_call(tmp_path, base_doc):
    llm = ScriptedLLM([base_doc.body])
    compiler = FakeCompiler([CompileResult(pages=1)])

    result = run(make_request(tmp_path, base_doc), llm, compiler=compiler)

    assert result.calls == 1
    assert compiler.calls == 1
    assert result.pages == 1
    assert result.pdf_path.exists()
    assert result.tex_path.read_text(encoding="utf-8") == base_doc.full
    assert not (tmp_path / "out" / ".work").exists()


def test_compile_error_retries_once(tmp_path, base_doc):
    llm = ScriptedLLM([base_doc.body, base_doc.body])
    compiler = FakeCompiler(
        [
            CompileResult(error="! Undefined control sequence."),
            CompileResult(pages=1),
        ]
    )

    result = run(make_request(tmp_path, base_doc), llm, compiler=compiler)

    assert result.calls == 2
    assert compiler.calls == 2
    follow_up = llm.calls[1][-1].content
    assert "Undefined control sequence" in follow_up
    assert "does not compile" in follow_up


def test_page_overflow_retries_with_cut_instruction(tmp_path, base_doc):
    llm = ScriptedLLM([base_doc.body, base_doc.body])
    compiler = FakeCompiler(
        [
            CompileResult(pages=2, overflow_text="alpha\nbeta"),
            CompileResult(pages=1),
        ]
    )

    result = run(make_request(tmp_path, base_doc), llm, compiler=compiler)

    assert result.calls == 2
    follow_up = llm.calls[1][-1].content
    assert "Remove at least 5 lines" in follow_up
    assert "alpha" in follow_up
    assert result.pages == 1


def test_page_overflow_twice_fails_without_third_call(tmp_path, base_doc):
    llm = ScriptedLLM([base_doc.body, base_doc.body])
    compiler = FakeCompiler(
        [
            CompileResult(pages=2, overflow_text="alpha"),
            CompileResult(pages=2, overflow_text="alpha"),
        ]
    )

    with pytest.raises(PageLimitError, match="still 2 pages"):
        run(make_request(tmp_path, base_doc), llm, compiler=compiler)

    assert len(llm.calls) == 2


def test_compile_then_page_then_success_is_three_calls(tmp_path, base_doc):
    llm = ScriptedLLM([base_doc.body, base_doc.body, base_doc.body])
    compiler = FakeCompiler(
        [
            CompileResult(error="! Missing $ inserted."),
            CompileResult(pages=2, overflow_text="spill"),
            CompileResult(pages=1),
        ]
    )

    result = run(make_request(tmp_path, base_doc), llm, compiler=compiler)

    assert result.calls == 3
    assert compiler.calls == 3
    assert result.pages == 1


def test_compile_error_twice_fails(tmp_path, base_doc):
    llm = ScriptedLLM([base_doc.body, base_doc.body])
    compiler = FakeCompiler(
        [
            CompileResult(error="! Undefined control sequence."),
            CompileResult(error="! Undefined control sequence."),
        ]
    )

    with pytest.raises(CompileError):
        run(make_request(tmp_path, base_doc), llm, compiler=compiler)

    assert len(llm.calls) == 2


def test_validation_failure_never_compiles(tmp_path, base_doc):
    bad = base_doc.body.replace(
        "Dummy summary used to verify the split/join and compile pipeline.",
        r"Cut cost by 999\%.",
    )
    llm = ScriptedLLM([bad])
    compiler = FakeCompiler([])

    with pytest.raises(ValidationError) as info:
        run(make_request(tmp_path, base_doc), llm, compiler=compiler)

    assert compiler.calls == 0
    assert any("999%" in line for line in info.value.violations)
    assert (tmp_path / "out" / "resume.rejected.tex").exists()


def test_failure_keeps_previous_pdf(tmp_path, base_doc):
    out = tmp_path / "out"
    out.mkdir()
    (out / "resume.pdf").write_bytes(b"previous-good-pdf")

    bad = base_doc.body.replace(
        "Dummy summary used to verify the split/join and compile pipeline.",
        r"Cut cost by 999\%.",
    )
    llm = ScriptedLLM([bad])

    with pytest.raises(ValidationError):
        run(make_request(tmp_path, base_doc), llm, compiler=FakeCompiler([]))

    assert (out / "resume.pdf").read_bytes() == b"previous-good-pdf"


def test_estimate_cut_lines():
    assert estimate_cut_lines("") == 15
    assert estimate_cut_lines("one\ntwo") == 5
    assert estimate_cut_lines("\n".join(["x"] * 10)) == 17
