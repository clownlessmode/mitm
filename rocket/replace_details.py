import copy
import json
from typing import Any
from urllib.parse import parse_qs, urlparse

from mitmproxy import http

from replace_history import TARGET_TRANSACTION_ID

HOST_SUB = "dbo.rocketbank.ru"
TRANSACTION_DETAIL_PATH = "/v1/history/transaction"

# --- Ответ для GET …/history/transaction?transactionId=<тот же, что TARGET_TRANSACTION_ID в replace_history.py>) ---
# A) PATCH: точечная подстановка поверх пришедшего JSON (dict объединяется рекурсивно; list/скаляр в patch заменяет целиком).
DETAIL_PATCH: dict[str, Any] = {
    "mainIcon": {
        "iconLiter": "А",
        "iconCode": "mcc_rashod"
    },
    "operationName": "Артур Ильдарович Х",
    "repeatableInfo": {
        "operationId": "69938279093",
        "repeatableType": "PHONE",
        "repeatable": True
    },
    "returnableInfo": {
        "isReturnable": False
    },
    "mainAmount": {
        "amount": 15000,
        "currencySymbol": "₽",
        "direction": "OUTGOING"
    },
    "operationStatus": {
        "status": "ENTRIED"
    },
    "operationFields": [
        {
            "title": "Комиссия",
            "value": "Нет",
            "key": "fee"
        },
        {
            "title": "Статус платежа",
            "value": "Выполнена",
            "icon": {
                "iconCode": "statusicon_done"
            },
            "key": "operationStatus"
        },
        {
            "title": "Дата и время",
            "value": "08 мая, 14:09",
            "key": "operationTime"
        },
        {
            "title": "Категория",
            "value": "Переводы",
            "key": "category",
            "isChangeAvailable": True
        },
        {
            "title": "Счёт списания",
            "value": "Мой счёт",
            "key": "sourceProductName"
        },
        {
            "title": "Перевод по номеру телефона",
            "value": "Через СБП",
            "icon": {
                "iconCode": "sbp"
            },
            "key": "phoneTransferMethod"
        },
        {
            "title": "Номер телефона получателя",
            "value": "+7 987 145-14-30",
            "key": "phoneNumber"
        },
        {
            "title": "Банк получателя",
            "value": "ПАО СБЕРБАНК",
            "icon": {
                "iconUrl": "https://cdn.lifetechx.ru/icons/banks/icon_square/sberbank_square.png",
                "iconCode": "statusicon_unknownbank"
            },
            "key": "bankName"
        },
        {
            "title": "Номер операции в СБП",
            "value": "A61280709064670X0G10010011760501",
            "key": "sbpOperationId"
        }
    ],
    "balance": {
        "before": {
            "amount": 320963.4+15000,
            "currencySymbol": "₽"
        },
        "after": {
            "amount": 320963.4,
            "currencySymbol": "₽"
        },
        "separator": "→"
    },
    "cheque": {
        "allowed": True,
        "productType": "CARD",
        "productId": "13856641038",
        "transactionId": "M69938279093"
    },
    "categoryChange": {
        "categoryCode": "CAT_TRANSFERS",
        "operationId": "69938279093"
    },
    "template": {
        "isAllowed": True,
        "originalOperationUuid": "f44396b4-311b-40c9-9cfe-b6d372ca6e07",
        "operationType": "PHONE"
    }
}


# B) Если не None — подставить всё тело ответа этим объектом (PATCH не используется).
DETAIL_REPLACE_FULL_JSON: dict[str, Any] | None = None

MAX_JSON_LOG_CHARS = 50_000


def _parsed_url(flow: http.HTTPFlow) -> tuple[str, str]:
    u = urlparse(flow.request.pretty_url)
    return u.path.rstrip("/"), u.query


def _query_transaction_id(query: str) -> str | None:
    qs = parse_qs(query, keep_blank_values=True)
    vals = qs.get("transactionId")
    return vals[0] if vals else None


def _is_target_detail_request(flow: http.HTTPFlow) -> bool:
    if HOST_SUB not in (flow.request.host or ""):
        return False
    path_no_q, query = _parsed_url(flow)
    if path_no_q != TRANSACTION_DETAIL_PATH.rstrip("/"):
        return False
    return _query_transaction_id(query) == TARGET_TRANSACTION_ID


def _deep_merge(base: Any, patch: dict[str, Any]) -> Any:
    if not isinstance(base, dict):
        return copy.deepcopy(patch)
    out: dict[str, Any] = dict(copy.deepcopy(base))
    for k, v in patch.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


def response(flow: http.HTTPFlow) -> None:
    if not _is_target_detail_request(flow):
        return

    has_patch = bool(DETAIL_PATCH)
    has_full = DETAIL_REPLACE_FULL_JSON is not None
    if not has_patch and not has_full:
        return

    ct = flow.response.headers.get("content-type", "")
    if "json" not in ct.lower():
        return

    text = flow.response.text or ""
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return

    if has_full:
        merged = copy.deepcopy(DETAIL_REPLACE_FULL_JSON)
    else:
        merged = _deep_merge(data, DETAIL_PATCH)

    flow.response.text = json.dumps(merged, ensure_ascii=False, separators=(",", ":"))

    print(f"\n📍 route: {flow.request.method} {flow.request.pretty_url}")
    print(f"📍 host={flow.request.host!r} path={flow.request.path!r}")
    print(f"\n🔁 transaction detail transactionId={TARGET_TRANSACTION_ID!r}")
    print(f"  режим: {'полная замена тела' if has_full else 'DETAIL_PATCH merge'}")

    body_for_log = flow.response.text or ""
    if len(body_for_log) > MAX_JSON_LOG_CHARS:
        body_for_log = (
            body_for_log[:MAX_JSON_LOG_CHARS]
            + f"\n… [обрезано, всего {len(flow.response.text)} символов]\n"
        )
    print(f"\n📄 response body:\n{body_for_log}\n")
    print("✅ Ответ изменён\n")
