from __future__ import annotations

from pathlib import Path

import pytest

from tailorlib.facts import FactCorpus
from tailorlib.tex import split_tex

FIXTURE = Path(__file__).parent / "fixtures" / "minimal.tex"


@pytest.fixture
def base_text() -> str:
    return FIXTURE.read_text(encoding="utf-8")


@pytest.fixture
def base_doc(base_text):
    return split_tex(base_text)


@pytest.fixture
def corpus(base_text) -> FactCorpus:
    return FactCorpus.build(
        {
            "name": "Dummy Candidate",
            "skills": ["Python", "PostgreSQL", "Node.js", "React.js", "Apache Kafka"],
            "metrics": "Reduced latency by 37% (22.8s to 14.4s)",
            "links": {
                "github": "https://github.com/dummy/repo",
                "site": "https://example.com",
            },
            "email": "dummy@example.com",
        },
        base_text,
    )
