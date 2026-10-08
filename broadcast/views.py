"""
Views for the broadcast app.

Each view is a thin request/response handler that delegates business
logic to ``services`` and uses helpers from ``utils``.
"""

import logging

from django.contrib import messages
from django.db.models import Count
from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from .decorators import magic_link_rate_limit, rate_limit, teacher_required
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
from .utils import BREADCRUMB_SELECT_RELATED, build_breadcrumbs, paginate_queryset

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_target_id(request):
    """Return ``target_id`` from POST as an int, or ``None`` if invalid."""
    raw = request.POST.get('target_id', '')
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Home & Auth views
# ---------------------------------------------------------------------------

def home_view(request):
    """Minimal landing page."""
    return render(request, 'broadcast/home.html')


@rate_limit(key_prefix='login_view', limit=5, period=60)
@magic_link_rate_limit
def login_view(request):
    """Step 1: Teacher enters their email."""
    if request.session.get('teacher_id'):
        return redirect('dashboard')

    form = EmailLoginForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        email = form.cleaned_data['email'].lower()
        token = create_login_token(email)
        verify_url = request.build_absolute_uri(
            reverse('verify_token', args=[token.token])
        )

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
    """Step 2: Teacher clicks the magic link.

    Returns the same error page for non-existent, expired, and used
    tokens to prevent information leakage about token existence.
    """
    try:
        login_token = LoginToken.objects.get(token=token)
    except LoginToken.DoesNotExist:
        return render(request, 'broadcast/token_invalid.html')

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
    if request.method == 'POST':
        action = request.POST.get('action')

        if action == 'delete_folder':
            target_id = _parse_target_id(request)
            if target_id is not None:
                delete_folder(request.teacher, target_id)
                messages.success(request, "Folder deleted successfully.")
            return redirect('dashboard')

        form = FolderForm(request.POST)
        if form.is_valid():
            create_folder(request.teacher, form.cleaned_data['name'])
            messages.success(request, f"Folder '{form.cleaned_data['name']}' created successfully.")
            return redirect('dashboard')
    else:
        form = FolderForm()

    root_folders = request.teacher.folders.filter(parent=None).annotate(children_count=Count('children'))

    return render(request, 'broadcast/dashboard.html', {
        'folders': root_folders,
        'form': form,
    })


@teacher_required
@rate_limit(key_prefix='folder_detail', limit=30, period=60, post_only=True)
def folder_detail(request, folder_id):
    """View a folder: shows subfolders, student links, channels, and forms."""
    folder = request.teacher.folders.select_related(
        BREADCRUMB_SELECT_RELATED,
    ).get(pk=folder_id)

    if request.method == 'POST':
        action = request.POST.get('action')

        if action == 'create_folder':
            folder_form = FolderForm(request.POST)
            if folder_form.is_valid():
                create_folder(request.teacher, folder_form.cleaned_data['name'], parent=folder)
                messages.success(request, f"Subfolder '{folder_form.cleaned_data['name']}' created successfully.")
                return redirect('folder_detail', folder_id=folder.pk)

        elif action == 'create_link':
            link_form = StudentLinkForm(request.POST)
            if link_form.is_valid():
                create_student_link(folder, link_form.cleaned_data['channel_name'])
                messages.success(request, f"Link '{link_form.cleaned_data['channel_name']}' created successfully.")
                return redirect('folder_detail', folder_id=folder.pk)

        elif action == 'delete_folder':
            target_id = _parse_target_id(request)
            if target_id is not None:
                delete_folder(request.teacher, target_id)
                messages.success(request, "Folder deleted successfully.")
            return redirect('folder_detail', folder_id=folder.pk)

    # Querysets only evaluated for GET (or invalid POST that falls through)
    subfolders = folder.children.all()
    student_links = folder.student_links.all()
    folder_form = FolderForm()
    link_form = StudentLinkForm()

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
    link = StudentLink.objects.select_related(
        f'folder__{BREADCRUMB_SELECT_RELATED}',
    ).prefetch_related('channels').get(
        pk=link_id, folder__teacher=request.teacher,
    )
    if slug != link.slug:
        return redirect('link_detail', link_id=link.pk, slug=link.slug)

    # Reuse prefetched channels throughout this view
    channels = list(link.channels.all())
    channel = channels[0] if channels else None

    send_form = SendMessageForm(request.POST or None, request.FILES or None)

    if request.method == 'POST':
        action = request.POST.get('action')

        if action == 'delete_link':
            folder_id = link.folder.pk
            name = delete_student_link(link)
            messages.success(request, f"Link '{name}' deleted successfully.")
            return redirect('folder_detail', folder_id=folder_id)

        if action == 'send_message' and send_form.is_valid():
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
    page_obj = None
    total_messages = 0
    if channel:
        msg_qs = channel.messages.all()
        page_obj = paginate_queryset(msg_qs, page_number=1)
        total_messages = page_obj.paginator.count

    return render(request, 'broadcast/link_detail.html', {
        'link': link,
        'send_form': send_form,
        'breadcrumbs': build_breadcrumbs(link.folder),
        'channel': channel,
        'page_obj': page_obj,
        'total_messages': total_messages,
    })


@teacher_required
@rate_limit(key_prefix='link_messages', limit=60, period=60, post_only=False)
def link_messages(request, link_id):
    """Returns paginated message items as HTML fragments for AJAX loading."""
    link = StudentLink.objects.select_related('folder').get(
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
    try:
        student_link = StudentLink.objects.select_related('folder').get(
            token=token, used=False,
        )
    except StudentLink.DoesNotExist:
        from django.http import Http404
        raise Http404

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
