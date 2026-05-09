/**
 * HTML (PDF24-формат) → PDF через Playwright (headless Chromium).
 * Запуск: node rocket/gen_pdf.js
 */

const { chromium } = require('/tmp/playwright_test/node_modules/playwright');
const path = require('path');
const fs   = require('fs');

const HTML_PATH = process.argv[2] || path.resolve(__dirname, 'saved_cheques', 'example.html');
const OUT_PATH  = process.argv[3] || HTML_PATH.replace(/\.html$/, '_generated.pdf');

(async () => {
  if (!fs.existsSync(HTML_PATH)) {
    console.error('HTML не найден:', HTML_PATH);
    process.exit(1);
  }
  console.log('читаю:', path.basename(HTML_PATH));

  const browser = await chromium.launch();
  const context = await browser.newContext({
    viewport: { width: 600, height: 900 },
  });
  const page = await context.newPage();

  // Читаем файл и вставляем напрямую (headless-shell игнорирует file://)
  const html = fs.readFileSync(HTML_PATH, 'utf8');
  await page.setContent(html, { waitUntil: 'load' });

  // Ждём загрузки всех шрифтов (embedded base64)
  await page.evaluate(() => document.fonts.ready);

  // При media=print PDF24 рендерит в натуральном масштабе.
  // Берём реальные размеры .pdf24_02 через print-media.
  const dims = await page.evaluate(() => {
    // Создаём временный iframe или читаем стили в print через matchMedia
    const el = document.querySelector('.pdf24_02');
    if (!el) return null;

    // Убираем scale-трюк на время замера
    const view = document.querySelector('.pdf24_view');
    const origStyle = view ? view.style.cssText : '';
    if (view) { view.style.fontSize = '1em'; view.style.transform = 'scale(1)'; }

    const rect = el.getBoundingClientRect();
    if (view) view.style.cssText = origStyle;

    return { w: Math.ceil(rect.width), h: Math.ceil(rect.height) };
  });

  console.log('размер страницы (px):', dims);

  await page.pdf({
    path: OUT_PATH,
    printBackground: true,
    width:  dims ? (dims.w + 'px') : '560px',
    height: dims ? (dims.h + 'px') : '1488px',
    margin: { top: '0', right: '0', bottom: '0', left: '0' },
  });

  await browser.close();

  const size = fs.statSync(OUT_PATH).size;
  console.log('сохранено:', OUT_PATH, `(${(size / 1024).toFixed(1)} KB)`);
})();
