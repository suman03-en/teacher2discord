"""
Rate-limiting decorators for the broadcast app.

All counters live in Django's cache (configured as a shared DatabaseCache
in settings) so limits are enforced across every gunicorn worker.
"""

import functools
import hashlib
import logging

from django.conf import settings
from django.contrib import messages
from django.core.cache import cache
from django.http import HttpResponseForbidden
from django.shortcuts import redirect

from .utils import get_client_ip

logger = logging.getLogger(__name__)


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


# ---------------------------------------------------------------------------
# Core counter logic
# ---------------------------------------------------------------------------

def _check_rules(request, rules):
    """Check every rule, and only if *all* pass increment their counters.

    *rules* is an iterable of ``(key_prefix, limit, period, key_func)``.
    Checking first and incrementing afterwards means a request blocked by
    one rule does not eat into the budget of the others (e.g. a blocked
    per-IP request doesn't consume the global quota).

    Returns the ``key_prefix`` of the rule that blocked, or ``None`` if allowed.
    """
    buckets = []
    for key_prefix, limit, period, key_func in rules:
        identity = key_func(request)
        if identity is None:
            continue
        cache_key = f"ratelimit_{key_prefix}_{identity}"
        if cache.get(cache_key, 0) >= limit:
            return key_prefix
        buckets.append((cache_key, period))

    for cache_key, period in buckets:
        # add() is atomic: only sets if the key doesn't exist yet.
        if not cache.add(cache_key, 1, timeout=period):
            try:
                cache.incr(cache_key)
            except ValueError:  # key expired between add() and incr()
                cache.set(cache_key, 1, timeout=period)
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
