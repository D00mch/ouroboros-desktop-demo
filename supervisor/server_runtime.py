"""Helpers for server-side supervisor bootstrap.

Extracted from server.py to keep the main entrypoint within repo size limits
without changing runtime behavior.
"""

from __future__ import annotations

import threading
from pathlib import Path
from datetime import datetime, timezone
from types import SimpleNamespace
import uuid
from typing import Any

from supervisor.messaging.base import InboundMessage
from supervisor.messaging.dialogs_provider import DialogsProvider


def bootstrap_repo_runtime(*, settings: dict, repo_dir, ensure_repo_present, safe_restart, logger) -> None:
    """Run the guarded repo bootstrap sequence used by the local server runtime."""
    code_intact = (repo_dir / "server.py").exists() or (repo_dir / "ouroboros").is_dir()
    repo_slug = settings.get("GITHUB_REPO", "")
    gh_token = settings.get("GITHUB_TOKEN", "")
    has_remote = bool(repo_slug and gh_token)

    if code_intact and not has_remote:
        logger.warning(
            "SAFETY: Skipping git bootstrap — code directory is intact "
            "but no GITHUB_REPO/TOKEN configured. Set them in Settings "
            "to enable self-update."
        )
        return

    ensure_repo_present()
    if has_remote:
        from supervisor.git_ops import configure_remote

        configure_remote(repo_slug, gh_token)
    ok, msg = safe_restart(reason="bootstrap", unsynced_policy="rescue_and_reset")
    if not ok:
        logger.error("Supervisor bootstrap failed: %s", msg)


def _safe_invoke(callable_obj: Any, *args: Any, **kwargs: Any) -> None:
    """Invoke callback while suppressing transport-level failures."""
    try:
        callable_obj(*args, **kwargs)
    except Exception:
        pass


def _register_dialogs_reply_token(ctx: Any, token: str, chat_id: Any) -> None:
    token = str(token)
    if not token:
        return

    registry = getattr(ctx, "dialogs_reply_tokens", None)
    if not isinstance(registry, dict):
        return

    token_meta = {
        "chat_id": str(chat_id),
        "origin": "dialogs",
        "loading_phrase_deleted": False,
    }

    runtime_transport = getattr(ctx, "runtime_transport", None)
    provider = getattr(runtime_transport, "provider", None)
    begin_reply_typing = getattr(provider, "begin_reply_typing", None)
    if callable(begin_reply_typing):
        _safe_invoke(begin_reply_typing, str(chat_id))

    existing_meta = registry.get(token)
    delete_loading_message = getattr(provider, "delete_loading_message", None)
    if (
        callable(delete_loading_message)
        and isinstance(existing_meta, dict)
        and existing_meta.get("loading_message_uuid")
        and not existing_meta.get("loading_phrase_deleted")
    ):
        _safe_invoke(
            delete_loading_message,
            existing_meta.get("chat_id") or str(chat_id),
            existing_meta.get("loading_message_uuid"),
        )

    send_loading_phrase = getattr(provider, "send_loading_phrase", None)
    if callable(send_loading_phrase):
        try:
            loading_meta = send_loading_phrase(str(chat_id))
        except Exception:
            loading_meta = None
        if isinstance(loading_meta, dict):
            token_meta.update(loading_meta)

    registry[token] = token_meta


def _clear_dialogs_reply_token(ctx: Any, token: str) -> None:
    token = str(token)
    if not token:
        return

    registry = getattr(ctx, "dialogs_reply_tokens", None)
    if not isinstance(registry, dict):
        return

    meta = registry.pop(token, None)
    if not isinstance(meta, dict):
        return

    runtime_transport = getattr(ctx, "runtime_transport", None)
    provider = getattr(runtime_transport, "provider", None)
    delete_loading_message = getattr(provider, "delete_loading_message", None)
    if callable(delete_loading_message) and meta.get("loading_message_uuid"):
        _safe_invoke(
            delete_loading_message,
            meta.get("chat_id"),
            meta.get("loading_message_uuid"),
        )
    end_reply_typing = getattr(provider, "end_reply_typing", None)
    if callable(end_reply_typing):
        _safe_invoke(end_reply_typing, meta.get("chat_id"))


def _clear_dialogs_loading_phrase(ctx: Any, token: str) -> None:
    token = str(token)
    if not token:
        return

    registry = getattr(ctx, "dialogs_reply_tokens", None)
    if not isinstance(registry, dict):
        return

    meta = registry.get(token)
    if not isinstance(meta, dict):
        return

    loading_message_uuid = meta.get("loading_message_uuid")
    if not loading_message_uuid:
        return

    runtime_transport = getattr(ctx, "runtime_transport", None)
    provider = getattr(runtime_transport, "provider", None)
    delete_loading_message = getattr(provider, "delete_loading_message", None)
    if not callable(delete_loading_message):
        return

    try:
        deleted = delete_loading_message(meta.get("chat_id"), loading_message_uuid)
    except Exception:
        return
    if deleted is False:
        return

    meta["loading_phrase_deleted"] = True
    meta.pop("loading_message_uuid", None)


def _clear_all_dialogs_reply_tokens(ctx: Any) -> None:
    registry = getattr(ctx, "dialogs_reply_tokens", None)
    if not isinstance(registry, dict) or not registry:
        return

    for token in list(registry.keys()):
        _clear_dialogs_reply_token(ctx, token)


def _dispatch_dialogs_direct_turn(ctx: Any, chat_id: Any, text: str) -> None:
    token = uuid.uuid4().hex[:8]
    _register_dialogs_reply_token(ctx, token, chat_id)

    handle_chat_direct = getattr(ctx, "handle_chat_direct", None)
    if not callable(handle_chat_direct):
        return

    on_terminal = getattr(ctx, "on_direct_chat_terminal", None)
    kwargs = {"task_id": token}
    if callable(on_terminal):
        kwargs["on_terminal"] = on_terminal
    handle_chat_direct(chat_id, text, None, **kwargs)


def _dispatch_dialogs_busy_injection(ctx: Any, agent: Any, chat_id: Any, text: str) -> None:
    token = getattr(agent, "current_task_id", None) or getattr(agent, "_current_task_id", None)
    if token:
        _register_dialogs_reply_token(ctx, token, chat_id)

    inject_message = getattr(agent, "inject_message", None)
    if callable(inject_message):
        inject_message(text)


def make_send_with_budget_fanout(*, send_with_budget: Any, bridge_send_message: Any = None):
    """Build a send helper that fans out between provider send path and web bridge."""

    def _send_with_budget(
        chat_id: Any,
        text: str,
        log_text: str | None = None,
        force_budget: bool = False,
        fmt: str = "",
        is_progress: bool = False,
        task_id: str = "",
        ts: str | None = None,
    ):
        if send_with_budget is not None:
            _safe_invoke(
                send_with_budget,
                chat_id,
                text,
                log_text=log_text,
                force_budget=force_budget,
                fmt=fmt,
                is_progress=is_progress,
            )

        if bridge_send_message is not None:
            bridge_text = text
            parse_mode = "markdown" if fmt == "markdown" else ""
            _safe_invoke(
                bridge_send_message,
                chat_id,
                bridge_text,
                parse_mode=parse_mode,
                ts=ts,
                is_progress=is_progress,
                task_id=task_id,
            )

    return _send_with_budget


def make_send_typing_fanout(*, send_typing: Any = None, send_chat_action: Any = None):
    """Build a typing helper that fans out to provider and web bridge."""

    def _send_typing(chat_id: Any) -> None:
        if send_typing is not None:
            _safe_invoke(send_typing, chat_id)
        if send_chat_action is not None:
            _safe_invoke(send_chat_action, chat_id, "typing")

    return _send_typing


def make_send_photo_fanout(*, send_photo: Any = None, send_bridge_photo: Any = None):
    """Build a photo helper that fans out to provider and web bridge."""

    def _send_photo(chat_id: Any, image_bytes: bytes, caption: str = "", mime: str = "image/png") -> None:
        if send_photo is not None:
            _safe_invoke(send_photo, chat_id, image_bytes, caption=caption, mime=mime)
        if send_bridge_photo is not None:
            _safe_invoke(send_bridge_photo, chat_id, image_bytes, caption=caption, mime=mime)

    return _send_photo


def persist_dialogs_cursor_state(state: dict, cursor: Any) -> None:
    """Persist Dialogs cursor/seq into runtime state."""
    if cursor is None:
        return

    provider_state = state.get("provider_state")
    if not isinstance(provider_state, dict):
        provider_state = {}
        state["provider_state"] = provider_state

    dialogs_state = provider_state.get("dialogs")
    if not isinstance(dialogs_state, dict):
        dialogs_state = {"seq": 0, "state": ""}
        provider_state["dialogs"] = dialogs_state

    try:
        dialogs_state["seq"] = int(cursor)
    except (TypeError, ValueError):
        # Keep prior cursor if conversion fails.
        return


def _dialogs_runtime_outbound_drive_root(runtime_config: Any) -> Path:
    return (
        getattr(runtime_config, "drive_root", None)
        or getattr(runtime_config, "repo_dir", None)
        or Path(".")
    )


def _make_runtime_transport_send_with_budget(transport: Any):
    def _send_with_budget(
        chat_id: Any,
        text: str,
        log_text: str | None = None,
        force_budget: bool = False,
        fmt: str = "",
        is_progress: bool = False,
        task_id: str = "",
        ts: str | None = None,
    ):
        provider = getattr(transport, "provider", None)
        if provider is None:
            return None
        try:
            return provider.send_text(chat_id, text, fmt=fmt)
        except Exception as exc:
            logger = getattr(transport, "logger", None)
            if logger is not None:
                logger.warning("Dialogs send failed: %s", exc)
            return False, str(exc)

    return _send_with_budget


def _make_runtime_transport_send_typing(transport: Any):
    def _send_typing(chat_id: Any):
        provider = getattr(transport, "provider", None)
        send_typing = getattr(provider, "send_typing", None)
        if callable(send_typing):
            return send_typing(chat_id)
        return None

    return _send_typing


def _make_runtime_transport_send_photo(transport: Any):
    def _send_photo(chat_id: Any, image_bytes: bytes, caption: str = "", mime: str = "image/png"):
        provider = getattr(transport, "provider", None)
        send_photo = getattr(provider, "send_photo", None)
        if callable(send_photo):
            try:
                return send_photo(chat_id, image_bytes, caption=caption, mime=mime)
            except TypeError:
                return send_photo(chat_id, image_bytes, caption=caption)
        return None

    return _send_photo


def ensure_dialogs_runtime_transport_provider(transport: Any):
    """Ensure the Dialogs runtime transport has an authenticated provider."""
    provider = getattr(transport, "provider", None)
    if provider is not None:
        transport.provider_active = True
        return provider

    provider_lock = getattr(transport, "_provider_lock", None)
    if provider_lock is None:
        provider_lock = threading.Lock()
        transport._provider_lock = provider_lock

    with provider_lock:
        provider = getattr(transport, "provider", None)
        if provider is not None:
            transport.provider_active = True
            return provider

        logger = getattr(transport, "logger", None)
        had_startup_error = bool(getattr(transport, "startup_error", None))

        try:
            runtime_config = transport.runtime_config
            dialogs_provider_factory = transport.dialogs_provider_factory
            provider = dialogs_provider_factory(runtime_config)
            provider.connect()
            provider.authenticate()
        except Exception as exc:
            transport.provider = None
            transport.provider_active = False
            transport.startup_error = str(exc)
            if logger is not None:
                logger.warning("Dialogs runtime startup failed, keeping local transport: %s", exc)
            return None

        transport.provider = provider
        transport.provider_active = True
        transport.startup_error = None
        if logger is not None and had_startup_error and callable(getattr(logger, "info", None)):
            logger.info("Dialogs runtime transport recovered; SeqUpdates retry loop is active again.")
        return provider


def build_server_runtime_transport(
    *,
    runtime_config,
    bridge,
    logger,
    dialogs_provider_factory=DialogsProvider,
):
    """Build runtime transport state used by server.py loops.

    Returns an object with provider details and provider-aware sender callables.
    """

    transport = SimpleNamespace(
        runtime_config=runtime_config,
        dialogs_provider_factory=dialogs_provider_factory,
        bridge=bridge,
        logger=logger,
        provider=None,
        provider_active=False,
        startup_error=None,
        send_with_budget=None,
        send_typing=None,
        send_photo=None,
        dialogs_input_thread=None,
        _provider_lock=threading.Lock(),
    )
    transport.send_with_budget = _make_runtime_transport_send_with_budget(transport)
    transport.send_typing = _make_runtime_transport_send_typing(transport)
    transport.send_photo = _make_runtime_transport_send_photo(transport)
    ensure_dialogs_runtime_transport_provider(transport)
    return transport


def poll_runtime_inputs(
    *,
    bridge,
    local_offset: int = 0,
    logger=None,
    local_timeout: int = 1,
):
    """Read inbound messages from the local web bridge."""

    items = []
    next_local_offset = int(local_offset or 0)

    if bridge is not None:
        try:
            updates = bridge.get_updates(offset=next_local_offset, timeout=local_timeout)
        except Exception as exc:
            if logger is not None:
                logger.warning("Local web poll failed: %s", exc)
            updates = []

        for upd in updates:
            msg = _normalize_local_bridge_update(upd)
            if msg is None:
                continue

            update_id = upd.get("update_id") if isinstance(upd, dict) else None
            if update_id is not None:
                try:
                    next_local_offset = max(int(update_id), next_local_offset) + 1
                except Exception:
                    pass
            items.append(("local_web", msg, next_local_offset))

    return items, next_local_offset


def process_next_dialogs_runtime_message(*, provider, dialogs_cursor_ref: dict[str, Any], ctx: Any) -> bool:
    """Read and dispatch the next inbound Dialogs message from the live SeqUpdates stream."""
    if provider is None:
        return False

    cursor = dialogs_cursor_ref.get("value", 0)
    message, next_cursor = provider.recv_update(cursor, timeout_sec=0)
    dialogs_cursor_ref["value"] = next_cursor
    if message is None:
        return False
    return handle_runtime_inbound(
        source="dialogs",
        message=message,
        cursor=next_cursor,
        ctx=ctx,
    )


def start_dialogs_runtime_input_thread(
    *,
    runtime_transport=None,
    provider=None,
    dialogs_cursor_ref: dict[str, Any],
    ctx: Any,
    logger,
    stop_event,
):
    """Start a daemon thread that consumes Dialogs SeqUpdates continuously."""

    if runtime_transport is None and provider is None:
        return None

    def _run():
        startup_backoff_sec = 1.0
        while not stop_event.is_set():
            active_provider = provider
            if runtime_transport is not None:
                active_provider = ensure_dialogs_runtime_transport_provider(runtime_transport)
            if active_provider is None:
                if stop_event.wait(startup_backoff_sec):
                    return
                startup_backoff_sec = min(startup_backoff_sec * 2, 30.0)
                continue
            try:
                process_next_dialogs_runtime_message(
                    provider=active_provider,
                    dialogs_cursor_ref=dialogs_cursor_ref,
                    ctx=ctx,
                )
                startup_backoff_sec = 1.0
            except Exception as exc:
                if logger is not None:
                    logger.warning("Dialogs input loop failed: %s", exc)
                if stop_event.wait(0.25):
                    return

    thread = threading.Thread(target=_run, name="dialogs-input-loop", daemon=True)
    thread.start()
    return thread


def attach_dialogs_transport_fanout(event_ctx: Any, runtime_transport: Any, load_state: Any) -> Any:
    """Fan out owner-bound Dialogs replies while preserving local web delivery."""
    base_send_with_budget = event_ctx.send_with_budget
    base_send_typing = event_ctx.send_typing
    base_send_photo = event_ctx.send_photo

    def _dialogs_should_receive(chat_id: Any, task_id: str = "") -> bool:
        token_meta = event_ctx.dialogs_reply_tokens.get(str(task_id or ""))
        if isinstance(token_meta, dict) and token_meta.get("origin") == "dialogs":
            return True
        try:
            st = load_state()
        except Exception:
            return False
        if st.get("owner_chat_source") != "dialogs":
            return False
        return str(st.get("owner_chat_id") or "") == str(chat_id)

    def _send_with_dialogs_fanout(
        chat_id: Any,
        text: str,
        log_text: str | None = None,
        force_budget: bool = False,
        fmt: str = "",
        is_progress: bool = False,
        task_id: str = "",
        ts: str | None = None,
    ) -> None:
        base_send_with_budget(
            chat_id,
            text,
            log_text=log_text,
            force_budget=force_budget,
            fmt=fmt,
            is_progress=is_progress,
            task_id=task_id,
            ts=ts,
        )
        if _dialogs_should_receive(chat_id, task_id):
            runtime_transport.send_with_budget(
                chat_id,
                text,
                log_text=log_text,
                force_budget=force_budget,
                fmt=fmt,
                is_progress=is_progress,
                task_id=task_id,
                ts=ts,
            )

    def _send_typing_with_dialogs_fanout(chat_id: Any) -> None:
        base_send_typing(chat_id)
        if _dialogs_should_receive(chat_id):
            runtime_transport.send_typing(chat_id)

    def _send_photo_with_dialogs_fanout(
        chat_id: Any,
        image_bytes: bytes,
        caption: str = "",
        mime: str = "image/png",
    ) -> None:
        base_send_photo(chat_id, image_bytes, caption=caption, mime=mime)
        if _dialogs_should_receive(chat_id):
            runtime_transport.send_photo(chat_id, image_bytes, caption=caption, mime=mime)

    event_ctx.send_with_budget = _send_with_dialogs_fanout
    event_ctx.send_typing = _send_typing_with_dialogs_fanout
    event_ctx.send_photo = _send_photo_with_dialogs_fanout
    return event_ctx


def _normalize_local_bridge_update(update: Any) -> InboundMessage | None:
    """Normalize LocalChatBridge update payload into `InboundMessage`."""
    if not isinstance(update, dict):
        return None

    msg = update.get("message")
    if not isinstance(msg, dict):
        return None

    return InboundMessage(
        chat_id=1,
        user_id=1,
        text=str(msg.get("text") or ""),
    )


def prepare_supervisor_runtime(
    *,
    bridge,
    max_workers: int,
    drive_root,
    repo_dir,
    load_state,
    save_state,
    append_jsonl,
    update_budget_from_usage,
    send_with_budget,
    restore_pending_from_snapshot,
    persist_queue_snapshot,
    auto_resume_after_restart,
    get_event_q,
    WORKERS,
    PENDING,
    RUNNING,
    enqueue_task,
    cancel_task_by_id,
    queue_review_task,
    safe_restart,
    kill_workers,
    spawn_workers,
    sort_pending,
    BackgroundConsciousness,
    request_restart,
    logger,
    provider_send_with_budget: Any = None,
    provider_send_typing: Any = None,
    provider_send_photo: Any = None,
):
    from supervisor import queue as queue_module

    import types
    dialogs_reply_tokens: dict[str, dict[str, Any]] = {}

    bridge_send_message = getattr(bridge, "send_message", None)
    event_send_with_budget = send_with_budget

    if provider_send_with_budget is not None:
        event_send_with_budget = make_send_with_budget_fanout(
            send_with_budget=provider_send_with_budget,
            bridge_send_message=bridge_send_message,
        )
    event_send_typing = make_send_typing_fanout(
        send_typing=provider_send_typing,
        send_chat_action=getattr(bridge, "send_chat_action", None),
    )
    event_send_photo = make_send_photo_fanout(
        send_photo=provider_send_photo,
        send_bridge_photo=getattr(bridge, "send_photo", None),
    )

    kill_workers()
    spawn_workers(max_workers)
    restored_pending = restore_pending_from_snapshot()
    persist_queue_snapshot(reason="startup")

    if restored_pending > 0:
        st_boot = load_state()
        if st_boot.get("owner_chat_id"):
            event_send_with_budget(
                st_boot["owner_chat_id"],
                f"♻️ Restored pending queue from snapshot: {restored_pending} tasks.",
            )

    auto_resume_after_restart()

    def _get_owner_chat_id():
        try:
            st = load_state()
            return st.get("owner_chat_id")
        except Exception:
            return None

    consciousness = BackgroundConsciousness(
        drive_root=drive_root,
        repo_dir=repo_dir,
        event_queue=get_event_q(),
        owner_chat_id_fn=_get_owner_chat_id,
    )

    bg_state = load_state()
    if bg_state.get("bg_consciousness_enabled"):
        consciousness.start()
        logger.info("Background consciousness auto-restored from saved state.")

    event_ctx = types.SimpleNamespace(
        DRIVE_ROOT=drive_root,
        REPO_DIR=repo_dir,
        BRANCH_DEV="ouroboros",
        BRANCH_STABLE="ouroboros-stable",
        bridge=bridge,
        WORKERS=WORKERS,
        PENDING=PENDING,
        RUNNING=RUNNING,
        MAX_WORKERS=max_workers,
        send_with_budget=event_send_with_budget,
        send_typing=event_send_typing,
        send_photo=event_send_photo,
        load_state=load_state,
        save_state=save_state,
        update_budget_from_usage=update_budget_from_usage,
        append_jsonl=append_jsonl,
        enqueue_task=enqueue_task,
        cancel_task_by_id=cancel_task_by_id,
        queue_review_task=queue_review_task,
        persist_queue_snapshot=persist_queue_snapshot,
        safe_restart=safe_restart,
        kill_workers=kill_workers,
        spawn_workers=spawn_workers,
        sort_pending=sort_pending,
        consciousness=consciousness,
        request_restart=request_restart,
        dialogs_reply_tokens=dialogs_reply_tokens,
    )

    def _on_direct_chat_terminal(task_id: str, _chat_id: Any = None) -> None:
        _clear_dialogs_reply_token(event_ctx, task_id)

    event_ctx.on_direct_chat_terminal = _on_direct_chat_terminal
    event_ctx.clear_dialogs_reply_token = lambda task_id: _clear_dialogs_reply_token(event_ctx, task_id)
    event_ctx.clear_dialogs_loading_phrase = lambda task_id: _clear_dialogs_loading_phrase(event_ctx, task_id)
    event_ctx.clear_all_dialogs_reply_tokens = lambda: _clear_all_dialogs_reply_tokens(event_ctx)

    def _kill_workers_with_dialogs_cleanup(*args: Any, **kwargs: Any) -> None:
        _clear_all_dialogs_reply_tokens(event_ctx)
        kill_workers(*args, **kwargs)

    event_ctx.kill_workers = _kill_workers_with_dialogs_cleanup
    set_task_terminal_hook = getattr(queue_module, "set_task_terminal_hook", None)
    if callable(set_task_terminal_hook):
        set_task_terminal_hook(_on_direct_chat_terminal)

    return consciousness, event_ctx


def handle_runtime_inbound(*, source: str, message: InboundMessage, cursor: Any, ctx: Any) -> bool:
    """Handle one inbound message from a runtime source (dialogs, local_web).

    Returns True when inbound handling was invoked.
    """
    st = ctx.load_state()
    should_dispatch = True

    if source == "dialogs":
        owner_id = st.get("owner_id")
        owner_chat_id = st.get("owner_chat_id")
        local_placeholder = (owner_id == 1 and owner_chat_id == 1)
        own_owner = (str(owner_id) == str(message.user_id) and str(owner_chat_id) == str(message.chat_id))

        if owner_id is None or local_placeholder:
            st["owner_id"] = message.user_id
            st["owner_chat_id"] = message.chat_id
            st["owner_chat_source"] = "dialogs"
            owner_id = message.user_id
            owner_chat_id = message.chat_id
            own_owner = True
        elif not own_owner:
            # Ignore non-owner dialogs peers from owner command/chat path.
            should_dispatch = False
        else:
            st["owner_chat_source"] = "dialogs"

        persist_dialogs_cursor_state(st, cursor)
        ctx.save_state(st)
        if not should_dispatch:
            return True

    elif st.get("owner_id") is None:
        st["owner_id"] = message.user_id
        st["owner_chat_id"] = message.chat_id

    st["last_owner_message_at"] = datetime.now(timezone.utc).isoformat()

    ctx.save_state(st)
    return _dispatch_runtime_inbound(message=message, text=(message.text or ""), ctx=ctx)



def _dispatch_runtime_inbound(*, message: InboundMessage, text: str, ctx: Any) -> bool:
    """Dispatch non-routing inbound message behavior (commands, agent handoff)."""
    from supervisor.message_bus import log_chat
    from supervisor.state import status_text

    chat_id = message.chat_id
    user_id = message.user_id
    normalized = str(text or "")
    log_chat("in", chat_id, user_id, normalized)

    if not normalized:
        return True

    lowered = normalized.strip().lower()
    if lowered.startswith("/panic"):
        panic_handler = getattr(ctx, "execute_panic_stop", None)
        if callable(panic_handler):
            panic_handler()
        return True

    if lowered.startswith("/restart"):
        send_with_budget = ctx.send_with_budget
        send_with_budget(chat_id, "♻️ Restarting (soft).")

        safe_restart = getattr(ctx, "safe_restart", None)
        if not callable(safe_restart):
            return True

        ok, restart_msg = safe_restart(reason="owner_restart", unsynced_policy="rescue_and_reset")
        if not ok:
            send_with_budget(chat_id, f"⚠️ Restart skipped: {restart_msg}")
            return True

        kill_workers = getattr(ctx, "kill_workers", None)
        if callable(kill_workers):
            kill_workers()

        request_restart = getattr(ctx, "request_restart", None)
        if callable(request_restart):
            request_restart()
        return True

    if lowered.startswith("/review"):
        queue_review_task = getattr(ctx, "queue_review_task", None)
        if callable(queue_review_task):
            queue_review_task(reason="owner:/review", force=True)
        return True

    if lowered.startswith("/evolve"):
        parts = lowered.split()
        action = parts[1] if len(parts) > 1 else "on"
        turn_on = action not in ("off", "stop", "0")

        st = ctx.load_state()
        st["evolution_mode_enabled"] = bool(turn_on)
        if turn_on:
            st["evolution_consecutive_failures"] = 0
        ctx.save_state(st)

        if not turn_on:
            pending = getattr(ctx, "PENDING", [])
            ctx.PENDING[:] = [t for t in pending if str(t.get("type")) != "evolution"]
            sort_pending = getattr(ctx, "sort_pending", None)
            persist_queue_snapshot = getattr(ctx, "persist_queue_snapshot", None)
            if callable(sort_pending):
                sort_pending()
            if callable(persist_queue_snapshot):
                persist_queue_snapshot(reason="evolve_off")

        state_str = "ON" if turn_on else "OFF"
        ctx.send_with_budget(chat_id, f"🧬 Evolution: {state_str}")
        return True

    if lowered.startswith("/bg"):
        parts = lowered.split()
        action = parts[1] if len(parts) > 1 else "status"

        consciousness = getattr(ctx, "consciousness", None)
        st = ctx.load_state()

        if action in ("start", "on", "1"):
            result = consciousness.start() if hasattr(consciousness, "start") else "⚠️ consciousness missing"
            st["bg_consciousness_enabled"] = True
            ctx.save_state(st)
            ctx.send_with_budget(chat_id, f"🧠 {result}")
            return True

        if action in ("stop", "off", "0"):
            result = consciousness.stop() if hasattr(consciousness, "stop") else "⚠️ consciousness missing"
            st["bg_consciousness_enabled"] = False
            ctx.save_state(st)
            ctx.send_with_budget(chat_id, f"🧠 {result}")
            return True

        bg_status = "running" if getattr(consciousness, "is_running", False) else "stopped"
        ctx.send_with_budget(chat_id, f"🧠 Background consciousness: {bg_status}")
        return True

    if lowered.startswith("/status"):
        from supervisor.workers import WORKERS, PENDING, RUNNING
        soft_timeout = int(getattr(ctx, "soft_timeout", 600))
        hard_timeout = int(getattr(ctx, "hard_timeout", 1800))

        status = status_text(WORKERS, PENDING, RUNNING, soft_timeout, hard_timeout)
        ctx.send_with_budget(chat_id, status, force_budget=True)
        return True

    consciousness = getattr(ctx, "consciousness", None)
    if consciousness is not None:
        consciousness.inject_observation(f"Owner message: {normalized[:100]}")

    get_chat_agent = getattr(ctx, "_get_chat_agent", None)
    if not callable(get_chat_agent):
        get_chat_agent = getattr(ctx, "get_chat_agent", None)

    if callable(get_chat_agent):
        agent = get_chat_agent()
        if getattr(agent, "_busy", False):
            _dispatch_dialogs_busy_injection(ctx=ctx, agent=agent, chat_id=chat_id, text=normalized)
            return True

    def _run_and_resume(cid, txt):
        try:
            _dispatch_dialogs_direct_turn(ctx=ctx, chat_id=cid, text=txt)
        finally:
            if consciousness is not None and hasattr(consciousness, "resume"):
                consciousness.resume()

    if consciousness is not None and hasattr(consciousness, "pause"):
        consciousness.pause()
    threading.Thread(target=_run_and_resume, args=(chat_id, normalized), daemon=True).start()
    return True
