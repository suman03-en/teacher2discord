import os
from pathlib import Path

import dj_database_url
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = os.environ.get('SECRET_KEY')
if not SECRET_KEY:
    raise ValueError(
        "SECRET_KEY environment variable is not set. "
        "Add it to your .env file or set it in your environment."
    )

DEBUG = os.environ.get('DEBUG', 'False') == 'True'

ALLOWED_HOSTS = [
    h.strip()
    for h in os.environ.get('ALLOWED_HOSTS', 'localhost,127.0.0.1').split(',')
    if h.strip()
]

CSRF_TRUSTED_ORIGINS = [
    origin.strip()
    for origin in os.environ.get('CSRF_TRUSTED_ORIGINS', '').split(',')
    if origin.strip()
]

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'anymail',
    'broadcast',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    'broadcast.middleware.ContentSecurityPolicyMiddleware',
]

ROOT_URLCONF = 'config.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'config.wsgi.application'


DATABASES = {
    'default': dj_database_url.config(
        default=f"sqlite:///{BASE_DIR / 'db.sqlite3'}",
        conn_max_age=600,
        conn_health_checks=True,
    )
}



AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]



LANGUAGE_CODE = 'en-us'

TIME_ZONE = 'UTC'

USE_I18N = True

USE_TZ = True


STATIC_URL = 'static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'
STORAGES = {
    'staticfiles': {
        'BACKEND': 'whitenoise.storage.CompressedManifestStaticFilesStorage',
    },
}

# Media files (User uploaded files)
MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'

# Email configuration using Brevo API (via django-anymail)
EMAIL_BACKEND = 'anymail.backends.brevo.EmailBackend'
ANYMAIL = {
    'BREVO_API_KEY': os.environ.get('BREVO_API_KEY', ''),
}
DEFAULT_FROM_EMAIL = os.environ.get(
    'DEFAULT_FROM_EMAIL', 'noreply@teacher2discord.com'
)

# Magic link expiry (minutes)
LOGIN_TOKEN_EXPIRY_MINUTES = 15

# ---------------------------------------------------------------------------
# Webhook encryption (Fernet symmetric key)
# Generate with: python -c "import base64, secrets; print(base64.urlsafe_b64encode(secrets.token_bytes(32)).decode())"
# ---------------------------------------------------------------------------
FIELD_ENCRYPTION_KEY = os.environ.get('FIELD_ENCRYPTION_KEY', '')

# ---------------------------------------------------------------------------
# Cache — shared across all gunicorn workers so rate-limit counters are
# global. (The default LocMemCache is per-process, which would multiply
# every limit by the number of workers.) Create the table once with:
#   python manage.py createcachetable
# ---------------------------------------------------------------------------
CACHES = {
    'default': {
        'BACKEND': 'django.core.cache.backends.db.DatabaseCache',
        'LOCATION': 'django_cache',
    }
}

# ---------------------------------------------------------------------------
# Magic-link rate limiting (protects inboxes AND the Brevo plan quota)
# Enforced by ``broadcast.decorators.magic_link_rate_limit``.
# ---------------------------------------------------------------------------
# Per email address
MAGIC_LINK_COOLDOWN_SECONDS = 60          # min gap between two links
MAGIC_LINK_PER_EMAIL_MAX_PER_HOUR = 3
MAGIC_LINK_PER_EMAIL_MAX_PER_DAY = 10
# Per client IP
MAGIC_LINK_PER_IP_MAX_PER_HOUR = 5
MAGIC_LINK_PER_IP_MAX_PER_DAY = 20
# Global hard cap across ALL users (rolling 24h). Keep this BELOW your
# Brevo daily allowance (free plan = 300/day) so an attack can never
# exhaust the plan.
MAGIC_LINK_GLOBAL_MAX_PER_DAY = int(os.environ.get('MAGIC_LINK_GLOBAL_MAX_PER_DAY', 250))

# Number of reverse proxies in front of Django that append to
# X-Forwarded-For (Render/Heroku = 1, none/local = 0). Used to read the
# real client IP without trusting spoofed headers.
TRUSTED_PROXY_COUNT = int(os.environ.get('TRUSTED_PROXY_COUNT', 1))

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'verbose': {
            'format': '{levelname} {asctime} {name} {message}',
            'style': '{',
        },
    },
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
            'formatter': 'verbose',
        },
    },
    'root': {
        'handlers': ['console'],
        'level': 'WARNING',
    },
    'loggers': {
        'broadcast': {
            'handlers': ['console'],
            'level': 'INFO' if not DEBUG else 'DEBUG',
            'propagate': False,
        },
        'django': {
            'handlers': ['console'],
            'level': 'INFO',
            'propagate': False,
        },
    },
}

# ---------------------------------------------------------------------------
# Security hardening
# ---------------------------------------------------------------------------
# Prevent the browser from MIME-sniffing the content type
SECURE_CONTENT_TYPE_NOSNIFF = True

# Clickjacking protection
X_FRAME_OPTIONS = 'DENY'

# Session cookie security
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = 'Lax'

# CSRF cookie security
CSRF_COOKIE_HTTPONLY = True
CSRF_COOKIE_SAMESITE = 'Lax'

# Production-only HTTPS settings (enabled when DEBUG is off)
if not DEBUG:
    SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
    SECURE_SSL_REDIRECT = True
    SECURE_HSTS_SECONDS = 31536000  # 1 year
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True

# Allowed file upload extensions for attachments
ALLOWED_ATTACHMENT_EXTENSIONS = [
    '.pdf', '.doc', '.docx', '.xls', '.xlsx', '.ppt', '.pptx',
    '.txt', '.csv', '.md',
    '.png', '.jpg', '.jpeg', '.gif', '.webp', '.svg',
    '.zip', '.rar', '.7z',
    '.mp3', '.mp4', '.wav', '.webm',
]

# Maximum attachment file size (bytes) — 10 MB
MAX_ATTACHMENT_SIZE = 10 * 1024 * 1024

# Django Debug Toolbar
if DEBUG:
    INSTALLED_APPS.append('debug_toolbar')
    MIDDLEWARE.insert(2, 'debug_toolbar.middleware.DebugToolbarMiddleware')
    INTERNAL_IPS = [
        '127.0.0.1',
        'localhost',
    ]
