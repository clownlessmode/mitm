import json
import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from mitmproxy import http

import app_logger
from bank_mapper import get_bank_meta
from runtime_config import get_active_profile, get_profile_payments, normalize_type, normalize_tz_suffix

HOST_SUB = "dbo.rocketbank.ru"
HISTORY_PATH = "/v1/history/list"
PROJECT_DIR = Path(__file__).resolve().parent.parent
TEMPLATE_BY_TYPE = {
    "SBP": "to_sbp.json",
    "CARD": "to_card.json",
}
SCOPE = "add_to_history"


def _is_history_list(flow: http.HTTPFlow) -> bool:
    if HOST_SUB not in (flow.request.host or ""):
        return False
    path = (flow.request.path or "").split("?")[0].rstrip("/")
    return path == HISTORY_PATH.rstrip("/")


def _seeded_digits(seed: str, salt: str, length: int) -> str:
    material = f"{seed}|{salt}".encode("utf-8")
    digits = ""
    while len(digits) < length:
        material = hashlib.sha256(material).hexdigest().encode("utf-8")
        for ch in material.decode("utf-8"):
            if len(digits) >= length:
                break
            digits += str(int(ch, 16) % 10)
    return digits[:length]


def _build_seeded_id(source_id: str, seed: str, digits_count: int) -> str:
    source = str(source_id).strip()
    prefix = source[:1] if source else "M"
    numeric = _seeded_digits(seed=str(seed).strip(), salt=prefix, length=digits_count)
    return f"{prefix}{numeric}"


def _now_iso_utc() -> str:
    # Формат как в API: 2026-05-09T02:27:31+0000
    return datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+0000")


def _datetime_for_payment(payment: dict[str, Any]) -> str:
    # Формируем время операции строго из конфига.
    date_part = str(payment["transaction_date"]).strip()
    time_part = str(payment["transaction_time"]).strip()
    if date_part and time_part:
        return f"{date_part}T{time_part}{normalize_tz_suffix(payment['transaction_time_zone'])}"
    return _now_iso_utc()


def _build_operation_name(payment: dict[str, Any]) -> str:
    custom_name = str(payment["history_new_payment_name"]).strip()
    tx_type = normalize_type(payment["type"])
    if tx_type == "CARD":
        return f"На карту {custom_name}".strip()
    return custom_name


def _build_icon_liter(payment: dict[str, Any]) -> str:
    name = str(payment["history_new_payment_name"]).strip()
    if not name:
        return ""
    return name[:1].upper()


def _set_if_dict(target: dict[str, Any], key: str) -> dict[str, Any]:
    value = target.get(key)
    if not isinstance(value, dict):
        value = {}
        target[key] = value
    return value


def _load_template(tx_type: str) -> dict[str, Any] | None:
    template_name = TEMPLATE_BY_TYPE.get(normalize_type(tx_type))
    if template_name is None:
        return None

    template_path = PROJECT_DIR / template_name
    try:
        template_data = json.loads(template_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None

    if not isinstance(template_data, dict):
        return None
    return template_data


def _build_operation(payment: dict[str, Any], index: int) -> dict[str, Any] | None:
    tx_type = normalize_type(payment["type"])
    new_op = _load_template(tx_type)
    if new_op is None:
        return None

    new_op["transactionDateTime"] = _datetime_for_payment(payment)
    new_op["operationName"] = _build_operation_name(payment)

    main_amount = _set_if_dict(new_op, "mainAmount")
    main_amount["amount"] = int(payment["history_new_payment_amount"])

    if tx_type == "SBP":
        main_icon = _set_if_dict(new_op, "mainIcon")
        main_icon["iconLiter"] = _build_icon_liter(payment)

    bank_meta = get_bank_meta(payment["bank"])
    status_icon = _set_if_dict(new_op, "statusIcon")
    status_icon["iconUrl"] = bank_meta["icon_url"]

    detail_action = _set_if_dict(new_op, "detailAction")
    source_tid = str(detail_action.get("transactionId") or "")
    seed = str(payment["history_new_payment_name"])
    if index > 0:
        seed = f"{seed}|{index}"
    detail_action["transactionId"] = _build_seeded_id(
        source_id=source_tid,
        seed=seed,
        digits_count=11,
    )
    return new_op


def _append_payments(data: Any) -> list[dict[str, Any]]:
    if not isinstance(data, list) or not data:
        return []

    ops: list[Any] | None = None
    for block in data:
        if not isinstance(block, dict):
            continue
        operations_list = block.get("operationsList")
        if isinstance(operations_list, list):
            ops = operations_list
            break

    if ops is None:
        return []
    profile = get_active_profile()
    pdata = profile["data"]
    payments = get_profile_payments(pdata)
    created: list[dict[str, Any]] = []
    # Чтобы в истории был порядок как в UI (1,2,3), вставляем в обратном.
    for idx in range(len(payments) - 1, -1, -1):
        payment = payments[idx]
        new_op = _build_operation(payment, index=idx)
        if new_op is None:
            continue
        ops.insert(0, new_op)
        created.append(new_op)
    created.reverse()
    return created


def response(flow: http.HTTPFlow) -> None:
    if not _is_history_list(flow):
        return

    ct = flow.response.headers.get("content-type", "")
    if "json" not in ct.lower():
        return

    text = flow.response.text or ""
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return

    created_ops = _append_payments(data)
    if not created_ops:
        return

    flow.response.text = json.dumps(data, ensure_ascii=False, separators=(",", ":"))

    profile = get_active_profile()
    pdata = profile["data"]
    first_tid = created_ops[0].get("detailAction", {}).get("transactionId")
    last_tid = created_ops[-1].get("detailAction", {}).get("transactionId")
    app_logger.info(
        SCOPE,
        "history operations inserted",
        method=flow.request.method,
        path=flow.request.path,
        count=len(created_ops),
        first_transaction_id=first_tid,
        last_transaction_id=last_tid,
        operation_type=pdata["type"],
        active_profile=profile["id"],
    )
