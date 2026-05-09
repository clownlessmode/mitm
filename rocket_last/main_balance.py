import re

from mitmproxy import http

import app_logger
from runtime_config import get_store

# Только пара ключ–значение в JSON: "balance": <число> (запятая после числа не трогаем)
NUM = r"-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?"
PATTERN = re.compile(r'("balance")\s*:\s*(' + NUM + r")")
SCOPE = "main_balance"


def response(flow: http.HTTPFlow) -> None:
    if flow.response is None:
        return

    req_path = (flow.request.path or "").split("?")[0]
    if "cheque-pdf" in req_path:
        return
    if "application/pdf" in (flow.response.headers.get("content-type") or "").lower():
        return

    source_text = flow.response.text or ""
    if '"balance"' not in source_text:
        return

    store = get_store()
    balance_value = int(store["last_balance"])
    changes: list[tuple[str, str]] = []

    def replace_match(m: re.Match) -> str:
        old_full = m.group(0)
        new_full = f'{m.group(1)}:{balance_value}'
        changes.append((old_full, new_full))
        return new_full

    new_text = PATTERN.sub(replace_match, source_text)
    if not changes:
        return

    flow.response.text = new_text
    app_logger.info(
        SCOPE,
        "balance fields rewritten",
        method=flow.request.method,
        path=flow.request.path,
        replacements=len(changes),
        balance=balance_value,
    )
