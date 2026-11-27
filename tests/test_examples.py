from __future__ import annotations

import json
from pathlib import Path

from tailorlib.facts import FactCorpus
from tailorlib.tex import extract_sections, split_tex
from tailorlib.validate import has_fatal, validate_body

ROOT = Path(__file__).resolve().parent.parent
PROFILE_EXAMPLE = ROOT / "profile.example.json"
BASE_EXAMPLE = ROOT / "base" / "resume.example.tex"

SECTIONS = [
    "Professional Summary",
    "Technical Skills",
    "Projects",
    "Education",
    "Achievements",
]


def test_example_profile_is_a_json_object():
    profile = json.loads(PROFILE_EXAMPLE.read_text(encoding="utf-8"))

    assert isinstance(profile, dict)
    assert profile["identity"]["name"] == "Jordan Doe"
    assert profile["identity"]["email"].endswith("@example.com")
    assert profile["identity"]["links"]["github"].startswith("https://github.com/")


def test_example_base_is_a_complete_one_page_document():
    doc = split_tex(BASE_EXAMPLE.read_text(encoding="utf-8"))

    assert doc.body.startswith("\\begin{document}")
    assert doc.body.rstrip().endswith("\\end{document}")
    assert extract_sections(doc.body) == SECTIONS


def test_example_base_body_passes_validation():
    profile = json.loads(PROFILE_EXAMPLE.read_text(encoding="utf-8"))
    doc = split_tex(BASE_EXAMPLE.read_text(encoding="utf-8"))
    corpus = FactCorpus.build(profile, doc.full)

    violations = validate_body(doc, doc.body, corpus)

    assert not has_fatal(violations), [v.message for v in violations]
