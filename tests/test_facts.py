from __future__ import annotations

import pytest

from tailorlib.facts import FactCorpus, check_facts, latex_to_text
from tailorlib.models import Severity

PROFILE = {
    "name": "Jane Doe",
    "skills": ["Python", "PostgreSQL", "Node.js", "React.js", "Apache Kafka"],
    "metrics": "Reduced latency by 37% (22.8s to 14.4s)",
    "links": {
        "github": "https://github.com/jane/repo",
        "site": "https://jane.example",
    },
    "email": "jane@example.com",
}

BASE = r"""\documentclass{article}
\begin{document}
Jane Doe builds APIs with Python and PostgreSQL.
\end{document}
"""


@pytest.fixture
def corpus() -> FactCorpus:
    return FactCorpus.build(PROFILE, BASE)


def body(text: str) -> str:
    return f"\\begin{{document}}\n{text}\n\\end{{document}}\n"


def check(corpus: FactCorpus, text: str):
    return check_facts(corpus, body(text))


def fatal(violations):
    return [v for v in violations if v.severity is Severity.FATAL]


def warnings(violations):
    return [v for v in violations if v.severity is Severity.WARN]


def test_invented_number_is_fatal(corpus):
    violations = check(corpus, r"Cut latency by 999\%.")
    assert [v.term for v in fatal(violations)] == ["999%"]


def test_invented_url_is_fatal(corpus):
    violations = check(corpus, r"\href{https://evil.example}{link}")
    assert any(v.code == "url" and v.severity is Severity.FATAL for v in violations)


def test_invented_email_is_fatal(corpus):
    violations = check(corpus, "Contact evil@example.com.")
    assert any(v.code == "email" and v.severity is Severity.FATAL for v in violations)


def test_known_numbers_pass(corpus):
    assert fatal(check(corpus, r"Reduced latency by 37\% (22.8s to 14.4s).")) == []


def test_escaped_percent_is_normalised(corpus):
    assert fatal(check(corpus, r"Reduced latency by 37\%.")) == []


def test_vspace_numbers_are_ignored(corpus):
    violations = check(corpus, r"\vspace{12pt} Reduced latency by 37\%.")
    assert fatal(violations) == []


def test_invented_skill_is_only_a_warning(corpus):
    violations = check(corpus, "Built services with Terraform.")
    assert fatal(violations) == []
    assert [v.term for v in warnings(violations)] == ["Terraform"]


def test_known_skill_passes(corpus):
    assert warnings(check(corpus, "Built services with PostgreSQL.")) == []


def test_prefix_match_accepts_react_for_react_js(corpus):
    assert warnings(check(corpus, "Built services with React.")) == []


def test_known_phrase_passes(corpus):
    assert warnings(check(corpus, "Built pipelines with Apache Kafka.")) == []


def test_invented_phrase_is_a_single_warning(corpus):
    violations = warnings(check(corpus, "Built pipelines with Apache Spark."))
    assert [v.term for v in violations] == ["Apache Spark"]


def test_latex_to_text_drops_layout_but_keeps_link_text():
    text = latex_to_text(r"\vspace{2pt}\href{https://x.dev}{click here}")
    assert "2pt" not in text
    assert "click here" in text
    assert "https://x.dev" in text
