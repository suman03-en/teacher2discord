"""
Reusable utility helpers for the broadcast app.

These are pure helper functions with no database side-effects.
"""

from django.core.paginator import Paginator

MESSAGES_PER_PAGE = 10


def build_breadcrumbs(node):
    """Walk from *node* up through its parents to build a breadcrumb list.

    Returns a list ordered from root → current node.
    Works for any model that has a `parent` FK to itself.
    """
    crumbs = []
    while node:
        crumbs.insert(0, node)
        node = node.parent
    return crumbs


def paginate_queryset(queryset, page_number, per_page=MESSAGES_PER_PAGE):
    """Return a Django Page object for *queryset* at *page_number*."""
    paginator = Paginator(queryset, per_page)
    return paginator.get_page(page_number)


def get_client_ip(request):
    """Return the real client IP in a spoof-resistant way.

    ``X-Forwarded-For`` is client-controlled: an attacker can send any value
    and every proxy only *appends* to it. So we take the entry that was
    added by our own outermost trusted proxy — counted from the right —
    using ``settings.TRUSTED_PROXY_COUNT`` (0 = not behind a proxy).
    """
    import ipaddress

    from django.conf import settings

    proxy_count = getattr(settings, 'TRUSTED_PROXY_COUNT', 1)
    ip = request.META.get('REMOTE_ADDR')

    forwarded = request.META.get('HTTP_X_FORWARDED_FOR')
    if proxy_count > 0 and forwarded:
        parts = [p.strip() for p in forwarded.split(',') if p.strip()]
        if parts:
            ip = parts[-min(proxy_count, len(parts))]

    try:
        return str(ipaddress.ip_address(ip))
    except (TypeError, ValueError):
        return None
