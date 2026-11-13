"""HTML clean-up, date parsing and small helpers used by every provider."""

from __future__ import annotations

import html
import re
from datetime import datetime, timezone
from typing import Any, Optional

_BLOCK_END = re.compile(r"(?i)<br\s*/?>|</p>|</li>|</div>|</h[1-6]>|</tr>|</ul>|</ol>")
_LI_START = re.compile(r"(?i)<li[^>]*>")
_TAG = re.compile(r"<[^>]+>")


def strip_html(value: Any) -> str:
    """Plain text from an HTML fragment, keeping paragraph and list structure as line breaks."""
    if not value:
        return ""
    s = str(value)
    s = _BLOCK_END.sub("\n", s)
    s = _LI_START.sub("\n- ", s)
    s = _TAG.sub(" ", s)
    s = html.unescape(s).replace("\xa0", " ")
    lines = [re.sub(r"[ \t]+", " ", ln).strip() for ln in s.splitlines()]
    out: list[str] = []
    for ln in lines:
        if ln or (out and out[-1]):
            out.append(ln)
    return "\n".join(out).strip()


_DATE_FORMATS = ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%a, %d %b %Y %H:%M:%S")


def parse_dt(value: Any) -> Optional[datetime]:
    """Epoch seconds/milliseconds, ISO-8601 or common date strings -> naive UTC datetime."""
    if value in (None, "", 0):
        return None
    try:
        if isinstance(value, (int, float)) or (isinstance(value, str) and re.fullmatch(r"\d{9,13}(\.\d+)?", value.strip())):
            num = float(value)
            if num > 1e11:  # milliseconds
                num /= 1000.0
            return datetime.fromtimestamp(num, tz=timezone.utc).replace(tzinfo=None)
        s = str(value).strip()
        try:
            dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
            if dt.tzinfo is not None:
                dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
            return dt
        except ValueError:
            pass
        s = re.sub(r"\s*(\+\d{4}|[A-Z]{3})$", "", s)  # drop trailing zone from RFC-822 style dates
        for fmt in _DATE_FORMATS:
            try:
                return datetime.strptime(s, fmt)
            except ValueError:
                continue
    except (ValueError, OverflowError, OSError):
        pass
    return None


def money(lo: Any, hi: Any, currency: Optional[str] = None, period: Optional[str] = None) -> Optional[str]:
    """Readable salary text, or None when nothing meaningful was provided."""

    def num(v: Any) -> Optional[float]:
        try:
            f = float(v)
            return f if f > 0 else None
        except (TypeError, ValueError):
            return None

    a, b = num(lo), num(hi)
    if a is None and b is None:
        return None

    def fmt(x: float) -> str:
        return f"{x:,.0f}"

    cur = f"{currency} " if currency else ""
    if a is not None and b is not None and a != b:
        text = f"{cur}{fmt(a)} - {fmt(b)}"
    else:
        text = f"{cur}{fmt(a if a is not None else b)}"  # type: ignore[arg-type]
    return text + (f" / {period}" if period else "")


def clean_text(value: Any) -> str:
    """Single-line text with markup removed (titles, company names)."""
    return re.sub(r"\s+", " ", strip_html(value)).strip()


def first(d: dict, *keys: str, default: Any = None) -> Any:
    for k in keys:
        v = d.get(k)
        if v not in (None, "", []):
            return v
    return default


def as_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value] if value.strip() else []
    out = []
    for v in value:
        if isinstance(v, dict):
            v = v.get("name") or v.get("title") or ""
        v = str(v).strip()
        if v:
            out.append(v)
    return out
