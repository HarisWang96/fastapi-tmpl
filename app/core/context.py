"""Per-request context values shared with sync worker threads.

Context variables survive the Starlette threadpool hop, so sync clients can
attach the incoming request ID to outbound calls without threading it through
every service function.
"""

from contextvars import ContextVar

request_id_ctx: ContextVar[str | None] = ContextVar("request_id", default=None)
