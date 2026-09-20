"""Template helpers for Athar's server-rendered views."""

import re

from django import template
from django.utils.html import escape
from django.utils.safestring import mark_safe

from core.views import relative_time

register = template.Library()

URL_RE = re.compile(r"(?<![\"'=])(https?://[^\s<]+|www\.[^\s<]+)")
HASHTAG_RE = re.compile(r"(?<![\w&#])#([\w\u0600-\u06FF_]{1,40})")
MENTION_RE = re.compile(r"(?<![\w@/])@([a-zA-Z0-9_.-]{1,30})")
TRAILING_PUNCTUATION = ".,;:!?)]}\"'"


@register.filter
def linkify(value):
    """Escape user text, then link URLs, #tags and @mentions."""
    text = escape(str(value or ""))

    def url_replacer(match):
        raw = match.group(0)
        trailing = ""
        while raw and raw[-1] in TRAILING_PUNCTUATION:
            trailing = raw[-1] + trailing
            raw = raw[:-1]
        href = raw if raw.startswith("http") else f"https://{raw}"
        return f'<a class="body-link" href="{href}" target="_blank" rel="noopener nofollow noreferrer">{raw}</a>{trailing}'

    text = URL_RE.sub(url_replacer, text)
    text = HASHTAG_RE.sub(
        lambda match: f'<button type="button" class="body-tag" data-topic="{escape(match.group(1))}">#{escape(match.group(1))}</button>',
        text,
    )
    text = MENTION_RE.sub(
        lambda match: f'<a class="body-mention" href="/u/{match.group(1).lower()}/">@{escape(match.group(1))}</a>',
        text,
    )
    return mark_safe(text.replace("\n", "<br>"))


@register.filter
def ago(value):
    return relative_time(value)


@register.filter
def compact_number(value):
    try:
        number = int(value)
    except (TypeError, ValueError):
        return value
    if number < 1000:
        return str(number)
    if number < 1_000_000:
        return f"{number / 1000:.1f}k".replace(".0k", "k")
    return f"{number / 1_000_000:.1f}M".replace(".0M", "M")


@register.simple_tag(takes_context=True)
def avatar_classes(context, url, tone):
    return f"avatar {context.get('avatar_size', 'avatar-large')} tone-{tone or 'violet'}{' has-photo' if url else ''}"


@register.filter
def initials(value):
    text = str(value or "").strip()
    parts = [part for part in text.split() if part]
    if len(parts) >= 2:
        return (parts[0][:1] + parts[1][:1]).upper()
    return text[:2].upper() or "أ"
