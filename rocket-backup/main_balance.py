import re
from mitmproxy import http

# Только пара ключ–значение в JSON: "balance": <число> (запятая после числа не трогаем)
NUM = r"-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?"
PATTERN = re.compile(r'("balance")\s*:\s*(' + NUM + r")")

BALANCE_VALUE = 320963
MAX_JSON_LOG_CHARS = 50_000


def response(flow: http.HTTPFlow) -> None:
    source_text = flow.response.text or ""
    if '"balance"' not in source_text:
        return

    changes: list[tuple[str, str]] = []

    def replace_match(m: re.Match) -> str:
        old_full = m.group(0)
        new_full = f'{m.group(1)}:{BALANCE_VALUE}'
        changes.append((old_full, new_full))
        return new_full

    new_text = PATTERN.sub(replace_match, source_text)

    if not changes:
        return

    flow.response.text = new_text

    print(f"\n📍 route: {flow.request.method} {flow.request.pretty_url}")
    print(f"📍 host={flow.request.host!r} path={flow.request.path!r}")
    print(f'\n🔁 Замены по ключу JSON "balance" -> {BALANCE_VALUE}: {len(changes)} шт.')
    for old_full, new_full in changes:
        print(f"  {old_full!r} -> {new_full!r}")

    body_for_log = new_text
    if len(body_for_log) > MAX_JSON_LOG_CHARS:
        body_for_log = (
            body_for_log[:MAX_JSON_LOG_CHARS]
            + f"\n… [обрезано, всего {len(new_text)} символов]\n"
        )
    print(f"\n📄 response body:\n{body_for_log}\n")
    print("✅ Ответ изменён\n")
