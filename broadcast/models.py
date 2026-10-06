import uuid

from django.db import models
from django.utils import timezone
from django.utils.text import slugify


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

    def is_leaf(self):
        return not self.children.exists()

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
    webhook_url = models.URLField()
    connected_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.student_link.channel_name} → {self.student_link.folder.name}"

class SentMessage(models.Model):
    channel = models.ForeignKey(Channel, on_delete=models.CASCADE, related_name='messages')
    content = models.TextField(blank=True)
    attachment_name = models.CharField(max_length=255, blank=True)
    sent_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-sent_at']

    def __str__(self):
        return f"To {self.channel}: {self.content[:20]}"
