"""SQLite store for checkout sessions awaiting Stripe payment confirmation."""

from __future__ import annotations

import json
import os
import sqlite3
from dataclasses import dataclass
from pathlib import Path

LOCAL_DB_PATH = Path(__file__).resolve().parents[2] / "data" / "checkout.db"
RENDER_DB_PATH = Path("/tmp/druvo_checkout.db")


def _default_db_path() -> Path:
    configured = os.getenv("CHECKOUT_DB_PATH", "").strip()
    if configured:
        return Path(configured)
    if os.getenv("RENDER"):
        return RENDER_DB_PATH
    return LOCAL_DB_PATH


DEFAULT_DB_PATH = _default_db_path()


@dataclass(frozen=True)
class PendingCheckout:
    external_order_id: str
    customer_email: str
    customer_name: str
    lines: list[dict]
    stripe_session_id: str
    status: str


def _connect(db_path: Path = DEFAULT_DB_PATH) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(db_path, check_same_thread=False)
    connection.row_factory = sqlite3.Row
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS pending_checkouts (
            external_order_id TEXT PRIMARY KEY,
            customer_email TEXT NOT NULL,
            customer_name TEXT NOT NULL DEFAULT '',
            lines_json TEXT NOT NULL,
            stripe_session_id TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'pending',
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
        """
    )
    return connection


def save_pending(
    external_order_id: str,
    customer_email: str,
    customer_name: str,
    lines: list[dict],
    *,
    stripe_session_id: str = "",
    db_path: Path = DEFAULT_DB_PATH,
) -> PendingCheckout:
    connection = _connect(db_path)
    try:
        connection.execute(
            """
            INSERT INTO pending_checkouts (
                external_order_id, customer_email, customer_name, lines_json, stripe_session_id, status
            ) VALUES (?, ?, ?, ?, ?, 'pending')
            ON CONFLICT(external_order_id) DO UPDATE SET
                customer_email = excluded.customer_email,
                customer_name = excluded.customer_name,
                lines_json = excluded.lines_json,
                stripe_session_id = excluded.stripe_session_id,
                status = 'pending'
            """,
            (
                external_order_id,
                customer_email.strip(),
                customer_name.strip(),
                json.dumps(lines),
                stripe_session_id,
            ),
        )
        connection.commit()
    finally:
        connection.close()
    return get_pending(external_order_id, db_path=db_path)  # type: ignore[return-value]


def attach_session(
    external_order_id: str,
    stripe_session_id: str,
    *,
    db_path: Path = DEFAULT_DB_PATH,
) -> None:
    connection = _connect(db_path)
    try:
        connection.execute(
            "UPDATE pending_checkouts SET stripe_session_id = ? WHERE external_order_id = ?",
            (stripe_session_id, external_order_id),
        )
        connection.commit()
    finally:
        connection.close()


def get_pending(
    external_order_id: str,
    *,
    db_path: Path = DEFAULT_DB_PATH,
) -> PendingCheckout | None:
    connection = _connect(db_path)
    try:
        row = connection.execute(
            "SELECT * FROM pending_checkouts WHERE external_order_id = ?",
            (external_order_id,),
        ).fetchone()
    finally:
        connection.close()
    if not row:
        return None
    return PendingCheckout(
        external_order_id=row["external_order_id"],
        customer_email=row["customer_email"],
        customer_name=row["customer_name"],
        lines=json.loads(row["lines_json"]),
        stripe_session_id=row["stripe_session_id"] or "",
        status=row["status"],
    )


def get_pending_by_session(
    stripe_session_id: str,
    *,
    db_path: Path = DEFAULT_DB_PATH,
) -> PendingCheckout | None:
    connection = _connect(db_path)
    try:
        row = connection.execute(
            "SELECT * FROM pending_checkouts WHERE stripe_session_id = ?",
            (stripe_session_id,),
        ).fetchone()
    finally:
        connection.close()
    if not row:
        return None
    return PendingCheckout(
        external_order_id=row["external_order_id"],
        customer_email=row["customer_email"],
        customer_name=row["customer_name"],
        lines=json.loads(row["lines_json"]),
        stripe_session_id=row["stripe_session_id"] or "",
        status=row["status"],
    )


def mark_status(
    external_order_id: str,
    status: str,
    *,
    db_path: Path = DEFAULT_DB_PATH,
) -> None:
    connection = _connect(db_path)
    try:
        connection.execute(
            "UPDATE pending_checkouts SET status = ? WHERE external_order_id = ?",
            (status, external_order_id),
        )
        connection.commit()
    finally:
        connection.close()
