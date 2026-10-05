from django.core.cache import cache
from django.http import HttpResponseForbidden
import functools

def rate_limit(key_prefix, limit=5, period=60, post_only=True):
    """
    Simple IP-based rate limiting decorator.
    Allows `limit` requests per `period` seconds.
    If `post_only` is True, only POST requests are rate limited.
    """
    def decorator(view_func):
        @functools.wraps(view_func)
        def wrapped_view(request, *args, **kwargs):
            if post_only and request.method != 'POST':
                return view_func(request, *args, **kwargs)

            # Get client IP address
            x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
            if x_forwarded_for:
                ip = x_forwarded_for.split(',')[0].strip()
            else:
                ip = request.META.get('REMOTE_ADDR')
                
            cache_key = f"ratelimit_{key_prefix}_{ip}"
            
            # Get current count for this IP
            current_count = cache.get(cache_key, 0)
            
            if current_count >= limit:
                return HttpResponseForbidden("Rate limit exceeded. Please try again later.")
            
            # Increment or set initial value
            if current_count == 0:
                cache.set(cache_key, 1, timeout=period)
            else:
                cache.incr(cache_key)
                
            return view_func(request, *args, **kwargs)
        return wrapped_view
    return decorator
