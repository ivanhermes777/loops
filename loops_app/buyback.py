"""Cellphone buyback pricing and request persistence."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SUPPORTED_CONDITIONS: dict[str, float] = {
    "New/Like New": 1.00,
    "Good": 0.85,
    "Fair": 0.70,
    "Cracked/Damaged": 0.45,
    "Not Working": 0.20,
}

SAMPLE_PRICING: tuple[tuple[str, str, str, int], ...] = (
    ("iPhone", "iPhone 15 Pro", "256GB", 64000),
    ("iPhone", "iPhone 14", "256GB", 42000),
    ("Samsung Galaxy", "Galaxy S24 Ultra", "512GB", 66000),
    ("Samsung Galaxy", "Galaxy S23", "256GB", 39000),
)


@dataclass(frozen=True)
class PricingRecord:
    id: int
    brand: str
    model: str
    storage: str
    base_price_cents: int
    active: bool


class BuybackStore:
    """SQLite-backed store for buyback pricing and submitted requests."""

    def __init__(self, db_path: str):
        self.db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS pricing (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    brand TEXT NOT NULL,
                    model TEXT NOT NULL,
                    storage TEXT NOT NULL,
                    base_price_cents INTEGER NOT NULL CHECK(base_price_cents > 0),
                    active INTEGER NOT NULL DEFAULT 1,
                    UNIQUE(brand, model, storage)
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS offer_requests (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TEXT NOT NULL,
                    name TEXT NOT NULL,
                    email TEXT NOT NULL,
                    phone TEXT NOT NULL,
                    brand TEXT NOT NULL,
                    model TEXT NOT NULL,
                    storage TEXT NOT NULL,
                    condition TEXT NOT NULL,
                    estimate_cents INTEGER NOT NULL,
                    base_price_cents INTEGER NOT NULL,
                    condition_multiplier REAL NOT NULL,
                    notes TEXT NOT NULL DEFAULT ''
                )
                """
            )

    def upsert_pricing(
        self,
        *,
        brand: str,
        model: str,
        storage: str,
        base_price_cents: int,
        active: bool = True,
    ) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO pricing (brand, model, storage, base_price_cents, active)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(brand, model, storage) DO UPDATE SET
                    base_price_cents = excluded.base_price_cents,
                    active = excluded.active
                """,
                (brand, model, storage, int(base_price_cents), int(active)),
            )

    def update_pricing(self, pricing_id: int, base_price_cents: int, active: bool) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE pricing
                SET base_price_cents = ?, active = ?
                WHERE id = ?
                """,
                (int(base_price_cents), int(active), int(pricing_id)),
            )

    def list_pricing(self, *, active_only: bool = False) -> list[dict[str, Any]]:
        query = "SELECT * FROM pricing"
        params: tuple[Any, ...] = ()
        if active_only:
            query += " WHERE active = 1"
        query += " ORDER BY brand, model, storage"
        with self._connect() as connection:
            return [dict(row) for row in connection.execute(query, params).fetchall()]

    def get_pricing(self, brand: str, model: str, storage: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM pricing
                WHERE brand = ? AND model = ? AND storage = ? AND active = 1
                """,
                (brand, model, storage),
            ).fetchone()
        return dict(row) if row else None

    def save_offer_request(self, request: dict[str, Any]) -> int:
        with self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO offer_requests (
                    created_at, name, email, phone, brand, model, storage,
                    condition, estimate_cents, base_price_cents,
                    condition_multiplier, notes
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    datetime.now(timezone.utc).isoformat(),
                    request["name"],
                    request["email"],
                    request["phone"],
                    request["brand"],
                    request["model"],
                    request["storage"],
                    request["condition"],
                    int(request["estimate_cents"]),
                    int(request["base_price_cents"]),
                    float(request["condition_multiplier"]),
                    request.get("notes", ""),
                ),
            )
            return int(cursor.lastrowid)

    def list_offer_requests(self) -> list[dict[str, Any]]:
        with self._connect() as connection:
            return [
                dict(row)
                for row in connection.execute(
                    "SELECT * FROM offer_requests ORDER BY created_at DESC, id DESC"
                ).fetchall()
            ]


def seed_sample_pricing(store: BuybackStore) -> None:
    """Populate the editable table with supported MVP iPhone/Galaxy prices."""

    for brand, model, storage, price_cents in SAMPLE_PRICING:
        store.upsert_pricing(
            brand=brand,
            model=model,
            storage=storage,
            base_price_cents=price_cents,
            active=True,
        )


def calculate_offer(
    store: BuybackStore,
    *,
    brand: str,
    model: str,
    storage: str,
    condition: str,
) -> dict[str, Any]:
    """Calculate an offer only for supported active catalog combinations."""

    if condition not in SUPPORTED_CONDITIONS:
        raise ValueError("Unsupported condition")
    pricing = store.get_pricing(brand, model, storage)
    if pricing is None:
        raise ValueError("Unsupported phone configuration")
    multiplier = SUPPORTED_CONDITIONS[condition]
    offer_cents = round(int(pricing["base_price_cents"]) * multiplier)
    return {
        "brand": brand,
        "model": model,
        "storage": storage,
        "condition": condition,
        "base_price_cents": int(pricing["base_price_cents"]),
        "condition_multiplier": multiplier,
        "offer_cents": offer_cents,
    }


def validate_request_fields(data: dict[str, str]) -> list[str]:
    required = {
        "name": "Name is required",
        "email": "Email is required",
        "phone": "Phone number is required",
        "brand": "Device brand is required",
        "model": "Device model is required",
        "storage": "Storage size is required",
        "condition": "Condition is required",
    }
    return [message for field, message in required.items() if not data.get(field, "").strip()]
