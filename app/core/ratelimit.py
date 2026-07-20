"""Rate limiting: the OpenAI credit is the asset at risk once the URL is public.

Two stacked limits on conversation endpoints:
- per user+IP: stops one aggressive client (or a reviewer's curl loop)
- per IP alone: stops user-id rotation from bypassing the first
"""

from slowapi import Limiter
from slowapi.util import get_remote_address

from app.config import settings


def user_and_ip(request) -> str:
    return f"{get_remote_address(request)}|{request.headers.get('X-User-Id', 'anon')}"


limiter = Limiter(key_func=user_and_ip, enabled=settings.rate_limit_enabled)

CONVERSE_LIMIT = "20/minute"
CONVERSE_IP_LIMIT = "60/minute"
SPEECH_LIMIT = "40/minute"
