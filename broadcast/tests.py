"""
Tests for the broadcast app.

Covers services, decorators, crypto utilities, views, and models.
"""

import hashlib
import json
import os
import uuid
from datetime import timedelta
from unittest.mock import MagicMock, patch

from django.conf import settings
from django.contrib.auth.models import User
from django.core.cache import cache
from django.test import RequestFactory, TestCase, override_settings
from django.utils import timezone

from .crypto import _ENCRYPTED_PREFIX, decrypt_value, encrypt_value, hash_value
from .decorators import _check_rules, ip_key, teacher_required
from .exceptions import (
    StudentLinkAlreadyUsedError,
    TokenAlreadyUsedError,
    TokenExpiredError,
    WebhookDuplicateError,
)
from .models import (
    Channel,
    Folder,
    LoginToken,
    SentMessage,
    StudentLink,
    Teacher,
)
from .services import (
    check_webhook_duplicate,
    connect_student_webhook,
    consume_login_token,
    create_folder,
    create_login_token,
    delete_folder,
    delete_student_link,
    get_or_create_teacher,
    set_teacher_session,
)
from .utils import build_breadcrumbs

# ---------------------------------------------------------------------------
# Crypto tests
# ---------------------------------------------------------------------------


@override_settings(FIELD_ENCRYPTION_KEY="dGVzdC1rZXktMTIzNDU2Nzg5MDEyMzQ1Njc4OTAxMjM0")
class CryptoTests(TestCase):
    """Tests for broadcast.crypto encrypt/decrypt/hash utilities."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # Generate a valid Fernet key for tests
        import base64
        import secrets

        cls.fernet_key = base64.urlsafe_b64encode(secrets.token_bytes(32)).decode()

    @override_settings()
    def test_encrypt_decrypt_roundtrip(self):
        settings.FIELD_ENCRYPTION_KEY = self.fernet_key
        plaintext = "https://discord.com/api/webhooks/123/abc"
        encrypted = encrypt_value(plaintext)

        self.assertTrue(encrypted.startswith(_ENCRYPTED_PREFIX))
        self.assertNotEqual(encrypted, plaintext)

        decrypted = decrypt_value(encrypted)
        self.assertEqual(decrypted, plaintext)

    @override_settings()
    def test_encrypt_already_encrypted_is_idempotent(self):
        settings.FIELD_ENCRYPTION_KEY = self.fernet_key
        plaintext = "https://example.com"
        encrypted = encrypt_value(plaintext)
        double_encrypted = encrypt_value(encrypted)

        # Should not double-encrypt
        self.assertEqual(encrypted, double_encrypted)

    def test_decrypt_plaintext_returns_as_is(self):
        """Plaintext without the prefix should pass through unchanged."""
        plaintext = "https://discord.com/api/webhooks/123/abc"
        result = decrypt_value(plaintext)
        self.assertEqual(result, plaintext)

    def test_decrypt_empty_and_none(self):
        self.assertEqual(decrypt_value(""), "")
        self.assertIsNone(decrypt_value(None))

    def test_encrypt_empty_and_none(self):
        self.assertEqual(encrypt_value(""), "")
        self.assertIsNone(encrypt_value(None))

    def test_hash_value_deterministic(self):
        url = "https://discord.com/api/webhooks/123/abc"
        h1 = hash_value(url)
        h2 = hash_value(url)
        self.assertEqual(h1, h2)
        self.assertEqual(len(h1), 64)  # SHA-256 hex digest

    def test_hash_value_matches_sha256(self):
        url = "test-value"
        expected = hashlib.sha256(url.encode()).hexdigest()
        self.assertEqual(hash_value(url), expected)


# ---------------------------------------------------------------------------
# Model tests
# ---------------------------------------------------------------------------


class TeacherModelTests(TestCase):
    def test_str(self):
        teacher = Teacher.objects.create(email="test@school.com")
        self.assertEqual(str(teacher), "test@school.com")


class LoginTokenModelTests(TestCase):
    def test_is_valid_fresh_token(self):
        token = LoginToken.objects.create(
            email="t@s.com",
            expires_at=timezone.now() + timedelta(minutes=15),
        )
        self.assertTrue(token.is_valid())

    def test_is_valid_expired_token(self):
        token = LoginToken.objects.create(
            email="t@s.com",
            expires_at=timezone.now() - timedelta(minutes=1),
        )
        self.assertFalse(token.is_valid())

    def test_is_valid_used_token(self):
        token = LoginToken.objects.create(
            email="t@s.com",
            expires_at=timezone.now() + timedelta(minutes=15),
            used=True,
        )
        self.assertFalse(token.is_valid())


class FolderModelTests(TestCase):
    def setUp(self):
        self.teacher = Teacher.objects.create(email="t@s.com")

    def test_ordering(self):
        Folder.objects.create(teacher=self.teacher, name="Zebra")
        Folder.objects.create(teacher=self.teacher, name="Alpha")
        names = list(self.teacher.folders.values_list("name", flat=True))
        self.assertEqual(names, ["Alpha", "Zebra"])


class ChannelModelTests(TestCase):
    def setUp(self):
        self.teacher = Teacher.objects.create(email="t@s.com")
        self.folder = Folder.objects.create(teacher=self.teacher, name="F1")
        self.link = StudentLink.objects.create(folder=self.folder, channel_name="Ch1")

    @override_settings()
    def test_webhook_url_hash_auto_populated(self):
        import base64
        import secrets

        settings.FIELD_ENCRYPTION_KEY = base64.urlsafe_b64encode(
            secrets.token_bytes(32)
        ).decode()

        url = "https://discord.com/api/webhooks/123/abc-def"
        channel = Channel.objects.create(student_link=self.link, webhook_url=url)
        self.assertNotEqual(channel.webhook_url_hash, "")
        self.assertEqual(channel.webhook_url_hash, hash_value(url))


# ---------------------------------------------------------------------------
# Service tests
# ---------------------------------------------------------------------------


class AuthServiceTests(TestCase):
    def test_get_or_create_teacher_new(self):
        teacher = get_or_create_teacher("NEW@School.com")
        self.assertEqual(teacher.email, "new@school.com")

    def test_get_or_create_teacher_existing(self):
        Teacher.objects.create(email="existing@s.com")
        teacher = get_or_create_teacher("Existing@S.com")
        self.assertEqual(Teacher.objects.filter(email="existing@s.com").count(), 1)
        self.assertEqual(teacher.email, "existing@s.com")

    def test_create_login_token(self):
        token = create_login_token("t@s.com")
        self.assertEqual(token.email, "t@s.com")
        self.assertFalse(token.used)
        self.assertTrue(token.is_valid())

    def test_consume_login_token_success(self):
        token = LoginToken.objects.create(
            email="t@s.com",
            expires_at=timezone.now() + timedelta(minutes=15),
        )
        consume_login_token(token)
        self.assertTrue(token.used)

    def test_consume_expired_token_raises(self):
        token = LoginToken.objects.create(
            email="t@s.com",
            expires_at=timezone.now() - timedelta(minutes=1),
        )
        with self.assertRaises(TokenExpiredError):
            consume_login_token(token)

    def test_consume_used_token_raises(self):
        token = LoginToken.objects.create(
            email="t@s.com",
            expires_at=timezone.now() + timedelta(minutes=15),
            used=True,
        )
        with self.assertRaises(TokenAlreadyUsedError):
            consume_login_token(token)

    def test_set_teacher_session_cycles_key(self):
        teacher = Teacher.objects.create(email="t@s.com")
        factory = RequestFactory()
        request = factory.get("/")

        # Attach a mock session
        from django.contrib.sessions.backends.db import SessionStore

        request.session = SessionStore()
        request.session.create()
        old_key = request.session.session_key

        set_teacher_session(request, teacher)

        self.assertEqual(request.session["teacher_id"], teacher.pk)
        self.assertNotEqual(request.session.session_key, old_key)


class FolderServiceTests(TestCase):
    def setUp(self):
        self.teacher = Teacher.objects.create(email="t@s.com")

    def test_create_folder(self):
        folder = create_folder(self.teacher, "Grade 10")
        self.assertEqual(folder.name, "Grade 10")
        self.assertEqual(folder.teacher, self.teacher)
        self.assertIsNone(folder.parent)

    def test_create_subfolder(self):
        parent = create_folder(self.teacher, "Root")
        child = create_folder(self.teacher, "Child", parent=parent)
        self.assertEqual(child.parent, parent)

    def test_delete_folder(self):
        folder = create_folder(self.teacher, "Temp")
        self.assertTrue(delete_folder(self.teacher, folder.pk))
        self.assertFalse(Folder.objects.filter(pk=folder.pk).exists())

    def test_delete_folder_wrong_teacher(self):
        other = Teacher.objects.create(email="other@s.com")
        folder = create_folder(self.teacher, "Mine")
        self.assertFalse(delete_folder(other, folder.pk))
        self.assertTrue(Folder.objects.filter(pk=folder.pk).exists())


class StudentLinkServiceTests(TestCase):
    def setUp(self):
        self.teacher = Teacher.objects.create(email="t@s.com")
        self.folder = Folder.objects.create(teacher=self.teacher, name="F1")

    def test_delete_student_link(self):
        link = StudentLink.objects.create(folder=self.folder, channel_name="Ch1")
        name = delete_student_link(link)
        self.assertEqual(name, "Ch1")
        self.assertFalse(StudentLink.objects.filter(pk=link.pk).exists())


class WebhookDuplicateTests(TestCase):
    def setUp(self):
        self.teacher = Teacher.objects.create(email="t@s.com")
        self.folder = Folder.objects.create(teacher=self.teacher, name="F1")

    @override_settings()
    def test_check_webhook_duplicate_no_duplicate(self):
        import base64
        import secrets

        settings.FIELD_ENCRYPTION_KEY = base64.urlsafe_b64encode(
            secrets.token_bytes(32)
        ).decode()
        # Should not raise
        check_webhook_duplicate(self.folder, "https://discord.com/api/webhooks/999/new")

    @override_settings()
    def test_check_webhook_duplicate_raises(self):
        import base64
        import secrets

        settings.FIELD_ENCRYPTION_KEY = base64.urlsafe_b64encode(
            secrets.token_bytes(32)
        ).decode()

        link = StudentLink.objects.create(folder=self.folder, channel_name="Ch1")
        url = "https://discord.com/api/webhooks/123/existing"
        Channel.objects.create(student_link=link, webhook_url=url)

        with self.assertRaises(WebhookDuplicateError):
            check_webhook_duplicate(self.folder, url)


class ConnectStudentWebhookTests(TestCase):
    def setUp(self):
        self.teacher = Teacher.objects.create(email="t@s.com")
        self.folder = Folder.objects.create(teacher=self.teacher, name="F1")

    @override_settings()
    def test_connect_success(self):
        import base64
        import secrets

        settings.FIELD_ENCRYPTION_KEY = base64.urlsafe_b64encode(
            secrets.token_bytes(32)
        ).decode()

        link = StudentLink.objects.create(folder=self.folder, channel_name="Ch1")
        url = "https://discord.com/api/webhooks/123/test"
        connect_student_webhook(link, url)

        link.refresh_from_db()
        self.assertTrue(link.used)
        self.assertEqual(link.channels.count(), 1)

    @override_settings()
    def test_connect_already_used_raises(self):
        import base64
        import secrets

        settings.FIELD_ENCRYPTION_KEY = base64.urlsafe_b64encode(
            secrets.token_bytes(32)
        ).decode()

        link = StudentLink.objects.create(
            folder=self.folder, channel_name="Ch1", used=True
        )
        with self.assertRaises(StudentLinkAlreadyUsedError):
            connect_student_webhook(link, "https://discord.com/api/webhooks/123/test")


# ---------------------------------------------------------------------------
# Utility tests
# ---------------------------------------------------------------------------


class BreadcrumbTests(TestCase):
    def setUp(self):
        self.teacher = Teacher.objects.create(email="t@s.com")

    def test_root_folder_breadcrumbs(self):
        root = Folder.objects.create(teacher=self.teacher, name="Root")
        crumbs = build_breadcrumbs(root)
        self.assertEqual(len(crumbs), 1)
        self.assertEqual(crumbs[0], root)

    def test_nested_folder_breadcrumbs(self):
        root = Folder.objects.create(teacher=self.teacher, name="Root")
        child = Folder.objects.create(teacher=self.teacher, name="Child", parent=root)
        grandchild = Folder.objects.create(
            teacher=self.teacher, name="GChild", parent=child
        )

        crumbs = build_breadcrumbs(grandchild)
        self.assertEqual(len(crumbs), 3)
        self.assertEqual(crumbs[0].name, "Root")
        self.assertEqual(crumbs[1].name, "Child")
        self.assertEqual(crumbs[2].name, "GChild")


# ---------------------------------------------------------------------------
# Rate-limit decorator tests
# ---------------------------------------------------------------------------


class RateLimitTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()

    def test_check_rules_allows_under_limit(self):
        request = self.factory.post("/")
        request.META["REMOTE_ADDR"] = "127.0.0.1"
        result = _check_rules(request, [("test", 5, 60, ip_key)])
        self.assertIsNone(result)

    def test_check_rules_blocks_over_limit(self):
        request = self.factory.post("/")
        request.META["REMOTE_ADDR"] = "127.0.0.1"

        # Exhaust the limit
        for _ in range(5):
            _check_rules(request, [("test_block", 5, 60, ip_key)])

        # Next request should be blocked
        result = _check_rules(request, [("test_block", 5, 60, ip_key)])
        self.assertEqual(result, "test_block")

    def test_check_rules_resets_after_expiry(self):
        from django.core.cache import cache

        request = self.factory.post("/")
        request.META["REMOTE_ADDR"] = "127.0.0.1"

        # Exhaust the limit with a 1-second period
        for _ in range(3):
            _check_rules(request, [("test_reset", 3, 1, ip_key)])

        # Clear the expired counter
        cache.clear()

        # Should be allowed again
        result = _check_rules(request, [("test_reset", 3, 1, ip_key)])
        self.assertIsNone(result)


# ---------------------------------------------------------------------------
# View tests
# ---------------------------------------------------------------------------


class TeacherRequiredDecoratorTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.teacher = Teacher.objects.create(email="t@s.com")

    def test_redirects_without_session(self):
        @teacher_required
        def dummy_view(request):
            return "ok"

        request = self.factory.get("/")
        from django.contrib.sessions.backends.db import SessionStore

        request.session = SessionStore()

        response = dummy_view(request)
        self.assertEqual(response.status_code, 302)

    def test_sets_teacher_on_request(self):
        @teacher_required
        def dummy_view(request):
            return request.teacher

        request = self.factory.get("/")
        from django.contrib.sessions.backends.db import SessionStore

        request.session = SessionStore()
        request.session["teacher_id"] = self.teacher.pk
        request.session.save()

        result = dummy_view(request)
        self.assertEqual(result, self.teacher)


class AuthViewTests(TestCase):
    def test_home_view(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)

    def test_login_view_get(self):
        response = self.client.get("/login/")
        self.assertEqual(response.status_code, 200)

    def test_logout_requires_post(self):
        response = self.client.get("/auth/logout/")
        self.assertEqual(response.status_code, 405)

    def test_verify_nonexistent_token(self):
        fake_token = uuid.uuid4()
        response = self.client.get(f"/auth/verify/{fake_token}/")
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "broadcast/token_invalid.html")

    def test_verify_expired_token(self):
        token = LoginToken.objects.create(
            email="t@s.com",
            expires_at=timezone.now() - timedelta(minutes=1),
        )
        response = self.client.get(f"/auth/verify/{token.token}/")
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "broadcast/token_invalid.html")

    def test_verify_valid_token_logs_in(self):
        token = LoginToken.objects.create(
            email="t@s.com",
            expires_at=timezone.now() + timedelta(minutes=15),
        )
        response = self.client.get(f"/auth/verify/{token.token}/")
        self.assertEqual(response.status_code, 302)  # redirects to dashboard
        self.assertIn("teacher_id", self.client.session)


class DashboardViewTests(TestCase):
    def setUp(self):
        self.teacher = Teacher.objects.create(email="t@s.com")
        session = self.client.session
        session["teacher_id"] = self.teacher.pk
        session.save()

    def test_dashboard_requires_login(self):
        self.client.session.flush()
        response = self.client.get("/dashboard/")
        self.assertEqual(response.status_code, 302)

    def test_dashboard_get(self):
        response = self.client.get("/dashboard/")
        self.assertEqual(response.status_code, 200)

    def test_create_folder_via_post(self):
        response = self.client.post("/dashboard/", {"name": "Test Folder"})
        self.assertEqual(response.status_code, 302)
        self.assertTrue(
            Folder.objects.filter(teacher=self.teacher, name="Test Folder").exists()
        )

    def test_delete_folder_validates_target_id(self):
        response = self.client.post(
            "/dashboard/",
            {
                "action": "delete_folder",
                "target_id": "not-a-number",
            },
        )
        self.assertEqual(response.status_code, 302)  # redirects, no crash


# ---------------------------------------------------------------------------
# CSP middleware tests
# ---------------------------------------------------------------------------


class CSPMiddlewareTests(TestCase):
    def test_csp_header_present(self):
        response = self.client.get("/")
        self.assertIn("Content-Security-Policy", response)
        csp = response["Content-Security-Policy"]
        self.assertIn("default-src 'self'", csp)
        self.assertIn("frame-ancestors 'none'", csp)

    def test_csp_allows_cloudinary(self):
        response = self.client.get("/")
        csp = response["Content-Security-Policy"]
        self.assertIn("img-src 'self' data: https://res.cloudinary.com", csp)
        self.assertIn("media-src 'self' https://res.cloudinary.com", csp)


# ---------------------------------------------------------------------------
# Attachment preview & Cloudinary storage tests
# ---------------------------------------------------------------------------


class AttachmentModelTests(TestCase):
    def setUp(self):
        self.teacher = Teacher.objects.create(email="t@example.com")
        self.folder = Folder.objects.create(teacher=self.teacher, name="Math")
        self.student_link = StudentLink.objects.create(
            folder=self.folder,
            channel_name="General",
        )
        self.channel = Channel.objects.create(
            student_link=self.student_link,
            webhook_url="https://discord.com/api/webhooks/123/abc",
        )

    def test_sent_message_is_image(self):
        msg_png = SentMessage(channel=self.channel, attachment_name="photo.png")
        msg_jpg = SentMessage(channel=self.channel, attachment_name="photo.JPG")
        msg_webp = SentMessage(channel=self.channel, attachment_name="art.webp")
        msg_pdf = SentMessage(channel=self.channel, attachment_name="doc.pdf")
        msg_empty = SentMessage(channel=self.channel, attachment_name="")

        self.assertTrue(msg_png.is_image)
        self.assertTrue(msg_jpg.is_image)
        self.assertTrue(msg_webp.is_image)
        self.assertFalse(msg_pdf.is_image)
        self.assertFalse(msg_empty.is_image)

    def test_sent_message_is_video(self):
        msg_mp4 = SentMessage(channel=self.channel, attachment_name="clip.mp4")
        msg_webm = SentMessage(channel=self.channel, attachment_name="demo.WEBM")
        msg_png = SentMessage(channel=self.channel, attachment_name="photo.png")

        self.assertTrue(msg_mp4.is_video)
        self.assertTrue(msg_webm.is_video)
        self.assertFalse(msg_png.is_video)

    def test_sent_message_file_extension(self):
        msg = SentMessage(channel=self.channel, attachment_name="homework.Final.PDF")
        self.assertEqual(msg.file_extension, "pdf")

        msg_no_ext = SentMessage(channel=self.channel, attachment_name="noextension")
        self.assertEqual(msg_no_ext.file_extension, "")

    def test_adaptive_storage_resource_types(self):
        from broadcast.storage import AdaptiveCloudinaryStorage

        storage = AdaptiveCloudinaryStorage()
        self.assertEqual(storage._get_resource_type("photo.png"), "image")
        self.assertEqual(storage._get_resource_type("diagram.jpeg"), "image")
        self.assertEqual(storage._get_resource_type("clip.mp4"), "video")
        self.assertEqual(storage._get_resource_type("recording.webm"), "video")
        self.assertEqual(storage._get_resource_type("assignment.pdf"), "raw")
        self.assertEqual(storage._get_resource_type("archive.zip"), "raw")
        self.assertEqual(storage._get_resource_type("notes.docx"), "raw")
        # Extensionless Cloudinary public_id or multi-dot filename with format stripped
        self.assertEqual(
            storage._get_resource_type("media/attachments/2026/10/Screenshot_www.roblox.com_lzbiog"),
            "image",
        )
        self.assertEqual(storage._get_resource_type("media/attachments/noext"), "image")


@override_settings(
    STORAGES={
        "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
        "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
    }
)
class AttachmentTemplateTests(TestCase):
    def setUp(self):
        self.teacher = Teacher.objects.create(email="t2@example.com")
        self.folder = Folder.objects.create(teacher=self.teacher, name="History")
        self.student_link = StudentLink.objects.create(
            folder=self.folder,
            channel_name="Class 101",
        )
        self.channel = Channel.objects.create(
            student_link=self.student_link,
            webhook_url="https://discord.com/api/webhooks/456/def",
        )

    def test_render_image_preview(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        from django.template.loader import render_to_string

        msg = SentMessage.objects.create(
            channel=self.channel,
            content="Look at this picture",
            attachment_name="graph.png",
            attachment_file=SimpleUploadedFile("graph.png", b"fake-png", content_type="image/png"),
        )
        html = render_to_string(
            "broadcast/_message_items.html",
            {"page_obj": [msg], "link": self.student_link},
        )
        self.assertIn("attachment-image-frame", html)
        self.assertIn("openLightbox(this.src, this.alt)", html)
        self.assertIn("graph.png", html)

    def test_render_video_preview(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        from django.template.loader import render_to_string

        msg = SentMessage.objects.create(
            channel=self.channel,
            content="Class recording",
            attachment_name="lesson.mp4",
            attachment_file=SimpleUploadedFile("lesson.mp4", b"fake-mp4", content_type="video/mp4"),
        )
        html = render_to_string(
            "broadcast/_message_items.html",
            {"page_obj": [msg], "link": self.student_link},
        )
        self.assertIn("attachment-video-frame", html)
        self.assertIn("<video controls", html)

    def test_render_raw_file_card(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        from django.template.loader import render_to_string

        msg = SentMessage.objects.create(
            channel=self.channel,
            content="Assignment doc",
            attachment_name="hw1.pdf",
            attachment_file=SimpleUploadedFile("hw1.pdf", b"%PDF-1.4", content_type="application/pdf"),
        )
        html = render_to_string(
            "broadcast/_message_items.html",
            {"page_obj": [msg], "link": self.student_link},
        )
        self.assertIn("attachment-file-card", html)
        self.assertIn("file-download", html)
        self.assertIn("PDF", html)

    def test_render_legacy_message(self):
        from django.template.loader import render_to_string

        msg = SentMessage.objects.create(
            channel=self.channel,
            content="Legacy announcement",
            attachment_name="old_note.txt",
        )
        html = render_to_string(
            "broadcast/_message_items.html",
            {"page_obj": [msg], "link": self.student_link},
        )
        self.assertIn("attachment-file-card", html)
        self.assertNotIn("file-download", html)
        self.assertIn("old_note.txt", html)


@override_settings(
    STORAGES={
        "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
        "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
    }
)
class MessageAttachmentViewTests(TestCase):
    def setUp(self):
        from django.core.files.uploadedfile import SimpleUploadedFile

        self.teacher = Teacher.objects.create(email="owner@example.com")
        self.folder = Folder.objects.create(teacher=self.teacher, name="Math")
        self.student_link = StudentLink.objects.create(
            folder=self.folder, channel_name="General"
        )
        self.channel = Channel.objects.create(
            student_link=self.student_link,
            webhook_url="https://discord.com/api/webhooks/789/xyz",
        )
        self.msg = SentMessage.objects.create(
            channel=self.channel,
            content="Homework",
            attachment_name="syllabus.pdf",
            attachment_file=SimpleUploadedFile(
                "syllabus.pdf", b"%PDF-1.4 test data", content_type="application/pdf"
            ),
        )

    def test_message_attachment_requires_login(self):
        response = self.client.get(f"/messages/{self.msg.pk}/attachment/")
        self.assertEqual(response.status_code, 302)

    def test_message_attachment_serves_inline(self):
        session = self.client.session
        session["teacher_id"] = self.teacher.pk
        session.save()

        response = self.client.get(f"/messages/{self.msg.pk}/attachment/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/pdf")
        self.assertIn('inline; filename="syllabus.pdf"', response["Content-Disposition"])
        self.assertEqual(b"".join(response.streaming_content), b"%PDF-1.4 test data")

    def test_message_attachment_download_mode(self):
        session = self.client.session
        session["teacher_id"] = self.teacher.pk
        session.save()

        response = self.client.get(f"/messages/{self.msg.pk}/attachment/?download=1")
        self.assertEqual(response.status_code, 200)
        self.assertIn('attachment; filename="syllabus.pdf"', response["Content-Disposition"])

    def test_message_attachment_denies_other_teacher(self):
        other_teacher = Teacher.objects.create(email="other@example.com")
        session = self.client.session
        session["teacher_id"] = other_teacher.pk
        session.save()

        response = self.client.get(f"/messages/{self.msg.pk}/attachment/")
        self.assertEqual(response.status_code, 404)


# ---------------------------------------------------------------------------
# Analytics & Admin Dashboard Tests
# ---------------------------------------------------------------------------


class AnalyticsDashboardTests(TestCase):
    """Tests for broadcast.analytics and custom admin dashboard index."""

    def setUp(self):
        cache.clear()
        self.superuser = User.objects.create_superuser(
            username="admin",
            email="admin@example.com",
            password="adminpassword123",
        )

    def test_get_brevo_stats_unconfigured(self):
        from .analytics import get_brevo_stats

        with override_settings(ANYMAIL={}):
            stats = get_brevo_stats(force_refresh=True)
            self.assertFalse(stats["configured"])
            self.assertIn("error", stats)

    @patch("urllib.request.urlopen")
    def test_get_brevo_stats_success(self, mock_urlopen):
        from .analytics import get_brevo_stats

        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps({
            "email": "teacher@example.com",
            "plan": [{"type": "free", "credits": 250}],
        }).encode("utf-8")
        mock_response.__enter__.return_value = mock_response
        mock_urlopen.return_value = mock_response

        with override_settings(ANYMAIL={"BREVO_API_KEY": "dummy_key"}):
            stats = get_brevo_stats(force_refresh=True)
            self.assertTrue(stats["configured"])
            self.assertEqual(stats["credits_remaining"], 250)
            self.assertEqual(stats["credits_used"], 50)
            self.assertEqual(stats["credits_total"], 300)
            self.assertEqual(stats["email"], "teacher@example.com")

    def test_get_cloudinary_stats_unconfigured(self):
        from .analytics import get_cloudinary_stats

        with patch.dict(os.environ, {}, clear=True):
            stats = get_cloudinary_stats(force_refresh=True)
            self.assertFalse(stats["configured"])

    @patch("cloudinary.api.usage")
    def test_get_cloudinary_stats_success(self, mock_usage):
        from .analytics import get_cloudinary_stats

        mock_usage.return_value = {
            "plan": "Free",
            "resources": 12,
            "storage": {"usage": 5242880},  # 5 MB
            "bandwidth": {"usage": 1048576},  # 1 MB
            "credits": {"usage": 0.5, "limit": 25.0, "used_percent": 2.0},
        }
        with patch.dict(os.environ, {"CLOUDINARY_URL": "cloudinary://test"}):
            stats = get_cloudinary_stats(force_refresh=True)
            self.assertTrue(stats["configured"])
            self.assertEqual(stats["total_resources"], 12)
            self.assertEqual(stats["storage_mb"], 5.0)
            self.assertEqual(stats["bandwidth_mb"], 1.0)

    def test_get_system_analytics(self):
        from .analytics import get_system_analytics

        Teacher.objects.create(email="prof@example.com")
        create_login_token(email="prof@example.com")

        data = get_system_analytics(force_refresh=True)
        self.assertIn("email", data)
        self.assertIn("cloudinary", data)
        self.assertIn("users", data)
        self.assertEqual(data["users"]["admin_users"], 1)
        self.assertEqual(data["users"]["teachers"], 1)
        self.assertEqual(data["email"]["total_sent"], 1)

    def test_admin_dashboard_renders_for_superuser(self):
        self.client.force_login(self.superuser)
        response = self.client.get("/admin/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "System Quotas &amp; Activity Dashboard")
        self.assertContains(response, "Email &amp; Brevo Quota")
        self.assertContains(response, "Cloudinary Media")
        self.assertContains(response, "Users &amp; App Activity")
        self.assertContains(response, "/admin/models/")

    def test_admin_dashboard_refresh_param(self):
        self.client.force_login(self.superuser)
        response = self.client.get("/admin/?refresh=1")
        self.assertEqual(response.status_code, 200)

    def test_admin_models_view_renders_models(self):
        self.client.force_login(self.superuser)
        response = self.client.get("/admin/models/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Django Models &amp; Authentication Management")
        self.assertContains(response, "Back to System Dashboard")
        self.assertContains(response, "Authentication and Authorization")
        self.assertContains(response, "Broadcast")

    def test_admin_models_via_query_param(self):
        self.client.force_login(self.superuser)
        response = self.client.get("/admin/?view=models")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Django Models &amp; Authentication Management")
        self.assertContains(response, "Back to System Dashboard")





