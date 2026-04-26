"""Token pricing — kept consistent with services/agents-mcp/.../morning_brief.py:253.

Sonnet rates (USD per million tokens):
- Input: $3.00
- Output: $15.00
- Cache read: $0.30 (10% of input)
- Cache write: $3.75 (1.25× input)

When we don't know the model (token_usage_daily.model is empty / unknown),
we default to Sonnet rates. That matches morning_brief's behavior.
"""

INPUT_PER_M = 3.00
OUTPUT_PER_M = 15.00
CACHE_READ_PER_M = 0.30
CACHE_WRITE_PER_M = 3.75


def estimate_usd(
    input_tokens: int,
    output_tokens: int,
    cache_read_tokens: int = 0,
    cache_write_tokens: int = 0,
) -> float:
    """Return cost in USD for the given token mix at Sonnet rates."""
    cost = (
        input_tokens * INPUT_PER_M
        + output_tokens * OUTPUT_PER_M
        + cache_read_tokens * CACHE_READ_PER_M
        + cache_write_tokens * CACHE_WRITE_PER_M
    ) / 1_000_000.0
    return round(cost, 4)
