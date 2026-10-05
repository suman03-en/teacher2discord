"""
Service layer for the broadcast app.

All business logic and database mutations live here so that views
remain thin request/response handlers.
"""

import logging
from anymail.exceptions import AnymailError, AnymailAPIError
from datetime import timedelta

from django.conf import settings
from django.core.mail import send_mail
from django.db import transaction
from django.utils import timezone

from .exceptions import (
    DiscordDeliveryError,
    EmailAuthenticationError,
    EmailConnectionError,
    EmailDeliveryError,
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


def create_login_token(teacher: Teacher) -> LoginToken:
    """Create a fresh magic-link token for *teacher*."""
    expiry = timezone.now() + timedelta(
        minutes=getattr(settings, 'LOGIN_TOKEN_EXPIRY_MINUTES', 15),
    )
    return LoginToken.objects.create(teacher=teacher, expires_at=expiry)


def send_magic_link_email(email: str, verify_url: str) -> None:
    """Send the magic-link email via Django's SMTP backend.

    Raises:
        EmailAuthenticationError: SMTP credentials rejected or IP not whitelisted.
        EmailConnectionError:     Cannot reach the SMTP server.
        EmailDeliveryError:       Server accepted connection but refused the message.
    """
    try:
        send_mail(
            subject='Your Teacher2Discord Login Link',
            message=(
                f'Hi,\n\nClick the link below to log in (expires in 15 minutes):\n\n'
                f'{verify_url}\n\n'
                f'If you did not request this, ignore this email.'
            ),
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[email],
            fail_silently=False,
        )
        logger.info("Magic link sent via SMTP to %s", email)
    except AnymailAPIError as exc:
        logger.error("Brevo API error for %s: %s", email, exc)
        raise EmailDeliveryError(str(exc)) from exc
    except AnymailError as exc:
        logger.error("Anymail error for %s: %s", email, exc)
        raise EmailConnectionError(str(exc)) from exc
    except ValueError as exc:
        logger.error("Invalid email configuration: %s", exc)
        raise EmailDeliveryError(str(exc)) from exc


def consume_login_token(login_token: LoginToken) -> None:
    """Mark *login_token* as used.

    Raises:
        TokenExpiredError:    Token has passed its expiry time.
        TokenAlreadyUsedError: Token was already consumed.
    """
    if login_token.used:
        raise TokenAlreadyUsedError()
    if timezone.now() >= login_token.expires_at:
        raise TokenExpiredError()

    login_token.used = True
    login_token.save(update_fields=['used'])


def set_teacher_session(request, teacher: Teacher) -> None:
    """Persist teacher identity in the Django session."""
    request.session['teacher_id'] = teacher.pk
    request.session.set_expiry(60 * 60 * 8)  # 8-hour session


# ---------------------------------------------------------------------------
# Folder services
# ---------------------------------------------------------------------------

def create_folder(teacher: Teacher, name: str, parent: Folder | None = None) -> Folder:
    """Create and return a new folder for *teacher*."""
    return Folder.objects.create(teacher=teacher, name=name, parent=parent)


def delete_folder(teacher: Teacher, folder_id) -> bool:
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
            'files[0]': (uploaded_file.name, uploaded_file.read(), uploaded_file.content_type),
        }

    with Webhook.from_url(channel.webhook_url) as wh:
        success = wh.send_message(payload, files=discord_files)

    if not success:
        raise DiscordDeliveryError()

    SentMessage.objects.create(
        channel=channel,
        content=payload.get('content', ''),
        attachment_name=uploaded_file.name if uploaded_file else '',
    )


# ---------------------------------------------------------------------------
# Student-connect services
# ---------------------------------------------------------------------------

def check_webhook_duplicate(folder: Folder, webhook_url: str) -> None:
    """Raise if *webhook_url* is already connected inside *folder*.

    Raises:
        WebhookDuplicateError: Webhook already exists in this folder.
    """
    if Channel.objects.filter(
        student_link__folder=folder,
        webhook_url=webhook_url,
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
