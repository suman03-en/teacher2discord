from django.contrib import admin

from .models import Channel, Folder, LoginToken, SentMessage, StudentLink, Teacher


@admin.register(Teacher)
class TeacherAdmin(admin.ModelAdmin):
    list_display = ('email', 'created_at')
    search_fields = ('email',)
    readonly_fields = ('created_at',)


@admin.register(LoginToken)
class LoginTokenAdmin(admin.ModelAdmin):
    list_display = ('teacher', 'token', 'created_at', 'expires_at', 'used')
    list_filter = ('used',)
    search_fields = ('teacher__email',)
    readonly_fields = ('token', 'created_at')


@admin.register(Folder)
class FolderAdmin(admin.ModelAdmin):
    list_display = ('name', 'teacher', 'parent', 'created_at')
    list_filter = ('teacher',)
    search_fields = ('name', 'teacher__email')
    readonly_fields = ('created_at',)


@admin.register(StudentLink)
class StudentLinkAdmin(admin.ModelAdmin):
    list_display = ('channel_name', 'folder', 'used', 'created_at')
    list_filter = ('used',)
    search_fields = ('channel_name', 'folder__name')
    readonly_fields = ('token', 'created_at')


@admin.register(Channel)
class ChannelAdmin(admin.ModelAdmin):
    list_display = ('student_link', 'connected_at')
    search_fields = ('student_link__channel_name',)
    readonly_fields = ('connected_at',)


@admin.register(SentMessage)
class SentMessageAdmin(admin.ModelAdmin):
    list_display = ('channel', 'content_preview', 'attachment_name', 'sent_at')
    search_fields = ('content', 'channel__student_link__channel_name')
    readonly_fields = ('sent_at',)

    @admin.display(description='Content')
    def content_preview(self, obj):
        return obj.content[:60] + '…' if len(obj.content) > 60 else obj.content
