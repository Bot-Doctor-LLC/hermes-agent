import importlib.util
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace


def _event(update_id=123):
    source = SimpleNamespace(
        platform=SimpleNamespace(value="telegram"), chat_id="42", thread_id="7"
    )
    return SimpleNamespace(source=source, platform_update_id=update_id, message_id="99")


def _window():
    return (
        (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat(),
        (datetime.now(timezone.utc) + timedelta(minutes=1)).isoformat(),
    )


def _load():
    path = (
        __import__("pathlib").Path(__file__).parents[1]
        / "gateway/telegram_transaction_ledger.py"
    )
    spec = importlib.util.spec_from_file_location(
        "telegram_transaction_ledger_under_test", path
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_receipt_delivery_and_summary_are_linked(tmp_path, monkeypatch):
    monkeypatch.setenv("TELEGRAM_TRANSACTION_LEDGER", str(tmp_path / "ledger.db"))
    monkeypatch.setenv("HERMES_AGENT_ID", "test-agent")
    ledger = _load()
    event = _event()
    ids = ledger.receive(event)
    metadata = {
        "telegram_transaction_id": ids["transaction_id"],
        "telegram_transaction_run_id": ids["run_id"],
    }
    ledger.record_delivery(
        metadata, SimpleNamespace(success=True, message_id="501"), "42", "7"
    )
    ledger.finish(event.source, "success")
    summary = ledger.summarize(*_window())
    assert summary["inbound"] == summary["replied"] == 1
    assert summary["failed"] == summary["pending"] == summary["unknown"] == 0


def test_duplicate_update_is_one_receipt(tmp_path, monkeypatch):
    monkeypatch.setenv("TELEGRAM_TRANSACTION_LEDGER", str(tmp_path / "ledger.db"))
    ledger = _load()
    assert (
        ledger.receive(_event(777))["transaction_id"]
        == ledger.receive(_event(777))["transaction_id"]
    )
    with ledger._connect() as conn:
        assert (
            conn.execute(
                "SELECT count(*) FROM telegram_transaction_events WHERE event_type='received'"
            ).fetchone()[0]
            == 1
        )


def test_send_failure_is_failed(tmp_path, monkeypatch):
    monkeypatch.setenv("TELEGRAM_TRANSACTION_LEDGER", str(tmp_path / "ledger.db"))
    ledger = _load()
    event = _event(888)
    ids = ledger.receive(event)
    ledger.record_delivery(
        {
            "telegram_transaction_id": ids["transaction_id"],
            "telegram_transaction_run_id": ids["run_id"],
        },
        SimpleNamespace(
            success=False, message_id=None, error="HTTP 400 invalid target"
        ),
        "42",
    )
    summary = ledger.summarize(*_window())
    assert summary["failed"] == 1 and summary["replied"] == 0


def test_unfinished_receipt_is_pending_not_healthy(tmp_path, monkeypatch):
    monkeypatch.setenv("TELEGRAM_TRANSACTION_LEDGER", str(tmp_path / "ledger.db"))
    ledger = _load()
    ledger.receive(_event(999))
    summary = ledger.summarize(*_window())
    assert summary["pending"] == 1
    assert summary["replied"] == summary["failed"] == summary["unknown"] == 0


def test_orphan_telemetry_is_unknown(tmp_path, monkeypatch):
    monkeypatch.setenv("TELEGRAM_TRANSACTION_LEDGER", str(tmp_path / "ledger.db"))
    ledger = _load()
    ledger._append("orphan", "run_started", {"run_id": "r1"})
    summary = ledger.summarize(*_window())
    assert summary["unknown"] == 1
    assert summary["inbound"] == summary["replied"] == summary["failed"] == 0
