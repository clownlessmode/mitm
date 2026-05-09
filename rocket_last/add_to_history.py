import json
import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from mitmproxy import http

from config import (
    bank,
    history_new_payment_amount,
    history_new_payment_name,
    transaction_date,
    transaction_time,
    transaction_tz_suffix,
    type as payment_type,
)
from bank_mapper import get_bank_meta

HOST_SUB = "dbo.rocketbank.ru"
HISTORY_PATH = "/v1/history/list"
MAX_JSON_LOG_CHARS = 50_000
PROJECT_DIR = Path(__file__).resolve().parent.parent
TEMPLATE_BY_TYPE = {
    "SBP": "to_sbp.json",
    "SPB": "to_sbp.json",  # поддержка частой опечатки
    "CARD": "to_card.json",
}


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


def _normalized_type() -> str:
    normalized = str(payment_type).strip().upper()
    if normalized == "SPB":
        return "SBP"
    return normalized


def _datetime_from_config() -> str:
    # Формируем время операции строго из конфига.
    date_part = str(transaction_date).strip()
    time_part = str(transaction_time).strip()
    if date_part and time_part:
        return f"{date_part}T{time_part}{transaction_tz_suffix()}"
    return _now_iso_utc()


def _build_operation_name() -> str:
    custom_name = str(history_new_payment_name).strip()
    tx_type = _normalized_type()
    if tx_type == "CARD":
        return f"На карту {custom_name}".strip()
    return custom_name


def _build_icon_liter() -> str:
    name = str(history_new_payment_name).strip()
    if not name:
        return ""
    return name[:1].upper()


def _set_if_dict(target: dict[str, Any], key: str) -> dict[str, Any]:
    value = target.get(key)
    if not isinstance(value, dict):
        value = {}
        target[key] = value
    return value


def _load_template() -> dict[str, Any] | None:
    normalized_type = _normalized_type()
    template_name = TEMPLATE_BY_TYPE.get(normalized_type)
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


def _append_payment(data: Any) -> dict[str, Any] | None:
    if not isinstance(data, list) or not data:
        return None

    ops: list[Any] | None = None
    for block in data:
        if not isinstance(block, dict):
            continue
        operations_list = block.get("operationsList")
        if isinstance(operations_list, list):
            ops = operations_list
            break

    if ops is None:
        return None

    new_op = _load_template()
    if new_op is None:
        return None

    # Обновляем время операции по значениям из конфига.
    new_op["transactionDateTime"] = _datetime_from_config()
    new_op["operationName"] = _build_operation_name()

    main_amount = _set_if_dict(new_op, "mainAmount")
    main_amount["amount"] = history_new_payment_amount

    if _normalized_type() == "SBP":
        main_icon = _set_if_dict(new_op, "mainIcon")
        main_icon["iconLiter"] = _build_icon_liter()

    bank_meta = get_bank_meta(bank)
    status_icon = _set_if_dict(new_op, "statusIcon")
    status_icon["iconUrl"] = bank_meta["icon_url"]

    detail_action = _set_if_dict(new_op, "detailAction")
    source_tid = str(detail_action.get("transactionId") or "")
    detail_action["transactionId"] = _build_seeded_id(
        source_id=source_tid,
        seed=history_new_payment_name,
        digits_count=11,
    )

    # Вставляем наверх списка, чтобы операция была первой в истории.
    ops.insert(0, new_op)
    return new_op


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

    new_op = _append_payment(data)
    if new_op is None:
        return

    flow.response.text = json.dumps(data, ensure_ascii=False, separators=(",", ":"))

    tid = new_op.get("detailAction", {}).get("transactionId")
    print(f"\n📍 route: {flow.request.method} {flow.request.pretty_url}")
    print(f"📍 host={flow.request.host!r} path={flow.request.path!r}")
    print("\n➕ В историю добавлен новый платеж (первым):")
    print(f"  transactionId -> {tid!r}")
    print(f"  operationName -> {new_op.get('operationName')!r}")
    print(f"  mainAmount.amount -> {new_op.get('mainAmount', {}).get('amount')!r}")
    print(f"  operationType -> {payment_type!r}")
    print(f"  bank -> {get_bank_meta(bank)['name']!r}")

    body_for_log = flow.response.text
    if len(body_for_log) > MAX_JSON_LOG_CHARS:
        body_for_log = (
            body_for_log[:MAX_JSON_LOG_CHARS]
            + f"\n… [обрезано, всего {len(flow.response.text)} символов]\n"
        )
    print(f"\n📄 response body:\n{body_for_log}\n")
    print("✅ Ответ изменён\n")
