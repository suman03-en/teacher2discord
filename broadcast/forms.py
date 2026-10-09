import os

from django import forms
from django.conf import settings
from django.core.validators import RegexValidator

from .webhook import Webhook

# File signatures (magic bytes) for content-type verification.
# Maps expected extensions to their known file signatures.
_MAGIC_SIGNATURES = {
    b"\x89PNG": {".png"},
    b"\xff\xd8\xff": {".jpg", ".jpeg"},
    b"GIF87a": {".gif"},
    b"GIF89a": {".gif"},
    b"RIFF": {".webm", ".wav"},  # WAV and WebM both use RIFF container
    b"%PDF": {".pdf"},
    b"PK": {".zip", ".docx", ".xlsx", ".pptx", ".doc"},
    b"\x1f\x8b": {".gz"},
    b"Rar": {".rar"},
    b"7z": {".7z"},
    b"\xff\xfb": {".mp3"},
    b"\xff\xf3": {".mp3"},
    b"\xff\xf2": {".mp3"},
    b"ID3": {".mp3"},
    b"\x00\x00\x00": {".mp4"},  # ftyp box starts after size bytes
}


def _check_file_signature(uploaded_file, extension):
    """Return True if the file's magic bytes are consistent with *extension*.

    Returns True (passes) when:
    - the extension is not in our signature database (we can't verify it), or
    - the file's leading bytes match a known signature for that extension.
    """
    # Read the first 12 bytes (enough for all our signatures).
    pos = uploaded_file.tell()
    header = uploaded_file.read(12)
    uploaded_file.seek(pos)

    if not header:
        return True  # empty file — let other validation handle it

    # Check whether any known signature matches this header AND includes
    # the file's claimed extension.
    for sig, exts in _MAGIC_SIGNATURES.items():
        if header[: len(sig)] == sig:
            # We found a matching signature — does it agree with the extension?
            if extension in exts:
                return True
            # Signature matches a different file type → suspicious
            return False

    # No signature matched — we can't verify, so allow it.
    return True


class EmailLoginForm(forms.Form):
    email = forms.EmailField(
        label="Your Email",
        widget=forms.EmailInput(
            attrs={"placeholder": "teacher@school.com", "autofocus": True}
        ),
    )


class FolderForm(forms.Form):
    name = forms.CharField(
        max_length=255,
        label="Folder Name",
        widget=forms.TextInput(attrs={"placeholder": "e.g. Grade 10 Physics"}),
    )


class StudentLinkForm(forms.Form):
    channel_name = forms.CharField(
        max_length=255,
        label="Channel Name",
        widget=forms.TextInput(attrs={"placeholder": "e.g. Grade 10 - Physics"}),
    )


class StudentConnectForm(forms.Form):
    webhook_url = forms.URLField(
        label="Your Discord Webhook URL",
        widget=forms.URLInput(
            attrs={"placeholder": "https://discord.com/api/webhooks/..."}
        ),
        validators=[
            RegexValidator(
                regex=r"^https://(discord|discordapp)\.com/api/webhooks/\d+/[A-Za-z0-9_-]+",
                message="Please enter a valid Discord webhook URL (must start with https://discord.com/api/webhooks/...)",
            )
        ],
    )

    def clean_webhook_url(self):
        url = self.cleaned_data["webhook_url"]
        with Webhook.from_url(url, name="validation-ping") as wh:
            if not wh.ping():
                raise forms.ValidationError(
                    "Could not verify this webhook. Please make sure the URL is correct and active."
                )
        return url


class SendMessageForm(forms.Form):
    message = forms.CharField(
        label="Message",
        required=False,
        widget=forms.Textarea(
            attrs={"placeholder": "Type your announcement...", "rows": 3}
        ),
    )
    attachment = forms.FileField(
        label="Attachment",
        required=False,
    )

    def clean_attachment(self):
        attachment = self.cleaned_data.get("attachment")
        if attachment:
            max_size = getattr(settings, "MAX_ATTACHMENT_SIZE", 10 * 1024 * 1024)
            if attachment.size > max_size:
                size_mb = max_size // (1024 * 1024)
                raise forms.ValidationError(f"File size must be under {size_mb}MB.")

            # Validate file extension against allowlist
            allowed_extensions = getattr(
                settings, "ALLOWED_ATTACHMENT_EXTENSIONS", None
            )
            ext = os.path.splitext(attachment.name)[1].lower()
            if allowed_extensions:
                if ext not in allowed_extensions:
                    raise forms.ValidationError(
                        f"File type '{ext}' is not allowed. "
                        f"Allowed types: {', '.join(allowed_extensions)}"
                    )

            # Verify file content matches claimed extension (magic bytes)
            if not _check_file_signature(attachment, ext):
                raise forms.ValidationError(
                    "The file content does not match its extension. "
                    "Please upload a valid file."
                )
        return attachment

    def clean(self):
        cleaned = super().clean()
        if not cleaned.get("message") and not cleaned.get("attachment"):
            raise forms.ValidationError("Please enter a message or attach a file.")
        return cleaned
