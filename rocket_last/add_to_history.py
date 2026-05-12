import json
import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from mitmproxy import http

import app_logger
from bank_mapper import get_bank_meta
from runtime_config import get_store, normalize_type, normalize_tz_suffix, normalize_direction

HOST_SUB = "dbo.rocketbank.ru"
HISTORY_PATH = "/v1/history/list"
PROJECT_DIR = Path(__file__).resolve().parent.parent
TEMPLATE_BY_TYPE = {
    "SBP": "to_sbp.json",
    "CARD": "to_card.json",
    "NALIK": "nalik.json",
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


def _parse_transaction_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None

    raw = value.strip()
    if not raw:
        return None

    # История в приложении визуально сортируется по написанным дате/времени.
    # Поэтому для позиции в списке не переводим +0700/+0000 в абсолютный UTC.
    raw = raw.replace("Z", "")
    for sign in ("+", "-"):
        tz_pos = raw.rfind(sign)
        if tz_pos > len("YYYY-MM-DDT"):
            raw = raw[:tz_pos]
            break

    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%S.%f"):
        try:
            return datetime.strptime(raw, fmt)
        except ValueError:
            continue
    return None


def _insert_operation_by_time(ops: list[Any], new_op: dict[str, Any]) -> None:
    new_dt = _parse_transaction_datetime(new_op.get("transactionDateTime"))
    if new_dt is None:
        ops.insert(0, new_op)
        return

    for pos, op in enumerate(ops):
        if not isinstance(op, dict):
            continue
        existing_dt = _parse_transaction_datetime(op.get("transactionDateTime"))
        if existing_dt is not None and new_dt > existing_dt:
            ops.insert(pos, new_op)
            return

    ops.append(new_op)


def _sort_operations_by_time(ops: list[Any]) -> None:
    indexed_ops = list(enumerate(ops))

    def sort_key(indexed_op: tuple[int, Any]) -> datetime:
        _original_index, op = indexed_op
        if not isinstance(op, dict):
            return datetime.min
        parsed = _parse_transaction_datetime(op.get("transactionDateTime"))
        if parsed is None:
            return datetime.min
        return parsed

    indexed_ops.sort(key=sort_key, reverse=True)
    ops[:] = [op for _original_index, op in indexed_ops]


def _nalik_operation_title(payment: dict[str, Any]) -> str:
    if normalize_direction(payment.get("direction")) == "INCOMING":
        return "Внесение наличных"
    return "Снятие наличных"


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
    if tx_type == "NALIK":
        new_op["operationName"] = _nalik_operation_title(payment)
        main_icon = _set_if_dict(new_op, "mainIcon")
        main_icon["icon"] = "cash_ATM"
    else:
        new_op["operationName"] = _build_operation_name(payment)

    main_amount = _set_if_dict(new_op, "mainAmount")
    main_amount["amount"] = int(payment["history_new_payment_amount"])
    main_amount["direction"] = normalize_direction(payment.get("direction"))

    if tx_type == "SBP":
        main_icon = _set_if_dict(new_op, "mainIcon")
        main_icon["iconLiter"] = _build_icon_liter(payment)

    if tx_type != "NALIK":
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
    store = get_store()
    payments = list(store["payments"])
    created: list[dict[str, Any]] = []
    for idx, payment in enumerate(payments):
        new_op = _build_operation(payment, index=idx)
        if new_op is None:
            continue
        _insert_operation_by_time(ops, new_op)
        created.append(new_op)
    if created:
        _sort_operations_by_time(ops)
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

    store = get_store()
    first = store["payments"][0]
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
        first_operation_type=first["type"],
    )
