from __future__ import annotations

import json
from pathlib import Path

import pytest

import tailor
from tailorlib.models import Severity, TailorResult, Violation


@pytest.fixture
def project(tmp_path, monkeypatch):
    """A throwaway project root with the three input files."""
    (tmp_path / "base").mkdir()
    (tmp_path / "base" / "resume.tex").write_text(
        "\\documentclass{article}\n"
        "\\begin{document}\n"
        "\\section{Summary}\nOld summary.\n"
        "\\end{document}\n",
        encoding="utf-8",
    )
    (tmp_path / "profile.json").write_text(
        json.dumps({"skills": ["Python"]}), encoding="utf-8"
    )
    (tmp_path / "prompt.md").write_text("PROMPT", encoding="utf-8")

    monkeypatch.setattr(tailor, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(tailor, "BASE_PATH", tmp_path / "base" / "resume.tex")
    monkeypatch.setattr(tailor, "PROFILE_PATH", tmp_path / "profile.json")
    monkeypatch.setattr(tailor, "PROMPT_PATH", tmp_path / "prompt.md")
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _fake_run(request, client):
    out_dir = Path(request.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    pdf = out_dir / "resume.pdf"
    pdf.write_bytes(b"%PDF-1.4\n")
    tex = out_dir / "resume.tex"
    body = request.base.body.replace("Old summary.", "New summary with Python.")
    tex.write_text(request.base.preamble + body, encoding="utf-8")
    return TailorResult(
        doc=type(request.base)(preamble=request.base.preamble, body=body),
        pdf_path=pdf,
        tex_path=tex,
        pages=1,
        violations=[Violation("term", "unknown", term="Terraform", severity=Severity.WARN)],
        calls=1,
        elapsed=1.25,
        out_dir=out_dir,
    )


def test_cli_writes_outputs_and_reports(project, monkeypatch, capsys):
    jd_file = project / "jd.txt"
    jd_file.write_text("Python backend engineer with PostgreSQL.", encoding="utf-8")
    monkeypatch.setattr(tailor, "run", _fake_run)
    monkeypatch.setattr(tailor, "build_client", lambda provider, model: object())

    code = tailor.main(
        ["--company", "Acme Corp", "--jd-file", str(jd_file), "--no-color"]
    )

    out = capsys.readouterr().out
    assert code == 0
    assert "Tailored resume for Acme Corp" in out
    assert "1 page" in out
    assert "1 API call" in out
    assert "Terraform" in out

    from datetime import date

    out_dir = project / "resumes" / f"acme-corp_{date.today().isoformat()}"
    assert (out_dir / "resume.pdf").exists()
    assert (out_dir / "resume.tex").exists()
    diff = (out_dir / "diff.txt").read_text(encoding="utf-8")
    assert "-Old summary." in diff
    assert "+New summary with Python." in diff


def test_cli_verbose_prints_diff(project, monkeypatch, capsys):
    jd_file = project / "jd.txt"
    jd_file.write_text("Python engineer.", encoding="utf-8")
    monkeypatch.setattr(tailor, "run", _fake_run)
    monkeypatch.setattr(tailor, "build_client", lambda provider, model: object())

    assert tailor.main(
        ["--company", "Acme", "--jd-file", str(jd_file), "--no-color", "--verbose"]
    ) == 0

    out = capsys.readouterr().out
    assert "--- base/resume.tex" in out
    assert "+++ tailored/resume.tex" in out


def test_cli_requires_company(project, capsys):
    with pytest.raises(SystemExit) as info:
        tailor.main(["--stdin"])
    assert info.value.code == 2
    assert "--company is required" in capsys.readouterr().err


def test_cli_missing_jd_is_input_error(project, monkeypatch, capsys):
    monkeypatch.setattr(tailor.sys, "stdin", type("S", (), {"isatty": lambda self: False, "read": lambda self: "   "})())
    code = tailor.main(["--company", "Acme"])
    assert code == 2
    assert "no job description" in capsys.readouterr().err


def test_cli_reports_validation_error_without_traceback(project, monkeypatch, capsys):
    from tailorlib.errors import ValidationError

    jd_file = project / "jd.txt"
    jd_file.write_text("Python engineer.", encoding="utf-8")

    def explode(request, client):
        raise ValidationError("invented number", ["[fatal] number: 999%"])

    monkeypatch.setattr(tailor, "run", explode)
    monkeypatch.setattr(tailor, "build_client", lambda provider, model: object())

    code = tailor.main(["--company", "Acme", "--jd-file", str(jd_file)])

    err = capsys.readouterr().err
    assert code == 3
    assert "invented number" in err
    assert "999%" in err
    assert "Traceback" not in err


def test_cli_unexpected_error_hidden_without_verbose(project, monkeypatch, capsys):
    jd_file = project / "jd.txt"
    jd_file.write_text("Python engineer.", encoding="utf-8")

    def explode(request, client):
        raise RuntimeError("boom")

    monkeypatch.setattr(tailor, "run", explode)
    monkeypatch.setattr(tailor, "build_client", lambda provider, model: object())

    code = tailor.main(["--company", "Acme", "--jd-file", str(jd_file)])

    err = capsys.readouterr().err
    assert code == 1
    assert "unexpected failure: boom" in err
    assert "Traceback" not in err


def test_check_mode_reports_missing_provider_key(project, monkeypatch, capsys):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.setenv("RESUME_TAILOR_PROVIDER", "gemini")

    code = tailor._check(
        type(
            "Args",
            (),
            {"provider": None, "model": None},
        )()
    )

    out = capsys.readouterr().out
    assert code == 2
    assert "provider" in out
    assert "GEMINI_API_KEY" in out
