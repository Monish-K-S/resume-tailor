#!/usr/bin/env python3
"""resume-tailor: tailor a LaTeX resume to a job description and compile a PDF."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
from datetime import date
from pathlib import Path

from tailorlib.compile import find_pdflatex
from tailorlib.errors import ConfigError, InputError, TailorError
from tailorlib.llm import build_client
from tailorlib.models import Severity, TailorRequest
from tailorlib.pipeline import run
from tailorlib.report import diff_stats, keyword_report, render_diff
from tailorlib.tex import extract_sections, split_tex

PROJECT_ROOT = Path(__file__).resolve().parent
BASE_PATH = PROJECT_ROOT / "base" / "resume.tex"
PROFILE_PATH = PROJECT_ROOT / "profile.json"
PROMPT_PATH = PROJECT_ROOT / "prompt.md"
MAX_JD_CHARS = 60_000


def _parse_dotenv(path: Path) -> None:
    """Minimal stdlib .env parser, used when python-dotenv is unavailable."""
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return

    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        if "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
            continue

        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            quote = value[0]
            value = value[1:-1]
            if quote == '"':
                value = value.replace("\\n", "\n").replace('\\"', '"')
        else:
            comment = value.find(" #")
            if comment != -1:
                value = value[:comment].rstrip()

        os.environ.setdefault(key, value)


def _load_env() -> None:
    path = PROJECT_ROOT / ".env"
    try:
        from dotenv import load_dotenv
    except ImportError:
        if path.exists():
            _parse_dotenv(path)
        return
    load_dotenv(path)


def _use_project_venv(argv: list[str] | None, *, verbose: bool = False) -> None:
    """Re-exec with .venv/bin/python so shell aliases and shims cannot bypass it.

    A common macOS setup aliases ``python`` to a system interpreter, which
    shadows the activated venv. Re-execing keeps ``python tailor.py`` working
    and guarantees the project's dependencies are the ones in use.
    """
    if argv is not None or os.environ.get("RESUME_TAILOR_NO_VENV") == "1":
        return

    venv_root = PROJECT_ROOT / ".venv"
    relative = Path("Scripts/python.exe") if os.name == "nt" else Path("bin/python")
    venv_python = venv_root / relative
    if not venv_python.exists():
        return

    try:
        if Path(sys.prefix).resolve() == venv_root.resolve():
            return
    except OSError:
        return

    if verbose:
        print(f"note: using the project venv interpreter ({venv_python})", file=sys.stderr)

    try:
        os.execv(str(venv_python), [str(venv_python), *sys.argv])
    except OSError:
        return


def _read_text(path: Path, label: str) -> str:
    if not path.exists():
        raise InputError(f"{label} not found: {path}")
    try:
        return path.read_text(encoding="utf-8")
    except OSError as exc:
        raise InputError(f"could not read {label} ({path}): {exc}") from exc


def _load_profile() -> dict:
    text = _read_text(PROFILE_PATH, "profile.json")
    try:
        profile = json.loads(text)
    except json.JSONDecodeError as exc:
        raise InputError(f"profile.json is not valid JSON: {exc}") from exc
    if not isinstance(profile, dict):
        raise InputError("profile.json must contain a JSON object")
    return profile


def _read_jd(args: argparse.Namespace) -> str:
    if args.jd_file is not None:
        text = _read_text(Path(args.jd_file), "job description file")
    elif args.clipboard:
        try:
            import pyperclip
        except ImportError as exc:
            raise InputError(
                "pyperclip is not installed; run: pip install pyperclip"
            ) from exc
        try:
            text = pyperclip.paste()
        except Exception as exc:
            raise InputError(f"could not read the clipboard: {exc}") from exc
    else:
        if sys.stdin.isatty() and not args.stdin:
            print(
                "Paste the job description.\n"
                "When finished: press Enter, then Ctrl-D "
                "(if nothing happens, press Ctrl-D again):",
                file=sys.stderr,
                flush=True,
            )
        text = sys.stdin.read()

    text = text.strip()
    if not text:
        raise InputError("no job description was provided")
    if len(text) > MAX_JD_CHARS:
        raise InputError(
            f"the job description is too long ({len(text)} characters; "
            f"limit {MAX_JD_CHARS}). Trim it or save it to a file."
        )
    return text


def _out_dir(company: str, root: Path) -> Path:
    slug = re.sub(r"[^a-z0-9]+", "-", company.casefold()).strip("-") or "company"
    root = root if root.is_absolute() else PROJECT_ROOT / root
    return root / f"{slug}_{date.today().isoformat()}"


def _paint(text: str, code: str, enabled: bool) -> str:
    return f"\033[{code}m{text}\033[0m" if enabled else text


def _print_report(
    args: argparse.Namespace,
    result,
    keywords,
    diff_text: str,
) -> None:
    color = sys.stdout.isatty() and not args.no_color
    warnings = [v for v in result.violations if v.severity is Severity.WARN]
    added, removed = diff_stats(diff_text)

    try:
        pdf_display = result.pdf_path.relative_to(Path.cwd())
    except ValueError:
        pdf_display = result.pdf_path

    diff_path = result.out_dir / "diff.txt"
    try:
        diff_display = diff_path.relative_to(Path.cwd())
    except ValueError:
        diff_display = diff_path

    pages = f"{result.pages} page" + ("" if result.pages == 1 else "s")
    calls = f"{result.calls} API call" + ("" if result.calls == 1 else "s")

    print()
    print(f"Tailored resume for {args.company}")
    print(f"  output    {pdf_display}  ({pages})")
    print(f"  elapsed   {result.elapsed:.1f}s  ({calls})")

    matched_preview = ", ".join(keywords.matched[:12])
    if len(keywords.matched) > 12:
        matched_preview += ", ..."
    print(
        "  matched   "
        + _paint(f"{len(keywords.matched)} keywords", "32", color)
        + (f": {matched_preview}" if matched_preview else "")
    )

    total_missing = len(keywords.missing)
    print(f"  missing   {_paint(str(total_missing) + ' keywords', '33', color)}")
    if keywords.missing_available:
        print(
            "            in profile but unused: "
            + ", ".join(keywords.missing_available)
        )
    if keywords.missing_unknown:
        print(
            "            not in profile:        "
            + ", ".join(keywords.missing_unknown)
        )

    if warnings:
        terms = ", ".join(v.term or v.code for v in warnings)
        print(f"  warnings  {len(warnings)} unverified term(s): {terms}")

    print(f"  diff      +{added} / -{removed} lines  (full diff: {diff_display})")

    if args.verbose and diff_text:
        print()
        print(diff_text)


def _check(args: argparse.Namespace) -> int:
    rows: list[tuple[str, bool, str]] = []

    for label, path in (
        ("base/resume.tex", BASE_PATH),
        ("profile.json", PROFILE_PATH),
        ("prompt.md", PROMPT_PATH),
    ):
        rows.append((label, path.exists(), str(path)))

    pdflatex = find_pdflatex()
    rows.append(("pdflatex", bool(pdflatex), pdflatex or "not found"))
    for tool in ("pdfinfo", "pdftotext"):
        found = shutil.which(tool)
        rows.append((tool, bool(found), found or "not found (optional)"))

    try:
        doc = split_tex(_read_text(BASE_PATH, "base resume"))
        sections = extract_sections(doc.body)
        rows.append(
            (
                "resume structure",
                bool(sections),
                f"{len(sections)} sections: {', '.join(sections)}",
            )
        )
    except TailorError as exc:
        rows.append(("resume structure", False, exc.message))

    try:
        profile = _load_profile()
        rows.append(("profile content", True, f"{len(profile)} top-level keys"))
    except TailorError as exc:
        rows.append(("profile content", False, exc.message))

    try:
        client = build_client(args.provider, args.model)
    except ConfigError as exc:
        rows.append(("provider", False, exc.message))
    else:
        try:
            client.ping()
        except Exception as exc:
            detail = " ".join(str(exc).split())[:240]
            hint = (
                " (transient provider error; try again)"
                if "503" in detail or "unavailable" in detail.casefold()
                else ""
            )
            rows.append(("provider", False, f"{client.model}: {detail}{hint}"))
        else:
            rows.append(
                (
                    "provider",
                    True,
                    f"{type(client).__name__} / {client.model} (live)",
                )
            )

    width = max(len(label) for label, _, _ in rows)
    for label, ok, detail in rows:
        mark = "ok" if ok else "FAIL"
        print(f"{label:<{width}}  {mark:<4}  {detail}")

    failed = [label for label, ok, _ in rows if not ok]
    if failed:
        sys.stdout.flush()
        print(f"\n{len(failed)} check(s) failed: {', '.join(failed)}", file=sys.stderr)
        return 2
    print("\nall checks passed")
    return 0


def _tailor(args: argparse.Namespace) -> int:
    base = split_tex(_read_text(BASE_PATH, "base resume"))
    profile = _load_profile()
    prompt = _read_text(PROMPT_PATH, "prompt.md")
    jd = _read_jd(args)
    client = build_client(args.provider, args.model)
    print(
        f"Generating a tailored resume for {args.company}... "
        "(usually 10-30 seconds)",
        file=sys.stderr,
        flush=True,
    )

    out_dir = _out_dir(args.company, args.out_root)
    request = TailorRequest(
        company=args.company,
        jd=jd,
        base=base,
        profile=profile,
        prompt=prompt,
        out_dir=out_dir,
        base_dir=BASE_PATH.parent,
        max_pages=args.max_pages,
        strict=args.strict,
    )
    result = run(request, client)

    diff_text = render_diff(base.body, result.doc.body)
    try:
        (out_dir / "diff.txt").write_text(
            (diff_text + "\n") if diff_text else "(no changes)\n",
            encoding="utf-8",
        )
    except OSError as exc:
        raise InputError(f"could not write diff.txt: {exc}") from exc

    keywords = keyword_report(jd, result.doc.body, profile, base.full)
    _print_report(args, result, keywords, diff_text)
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="tailor.py",
        description="Tailor a LaTeX resume to a job description and compile a one-page PDF.",
    )
    parser.add_argument("--company", help="company name, used for the output folder")
    parser.add_argument(
        "--check",
        action="store_true",
        help="check inputs, TeX tools and API configuration",
    )

    source = parser.add_mutually_exclusive_group()
    source.add_argument("--stdin", action="store_true", help="read the JD from stdin")
    source.add_argument(
        "--clipboard", action="store_true", help="read the JD from the clipboard"
    )
    source.add_argument("--jd-file", type=Path, help="read the JD from a file")

    parser.add_argument(
        "--provider", help="gemini (default) or an OpenAI-compatible provider"
    )
    parser.add_argument("--model", help="override RESUME_TAILOR_MODEL")
    parser.add_argument("--max-pages", type=int, default=1, help="page limit (default: 1)")
    parser.add_argument(
        "--strict",
        action="store_true",
        help="treat unverified skills/terms as fatal",
    )
    parser.add_argument(
        "--out-root",
        type=Path,
        default=Path("resumes"),
        help="output root (default: resumes/)",
    )
    parser.add_argument("--no-color", action="store_true", help="disable colored output")
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="print the full diff and tracebacks",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    _use_project_venv(argv, verbose=args.verbose)
    _load_env()

    if args.check:
        return _check(args)

    if not args.company or not args.company.strip():
        parser.error("--company is required")
    if args.max_pages < 1:
        parser.error("--max-pages must be at least 1")

    try:
        return _tailor(args)
    except TailorError as exc:
        print(f"error: {exc.message}", file=sys.stderr)
        for line in getattr(exc, "violations", [])[:12]:
            print(f"  {line}", file=sys.stderr)
        return exc.exit_code
    except KeyboardInterrupt:
        print("\naborted", file=sys.stderr)
        return 130
    except Exception as exc:
        if args.verbose:
            raise
        print(f"error: unexpected failure: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
