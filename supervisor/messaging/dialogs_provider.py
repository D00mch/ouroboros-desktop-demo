from __future__ import annotations

import json
import logging
import queue
import random
import threading
from pathlib import Path
from typing import Any

from supervisor.messaging.base import InboundMessage
from supervisor.runtime_config import RuntimeConfig

log = logging.getLogger(__name__)

DEFAULT_DIALOGS_GROUP_ID = 2112986678


class DialogsProvider:
    name = "dialogs"

    def __init__(self, cfg: RuntimeConfig):
        self.cfg = cfg
        self._dialogs_loading_phrases_path = (
            Path(__file__).resolve().with_name("dialogs_loading_phrases.json")
        )
        self._dialogs_loading_phrases_cache: list[str] | None = None
        self._bot = None
        self._group_peer = None
        self._group_peer_by_id: dict[str, Any] = {}
        self._incoming: queue.Queue[InboundMessage] = queue.Queue()
        self._cursor = 0
        self._bot_lock = threading.RLock()
        self._handlers_registered = False
        self._updates_thread: threading.Thread | None = None
        self._updates_stop_event = threading.Event()
        self._last_updates_error = ""

    def connect(self) -> None:
        self._ensure_bot()

    def authenticate(self) -> None:
        self._ensure_bot()
        self._register_handlers()
        self._resolve_group_peer()
        self._ensure_updates_thread()

    def send_text(self, chat_id: Any, text: str, fmt: str = "") -> tuple[bool, str]:
        if self._bot is None:
            return False, "dialogs sdk bot not initialized"

        peer = self._resolve_out_peer(chat_id)
        if peer is None:
            return False, f"dialogs group peer is not available for chat_id={chat_id!r}"

        clean_text = str(text or "")
        if not clean_text:
            return True, "empty"

        messaging = getattr(self._bot, "messaging", None)
        for method_name in ("send_message_sync", "send_message"):
            method = getattr(messaging, method_name, None)
            if not callable(method):
                continue
            try:
                response = method(peer, clean_text)
            except Exception as exc:
                log.warning("Dialogs SDK send failed method=%s error=%s", method_name, exc)
                return False, str(exc)
            return True, str(
                getattr(response, "message_id", None)
                or getattr(response, "mid", None)
                or "ok"
            )

        return False, "dialogs sdk messaging send method is not available"

    def send_loading_phrase(self, chat_id: Any) -> dict[str, Any] | None:
        # The SDK path does not expose a stable message id for follow-up deletion
        # across the versions used by SberChat, so avoid leaving transient messages
        # in the group.
        return None

    def delete_loading_message(self, chat_id: Any, message_uuid: dict[str, Any]) -> bool:
        return False

    def send_typing(self, chat_id: Any) -> bool:
        return False

    def begin_reply_typing(self, chat_id: Any) -> None:
        return None

    def end_reply_typing(self, chat_id: Any) -> None:
        return None

    def send_photo(
        self,
        chat_id: Any,
        image_bytes: bytes,
        caption: str = "",
        mime: str = "image/png",
    ) -> tuple[bool, str]:
        if caption:
            return self.send_text(chat_id, caption)
        return False, "dialogs sdk photo sending is not implemented"

    def recv_update(self, cursor: Any, timeout_sec: int = 0) -> tuple[InboundMessage | None, Any]:
        self._ensure_updates_thread()
        try:
            self._cursor = max(int(self._cursor or 0), int(cursor or 0))
        except Exception:
            pass

        timeout = max(float(timeout_sec or 0), 0.25)
        try:
            message = self._incoming.get(timeout=timeout)
        except queue.Empty:
            return None, self._cursor

        self._cursor += 1
        return message, self._cursor

    def _ensure_bot(self):
        if self._bot is not None:
            return self._bot

        with self._bot_lock:
            if self._bot is not None:
                return self._bot

            try:
                from dialog_bot_sdk.bot import DialogBot
            except Exception as exc:
                raise RuntimeError(
                    "dialog-bot-sdk is not installed; install the dialog-bot-sdk package"
                ) from exc

            bot_config = self._build_bot_config()
            self._bot = self._create_sdk_bot(DialogBot, bot_config)
            return self._bot

    def _create_sdk_bot(self, dialog_bot_cls: Any, bot_config: dict[str, Any]):
        create_bot = getattr(dialog_bot_cls, "create_bot", None)
        if callable(create_bot):
            return create_bot(bot_config)

        endpoint = str(bot_config.get("endpoint") or "")
        token = str(bot_config.get("token") or "")
        is_secure = bool(bot_config.get("is_secure"))
        if is_secure:
            secure_factory = getattr(dialog_bot_cls, "get_secure_bot", None)
            if callable(secure_factory):
                try:
                    import grpc
                except Exception as exc:
                    raise RuntimeError("grpc is required by dialog-bot-sdk get_secure_bot") from exc
                root_certificates = self._read_root_certificates_bytes(
                    bot_config.get("root_certificates"),
                )
                credentials = grpc.ssl_channel_credentials(root_certificates=root_certificates)
                return secure_factory(endpoint, credentials, token)

        for method_name in ("get_insecure_bot", "get_unsecure_bot"):
            factory = getattr(dialog_bot_cls, method_name, None)
            if callable(factory):
                return factory(endpoint, token)

        raise RuntimeError("dialog-bot-sdk DialogBot factory method is not available")

    def _read_root_certificates_bytes(self, path_value: Any) -> bytes | None:
        path_text = str(path_value or "").strip()
        if not path_text:
            return None
        try:
            return Path(path_text).expanduser().read_bytes()
        except Exception as exc:
            raise RuntimeError(f"failed to read Dialogs root certificates: {path_text}") from exc

    def _build_bot_config(self) -> dict[str, Any]:
        endpoint, is_secure = self._sdk_endpoint_and_security(self.cfg.dialogs_endpoint)
        config: dict[str, Any] = {
            "endpoint": endpoint,
            "token": str(self.cfg.dialogs_bot_token or ""),
            "is_secure": bool(is_secure),
        }

        root_certificates = self._root_certificates_path()
        if root_certificates:
            config["root_certificates"] = root_certificates

        return config

    def _sdk_endpoint_and_security(self, endpoint: str) -> tuple[str, bool]:
        value = str(endpoint or "").strip()
        if not value:
            return "epbotsift.sberchat.sberbank.ru:443", True
        if value.startswith(("https://", "grpcs://")):
            return value.split("://", 1)[1], True
        if value.startswith(("http://", "grpc://")):
            return value.split("://", 1)[1], False
        return value, True

    def _root_certificates_path(self) -> str:
        raw = str(getattr(self.cfg, "dialogs_root_certificates", "") or "").strip()
        if not raw:
            default_path = Path("~/ru_certs/russian_trusted_bundle.pem").expanduser()
            return str(default_path) if default_path.exists() else ""
        return str(Path(raw).expanduser())

    def _register_handlers(self) -> None:
        if self._handlers_registered:
            return
        bot = self._ensure_bot()

        try:
            from dialog_bot_sdk.entities.messaging import MessageContentType, MessageHandler
            from dialog_bot_sdk.entities.peers import PeerType
        except Exception as exc:
            raise RuntimeError("dialog-bot-sdk messaging entities are not available") from exc

        handler = self._build_message_handler(
            MessageHandler,
            self._on_text_message,
            MessageContentType.TEXT_MESSAGE,
            PeerType.PEERTYPE_GROUP,
        )
        bot.messaging.message_handler([handler])
        self._handlers_registered = True

    def _build_message_handler(self, handler_cls, callback, content_type, peer_type):
        try:
            return handler_cls(callback, content_type, peer_type=peer_type)
        except TypeError:
            return handler_cls(callback, content_type)

    def _ensure_updates_thread(self) -> None:
        if self._bot is None:
            return
        if self._updates_thread is not None and self._updates_thread.is_alive():
            return

        self._updates_stop_event.clear()
        self._updates_thread = threading.Thread(
            target=self._updates_loop,
            name="dialogs-sdk-updates",
            daemon=True,
        )
        self._updates_thread.start()

    def _updates_loop(self) -> None:
        while not self._updates_stop_event.is_set():
            try:
                self._bot.updates.on_updates(
                    do_read_message=True,
                    do_register_commands=True,
                )
                self._last_updates_error = ""
            except Exception as exc:
                self._last_updates_error = str(exc)
                log.warning("Dialogs SDK updates loop failed: %s", exc)

            if self._updates_stop_event.wait(5.0):
                return

    def _on_text_message(self, message: Any) -> None:
        try:
            inbound, reason = self._normalize_sdk_update_message(message)
            log.info(
                "Dialogs SDK message handled=%s reason=%s chat_id=%s user_id=%s text_len=%s",
                inbound is not None,
                reason,
                getattr(inbound, "chat_id", ""),
                getattr(inbound, "user_id", ""),
                len(getattr(inbound, "text", "") or ""),
            )
            if inbound is not None:
                self._incoming.put(inbound)
        except Exception:
            log.exception("Dialogs SDK message handler failed")

    def _normalize_sdk_update_message(self, update: Any) -> tuple[InboundMessage | None, str]:
        peer = getattr(update, "peer", None)
        if not self._is_configured_group_peer(peer):
            return None, "ignored_peer"

        sender_peer = getattr(update, "sender_peer", None)
        if self._is_self_sender(sender_peer):
            return None, "ignored_self_message"

        original_text = self._extract_text(update)
        if not original_text:
            return None, "empty_text"

        self._remember_group_peer(peer)
        group_id = str(self._group_id())
        return InboundMessage(
            chat_id=group_id,
            user_id=group_id,
            text=original_text,
            caption="",
            image_data=None,
            raw_command=original_text if str(original_text).startswith("/") else "",
        ), "accepted_group_text"

    def _is_configured_group_peer(self, peer: Any) -> bool:
        peer_id = self._peer_id(peer)
        group_id = self._group_id()
        if peer_id is None or peer_id != group_id:
            return False

        peer_type = self._peer_type(peer)
        if peer_type is None:
            return True

        try:
            from dialog_bot_sdk.entities.peers import PeerType
            group_type = int(PeerType.PEERTYPE_GROUP)
        except Exception:
            group_type = 2
        return int(peer_type) == group_type

    def _is_self_sender(self, sender_peer: Any) -> bool:
        sender_id = self._sender_id(sender_peer)
        if sender_id is None or self._bot is None:
            return False

        user_info = getattr(self._bot, "user_info", None)
        user = getattr(user_info, "user", None)
        self_peer = getattr(user, "peer", None)
        self_id = self._sender_id(self_peer)
        return self_id is not None and int(sender_id) == int(self_id)

    def _extract_text(self, update: Any) -> str:
        message = getattr(update, "message", None)
        if message is None:
            return ""

        for attr in ("text_message", "textMessage"):
            text_message = getattr(message, attr, None)
            text = getattr(text_message, "text", None)
            if text is not None:
                return str(text or "")

        if isinstance(message, dict):
            text_message = message.get("text_message") or message.get("textMessage")
            if isinstance(text_message, dict):
                return str(text_message.get("text") or "")
            return str(message.get("text") or "")

        return ""

    def _resolve_out_peer(self, chat_id: Any):
        if self._bot is None:
            return None

        if hasattr(chat_id, "id"):
            chat_peer_id = self._peer_id(chat_id)
            if chat_peer_id == self._group_id():
                return chat_id

        if isinstance(chat_id, dict):
            chat_peer_id = self._peer_id(chat_id)
            if chat_peer_id == self._group_id():
                return chat_id

        key = str(self._group_id())
        if str(chat_id) != key:
            return None

        cached_peer = self._group_peer_by_id.get(key)
        if cached_peer is not None:
            return cached_peer

        return self._resolve_group_peer()

    def _resolve_group_peer(self):
        if self._group_peer is not None:
            return self._group_peer
        if self._bot is None:
            return None

        group_id = self._group_id()
        groups = getattr(self._bot, "groups", None)
        finder = getattr(groups, "find_group_by_id_sync", None)
        if callable(finder):
            try:
                group = finder(group_id)
                peer = getattr(group, "peer", None)
                if peer is not None:
                    self._remember_group_peer(peer)
                    return peer
            except Exception as exc:
                log.warning("Dialogs SDK failed to resolve group %s: %s", group_id, exc)

        peer = self._build_group_peer(group_id)
        if peer is not None:
            self._remember_group_peer(peer)
        return peer

    def _build_group_peer(self, group_id: int):
        peer_type = self._sdk_group_peer_type()
        for module_name in (
            "dialog_bot_sdk.entities.peers",
            "dialog_bot_sdk.entities.messaging",
        ):
            try:
                module = __import__(module_name, fromlist=["Peer"])
                peer_cls = getattr(module, "Peer")
            except Exception:
                continue

            for args, kwargs in (
                ((), {"type": peer_type, "id": group_id}),
                ((peer_type, group_id), {}),
            ):
                try:
                    return peer_cls(*args, **kwargs)
                except TypeError:
                    continue
        return None

    def _sdk_group_peer_type(self):
        try:
            from dialog_bot_sdk.entities.peers import PeerType
            return PeerType.PEERTYPE_GROUP
        except Exception:
            return 2

    def _remember_group_peer(self, peer: Any) -> None:
        peer_id = self._peer_id(peer)
        if peer_id != self._group_id():
            return
        self._group_peer = peer
        self._group_peer_by_id[str(peer_id)] = peer

    def _group_id(self) -> int:
        try:
            value = int(getattr(self.cfg, "dialogs_group_id", 0) or 0)
        except Exception:
            value = 0
        return value or DEFAULT_DIALOGS_GROUP_ID

    def _peer_id(self, peer: Any) -> int | None:
        if isinstance(peer, dict):
            value = peer.get("id")
        else:
            value = getattr(peer, "id", None)
        return self._as_int_or_none(value)

    def _sender_id(self, peer: Any) -> int | None:
        if isinstance(peer, dict):
            value = peer.get("id")
            if value is None:
                value = peer.get("uid")
        else:
            value = getattr(peer, "id", None)
            if value is None:
                value = getattr(peer, "uid", None)
        return self._as_int_or_none(value)

    def _peer_type(self, peer: Any) -> int | None:
        if isinstance(peer, dict):
            value = peer.get("type")
        else:
            value = getattr(peer, "type", None)
        return self._as_int_or_none(value)

    def _as_int_or_none(self, value: Any) -> int | None:
        if value is None:
            return None
        try:
            return int(value)
        except Exception:
            return None

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

    def _random_loading_phrase(self) -> str:
        return random.choice(self._load_loading_phrases())
