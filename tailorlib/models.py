"""Plain data passed between the pipeline stages."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path


class Severity(str, Enum):
    FATAL = "fatal"
    WARN = "warn"


@dataclass(frozen=True)
class TexDoc:
    """A resume split at ``\\begin{document}``.

    ``preamble + body`` reproduces the source file byte-for-byte.
    """

    preamble: str
    body: str

    @property
    def full(self) -> str:
        return self.preamble + self.body


@dataclass(frozen=True)
class Violation:
    """One failed (or advisory) check, with the offending term when there is one."""

    code: str
    message: str
    term: str | None = None
    severity: Severity = Severity.FATAL


@dataclass
class CompileResult:
    """Outcome of one pdflatex attempt (which may include two passes)."""

    pdf_path: Path | None = None
    pages: int | None = None
    error: str | None = None
    overflow_text: str = ""
    log_path: Path | None = None
    runs: int = 0

    @property
    def ok(self) -> bool:
        return self.error is None and self.pdf_path is not None


@dataclass
class TailorRequest:
    company: str
    jd: str
    base: TexDoc
    profile: dict
    prompt: str
    out_dir: Path
    base_dir: Path
    max_pages: int = 1
    strict: bool = False


@dataclass
class TailorResult:
    doc: TexDoc
    pdf_path: Path
    tex_path: Path
    pages: int
    violations: list[Violation]
    calls: int
    elapsed: float
    out_dir: Path
