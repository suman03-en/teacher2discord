import os

from django import forms
from django.conf import settings
from django.core.validators import RegexValidator

from .webhook import Webhook


class EmailLoginForm(forms.Form):
    email = forms.EmailField(
        label="Your Email",
        widget=forms.EmailInput(attrs={'placeholder': 'teacher@school.com', 'autofocus': True})
    )


class FolderForm(forms.Form):
    name = forms.CharField(
        max_length=255,
        label="Folder Name",
        widget=forms.TextInput(attrs={'placeholder': 'e.g. Grade 10 Physics'})
    )


class StudentLinkForm(forms.Form):
    channel_name = forms.CharField(
        max_length=255,
        label="Channel Name",
        widget=forms.TextInput(attrs={'placeholder': 'e.g. Grade 10 - Physics'})
    )


class StudentConnectForm(forms.Form):
    webhook_url = forms.URLField(
        label="Your Discord Webhook URL",
        widget=forms.URLInput(attrs={'placeholder': 'https://discord.com/api/webhooks/...'}),
        validators=[
            RegexValidator(
                regex=r'^https://(discord|discordapp)\.com/api/webhooks/\d+/[A-Za-z0-9_-]+',
                message='Please enter a valid Discord webhook URL (must start with https://discord.com/api/webhooks/...)'
            )
        ]
    )

    def clean_webhook_url(self):
        url = self.cleaned_data['webhook_url']
        with Webhook.from_url(url) as wh:
            if not wh.ping():
                raise forms.ValidationError("Could not verify this webhook. Please make sure the URL is correct and active.")
        return url


class SendMessageForm(forms.Form):
    message = forms.CharField(
        label="Message",
        required=False,
        widget=forms.Textarea(attrs={'placeholder': 'Type your announcement...', 'rows': 3})
    )
    attachment = forms.FileField(
        label="Attachment",
        required=False,
    )

    def clean_attachment(self):
        attachment = self.cleaned_data.get('attachment')
        if attachment:
            max_size = getattr(settings, 'MAX_ATTACHMENT_SIZE', 10 * 1024 * 1024)
            if attachment.size > max_size:
                size_mb = max_size // (1024 * 1024)
                raise forms.ValidationError(f"File size must be under {size_mb}MB.")

            # Validate file extension against allowlist
            allowed_extensions = getattr(settings, 'ALLOWED_ATTACHMENT_EXTENSIONS', None)
            if allowed_extensions:
                ext = os.path.splitext(attachment.name)[1].lower()
                if ext not in allowed_extensions:
                    raise forms.ValidationError(
                        f"File type '{ext}' is not allowed. "
                        f"Allowed types: {', '.join(allowed_extensions)}"
                    )
        return attachment

    def clean(self):
        cleaned = super().clean()
        if not cleaned.get('message') and not cleaned.get('attachment'):
            raise forms.ValidationError("Please enter a message or attach a file.")
        return cleaned