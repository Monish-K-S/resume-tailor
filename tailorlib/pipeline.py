"""The retry state machine: generate -> validate -> compile -> page check."""

from __future__ import annotations

import math
import os
import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from .compile import compile_document, count_text_lines
from .errors import (
    CompileError,
    LLMError,
    PageLimitError,
    TailorError,
    ValidationError,
)
from .facts import FactCorpus
from .llm.base import LLMClient, Message
from .models import (
    CompileResult,
    Severity,
    TailorRequest,
    TailorResult,
    TexDoc,
    Violation,
)
from .prompts import (
    OUTPUT_SCHEMA,
    build_system_prompt,
    compile_fix_message,
    initial_user_message,
    page_cut_message,
)
from .tex import normalize_llm_body
from .validate import has_fatal, validate_body


class Compiler(Protocol):
    def __call__(
        self,
        full_tex: str,
        out_dir: Path,
        *,
        base_dir: Path | None = None,
        timeout: int = 60,
    ) -> CompileResult: ...


@dataclass
class PipelineConfig:
    temperature: float = 0.2
    max_tokens: int = 4096
    compile_timeout: int = 60


def estimate_cut_lines(overflow: str, *, fallback: int = 15) -> int:
    """Lines to ask the model to remove, with slack for reflow."""
    lines = count_text_lines(overflow)
    if lines <= 0:
        return fallback
    return max(5, math.ceil(lines * 1.5) + 2)


def run(
    request: TailorRequest,
    llm: LLMClient,
    *,
    compiler: Compiler = compile_document,
    config: PipelineConfig | None = None,
) -> TailorResult:
    """Tailor, validate, compile and retry at most once per failure class.

    Call budget: 1 base call + 1 compile fix + 1 page cut = 3 maximum.
    """
    cfg = config or PipelineConfig()
    started = time.perf_counter()

    out_dir = Path(request.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    work_dir = out_dir / ".work"
    if work_dir.exists():
        shutil.rmtree(work_dir)
    work_dir.mkdir(parents=True)

    corpus = FactCorpus.build(request.profile, request.base.full)
    system = build_system_prompt(request.prompt, request.base)
    history: list[Message] = [
        Message(
            "user", initial_user_message(request.profile, request.base, request.jd)
        )
    ]

    used = {"compile": False, "page": False}
    calls = 0
    raw_body = ""
    body = ""
    doc = request.base
    result: CompileResult | None = None
    violations: list[Violation] = []

    final_tex = out_dir / "resume.tex"
    final_pdf = out_dir / "resume.pdf"

    try:
        while True:
            payload = llm.complete(
                system=system,
                messages=history,
                schema=OUTPUT_SCHEMA,
                temperature=cfg.temperature,
                max_tokens=cfg.max_tokens,
            )
            calls += 1

            raw_body = payload.get("body") if isinstance(payload, dict) else None
            if not isinstance(raw_body, str) or not raw_body.strip():
                raise LLMError(
                    "the model response did not contain a non-empty 'body' string"
                )

            body = normalize_llm_body(raw_body)
            doc = TexDoc(preamble=request.base.preamble, body=body)

            violations = validate_body(
                request.base, body, corpus, strict=request.strict
            )
            if has_fatal(violations):
                raise ValidationError(
                    _summary(violations),
                    [f"[{v.severity.value}] {v.code}: {v.message}" for v in violations],
                )

            result = compiler(
                doc.full,
                work_dir,
                base_dir=request.base_dir,
                timeout=cfg.compile_timeout,
            )

            if result.error:
                if used["compile"]:
                    raise CompileError(result.error)
                used["compile"] = True
                history = [
                    *history,
                    Message("assistant", body),
                    Message("user", compile_fix_message(result.error)),
                ]
                continue

            if result.pages is None:
                raise CompileError("pdflatex succeeded but the page count is unknown")

            if result.pages > request.max_pages:
                if used["page"]:
                    raise PageLimitError(
                        f"still {result.pages} pages after one retry; the limit is "
                        f"{request.max_pages}. Trim profile.json or the base resume."
                    )
                used["page"] = True
                cut = estimate_cut_lines(result.overflow_text)
                history = [
                    *history,
                    Message("assistant", body),
                    Message(
                        "user",
                        page_cut_message(
                            result.pages, request.max_pages, cut, result.overflow_text
                        ),
                    ),
                ]
                continue

            break

        if result is None or result.pdf_path is None:
            raise CompileError("compiler reported success but produced no PDF")

        final_tex.write_text(doc.full, encoding="utf-8", newline="\n")
        os.replace(result.pdf_path, final_pdf)
    except TailorError:
        _save_failure(out_dir, work_dir, body, raw_body)
        raise
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)

    return TailorResult(
        doc=doc,
        pdf_path=final_pdf,
        tex_path=final_tex,
        pages=result.pages or 0,
        violations=violations,
        calls=calls,
        elapsed=time.perf_counter() - started,
        out_dir=out_dir,
    )


def _summary(violations: list[Violation]) -> str:
    fatal = [v for v in violations if v.severity is Severity.FATAL]
    return "; ".join(f"{v.term or v.code}: {v.message}" for v in fatal)


def _save_failure(out_dir: Path, work_dir: Path, body: str, raw: str) -> None:
    """Keep the rejected body and the pdflatex log for debugging."""
    try:
        if body:
            (out_dir / "resume.rejected.tex").write_text(body, encoding="utf-8")
        elif raw:
            (out_dir / "resume.rejected.raw.txt").write_text(raw, encoding="utf-8")

        log = work_dir / "resume.log"
        if log.exists():
            shutil.copy2(log, out_dir / "compile.log")
    except OSError:
        pass
