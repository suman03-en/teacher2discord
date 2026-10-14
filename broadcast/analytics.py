"""
Analytics and quota tracking services for Admin Dashboard.
Fetches Brevo email credits, Cloudinary asset metrics, and database statistics.
"""

import json
import logging
import os
import urllib.request

from django.conf import settings
from django.contrib.auth.models import User
from django.core.cache import cache
from django.utils import timezone

from .models import Channel, Folder, LoginToken, SentMessage, StudentLink, Teacher

logger = logging.getLogger(__name__)

BREVO_CACHE_KEY = "admin_stats_brevo"
CLOUDINARY_CACHE_KEY = "admin_stats_cloudinary"
CACHE_TTL = 90  # cache external API calls for 90 seconds


def get_brevo_stats(force_refresh=False):
    """Fetch Brevo email send limit, used credits, and remaining available credits."""
    if not force_refresh:
        cached = cache.get(BREVO_CACHE_KEY)
        if cached is not None:
            return cached

    api_key = settings.ANYMAIL.get("BREVO_API_KEY", "")
    if not api_key:
        return {
            "configured": False,
            "error": "BREVO_API_KEY is not configured",
            "credits_remaining": 0,
            "credits_used": 0,
            "credits_total": 0,
            "percent_used": 0,
        }

    try:
        req = urllib.request.Request(
            "https://api.brevo.com/v3/account",
            headers={"api-key": api_key, "accept": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=4) as resp:
            data = json.loads(resp.read().decode())
            plans = data.get("plan", [{}])
            plan = plans[0] if plans else {}
            credits_remaining = plan.get("credits", 0)
            is_free = plan.get("type") == "free"
            total_limit = 300 if is_free else credits_remaining
            credits_used = max(0, total_limit - credits_remaining)
            percent = (
                round((credits_used / total_limit * 100), 1)
                if total_limit > 0
                else 0
            )

            stats = {
                "configured": True,
                "email": data.get("email", ""),
                "plan_type": plan.get("type", "Free").title(),
                "credits_remaining": credits_remaining,
                "credits_used": credits_used,
                "credits_total": total_limit,
                "percent_used": percent,
            }
            cache.set(BREVO_CACHE_KEY, stats, timeout=CACHE_TTL)
            return stats
    except Exception as exc:
        logger.warning("Failed to fetch Brevo stats: %s", exc)
        return {
            "configured": True,
            "error": str(exc),
            "credits_remaining": "N/A",
            "credits_used": "N/A",
            "credits_total": "N/A",
            "percent_used": 0,
        }


def get_cloudinary_stats(force_refresh=False):
    """Fetch Cloudinary total uploads, storage, bandwidth, and credits."""
    if not force_refresh:
        cached = cache.get(CLOUDINARY_CACHE_KEY)
        if cached is not None:
            return cached

    has_cloudinary = bool(
        os.environ.get("CLOUDINARY_URL") or os.environ.get("CLOUDINARY_CLOUD_NAME")
    )
    if not has_cloudinary:
        return {
            "configured": False,
            "error": "Cloudinary is not configured",
            "total_resources": 0,
            "storage_mb": 0,
        }

    try:
        import cloudinary.api

        usage = cloudinary.api.usage()
        storage_bytes = usage.get("storage", {}).get("usage", 0)
        storage_mb = round(storage_bytes / (1024 * 1024), 2)
        bandwidth_bytes = usage.get("bandwidth", {}).get("usage", 0)
        bandwidth_mb = round(bandwidth_bytes / (1024 * 1024), 2)
        credits_info = usage.get("credits", {})

        stats = {
            "configured": True,
            "plan": usage.get("plan", "Free"),
            "total_resources": usage.get("resources", 0),
            "storage_mb": storage_mb,
            "bandwidth_mb": bandwidth_mb,
            "credits_used": credits_info.get("usage", 0),
            "credits_limit": credits_info.get("limit", 25.0),
            "percent_used": credits_info.get("used_percent", 0),
        }
        cache.set(CLOUDINARY_CACHE_KEY, stats, timeout=CACHE_TTL)
        return stats
    except Exception as exc:
        logger.warning("Failed to fetch Cloudinary usage: %s", exc)
        return {
            "configured": True,
            "error": str(exc),
            "total_resources": "N/A",
            "storage_mb": "N/A",
        }


def get_system_analytics(force_refresh=False):
    """Aggregate complete analytics dashboard metrics."""
    now = timezone.now()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

    total_tokens_sent = LoginToken.objects.count()
    tokens_sent_today = LoginToken.objects.filter(created_at__gte=today_start).count()
    tokens_used = LoginToken.objects.filter(used=True).count()

    admin_users = User.objects.count()
    superusers = User.objects.filter(is_superuser=True).count()
    teachers_count = Teacher.objects.count()
    folders_count = Folder.objects.count()
    channels_count = Channel.objects.count()
    links_count = StudentLink.objects.count()
    messages_count = SentMessage.objects.count()

    messages_with_files = SentMessage.objects.exclude(attachment_name="")
    total_attachment_records = messages_with_files.count()

    image_count = 0
    video_count = 0
    doc_count = 0
    for m in messages_with_files:
        if m.is_image:
            image_count += 1
        elif m.is_video:
            video_count += 1
        else:
            doc_count += 1

    brevo = get_brevo_stats(force_refresh=force_refresh)
    cloudinary_stats = get_cloudinary_stats(force_refresh=force_refresh)

    return {
        "email": {
            "total_sent": total_tokens_sent,
            "sent_today": tokens_sent_today,
            "tokens_used": tokens_used,
            "brevo_used": brevo.get("credits_used", 0),
            "brevo_available": brevo.get("credits_remaining", 0),
            "brevo_total": brevo.get("credits_total", 300),
            "brevo_percent": brevo.get("percent_used", 0),
            "brevo_email": brevo.get("email", ""),
            "brevo_plan": brevo.get("plan_type", "Free"),
            "brevo_error": brevo.get("error"),
        },
        "cloudinary": {
            "total_resources": cloudinary_stats.get("total_resources", 0),
            "storage_mb": cloudinary_stats.get("storage_mb", 0),
            "bandwidth_mb": cloudinary_stats.get("bandwidth_mb", 0),
            "credits_used": cloudinary_stats.get("credits_used", 0),
            "credits_limit": cloudinary_stats.get("credits_limit", 25.0),
            "percent_used": cloudinary_stats.get("percent_used", 0),
            "image_count": image_count,
            "video_count": video_count,
            "doc_count": doc_count,
            "total_db_files": total_attachment_records,
            "error": cloudinary_stats.get("error"),
        },
        "users": {
            "admin_users": admin_users,
            "superusers": superusers,
            "teachers": teachers_count,
            "folders": folders_count,
            "channels": channels_count,
            "links": links_count,
            "messages": messages_count,
        },
    }
