import functools

from django.core.cache import cache
from django.http import HttpResponseForbidden

from .utils import get_client_ip


def rate_limit(key_prefix, limit=5, period=60, post_only=True):
    """IP-based rate limiting. Allows *limit* requests per *period* seconds."""

    def decorator(view_func):
        @functools.wraps(view_func)
        def wrapped_view(request, *args, **kwargs):
            if post_only and request.method != 'POST':
                return view_func(request, *args, **kwargs)

            ip = get_client_ip(request)
            cache_key = f"ratelimit_{key_prefix}_{ip}"
            current_count = cache.get(cache_key, 0)

            if current_count >= limit:
                return HttpResponseForbidden(
                    "Rate limit exceeded. Please try again later."
                )

            if current_count == 0:
                cache.set(cache_key, 1, timeout=period)
            else:
                cache.incr(cache_key)

            return view_func(request, *args, **kwargs)

        return wrapped_view

    return decorator
