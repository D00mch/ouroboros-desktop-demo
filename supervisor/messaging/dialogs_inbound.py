from __future__ import annotations

import logging
import time
from typing import Any

from supervisor.messaging.dialogs_attachment_context import (
    build_attachment_context,
    render_yaml_text_block,
)
from supervisor.messaging.base import InboundMessage

log = logging.getLogger("supervisor.messaging.dialogs_provider")


def normalize_update_message(self, update: Any) -> tuple[InboundMessage | None, str]:
    if update is None:
        return None, "missing_update_message"

    payload = getattr(update, "message", None)
    body_kind = self._message_body_kind(payload)
    original_text = self._extract_text(payload)
    attachment_context = self._build_attachment_context(update)
    if not original_text and body_kind == "textMessage" and not attachment_context:
        return None, "empty_text"
    if not original_text and body_kind != "textMessage":
        return None, f"unsupported_message_body:{body_kind or 'none'}"

    chat_id = self._peer_key(getattr(update, "peer", None))
    if not chat_id:
        return None, "missing_peer_id"

    user_id = self._sender_key(getattr(update, "sender_peer", None))
    if user_id == "":
        return None, "missing_sender_uid"

    self._remember_private_out_peer(
        chat_id=chat_id,
        peer=getattr(update, "peer", None),
        sender_peer=getattr(update, "sender_peer", None),
    )
    enriched_text = self._normalize_update_message_text(original_text, attachment_context)

    return InboundMessage(
        chat_id=chat_id,
        user_id=user_id,
        text=enriched_text,
        caption="",
        image_data=None,
        raw_command=original_text if str(original_text).startswith("/") else "",
    ), "accepted_update_message"


def normalize_update_message_text(self, original_text: str, attachment_context: str) -> str:
    if not attachment_context:
        return original_text
    body_text = original_text if original_text else "(no user text)"
    return (
        "[ATTACHMENT_CONTEXT]\n"
        f"{attachment_context}\n\n"
        "[MESSAGE_BODY]\n"
        f"{body_text}"
    )


def build_attachment_context_for_update(self, update: Any) -> str:
    author_names = self._resolve_referenced_authors(update)
    return build_attachment_context(
        update=update,
        extract_text=self._extract_text,
        render_yaml_text_block=self._render_yaml_text_block,
        author_names=author_names,
    )


def resolve_referenced_authors(self, update: Any) -> dict[int, str]:
    origin_peers = self._collect_referenced_author_peers(update)
    if not origin_peers or self._seq_stub is None:
        return {}

    if not hasattr(self._seq_stub, "GetReferencedEntitites"):
        return {}

    self._ensure_generated_import_path()
    from supervisor.messaging.generated.dialogs import sequence_and_updates_pb2

    request = sequence_and_updates_pb2.RequestGetReferencedEntitites(users=origin_peers)

    unauthorized_retry_done = False
    transient_retry_count = 0
    max_transient_retries = 2

    while True:
        try:
            response = self._call_stub(
                self._seq_stub,
                "GetReferencedEntitites",
                request,
                metadata=self._rpc_metadata(),
            )
            break
        except Exception as exc:
            if self._is_unauthorized_error(exc) and not unauthorized_retry_done:
                unauthorized_retry_done = True
                self._reset_auth_state()
                self._reauth_with_backoff()
                continue

            if self._is_transient_error(exc) and transient_retry_count < max_transient_retries:
                transient_retry_count += 1
                time.sleep(0.5 * (2 ** (transient_retry_count - 1)))
                continue

            return {}

    author_names: dict[int, str] = {}
    for user in getattr(response, "users", []):
        uid = self._sender_key(user)
        try:
            uid_int = int(uid)
        except Exception:
            continue
        if uid_int in author_names:
            continue

        name = str(getattr(getattr(user, "data", None), "name", ""))
        if not name:
            continue
        author_names[uid_int] = name
    return author_names


def collect_referenced_author_peers(self, update: Any) -> list[Any]:
    if update is None:
        return []

    peers: list[Any] = []
    seen_uids: set[int] = set()

    self._ensure_generated_import_path()
    from supervisor.messaging.generated.dialogs import peers_pb2

    forward_obj = getattr(update, "forward", None)
    for preview in getattr(forward_obj, "previews", []):
        uid = self._extract_origin_sender_peer_uid(preview)
        if uid is None or uid in seen_uids:
            continue
        seen_uids.add(uid)
        peers.append(
            peers_pb2.UserOutPeer(
                uid=uid,
                access_hash=self._sender_access_hash(getattr(preview, "origin_sender_peer", None))
                or 0,
            ),
        )

    reply_obj = getattr(update, "reply", None)
    for preview in getattr(reply_obj, "previews", []):
        text = self._extract_text(getattr(preview, "message", None))
        if not text:
            continue
        if not self._is_reply_forward_preview(preview):
            break
        uid = self._extract_origin_sender_peer_uid(preview)
        if uid is None or uid in seen_uids:
            break
        seen_uids.add(uid)
        peers.append(
            peers_pb2.UserOutPeer(
                uid=uid,
                access_hash=self._sender_access_hash(getattr(preview, "origin_sender_peer", None))
                or 0,
            ),
        )
        break
    return peers


def is_reply_forward_preview(self, preview: Any) -> bool:
    attrs = getattr(preview, "attributes", None)
    if not self._has_field(attrs, "is_forward"):
        return False
    wrapped_value = getattr(attrs, "is_forward", None)
    return bool(getattr(wrapped_value, "value", False))


def extract_origin_sender_peer_uid(self, preview: Any) -> int | None:
    if not self._has_field(preview, "origin_sender_peer"):
        return None
    peer = getattr(preview, "origin_sender_peer", None)
    uid = getattr(peer, "uid", None)
    try:
        uid_int = int(uid)
    except Exception:
        return None
    if uid_int <= 0:
        return None
    return uid_int


def has_field(self, message: Any, field_name: str) -> bool:
    if message is None:
        return False
    has_field_method = getattr(message, "HasField", None)
    if not callable(has_field_method):
        return False
    try:
        return bool(has_field_method(field_name))
    except Exception:
        return False


def render_yaml_text_block_method(self, value: str, indent: int) -> list[str]:
    return render_yaml_text_block(value=value, indent=indent)


def extract_inbound_message(self, box: Any) -> InboundMessage | None:
    if box is None:
        self._log_seq_update_handling(box=None, update_type="none", handled=False, reason="missing_box")
        return None
    update = getattr(box, "unboxed_update", None)
    update_type = self._seq_update_type(update)
    if update_type != "updateMessage":
        reason = f"unsupported_update_type:{update_type}" if update_type else "missing_update_type"
        self._log_seq_update_handling(box=box, update_type=update_type or "none", handled=False, reason=reason)
        return None

    msg, reason = self._normalize_update_message(getattr(update, "updateMessage", None))
    self._log_seq_update_handling(
        box=box,
        update_type=update_type,
        handled=msg is not None,
        reason=reason,
        msg=msg,
    )
    return msg


def log_seq_update_handling(
    self,
    box: Any,
    update_type: str,
    handled: bool,
    reason: str,
    msg: InboundMessage | None = None,
) -> None:
    seq = self._box_seq(box)
    if msg is None:
        log.info(
            "Dialogs SeqUpdate handled=%s reason=%s update_type=%s seq=%s",
            handled,
            reason,
            update_type,
            seq,
        )
        return
    log.info(
        "Dialogs SeqUpdate handled=%s reason=%s update_type=%s seq=%s chat_id=%s user_id=%s text_len=%s",
        handled,
        reason,
        update_type,
        seq,
        msg.chat_id,
        msg.user_id,
        len(msg.text or ""),
    )


def seq_update_type(self, update: Any) -> str:
    if update is None:
        return ""
    which_oneof = getattr(update, "WhichOneof", None)
    if callable(which_oneof):
        try:
            return str(which_oneof("update") or "")
        except Exception:
            return ""
    return ""


def box_seq(self, box: Any) -> int:
    if box is None:
        return 0
    if isinstance(box, dict):
        value = box.get("seq") or 0
    elif hasattr(box, "seq"):
        value = getattr(box, "seq", 0) or 0
    else:
        value = self._as_dict(box).get("seq") or 0
    try:
        return int(value)
    except Exception:
        return 0
