from __future__ import annotations

from tailorlib.models import Severity
from tailorlib.validate import (
    allowed_commands,
    allowed_environments,
    has_fatal,
    validate_body,
)


def insert_before_end(body: str, snippet: str) -> str:
    return body.replace("\\end{document}", f"{snippet}\n\\end{{document}}", 1)


def test_base_body_is_valid(base_doc, corpus):
    assert validate_body(base_doc, base_doc.body, corpus) == []


def test_missing_section_is_fatal(base_doc, corpus):
    body = base_doc.body.replace("\\section{Projects}", "\\section{Experience}")
    violations = validate_body(base_doc, body, corpus)
    assert any(v.code == "sections" and v.severity is Severity.FATAL for v in violations)


def test_reordered_sections_are_fatal(base_doc, corpus):
    body = base_doc.body.replace(
        "\\section{Education}", "\\section{TMP}", 1
    ).replace("\\section{Achievements}", "\\section{Education}", 1).replace(
        "\\section{TMP}", "\\section{Achievements}", 1
    )
    violations = validate_body(base_doc, body, corpus)
    assert any(v.code == "sections" for v in violations)


def test_unbalanced_brace_is_fatal(base_doc, corpus):
    body = insert_before_end(base_doc.body, "{")
    violations = validate_body(base_doc, body, corpus)
    assert any(v.code == "brace" for v in violations)


def test_unknown_command_is_fatal(base_doc, corpus):
    body = insert_before_end(base_doc.body, "\\foo")
    violations = validate_body(base_doc, body, corpus)
    assert any(v.code == "command" and v.term == "foo" for v in violations)


def test_preamble_command_is_fatal(base_doc, corpus):
    body = insert_before_end(base_doc.body, "\\usepackage{evil}")
    violations = validate_body(base_doc, body, corpus)
    assert any(v.code == "command" and v.term == "usepackage" for v in violations)


def test_unknown_environment_is_fatal(base_doc, corpus):
    body = insert_before_end(
        base_doc.body, "\\begin{verbatim}raw\\end{verbatim}"
    )
    violations = validate_body(base_doc, body, corpus)
    assert any(v.code == "environment" and v.term == "verbatim" for v in violations)


def test_allowlist_extends_from_base_body(base_doc):
    assert {"achieveItem", "hfill", "LARGE"} <= allowed_commands(base_doc)
    assert "center" in allowed_environments(base_doc)
    assert "verbatim" not in allowed_environments(base_doc)


def test_strict_promotes_warnings(base_doc, corpus):
    body = base_doc.body.replace(
        "Won a dummy award.", "Won a dummy award with Terraform."
    )
    relaxed = validate_body(base_doc, body, corpus)
    assert not has_fatal(relaxed)
    assert any(v.term == "Terraform" for v in relaxed)

    strict = validate_body(base_doc, body, corpus, strict=True)
    assert has_fatal(strict)
    assert any(v.term == "Terraform" and v.severity is Severity.FATAL for v in strict)
