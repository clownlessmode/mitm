"""
Тест полного пайплайна: example.html → подстановка данных + шрифты → PDF.
Запуск: .venv/bin/python rocket/gen_cheque.py
"""

import sys
sys.path.insert(0, str(__import__('pathlib').Path(__file__).resolve().parent))

from replace_check import _build_cheque_html, _html_to_pdf, OUTPUT_DIR

if __name__ == "__main__":
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    print("строю HTML из шаблона...")
    html = _build_cheque_html()
    if html is None:
        raise SystemExit(1)

    html_path = OUTPUT_DIR / "cheque_test.html"
    html_path.write_text(html, encoding="utf-8")
    print(f"html: {html_path}")

    pdf_path = OUTPUT_DIR / "cheque_test.pdf"
    print("конвертирую HTML → PDF...")
    ok = _html_to_pdf(html_path, pdf_path)
    if not ok:
        print("ошибка конвертации")
        raise SystemExit(1)

    print(f"pdf:  {pdf_path} ({pdf_path.stat().st_size // 1024} KB)")
    print("готово")
