"""Append-only receipt-to-reply evidence for Telegram gateway turns."""

from __future__ import annotations

import hashlib, json, os, sqlite3, threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_LOCK = threading.Lock()


def _now():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def ledger_path():
    home = Path(os.environ.get("HERMES_HOME") or Path.home() / ".hermes")
    return Path(
        os.environ.get("TELEGRAM_TRANSACTION_LEDGER")
        or home / "state/telegram-transactions.sqlite3"
    )


def _connect():
    path = ledger_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=10)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript("""
      CREATE TABLE IF NOT EXISTS telegram_transaction_events(
        id INTEGER PRIMARY KEY AUTOINCREMENT, transaction_id TEXT NOT NULL,
        event_type TEXT NOT NULL, occurred_at TEXT NOT NULL, payload_json TEXT NOT NULL);
      CREATE UNIQUE INDEX IF NOT EXISTS telegram_transaction_receipt_once
        ON telegram_transaction_events(transaction_id,event_type) WHERE event_type='received';
      CREATE UNIQUE INDEX IF NOT EXISTS telegram_transaction_run_start_once
        ON telegram_transaction_events(transaction_id,event_type) WHERE event_type='run_started';
      CREATE INDEX IF NOT EXISTS telegram_transaction_events_lookup
        ON telegram_transaction_events(transaction_id,id);
    """)
    return conn


def _append(transaction_id, event_type, payload):
    with _LOCK, _connect() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO telegram_transaction_events VALUES(NULL,?,?,?,?)",
            (
                transaction_id,
                event_type,
                _now(),
                json.dumps(payload, sort_keys=True, separators=(",", ":")),
            ),
        )


def receive(event):
    source = getattr(event, "source", None)
    update_id = getattr(event, "platform_update_id", None)
    if (
        getattr(getattr(source, "platform", None), "value", "") != "telegram"
        or update_id is None
    ):
        return None
    agent_id = os.environ.get("HERMES_AGENT_ID", "main").strip() or "main"
    transaction_id = hashlib.sha256(f"{agent_id}:{update_id}".encode()).hexdigest()[:32]
    run_id = hashlib.sha256(f"{transaction_id}:run".encode()).hexdigest()[:32]
    _append(
        transaction_id,
        "received",
        {
            "agent_id": agent_id,
            "bot_identity": agent_id,
            "update_id": int(update_id),
            "chat_id": str(getattr(source, "chat_id", "") or ""),
            "thread_id": str(getattr(source, "thread_id", "") or "") or None,
            "inbound_message_id": str(getattr(event, "message_id", "") or "") or None,
        },
    )
    _append(transaction_id, "run_started", {"run_id": run_id})
    setattr(source, "telegram_transaction_id", transaction_id)
    setattr(source, "telegram_transaction_run_id", run_id)
    return {"transaction_id": transaction_id, "run_id": run_id}


def record_delivery(metadata, result, chat_id, thread_id=None):
    transaction_id = str((metadata or {}).get("telegram_transaction_id") or "")
    if not transaction_id:
        return
    run_id = str((metadata or {}).get("telegram_transaction_run_id") or "") or None
    if getattr(result, "success", False) and getattr(result, "message_id", None):
        _append(
            transaction_id,
            "telegram_accepted",
            {
                "run_id": run_id,
                "outbound_chat_id": str(chat_id),
                "outbound_thread_id": str(thread_id)
                if thread_id not in (None, "")
                else None,
                "outbound_message_id": str(result.message_id),
            },
        )
    elif not getattr(result, "success", False):
        _append(
            transaction_id,
            "failed",
            {
                "run_id": run_id,
                "failure_stage": "telegram_send",
                "failure_type": "SendResult",
                "failure_detail": str(getattr(result, "error", "telegram send failed"))[
                    :500
                ],
            },
        )


def finish(source, outcome, detail=""):
    transaction_id = str(getattr(source, "telegram_transaction_id", "") or "")
    if not transaction_id:
        return
    payload = {
        "run_id": str(getattr(source, "telegram_transaction_run_id", "") or "") or None,
        "run_outcome": outcome,
    }
    event_type = "run_finished" if outcome == "success" else "failed"
    if event_type == "failed":
        payload.update(
            failure_stage="agent_run", failure_type=outcome, failure_detail=detail[:500]
        )
    _append(transaction_id, event_type, payload)


def summarize(start, end, pending_sla_seconds=300):
    with _connect() as conn:
        rows = conn.execute(
            "SELECT transaction_id,event_type,occurred_at,payload_json "
            "FROM telegram_transaction_events WHERE transaction_id IN ("
            "SELECT transaction_id FROM telegram_transaction_events "
            "WHERE event_type='received' AND occurred_at>=? AND occurred_at<?"
            ") ORDER BY id",
            (start, end),
        ).fetchall()
    grouped = {}
    for tid, kind, at, raw in rows:
        grouped.setdefault(tid, []).append((kind, at, json.loads(raw)))
    counts = {"inbound": 0, "replied": 0, "failed": 0, "pending": 0, "unknown": 0}
    for events in grouped.values():
        received = next((e for e in events if e[0] == "received"), None)
        if received is None:
            counts["unknown"] += 1
            continue
        counts["inbound"] += 1
        if any(e[0] == "failed" for e in events):
            counts["failed"] += 1
        elif any(
            e[0] == "telegram_accepted" and e[2].get("outbound_message_id")
            for e in events
        ):
            counts["replied"] += 1
        else:
            counts["pending"] += 1
    return {
        "window_start": start,
        "window_end": end,
        "pending_sla_seconds": pending_sla_seconds,
        **counts,
        "generated_at": _now(),
    }
