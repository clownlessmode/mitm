import json
from typing import Any

from mitmproxy import http

HOST_SUB = "dbo.rocketbank.ru"
HISTORY_PATH = "/v1/history/list"

TARGET_TRANSACTION_ID = "M69938279093"

# None = поле не менять
NEW_OPERATION_NAME: str | None = "АРТУР Х."
NEW_MAIN_AMOUNT: int | float | None = 15000
NEW_ICON_URL: str | None = None

MAX_JSON_LOG_CHARS = 50_000


def _is_history_list(flow: http.HTTPFlow) -> bool:
    if HOST_SUB not in (flow.request.host or ""):
        return False
    path = (flow.request.path or "").split("?")[0].rstrip("/")
    return path == HISTORY_PATH.rstrip("/")


def _find_and_patch(data: Any) -> dict | None:
    """
    Ищет первую операцию с detailAction.transactionId == TARGET_TRANSACTION_ID
    и правит operationName / mainAmount.amount. Возвращает сам объект операции или None.
    """
    if not isinstance(data, list):
        return None
    for block in data:
        if not isinstance(block, dict):
            continue
        ops = block.get("operationsList")
        if not isinstance(ops, list):
            continue
        for op in ops:
            if not isinstance(op, dict):
                continue
            da = op.get("detailAction")
            if not isinstance(da, dict):
                continue
            if da.get("transactionId") != TARGET_TRANSACTION_ID:
                continue
            if NEW_OPERATION_NAME is not None:
                op["operationName"] = NEW_OPERATION_NAME
                icon = op.get("mainIcon")
                if not isinstance(icon, dict):
                    icon = {}
                    op["mainIcon"] = icon
                icon["iconLiter"] = NEW_OPERATION_NAME[:1].capitalize()
            if NEW_ICON_URL is not None:
                icon = op.get("mainIcon")
                if not isinstance(icon, dict):
                    icon = {}
                    op["mainIcon"] = icon
                icon["iconUrl"] = NEW_ICON_URL
            if NEW_MAIN_AMOUNT is not None:
                ma = op.get("mainAmount")
                if not isinstance(ma, dict):
                    ma = {}
                    op["mainAmount"] = ma
                ma["amount"] = NEW_MAIN_AMOUNT
            return op
    return None


def response(flow: http.HTTPFlow) -> None:
    if not _is_history_list(flow):
        return
    if NEW_OPERATION_NAME is None and NEW_MAIN_AMOUNT is None and NEW_ICON_URL is None:
        return

    ct = flow.response.headers.get("content-type", "")
    if "json" not in ct.lower():
        return

    text = flow.response.text or ""
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return

    patched_op = _find_and_patch(data)
    if patched_op is None:
        return

    flow.response.text = json.dumps(data, ensure_ascii=False, separators=(",", ":"))

    tid = patched_op.get("detailAction", {}).get("transactionId")
    print(f"\n📍 route: {flow.request.method} {flow.request.pretty_url}")
    print(f"📍 host={flow.request.host!r} path={flow.request.path!r}")
    print(f"\n🔁 history: transactionId={tid!r}")
    if NEW_OPERATION_NAME is not None:
        print(f"  operationName -> {NEW_OPERATION_NAME!r}")
        print(f"  mainIcon.iconLiter -> {NEW_OPERATION_NAME[:1].capitalize()!r}")
    if NEW_ICON_URL is not None:
        print(f"  mainIcon.iconUrl -> {NEW_ICON_URL!r}")
    if NEW_MAIN_AMOUNT is not None:
        print(f"  mainAmount.amount -> {NEW_MAIN_AMOUNT!r}")

    body_for_log = flow.response.text
    if len(body_for_log) > MAX_JSON_LOG_CHARS:
        body_for_log = (
            body_for_log[:MAX_JSON_LOG_CHARS]
            + f"\n… [обрезано, всего {len(flow.response.text)} символов]\n"
        )
    print(f"\n📄 response body:\n{body_for_log}\n")
    print("✅ Ответ изменён\n")
