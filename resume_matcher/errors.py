"""Application exceptions. Every AppError carries a message safe to show to the user."""

from __future__ import annotations


class AppError(Exception):
    """Base class for errors whose message can be shown directly in the UI."""

    def __init__(self, message: str):
        super().__init__(message)
        self.user_message = message


# --- document handling -----------------------------------------------------
class DocumentError(AppError):
    """The document could not be read."""


class UnsupportedFormatError(DocumentError):
    pass


class CorruptedDocumentError(DocumentError):
    pass


class EmptyDocumentError(DocumentError):
    pass


# --- AI --------------------------------------------------------------------
class AIError(AppError):
    """Base class for AI provider problems."""


class AINotConfiguredError(AIError):
    pass


class AIAuthError(AIError):
    pass


class AIRateLimitError(AIError):
    pass


class AINetworkError(AIError):
    pass


class AIResponseError(AIError):
    """The model answered, but not with usable, valid JSON."""


# --- data ------------------------------------------------------------------
class NotFoundError(AppError):
    pass


class StorageError(AppError):
    pass
