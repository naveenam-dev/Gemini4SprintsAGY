from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .schemas import CarePlanResponse


DEFAULT_DB_PATH = os.getenv(
    "SQLITE_PATH",
    "/tmp/discharge_dost.db" if os.getenv("K_SERVICE") else str(Path(__file__).resolve().parent.parent / "discharge_dost.db"),
)


def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DEFAULT_DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with _get_conn() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS care_plans (
                plan_id TEXT PRIMARY KEY,
                language TEXT NOT NULL,
                diagnosis TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        conn.commit()


def save_care_plan(plan: CarePlanResponse) -> None:
    init_db()
    with _get_conn() as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO care_plans (plan_id, language, diagnosis, payload_json, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                plan.plan_id,
                plan.language,
                plan.diagnosis,
                plan.model_dump_json(),
                plan.created_at,
            ),
        )
        conn.commit()


def get_care_plan(plan_id: str) -> Optional[CarePlanResponse]:
    init_db()
    with _get_conn() as conn:
        row = conn.execute(
            "SELECT payload_json FROM care_plans WHERE plan_id = ?", (plan_id,)
        ).fetchone()
    if not row:
        return None
    return CarePlanResponse.model_validate_json(row["payload_json"])


def update_checklist_item(plan_id: str, item_id: str, checked: bool) -> Optional[CarePlanResponse]:
    plan = get_care_plan(plan_id)
    if not plan:
        return None
    updated = False
    for slot in plan.schedule:
        for dose in slot.doses:
            if dose.item_id == item_id:
                dose.checked = checked
                updated = True
    if updated:
        save_care_plan(plan)
    return plan


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
