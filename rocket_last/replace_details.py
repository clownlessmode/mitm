import json
import hashlib
from pathlib import Path
from typing import Any

from mitmproxy import http

import app_logger
from bank_mapper import get_bank_meta
from runtime_config import get_active_profile, normalize_type, normalize_tz_suffix

HOST_SUB = "dbo.rocketbank.ru"
DETAILS_PATH = "/v1/history/transaction"
PROJECT_DIR = Path(__file__).resolve().parent.parent
TEMPLATE_BY_TYPE = {
    "SBP": "details_sbp.json",
    "SPB": "details_sbp.json",  # поддержка частой опечатки
    "CARD": "details_card.json",
}
SCOPE = "replace_details"


def _normalized_type() -> str:
    profile = get_active_profile()
    return normalize_type(profile["data"]["type"])


def _is_target_request(flow: http.HTTPFlow) -> bool:
    if flow.request.method.upper() != "GET":
        return False
    if HOST_SUB not in (flow.request.host or ""):
        return False
    path = (flow.request.path or "").split("?")[0].rstrip("/")
    return path == DETAILS_PATH.rstrip("/")


def _load_template() -> dict | None:
    template_name = TEMPLATE_BY_TYPE.get(_normalized_type())
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


def _expected_transaction_id(template: dict[str, Any]) -> str:
    profile = get_active_profile()
    pdata = profile["data"]
    cheque = template.get("cheque")
    source_tid = ""
    if isinstance(cheque, dict):
        source_tid = str(cheque.get("transactionId") or "")
    return _build_seeded_id(
        source_id=source_tid,
        seed=pdata["history_new_payment_name"],
        digits_count=11,
    )


def _format_operation_time() -> str:
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
    profile = get_active_profile()
    pdata = profile["data"]
    date_raw = str(pdata["transaction_date"]).strip()
    time_raw = str(pdata["transaction_time"]).strip()
    try:
        yyyy, mm, dd = date_raw.split("-")
        hh, mi, _ss = time_raw.split(":")
    except ValueError:
        return f"{date_raw} {time_raw}".strip()
    month = months.get(mm, mm)
    return f"{int(dd)} {month}, {hh}:{mi}"


def _patch_operation_fields(template: dict[str, Any], tx_type: str) -> None:
    profile = get_active_profile()
    pdata = profile["data"]
    fields = template.get("operationFields")
    if not isinstance(fields, list):
        return

    bank_meta = get_bank_meta(pdata["bank"])
    formatted_time = _format_operation_time()
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
            item["value"] = str(pdata["sbp_telephone"]).strip()
        if tx_type == "SBP" and key == "sbpOperationId":
            source_sbp_id = str(item.get("value") or "")
            item["value"] = _build_seeded_id(
                source_id=source_sbp_id,
                seed=pdata["history_new_payment_name"],
                digits_count=31,
            )


def _patch_template(template: dict[str, Any]) -> None:
    profile = get_active_profile()
    pdata = profile["data"]
    tx_type = _normalized_type()

    if tx_type == "SBP":
        operation_name = str(pdata["details_new_payment_name"]).strip()
    else:
        operation_name = f"На карту {str(pdata['history_new_payment_name']).strip()}".strip()

    amount = int(pdata["history_new_payment_amount"])
    before_amount = int(pdata["last_balance"]) + int(pdata["history_new_payment_amount"])
    after_amount = int(pdata["last_balance"])

    template["operationName"] = operation_name
    template["transactionDateTime"] = (
        f"{str(pdata['transaction_date']).strip()}T"
        f"{str(pdata['transaction_time']).strip()}{normalize_tz_suffix(pdata['transaction_time_zone'])}"
    )
    generated_tid = _expected_transaction_id(template)

    main_amount = _set_if_dict(template, "mainAmount")
    main_amount["amount"] = amount

    if tx_type == "SBP":
        main_icon = _set_if_dict(template, "mainIcon")
        payer_name = str(pdata["history_new_payment_name"]).strip()
        main_icon["iconLiter"] = payer_name[:1].upper() if payer_name else ""

    balance = _set_if_dict(template, "balance")
    before = _set_if_dict(balance, "before")
    after = _set_if_dict(balance, "after")
    before["amount"] = before_amount
    after["amount"] = after_amount

    cheque = _set_if_dict(template, "cheque")
    cheque["transactionId"] = generated_tid

    _patch_operation_fields(template, tx_type)


def response(flow: http.HTTPFlow) -> None:
    if not _is_target_request(flow):
        return

    req_tid = (flow.request.query.get("transactionId") or "").strip()
    template = _load_template()
    if template is None:
        return
    expected_tid = _expected_transaction_id(template)
    if not expected_tid or req_tid != expected_tid:
        return

    _patch_template(template)
    flow.response.status_code = 200
    flow.response.text = json.dumps(template, ensure_ascii=False, separators=(",", ":"))

    profile = get_active_profile()
    app_logger.info(
        SCOPE,
        "details response replaced",
        method=flow.request.method,
        path=flow.request.path,
        transaction_id=expected_tid,
        template_type=_normalized_type(),
        active_profile=profile["id"],
    )
