"""
Rate-limiting and auth decorators for the broadcast app.

All counters live in the database (``RateLimit`` model) so limits are
enforced across every gunicorn worker.
"""

import functools
import hashlib
import logging
import random

from django.conf import settings
from django.contrib import messages
from django.core.cache import cache
from django.db import transaction
from django.http import HttpResponseForbidden
from django.shortcuts import redirect
from django.utils import timezone

from .models import RateLimit, Teacher
from .utils import get_client_ip

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Auth decorator (§2.1 — moved here from views.py)
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
# Key functions — map a request to the identity being limited
# ---------------------------------------------------------------------------

def ip_key(request):
    """Limit per client IP."""
    return get_client_ip(request) or 'unknown'


def email_key(request):
    """Limit per submitted email address (hashed to keep cache keys safe)."""
    email = (request.POST.get('email') or '').strip().lower()
    if not email:
        return None  # nothing to limit on — skip this rule
    return hashlib.sha256(email.encode()).hexdigest()


def global_key(request):
    """A single shared bucket for all requests."""
    return 'all'


def _check_rules(request, rules):
    """Check every rule, and only if *all* pass increment their counters.

    *rules* is an iterable of ``(key_prefix, limit, period, key_func)``.
    """
    now = timezone.now()
    
    # 1. Gather all keys for this request
    cache_keys = []
    for key_prefix, limit, period, key_func in rules:
        identity = key_func(request)
        if identity is None: continue
        cache_keys.append((f"rl_{key_prefix}_{identity}", limit, period, key_prefix))
        
    if not cache_keys: 
        return None

    # 2. Check limits and increment atomically
    keys = [k[0] for k in cache_keys]
    
    with transaction.atomic():
        # Fetch existing counters with lock to prevent TOCTOU
        existing = {
            rl.key: rl 
            for rl in RateLimit.objects.select_for_update().filter(key__in=keys)
        }
        
        # Check if ANY limit is exceeded
        for key, limit, period, prefix in cache_keys:
            rl = existing.get(key)
            if rl and rl.reset_at > now and rl.count >= limit:
                return prefix

        # If all clear, apply increments
        to_create = []
        to_update = []
        for key, limit, period, prefix in cache_keys:
            rl = existing.get(key)
            if rl:
                if rl.reset_at <= now:
                    rl.count = 1
                    rl.reset_at = now + timezone.timedelta(seconds=period)
                else:
                    rl.count += 1
                to_update.append(rl)
            else:
                to_create.append(RateLimit(
                    key=key, 
                    count=1, 
                    reset_at=now + timezone.timedelta(seconds=period)
                ))
                
        if to_update:
            RateLimit.objects.bulk_update(to_update, ['count', 'reset_at'])
        if to_create:
            RateLimit.objects.bulk_create(to_create)

    # 3. Occasional cleanup (1% chance)
    if random.random() < 0.01:
        RateLimit.objects.filter(reset_at__lt=now).delete()

    return None


# ---------------------------------------------------------------------------
# Decorators
# ---------------------------------------------------------------------------

def rate_limit(key_prefix, limit=5, period=60, post_only=True, key_func=ip_key):
    """Allow *limit* requests per *period* seconds per ``key_func(request)``.

    Defaults to IP-based limiting.
    """

    def decorator(view_func):
        @functools.wraps(view_func)
        def wrapped_view(request, *args, **kwargs):
            if post_only and request.method != 'POST':
                return view_func(request, *args, **kwargs)

            if _check_rules(request, [(key_prefix, limit, period, key_func)]):
                return HttpResponseForbidden(
                    "Rate limit exceeded. Please try again later."
                )

            return view_func(request, *args, **kwargs)

        return wrapped_view

    return decorator


def magic_link_rate_limit(view_func):
    """Layered limits for views that send magic-link emails.

    Protects both individual inboxes and the Brevo plan quota:

    * **Per email**  – cooldown + daily cap, stops one inbox being spammed.
    * **Per IP**     – hourly + daily cap, stops one client spraying addresses.
    * **Global**     – daily cap across everyone, so even a distributed
      attack can never exhaust the email plan.

    On limit, shows a warning message and redirects back to the form.
    Limits are configured via ``MAGIC_LINK_*`` settings.
    """
    hour, day = 60 * 60, 60 * 60 * 24

    @functools.wraps(view_func)
    def wrapped_view(request, *args, **kwargs):
        if request.method != 'POST':
            return view_func(request, *args, **kwargs)

        rules = [
            ('magic_email_cooldown', 1, settings.MAGIC_LINK_COOLDOWN_SECONDS, email_key),
            ('magic_email_hour', settings.MAGIC_LINK_PER_EMAIL_MAX_PER_HOUR, hour, email_key),
            ('magic_email_day', settings.MAGIC_LINK_PER_EMAIL_MAX_PER_DAY, day, email_key),
            ('magic_ip_hour', settings.MAGIC_LINK_PER_IP_MAX_PER_HOUR, hour, ip_key),
            ('magic_ip_day', settings.MAGIC_LINK_PER_IP_MAX_PER_DAY, day, ip_key),
            ('magic_global_day', settings.MAGIC_LINK_GLOBAL_MAX_PER_DAY, day, global_key),
        ]

        blocked = _check_rules(request, rules)
        if blocked:
            if blocked.startswith('magic_global'):
                logger.critical(
                    "GLOBAL magic-link daily cap (%s) reached — possible attack. ip=%s",
                    settings.MAGIC_LINK_GLOBAL_MAX_PER_DAY, ip_key(request),
                )
            else:
                logger.warning("Magic-link rate limit '%s' hit. ip=%s", blocked, ip_key(request))
            messages.warning(request, _MAGIC_LINK_MESSAGES[blocked.split('_')[1]])
            return redirect(request.path)

        return view_func(request, *args, **kwargs)

    return wrapped_view


_MAGIC_LINK_MESSAGES = {
    'email': "A login link was requested too recently for this email. Please wait a bit and try again.",
    'ip': "Too many login links have been requested from your network. Please try again later.",
    'global': "Login emails are temporarily unavailable due to high demand. Please try again later.",
}
