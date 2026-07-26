"""Cellphone buyback pricing, quote calculation, and SQLite persistence."""

from __future__ import annotations

import secrets
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SUPPORTED_CONDITIONS: dict[str, int] = {
    "Brand New": 0,
    "Like New": 3000,
    "Good": 7000,
    "Fair": 16000,
    "Damaged": 30000,
    "Not Working": 0,
}

PAYOUT_METHODS = {"PayPal", "Venmo", "Bank Transfer", "Digital Prepaid Card", "Mailed Check"}
INELIGIBLE_FLAGS = {"lost_stolen", "financed", "account_lock", "legally_ineligible"}
NEUTRAL_CONDITION_ANSWERS = {
    "power_on": "yes",
    "buttons": "yes",
    "cameras": "yes",
    "charging": "yes",
}

SAMPLE_PRICING: tuple[dict[str, Any], ...] = (
    {"brand": "Apple iPhone", "model": "iPhone 15 Pro Max", "storage": "256GB", "newest_rank": 100, "base_value_cents": 76000, "maximum_payout_cents": 89000, "carrier_adjustment_cents": 2500, "condition_deduction_cents": 7000, "screen_damage_deduction_cents": 12000, "back_glass_deduction_cents": 6500, "water_damage_deduction_cents": 22000, "non_working_value_cents": 18000, "promotional_bonus_cents": 0},
    {"brand": "Apple iPhone", "model": "iPhone 15 Pro", "storage": "256GB", "newest_rank": 96, "base_value_cents": 64000, "maximum_payout_cents": 72000, "carrier_adjustment_cents": 2000, "condition_deduction_cents": 6000, "screen_damage_deduction_cents": 11000, "back_glass_deduction_cents": 6000, "water_damage_deduction_cents": 20000, "non_working_value_cents": 15000, "promotional_bonus_cents": 1000},
    {"brand": "Samsung Galaxy", "model": "Galaxy S24 Ultra", "storage": "512GB", "newest_rank": 98, "base_value_cents": 65000, "maximum_payout_cents": 65000, "carrier_adjustment_cents": 0, "condition_deduction_cents": 5500, "screen_damage_deduction_cents": 10500, "back_glass_deduction_cents": 5000, "water_damage_deduction_cents": 19000, "non_working_value_cents": 14000, "promotional_bonus_cents": 0},
    {"brand": "Google Pixel", "model": "Pixel 8 Pro", "storage": "256GB", "newest_rank": 92, "base_value_cents": 41000, "maximum_payout_cents": 41000, "carrier_adjustment_cents": 0, "condition_deduction_cents": 4500, "screen_damage_deduction_cents": 8500, "back_glass_deduction_cents": 4500, "water_damage_deduction_cents": 14000, "non_working_value_cents": 9000, "promotional_bonus_cents": 0},
    {"brand": "OnePlus", "model": "OnePlus 12", "storage": "256GB", "newest_rank": 88, "base_value_cents": 36000, "maximum_payout_cents": 38000, "carrier_adjustment_cents": 1000, "condition_deduction_cents": 4000, "screen_damage_deduction_cents": 8000, "back_glass_deduction_cents": 4000, "water_damage_deduction_cents": 13000, "non_working_value_cents": 8000, "promotional_bonus_cents": 1000},
    {"brand": "Motorola", "model": "Razr Plus", "storage": "256GB", "newest_rank": 80, "base_value_cents": 28000, "maximum_payout_cents": 30000, "carrier_adjustment_cents": 500, "condition_deduction_cents": 3500, "screen_damage_deduction_cents": 7500, "back_glass_deduction_cents": 3500, "water_damage_deduction_cents": 11000, "non_working_value_cents": 6000, "promotional_bonus_cents": 0},
    {"brand": "Xiaomi", "model": "Xiaomi 14 Ultra", "storage": "512GB", "newest_rank": 78, "base_value_cents": 34000, "maximum_payout_cents": 35000, "carrier_adjustment_cents": 0, "condition_deduction_cents": 4000, "screen_damage_deduction_cents": 8000, "back_glass_deduction_cents": 4000, "water_damage_deduction_cents": 12000, "non_working_value_cents": 7000, "promotional_bonus_cents": 0},
    {"brand": "Nothing", "model": "Nothing Phone 2", "storage": "256GB", "newest_rank": 74, "base_value_cents": 24000, "maximum_payout_cents": 25000, "carrier_adjustment_cents": 0, "condition_deduction_cents": 3000, "screen_damage_deduction_cents": 6500, "back_glass_deduction_cents": 3000, "water_damage_deduction_cents": 10000, "non_working_value_cents": 5000, "promotional_bonus_cents": 0},
    {"brand": "Other Brands", "model": "Manual Review Device", "storage": "Varies", "newest_rank": 1, "base_value_cents": 5000, "maximum_payout_cents": 10000, "carrier_adjustment_cents": 0, "condition_deduction_cents": 1000, "screen_damage_deduction_cents": 2000, "back_glass_deduction_cents": 1000, "water_damage_deduction_cents": 4000, "non_working_value_cents": 1000, "promotional_bonus_cents": 0},
)


class BuybackStore:
    """SQLite-backed store for buyback pricing and demo order management."""

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
            self._recover_legacy_pricing_schema(connection)
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS pricing (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    brand TEXT NOT NULL,
                    model TEXT NOT NULL,
                    storage TEXT NOT NULL,
                    base_value_cents INTEGER NOT NULL CHECK(base_value_cents >= 0),
                    maximum_payout_cents INTEGER NOT NULL CHECK(maximum_payout_cents >= 0),
                    carrier_adjustment_cents INTEGER NOT NULL DEFAULT 0,
                    condition_deduction_cents INTEGER NOT NULL DEFAULT 0,
                    screen_damage_deduction_cents INTEGER NOT NULL DEFAULT 0,
                    back_glass_deduction_cents INTEGER NOT NULL DEFAULT 0,
                    water_damage_deduction_cents INTEGER NOT NULL DEFAULT 0,
                    non_working_value_cents INTEGER NOT NULL DEFAULT 0,
                    promotional_bonus_cents INTEGER NOT NULL DEFAULT 0,
                    newest_rank INTEGER NOT NULL DEFAULT 0,
                    active INTEGER NOT NULL DEFAULT 1,
                    UNIQUE(brand, model, storage)
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS orders (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    quote_number TEXT NOT NULL UNIQUE,
                    created_at TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'Quote Created',
                    brand TEXT NOT NULL,
                    model TEXT NOT NULL,
                    storage TEXT NOT NULL,
                    carrier TEXT NOT NULL,
                    condition TEXT NOT NULL,
                    estimated_payout_cents INTEGER NOT NULL,
                    final_payout_cents INTEGER,
                    adjustment_summary TEXT NOT NULL DEFAULT '',
                    full_name TEXT NOT NULL,
                    email TEXT NOT NULL,
                    phone TEXT NOT NULL,
                    street_address TEXT NOT NULL,
                    apartment TEXT NOT NULL DEFAULT '',
                    city TEXT NOT NULL,
                    state TEXT NOT NULL,
                    zip_code TEXT NOT NULL,
                    payout_method TEXT NOT NULL,
                    inspection_result TEXT NOT NULL DEFAULT '',
                    internal_notes TEXT NOT NULL DEFAULT '',
                    decision TEXT NOT NULL DEFAULT 'Pending',
                    payment_sent INTEGER NOT NULL DEFAULT 0
                )
                """
            )

    def _recover_legacy_pricing_schema(self, connection: sqlite3.Connection) -> None:
        existing = connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='pricing'"
        ).fetchone()
        if existing is None:
            return

        columns = {row[1] for row in connection.execute("PRAGMA table_info(pricing)").fetchall()}
        required = {
            "brand", "model", "storage", "base_value_cents", "maximum_payout_cents",
            "carrier_adjustment_cents", "condition_deduction_cents", "screen_damage_deduction_cents",
            "back_glass_deduction_cents", "water_damage_deduction_cents", "non_working_value_cents",
            "promotional_bonus_cents", "newest_rank", "active",
        }
        has_unique_device_index = False
        for index in connection.execute("PRAGMA index_list(pricing)").fetchall():
            if not index[2]:
                continue
            index_columns = [row[2] for row in connection.execute(f"PRAGMA index_info({index[1]})").fetchall()]
            if index_columns == ["brand", "model", "storage"]:
                has_unique_device_index = True
                break
        if required.issubset(columns) and has_unique_device_index:
            return

        legacy_rows = [dict(row) for row in connection.execute("SELECT * FROM pricing").fetchall()]
        backup_name = f"pricing_legacy_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"
        connection.execute(f"ALTER TABLE pricing RENAME TO {backup_name}")
        connection.execute(
            """
            CREATE TABLE pricing (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                brand TEXT NOT NULL,
                model TEXT NOT NULL,
                storage TEXT NOT NULL,
                base_value_cents INTEGER NOT NULL CHECK(base_value_cents >= 0),
                maximum_payout_cents INTEGER NOT NULL CHECK(maximum_payout_cents >= 0),
                carrier_adjustment_cents INTEGER NOT NULL DEFAULT 0,
                condition_deduction_cents INTEGER NOT NULL DEFAULT 0,
                screen_damage_deduction_cents INTEGER NOT NULL DEFAULT 0,
                back_glass_deduction_cents INTEGER NOT NULL DEFAULT 0,
                water_damage_deduction_cents INTEGER NOT NULL DEFAULT 0,
                non_working_value_cents INTEGER NOT NULL DEFAULT 0,
                promotional_bonus_cents INTEGER NOT NULL DEFAULT 0,
                newest_rank INTEGER NOT NULL DEFAULT 0,
                active INTEGER NOT NULL DEFAULT 1,
                UNIQUE(brand, model, storage)
            )
            """
        )
        for row in legacy_rows:
            base_value = int(row.get("base_value_cents") or row.get("base_price_cents") or 0)
            active_value = row.get("active")
            connection.execute(
                """
                INSERT OR IGNORE INTO pricing (brand, model, storage, base_value_cents, maximum_payout_cents,
                    carrier_adjustment_cents, condition_deduction_cents, screen_damage_deduction_cents,
                    back_glass_deduction_cents, water_damage_deduction_cents, non_working_value_cents,
                    promotional_bonus_cents, newest_rank, active)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    row.get("brand", "Legacy Brand"), row.get("model", "Legacy Device"), row.get("storage", "Unknown"),
                    base_value, int(row.get("maximum_payout_cents") or base_value), int(row.get("carrier_adjustment_cents") or 0),
                    int(row.get("condition_deduction_cents") or 0), int(row.get("screen_damage_deduction_cents") or 0),
                    int(row.get("back_glass_deduction_cents") or 0), int(row.get("water_damage_deduction_cents") or 0),
                    int(row.get("non_working_value_cents") or 0), int(row.get("promotional_bonus_cents") or 0),
                    int(row.get("newest_rank") or 0), int(active_value) if active_value is not None else 1,
                ),
            )

    def upsert_pricing(self, **row: Any) -> None:
        fields = {
            "brand": row["brand"],
            "model": row["model"],
            "storage": row["storage"],
            "base_value_cents": int(row.get("base_value_cents", row.get("base_price_cents", 0))),
            "maximum_payout_cents": int(row.get("maximum_payout_cents", row.get("base_value_cents", 0))),
            "carrier_adjustment_cents": int(row.get("carrier_adjustment_cents", 0)),
            "condition_deduction_cents": int(row.get("condition_deduction_cents", 0)),
            "screen_damage_deduction_cents": int(row.get("screen_damage_deduction_cents", 0)),
            "back_glass_deduction_cents": int(row.get("back_glass_deduction_cents", 0)),
            "water_damage_deduction_cents": int(row.get("water_damage_deduction_cents", 0)),
            "non_working_value_cents": int(row.get("non_working_value_cents", 0)),
            "promotional_bonus_cents": int(row.get("promotional_bonus_cents", 0)),
            "newest_rank": int(row.get("newest_rank", 0)),
            "active": int(row.get("active", True)),
        }
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO pricing (brand, model, storage, base_value_cents, maximum_payout_cents,
                    carrier_adjustment_cents, condition_deduction_cents, screen_damage_deduction_cents,
                    back_glass_deduction_cents, water_damage_deduction_cents, non_working_value_cents,
                    promotional_bonus_cents, newest_rank, active)
                VALUES (:brand, :model, :storage, :base_value_cents, :maximum_payout_cents,
                    :carrier_adjustment_cents, :condition_deduction_cents, :screen_damage_deduction_cents,
                    :back_glass_deduction_cents, :water_damage_deduction_cents, :non_working_value_cents,
                    :promotional_bonus_cents, :newest_rank, :active)
                ON CONFLICT(brand, model, storage) DO UPDATE SET
                    base_value_cents=excluded.base_value_cents,
                    maximum_payout_cents=excluded.maximum_payout_cents,
                    carrier_adjustment_cents=excluded.carrier_adjustment_cents,
                    condition_deduction_cents=excluded.condition_deduction_cents,
                    screen_damage_deduction_cents=excluded.screen_damage_deduction_cents,
                    back_glass_deduction_cents=excluded.back_glass_deduction_cents,
                    water_damage_deduction_cents=excluded.water_damage_deduction_cents,
                    non_working_value_cents=excluded.non_working_value_cents,
                    promotional_bonus_cents=excluded.promotional_bonus_cents,
                    newest_rank=excluded.newest_rank,
                    active=excluded.active
                """,
                fields,
            )

    def update_pricing(self, pricing_id: int, **updates: Any) -> None:
        existing = self.get_pricing_by_id(pricing_id)
        if existing is None:
            raise ValueError("Pricing row not found")
        existing.update({key: value for key, value in updates.items() if value is not None})
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE pricing SET base_value_cents=?, maximum_payout_cents=?, carrier_adjustment_cents=?,
                    condition_deduction_cents=?, screen_damage_deduction_cents=?, back_glass_deduction_cents=?,
                    water_damage_deduction_cents=?, non_working_value_cents=?, promotional_bonus_cents=?, active=?
                WHERE id=?
                """,
                (
                    int(existing["base_value_cents"]), int(existing["maximum_payout_cents"]), int(existing["carrier_adjustment_cents"]),
                    int(existing["condition_deduction_cents"]), int(existing["screen_damage_deduction_cents"]), int(existing["back_glass_deduction_cents"]),
                    int(existing["water_damage_deduction_cents"]), int(existing["non_working_value_cents"]), int(existing["promotional_bonus_cents"]),
                    int(existing.get("active", 1)), int(pricing_id),
                ),
            )

    def list_pricing(self, *, active_only: bool = False) -> list[dict[str, Any]]:
        query = "SELECT *, base_value_cents AS base_price_cents FROM pricing"
        if active_only:
            query += " WHERE active = 1"
        query += " ORDER BY brand, newest_rank DESC, model, storage"
        with self._connect() as connection:
            return [dict(row) for row in connection.execute(query).fetchall()]

    def get_pricing_by_id(self, pricing_id: int) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM pricing WHERE id = ?", (int(pricing_id),)).fetchone()
        return dict(row) if row else None

    def get_pricing(self, brand: str, model: str, storage: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM pricing WHERE brand = ? AND model = ? AND storage = ? AND active = 1",
                (brand, model, storage),
            ).fetchone()
        return dict(row) if row else None

    def create_order(self, data: dict[str, Any]) -> dict[str, Any]:
        explicit_quote_number = data.get("quote_number")
        attempts = 1 if explicit_quote_number else 5
        last_error: sqlite3.IntegrityError | None = None
        for _attempt in range(attempts):
            quote_number = explicit_quote_number or self._quote_number()
            payload = {**data, "quote_number": quote_number, "created_at": datetime.now(timezone.utc).isoformat()}
            try:
                with self._connect() as connection:
                    connection.execute(
                """
                INSERT INTO orders (quote_number, created_at, status, brand, model, storage, carrier, condition,
                    estimated_payout_cents, final_payout_cents, adjustment_summary, full_name, email, phone,
                    street_address, apartment, city, state, zip_code, payout_method)
                VALUES (:quote_number, :created_at, COALESCE(:status, 'Quote Created'), :brand, :model, :storage,
                    :carrier, :condition, :estimated_payout_cents, :final_payout_cents, :adjustment_summary,
                    :full_name, :email, :phone, :street_address, :apartment, :city, :state, :zip_code, :payout_method)
                """,
                        {
                            **payload,
                            "status": payload.get("status", "Quote Created"),
                            "final_payout_cents": payload.get("final_payout_cents"),
                            "adjustment_summary": payload.get("adjustment_summary", ""),
                            "apartment": payload.get("apartment", ""),
                        },
                    )
                return self.get_order(quote_number) or payload
            except sqlite3.IntegrityError as error:
                last_error = error
                if explicit_quote_number:
                    raise
        if last_error:
            raise last_error
        raise RuntimeError("Unable to create a unique quote number")

    def list_orders(self) -> list[dict[str, Any]]:
        with self._connect() as connection:
            return [dict(row) for row in connection.execute("SELECT * FROM orders ORDER BY created_at DESC, id DESC").fetchall()]

    def get_order(self, quote_number: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM orders WHERE quote_number = ?", (quote_number.strip().upper(),)).fetchone()
        return dict(row) if row else None

    def update_order(self, quote_number: str, **updates: Any) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE orders SET status=?, inspection_result=?, internal_notes=?, decision=?, final_payout_cents=?, payment_sent=?
                WHERE quote_number=?
                """,
                (
                    updates.get("status", "Quote Created"), updates.get("inspection_result", ""),
                    updates.get("internal_notes", ""), updates.get("decision", "Pending"),
                    updates.get("final_payout_cents"), int(updates.get("payment_sent", False)), quote_number,
                ),
            )

    def count_demo_credentials(self) -> int:
        return 0

    def admin_stats(self) -> dict[str, Any]:
        orders = self.list_orders()
        total = len(orders)
        accepted = sum(1 for row in orders if row["decision"] == "Approved")
        received = sum(1 for row in orders if "Received" in row["status"])
        inspected = sum(1 for row in orders if row["inspection_result"])
        paid = sum(1 for row in orders if row["payment_sent"])
        total_value = sum(int(row.get("final_payout_cents") or row["estimated_payout_cents"]) for row in orders)
        return {
            "total_quotes": total,
            "accepted_quotes": accepted,
            "devices_received": received,
            "devices_inspected": inspected,
            "payments_sent": paid,
            "average_payout_cents": round(total_value / total) if total else 0,
            "conversion_rate": round((accepted / total) * 100) if total else 0,
            "total_buyback_value_cents": total_value,
        }

    def _quote_number(self) -> str:
        stamp = datetime.now(timezone.utc).strftime("%y%m%d")
        return f"ZEL-{stamp}-{secrets.token_hex(8).upper()}"


def seed_sample_data(store: BuybackStore) -> None:
    for row in SAMPLE_PRICING:
        store.upsert_pricing(**row)


def seed_sample_pricing(store: BuybackStore) -> None:
    seed_sample_data(store)


def calculate_offer(store: BuybackStore, *, brand: str, model: str, storage: str, carrier: str = "Unlocked", condition: str = "Good", cracked_screen: str = "no", cracked_back_glass: str = "no", water_damage: str = "no", deep_scratches: str = "no", **_: Any) -> dict[str, Any]:
    pricing = store.get_pricing(brand, model, storage)
    if pricing is None:
        raise ValueError("Unsupported phone configuration")
    if condition not in SUPPORTED_CONDITIONS:
        raise ValueError("Unsupported condition")

    if condition == "Not Working":
        payout = int(pricing["non_working_value_cents"])
        adjustments = ["Not Working value applied"]
    else:
        payout = int(pricing["base_value_cents"])
        adjustments = [f"{condition} condition"]
        deduction = SUPPORTED_CONDITIONS[condition] if condition != "Good" else int(pricing["condition_deduction_cents"])
        if deduction:
            payout -= deduction
            adjustments.append(f"Condition deduction -{_money(deduction)}")
    if carrier == "Unlocked" and int(pricing["carrier_adjustment_cents"]):
        payout += int(pricing["carrier_adjustment_cents"])
        adjustments.append(f"Unlocked carrier bonus +{_money(int(pricing['carrier_adjustment_cents']))}")
    if cracked_screen == "yes":
        payout -= int(pricing["screen_damage_deduction_cents"])
        adjustments.append(f"Cracked screen -{_money(int(pricing['screen_damage_deduction_cents']))}")
    if cracked_back_glass == "yes":
        payout -= int(pricing["back_glass_deduction_cents"])
        adjustments.append(f"Cracked back glass -{_money(int(pricing['back_glass_deduction_cents']))}")
    if water_damage == "yes":
        payout -= int(pricing["water_damage_deduction_cents"])
        adjustments.append(f"Water damage -{_money(int(pricing['water_damage_deduction_cents']))}")
    if deep_scratches == "yes":
        payout -= 2500
        adjustments.append("Deep scratches -$25.00")
    if int(pricing["promotional_bonus_cents"]):
        payout += int(pricing["promotional_bonus_cents"])
        adjustments.append(f"Promotional bonus +{_money(int(pricing['promotional_bonus_cents']))}")
    payout = max(0, min(int(pricing["maximum_payout_cents"]), payout))
    return {
        "eligible": True,
        "brand": brand,
        "model": model,
        "storage": storage,
        "carrier": carrier,
        "condition": condition,
        "base_value_cents": int(pricing["base_value_cents"]),
        "base_price_cents": int(pricing["base_value_cents"]),
        "maximum_payout_cents": int(pricing["maximum_payout_cents"]),
        "offer_cents": payout,
        "condition_multiplier": round(payout / int(pricing["base_value_cents"]), 4) if pricing["base_value_cents"] else 0,
        "adjustments": adjustments,
        "adjustment_summary": "; ".join(adjustments),
    }


def calculate_condition_offer(store: BuybackStore, *, answers: dict[str, str], **details: Any) -> dict[str, Any]:
    normalized_answers = {key: value.strip().lower() for key, value in answers.items()}
    for key, value in NEUTRAL_CONDITION_ANSWERS.items():
        normalized_answers.setdefault(key, value)
    blocked = [flag for flag in INELIGIBLE_FLAGS if normalized_answers.get(flag) == "yes"]
    if blocked:
        return {
            "eligible": False,
            "block_message": "Zelvari cannot accept this device",
            "block_explanation": "Only legally eligible devices can be sold. Please edit answers for lost, stolen, financed, activation/account locked, or otherwise legally ineligible devices.",
            "blocked_reasons": blocked,
        }
    mapped = {
        "cracked_screen": normalized_answers.get("cracked_screen", "no"),
        "cracked_back_glass": normalized_answers.get("cracked_back_glass", "no"),
        "water_damage": normalized_answers.get("water_damage", "no"),
        "deep_scratches": normalized_answers.get("deep_scratches", "no"),
    }
    offer = calculate_offer(store, **details, **mapped)
    pricing = store.get_pricing(str(details.get("brand", "")), str(details.get("model", "")), str(details.get("storage", "")))
    if pricing is None:
        raise ValueError("Unsupported phone configuration")

    payout = int(offer["offer_cents"])
    adjustments = list(offer["adjustments"])
    if normalized_answers.get("power_on") == "no":
        payout = min(payout, int(pricing["non_working_value_cents"]))
        adjustments.append("Power on issue - non-working value applied")
    hardware_deductions = [
        ("buttons", "no", 5000, "Buttons issue"),
        ("cameras", "no", 7000, "Cameras issue"),
        ("charging", "no", 6000, "Charging issue"),
        ("swollen_battery", "yes", 10000, "Swollen battery"),
        ("missing_parts", "yes", 9000, "Missing parts"),
    ]
    for key, trigger, deduction, label in hardware_deductions:
        if normalized_answers.get(key) == trigger:
            payout -= deduction
            adjustments.append(f"{label} -{_money(deduction)}")
    if normalized_answers.get("repair_history") == "yes":
        adjustments.append("Repair history noted - no automatic value impact")
    offer["offer_cents"] = max(0, min(int(pricing["maximum_payout_cents"]), payout))
    offer["adjustments"] = adjustments
    offer["adjustment_summary"] = "; ".join(adjustments)
    offer["condition_multiplier"] = round(offer["offer_cents"] / int(pricing["base_value_cents"]), 4) if pricing["base_value_cents"] else 0
    return offer


def validate_seller_fields(data: dict[str, str]) -> list[str]:
    labels = {
        "full_name": "Full name is required",
        "email": "Email is required",
        "phone": "Phone number is required",
        "street_address": "Street address is required",
        "city": "City is required",
        "state": "State is required",
        "zip_code": "ZIP code is required",
        "payout_method": "Preferred payout method is required",
        "brand": "Device brand is required",
        "model": "Device model is required",
        "storage": "Storage is required",
        "condition": "Condition is required",
    }
    errors = [message for field, message in labels.items() if not data.get(field, "").strip()]
    if data.get("payout_method") and data["payout_method"] not in PAYOUT_METHODS:
        errors.append("Unsupported payout method")
    if data.get("terms_agree") != "1":
        errors.append("Terms agreement is required")
    if data.get("privacy_agree") != "1":
        errors.append("Privacy agreement is required")
    if data.get("email") and "@" not in data["email"]:
        errors.append("Enter a valid email")
    return errors


def validate_request_fields(data: dict[str, str]) -> list[str]:
    return validate_seller_fields(data)


def _money(cents: int) -> str:
    return f"${cents / 100:,.2f}"
