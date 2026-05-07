import datetime
import json
import sys
import types


def test_init_state_disables_persisted_autonomous_flags(tmp_path, monkeypatch):
    from supervisor import state

    state.init(tmp_path, 1000.0)
    st = state.default_state_dict()
    st["evolution_mode_enabled"] = True
    st["bg_consciousness_enabled"] = True
    state.save_state(st)

    monkeypatch.setattr(state, "check_openrouter_ground_truth", lambda: None)

    state.init_state()

    loaded = state.load_state()
    assert loaded["evolution_mode_enabled"] is False
    assert loaded["bg_consciousness_enabled"] is False


def test_restore_pending_from_snapshot_skips_evolution_tasks(tmp_path, monkeypatch):
    message_bus = types.ModuleType("supervisor.message_bus")
    message_bus.send_with_budget = lambda *_args, **_kwargs: None
    monkeypatch.setitem(sys.modules, "supervisor.message_bus", message_bus)

    from supervisor import queue as queue_module

    snapshot_path = tmp_path / "state" / "queue_snapshot.json"
    snapshot_path.parent.mkdir(parents=True)
    snapshot_path.write_text(
        json.dumps({
            "ts": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "pending": [
                {"task": {"id": "evo1", "type": "evolution", "chat_id": 1}},
                {"task": {"id": "task1", "type": "task", "chat_id": 1}},
            ],
        }),
        encoding="utf-8",
    )

    pending = []
    monkeypatch.setattr(queue_module, "PENDING", pending)
    monkeypatch.setattr(queue_module, "RUNNING", {})
    monkeypatch.setattr(queue_module, "QUEUE_SNAPSHOT_PATH", snapshot_path)
    monkeypatch.setattr(queue_module, "append_jsonl", lambda *_args, **_kwargs: None)

    assert queue_module.restore_pending_from_snapshot() == 1
    assert [task["id"] for task in pending] == ["task1"]
