from __future__ import annotations

import ast
import json
import shutil
from pathlib import Path
from typing import Any

import config as legacy_config

PAYMENT_KEYS = (
    "type",
    "history_new_payment_name",
    "history_new_payment_amount",
    "details_new_payment_name",
    "transaction_date",
    "transaction_time",
    "transaction_time_zone",
    "sbp_telephone",
    "bank",
    "card_number",
)

PAYMENT_DEFAULTS: dict[str, Any] = {
    "type": "SBP",
    "history_new_payment_name": "Денис Н.",
    "history_new_payment_amount": 100,
    "details_new_payment_name": "ДЕНИСКА АЛЕКСЕЕВИЧ Н",
    "transaction_date": "2026-05-09",
    "transaction_time": "19:44:03",
    "transaction_time_zone": "+0700",
    "sbp_telephone": "+7 900 108-32-49",
    "bank": "TBANK",
    "card_number": "2200 **** **** 5206",
}

STORE_DEFAULTS: dict[str, Any] = {
    "last_balance": 30000,
    "payments": [],
}


def _store_path() -> Path:
    return Path(__file__).resolve().parent / "payments.json"


def _legacy_profiles_path() -> Path:
    return Path(__file__).resolve().parent / "profiles.json"


def _legacy_config_path() -> Path:
    return Path(__file__).resolve().parent / "config.py"


def normalize_tz_suffix(raw: object) -> str:
    value = str(raw).strip()
    if not value:
        return "+0000"
    upper = value.upper()
    if upper in ("Z", "UTC"):
        return "+0000"
    compact = value.replace(":", "")
    if len(compact) == 5 and compact[0] in "+-" and compact[1:].isdigit():
        return compact
    return "+0000"


def normalize_type(raw: object) -> str:
    value = str(raw).strip().upper()
    if value == "SPB":
        return "SBP"
    if value not in ("SBP", "CARD"):
        return "SBP"
    return value


def _to_int(raw: object, default: int = 0) -> int:
    try:
        return int(float(str(raw).replace(",", ".")))
    except (TypeError, ValueError):
        return default


def _legacy_single_payment() -> dict[str, Any]:
    return {
        "type": getattr(legacy_config, "type", PAYMENT_DEFAULTS["type"]),
        "history_new_payment_name": getattr(
            legacy_config, "history_new_payment_name", PAYMENT_DEFAULTS["history_new_payment_name"]
        ),
        "history_new_payment_amount": getattr(
            legacy_config, "history_new_payment_amount", PAYMENT_DEFAULTS["history_new_payment_amount"]
        ),
        "details_new_payment_name": getattr(
            legacy_config, "details_new_payment_name", PAYMENT_DEFAULTS["details_new_payment_name"]
        ),
        "transaction_date": getattr(legacy_config, "transaction_date", PAYMENT_DEFAULTS["transaction_date"]),
        "transaction_time": getattr(legacy_config, "transaction_time", PAYMENT_DEFAULTS["transaction_time"]),
        "transaction_time_zone": getattr(
            legacy_config, "transaction_time_zone", PAYMENT_DEFAULTS["transaction_time_zone"]
        ),
        "sbp_telephone": getattr(legacy_config, "sbp_telephone", PAYMENT_DEFAULTS["sbp_telephone"]),
        "bank": getattr(legacy_config, "bank", PAYMENT_DEFAULTS["bank"]),
        "card_number": getattr(legacy_config, "card_number", PAYMENT_DEFAULTS["card_number"]),
    }


def sanitize_payment(raw: dict[str, Any], fallback: dict[str, Any] | None = None) -> dict[str, Any]:
    base = dict(PAYMENT_DEFAULTS)
    if fallback:
        for key in PAYMENT_KEYS:
            if key in fallback:
                base[key] = fallback[key]
    for key in PAYMENT_KEYS:
        if key in raw:
            base[key] = raw[key]
    return {
        "type": normalize_type(base["type"]),
        "history_new_payment_name": str(base["history_new_payment_name"]).strip(),
        "history_new_payment_amount": _to_int(base["history_new_payment_amount"], 0),
        "details_new_payment_name": str(base["details_new_payment_name"]).strip(),
        "transaction_date": str(base["transaction_date"]).strip(),
        "transaction_time": str(base["transaction_time"]).strip(),
        "transaction_time_zone": normalize_tz_suffix(base["transaction_time_zone"]),
        "sbp_telephone": str(base["sbp_telephone"]).strip(),
        "bank": str(base["bank"]).strip().upper() or "UNKNOWN",
        "card_number": str(base["card_number"]).strip(),
    }


def sanitize_payments(raw: Any, fallback: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    if not isinstance(raw, list):
        return []
    out: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        out.append(sanitize_payment(item, fallback=fallback))
    return out


def _migrate_legacy_profiles_if_present() -> dict[str, Any] | None:
    path = _legacy_profiles_path()
    if not path.exists():
        return None
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(loaded, dict):
        return None
    profiles = loaded.get("profiles")
    active_profile_id = str(loaded.get("active_profile_id") or "")
    if not isinstance(profiles, list) or not profiles:
        return None
    active = None
    for profile in profiles:
        if not isinstance(profile, dict):
            continue
        if str(profile.get("id") or "") == active_profile_id:
            active = profile
            break
    if active is None:
        active = profiles[0] if isinstance(profiles[0], dict) else None
    if active is None:
        return None
    raw_data = active.get("data")
    if not isinstance(raw_data, dict):
        raw_data = {}
    last_balance = _to_int(raw_data.get("last_balance", STORE_DEFAULTS["last_balance"]), 0)
    payments = sanitize_payments(raw_data.get("payments"), fallback=raw_data)
    if not payments:
        payments = [sanitize_payment(raw_data)]
    return {"last_balance": last_balance, "payments": payments}


def sanitize_store(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raw = {}
    last_balance = _to_int(raw.get("last_balance", STORE_DEFAULTS["last_balance"]), 0)
    payments = sanitize_payments(raw.get("payments"))
    if not payments:
        payments = [sanitize_payment(_legacy_single_payment())]
    return {"last_balance": last_balance, "payments": payments}


def ensure_store() -> dict[str, Any]:
    path = _store_path()
    loaded: Any = {}
    if path.exists():
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            loaded = {}
    else:
        migrated = _migrate_legacy_profiles_if_present()
        if migrated is not None:
            loaded = migrated
        else:
            loaded = {
                "last_balance": getattr(legacy_config, "last_balance", STORE_DEFAULTS["last_balance"]),
                "payments": [sanitize_payment(_legacy_single_payment())],
            }
    store = sanitize_store(loaded)
    save_store(store)
    return store


def save_store(store: dict[str, Any]) -> None:
    normalized = sanitize_store(store)
    text = json.dumps(normalized, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    _store_path().write_text(text, encoding="utf-8")


def get_store() -> dict[str, Any]:
    return ensure_store()


def get_payments() -> list[dict[str, Any]]:
    return get_store()["payments"]


def write_legacy_config_from_store(store: dict[str, Any]) -> None:
    normalized = sanitize_store(store)
    last_balance = int(normalized["last_balance"])
    first = normalized["payments"][0]
    text = f"""# Central settings for rocket_last scripts.
# This file is auto-synced from payments.json.
last_balance = {last_balance}
type = {first["type"]!r}

history_new_payment_name = {first["history_new_payment_name"]!r}
history_new_payment_amount = {int(first["history_new_payment_amount"])}
details_new_payment_name = {first["details_new_payment_name"]!r}

transaction_date = {first["transaction_date"]!r}
transaction_time = {first["transaction_time"]!r}
transaction_time_zone = {first["transaction_time_zone"]!r}

sbp_telephone = {first["sbp_telephone"]!r}
bank = {first["bank"]!r}
card_number = {first["card_number"]!r}


def transaction_tz_suffix() -> str:
    raw = str(transaction_time_zone).strip()
    if not raw:
        return "+0000"
    u = raw.upper()
    if u in ("Z", "UTC"):
        return "+0000"
    compact = raw.replace(":", "")
    if len(compact) == 5 and compact[0] in "+-" and compact[1:].isdigit():
        return compact
    return "+0000"
"""
    ast.parse(text)
    cfg = _legacy_config_path()
    if cfg.exists():
        shutil.copy2(cfg, cfg.with_suffix(".py.bak"))
    cfg.write_text(text, encoding="utf-8")

