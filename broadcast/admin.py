from datetime import timedelta
from django.contrib import admin
from django.db.models import Q
from django.utils import timezone

from .models import Channel, Folder, LoginToken, RateLimit, SentMessage, StudentLink, Teacher


@admin.register(Teacher)
class TeacherAdmin(admin.ModelAdmin):
    list_display = ('email', 'created_at')
    search_fields = ('email',)
    readonly_fields = ('created_at',)
    show_full_result_count = False


@admin.register(LoginToken)
class LoginTokenAdmin(admin.ModelAdmin):
    list_display = ('email', 'token', 'created_at', 'expires_at', 'used')
    list_filter = ('used',)
    search_fields = ('email',)
    readonly_fields = ('token', 'created_at')
    show_full_result_count = False

    def get_urls(self):
        from django.urls import path
        urls = super().get_urls()
        custom_urls = [
            path('cleanup-stale/', self.admin_site.admin_view(self.cleanup_stale_view), name='logintoken-cleanup'),
        ]
        return custom_urls + urls

    def cleanup_stale_view(self, request):
        from django.shortcuts import redirect
        stale = LoginToken.objects.filter(Q(used=True) | Q(expires_at__lt=timezone.now()))
        count, _ = stale.delete()
        self.message_user(request, f"Successfully deleted {count} stale login tokens.")
        return redirect('..')


@admin.register(Folder)
class FolderAdmin(admin.ModelAdmin):
    list_display = ('name', 'teacher', 'parent', 'created_at')
    list_filter = ('teacher',)
    search_fields = ('name', 'teacher__email')
    readonly_fields = ('created_at',)
    show_full_result_count = False


@admin.register(StudentLink)
class StudentLinkAdmin(admin.ModelAdmin):
    list_display = ('channel_name', 'folder', 'used', 'created_at')
    list_filter = ('used',)
    search_fields = ('channel_name', 'folder__name')
    readonly_fields = ('token', 'created_at')
    show_full_result_count = False

    def get_urls(self):
        from django.urls import path
        urls = super().get_urls()
        custom_urls = [
            path('cleanup-stale/', self.admin_site.admin_view(self.cleanup_stale_view), name='studentlink-cleanup'),
        ]
        return custom_urls + urls

    def cleanup_stale_view(self, request):
        from django.shortcuts import redirect
        threshold = timezone.now() - timedelta(days=30)
        stale = StudentLink.objects.filter(used=False, created_at__lt=threshold)
        count, _ = stale.delete()
        self.message_user(request, f"Successfully deleted {count} stale student links.")
        return redirect('..')

    def get_queryset(self, request):
        return super().get_queryset(request).select_related('folder')


@admin.register(Channel)
class ChannelAdmin(admin.ModelAdmin):
    list_display = ('student_link', 'connected_at')
    search_fields = ('student_link__channel_name',)
    readonly_fields = ('connected_at', 'webhook_url_hash')
    exclude = ('webhook_url',)  # Don't display decrypted webhook in admin
    show_full_result_count = False

    def get_queryset(self, request):
        """Prefetch related objects to avoid N+1 in list_display."""
        return (
            super()
            .get_queryset(request)
            .select_related('student_link', 'student_link__folder')
        )


@admin.register(SentMessage)
class SentMessageAdmin(admin.ModelAdmin):
    list_display = ('channel', 'content_preview', 'attachment_name', 'sent_at')
    search_fields = ('content', 'channel__student_link__channel_name')
    readonly_fields = ('sent_at',)
    show_full_result_count = False

    def get_queryset(self, request):
        """Prefetch related objects to avoid N+1 in list_display and __str__."""
        return (
            super()
            .get_queryset(request)
            .select_related('channel', 'channel__student_link')
        )

    @admin.display(description='Content')
    def content_preview(self, obj):
        return obj.content[:60] + '…' if len(obj.content) > 60 else obj.content


@admin.register(RateLimit)
class RateLimitAdmin(admin.ModelAdmin):
    """Expose rate-limit records for debugging and manual cleanup."""
    list_display = ('key', 'count', 'reset_at')
    search_fields = ('key',)
    list_filter = ('reset_at',)
    readonly_fields = ('key',)
    show_full_result_count = False
