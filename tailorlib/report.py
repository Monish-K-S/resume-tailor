"""Pure reporting helpers: JD keyword gap analysis and unified diff."""

from __future__ import annotations

import difflib
import re
from collections import Counter
from dataclasses import dataclass

from .facts import FactCorpus, is_name_like, latex_to_text, normalize_text, tokenize

STOPWORDS = frozenset(
    """
    a an the and or but if then else for to of in on at by with from as is are
    was were be been being have has had do does did will would should could can
    may might must shall you your we our us they their it its this that these
    those who whom which what when where why how all any both each few more most
    other some such no not only own same so than too very just also into over
    under about across after before between during through up down out off again
    further once here there etc using use used work working works experience
    experienced years year team teams role roles ability skills skill knowledge
    strong excellent good great new including include includes preferred required
    require requirements responsibilities responsibility candidate candidates job
    position company opportunity looking join help build building develop
    developing design designing implement implementing maintain maintaining create
    creating support supporting ensure ensuring drive driving deliver delivering
    manage managing lead leading collaborate collaborating partner partnering
    plus bonus nice ideal successful proven demonstrated solid deep hands hand
    engineer engineers engineering developer developers sr jr senior junior staff
    principal architect manager director specialist associate analyst consultant
    end full time part remote hybrid onsite salary benefits equal employer
    diversity inclusion apply application please contact email resume cv interview
    offer location based within without while per via
    """.split()
)

_WORD_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9+#./_-]*")
_ACRONYM_RE = re.compile(r"[A-Z][A-Z0-9&/+#.-]{1,7}")


@dataclass
class KeywordReport:
    matched: list[str]
    missing_available: list[str]
    missing_unknown: list[str]

    @property
    def missing(self) -> list[str]:
        return [*self.missing_available, *self.missing_unknown]


def extract_jd_keywords(jd: str, limit: int = 40) -> list[str]:
    """Acronyms, proper-noun phrases, then frequent content words from the JD."""
    matches = list(_WORD_RE.finditer(jd))
    words = [match.group(0).rstrip(".,;:") for match in matches]

    keywords: list[str] = []
    seen: set[str] = set()

    def add(term: str) -> None:
        key = normalize_text(term)
        if len(key) < 2 or key in seen:
            return
        seen.add(key)
        keywords.append(term)

    for word in words:
        if _ACRONYM_RE.fullmatch(word) and word.casefold() not in STOPWORDS:
            add(word)

    for index in range(len(matches)):
        for size in (3, 2):
            if index + size > len(matches):
                continue
            chunk = words[index : index + size]
            if not all(is_name_like(word) for word in chunk):
                continue
            if any(word.casefold() in STOPWORDS for word in chunk):
                continue
            gaps_ok = all(
                jd[
                    matches[index + offset].end() : matches[index + offset + 1].start()
                ].strip(" \t")
                == ""
                for offset in range(size - 1)
            )
            if gaps_ok:
                add(" ".join(chunk))

    frequency: Counter[str] = Counter()
    display: dict[str, str] = {}
    for word in words:
        key = word.casefold()
        if len(key) < 3 or key in STOPWORDS or key.isdigit():
            continue
        frequency[key] += 1
        display.setdefault(key, word)

    for key, _ in frequency.most_common(limit):
        add(display[key])

    return keywords[:limit]


def _phrases(tokens: list[str], sizes: tuple[int, ...] = (2, 3)) -> set[str]:
    phrases: set[str] = set()
    for size in sizes:
        for index in range(len(tokens) - size + 1):
            phrases.add(" ".join(tokens[index : index + size]))
    return phrases


def keyword_report(
    jd: str,
    body_tex: str,
    profile: dict,
    base_tex: str,
    *,
    limit: int = 40,
) -> KeywordReport:
    keywords = extract_jd_keywords(jd, limit)
    body_tokens = tokenize(latex_to_text(body_tex))
    body_token_set = set(body_tokens)
    body_phrases = _phrases(body_tokens)
    corpus = FactCorpus.build(profile, base_tex)

    matched: list[str] = []
    available: list[str] = []
    unknown: list[str] = []

    for keyword in keywords:
        key = normalize_text(keyword)
        if key in body_token_set or key in body_phrases:
            matched.append(keyword)
        elif key in corpus.tokens or key in corpus.phrases:
            available.append(keyword)
        else:
            unknown.append(keyword)

    return KeywordReport(matched, available, unknown)


def render_diff(base_body: str, new_body: str) -> str:
    return "\n".join(
        difflib.unified_diff(
            base_body.splitlines(),
            new_body.splitlines(),
            fromfile="base/resume.tex",
            tofile="tailored/resume.tex",
            lineterm="",
        )
    )


def diff_stats(diff_text: str) -> tuple[int, int]:
    added = removed = 0
    for line in diff_text.splitlines():
        if line.startswith("+") and not line.startswith("+++"):
            added += 1
        elif line.startswith("-") and not line.startswith("---"):
            removed += 1
    return added, removed
