import re
from mitmproxy import http

# «Климент Александрович К» — любой регистр; между частями — пробелы; точка после «К» необязательна.
PATTERN = re.compile(
    r"Климент\s+Александрович\s+К(?:\.)?",
    re.IGNORECASE,
)
MAX_JSON_LOG_CHARS = 50_000


def response(flow: http.HTTPFlow) -> None:
    source_text = flow.response.text or ""
    counter = 0
    changes: list[tuple[str, str]] = []

    def replace_match(match: re.Match) -> str:
        nonlocal counter
        counter += 1
        old_value = match.group(0)
        marker = f"MITM {counter}"
        changes.append((old_value, marker))
        return marker

    new_text = PATTERN.sub(replace_match, source_text)

    if counter == 0:
        return

    flow.response.text = new_text

    print(f"\n📍 route: {flow.request.method} {flow.request.pretty_url}")
    print(f"📍 host={flow.request.host!r} path={flow.request.path!r}")
    print(
        '\n🔁 Поиск «Климент Александрович К»: вставлены «MITM 1», «MITM 2»… — в JSON ищи по подстроке "MITM".'
    )
    for old_value, marker in changes:
        print(f"  {old_value!r} -> {marker!r}")

    body_for_log = new_text
    if len(body_for_log) > MAX_JSON_LOG_CHARS:
        body_for_log = (
            body_for_log[:MAX_JSON_LOG_CHARS]
            + f"\n… [обрезано, всего {len(new_text)} символов]\n"
        )
    print(f"\n📄 response body:\n{body_for_log}\n")
    print("✅ Ответ изменён\n")
