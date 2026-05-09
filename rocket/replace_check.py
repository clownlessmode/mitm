"""
Чек PDF: POST /v1/reports/cheque-pdf

Если PDF содержит PDF_ID_MARK — подменяем ответ сгенерированным PDF:
  1. Берём example.html как шаблон
  2. Вставляем данные из replace_history / replace_details
  3. Конвертируем HTML → PDF через gen_pdf.js (Playwright)
  4. Отдаём клиенту сгенерированный PDF

В saved_cheques/ сохраняются: оригинал, заполненный HTML, сгенерированный PDF.
"""

from __future__ import annotations

import subprocess
from datetime import datetime
from pathlib import Path

from mitmproxy import http

from replace_details import DETAIL_PATCH
from replace_history import NEW_MAIN_AMOUNT, NEW_OPERATION_NAME, TARGET_TRANSACTION_ID

FONT_DIR = Path(__file__).resolve().parent / "font"

HOST_SUB = "dbo.rocketbank.ru"
CHEQUE_PDF_PATH = "/v1/reports/cheque-pdf"

OUTPUT_DIR      = Path(__file__).resolve().parent / "saved_cheques"
CHEQUE_TEMPLATE = Path(__file__).resolve().parent / "saved_cheques" / "example.html"
GEN_PDF_JS      = Path(__file__).resolve().parent / "gen_pdf.js"

# Должен совпадать с TARGET_TRANSACTION_ID из replace_history.py
PDF_ID_MARK = TARGET_TRANSACTION_ID

# ── Точные строки из example.html, которые будем заменять ───────────────────
TMPL_AMOUNT      = "12 000 ₽"
TMPL_RECIPIENT   = "РОДИОН ВИТАЛЬЕВИЧ К"
TMPL_RECIP_PHONE = "+7 960 917-71-31"
TMPL_RECIP_BANK  = "ПАО СБЕРБАНК"
TMPL_SBP_ID      = "A61280709064670X0G10010011760501"
TMPL_DOC_NUMBER  = "M69938279093"
# Строка в example.html (точное совпадение для replace)
TMPL_CHEQUE_TIME = "08.05.2026 10:09 ПО МСК &nbsp;"
# Значение по умолчанию при генерации (переопределяется аргументом --time в gen_cheque.py)
DEFAULT_CHEQUE_TIME = "08.05.2026 13:18 ПО МСК &nbsp;"


def _recipient_with_period(name: str) -> str:
    n = (name or "").strip()
    if not n:
        return ""
    return n if n.endswith(".") else f"{n}."


def _cheque_time_value(override: str | None) -> str:
    if override is None or not str(override).strip():
        return DEFAULT_CHEQUE_TIME
    t = str(override).strip()
    if "&nbsp;" not in t:
        t = t.rstrip() + " &nbsp;"
    return t


def _path_from_flow(flow: http.HTTPFlow) -> str:
    from urllib.parse import urlparse
    return urlparse(flow.request.pretty_url).path.rstrip("/")


def _is_cheque_pdf_endpoint(flow: http.HTTPFlow) -> bool:
    if HOST_SUB not in (flow.request.host or ""):
        return False
    return _path_from_flow(flow) == CHEQUE_PDF_PATH.rstrip("/")


def _slug_flow(flow: http.HTTPFlow) -> str:
    ts = getattr(flow.request, "timestamp_start", None)
    if ts is not None:
        return f"{ts:.3f}".replace(".", "_")[:40]
    return hex(id(flow))[-8:]


def _inject_font_overrides(html: str) -> str:
    """
    Встраивает font.woff2 (сумма) и mono.woff2 (весь остальной текст) как base64,
    переопределяет шрифты и убирает все тени.
    """
    import base64

    def _b64(name: str) -> str:
        p = FONT_DIR / name
        return base64.b64encode(p.read_bytes()).decode() if p.exists() else ""

    wide_b64 = _b64("font.woff2")
    mono_b64 = _b64("mono.woff2")

    face_wide = (
        f'@font-face{{font-family:"RocketSans-Wide";'
        f'src:url("data:font/woff2;base64,{wide_b64}") format("woff2");}}'
        if wide_b64 else ""
    )
    face_mono = (
        f'@font-face{{font-family:"RocketMono";'
        f'src:url("data:font/woff2;base64,{mono_b64}") format("woff2");}}'
        if mono_b64 else ""
    )

    override = (
        "<style>\n"
        + face_wide + "\n"
        + face_mono + "\n"
        # весь текст — wide (font.woff2)
        + '.pdf24_ span{font-family:"RocketSans-Wide" !important;}\n'
        # сумма — mono bold (mono.woff2)
        + 'span.pdf24_10{font-family:"RocketMono" !important;font-weight:bold !important;}\n'
        # никаких теней
        + "*{box-shadow:none !important;}\n"
        + "body>div{box-shadow:none !important;margin:0 !important;}\n"
        + "</style>"
    )

    return html.replace("</head>", override + "\n</head>", 1)


def _pdf_contains_mark(body: bytes) -> bool:
    """Ищет PDF_ID_MARK в текстовом слое PDF через PyMuPDF."""
    try:
        import fitz
        doc = fitz.open(stream=body, filetype="pdf")
        for page in doc:
            if page.search_for(PDF_ID_MARK):
                doc.close()
                return True
        doc.close()
    except Exception:
        pass
    return False


def _format_amount(amount) -> str:
    """15000 → '15 000 ₽'"""
    s = str(int(amount))
    groups = []
    while len(s) > 3:
        groups.append(s[-3:])
        s = s[:-3]
    groups.append(s)
    return " ".join(reversed(groups)) + " ₽"


def _get_field(key: str) -> str:
    for f in DETAIL_PATCH.get("operationFields", []):
        if f.get("key") == key:
            return str(f.get("value") or "")
    return ""


def _build_cheque_html(cheque_time: str | None = None) -> str | None:
    if not CHEQUE_TEMPLATE.exists():
        print(f"   cheque: шаблон не найден: {CHEQUE_TEMPLATE}")
        return None

    html = CHEQUE_TEMPLATE.read_text(encoding="utf-8")

    amount_raw = (DETAIL_PATCH.get("mainAmount") or {}).get("amount") or NEW_MAIN_AMOUNT or 0
    op_name    = (DETAIL_PATCH.get("operationName") or NEW_OPERATION_NAME or "").upper()
    recip      = _recipient_with_period(op_name)

    replacements = {
        TMPL_AMOUNT:      _format_amount(amount_raw),
        TMPL_RECIPIENT:   recip,
        TMPL_RECIP_PHONE: _get_field("phoneNumber"),
        TMPL_RECIP_BANK:  _get_field("bankName"),
        TMPL_SBP_ID:      _get_field("sbpOperationId"),
        TMPL_DOC_NUMBER:  TARGET_TRANSACTION_ID,
        TMPL_CHEQUE_TIME: _cheque_time_value(cheque_time),
    }

    for old, new in replacements.items():
        if new:
            html = html.replace(old, new)

    html = _inject_font_overrides(html)
    return html


def _html_to_pdf(html_path: Path, pdf_path: Path) -> bool:
    try:
        result = subprocess.run(
            ["node", str(GEN_PDF_JS), str(html_path), str(pdf_path)],
            capture_output=True,
            timeout=30,
            cwd=str(GEN_PDF_JS.parent.parent),
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
        return False
    except Exception as e:
        print(f"   gen_pdf.js: ошибка запуска: {e}")
        return False


def _clear_output_dir() -> None:
    if OUTPUT_DIR.exists():
        for f in OUTPUT_DIR.iterdir():
            if f.is_file() and f.name != "example.html":
                try:
                    f.unlink()
                except Exception:
                    pass


def request(flow: http.HTTPFlow) -> None:
    if not _is_cheque_pdf_endpoint(flow):
        return
    if flow.request.method.upper() != "POST":
        return
    raw = flow.request.content or b""
    print(f"\n📄 cheque-pdf POST: {len(raw)} B")


def response(flow: http.HTTPFlow) -> None:
    if not _is_cheque_pdf_endpoint(flow):
        return

    ct   = (flow.response.headers.get("content-type") or "").lower()
    body = flow.response.content
    if not body:
        return

    is_pdf = body[:5] == b"%PDF-" or "pdf" in ct
    if not is_pdf:
        print("\n📄 cheque-pdf: не похоже на PDF, пропускаем")
        return

    print(f"\n📄 cheque-pdf ответ: {len(body)} B")

    if not _pdf_contains_mark(body):
        print(f"   ℹ️  PDF_ID_MARK {PDF_ID_MARK!r} не найден — не наш чек")
        return

    print(f"   ✅ PDF_ID_MARK найден: {PDF_ID_MARK!r}")

    _clear_output_dir()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    stamp     = datetime.now().strftime("%Y%m%d_%H%M%S")
    slug      = _slug_flow(flow)
    base_name = f"cheque_{stamp}_{slug}"

    # 1. Сохраняем оригинал
    orig_path = OUTPUT_DIR / f"{base_name}_original.pdf"
    orig_path.write_bytes(body)
    print(f"   original: {orig_path.name}")

    # 2. Строим заполненный HTML
    html = _build_cheque_html()
    if html is None:
        print("   ошибка: не удалось построить HTML, отдаём оригинал")
        return

    html_path = OUTPUT_DIR / f"{base_name}.html"
    html_path.write_text(html, encoding="utf-8")
    print(f"   html:     {html_path.name}")

    # 3. Конвертируем HTML → PDF
    pdf_path = OUTPUT_DIR / f"{base_name}.pdf"
    ok = _html_to_pdf(html_path, pdf_path)
    if not ok:
        print("   ошибка: PDF не сгенерирован, отдаём оригинал")
        return

    generated = pdf_path.read_bytes()
    print(f"   pdf:      {pdf_path.name} ({len(generated)} B)")

    # 4. Подменяем ответ
    flow.response.content = generated
    flow.response.headers["content-type"]   = "application/pdf"
    flow.response.headers["content-length"] = str(len(generated))
    print("   ✅ ответ подменён на сгенерированный PDF")
