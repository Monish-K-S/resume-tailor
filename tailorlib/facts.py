"""Build a fact corpus from profile.json + the base resume, then check a body.

Severity policy (chosen deliberately):
  * numbers, URLs and emails are FATAL when invented
  * skills/tools/proper nouns are WARNINGS, reported but not blocking

The check is deterministic: no LLM call is involved.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any, Iterator

from .models import Severity, Violation
from .tex import strip_comments

# --------------------------------------------------------------------------- #
# normalisation
# --------------------------------------------------------------------------- #

_DASHES = {"\u2013": "-", "\u2014": "-", "\u2212": "-"}
_QUOTES = {
    "\u2018": "'",
    "\u2019": "'",
    "\u201c": '"',
    "\u201d": '"',
    "\u00a0": " ",
}

_TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9+#./_-]*[a-z0-9+#]|[a-z0-9]")


def normalize_text(text: str) -> str:
    text = unicodedata.normalize("NFKC", text)
    for src, dst in {**_DASHES, **_QUOTES}.items():
        text = text.replace(src, dst)
    text = re.sub(r"\s+", " ", text).strip()
    return text.casefold()


def tokenize(text: str) -> list[str]:
    return _TOKEN_RE.findall(normalize_text(text))


def _flatten(value: Any) -> Iterator[str]:
    if isinstance(value, dict):
        for item in value.values():
            yield from _flatten(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from _flatten(item)
    elif isinstance(value, bool):
        return
    elif isinstance(value, (str, int, float)):
        yield str(value)


# --------------------------------------------------------------------------- #
# LaTeX -> plain text (for number/term extraction only)
# --------------------------------------------------------------------------- #

_DROP_ENVIRONMENTS = re.compile(
    r"\\(?:begin|end)\s*\{[^{}]*\}\s*(?:\[[^\]]*\])?"
)
_DROP_DOC_COMMANDS = re.compile(
    r"\\(?:documentclass|usepackage|RequirePackage)\s*(?:\[[^\]]*\])?\s*\{[^{}]*\}"
)
_DROP_LENGTHS = re.compile(
    r"\\(?:setlength|addtolength)\s*\{[^{}]*\}\s*\{[^{}]*\}"
)
_DROP_LINEBREAK_SPACING = re.compile(r"\\\\\s*(?:\[[^\]]*\])?")

_DROP_COMMANDS = (
    "vspace",
    "hspace",
    "rule",
    "includegraphics",
    "linespread",
    "pagestyle",
    "thispagestyle",
    "hypersetup",
    "titleformat",
    "titlespacing",
    "pdfgentounicode",
    "hyphenpenalty",
    "exhyphenpenalty",
    "tolerance",
    "emergencystretch",
    "newcommand",
    "renewcommand",
    "providecommand",
    "def",
    "let",
    "input",
    "include",
    "label",
    "ref",
    "pageref",
    "cite",
)


def _drop_layout(text: str) -> str:
    text = _DROP_ENVIRONMENTS.sub("\n", text)
    text = _DROP_DOC_COMMANDS.sub(" ", text)
    text = _DROP_LENGTHS.sub(" ", text)
    text = _DROP_LINEBREAK_SPACING.sub("\n", text)
    for command in _DROP_COMMANDS:
        text = re.sub(
            rf"\\{command}\*?\s*(?:\[[^\]]*\])?\s*(?:\{{[^{{}}]*\}})?", " ", text
        )
    return text


def latex_to_text(text: str) -> str:
    """Strip commands and braces while keeping the words and arguments."""
    text = _drop_layout(strip_comments(text))
    out: list[str] = []
    i = 0
    while i < len(text):
        ch = text[i]
        if ch == "\\":
            j = i + 1
            if j < len(text) and (text[j].isalpha() or text[j] == "@"):
                while j < len(text) and (text[j].isalpha() or text[j] == "@"):
                    j += 1
                k = j
                while k < len(text) and text[k] in " \t":
                    k += 1
                if k < len(text) and text[k] == "[":
                    close = text.find("]", k)
                    if close != -1:
                        j = close + 1
                out.append(" ")
                i = j
                continue
            if j < len(text):
                escaped = text[j]
                if escaped in "%&$#_{}":
                    out.append(escaped)
                elif escaped == "\\":
                    out.append("\n")
                else:
                    out.append(" ")
                i = j + 1
                continue
            i += 1
            continue
        if ch in "{}":
            out.append("\n")
        elif ch in "~$":
            out.append(" ")
        else:
            out.append(ch)
        i += 1
    return re.sub(r"[ \t]+", " ", "".join(out))


# --------------------------------------------------------------------------- #
# numbers, URLs, emails
# --------------------------------------------------------------------------- #

_UNIT = (
    r"(?:%|x|k|m|b|s|ms|secs?|seconds?|mins?|minutes?|hrs?|hours?|days?|weeks?"
    r"|months?|years?|yrs?|st|nd|rd|th)?"
)
_NUMBER_RE = re.compile(
    rf"(?<![\w.])(\$?\d[\d,]*(?:\.\d+)?)\s*{_UNIT}(?![\w])", re.IGNORECASE
)
_HREF_ARG_RE = re.compile(r"\\href\s*\{([^{}]*)\}")
_URL_RE = re.compile(r"(?:https?://|mailto:|tel:)[^\s{}]+", re.IGNORECASE)
_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")


def extract_numbers(text: str) -> set[str]:
    found: set[str] = set()
    for match in _NUMBER_RE.finditer(text):
        raw = match.group(0).replace("$", "").replace(",", "")
        found.add(re.sub(r"\s+", "", raw).casefold())
    return found


def _normalize_url(url: str) -> str:
    return url.strip().strip(".,;:)]}").rstrip("/").casefold()


def extract_urls(tex: str) -> set[str]:
    found: set[str] = set()
    for match in _HREF_ARG_RE.finditer(tex):
        found.add(match.group(1))
    for match in _URL_RE.finditer(strip_comments(tex)):
        found.add(match.group(0))
    return {_normalize_url(url) for url in found if url.strip()}


def extract_emails(tex: str) -> set[str]:
    return {match.group(0).casefold() for match in _EMAIL_RE.finditer(strip_comments(tex))}


# --------------------------------------------------------------------------- #
# corpus
# --------------------------------------------------------------------------- #


@dataclass
class FactCorpus:
    tokens: set[str] = field(default_factory=set)
    phrases: set[str] = field(default_factory=set)
    numbers: set[str] = field(default_factory=set)
    urls: set[str] = field(default_factory=set)
    emails: set[str] = field(default_factory=set)

    @classmethod
    def build(cls, profile: Any, base_tex: str) -> "FactCorpus":
        profile_text = "\n".join(_flatten(profile))
        base_text = latex_to_text(base_tex)
        text = profile_text + "\n" + base_text
        tokens = tokenize(text)

        phrases: set[str] = set()
        for size in (2, 3):
            for index in range(len(tokens) - size + 1):
                phrases.add(" ".join(tokens[index : index + size]))

        return cls(
            tokens=set(tokens),
            phrases=phrases,
            numbers=extract_numbers(text),
            urls=extract_urls(profile_text) | extract_urls(base_tex),
            emails=extract_emails(profile_text) | extract_emails(base_tex),
        )


# --------------------------------------------------------------------------- #
# claims
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class TermClaim:
    term: str
    kind: str


@dataclass
class Claims:
    numbers: set[str] = field(default_factory=set)
    urls: set[str] = field(default_factory=set)
    emails: set[str] = field(default_factory=set)
    terms: list[TermClaim] = field(default_factory=list)


_WORD_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9+#./_-]*")
_SENTENCE_END = set(".!?:\n")


def _is_acronym(token: str) -> bool:
    return bool(re.fullmatch(r"[A-Z][A-Z0-9&/]{1,7}", token))


def _is_camel(token: str) -> bool:
    return bool(re.search(r"[a-z][A-Z]", token)) or bool(
        re.search(r"^[A-Z][a-z]+[A-Z]", token)
    )


def _is_tech(token: str) -> bool:
    if any(char in token for char in ".+#/"):
        return True
    return bool(re.search(r"(?:sql|db|api|ml|ai|js|py)$", token, re.IGNORECASE))


def _is_title(token: str) -> bool:
    return len(token) > 1 and token[0].isupper() and token[1:].islower()


def is_name_like(token: str) -> bool:
    return _is_acronym(token) or _is_camel(token) or _is_tech(token) or _is_title(token)


def _sentence_start(text: str, index: int) -> bool:
    position = index - 1
    while position >= 0 and text[position] in " \t":
        position -= 1
    return position < 0 or text[position] in _SENTENCE_END


def extract_claims(body_tex: str) -> Claims:
    text = latex_to_text(body_tex)
    claims = Claims(
        numbers=extract_numbers(text),
        urls=extract_urls(body_tex),
        emails=extract_emails(body_tex),
    )

    matches = list(_WORD_RE.finditer(text))
    runs: list[list[tuple[str, re.Match[str]]]] = []
    current: list[tuple[str, re.Match[str]]] = []

    for match in matches:
        token = match.group(0).rstrip(".,;:")
        gap = text[current[-1][1].end() : match.start()] if current else ""
        if is_name_like(token) and gap.strip(" \t") == "":
            current.append((token, match))
        else:
            if len(current) >= 2:
                runs.append(current)
            current = [(token, match)] if is_name_like(token) else []
    if len(current) >= 2:
        runs.append(current)

    covered: set[int] = set()
    for run in runs:
        for start in range(len(run)):
            for size in (3, 2):
                if start + size <= len(run):
                    window = " ".join(token for token, _ in run[start : start + size])
                    claims.terms.append(TermClaim(window, "phrase"))
                    covered.update(id(run[start + offset][1]) for offset in range(size))

    for match in matches:
        token = match.group(0).rstrip(".,;:")
        if len(token) < 2 or not token[0].isupper():
            continue
        if id(match) in covered:
            continue
        if _is_acronym(token):
            kind = "acronym"
        elif _is_camel(token):
            kind = "camel"
        elif _is_tech(token):
            kind = "tech"
        elif _is_title(token):
            kind = "title"
            if _sentence_start(text, match.start()):
                continue
        else:
            continue
        claims.terms.append(TermClaim(token, kind))

    return claims


# --------------------------------------------------------------------------- #
# checking
# --------------------------------------------------------------------------- #


def _term_known(term: str, corpus: FactCorpus) -> bool:
    normalized = normalize_text(term)
    if not normalized:
        return True
    if normalized in corpus.tokens:
        return True
    if normalized in corpus.phrases:
        return True
    if normalized.endswith("s") and normalized[:-1] in corpus.tokens:
        return True
    for token in corpus.tokens:
        for separator in (".", "-", "/", "+", "#"):
            if token.startswith(normalized + separator):
                return True
            if normalized.startswith(token + separator):
                return True
    return False


def check_facts(corpus: FactCorpus, body_tex: str) -> list[Violation]:
    claims = extract_claims(body_tex)
    violations: list[Violation] = []

    for number in sorted(claims.numbers):
        if number not in corpus.numbers:
            violations.append(
                Violation(
                    "number",
                    f"number '{number}' does not appear in profile.json or the base resume",
                    term=number,
                )
            )

    for url in sorted(claims.urls):
        if url not in corpus.urls:
            violations.append(
                Violation(
                    "url",
                    f"URL '{url}' does not appear in profile.json or the base resume",
                    term=url,
                )
            )

    for email in sorted(claims.emails):
        if email not in corpus.emails:
            violations.append(
                Violation(
                    "email",
                    f"email '{email}' does not appear in profile.json or the base resume",
                    term=email,
                )
            )

    seen: set[str] = set()
    for claim in claims.terms:
        key = claim.term.casefold()
        if key in seen:
            continue
        seen.add(key)
        if _term_known(claim.term, corpus):
            continue
        violations.append(
            Violation(
                "term",
                f"{claim.kind} '{claim.term}' does not appear in profile.json "
                f"or the base resume",
                term=claim.term,
                severity=Severity.WARN,
            )
        )

    return violations
