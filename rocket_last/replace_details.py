import json
import hashlib
from pathlib import Path
from typing import Any

from mitmproxy import http

import app_logger
from bank_mapper import get_bank_meta
from runtime_config import get_store, normalize_type, normalize_tz_suffix

HOST_SUB = "dbo.rocketbank.ru"
DETAILS_PATH = "/v1/history/transaction"
PROJECT_DIR = Path(__file__).resolve().parent.parent
TEMPLATE_BY_TYPE = {
    "SBP": "details_sbp.json",
    "CARD": "details_card.json",
}
HISTORY_SOURCE_BY_TYPE = {
    "SBP": "M69947658350",
    "CARD": "M69949783738",
}
SCOPE = "replace_details"


def _is_target_request(flow: http.HTTPFlow) -> bool:
    if flow.request.method.upper() != "GET":
        return False
    if HOST_SUB not in (flow.request.host or ""):
        return False
    path = (flow.request.path or "").split("?")[0].rstrip("/")
    return path == DETAILS_PATH.rstrip("/")


def _load_template(payment_type: str) -> dict | None:
    template_name = TEMPLATE_BY_TYPE.get(normalize_type(payment_type))
    if template_name is None:
        return None
    template_path = PROJECT_DIR / template_name
    try:
        data = json.loads(template_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    return data


def _set_if_dict(target: dict[str, Any], key: str) -> dict[str, Any]:
    value = target.get(key)
    if not isinstance(value, dict):
        value = {}
        target[key] = value
    return value


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


def _expected_transaction_id(seed: str, source_tid: str) -> str:
    return _build_seeded_id(
        source_id=source_tid,
        seed=seed,
        digits_count=11,
    )


def _payment_seed(payment: dict[str, Any], index: int) -> str:
    seed = str(payment["history_new_payment_name"])
    if index > 0:
        seed = f"{seed}|{index}"
    return seed


def _find_payment_by_tid(req_tid: str) -> tuple[dict[str, Any], int] | None:
    store = get_store()
    for idx, payment in enumerate(store["payments"]):
        tx_type = normalize_type(payment["type"])
        source_tid = HISTORY_SOURCE_BY_TYPE.get(tx_type)
        if not source_tid:
            continue
        expected = _expected_transaction_id(_payment_seed(payment, idx), source_tid)
        if req_tid == expected:
            return payment, idx
    return None


def _format_operation_time(payment: dict[str, Any]) -> str:
    months = {
        "01": "января",
        "02": "февраля",
        "03": "марта",
        "04": "апреля",
        "05": "мая",
        "06": "июня",
        "07": "июля",
        "08": "августа",
        "09": "сентября",
        "10": "октября",
        "11": "ноября",
        "12": "декабря",
    }
    date_raw = str(payment["transaction_date"]).strip()
    time_raw = str(payment["transaction_time"]).strip()
    try:
        yyyy, mm, dd = date_raw.split("-")
        hh, mi, _ss = time_raw.split(":")
    except ValueError:
        return f"{date_raw} {time_raw}".strip()
    month = months.get(mm, mm)
    return f"{int(dd)} {month}, {hh}:{mi}"


def _patch_operation_fields(template: dict[str, Any], tx_type: str, payment: dict[str, Any], index: int) -> None:
    fields = template.get("operationFields")
    if not isinstance(fields, list):
        return

    bank_meta = get_bank_meta(payment["bank"])
    formatted_time = _format_operation_time(payment)
    for item in fields:
        if not isinstance(item, dict):
            continue
        key = item.get("key")
        if key == "operationTime":
            item["value"] = formatted_time
        if key == "bankName":
            item["value"] = bank_meta["name"]
            icon = _set_if_dict(item, "icon")
            icon["iconUrl"] = bank_meta["icon_url"]
        if tx_type == "SBP" and key == "phoneNumber":
            item["value"] = str(payment["sbp_telephone"]).strip()
        if tx_type == "SBP" and key == "sbpOperationId":
            source_sbp_id = str(item.get("value") or "")
            item["value"] = _build_seeded_id(
                source_id=source_sbp_id,
                seed=_payment_seed(payment, index),
                digits_count=31,
            )


def _patch_template(template: dict[str, Any], payment: dict[str, Any], index: int, req_tid: str) -> None:
    store = get_store()
    tx_type = normalize_type(payment["type"])

    if tx_type == "SBP":
        operation_name = str(payment["details_new_payment_name"]).strip()
    else:
        operation_name = f"На карту {str(payment['history_new_payment_name']).strip()}".strip()

    amount = int(payment["history_new_payment_amount"])
    before_amount = int(store["last_balance"]) + int(payment["history_new_payment_amount"])
    after_amount = int(store["last_balance"])

    template["operationName"] = operation_name
    template["transactionDateTime"] = (
        f"{str(payment['transaction_date']).strip()}T"
        f"{str(payment['transaction_time']).strip()}{normalize_tz_suffix(payment['transaction_time_zone'])}"
    )
    generated_tid = req_tid

    main_amount = _set_if_dict(template, "mainAmount")
    main_amount["amount"] = amount

    if tx_type == "SBP":
        main_icon = _set_if_dict(template, "mainIcon")
        payer_name = str(payment["history_new_payment_name"]).strip()
        main_icon["iconLiter"] = payer_name[:1].upper() if payer_name else ""

    balance = _set_if_dict(template, "balance")
    before = _set_if_dict(balance, "before")
    after = _set_if_dict(balance, "after")
    before["amount"] = before_amount
    after["amount"] = after_amount

    cheque = _set_if_dict(template, "cheque")
    cheque["transactionId"] = generated_tid

    _patch_operation_fields(template, tx_type, payment, index)


def response(flow: http.HTTPFlow) -> None:
    if not _is_target_request(flow):
        return

    req_tid = (flow.request.query.get("transactionId") or "").strip()
    selected = _find_payment_by_tid(req_tid)
    if selected is None:
        return
    payment, index = selected
    template = _load_template(payment["type"])
    if template is None:
        return

    _patch_template(template, payment, index, req_tid)
    flow.response.status_code = 200
    flow.response.text = json.dumps(template, ensure_ascii=False, separators=(",", ":"))

    app_logger.info(
        SCOPE,
        "details response replaced",
        method=flow.request.method,
        path=flow.request.path,
        transaction_id=req_tid,
        template_type=normalize_type(payment["type"]),
        payment_name=payment["history_new_payment_name"],
        payment_index=index,
    )
