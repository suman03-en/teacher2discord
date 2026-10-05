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
    """Extract the client IP from the request, respecting X-Forwarded-For."""
    forwarded = request.META.get('HTTP_X_FORWARDED_FOR')
    if forwarded:
        return forwarded.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR')
