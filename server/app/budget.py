"""Shared daily Gemini token budget.

Before each Gemini call, an estimated amount is reserved. If today's
recorded usage plus everything currently reserved would pass the budget,
the call is refused before any tokens are spent. After the call, the real
usage reported by Gemini is recorded and the reservation is released.
"""

import threading
from contextlib import contextmanager

from app import config, db


class BudgetExceeded(Exception):
    pass


_lock = threading.Lock()
_reserved_tokens = 0


def remaining_tokens() -> int:
    with _lock:
        return config.DAILY_TOKEN_BUDGET - db.tokens_used_today() - _reserved_tokens


def can_afford(estimate: int) -> bool:
    return remaining_tokens() >= estimate


@contextmanager
def reserve(estimate: int):
    global _reserved_tokens
    with _lock:
        available = config.DAILY_TOKEN_BUDGET - db.tokens_used_today() - _reserved_tokens
        if available < estimate:
            raise BudgetExceeded(
                "The beta's daily AI budget has been reached. "
                "It resets at 00:00 UTC (7 PM Eastern)."
            )
        _reserved_tokens += estimate
    try:
        yield
    finally:
        with _lock:
            _reserved_tokens -= estimate


def record_response_usage(
    response,
    kind: str,
    tester_id: int | None,
    analysis_id: str | None,
    fallback_estimate: int,
) -> int:
    """Record the token usage Gemini reported for a response.

    If Gemini returns no usage metadata, the reservation estimate is
    recorded instead, so the budget is never under-counted.
    """
    usage = getattr(response, "usage_metadata", None)
    prompt = int(getattr(usage, "prompt_token_count", 0) or 0)
    output = int(getattr(usage, "candidates_token_count", 0) or 0)
    thoughts = int(getattr(usage, "thoughts_token_count", 0) or 0)
    total = int(getattr(usage, "total_token_count", 0) or 0)

    if total <= 0:
        total = prompt + output + thoughts
    if total <= 0:
        total = fallback_estimate

    db.record_usage(
        kind=kind,
        model=config.GEMINI_MODEL,
        prompt_tokens=prompt,
        output_tokens=output + thoughts,
        total_tokens=total,
        tester_id=tester_id,
        analysis_id=analysis_id,
    )
    return total
