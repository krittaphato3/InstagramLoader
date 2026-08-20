"""Typed errors that map to friendly, user-facing messages.

Keeping every failure mode here means the API layer and the UI can agree on
the exact wording, and the downloader can mark items as failed without
aborting the whole job.
"""
from __future__ import annotations


class AppError(Exception):
    """Base class for all expected, user-facing failures."""

    status_code = 400
    message = "Something went wrong."


class InvalidInputError(AppError):
    message = "That does not look like a valid Instagram link or username."


class UnsupportedURLError(AppError):
    message = "This URL is not supported. Paste an Instagram post, reel, profile, or username."


class PrivateAccountError(AppError):
    status_code = 403
    message = "This content appears to be private or unavailable."


class DeletedError(AppError):
    status_code = 404
    message = "This post could not be found. It may have been deleted."


class LoginRequiredError(AppError):
    message = "Instagram requires login to view this content."


class RateLimitError(AppError):
    status_code = 429
    message = "Too many requests. Please wait a moment and try again."


class NetworkError(AppError):
    status_code = 502
    message = "Could not reach Instagram. Please try again later."


class NotFoundError(AppError):
    status_code = 404
    message = "Could not find any downloadable media for this input."


class DownloadError(AppError):
    """Raised for a single item failing to download; the job continues."""