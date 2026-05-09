from __future__ import annotations

import hashlib
import shutil
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from mitmproxy import http

import app_logger
from bank_mapper import get_bank_meta
from runtime_config import get_active_profile, normalize_tz_suffix, normalize_type

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
SCOPE = "replace_cheque"


def _normalized_type() -> str:
    profile = get_active_profile()
    return normalize_type(profile["data"]["type"])


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
    profile = get_active_profile()
    pdata = profile["data"]
    source = "M69949783738" if _normalized_type() == "CARD" else "M69943705894"
    return _build_seeded_id(
        source_id=source,
        seed=pdata["history_new_payment_name"],
        digits_count=11,
    )


def _sbp_operation_id() -> str:
    profile = get_active_profile()
    pdata = profile["data"]
    return _build_seeded_id(
        source_id="B6128112922901280G10180011760501",
        seed=pdata["history_new_payment_name"],
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
    profile = get_active_profile()
    pdata = profile["data"]
    date_raw = str(pdata["transaction_date"]).strip()
    time_raw = str(pdata["transaction_time"]).strip()
    if not date_raw or not time_raw:
        return f"{date_raw} {time_raw} ПО МСК".strip()
    tzinfo = _suffix_to_tzinfo(normalize_tz_suffix(pdata["transaction_time_zone"]))
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
    profile = get_active_profile()
    return str(profile["data"]["card_number"]).strip() or TMPL_CARD_NUMBER


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
            app_logger.warning(SCOPE, "svg asset missing", asset=str(path))
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
    profile = get_active_profile()
    pdata = profile["data"]
    template_path = _template_path()
    if template_path is None:
        app_logger.warning(SCOPE, "unknown payment type", payment_type=pdata["type"])
        return None
    if not template_path.exists():
        app_logger.error(SCOPE, "template missing", template_path=str(template_path))
        return None

    tx_type = _normalized_type()
    html = template_path.read_text(encoding="utf-8")
    bank_name = get_bank_meta(pdata["bank"])["name"]

    replacements = {
        TMPL_DATE: _format_cheque_datetime(),
        TMPL_AMOUNT: _format_amount(pdata["history_new_payment_amount"]),
        TMPL_BANK: bank_name,
        TMPL_DOC_NUMBER: _transaction_id(),
    }
    if tx_type == "SBP":
        replacements.update(
            {
                TMPL_SBP_RECIPIENT: str(pdata["details_new_payment_name"]).strip().upper(),
                TMPL_SBP_PHONE: str(pdata["sbp_telephone"]).strip(),
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
        app_logger.error(SCOPE, "gen_pdf.js not found")
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
            app_logger.error(
                SCOPE,
                "gen_pdf.js failed",
                return_code=result.returncode,
                stderr=err[:300],
            )
            return False
        if not pdf_path.exists():
            app_logger.error(SCOPE, "gen_pdf.js did not create output file")
            return False
        return True
    except subprocess.TimeoutExpired:
        app_logger.error(SCOPE, "gen_pdf.js timeout", timeout_sec=30)
    except Exception as exc:
        app_logger.error(SCOPE, "gen_pdf.js launch error", error=str(exc))
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
    app_logger.info(SCOPE, "html built for cheque", html_file=html_path.name)

    if not _html_to_pdf(html_path, pdf_path):
        return None

    generated = pdf_path.read_bytes()
    app_logger.info(SCOPE, "pdf generated", pdf_file=pdf_path.name, size=len(generated))
    return generated


def request(flow: http.HTTPFlow) -> None:
    if not _is_cheque_pdf_endpoint(flow):
        return
    if flow.request.method.upper() != "POST":
        return
    app_logger.info(
        SCOPE,
        "cheque request captured",
        method=flow.request.method,
        path=flow.request.path,
        content_bytes=len(flow.request.content or b""),
    )


def response(flow: http.HTTPFlow) -> None:
    if not _is_cheque_pdf_endpoint(flow):
        return
    if flow.request.method.upper() != "POST":
        return

    status = flow.response.status_code if flow.response else None
    profile = get_active_profile()
    app_logger.info(
        SCOPE,
        "cheque response intercepted",
        status=status,
        payment_type=_normalized_type(),
        active_profile=profile["id"],
    )
    if status == 200 and _incoming_response_is_usable_pdf(flow):
        app_logger.info(SCOPE, "upstream pdf is valid, no replacement")
        return
    if status == 200:
        app_logger.warning(SCOPE, "upstream returned 200 but body is not usable pdf")

    generated = _build_pdf_for_flow()
    if generated is None:
        app_logger.warning(SCOPE, "failed to generate replacement pdf, passthrough enabled")
        return

    flow.response.status_code = 200
    flow.response.reason = "OK"
    flow.response.content = generated
    flow.response.headers.clear()
    flow.response.headers["content-type"] = "application/pdf"
    flow.response.headers["content-length"] = str(len(generated))
    flow.response.headers["cache-control"] = "no-store"
    app_logger.info(
        SCOPE,
        "response replaced with generated pdf",
        transaction_id=_transaction_id(),
        bytes=len(generated),
    )
