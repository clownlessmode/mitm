from __future__ import annotations

import hashlib
import shutil
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from mitmproxy import http

from bank_mapper import get_bank_meta
from config import (
    bank,
    card_number,
    details_new_payment_name,
    history_new_payment_amount,
    history_new_payment_name,
    sbp_telephone,
    transaction_date,
    transaction_time,
    transaction_tz_suffix,
    type as payment_type,
)

HOST_SUB = "dbo.rocketbank.ru"
CHEQUE_PDF_PATH = "/v1/reports/cheque-pdf"

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_DIR = SCRIPT_DIR.parent
OUTPUT_DIR = SCRIPT_DIR / "saved_cheques"
FONT_DIR = SCRIPT_DIR / "font"

TEMPLATE_BY_TYPE = {
    "SBP": PROJECT_DIR / "example-sbp.html",
    "SPB": PROJECT_DIR / "example-sbp.html",
    "CARD": PROJECT_DIR / "example-card.html",
}

TMPL_DATE = "08.05.2026 10:09 ПО МСК"
TMPL_AMOUNT = "12 000 ₽"
TMPL_SBP_RECIPIENT = "РОДИОН ВИТАЛЬЕВИЧ К"
TMPL_SBP_PHONE = "+7 960 917-71-31"
TMPL_BANK = "ПАО СБЕРБАНК"
TMPL_SBP_ID = "A61280709064670X0G10010011760501"
TMPL_CARD_NUMBER = "2200 **** **** 2966"
TMPL_DOC_NUMBER = "M69938279093"


def _normalized_type() -> str:
    normalized = str(payment_type).strip().upper()
    if normalized == "SPB":
        return "SBP"
    return normalized


def _is_cheque_pdf_endpoint(flow: http.HTTPFlow) -> bool:
    if HOST_SUB not in (flow.request.host or ""):
        return False
    path = (flow.request.path or "").split("?")[0].rstrip("/")
    return path == CHEQUE_PDF_PATH.rstrip("/")


def _incoming_response_is_usable_pdf(flow: http.HTTPFlow) -> bool:
    """Банк иногда отдаёт 200 без тела или не PDF — клиент крутит загрузку бесконечно."""
    if flow.response is None:
        return False
    body = flow.response.content or b""
    if len(body) < 5 or not body.startswith(b"%PDF"):
        return False
    ct = (flow.response.headers.get("content-type") or "").lower()
    if ct and "pdf" not in ct and "octet-stream" not in ct:
        return False
    return True


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


def _transaction_id() -> str:
    source = "M69949783738" if _normalized_type() == "CARD" else "M69943705894"
    return _build_seeded_id(
        source_id=source,
        seed=history_new_payment_name,
        digits_count=11,
    )


def _sbp_operation_id() -> str:
    return _build_seeded_id(
        source_id="B6128112922901280G10180011760501",
        seed=history_new_payment_name,
        digits_count=31,
    )


def _format_amount(amount: object) -> str:
    try:
        value = float(str(amount).replace(",", "."))
    except (TypeError, ValueError):
        value = 0

    if value.is_integer():
        text = f"{int(value):,}".replace(",", " ")
    else:
        text = f"{value:,.2f}".replace(",", " ").replace(".", ",")
    return f"{text} ₽"


def _suffix_to_tzinfo(suffix: str) -> timezone:
    s = suffix.strip()
    if len(s) != 5 or s[0] not in "+-":
        return timezone.utc
    sign = 1 if s[0] == "+" else -1
    hh = int(s[1:3])
    mi = int(s[3:5])
    return timezone(sign * timedelta(hours=hh, minutes=mi))


def _format_cheque_datetime() -> str:
    """На чеке всегда московские часы; дата и время переводятся из зоны конфига в МСК."""
    date_raw = str(transaction_date).strip()
    time_raw = str(transaction_time).strip()
    if not date_raw or not time_raw:
        return f"{date_raw} {time_raw} ПО МСК".strip()
    tzinfo = _suffix_to_tzinfo(transaction_tz_suffix())
    parsed: datetime | None = None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            parsed = datetime.strptime(f"{date_raw} {time_raw}", fmt).replace(tzinfo=tzinfo)
            break
        except ValueError:
            continue
    if parsed is None:
        return f"{date_raw} {time_raw} ПО МСК".strip()
    try:
        msk = parsed.astimezone(ZoneInfo("Europe/Moscow"))
    except Exception:
        msk = parsed
    return f"{msk.day:02d}.{msk.month:02d}.{msk.year} {msk.hour:02d}:{msk.minute:02d} ПО МСК"


def _card_number() -> str:
    return str(card_number).strip() or TMPL_CARD_NUMBER


def _inject_font_overrides(html: str) -> str:
    import base64

    def _font_source(name: str) -> str:
        candidates = [
            FONT_DIR / name,
            PROJECT_DIR / "font" / name,
            PROJECT_DIR / "rocket-backup" / "font" / name,
            PROJECT_DIR / "rocket" / "font" / name,
        ]
        for path in candidates:
            if path.exists():
                return base64.b64encode(path.read_bytes()).decode()
        return ""

    font_b64 = _font_source("font.woff2")
    mono_b64 = _font_source("mono.woff2")
    if not font_b64 and not mono_b64:
        return html

    style = "<style>\n"
    if font_b64:
        style += (
            '@font-face{font-family:"MonoCustom";'
            f'src:url("data:font/woff2;base64,{font_b64}") format("woff2");}}\n'
        )
    if mono_b64:
        style += (
            '@font-face{font-family:"RocketFont-Amount";'
            f'src:url("data:font/woff2;base64,{mono_b64}") format("woff2");}}\n'
        )
    style += "</style>"
    return html.replace("</head>", style + "\n</head>", 1)


def _embed_svg_assets(html: str) -> str:
    import base64

    for name in ("logo.svg", "pin.svg"):
        path = PROJECT_DIR / name
        if not path.exists():
            print(f"   cheque: SVG не найден: {path}")
            continue
        data_uri = "data:image/svg+xml;base64," + base64.b64encode(path.read_bytes()).decode()
        html = html.replace(f'src="../mitm_scripts/{name}"', f'src="{data_uri}"')
        html = html.replace(f"src='../mitm_scripts/{name}'", f"src='{data_uri}'")
        html = html.replace(f'src="{name}"', f'src="{data_uri}"')
        html = html.replace(f"src='{name}'", f"src='{data_uri}'")
    return html


def _template_path() -> Path | None:
    return TEMPLATE_BY_TYPE.get(_normalized_type())


def build_cheque_html() -> str | None:
    template_path = _template_path()
    if template_path is None:
        print(f"   cheque: неизвестный type={payment_type!r}, нужен SBP/SPB или CARD")
        return None
    if not template_path.exists():
        print(f"   cheque: шаблон не найден: {template_path}")
        return None

    tx_type = _normalized_type()
    html = template_path.read_text(encoding="utf-8")
    bank_name = get_bank_meta(bank)["name"]

    replacements = {
        TMPL_DATE: _format_cheque_datetime(),
        TMPL_AMOUNT: _format_amount(history_new_payment_amount),
        TMPL_BANK: bank_name,
        TMPL_DOC_NUMBER: _transaction_id(),
    }
    if tx_type == "SBP":
        replacements.update(
            {
                TMPL_SBP_RECIPIENT: str(details_new_payment_name).strip().upper(),
                TMPL_SBP_PHONE: str(sbp_telephone).strip(),
                TMPL_SBP_ID: _sbp_operation_id(),
            }
        )
    elif tx_type == "CARD":
        replacements[TMPL_CARD_NUMBER] = _card_number()

    for old, new in replacements.items():
        if new:
            html = html.replace(old, str(new))

    html = _embed_svg_assets(html)
    return _inject_font_overrides(html)


def _resolve_gen_pdf_js() -> Path | None:
    candidates = [
        SCRIPT_DIR / "gen_pdf.js",
        PROJECT_DIR / "rocket" / "gen_pdf.js",
        PROJECT_DIR / "rocket-backup" / "gen_pdf.js",
    ]
    for path in candidates:
        if path.exists():
            return path
    return None


def _html_to_pdf(html_path: Path, pdf_path: Path, gen_pdf_js: Path | None = None) -> bool:
    gen_js = gen_pdf_js or _resolve_gen_pdf_js()
    if gen_js is None:
        print("   cheque: gen_pdf.js не найден")
        return False
    try:
        result = subprocess.run(
            ["node", str(gen_js), str(html_path), str(pdf_path)],
            capture_output=True,
            timeout=30,
            cwd=str(PROJECT_DIR),
        )
        if result.returncode != 0:
            err = result.stderr.decode(errors="replace")
            print(f"   gen_pdf.js failed (code {result.returncode}): {err[:300]}")
            return False
        if not pdf_path.exists():
            print("   gen_pdf.js: выходной файл не создан")
            return False
        return True
    except subprocess.TimeoutExpired:
        print("   gen_pdf.js: таймаут (>30 с)")
    except Exception as exc:
        print(f"   gen_pdf.js: ошибка запуска: {exc}")
    return False


def _clear_saved_cheques_dir() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for child in OUTPUT_DIR.iterdir():
        if child.is_dir():
            shutil.rmtree(child)
        else:
            child.unlink()


def _build_pdf_for_flow() -> bytes | None:
    _clear_saved_cheques_dir()

    base_name = "rocket-reciept"

    html = build_cheque_html()
    if html is None:
        return None

    html_path = OUTPUT_DIR / f"{base_name}.html"
    pdf_path = OUTPUT_DIR / f"{base_name}.pdf"
    html_path.write_text(html, encoding="utf-8")
    print(f"   html: {html_path.name}")

    if not _html_to_pdf(html_path, pdf_path):
        return None

    generated = pdf_path.read_bytes()
    print(f"   pdf:  {pdf_path.name} ({len(generated)} B)")
    return generated


def request(flow: http.HTTPFlow) -> None:
    if not _is_cheque_pdf_endpoint(flow):
        return
    if flow.request.method.upper() != "POST":
        return
    print(f"\n📄 cheque-pdf POST: {len(flow.request.content or b'')} B")


def response(flow: http.HTTPFlow) -> None:
    if not _is_cheque_pdf_endpoint(flow):
        return
    if flow.request.method.upper() != "POST":
        return

    status = flow.response.status_code if flow.response else None
    print(f"\n📄 cheque-pdf response: status={status}, type={_normalized_type()!r}")
    if status == 200 and _incoming_response_is_usable_pdf(flow):
        print("   cheque: исходный ответ 200 с валидным PDF, ничего не меняю")
        return
    if status == 200:
        print("   cheque: 200, но тело пустое/не PDF — генерирую свой PDF")

    generated = _build_pdf_for_flow()
    if generated is None:
        print("   cheque: PDF не сгенерирован, оставляю исходный ответ")
        return

    flow.response.status_code = 200
    flow.response.reason = "OK"
    flow.response.content = generated
    flow.response.headers.clear()
    flow.response.headers["content-type"] = "application/pdf"
    flow.response.headers["content-length"] = str(len(generated))
    flow.response.headers["cache-control"] = "no-store"
    print(f"   ✅ ответ подменён на 200 PDF ({_transaction_id()})")
