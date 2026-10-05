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
# Email / SMTP errors
# ---------------------------------------------------------------------------

class EmailError(BroadcastError):
    """Base class for all email-related failures."""


class EmailAuthenticationError(EmailError):
    """SMTP credentials were rejected (wrong user/password or unauthorized IP)."""

    def __init__(self, message: str = ""):
        super().__init__(
            message or "SMTP authentication failed.",
            user_message=(
                "Unable to send email — the mail server rejected our credentials. "
                "Please contact the administrator."
            ),
        )


class EmailConnectionError(EmailError):
    """Could not connect to the SMTP server at all."""

    def __init__(self, message: str = ""):
        super().__init__(
            message or "Could not connect to the SMTP server.",
            user_message=(
                "Unable to send email — could not reach the mail server. "
                "Please try again later."
            ),
        )


class EmailDeliveryError(EmailError):
    """Connected successfully but the message was not accepted."""

    def __init__(self, message: str = ""):
        super().__init__(
            message or "The mail server refused the message.",
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
