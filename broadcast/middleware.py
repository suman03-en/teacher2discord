"""
Security middleware for the broadcast app.
"""


class ContentSecurityPolicyMiddleware:
    """Add a ``Content-Security-Policy`` header to every response.

    Directives are read from ``settings.CSP_DIRECTIVES`` (a dict mapping
    directive names to space-separated source values).  A sensible
    default is used when the setting is absent.

    This lightweight middleware avoids pulling in the ``django-csp``
    package while still providing baseline XSS protection.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)

        # Skip if the response already has a CSP header (e.g. from a view).
        if "Content-Security-Policy" not in response:
            from django.conf import settings

            directives = getattr(settings, "CSP_DIRECTIVES", None) or {
                "default-src": "'self'",
                "script-src": "'self'",
                "style-src": "'self' 'unsafe-inline' https://fonts.googleapis.com",
                "font-src": "'self' https://fonts.gstatic.com",
                "img-src": "'self' data:",
                "connect-src": "'self'",
                "frame-ancestors": "'none'",
                "base-uri": "'self'",
                "form-action": "'self'",
            }
            policy = "; ".join(f"{k} {v}" for k, v in directives.items())
            response["Content-Security-Policy"] = policy

        return response
