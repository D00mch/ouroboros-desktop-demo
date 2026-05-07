from __future__ import annotations

import threading
from types import SimpleNamespace

from supervisor.messaging.base import InboundMessage


class _DummyProvider:
    def __init__(self, messages=None, recv_cursor=0):
        self.messages = list(messages or [])
        self.recv_cursor = recv_cursor
        self.connect_calls = 0
        self.authenticate_calls = 0
        self.text_calls = []

    def connect(self):
        self.connect_calls += 1

    def authenticate(self):
        self.authenticate_calls += 1

    def send_text(self, chat_id, text: str, fmt: str = ""):
        self.text_calls.append((chat_id, text, fmt))
        return True, "ok"

    def recv_update(self, cursor, timeout_sec: int = 0):
        if not self.messages:
            return None, self.recv_cursor
        return self.messages.pop(0), self.recv_cursor


class _DummyBridge:
    def send_message(self, *_args, **_kwargs):
        return True, "ok"

    def send_chat_action(self, *_args, **_kwargs):
        return True

    def send_photo(self, *_args, **_kwargs):
        return True, "ok"


def test_runtime_config_reads_dialogs_settings_and_data_dir(tmp_path):
    from supervisor.runtime_config import load_runtime_config

    data_dir = tmp_path / "data"
    cfg = load_runtime_config(
        env={
            "OUROBOROS_DATA_DIR": str(data_dir),
            "OUROBOROS_REPO_DIR": str(tmp_path / "repo"),
            "DIALOGS_BOT_TOKEN": "token",
            "DIALOGS_APP_ID": "12",
        },
        cwd=tmp_path,
    )

    assert cfg.drive_root == data_dir
    assert cfg.dialogs_endpoint == "epbotsift.sberchat.sberbank.ru:443"
    assert cfg.dialogs_bot_token == "token"
    assert cfg.dialogs_group_id == 2112986678
    assert cfg.dialogs_app_id == 12


def test_dialogs_transport_starts_provider_and_sends_text(tmp_path):
    from supervisor.runtime_config import RuntimeConfig
    from supervisor.server_runtime import build_server_runtime_transport

    cfg = RuntimeConfig(
        repo_dir=tmp_path,
        drive_root=tmp_path,
        launcher_path=tmp_path / "launcher.py",
        github_user="",
        github_repo="",
        dialogs_endpoint="grpc://dialogs",
        dialogs_bot_token="token",
    )
    provider = _DummyProvider()
    transport = build_server_runtime_transport(
        runtime_config=cfg,
        bridge=_DummyBridge(),
        logger=SimpleNamespace(warning=lambda *_a, **_k: None, info=lambda *_a, **_k: None),
        dialogs_provider_factory=lambda _cfg: provider,
    )

    transport.send_with_budget("peer-42", "hello", fmt="markdown")

    assert transport.provider_active is True
    assert provider.connect_calls == 1
    assert provider.authenticate_calls == 1
    assert provider.text_calls == [("peer-42", "hello", "markdown")]


def test_handle_runtime_inbound_preserves_sberchat_peer_id(tmp_path):
    from supervisor import state
    from supervisor.server_runtime import handle_runtime_inbound

    state.init(tmp_path, 1000.0)
    state.save_state(state.default_state_dict())
    observed = {}
    called = threading.Event()

    def handle_chat_direct(chat_id, text, image_data=None, task_id="", on_terminal=None):
        observed.update(
            chat_id=chat_id,
            text=text,
            image_data=image_data,
            task_id=task_id,
            on_terminal=on_terminal,
        )
        called.set()

    ctx = SimpleNamespace(
        load_state=state.load_state,
        save_state=state.save_state,
        send_with_budget=lambda *_a, **_k: None,
        get_chat_agent=lambda: SimpleNamespace(_busy=False),
        handle_chat_direct=handle_chat_direct,
        dialogs_reply_tokens={},
        runtime_transport=SimpleNamespace(provider=None),
    )

    handled = handle_runtime_inbound(
        source="dialogs",
        message=InboundMessage(chat_id="peer-42", user_id="user-42", text="hello"),
        cursor=15,
        ctx=ctx,
    )
    st = state.load_state()

    assert handled is True
    assert called.wait(1.0)
    assert st["owner_chat_id"] == "peer-42"
    assert st["owner_chat_source"] == "dialogs"
    assert st["provider_state"]["dialogs"]["seq"] == 15
    assert observed["chat_id"] == "peer-42"


def test_dialogs_provider_treats_configured_group_as_single_user(tmp_path):
    from supervisor.messaging.dialogs_provider import DialogsProvider
    from supervisor.runtime_config import RuntimeConfig

    cfg = RuntimeConfig(
        repo_dir=tmp_path,
        drive_root=tmp_path,
        launcher_path=tmp_path / "launcher.py",
        github_user="",
        github_repo="",
        dialogs_endpoint="epbotsift.sberchat.sberbank.ru:443",
        dialogs_bot_token="token",
        dialogs_group_id=2112986678,
    )
    provider = DialogsProvider(cfg)
    update = SimpleNamespace(
        peer=SimpleNamespace(id=2112986678, type=2),
        sender_peer=SimpleNamespace(id=100500),
        message=SimpleNamespace(text_message=SimpleNamespace(text="hello group")),
    )

    inbound, reason = provider._normalize_sdk_update_message(update)

    assert reason == "accepted_group_text"
    assert inbound.chat_id == "2112986678"
    assert inbound.user_id == "2112986678"
    assert inbound.text == "hello group"


def test_dialogs_provider_ignores_other_groups(tmp_path):
    from supervisor.messaging.dialogs_provider import DialogsProvider
    from supervisor.runtime_config import RuntimeConfig

    cfg = RuntimeConfig(
        repo_dir=tmp_path,
        drive_root=tmp_path,
        launcher_path=tmp_path / "launcher.py",
        github_user="",
        github_repo="",
        dialogs_endpoint="epbotsift.sberchat.sberbank.ru:443",
        dialogs_bot_token="token",
        dialogs_group_id=2112986678,
    )
    provider = DialogsProvider(cfg)
    update = SimpleNamespace(
        peer=SimpleNamespace(id=999, type=2),
        sender_peer=SimpleNamespace(id=100500),
        message=SimpleNamespace(text_message=SimpleNamespace(text="hello")),
    )

    inbound, reason = provider._normalize_sdk_update_message(update)

    assert inbound is None
    assert reason == "ignored_peer"


def test_send_message_event_preserves_string_chat_id():
    from supervisor import events

    calls = []
    ctx = SimpleNamespace(
        send_with_budget=lambda *args, **kwargs: calls.append((args, kwargs)),
        clear_dialogs_reply_token=lambda *_a, **_k: None,
        clear_dialogs_loading_phrase=lambda *_a, **_k: None,
        append_jsonl=lambda *_a, **_k: None,
        DRIVE_ROOT=".",
    )

    events._handle_send_message(
        {"chat_id": "peer-42", "text": "hello", "task_id": "task-1"},
        ctx,
    )

    assert calls[0][0][0] == "peer-42"
