from __future__ import annotations

from tailorlib.report import (
    diff_stats,
    extract_jd_keywords,
    keyword_report,
    render_diff,
)

JD = """
Senior Backend Engineer

We are looking for a backend engineer to build distributed services with
Python, PostgreSQL and Apache Kafka. Experience with Kubernetes, Terraform and
AWS is preferred. You will design REST APIs, own observability, and mentor
engineers. Strong communication skills required.
"""

PROFILE = {
    "skills": ["Python", "PostgreSQL", "Apache Kafka", "Docker"],
    "experience": "Built REST APIs with Python and PostgreSQL.",
}

BASE = r"""
\documentclass{article}
\begin{document}
Built REST APIs with Python and PostgreSQL.
\end{document}
"""


def test_extract_jd_keywords_finds_tech_and_acronyms():
    keywords = extract_jd_keywords(JD)
    lowered = {keyword.casefold() for keyword in keywords}
    assert "python" in lowered
    assert "postgresql" in lowered
    assert "apache kafka" in lowered
    assert "kubernetes" in lowered
    assert "terraform" in lowered
    assert "apis" in lowered
    assert "engineer" not in lowered


def test_extract_jd_keywords_is_deduplicated():
    keywords = extract_jd_keywords(JD)
    assert len(keywords) == len({keyword.casefold() for keyword in keywords})


def test_keyword_report_splits_matched_available_unknown():
    body = (
        "\\begin{document}\n"
        "Built REST APIs with Python and PostgreSQL.\n"
        "\\end{document}\n"
    )
    report = keyword_report(JD, body, PROFILE, BASE)

    matched = {keyword.casefold() for keyword in report.matched}
    available = {keyword.casefold() for keyword in report.missing_available}
    unknown = {keyword.casefold() for keyword in report.missing_unknown}

    assert "python" in matched
    assert "apache kafka" in available
    assert "kubernetes" in unknown
    assert not matched & available
    assert not matched & unknown


def test_keyword_report_missing_is_concatenation():
    report = keyword_report(JD, "\\begin{document}Python\\end{document}", PROFILE, BASE)
    assert report.missing == [*report.missing_available, *report.missing_unknown]


def test_render_diff_labels_both_sides():
    diff = render_diff("a\nb\n", "a\nc\n")
    assert "--- base/resume.tex" in diff
    assert "+++ tailored/resume.tex" in diff
    assert "-b" in diff
    assert "+c" in diff


def test_diff_stats_counts_content_lines_only():
    diff = render_diff("a\nb\n", "a\nc\nd\n")
    added, removed = diff_stats(diff)
    assert (added, removed) == (2, 1)


def test_diff_stats_empty_diff():
    assert diff_stats("") == (0, 0)
