"""Business time helpers using naive local time in settings.TIMEZONE.

Database DATETIME columns have no timezone, so writes and comparisons must use
the same convention. datetime.now() uses the container timezone (usually UTC)
and can shift boundary data when deployment settings change.
"""

from datetime import datetime
from zoneinfo import ZoneInfo

from app.core.config import settings

TZ = ZoneInfo(settings.TIMEZONE)


def now() -> datetime:
    return datetime.now(TZ).replace(tzinfo=None)
