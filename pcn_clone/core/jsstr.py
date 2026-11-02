"""JavaScript primitives: whitespace, number rendering, value-to-string
conversion and JSON encoding.

Serialized text is compared and hashed byte for byte, so these follow the
ECMAScript definitions rather than Python's. JavaScript whitespace (``\\s``,
``trim``) is the WhiteSpace and LineTerminator set, which includes U+FEFF and
excludes the C0 separators and U+0085 that Python treats as whitespace.
Numbers are IEEE doubles rendered with the shortest round-trip digits.
"""

from __future__ import annotations

import math
import re
from collections.abc import Mapping, Sequence
from typing import Any

JS_WHITESPACE = (
    "\t\n\v\f\r \u00a0\u1680"
    "\u2000\u2001\u2002\u2003\u2004\u2005\u2006\u2007\u2008\u2009\u200a"
    "\u2028\u2029\u202f\u205f\u3000\ufeff"
)
"""Every character JavaScript's ``\\s`` and ``String.prototype.trim`` match."""

JS_WHITESPACE_RUN = re.compile(f"[{re.escape(JS_WHITESPACE)}]+")
"""JavaScript's ``/\\s+/``."""


# --- Strings -----------------------------------------------------------------


def js_trim(text: str) -> str:
    """``String.prototype.trim``."""
    return text.strip(JS_WHITESPACE)


def trim_or_empty(text: str | None) -> str:
    """``(text ?? "").trim()``: a missing value trims to ``""``."""
    return "" if text is None else js_trim(text)


def collapse_whitespace(text: str) -> str:
    """Replace every run of JavaScript whitespace with a single space."""
    return JS_WHITESPACE_RUN.sub(" ", text)


def to_utf16(text: str) -> bytes:
    """The UTF-16LE code units of a string, lone surrogates included."""
    return text.encode("utf-16-le", "surrogatepass")


def canonical_surrogates(text: str) -> str:
    """Join adjacent surrogate halves into the code point they encode.

    A JavaScript string is a sequence of UTF-16 code units, so a high/low
    surrogate pair is one character however it was produced; lone halves
    stay as they are.
    """
    return to_utf16(text).decode("utf-16-le", "surrogatepass")


def utf16_contains(haystack: str, needle: str) -> bool:
    """``String.prototype.includes``: code-unit substring containment."""
    hay = to_utf16(haystack)
    pin = to_utf16(needle)
    index = hay.find(pin)
    while index != -1:
        if index % 2 == 0:
            return True
        index = hay.find(pin, index + 1)
    return False


# --- Numbers -----------------------------------------------------------------


def _int_to_double(value: int) -> float:
    try:
        return float(value)
    except OverflowError:
        return math.inf if value > 0 else -math.inf


def as_double(value: float) -> float:
    """The double a JavaScript number with this value holds; integers too
    large for a double become infinite."""
    return _int_to_double(value) if isinstance(value, int) else float(value)


def _shortest_digits(value: float) -> tuple[str, int]:
    """Shortest round-trip digits ``s`` and exponent ``n`` with
    value = 0.s × 10^n, for a finite positive value."""
    mantissa, _, exponent = repr(value).partition("e")
    whole, _, fraction = mantissa.partition(".")
    digits = whole + fraction
    point = len(whole) + (int(exponent) if exponent else 0)
    stripped = digits.lstrip("0")
    point -= len(digits) - len(stripped)
    return stripped.rstrip("0"), point


def number_to_string(value: float) -> str:
    """Render a number exactly as JavaScript's ``String(number)``."""
    value = as_double(value)
    if math.isnan(value):
        return "NaN"
    if value == 0:
        return "0"
    if value < 0:
        return "-" + number_to_string(-value)
    if math.isinf(value):
        return "Infinity"
    digits, n = _shortest_digits(value)
    k = len(digits)
    if k <= n <= 21:
        return digits + "0" * (n - k)
    if 0 < n <= 21:
        return digits[:n] + "." + digits[n:]
    if -6 < n <= 0:
        return "0." + "0" * (-n) + digits
    exponent = n - 1
    sign = "+" if exponent >= 0 else "-"
    head = digits if k == 1 else digits[0] + "." + digits[1:]
    return f"{head}e{sign}{abs(exponent)}"


# --- Values ------------------------------------------------------------------


def js_to_string(value: Any) -> str:
    """Convert a JSON-shaped value to text as a JavaScript template literal does.

    ``None`` maps to ``""`` (callers read absent and null alike), arrays join
    their items with commas, and objects render as ``[object Object]``.
    """
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return number_to_string(value)
    if isinstance(value, Mapping):
        return "[object Object]"
    if isinstance(value, Sequence):
        return ",".join(js_to_string(item) for item in value)
    return str(value)


def _is_array_index(key: str) -> bool:
    return (
        key.isascii()
        and key.isdigit()
        and (key == "0" or not key.startswith("0"))
        and int(key) < 2**32 - 1
    )


def js_object_keys(value: Mapping[Any, Any]) -> list[str]:
    """``Object.keys`` order: array-index keys ascending, then insertion order."""
    keys = [str(key) for key in value]
    index_keys = sorted((key for key in keys if _is_array_index(key)), key=int)
    return [*index_keys, *(key for key in keys if not _is_array_index(key))]


_JSON_ESCAPES = {
    '"': '\\"',
    "\\": "\\\\",
    "\b": "\\b",
    "\f": "\\f",
    "\n": "\\n",
    "\r": "\\r",
    "\t": "\\t",
}


def _json_quote(text: str) -> str:
    out = ['"']
    for char in canonical_surrogates(text):
        escaped = _JSON_ESCAPES.get(char)
        if escaped is not None:
            out.append(escaped)
        elif char < " " or "\ud800" <= char <= "\udfff":
            out.append(f"\\u{ord(char):04x}")
        else:
            out.append(char)
    out.append('"')
    return "".join(out)


def js_json_stringify(value: Any) -> str:
    """``JSON.stringify`` without indentation, byte-compatible with JavaScript.

    Strings escape only quote, backslash and control characters (short forms
    where JSON has them, lowercase ``\\u00xx`` otherwise) plus lone
    surrogates; U+2028, U+2029 and astral characters are emitted as is.
    Object keys follow JavaScript property order; non-finite numbers encode
    as ``null``.
    """
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str):
        return _json_quote(value)
    if isinstance(value, (int, float)):
        number = as_double(value)
        return number_to_string(number) if math.isfinite(number) else "null"
    if isinstance(value, Mapping):
        items = {str(key): item for key, item in value.items()}
        members = (
            f"{_json_quote(key)}:{js_json_stringify(items[key])}"
            for key in js_object_keys(value)
        )
        return "{" + ",".join(members) + "}"
    if isinstance(value, Sequence):
        return "[" + ",".join(js_json_stringify(item) for item in value) + "]"
    raise TypeError(f"Cannot JSON-encode a value of type {type(value).__name__}.")
