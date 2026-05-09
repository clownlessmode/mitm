"""
Тест полного пайплайна: example.html → подстановка данных + шрифты → PDF.
Запуск: .venv/bin/python rocket/gen_cheque.py
        .venv/bin/python rocket/gen_cheque.py --time "07.05.2026 09:00 ПО МСК"
"""

import argparse
import sys
sys.path.insert(0, str(__import__('pathlib').Path(__file__).resolve().parent))

from replace_check import DEFAULT_CHEQUE_TIME, _build_cheque_html, _html_to_pdf, OUTPUT_DIR

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Сборка чека из example.html → PDF")
    parser.add_argument(
        "--time",
        "-t",
        default=None,
        metavar="STR",
        help=(
            'Дата и время на чеке (как в шаблоне, можно без « &nbsp;» в конце). '
            f"По умолчанию: {DEFAULT_CHEQUE_TIME!r}"
        ),
    )
    args = parser.parse_args()

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    print("строю HTML из шаблона...")
    html = _build_cheque_html(cheque_time=args.time)
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
