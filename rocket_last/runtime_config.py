from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import config as legacy_config

CONFIG_KEYS = (
    "last_balance",
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
    "payments",
)

DEFAULTS: dict[str, Any] = {
    "last_balance": 0,
    "type": "SBP",
    "history_new_payment_name": "",
    "history_new_payment_amount": 0,
    "details_new_payment_name": "",
    "transaction_date": "",
    "transaction_time": "",
    "transaction_time_zone": "+0000",
    "sbp_telephone": "",
    "bank": "UNKNOWN",
    "card_number": "",
    "payments": [],
}


def _profiles_path() -> Path:
    return Path(__file__).resolve().parent / "profiles.json"


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


def _legacy_profile_data() -> dict[str, Any]:
    return {
        "last_balance": getattr(legacy_config, "last_balance", DEFAULTS["last_balance"]),
        "type": getattr(legacy_config, "type", DEFAULTS["type"]),
        "history_new_payment_name": getattr(
            legacy_config, "history_new_payment_name", DEFAULTS["history_new_payment_name"]
        ),
        "history_new_payment_amount": getattr(
            legacy_config,
            "history_new_payment_amount",
            DEFAULTS["history_new_payment_amount"],
        ),
        "details_new_payment_name": getattr(
            legacy_config,
            "details_new_payment_name",
            DEFAULTS["details_new_payment_name"],
        ),
        "transaction_date": getattr(legacy_config, "transaction_date", DEFAULTS["transaction_date"]),
        "transaction_time": getattr(legacy_config, "transaction_time", DEFAULTS["transaction_time"]),
        "transaction_time_zone": getattr(
            legacy_config,
            "transaction_time_zone",
            DEFAULTS["transaction_time_zone"],
        ),
        "sbp_telephone": getattr(legacy_config, "sbp_telephone", DEFAULTS["sbp_telephone"]),
        "bank": getattr(legacy_config, "bank", DEFAULTS["bank"]),
        "card_number": getattr(legacy_config, "card_number", DEFAULTS["card_number"]),
    }


def sanitize_profile_data(raw: dict[str, Any]) -> dict[str, Any]:
    data = dict(DEFAULTS)
    for key in CONFIG_KEYS:
        if key in raw:
            data[key] = raw[key]
    data["last_balance"] = _to_int(data["last_balance"], 0)
    data["history_new_payment_amount"] = _to_int(data["history_new_payment_amount"], 0)
    data["type"] = normalize_type(data["type"])
    data["transaction_time_zone"] = normalize_tz_suffix(data["transaction_time_zone"])
    data["history_new_payment_name"] = str(data["history_new_payment_name"]).strip()
    data["details_new_payment_name"] = str(data["details_new_payment_name"]).strip()
    data["transaction_date"] = str(data["transaction_date"]).strip()
    data["transaction_time"] = str(data["transaction_time"]).strip()
    data["sbp_telephone"] = str(data["sbp_telephone"]).strip()
    data["bank"] = str(data["bank"]).strip().upper() or "UNKNOWN"
    data["card_number"] = str(data["card_number"]).strip()
    data["payments"] = sanitize_payments(raw.get("payments"), fallback=data)
    if data["payments"]:
        first = data["payments"][0]
        data["type"] = first["type"]
        data["history_new_payment_name"] = first["history_new_payment_name"]
        data["history_new_payment_amount"] = first["history_new_payment_amount"]
        data["details_new_payment_name"] = first["details_new_payment_name"]
        data["transaction_date"] = first["transaction_date"]
        data["transaction_time"] = first["transaction_time"]
        data["transaction_time_zone"] = first["transaction_time_zone"]
        data["sbp_telephone"] = first["sbp_telephone"]
        data["bank"] = first["bank"]
        data["card_number"] = first["card_number"]
    return data


def sanitize_payment(raw: dict[str, Any], fallback: dict[str, Any]) -> dict[str, Any]:
    name = str(raw.get("history_new_payment_name", fallback["history_new_payment_name"])).strip()
    details_name = str(raw.get("details_new_payment_name", fallback["details_new_payment_name"])).strip()
    amount = _to_int(raw.get("history_new_payment_amount", fallback["history_new_payment_amount"]), 0)
    tx_type = normalize_type(raw.get("type", fallback["type"]))
    tx_date = str(raw.get("transaction_date", fallback["transaction_date"])).strip()
    tx_time = str(raw.get("transaction_time", fallback["transaction_time"])).strip()
    tx_tz = normalize_tz_suffix(raw.get("transaction_time_zone", fallback["transaction_time_zone"]))
    sbp_phone = str(raw.get("sbp_telephone", fallback["sbp_telephone"])).strip()
    bank = str(raw.get("bank", fallback["bank"])).strip().upper() or "UNKNOWN"
    card_number = str(raw.get("card_number", fallback["card_number"])).strip()
    return {
        "type": tx_type,
        "history_new_payment_name": name,
        "history_new_payment_amount": amount,
        "details_new_payment_name": details_name,
        "transaction_date": tx_date,
        "transaction_time": tx_time,
        "transaction_time_zone": tx_tz,
        "sbp_telephone": sbp_phone,
        "bank": bank,
        "card_number": card_number,
    }


def sanitize_payments(raw: Any, fallback: dict[str, Any]) -> list[dict[str, Any]]:
    if not isinstance(raw, list):
        return []
    out: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        out.append(sanitize_payment(item, fallback=fallback))
    return out


def get_profile_payments(profile_data: dict[str, Any]) -> list[dict[str, Any]]:
    payments = sanitize_payments(profile_data.get("payments"), fallback=profile_data)
    if payments:
        return payments
    return [sanitize_payment({}, fallback=profile_data)]


def ensure_store() -> dict[str, Any]:
    path = _profiles_path()
    if path.exists():
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            loaded = {}
    else:
        loaded = {}

    profiles = loaded.get("profiles")
    active_profile_id = loaded.get("active_profile_id")

    if not isinstance(profiles, list) or not profiles:
        profiles = [
            {
                "id": "default",
                "title": "Default",
                "data": sanitize_profile_data(_legacy_profile_data()),
            }
        ]
        active_profile_id = "default"
        save_store({"active_profile_id": active_profile_id, "profiles": profiles})
        return {"active_profile_id": active_profile_id, "profiles": profiles}

    normalized_profiles: list[dict[str, Any]] = []
    seen: set[str] = set()
    for idx, profile in enumerate(profiles):
        if not isinstance(profile, dict):
            continue
        pid = str(profile.get("id") or "").strip() or f"profile-{idx + 1}"
        if pid in seen:
            pid = f"{pid}-{idx + 1}"
        seen.add(pid)
        title = str(profile.get("title") or pid).strip() or pid
        pdata_raw = profile.get("data")
        pdata = sanitize_profile_data(pdata_raw if isinstance(pdata_raw, dict) else {})
        normalized_profiles.append({"id": pid, "title": title, "data": pdata})

    if not normalized_profiles:
        normalized_profiles = [
            {"id": "default", "title": "Default", "data": sanitize_profile_data(_legacy_profile_data())}
        ]
        active_profile_id = "default"

    ids = {p["id"] for p in normalized_profiles}
    if active_profile_id not in ids:
        active_profile_id = normalized_profiles[0]["id"]

    result = {"active_profile_id": active_profile_id, "profiles": normalized_profiles}
    save_store(result)
    return result


def save_store(store: dict[str, Any]) -> None:
    path = _profiles_path()
    text = json.dumps(store, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    path.write_text(text, encoding="utf-8")


def get_active_profile() -> dict[str, Any]:
    store = ensure_store()
    active_profile_id = str(store.get("active_profile_id") or "")
    for profile in store["profiles"]:
        if profile["id"] == active_profile_id:
            return profile
    return store["profiles"][0]

