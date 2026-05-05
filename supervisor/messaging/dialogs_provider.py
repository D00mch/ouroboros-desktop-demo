from __future__ import annotations

import logging
import random
import queue
import ssl
import sys
import time
import threading
import json
from pathlib import Path
from typing import Any

from supervisor.messaging.base import InboundMessage
from supervisor.messaging.dialogs_inbound import (
    box_seq as dialogs_box_seq,
    build_attachment_context_for_update as dialogs_build_attachment_context,
    collect_referenced_author_peers as dialogs_collect_referenced_author_peers,
    extract_inbound_message as dialogs_extract_inbound_message,
    extract_origin_sender_peer_uid as dialogs_extract_origin_sender_peer_uid,
    has_field as dialogs_has_field,
    is_reply_forward_preview as dialogs_is_reply_forward_preview,
    log_seq_update_handling as dialogs_log_seq_update_handling,
    normalize_update_message as dialogs_normalize_update_message,
    normalize_update_message_text as dialogs_normalize_update_message_text,
    render_yaml_text_block_method as dialogs_render_yaml_text_block,
    resolve_referenced_authors as dialogs_resolve_referenced_authors,
    seq_update_type as dialogs_seq_update_type,
)
from supervisor.runtime_config import RuntimeConfig

log = logging.getLogger(__name__)


try:
    import grpc
except Exception:  # pragma: no cover - optional import for environments without grpc
    grpc = None


class DialogsProvider:
    name = "dialogs"

    def __init__(self, cfg: RuntimeConfig):
        self.cfg = cfg
        self._dialogs_loading_phrases_path = (
            Path(__file__).resolve().with_name("dialogs_loading_phrases.json")
        )
        self._dialogs_loading_phrases_cache: list[str] | None = None
        self._channel = None
        self._registration_stub = None
        self._auth_stub = None
        self._messaging_stub = None
        self._seq_stub = None
        self._auth_ticket = ""
        self._session_token = ""
        self._private_out_peers_by_chat: dict[str, dict[str, int]] = {}
        self._seq_stream_iter = None
        self._seq_stream_cursor = 0
        self._weak_request_queue = queue.Queue()
        self._weak_reader_thread = None
        self._weak_stream_stop_event = threading.Event()
        self._weak_reader_session_token = ""
        self._active_typing_chats: set[str] = set()
        self._typing_heartbeat_thread = None
        self._typing_heartbeat_stop_event = threading.Event()
        self._typing_last_heartbeat_at: dict[str, float] = {}

    _normalize_update_message = dialogs_normalize_update_message
    _normalize_update_message_text = dialogs_normalize_update_message_text
    _build_attachment_context = dialogs_build_attachment_context
    _resolve_referenced_authors = dialogs_resolve_referenced_authors
    _collect_referenced_author_peers = dialogs_collect_referenced_author_peers
    _is_reply_forward_preview = dialogs_is_reply_forward_preview
    _extract_origin_sender_peer_uid = dialogs_extract_origin_sender_peer_uid
    _has_field = dialogs_has_field
    _render_yaml_text_block = dialogs_render_yaml_text_block
    _extract_inbound_message = dialogs_extract_inbound_message
    _log_seq_update_handling = dialogs_log_seq_update_handling
    _seq_update_type = dialogs_seq_update_type
    _box_seq = dialogs_box_seq

    def send_text(self, chat_id: Any, text: str, fmt: str = "") -> tuple[bool, str]:
        if self._messaging_stub is None:
            return False, "dialogs messaging stub not initialized"
        deduplication_id = random.randint(1, (1 << 63) - 1)
        req = self._build_send_message_request(
            peer_id=chat_id,
            text=text,
            deduplication_id=deduplication_id,
        )
        try:
            resp = self._send_message_request(req, metadata=self._rpc_metadata)
        except Exception as exc:
            return False, str(exc)
        return True, getattr(resp, "message_id", "ok")

    def send_loading_phrase(self, chat_id: Any) -> dict[str, Any] | None:
        if self._messaging_stub is None:
            return None

        phrase = random.choice(self._load_loading_phrases())
        deduplication_id = random.randint(1, (1 << 63) - 1)
        req = self._build_send_message_request(
            peer_id=chat_id,
            text=phrase,
            deduplication_id=deduplication_id,
        )
        try:
            resp = self._send_message_request(req, metadata=self._rpc_metadata)
        except Exception:
            return None

        message_uuid = self._normalize_uuid_value(getattr(resp, "message_id", None))
        if not message_uuid:
            return None

        return {
            "loading_phrase": phrase,
            "loading_message_uuid": message_uuid,
        }

    def delete_loading_message(self, chat_id: Any, message_uuid: dict[str, Any]) -> bool:
        if self._messaging_stub is None:
            return False

        req = self._build_delete_message_request(chat_id, message_uuid)
        try:
            self._call_stub(
                self._messaging_stub,
                "DeleteMessage",
                req,
                metadata=self._rpc_metadata(),
            )
            return True
        except Exception:
            return False

    def send_typing(self, chat_id: Any) -> bool:
        return False

    def begin_reply_typing(self, chat_id: Any) -> None:
        normalized_chat_id = self._normalize_typing_chat_id(chat_id)
        if not normalized_chat_id:
            return

        if normalized_chat_id in self._active_typing_chats:
            return

        self._active_typing_chats.add(normalized_chat_id)
        self._typing_last_heartbeat_at[normalized_chat_id] = time.time()
        self._enqueue_weak_command(
            self._build_change_my_typing_command(normalized_chat_id, start=True),
        )
        self._ensure_typing_heartbeat_thread()

    def end_reply_typing(self, chat_id: Any) -> None:
        normalized_chat_id = self._normalize_typing_chat_id(chat_id)
        if not normalized_chat_id:
            return
        if normalized_chat_id not in self._active_typing_chats:
            return

        self._active_typing_chats.remove(normalized_chat_id)
        self._typing_last_heartbeat_at.pop(normalized_chat_id, None)
        self._enqueue_weak_command(
            self._build_change_my_typing_command(normalized_chat_id, start=False),
        )

        if not self._active_typing_chats:
            self._typing_heartbeat_stop_event.set()

    def _ensure_typing_heartbeat_thread(self) -> None:
        if self._typing_heartbeat_thread is not None and self._typing_heartbeat_thread.is_alive():
            return

        self._typing_heartbeat_stop_event.clear()
        self._typing_heartbeat_thread = threading.Thread(
            target=self._typing_heartbeat_loop,
            name="dialogs-typing-heartbeat",
            daemon=True,
        )
        self._typing_heartbeat_thread.start()

    def _typing_heartbeat_loop(self) -> None:
        heartbeat_interval_sec = 5.0
        sleep_interval_sec = 0.25
        while True:
            if self._typing_heartbeat_stop_event.is_set():
                break

            active_chats = set(self._active_typing_chats)
            if not active_chats:
                break

            now = time.time()
            for chat_id in active_chats:
                last_heartbeat = self._typing_last_heartbeat_at.get(chat_id)
                if last_heartbeat is None:
                    self._typing_last_heartbeat_at[chat_id] = now
                    continue

                if now - last_heartbeat >= heartbeat_interval_sec:
                    self._enqueue_weak_command(
                        self._build_change_my_typing_command(chat_id, start=True),
                    )
                    self._typing_last_heartbeat_at[chat_id] = now

            for chat_id in list(self._typing_last_heartbeat_at):
                if chat_id not in self._active_typing_chats:
                    self._typing_last_heartbeat_at.pop(chat_id, None)

            if self._typing_heartbeat_stop_event.wait(sleep_interval_sec):
                break

        self._typing_heartbeat_thread = None

    def _normalize_typing_chat_id(self, chat_id: Any) -> str:
        if isinstance(chat_id, dict):
            value = chat_id.get("id")
        elif hasattr(chat_id, "id"):
            value = getattr(chat_id, "id")
        else:
            value = chat_id

        if value is None:
            return ""

        try:
            return str(int(value))
        except Exception:
            return str(value)

    def _load_loading_phrases(self) -> list[str]:
        if self._dialogs_loading_phrases_cache is not None:
            return list(self._dialogs_loading_phrases_cache)

        fallback = ["_Хмм... дайте подумать..._"]
        try:
            payload = json.loads(self._dialogs_loading_phrases_path.read_text(encoding="utf-8"))
            phrases = [str(item).strip() for item in payload.get("phrases", []) if str(item).strip()]
            if phrases:
                self._dialogs_loading_phrases_cache = phrases
                return list(phrases)
        except Exception:
            log.warning(
                "Dialogs loading phrase file invalid; falling back to built-in list",
                exc_info=True,
            )

        self._dialogs_loading_phrases_cache = fallback
        return list(fallback)

    def send_photo(self, chat_id: Any, image_bytes: bytes, caption: str = "", mime: str = "image/png") -> tuple[bool, str]:
        if self._messaging_stub is None:
            return False, "dialogs messaging stub not initialized"

        self._ensure_generated_import_path()
        from supervisor.messaging.generated.dialogs import messaging_pb2, peers_pb2

        try:
            if caption:
                self.send_text(chat_id, caption)
            req = messaging_pb2.RequestSendMessage(
                peer=self._resolve_out_peer(chat_id, peers_pb2),
                deduplication_id=random.randint(1, (1 << 63) - 1),
                message=messaging_pb2.MessageContent(
                    binaryMessage=messaging_pb2.BinaryMessage(
                        content_tag=str(mime or "image/png"),
                        msg=image_bytes,
                    )
                ),
            )
            resp = self._send_message_request(req, metadata=self._rpc_metadata)
        except Exception as exc:
            return False, str(exc)
        return True, getattr(resp, "message_id", "ok")

    def recv_update(self, cursor: Any, timeout_sec: int = 0) -> tuple[InboundMessage | None, Any]:
        events_cursor = int(cursor or 0)
        if self._seq_stream_iter is None or int(self._seq_stream_cursor or 0) != events_cursor:
            self._seq_stream_cursor = events_cursor
            self._seq_stream_iter = self._recovering_seq_stream(events_cursor, timeout_sec)
        while True:
            try:
                box = next(self._seq_stream_iter)
            except StopIteration:
                self._seq_stream_iter = None
                return None, events_cursor

            msg = self._extract_inbound_message(box)
            events_cursor = self._update_cursor_from_box(events_cursor, box)
            self._seq_stream_cursor = events_cursor
            if msg is not None:
                return msg, events_cursor

    def _recovering_seq_stream(self, cursor: Any, timeout_sec: int):
        backoff = 1.0
        stream_cursor = int(cursor or 0)
        while True:
            stream_resolved = False
            try:
                stream_resolved = True
                for box in self._seq_stream(stream_cursor, timeout_sec):
                    stream_cursor = self._update_cursor_from_box(stream_cursor, box)
                    yield box
                backoff = 1.0
                return
            except Exception as exc:
                self._log_rpc_error("SeqUpdates", exc)
                if self._is_unauthorized_error(exc):
                    self._reset_auth_state()
                    self._reauth_with_backoff()
                    backoff = 1.0
                    continue
                if stream_resolved:
                    backoff = 1.0
                time.sleep(backoff)
                backoff = min(backoff * 2, 10.0)

    def _reauth_with_backoff(self):
        backoff = 1.0
        while True:
            try:
                self.authenticate()
                return
            except Exception:
                time.sleep(backoff)
                backoff = min(backoff * 2, 300.0)

    def _is_unauthorized_error(self, exc: Exception) -> bool:
        if grpc is None:
            return False
        code_getter = getattr(exc, "code", None)
        if callable(code_getter):
            try:
                return code_getter() == grpc.StatusCode.UNAUTHENTICATED
            except Exception:
                return False
        return False

    def _is_transient_error(self, exc: Exception) -> bool:
        if grpc is None:
            return False
        code_getter = getattr(exc, "code", None)
        if not callable(code_getter):
            return False
        try:
            code = code_getter()
        except Exception:
            return False
        return code in {
            grpc.StatusCode.UNAVAILABLE,
            grpc.StatusCode.DEADLINE_EXCEEDED,
            grpc.StatusCode.INTERNAL,
        }

    def authenticate(self):
        if self._registration_stub is None or self._auth_stub is None:
            raise RuntimeError("dialogs stubs not initialized")

        reg_req = self._build_register_request()
        reg = self._call_stub(self._registration_stub, "RegisterDevice", reg_req)
        self._auth_ticket = getattr(reg, "token", "")
        if not self._auth_ticket:
            raise RuntimeError("missing_auth_ticket")

        auth_req = self._build_start_token_auth_request()
        auth = self._call_stub(
            self._auth_stub,
            "StartTokenAuth",
            auth_req,
            metadata=self._rpc_metadata(),
        )
        self._session_token = getattr(auth, "token", "")
        self._post_auth_start_weak_stream()
        return auth

    def _post_auth_start_weak_stream(self) -> None:
        if not self._session_token:
            return
        self._start_weak_reader_thread()

    def _start_weak_reader_thread(self) -> None:
        if self._weak_reader_thread is not None and self._weak_reader_thread.is_alive():
            return
        self._weak_reader_session_token = self._session_token
        self._weak_stream_stop_event.clear()
        self._weak_reader_thread = threading.Thread(
            target=self._recovering_weak_stream,
            name="dialogs-weak-reader",
            daemon=True,
        )
        self._weak_reader_thread.start()

    def _recovering_weak_stream(self):
        backoff = 1.0
        while not self._weak_stream_stop_event.is_set():
            try:
                self._weak_stream_loop()
            except Exception as exc:
                if self._weak_stream_stop_event.is_set():
                    return
                self._log_rpc_error("WeakUpdates", exc)
                if self._is_unauthorized_error(exc):
                    self._reset_auth_state()
                    self._reauth_with_backoff()
                    continue
                time.sleep(backoff)
                backoff = min(backoff * 2, 10.0)
                continue
            if self._weak_stream_stop_event.is_set():
                return
            backoff = 1.0

    def _weak_stream_loop(self):
        try:
            for box in self._open_weak_stream():
                self._drain_weak_stream_once(box)
        except Exception:
            raise

    def _weak_request_iter(self):
        while not self._weak_stream_stop_event.is_set():
            try:
                command = self._weak_request_queue.get(timeout=0.25)
            except queue.Empty:
                continue
            yield command

    def _open_weak_stream(self):
        if self._seq_stub is None or not hasattr(self._seq_stub, "WeakUpdates"):
            raise RuntimeError("dialogs weak updates stub not initialized")
        return self._call_stub(
            self._seq_stub,
            "WeakUpdates",
            self._weak_request_iter(),
            metadata=self._rpc_metadata(),
        )

    def _drain_weak_stream_once(self, box):
        update_type = self._weak_update_type(box)
        log.info(
            "Dialogs WeakUpdate handled=False reason=ignored_inbound_update update_type=%s",
            update_type or "none",
        )

    def _weak_update_type(self, update: Any) -> str:
        if update is None:
            return ""
        which_oneof = getattr(update, "WhichOneof", None)
        if callable(which_oneof):
            try:
                return str(which_oneof("update") or "")
            except Exception:
                return ""
        return ""

    def _enqueue_weak_command(self, command):
        self._weak_request_queue.put(command)

    def _build_change_my_typing_command(self, chat_id, start):
        self._ensure_generated_import_path()
        from supervisor.messaging.generated.dialogs import peers_pb2
        from supervisor.messaging.generated.dialogs import presence_pb2
        from supervisor.messaging.generated.dialogs import sequence_and_updates_pb2

        command = sequence_and_updates_pb2.WeakUpdateCommand()
        command.change_my_typing.peer.CopyFrom(
            peers_pb2.Peer(
                type=peers_pb2.PEERTYPE_PRIVATE,
                id=int(chat_id),
            )
        )
        command.change_my_typing.type = presence_pb2.TypingType.TYPINGTYPE_TEXT
        command.change_my_typing.start = bool(start)
        return command

    def _rpc_metadata(self):
        if not self._auth_ticket:
            raise RuntimeError("missing_auth_ticket")
        return [("x-auth-ticket", self._auth_ticket)]

    def _reset_auth_state(self):
        self._auth_ticket = ""
        self._session_token = ""

    def _call_stub(self, stub: Any, method_name: str, request: Any, metadata=None):
        self._log_rpc_request(method_name)
        method = getattr(stub, method_name)
        try:
            response = self._invoke_stub_method(method, request, metadata=metadata)
        except Exception as exc:
            self._log_rpc_error(method_name, exc)
            raise
        self._log_response_errors(method_name, response)
        return response

    def _send_message_request(self, req: Any, *, metadata=None) -> Any:
        if callable(metadata):
            first_metadata = metadata()
            second_metadata = metadata
        else:
            first_metadata = metadata
            second_metadata = metadata
        try:
            return self._call_stub(
                self._messaging_stub,
                "SendMessage",
                req,
                metadata=first_metadata,
            )
        except Exception as exc:
            if not self._is_unauthorized_error(exc):
                raise
            self._reset_auth_state()
            self._reauth_with_backoff()
            if callable(second_metadata):
                second_metadata = second_metadata()
            return self._call_stub(
                self._messaging_stub,
                "SendMessage",
                req,
                metadata=second_metadata,
            )

    def _invoke_stub_method(self, method: Any, request: Any, metadata=None):
        if metadata is None:
            return method(request)
        last_exc: Exception | None = None
        try:
            return method(request, metadata=metadata)
        except TypeError as exc:
            msg = str(exc)
            last_exc = exc
            if "multiple values for argument 'metadata'" not in msg:
                raise
        try:
            if request is not None:
                return method(request)
        except TypeError as exc:
            last_exc = exc

        try:
            return method(metadata=metadata)
        except TypeError as exc:
            if "missing 1 required positional argument" in str(exc):
                raise last_exc or exc
            raise

    def _log_rpc_request(self, method_name: str) -> None:
        log.info("Dialogs gRPC request method=%s", method_name)

    def _log_rpc_error(self, method_name: str, exc: Exception) -> None:
        code = self._rpc_error_code(exc)
        details = self._rpc_error_details(exc)
        if code or details:
            log.warning(
                "Dialogs gRPC error method=%s code=%s details=%s",
                method_name,
                code or "unknown",
                details or str(exc),
            )
            return
        log.warning("Dialogs gRPC error method=%s error=%s", method_name, exc)

    def _rpc_error_code(self, exc: Exception) -> str:
        getter = getattr(exc, "code", None)
        if callable(getter):
            try:
                return str(getter() or "")
            except Exception:
                return ""
        return ""

    def _rpc_error_details(self, exc: Exception) -> str:
        getter = getattr(exc, "details", None)
        if callable(getter):
            try:
                return str(getter() or "")
            except Exception:
                return ""
        return ""

    def _log_response_errors(self, method_name: str, response: Any) -> None:
        summary = self._response_error_summary(response)
        if not summary:
            return
        log.warning("Dialogs gRPC response_error method=%s %s", method_name, summary)

    def _response_error_summary(self, response: Any) -> str:
        if response is None:
            return ""
        parts: list[str] = []

        list_fields = getattr(response, "ListFields", None)
        if callable(list_fields):
            try:
                for field, value in list_fields():
                    if self._is_error_field_name(field.name):
                        parts.append(f"{field.name}={self._safe_log_value(value)}")
            except Exception:
                parts = []
        if parts:
            return " ".join(parts)

        if hasattr(response, "__dict__"):
            for name, value in vars(response).items():
                if self._is_error_field_name(name) and self._has_error_value(value):
                    parts.append(f"{name}={self._safe_log_value(value)}")
        return " ".join(parts)

    def _is_error_field_name(self, name: str) -> bool:
        value = str(name or "")
        return value in {"error", "errors"} or value.startswith("error") or value.endswith("_error")

    def _has_error_value(self, value: Any) -> bool:
        if value is None:
            return False
        if isinstance(value, (str, bytes, list, tuple, set, dict)):
            return bool(value)
        return bool(value) or hasattr(value, "ListFields")

    def _safe_log_value(self, value: Any) -> str:
        text = str(value)
        if len(text) > 200:
            return text[:197] + "..."
        return text

    def _normalize_uuid_value(self, value: Any) -> dict[str, int] | None:
        if value is None:
            return None
        if isinstance(value, dict):
            try:
                return {"msb": int(value.get("msb")), "lsb": int(value.get("lsb"))}
            except Exception:
                return None
        try:
            return {"msb": int(value.msb), "lsb": int(value.lsb)}
        except Exception:
            return None

    def _as_dict(self, obj: Any) -> dict[str, Any]:
        if isinstance(obj, dict):
            return obj
        if obj is None:
            return {}
        if hasattr(obj, "__dict__"):
            return vars(obj)
        if hasattr(obj, "items") and callable(obj.items):
            return dict(obj)
        return {}

    def _extract_text(self, payload: Any) -> str:
        if payload is None:
            return ""
        if isinstance(payload, dict):
            value = payload.get("text")
            if isinstance(value, str):
                return value
            return str(value or "")

        which_oneof = getattr(payload, "WhichOneof", None)
        if callable(which_oneof):
            try:
                body_kind = which_oneof("body")
            except Exception:
                body_kind = None
            if body_kind == "textMessage":
                text_message = getattr(payload, "textMessage", None)
                return str(getattr(text_message, "text", "") or "")
            return ""
        return ""

    def _message_body_kind(self, payload: Any) -> str:
        if payload is None:
            return ""
        if isinstance(payload, dict):
            if "text" in payload:
                return "text"
            return ""
        which_oneof = getattr(payload, "WhichOneof", None)
        if callable(which_oneof):
            try:
                return str(which_oneof("body") or "")
            except Exception:
                return ""
        return ""

    def _peer_key(self, peer: Any) -> str:
        if isinstance(peer, dict):
            return str(peer.get("id") or "")
        if hasattr(peer, "id"):
            return str(peer.id)
        return ""

    def _peer_type(self, peer: Any) -> int | None:
        if isinstance(peer, dict):
            value = peer.get("type")
        elif hasattr(peer, "type"):
            value = getattr(peer, "type")
        else:
            return None
        try:
            return int(value)
        except Exception:
            return None

    def _sender_key(self, peer: Any):
        if isinstance(peer, dict):
            value = peer.get("id")
            if value is None:
                value = peer.get("uid")
            if value is None:
                return ""
            try:
                return int(value)
            except Exception:
                return str(value)
        for attr in ("id", "uid"):
            if hasattr(peer, attr):
                value = getattr(peer, attr)
                if value is None:
                    return ""
                try:
                    return int(value)
                except Exception:
                    return str(value)
        return ""

    def _sender_access_hash(self, peer: Any) -> int | None:
        if isinstance(peer, dict):
            value = peer.get("access_hash")
        elif hasattr(peer, "access_hash"):
            value = getattr(peer, "access_hash")
        else:
            return None
        if value is None:
            return None
        try:
            return int(value)
        except Exception:
            return None

    def _remember_private_out_peer(self, chat_id: str, peer: Any, sender_peer: Any) -> None:
        if not chat_id or self._peer_type(peer) != 1:
            return
        sender_uid = self._sender_key(sender_peer)
        access_hash = self._sender_access_hash(sender_peer)
        if sender_uid == "" or access_hash is None:
            return
        self._private_out_peers_by_chat[str(chat_id)] = {
            "id": int(sender_uid),
            "access_hash": int(access_hash),
        }

    def _ensure_stubs(self) -> None:
        if grpc is None:
            raise RuntimeError("grpc runtime is not available")
        if self._messaging_stub is not None:
            return
        if not self.cfg.dialogs_endpoint:
            raise RuntimeError("missing_dialogs_endpoint")

        self._ensure_generated_import_path()

        # Keep imports lazy to avoid hard import failures when generated files
        # are not available during unit tests.
        from supervisor.messaging.generated.dialogs import registration_pb2_grpc
        from supervisor.messaging.generated.dialogs import authentication_pb2_grpc
        from supervisor.messaging.generated.dialogs import messaging_pb2_grpc

        self._channel = self._create_channel()
        self._registration_stub = registration_pb2_grpc.RegistrationStub(self._channel)
        self._auth_stub = authentication_pb2_grpc.AuthenticationStub(self._channel)
        self._messaging_stub = messaging_pb2_grpc.MessagingStub(self._channel)
        # Some schemas expose SeqUpdates through a dedicated service.
        from supervisor.messaging.generated.dialogs import sequence_and_updates_pb2_grpc

        self._seq_stub = sequence_and_updates_pb2_grpc.SequenceAndUpdatesStub(self._channel)

    def _ensure_generated_import_path(self) -> None:
        from pathlib import Path

        generated_dir = Path(__file__).resolve().parent / "generated" / "dialogs"
        if str(generated_dir) not in sys.path:
            sys.path.insert(0, str(generated_dir))

    def _create_channel(self):
        target, is_secure = self._resolve_channel_target(self.cfg.dialogs_endpoint)
        options = self._grpc_channel_options()
        if is_secure:
            credentials = self._build_secure_channel_credentials(target)
            return grpc.secure_channel(target, credentials, options=options)
        return grpc.insecure_channel(target, options=options)

    def _grpc_channel_options(self) -> list[tuple[str, int]]:
        return [
            ("grpc.keepalive_time_ms", int(self.cfg.dialogs_grpc_keepalive_time_ms)),
            ("grpc.keepalive_timeout_ms", int(self.cfg.dialogs_grpc_keepalive_timeout_ms)),
            (
                "grpc.keepalive_permit_without_calls",
                int(bool(self.cfg.dialogs_grpc_keepalive_permit_without_calls)),
            ),
        ]

    def _resolve_channel_target(self, endpoint: str) -> tuple[str, bool]:
        value = str(endpoint or "").strip()
        if value.startswith(("grpc://", "http://")):
            return value.split("://", 1)[1], False
        if value.startswith(("grpcs://", "https://")):
            return value.split("://", 1)[1], True
        return value, False

    def _build_secure_channel_credentials(self, target: str):
        if not self.cfg.dialogs_trust_all_server_certificates:
            return grpc.ssl_channel_credentials()
        return grpc.ssl_channel_credentials(
            root_certificates=self._fetch_server_certificate_pem(target),
        )

    def _fetch_server_certificate_pem(self, target: str) -> bytes:
        host, port = self._split_target_host_port(target)
        try:
            return ssl.get_server_certificate((host, port)).encode("ascii")
        except Exception as exc:
            raise RuntimeError(f"failed_to_fetch_dialogs_server_certificate:{target}") from exc

    def _split_target_host_port(self, target: str) -> tuple[str, int]:
        if target.startswith("["):
            host, sep, remainder = target[1:].partition("]")
            if sep != "]" or not remainder.startswith(":"):
                raise RuntimeError(f"dialogs_tls_endpoint_missing_port:{target}")
            return host, int(remainder[1:])
        host, sep, port = target.rpartition(":")
        if not sep or not host or not port:
            raise RuntimeError(f"dialogs_tls_endpoint_missing_port:{target}")
        return host, int(port)

    def connect(self) -> None:
        self._ensure_stubs()

    def _seq_stream(self, cursor: Any, timeout_sec: int):
        if self._seq_stub is not None and hasattr(self._seq_stub, "SeqUpdates"):
            stub = self._seq_stub
        elif self._messaging_stub is not None and hasattr(self._messaging_stub, "SeqUpdates"):
            stub = self._messaging_stub
        else:
            return []
        req = self._build_seq_updates_request(cursor=cursor, timeout_sec=timeout_sec)
        return self._call_stub(
            stub,
            "SeqUpdates",
            req,
            metadata=self._rpc_metadata(),
        )

    def _update_cursor_from_box(self, cursor: int, box: Any) -> int:
        seq = self._box_seq(box)
        try:
            return max(int(cursor), int(seq))
        except Exception:
            return cursor

    # ---- Request builders -------------------------------------------------

    def _build_register_request(self):
        self._ensure_generated_import_path()
        from supervisor.messaging.generated.dialogs import registration_pb2

        return registration_pb2.RequestRegisterDevice(
            client_pk=b"",
            app_id=int(self.cfg.dialogs_app_id or 0),
            app_title=str(self.cfg.dialogs_app_title or "Ouroboros"),
            device_title=str(self.cfg.dialogs_device_title or "Ouroboros"),
        )

    def _build_start_token_auth_request(self):
        self._ensure_generated_import_path()
        from supervisor.messaging.generated.dialogs import authentication_pb2

        return authentication_pb2.RequestStartTokenAuth(
            token=str(self.cfg.dialogs_bot_token or ""),
        )

    def _build_send_message_request(self, peer_id: Any, text: str, deduplication_id: Any):
        self._ensure_generated_import_path()
        from supervisor.messaging.generated.dialogs import messaging_pb2, peers_pb2

        return messaging_pb2.RequestSendMessage(
            peer=self._resolve_out_peer(peer_id, peers_pb2),
            deduplication_id=int(deduplication_id),
            message=messaging_pb2.MessageContent(
                textMessage=messaging_pb2.TextMessage(
                    text=str(text),
                )
            ),
        )

    def _build_delete_message_request(self, peer_id: Any, message_uuid: dict[str, int]):
        self._ensure_generated_import_path()
        from supervisor.messaging.generated.dialogs import definitions_pb2, messaging_pb2, peers_pb2

        if isinstance(peer_id, dict):
            peer_value = peer_id.get("id")
        else:
            peer_value = peer_id

        return messaging_pb2.RequestDeleteMessage(
            peer=peers_pb2.Peer(
                type=peers_pb2.PEERTYPE_PRIVATE,
                id=int(peer_value),
            ),
            message_id=definitions_pb2.UUIDValue(
                msb=int(message_uuid["msb"]),
                lsb=int(message_uuid["lsb"]),
            ),
            delete_for_user_only=False,
        )

    def _resolve_out_peer(self, peer_id: Any, peers_pb2: Any):
        if isinstance(peer_id, dict) and "id" in peer_id:
            return peers_pb2.OutPeer(
                type=int(peer_id.get("type") or peers_pb2.PEERTYPE_PRIVATE),
                id=int(peer_id["id"]),
                access_hash=int(peer_id.get("access_hash") or 0),
            )

        for attr in ("id", "type"):
            if not hasattr(peer_id, attr):
                break
        else:
            return peers_pb2.OutPeer(
                type=int(getattr(peer_id, "type") or peers_pb2.PEERTYPE_PRIVATE),
                id=int(getattr(peer_id, "id")),
                access_hash=int(getattr(peer_id, "access_hash", 0) or 0),
            )

        cached = self._private_out_peers_by_chat.get(str(peer_id))
        if cached is not None:
            return peers_pb2.OutPeer(
                type=peers_pb2.PEERTYPE_PRIVATE,
                id=int(cached["id"]),
                access_hash=int(cached["access_hash"]),
            )

        return peers_pb2.OutPeer(
            type=peers_pb2.PEERTYPE_PRIVATE,
            id=int(peer_id),
        )

    def _build_seq_updates_request(self, cursor: Any, timeout_sec: int):
        from google.protobuf import empty_pb2

        return empty_pb2.Empty()
