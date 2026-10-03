"""Safe domain errors shared by the HTTP and service layers."""

from __future__ import annotations


class MatchdayError(Exception):
    def __init__(
        self,
        code: str,
        message: str,
        status: int = 400,
        retryable: bool = False,
        details: dict[str, object] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status
        self.retryable = retryable
        self.details = details or {}
