from __future__ import annotations

import json
import os
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


def _check_args():
    return type("Args", (), {"provider": None, "model": None})()


def _stub_tools(monkeypatch):
    monkeypatch.setattr(tailor, "find_pdflatex", lambda: "/usr/bin/pdflatex")
    monkeypatch.setattr(tailor.shutil, "which", lambda name: f"/usr/bin/{name}")


def test_check_mode_makes_a_live_provider_call(project, monkeypatch, capsys):
    _stub_tools(monkeypatch)

    class FakeClient:
        model = "gemini-3.8-flash"

        def ping(self):
            return None

    monkeypatch.setattr(tailor, "build_client", lambda provider, model: FakeClient())

    assert tailor._check(_check_args()) == 0

    out = capsys.readouterr().out
    assert "gemini-3.8-flash (live)" in out


def test_check_mode_reports_live_provider_failure(project, monkeypatch, capsys):
    _stub_tools(monkeypatch)

    class FakeClient:
        model = "gemini-3.8-flash"

        def ping(self):
            raise RuntimeError("503 UNAVAILABLE: high demand")

    monkeypatch.setattr(tailor, "build_client", lambda provider, model: FakeClient())

    assert tailor._check(_check_args()) == 2

    out = capsys.readouterr().out
    assert "provider" in out
    assert "503 UNAVAILABLE" in out
    assert "transient provider error" in out


def test_parse_dotenv_handles_real_world_syntax(tmp_path, monkeypatch):
    for name in (
        "EXPORTED",
        "PLAIN",
        "QUOTED",
        "SINGLE",
        "INLINE",
        "HASH_URL",
        "EMPTY",
        "COMMENTED",
    ):
        monkeypatch.delenv(name, raising=False)

    path = tmp_path / ".env"
    path.write_text(
        "\n".join(
            [
                "# a comment",
                "export EXPORTED=one",
                "PLAIN=two",
                'QUOTED="three four"',
                "SINGLE='five six'",
                "INLINE=seven # trailing comment",
                "HASH_URL=https://example.com/#frag",
                "EMPTY=",
                "# COMMENTED=ignored",
                "NOT A KEY=ignored",
            ]
        ),
        encoding="utf-8",
    )

    tailor._parse_dotenv(path)

    assert os.environ["EXPORTED"] == "one"
    assert os.environ["PLAIN"] == "two"
    assert os.environ["QUOTED"] == "three four"
    assert os.environ["SINGLE"] == "five six"
    assert os.environ["INLINE"] == "seven"
    assert os.environ["HASH_URL"] == "https://example.com/#frag"
    assert os.environ["EMPTY"] == ""
    assert "COMMENTED" not in os.environ
    assert "NOT A KEY" not in os.environ


def test_parse_dotenv_does_not_override_existing_values(tmp_path, monkeypatch):
    monkeypatch.setenv("ALREADY_SET", "from-shell")

    path = tmp_path / ".env"
    path.write_text("ALREADY_SET=from-file\n", encoding="utf-8")
    tailor._parse_dotenv(path)

    assert os.environ["ALREADY_SET"] == "from-shell"


def _make_venv(root: Path) -> Path:
    binary = root / ".venv" / "bin"
    binary.mkdir(parents=True)
    python = binary / "python"
    python.write_text("#!/bin/sh\n", encoding="utf-8")
    python.chmod(0o755)
    return python


def test_reexec_switches_to_the_project_venv(tmp_path, monkeypatch):
    python = _make_venv(tmp_path)
    monkeypatch.setattr(tailor, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(tailor.sys, "prefix", str(tmp_path / "system-python"))
    monkeypatch.delenv("RESUME_TAILOR_NO_VENV", raising=False)

    calls: list[tuple[str, list[str]]] = []
    monkeypatch.setattr(tailor.os, "execv", lambda path, args: calls.append((path, args)))

    tailor._use_project_venv(None)

    assert calls
    assert calls[0][0] == str(python)
    assert calls[0][1][0] == str(python)


def test_reexec_is_skipped_inside_the_venv(tmp_path, monkeypatch):
    _make_venv(tmp_path)
    monkeypatch.setattr(tailor, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(tailor.sys, "prefix", str(tmp_path / ".venv"))
    monkeypatch.delenv("RESUME_TAILOR_NO_VENV", raising=False)

    calls: list[tuple[str, list[str]]] = []
    monkeypatch.setattr(tailor.os, "execv", lambda path, args: calls.append((path, args)))

    tailor._use_project_venv(None)

    assert calls == []


def test_reexec_can_be_disabled(tmp_path, monkeypatch):
    _make_venv(tmp_path)
    monkeypatch.setattr(tailor, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(tailor.sys, "prefix", str(tmp_path / "system-python"))
    monkeypatch.setenv("RESUME_TAILOR_NO_VENV", "1")

    calls: list[tuple[str, list[str]]] = []
    monkeypatch.setattr(tailor.os, "execv", lambda path, args: calls.append((path, args)))

    tailor._use_project_venv(None)

    assert calls == []


def test_reexec_is_skipped_for_programmatic_calls(tmp_path, monkeypatch):
    _make_venv(tmp_path)
    monkeypatch.setattr(tailor, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(tailor.sys, "prefix", str(tmp_path / "system-python"))
    monkeypatch.delenv("RESUME_TAILOR_NO_VENV", raising=False)

    calls: list[tuple[str, list[str]]] = []
    monkeypatch.setattr(tailor.os, "execv", lambda path, args: calls.append((path, args)))

    tailor._use_project_venv(["--check"])

    assert calls == []


def test_reexec_is_skipped_without_a_venv(tmp_path, monkeypatch):
    monkeypatch.setattr(tailor, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(tailor.sys, "prefix", str(tmp_path / "system-python"))
    monkeypatch.delenv("RESUME_TAILOR_NO_VENV", raising=False)

    calls: list[tuple[str, list[str]]] = []
    monkeypatch.setattr(tailor.os, "execv", lambda path, args: calls.append((path, args)))

    tailor._use_project_venv(None)

    assert calls == []
