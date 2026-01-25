from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any


SCHEMA = """
PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS clients (
  token TEXT PRIMARY KEY,
  created_at INTEGER NOT NULL,
  paid INTEGER NOT NULL DEFAULT 0,
  paid_at INTEGER,
  stripe_customer_id TEXT,
  last_seen_at INTEGER
);

CREATE TABLE IF NOT EXISTS jobs (
  id TEXT PRIMARY KEY,
  client_token TEXT NOT NULL,
  created_at INTEGER NOT NULL,
  FOREIGN KEY (client_token) REFERENCES clients(token)
);

CREATE TABLE IF NOT EXISTS images (
  id TEXT PRIMARY KEY,
  job_id TEXT NOT NULL,
  filename TEXT,
  created_at INTEGER NOT NULL,
  status TEXT NOT NULL, -- queued|processing|ready|error
  error TEXT,
  original_path TEXT NOT NULL,
  cutout_path TEXT,
  width INTEGER,
  height INTEGER,
  FOREIGN KEY (job_id) REFERENCES jobs(id)
);

CREATE TABLE IF NOT EXISTS payments (
  id TEXT PRIMARY KEY,
  client_token TEXT NOT NULL,
  amount_chf_centimes INTEGER NOT NULL,
  currency TEXT NOT NULL,
  status TEXT NOT NULL, -- paid|unpaid|refunded
  stripe_session_id TEXT,
  stripe_payment_intent_id TEXT,
  created_at INTEGER NOT NULL,
  FOREIGN KEY (client_token) REFERENCES clients(token)
);

CREATE TABLE IF NOT EXISTS logs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts INTEGER NOT NULL,
  level TEXT NOT NULL,
  event TEXT NOT NULL,
  detail TEXT
);
"""


@dataclass
class Db:
    path: Path

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    def init(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as conn:
            conn.executescript(SCHEMA)
            conn.commit()

    def log(self, level: str, event: str, detail: str | None = None) -> None:
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO logs(ts, level, event, detail) VALUES(?,?,?,?)",
                (int(time.time()), level, event, detail),
            )
            conn.commit()

    def upsert_client(self, token: str) -> None:
        now = int(time.time())
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO clients(token, created_at, last_seen_at)
                VALUES(?,?,?)
                ON CONFLICT(token) DO UPDATE SET last_seen_at=excluded.last_seen_at
                """,
                (token, now, now),
            )
            conn.commit()

    def set_paid(self, token: str, stripe_customer_id: str | None = None) -> None:
        now = int(time.time())
        with self.connect() as conn:
            conn.execute(
                "UPDATE clients SET paid=1, paid_at=?, stripe_customer_id=COALESCE(?, stripe_customer_id) WHERE token=?",
                (now, stripe_customer_id, token),
            )
            conn.commit()

    def get_client(self, token: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM clients WHERE token=?", (token,)).fetchone()
            return dict(row) if row else None

    def stats(self) -> dict[str, Any]:
        with self.connect() as conn:
            uploads = conn.execute("SELECT COUNT(*) AS c FROM images").fetchone()["c"]
            processed = conn.execute("SELECT COUNT(*) AS c FROM images WHERE status='ready'").fetchone()["c"]
            payments = conn.execute("SELECT COUNT(*) AS c FROM payments WHERE status='paid'").fetchone()["c"]
            revenue_chf_centimes = conn.execute(
                "SELECT COALESCE(SUM(amount_chf_centimes), 0) AS s FROM payments WHERE status='paid'"
            ).fetchone()["s"]
            watermark_removals = conn.execute("SELECT COUNT(*) AS c FROM clients WHERE paid=1").fetchone()["c"]
            return {
                "uploads": uploads,
                "processed": processed,
                "payments": payments,
                "revenue_chf_centimes": revenue_chf_centimes,
                "watermark_removals": watermark_removals,
            }

    def recent_logs(self, limit: int = 200) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute("SELECT * FROM logs ORDER BY ts DESC, id DESC LIMIT ?", (limit,)).fetchall()
            return [dict(r) for r in rows]

