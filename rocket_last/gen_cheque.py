"""Ручная генерация PDF-чека (тот же пайплайн, что replace_cheque.response).

Запуск из корня репозитория:
  python rocket_last/gen_cheque.py
"""

from __future__ import annotations

import sys
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

from replace_cheque import (  # noqa: E402
    OUTPUT_DIR,
    _html_to_pdf,
    _resolve_gen_pdf_js,
    build_cheque_html,
)

if __name__ == "__main__":
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    html = build_cheque_html()
    if not html:
        raise SystemExit(1)

    html_path = OUTPUT_DIR / "manual_cheque.html"
    pdf_path = OUTPUT_DIR / "manual_cheque.pdf"
    html_path.write_text(html, encoding="utf-8")

    gen_js = _resolve_gen_pdf_js()
    if not gen_js:
        print("gen_pdf.js не найден (rocket_last, rocket или rocket-backup)")
        raise SystemExit(1)

    if not _html_to_pdf(html_path, pdf_path, gen_js):
        raise SystemExit(1)

    print(f"html: {html_path}")
    print(f"pdf:  {pdf_path} ({pdf_path.stat().st_size} B)")
