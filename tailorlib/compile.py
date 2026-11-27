"""Run pdflatex, read its log, and count pages. All subprocess work lives here."""

from __future__ import annotations

import glob
import os
import re
import shutil
import subprocess
from pathlib import Path

from .errors import CompileError
from .models import CompileResult

PDFLATEX = "pdflatex"

# macOS installers put TeX here but GUI-launched shells often miss the PATH entry.
_TEXBIN_GLOBS = (
    "/Library/TeX/texbin",
    "/usr/local/texlive/*/bin/*",
    "/opt/homebrew/bin",
    "/usr/local/bin",
)

AUX_SUFFIXES = (
    ".aux",
    ".log",
    ".out",
    ".toc",
    ".fls",
    ".fdb_latexmk",
    ".synctex.gz",
    ".nav",
    ".snm",
    ".vrb",
)

_RERUN_MARKERS = (
    "rerun to get",
    "label(s) may have changed",
    "there were undefined references",
    "please rerun",
    "rerun latex",
)


def find_pdflatex() -> str | None:
    """Locate pdflatex on PATH or in the usual macOS TeX Live locations."""
    found = shutil.which(PDFLATEX)
    if found:
        return found
    for pattern in _TEXBIN_GLOBS:
        for directory in glob.glob(pattern):
            candidate = Path(directory) / PDFLATEX
            if candidate.is_file() and os.access(candidate, os.X_OK):
                return str(candidate)
    return None


def pdflatex_available() -> bool:
    return find_pdflatex() is not None


def compile_document(
    full_tex: str,
    out_dir: Path,
    *,
    base_dir: Path | None = None,
    timeout: int = 60,
) -> CompileResult:
    """Compile ``full_tex`` in ``out_dir``.

    ``base_dir`` is the working directory for pdflatex, so relative assets
    referenced by the frozen preamble resolve exactly as they do when the
    user compiles by hand. Output is redirected to ``out_dir``.
    """
    out_dir = Path(out_dir).resolve()
    base_dir = Path(base_dir or out_dir).resolve()

    pdflatex = find_pdflatex()
    if pdflatex is None:
        raise CompileError(
            "pdflatex not found. Install BasicTeX or MacTeX, then re-run."
        )

    out_dir.mkdir(parents=True, exist_ok=True)
    tex_path = out_dir / "resume.tex"
    tex_path.write_text(full_tex, encoding="utf-8", newline="\n")

    pdf_path = out_dir / "resume.pdf"
    log_path = out_dir / "resume.log"
    cmd = [
        pdflatex,
        "-interaction=nonstopmode",
        "-halt-on-error",
        "-file-line-error",
        "-no-shell-escape",
        f"-output-directory={out_dir}",
        str(tex_path),
    ]

    runs = 0
    log_text = ""
    for run in (1, 2):
        runs = run
        proc = _run(cmd, base_dir, timeout)
        log_text = (
            log_path.read_text(encoding="utf-8", errors="replace")
            if log_path.exists()
            else (proc.stdout or "")
        )

        if proc.returncode != 0:
            return CompileResult(
                error=first_error(log_text) or _tail(proc),
                log_path=log_path,
                runs=runs,
            )

        error = first_error(log_text)
        if error is not None:
            return CompileResult(error=error, log_path=log_path, runs=runs)

        if run == 1 and needs_rerun(log_text):
            continue
        break

    pages = page_count(pdf_path, log_text)
    if pages is None:
        return CompileResult(
            error="compiled, but could not determine the page count "
            "(pdfinfo missing and no page count in the log)",
            log_path=log_path,
            runs=runs,
        )

    overflow = overflow_text(pdf_path, pages) if pages > 1 else ""
    return CompileResult(
        pdf_path=pdf_path,
        pages=pages,
        overflow_text=overflow,
        log_path=log_path,
        runs=runs,
    )


def _run(cmd: list[str], cwd: Path, timeout: int) -> subprocess.CompletedProcess[str]:
    # Wide log lines stop pdflatex from wrapping error messages mid-word.
    env = {
        **os.environ,
        "max_print_line": "10000",
        "error_line": "254",
        "half_error_line": "238",
    }
    try:
        return subprocess.run(
            cmd,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            errors="replace",
            timeout=timeout,
            env=env,
        )
    except subprocess.TimeoutExpired as exc:
        raise CompileError(f"pdflatex timed out after {timeout}s") from exc
    except FileNotFoundError as exc:
        raise CompileError("pdflatex not found. Install BasicTeX or MacTeX.") from exc


def _tail(proc: subprocess.CompletedProcess[str]) -> str:
    text = (proc.stdout or "") + "\n" + (proc.stderr or "")
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return " | ".join(lines[-3:]) or f"pdflatex exited with code {proc.returncode}"


def first_error(log: str) -> str | None:
    """The first ``!`` error plus its context, or the first ``file:line:`` error."""
    lines = log.splitlines()
    for index, line in enumerate(lines):
        if line.startswith("!"):
            detail = [line.strip()]
            for follow in lines[index + 1 : index + 4]:
                stripped = follow.strip()
                if not stripped:
                    break
                detail.append(stripped)
                if stripped.startswith("l."):
                    break
            return " | ".join(detail)

    for line in lines:
        if re.match(r"^[^:]+:\d+: ", line.strip()):
            return line.strip()
    return None


def needs_rerun(log: str) -> bool:
    lowered = log.lower()
    return any(marker in lowered for marker in _RERUN_MARKERS)


def page_count(pdf_path: Path, log: str = "") -> int | None:
    """Prefer pdfinfo; fall back to pdflatex's ``Output written on ... (N pages)``."""
    if pdf_path.exists() and shutil.which("pdfinfo"):
        try:
            proc = subprocess.run(
                ["pdfinfo", str(pdf_path)],
                capture_output=True,
                text=True,
                errors="replace",
                timeout=20,
            )
            match = re.search(r"^Pages:\s+(\d+)", proc.stdout, re.MULTILINE)
            if match:
                return int(match.group(1))
        except (OSError, subprocess.TimeoutExpired):
            pass

    match = re.search(r"Output written on .*?\((\d+) pages?", log)
    return int(match.group(1)) if match else None


def overflow_text(pdf_path: Path, pages: int, *, timeout: int = 20) -> str:
    """Text of pages 2..N, used to tell the model exactly what spilled over."""
    if not shutil.which("pdftotext"):
        return ""
    try:
        proc = subprocess.run(
            [
                "pdftotext",
                "-f",
                "2",
                "-l",
                str(pages),
                "-layout",
                str(pdf_path),
                "-",
            ],
            capture_output=True,
            text=True,
            errors="replace",
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return proc.stdout if proc.returncode == 0 else ""


def count_text_lines(text: str) -> int:
    return sum(1 for line in text.splitlines() if line.strip())


def cleanup_aux(out_dir: Path) -> list[Path]:
    """Delete intermediate LaTeX files, keeping .tex, .pdf and diff.txt."""
    removed: list[Path] = []
    for suffix in AUX_SUFFIXES:
        for path in out_dir.glob(f"*{suffix}"):
            try:
                path.unlink()
                removed.append(path)
            except OSError:
                pass
    return removed
