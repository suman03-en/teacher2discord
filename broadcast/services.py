"""
Service layer for the broadcast app.

All business logic and database mutations live here so that views
remain thin request/response handlers.
"""

import logging
from anymail.exceptions import (
    AnymailAPIError,
    AnymailConfigurationError,
    AnymailError,
    AnymailInvalidAddress,
    AnymailRecipientsRefused,
)
from datetime import timedelta

from django.conf import settings
from django.core.mail import send_mail
from django.db import transaction
from django.template.loader import render_to_string
from django.utils import timezone

from .crypto import hash_value
from .exceptions import (
    DiscordDeliveryError,
    EmailAuthenticationError,
    EmailConfigurationError,
    EmailConnectionError,
    EmailDeliveryError,
    EmailRateLimitError,
    EmailRecipientError,
    StudentLinkAlreadyUsedError,
    TokenAlreadyUsedError,
    TokenExpiredError,
    WebhookDuplicateError,
)
from .models import Channel, Folder, LoginToken, SentMessage, StudentLink, Teacher
from .webhook import Webhook

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Auth services
# ---------------------------------------------------------------------------

def get_or_create_teacher(email: str) -> Teacher:
    """Return the Teacher for *email*, creating one if needed."""
    teacher, _ = Teacher.objects.get_or_create(email=email.lower())
    return teacher


def create_login_token(email: str) -> LoginToken:
    """Create a fresh magic-link token for *email*."""
    expiry = timezone.now() + timedelta(
        minutes=getattr(settings, 'LOGIN_TOKEN_EXPIRY_MINUTES', 15),
    )
    return LoginToken.objects.create(email=email.lower(), expires_at=expiry)



def send_magic_link_email(email: str, verify_url: str) -> None:
    """Send the magic-link email via the Brevo API (django-anymail).

    Raises:
        EmailConfigurationError:  BREVO_API_KEY missing / backend misconfigured.
        EmailAuthenticationError: Brevo rejected the API key (401/403).
        EmailRateLimitError:      Brevo rate limit / quota exceeded (429).
        EmailRecipientError:      Recipient address invalid or refused.
        EmailConnectionError:     Could not reach the Brevo API.
        EmailDeliveryError:       Any other Brevo API error.
    """
    # Derive base_url from the verify_url without coupling to URL structure.
    from urllib.parse import urlparse
    parsed = urlparse(verify_url)
    base_url = f"{parsed.scheme}://{parsed.netloc}"
    logo_url = f"{base_url}/static/broadcast/images/main_logo.png"

    expiry_minutes = getattr(settings, 'LOGIN_TOKEN_EXPIRY_MINUTES', 15)

    context = {
        'verify_url': verify_url,
        'logo_url': logo_url,
        'base_url': base_url,
    }

    text_content = (
        f"Hi,\n\nClick the link below to log in "
        f"(expires in {expiry_minutes} minutes):\n\n"
        f"{verify_url}\n\n"
        f"If you did not request this, ignore this email."
    )
    
    html_content = render_to_string('broadcast/email/magic_link.html', context)

    try:
        send_mail(
            subject='Your Teacher2Discord Login Link',
            message=text_content,
            html_message=html_content,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[email],
            fail_silently=False,
        )
        logger.info("Magic link sent via Brevo API to %s", email)
    except AnymailConfigurationError as exc:
        logger.error("Brevo backend misconfigured: %s", exc)
        raise EmailConfigurationError(str(exc)) from exc
    except (AnymailInvalidAddress, AnymailRecipientsRefused) as exc:
        logger.warning("Brevo refused recipient %s: %s", email, exc)
        raise EmailRecipientError(str(exc)) from exc
    except AnymailAPIError as exc:
        status = getattr(exc, 'status_code', None)
        logger.error("Brevo API error (status=%s) for %s: %s", status, email, exc)
        if status is None:
            # No HTTP response at all -> network/timeout/DNS failure.
            raise EmailConnectionError(str(exc)) from exc
        if status in (401, 403):
            raise EmailAuthenticationError(str(exc)) from exc
        if status == 429:
            raise EmailRateLimitError(str(exc)) from exc
        raise EmailDeliveryError(str(exc)) from exc
    except AnymailError as exc:
        logger.error("Anymail error for %s: %s", email, exc)
        raise EmailDeliveryError(str(exc)) from exc


def consume_login_token(login_token: LoginToken) -> None:
    """Mark *login_token* as used atomically.

    Raises:
        TokenExpiredError:    Token has passed its expiry time.
        TokenAlreadyUsedError: Token was already consumed.
    """
    if login_token.used:
        raise TokenAlreadyUsedError()
    if timezone.now() >= login_token.expires_at:
        raise TokenExpiredError()

    # Use atomic UPDATE to prevent double-use race conditions
    updated = LoginToken.objects.filter(pk=login_token.pk, used=False).update(used=True)
    if not updated:
        raise TokenAlreadyUsedError()
        
    login_token.used = True


def set_teacher_session(request, teacher: Teacher) -> None:
    """Persist teacher identity in the Django session.

    Cycles the session key first to prevent session-fixation attacks.
    """
    request.session.cycle_key()
    request.session['teacher_id'] = teacher.pk
    request.session.set_expiry(60 * 60 * 8)  # 8-hour session


# ---------------------------------------------------------------------------
# Folder services
# ---------------------------------------------------------------------------

def create_folder(teacher: Teacher, name: str, parent: Folder | None = None) -> Folder:
    """Create and return a new folder for *teacher*."""
    return Folder.objects.create(teacher=teacher, name=name, parent=parent)


def delete_folder(teacher: Teacher, folder_id: int) -> bool:
    """Delete a folder owned by *teacher*. Returns True if anything was deleted."""
    deleted, _ = Folder.objects.filter(pk=folder_id, teacher=teacher).delete()
    return deleted > 0


# ---------------------------------------------------------------------------
# Student-link services
# ---------------------------------------------------------------------------

def create_student_link(folder: Folder, channel_name: str) -> StudentLink:
    """Create a new student link inside *folder*."""
    return StudentLink.objects.create(folder=folder, channel_name=channel_name)


def delete_student_link(link: StudentLink) -> str:
    """Delete a student link and return its former channel name."""
    name = link.channel_name
    link.delete()
    return name


# ---------------------------------------------------------------------------
# Messaging services
# ---------------------------------------------------------------------------

def send_discord_message(channel: Channel, message_text: str, uploaded_file=None) -> None:
    """Send a message (with optional attachment) to *channel*'s webhook.

    On success a `SentMessage` record is persisted.

    Raises:
        DiscordDeliveryError: The webhook call failed.
    """
    payload = {'content': message_text or ''}
    discord_files = None

    if uploaded_file:
        discord_files = {
            'files[0]': (uploaded_file.name, uploaded_file, uploaded_file.content_type),
        }

    webhook_name = f"channel-{channel.pk}"
    with Webhook.from_url(channel.webhook_url, name=webhook_name) as wh:
        success = wh.send_message(payload, files=discord_files)

    if not success:
        raise DiscordDeliveryError()

    try:
        SentMessage.objects.create(
            channel=channel,
            content=payload.get('content', ''),
            attachment_name=uploaded_file.name if uploaded_file else '',
        )
    except Exception:
        # Message was delivered but history persistence failed — log and
        # continue so the user sees a success (the message *was* sent).
        logger.exception(
            "SentMessage persistence failed for channel %s after successful delivery",
            channel.pk,
        )


# ---------------------------------------------------------------------------
# Student-connect services
# ---------------------------------------------------------------------------

def check_webhook_duplicate(folder: Folder, webhook_url: str) -> None:
    """Raise if *webhook_url* is already connected inside *folder*.

    Uses the indexed hash field for efficient lookups on encrypted data.

    Raises:
        WebhookDuplicateError: Webhook already exists in this folder.
    """
    url_hash = hash_value(webhook_url)
    if Channel.objects.filter(
        student_link__folder=folder,
        webhook_url_hash=url_hash,
    ).exists():
        raise WebhookDuplicateError()


def connect_student_webhook(student_link: StudentLink, webhook_url: str) -> None:
    """Atomically attach a webhook to *student_link*.

    Raises:
        StudentLinkAlreadyUsedError: Link was already consumed.
    """
    with transaction.atomic():
        link = StudentLink.objects.select_for_update().get(pk=student_link.pk)
        if link.used:
            raise StudentLinkAlreadyUsedError()

        Channel.objects.create(student_link=link, webhook_url=webhook_url)
        link.used = True
        link.save(update_fields=['used'])
