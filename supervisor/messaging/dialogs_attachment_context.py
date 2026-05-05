from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable


def build_attachment_context(
    update: Any,
    extract_text: Callable[[Any], str],
    render_yaml_text_block: Callable[[str, int], list[str]],
    author_names: dict[int, str] | None = None,
) -> str:
    if update is None:
        return ""

    reply_obj = getattr(update, "reply", None)
    forward_obj = getattr(update, "forward", None)

    has_reply_preview = False
    has_forward_preview = False
    reply_render_error = False
    forward_render_error = False
    has_rendered_content = False
    lines = ["policy: reference-only"]

    try:
        reply_previews = list(getattr(reply_obj, "previews", []))
        has_reply_preview = bool(reply_previews)
    except Exception:
        reply_previews = []

    try:
        forward_previews = list(getattr(forward_obj, "previews", []))
        has_forward_preview = bool(forward_previews)
    except Exception:
        forward_previews = []

    if has_reply_preview:
        try:
            reply_text, reply_date, reply_author = extract_reply_context(
                reply_obj,
                extract_text=extract_text,
                as_iso8601_text=as_iso8601_text,
                author_names=author_names,
            )
        except Exception:
            reply_text = None
            reply_date = None
            reply_render_error = True
        else:
            if reply_text:
                try:
                    rendered_reply = render_yaml_text_block(reply_text, 4)
                except Exception:
                    reply_render_error = True
                else:
                    has_rendered_content = True
                    lines.append("Reply:")
                    if reply_date:
                        lines.append(f"  date: {reply_date}")
                    if reply_author:
                        lines.append(f"  original_author: {reply_author}")
                    lines.append("  content:")
                    lines.extend(rendered_reply)

    if has_forward_preview:
        try:
            forwarded_previews = extract_forwarded_contexts(
                forward_obj,
                extract_text=extract_text,
                author_names=author_names,
            )
        except Exception:
            forwarded_texts = []
            forward_render_error = True
        else:
            rendered_previews = []
            for forwarded_text, forwarded_author in forwarded_previews:
                if not forwarded_text:
                    continue
                try:
                    rendered_preview = render_yaml_text_block(forwarded_text, 6)
                except Exception:
                    forward_render_error = True
                    continue
                has_rendered_content = True
                preview_lines = ["  - content:"]
                if forwarded_author:
                    rendered_previews.extend([f"  - original_author: {forwarded_author}", "    content:"])
                else:
                    rendered_previews.extend(preview_lines)
                rendered_previews.extend(rendered_preview)

            if rendered_previews:
                lines.append("ForwardedMessages:")
                lines.extend(rendered_previews)

    if not has_rendered_content:
        if (reply_render_error or forward_render_error) and (has_reply_preview or has_forward_preview):
            return "policy: reference-only\nrender_error: true"
        return ""

    return "\n".join(lines)


def extract_reply_context(
    reply: Any,
    extract_text: Callable[[Any], str],
    as_iso8601_text: Callable[[Any], str | None],
    author_names: dict[int, str] | None = None,
) -> tuple[str | None, str | None, str | None]:
    if reply is None:
        return None, None

    for preview in getattr(reply, "previews", []):
        text = extract_text(getattr(preview, "message", None))
        if not text:
            continue
        original_author = None
        if _is_forward_reply(preview):
            original_author = _extract_original_author(preview, author_names)
        return text, as_iso8601_text(getattr(preview, "date", None)), original_author
    return None, None, None


def extract_forwarded_contexts(
    forward: Any,
    extract_text: Callable[[Any], str],
    author_names: dict[int, str] | None = None,
) -> list[tuple[str, str | None]]:
    if forward is None:
        return []

    previews = []
    for preview in getattr(forward, "previews", []):
        text = extract_text(getattr(preview, "message", None))
        if text:
            original_author = _extract_original_author(preview, author_names)
            previews.append((text, original_author))
    return previews


def _is_forward_reply(preview: Any) -> bool:
    attrs = getattr(preview, "attributes", None)
    if not _has_proto_field(attrs, "is_forward"):
        return False
    value = getattr(attrs, "is_forward", None)
    return bool(getattr(value, "value", False))


def _extract_original_author(preview: Any, author_names: dict[int, str] | None) -> str | None:
    if not author_names:
        return None
    uid = _extract_origin_sender_uid(preview)
    if uid is None:
        return None
    return author_names.get(uid)


def _extract_origin_sender_uid(preview: Any) -> int | None:
    if not _has_proto_field(preview, "origin_sender_peer"):
        return None
    peer = getattr(preview, "origin_sender_peer", None)
    uid = getattr(peer, "uid", None)
    try:
        uid_value = int(uid)
    except Exception:
        return None
    if uid_value <= 0:
        return None
    return uid_value


def _has_proto_field(message: Any, field_name: str) -> bool:
    if message is None:
        return False
    has_field = getattr(message, "HasField", None)
    if not callable(has_field):
        return False
    try:
        return bool(has_field(field_name))
    except Exception:
        return False


def as_iso8601_text(value: Any) -> str | None:
    if value is None:
        return None
    try:
        timestamp = int(value)
    except Exception:
        return None
    if timestamp <= 0:
        return None
    try:
        if timestamp >= 10**12:
            timestamp = timestamp / 1000
        dt = datetime.fromtimestamp(timestamp, tz=timezone.utc).replace(microsecond=0)
    except Exception:
        return None
    return dt.isoformat().replace("+00:00", "Z")


def render_yaml_text_block(value: str, indent: int) -> list[str]:
    indent_text = " " * indent
    body_lines = value.split("\n") if value else [""]
    lines = [f"{indent_text}text: |-"]
    lines.extend(f"{indent_text}  {line}" for line in body_lines)
    return lines
