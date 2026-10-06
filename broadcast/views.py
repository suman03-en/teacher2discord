"""
Views for the broadcast app.

Each view is a thin request/response handler that delegates business
logic to ``services`` and uses helpers from ``utils``.
"""

import functools
import logging

from django.contrib import messages
from django.db.models import Count
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from .decorators import rate_limit
from .exceptions import (
    DiscordDeliveryError,
    EmailError,
    StudentLinkAlreadyUsedError,
    TokenError,
    WebhookDuplicateError,
)
from .forms import (
    EmailLoginForm,
    FolderForm,
    SendMessageForm,
    StudentConnectForm,
    StudentLinkForm,
)
from .models import LoginToken, StudentLink, Teacher
from .services import (
    check_webhook_duplicate,
    connect_student_webhook,
    consume_login_token,
    create_folder,
    create_login_token,
    create_student_link,
    delete_folder,
    delete_student_link,
    get_or_create_teacher,
    send_discord_message,
    send_magic_link_email,
    set_teacher_session,
)
from .utils import build_breadcrumbs, paginate_queryset

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Auth helpers
# ---------------------------------------------------------------------------

def teacher_required(view_fn):
    """Decorator: ensures a teacher is logged in via session."""
    @functools.wraps(view_fn)
    def wrapper(request, *args, **kwargs):
        teacher_id = request.session.get('teacher_id')
        if not teacher_id:
            return redirect('login')
        try:
            request.teacher = Teacher.objects.get(pk=teacher_id)
        except Teacher.DoesNotExist:
            del request.session['teacher_id']
            return redirect('login')
        return view_fn(request, *args, **kwargs)
    return wrapper


# ---------------------------------------------------------------------------
# Home & Auth views
# ---------------------------------------------------------------------------

def home_view(request):
    """Minimal landing page."""
    return render(request, 'broadcast/home.html')


@rate_limit(key_prefix='login_view', limit=5, period=60)
def login_view(request):
    """Step 1: Teacher enters their email."""
    if request.session.get('teacher_id'):
        return redirect('dashboard')

    form = EmailLoginForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        email = form.cleaned_data['email'].lower()
        token = create_login_token(email)
        verify_url = request.build_absolute_uri(f'/auth/verify/{token.token}/')

        try:
            send_magic_link_email(email, verify_url)
        except EmailError as exc:
            logger.exception("Email delivery failed for %s", email)
            messages.error(request, exc.user_message)
            return render(request, 'broadcast/login.html', {'form': form})

        return render(request, 'broadcast/login_sent.html', {'email': email})

    return render(request, 'broadcast/login.html', {'form': form})


@rate_limit(key_prefix='verify_token', limit=10, period=60, post_only=False)
def verify_token(request, token):
    """Step 2: Teacher clicks the magic link."""
    login_token = get_object_or_404(LoginToken, token=token)

    try:
        consume_login_token(login_token)
    except TokenError:
        return render(request, 'broadcast/token_invalid.html')

    teacher = get_or_create_teacher(login_token.email)
    set_teacher_session(request, teacher)
    messages.success(request, "Successfully logged in!")
    return redirect('dashboard')


@require_POST
def logout_view(request):
    """Logout must be POST to prevent CSRF-based forced logouts."""
    request.session.flush()
    messages.info(request, "You have been logged out.")
    return redirect('login')


# ---------------------------------------------------------------------------
# Dashboard & Folders
# ---------------------------------------------------------------------------

@teacher_required
@rate_limit(key_prefix='dashboard', limit=30, period=60, post_only=True)
def dashboard(request):
    """Root-level folders for the logged-in teacher."""
    root_folders = request.teacher.folders.filter(parent=None).annotate(children_count=Count('children'))
    form = FolderForm(request.POST or None)

    if request.method == 'POST':
        action = request.POST.get('action')

        if action == 'delete_folder':
            delete_folder(request.teacher, request.POST.get('target_id'))
            messages.success(request, "Folder deleted successfully.")
            return redirect('dashboard')

        if form.is_valid():
            create_folder(request.teacher, form.cleaned_data['name'])
            messages.success(request, f"Folder '{form.cleaned_data['name']}' created successfully.")
            return redirect('dashboard')

    return render(request, 'broadcast/dashboard.html', {
        'folders': root_folders,
        'form': form,
    })


@teacher_required
@rate_limit(key_prefix='folder_detail', limit=30, period=60, post_only=True)
def folder_detail(request, folder_id):
    """View a folder: shows subfolders, student links, channels, and forms."""
    folder = get_object_or_404(request.teacher.folders, pk=folder_id)
    subfolders = folder.children.all()
    student_links = folder.student_links.all()

    folder_form = FolderForm(request.POST if request.POST.get('action') == 'create_folder' else None)
    link_form = StudentLinkForm(request.POST if request.POST.get('action') == 'create_link' else None)

    if request.method == 'POST':
        action = request.POST.get('action')

        if action == 'create_folder' and folder_form.is_valid():
            create_folder(request.teacher, folder_form.cleaned_data['name'], parent=folder)
            messages.success(request, f"Subfolder '{folder_form.cleaned_data['name']}' created successfully.")
            return redirect('folder_detail', folder_id=folder.pk)

        if action == 'create_link' and link_form.is_valid():
            create_student_link(folder, link_form.cleaned_data['channel_name'])
            messages.success(request, f"Link '{link_form.cleaned_data['channel_name']}' created successfully.")
            return redirect('folder_detail', folder_id=folder.pk)

        if action == 'delete_folder':
            delete_folder(request.teacher, request.POST.get('target_id'))
            messages.success(request, "Folder deleted successfully.")
            return redirect('folder_detail', folder_id=folder.pk)

    return render(request, 'broadcast/folder_detail.html', {
        'folder': folder,
        'subfolders': subfolders,
        'student_links': student_links,
        'folder_form': folder_form,
        'link_form': link_form,
        'breadcrumbs': build_breadcrumbs(folder),
    })


@teacher_required
@rate_limit(key_prefix='link_detail', limit=20, period=60, post_only=True)
def link_detail(request, link_id, slug=None):
    """View a single student link — send messages, see history."""
    link = get_object_or_404(
        StudentLink.objects.select_related('folder').prefetch_related('channels'),
        pk=link_id, folder__teacher=request.teacher,
    )
    if slug != link.slug:
        return redirect('link_detail', link_id=link.pk, slug=link.slug)

    send_form = SendMessageForm(request.POST or None, request.FILES or None)

    if request.method == 'POST':
        action = request.POST.get('action')

        if action == 'delete_link':
            folder_id = link.folder.pk
            name = delete_student_link(link)
            messages.success(request, f"Link '{name}' deleted successfully.")
            return redirect('folder_detail', folder_id=folder_id)

        if action == 'send_message' and send_form.is_valid():
            channel = link.channels.first()
            if channel:
                try:
                    send_discord_message(
                        channel,
                        send_form.cleaned_data.get('message', ''),
                        send_form.cleaned_data.get('attachment'),
                    )
                    messages.success(request, "Message sent successfully!")
                except DiscordDeliveryError as exc:
                    messages.error(request, exc.user_message)
            return redirect('link_detail', link_id=link.pk, slug=link.slug)

    # Pagination
    channel = link.channels.first()
    page_obj = None
    total_messages = 0
    if channel:
        msg_qs = channel.messages.all()
        total_messages = msg_qs.count()
        page_obj = paginate_queryset(msg_qs, page_number=1)

    return render(request, 'broadcast/link_detail.html', {
        'link': link,
        'send_form': send_form,
        'breadcrumbs': build_breadcrumbs(link.folder),
        'channel': channel,
        'page_obj': page_obj,
        'total_messages': total_messages,
    })


@teacher_required
def link_messages(request, link_id):
    """Returns paginated message items as HTML fragments for AJAX loading."""
    link = get_object_or_404(
        StudentLink.objects.select_related('folder'),
        pk=link_id, folder__teacher=request.teacher,
    )
    channel = link.channels.first()
    if not channel:
        return HttpResponse('')

    page_obj = paginate_queryset(
        channel.messages.all(),
        page_number=request.GET.get('page', 1),
    )
    return render(request, 'broadcast/_message_items.html', {
        'page_obj': page_obj,
        'link': link,
    })


# ---------------------------------------------------------------------------
# Student views (no auth required)
# ---------------------------------------------------------------------------

@rate_limit(key_prefix='student_connect', limit=5, period=60)
def student_connect(request, token):
    """Student lands here via magic link. One-time use — raises 404 if already used."""
    student_link = get_object_or_404(
        StudentLink.objects.select_related('folder'),
        token=token, used=False,
    )

    form = StudentConnectForm(request.POST or None)

    if request.method == 'POST' and form.is_valid():
        webhook_url = form.cleaned_data['webhook_url']

        try:
            check_webhook_duplicate(student_link.folder, webhook_url)
        except WebhookDuplicateError as exc:
            form.add_error('webhook_url', exc.user_message)
            return render(request, 'broadcast/student_connect.html', {
                'student_link': student_link,
                'form': form,
            })

        try:
            connect_student_webhook(student_link, webhook_url)
        except StudentLinkAlreadyUsedError:
            return render(request, 'broadcast/student_link_used.html')

        return render(request, 'broadcast/student_done.html', {
            'student_link': student_link,
        })

    return render(request, 'broadcast/student_connect.html', {
        'student_link': student_link,
        'form': form,
    })
