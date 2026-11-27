"""Expected, user-facing failures. The CLI maps these to one-line messages."""

from __future__ import annotations


class TailorError(Exception):
    """Base class for failures we can explain to the user."""

    exit_code = 1

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class InputError(TailorError):
    """Missing/invalid inputs (resume, profile, prompt, JD, flags)."""

    exit_code = 2


class ConfigError(InputError):
    """Missing API key, unknown provider, unusable model config."""

    exit_code = 2


class TexError(TailorError):
    """The document does not have the shape we require."""

    exit_code = 3


class ValidationError(TailorError):
    """The tailored body failed a validator."""

    exit_code = 3

    def __init__(self, message: str, violations: list[str] | None = None) -> None:
        super().__init__(message)
        self.violations = violations or []


class CompileError(TailorError):
    """pdflatex is missing, timed out, or refused the document."""

    exit_code = 4


class PageLimitError(TailorError):
    """The PDF still exceeds the page limit after the retry."""

    exit_code = 5


class LLMError(TailorError):
    """Provider call failed, returned unparseable output, or was misconfigured."""

    exit_code = 6
