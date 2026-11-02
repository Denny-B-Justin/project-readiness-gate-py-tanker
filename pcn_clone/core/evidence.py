"""Quote verification for reviewer citations.

A quote is verified when, after normalisation (Unicode NFC, JavaScript
whitespace runs collapsed to one space, trimmed), it is a non-empty,
case-sensitive substring of the cited field's normalised text. This
tolerates line wraps, doubled spaces and composed versus decomposed
characters while still rejecting paraphrase.
"""

from __future__ import annotations

import unicodedata

from pcn_clone.core.jsstr import collapse_whitespace, js_trim, utf16_contains


def normalize_for_quote_match(text: str) -> str:
    """NFC-normalise, collapse JavaScript whitespace runs to one space, trim."""
    return js_trim(collapse_whitespace(unicodedata.normalize("NFC", text)))


def verify_quote(quote: str, field_text: str) -> bool:
    """True when the normalised quote is non-empty and occurs in the
    normalised field text."""
    normalized_quote = normalize_for_quote_match(quote)
    return len(normalized_quote) > 0 and utf16_contains(
        normalize_for_quote_match(field_text), normalized_quote
    )
