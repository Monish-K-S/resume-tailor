"""The validator gate. A body reaches pdflatex only if every fatal check passes."""

from __future__ import annotations

import re

from .errors import TexError
from .facts import FactCorpus, check_facts
from .models import Severity, TexDoc, Violation
from .tex import (
    DOC_BEGIN,
    DOC_END,
    check_balanced,
    extract_sections,
    scan_commands,
    split_tex,
    strip_comments,
)

# The macros named in the brief. Anything already used by the base body is
# added automatically, so the candidate's own header/achievements stay legal.
SPEC_COMMANDS = frozenset(
    {
        "begin",
        "end",
        "section",
        "roleEntry",
        "resumeItem",
        "itemize",
        "enumerate",
        "item",
        "textbf",
        "textit",
        "href",
        "vspace",
    }
)

SPEC_ENVIRONMENTS = frozenset({"document", "itemize", "enumerate"})

_ENV_RE = re.compile(r"\\(begin|end)\s*\{([^{}]*)\}")


def allowed_commands(base: TexDoc) -> set[str]:
    return set(SPEC_COMMANDS) | {name for name, _ in scan_commands(base.body)}


def allowed_environments(base: TexDoc) -> set[str]:
    return set(SPEC_ENVIRONMENTS) | {
        match.group(2).strip() for match in _ENV_RE.finditer(strip_comments(base.body))
    }


def _environments(body: str) -> list[tuple[str, int]]:
    clean = strip_comments(body)
    return [
        (match.group(2).strip(), clean.count("\n", 0, match.start()) + 1)
        for match in _ENV_RE.finditer(clean)
    ]


def has_fatal(violations: list[Violation]) -> bool:
    return any(violation.severity is Severity.FATAL for violation in violations)


def validate_body(
    base: TexDoc,
    body: str,
    corpus: FactCorpus,
    *,
    strict: bool = False,
) -> list[Violation]:
    """Validate a candidate body against the frozen base document."""
    violations: list[Violation] = []

    if not body.startswith(DOC_BEGIN):
        violations.append(
            Violation("document", f"body must start with {DOC_BEGIN}")
        )
    if not body.rstrip().endswith(DOC_END):
        violations.append(Violation("document", f"body must end with {DOC_END}"))

    try:
        reparsed = split_tex(base.preamble + body)
    except TexError as exc:
        violations.append(Violation("document", str(exc)))
        return violations

    if reparsed.preamble != base.preamble:
        violations.append(
            Violation("preamble", "the preamble is not byte-for-byte identical to the base")
        )

    base_sections = extract_sections(base.body)
    new_sections = extract_sections(body)
    if base_sections != new_sections:
        violations.append(
            Violation(
                "sections",
                f"section structure changed: expected {base_sections}, got {new_sections}",
            )
        )

    violations.extend(check_balanced(body))

    allowed = allowed_commands(base)
    reported: set[str] = set()
    for name, line in scan_commands(body):
        if name in allowed or name in reported:
            continue
        reported.add(name)
        violations.append(
            Violation(
                "command",
                f"\\{name} on line {line} is not in the allowlist",
                term=name,
            )
        )

    allowed_envs = allowed_environments(base)
    for name, line in _environments(body):
        if name not in allowed_envs:
            violations.append(
                Violation(
                    "environment",
                    f"environment '{name}' on line {line} is not in the allowlist",
                    term=name,
                )
            )

    violations.extend(check_facts(corpus, body))

    if strict:
        violations = [
            Violation(v.code, v.message, v.term, Severity.FATAL)
            if v.severity is Severity.WARN
            else v
            for v in violations
        ]

    return violations
