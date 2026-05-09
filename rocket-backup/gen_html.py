"""
Утилита для тестовой генерации HTML из сохранённого PDF.
Запуск: python3 rocket/gen_html.py
"""

from pathlib import Path

PDF_PATH = Path(__file__).resolve().parent / "saved_cheques" / "cheque_20260508_154816_1778230094_642.pdf"


def _pdf_to_html(body: bytes) -> str | None:
    try:
        import fitz

        doc = fitz.open(stream=body, filetype="pdf")
        pages_html: list[str] = []

        for page_no, page in enumerate(doc, start=1):
            svg = page.get_svg_image(matrix=fitz.Identity, text_as_path=False)
            w = page.rect.width
            h = page.rect.height
            pages_html.append(
                f'<div class="page" id="page-{page_no}" '
                f'style="width:{w:.2f}pt;height:{h:.2f}pt;">'
                f"{svg}"
                f"</div>"
            )

        doc.close()

        return (
            "<!DOCTYPE html>\n"
            '<html lang="ru"><head><meta charset="utf-8"><title>Чек</title>'
            "<style>"
            "body{margin:0;padding:24px;background:#e0e0e0;"
            "display:flex;flex-direction:column;align-items:center;}"
            ".page{background:#fff;margin-bottom:24px;"
            "box-shadow:0 2px 12px rgba(0,0,0,.3);overflow:hidden;}"
            ".page svg{display:block;width:100%;height:auto;}"
            "</style></head><body>\n"
            + "\n".join(pages_html)
            + "\n</body></html>"
        )
    except Exception as e:
        print(f"ошибка конвертации: {e}")
        return None


if __name__ == "__main__":
    if not PDF_PATH.exists():
        print(f"PDF не найден: {PDF_PATH}")
        raise SystemExit(1)

    body = PDF_PATH.read_bytes()
    print(f"читаю: {PDF_PATH.name} ({len(body)} B)")

    html = _pdf_to_html(body)
    if html is None:
        raise SystemExit(1)

    out = PDF_PATH.with_suffix(".html")
    out.write_text(html, encoding="utf-8")
    print(f"сохранено: {out}")
