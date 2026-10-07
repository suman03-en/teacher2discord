"""
Custom exceptions for the broadcast app.

These provide specific, catchable error types so that views can map
each failure to the right user-facing message without catching bare
``Exception``.
"""


class BroadcastError(Exception):
    """Base exception for all broadcast-app errors."""

    def __init__(self, message: str = "", *, user_message: str = ""):
        super().__init__(message)
        # A safe, non-technical message that can be shown to the end user.
        self.user_message = user_message or message


# ---------------------------------------------------------------------------
# Email (Brevo API) errors
# ---------------------------------------------------------------------------

class EmailError(BroadcastError):
    """Base class for all email-related failures."""


class EmailConfigurationError(EmailError):
    """Email backend is misconfigured (e.g. ``BREVO_API_KEY`` missing)."""

    def __init__(self, message: str = ""):
        super().__init__(
            message or "Email backend is not configured correctly.",
            user_message=(
                "Email service is not configured. "
                "Please contact the administrator."
            ),
        )


class EmailAuthenticationError(EmailError):
    """Brevo rejected the API key (HTTP 401/403 — invalid, revoked or IP not authorised)."""

    def __init__(self, message: str = ""):
        super().__init__(
            message or "Brevo API key was rejected.",
            user_message=(
                "Unable to send email — the email service rejected our credentials. "
                "Please contact the administrator."
            ),
        )


class EmailRateLimitError(EmailError):
    """Brevo rate limit or sending quota exceeded (HTTP 429)."""

    def __init__(self, message: str = ""):
        super().__init__(
            message or "Brevo rate limit exceeded.",
            user_message=(
                "Too many emails are being sent right now. "
                "Please wait a moment and try again."
            ),
        )


class EmailRecipientError(EmailError):
    """The recipient address is invalid or was refused by Brevo."""

    def __init__(self, message: str = ""):
        super().__init__(
            message or "Recipient address was rejected.",
            user_message=(
                "We couldn't send an email to that address. "
                "Please check it and try again."
            ),
        )


class EmailConnectionError(EmailError):
    """Could not reach the Brevo API (network error, timeout, DNS failure)."""

    def __init__(self, message: str = ""):
        super().__init__(
            message or "Could not connect to the Brevo API.",
            user_message=(
                "Unable to send email — could not reach the email service. "
                "Please try again later."
            ),
        )


class EmailDeliveryError(EmailError):
    """Brevo responded with an error not covered by a more specific class."""

    def __init__(self, message: str = ""):
        super().__init__(
            message or "Brevo API refused the message.",
            user_message="Failed to send the login email. Please try again later.",
        )


# ---------------------------------------------------------------------------
# Token / auth errors
# ---------------------------------------------------------------------------

class TokenError(BroadcastError):
    """Base class for login-token problems."""


class TokenExpiredError(TokenError):
    """The magic-link token has expired."""

    def __init__(self):
        super().__init__(
            "Login token has expired.",
            user_message="This login link has expired. Please request a new one.",
        )


class TokenAlreadyUsedError(TokenError):
    """The magic-link token was already consumed."""

    def __init__(self):
        super().__init__(
            "Login token was already used.",
            user_message="This login link has already been used.",
        )


# ---------------------------------------------------------------------------
# Discord / webhook errors
# ---------------------------------------------------------------------------

class DiscordError(BroadcastError):
    """Base class for Discord webhook failures."""


class DiscordDeliveryError(DiscordError):
    """The webhook request failed or returned a non-success status."""

    def __init__(self, message: str = ""):
        super().__init__(
            message or "Discord webhook delivery failed.",
            user_message="Failed to send message to Discord. Please try again.",
        )


class WebhookDuplicateError(DiscordError):
    """The same webhook URL is already registered in this folder."""

    def __init__(self):
        super().__init__(
            "Duplicate webhook in folder.",
            user_message="This webhook is already connected to a different link in this folder.",
        )


# ---------------------------------------------------------------------------
# Student-link errors
# ---------------------------------------------------------------------------

class StudentLinkError(BroadcastError):
    """Base class for student-link problems."""


class StudentLinkAlreadyUsedError(StudentLinkError):
    """The student link was already consumed (race-condition guard)."""

    def __init__(self):
        super().__init__(
            "Student link already used.",
            user_message="This student link has already been used.",
        )
