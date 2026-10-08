import uuid

from django.db import models
from django.utils import timezone
from django.utils.text import slugify

from .fields import EncryptedTextField


class RateLimit(models.Model):
    key = models.CharField(max_length=255, unique=True, db_index=True)
    count = models.IntegerField(default=0)
    reset_at = models.DateTimeField()

    def __str__(self):
        return f"{self.key} ({self.count})"



class Teacher(models.Model):
    email = models.EmailField(unique=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.email


class LoginToken(models.Model):
    email = models.EmailField()
    token = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    used = models.BooleanField(default=False)

    class Meta:
        indexes = [
            models.Index(fields=['email']),
            models.Index(fields=['expires_at', 'used']),
        ]

    def is_valid(self):
        return not self.used and timezone.now() < self.expires_at

    def __str__(self):
        return f"Token for {self.email}"


class Folder(models.Model):
    teacher = models.ForeignKey(Teacher, on_delete=models.CASCADE, related_name='folders')
    name = models.CharField(max_length=255)
    parent = models.ForeignKey(
        'self', null=True, blank=True,
        on_delete=models.CASCADE, related_name='children'
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name


class StudentLink(models.Model):
    folder = models.ForeignKey(Folder, on_delete=models.CASCADE, related_name='student_links')
    token = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    channel_name = models.CharField(max_length=255)
    created_at = models.DateTimeField(auto_now_add=True)
    used = models.BooleanField(default=False)

    @property
    def slug(self):
        return slugify(self.channel_name) or "link"

    def __str__(self):
        return self.channel_name


class Channel(models.Model):
    student_link = models.ForeignKey(StudentLink, on_delete=models.CASCADE, related_name='channels')
    webhook_url = EncryptedTextField()
    webhook_url_hash = models.CharField(
        max_length=64,
        db_index=True,
        blank=True,
        default='',
        help_text='SHA-256 hash for indexed duplicate lookups.',
    )
    connected_at = models.DateTimeField(auto_now_add=True)

    def save(self, **kwargs):
        # Auto-populate the hash whenever webhook_url is set.
        if self.webhook_url:
            from .crypto import hash_value
            self.webhook_url_hash = hash_value(self.webhook_url)
        super().save(**kwargs)

    def __str__(self):
        return f"Channel #{self.pk}"


class SentMessage(models.Model):
    channel = models.ForeignKey(Channel, on_delete=models.CASCADE, related_name='messages')
    content = models.TextField(blank=True)
    attachment_name = models.CharField(max_length=255, blank=True)
    sent_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-sent_at']
        indexes = [
            models.Index(fields=['channel', '-sent_at']),
        ]

    def __str__(self):
        return f"To {self.channel}: {self.content[:20]}"
