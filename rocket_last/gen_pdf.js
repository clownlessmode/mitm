/**
 * HTML (PDF24-формат) → PDF через Playwright (headless Chromium).
 * Используется из rocket_last/replace_cheque.py; ищет playwright в нескольких местах.
 */

const path = require('path');
const fs = require('fs');

function loadPlaywright() {
  const candidates = [
    path.join(__dirname, 'node_modules', 'playwright'),
    path.join(__dirname, '..', 'node_modules', 'playwright'),
    path.join(__dirname, '..', 'rocket', 'node_modules', 'playwright'),
    '/tmp/playwright_test/node_modules/playwright',
  ];
  for (const dir of candidates) {
    try {
      return require(dir);
    } catch (_) {
      /* continue */
    }
  }
  try {
    return require('playwright');
  } catch (e) {
    console.error('Не найден пакет playwright. Пример: npm install playwright (в корне репозитория).');
    console.error(e.message);
    process.exit(1);
  }
}

const { chromium } = loadPlaywright();
const PDF_SCALE = Number.parseFloat(process.env.PDF_SCALE || '1.10');
const SAFE_PDF_SCALE = Number.isFinite(PDF_SCALE) && PDF_SCALE > 0 ? PDF_SCALE : 1.10;

function resolveChromiumExecutable() {
  const candidates = [
    process.env.CHROMIUM_PATH || '',
    '/usr/bin/chromium',
    '/usr/bin/chromium-browser',
    '/snap/bin/chromium',
  ].filter(Boolean);
  for (const p of candidates) {
    try {
      if (fs.existsSync(p)) return p;
    } catch (_) {
      /* continue */
    }
  }
  return '';
}

const HTML_PATH = process.argv[2] || path.resolve(__dirname, 'saved_cheques', 'example.html');
const OUT_PATH = process.argv[3] || HTML_PATH.replace(/\.html$/, '_generated.pdf');

(async () => {
  if (!fs.existsSync(HTML_PATH)) {
    console.error('HTML не найден:', HTML_PATH);
    process.exit(1);
  }
  console.log('читаю:', path.basename(HTML_PATH));

  let browser;
  try {
    const systemChromium = resolveChromiumExecutable();
    const launchOptions = {};
    if (systemChromium) {
      launchOptions.executablePath = systemChromium;
      // Для VPS/контейнеров root-сценарий обычно требует no-sandbox.
      launchOptions.args = ['--no-sandbox', '--disable-setuid-sandbox'];
      console.log('использую system chromium:', systemChromium);
    } else {
      console.log('использую bundled playwright chromium');
    }

    browser = await chromium.launch(launchOptions);
    const context = await browser.newContext({
      viewport: { width: 600, height: 900 },
    });
    const page = await context.newPage();

    const html = fs.readFileSync(HTML_PATH, 'utf8');
    await page.setContent(html, { waitUntil: 'load' });

    await page.evaluate(() => document.fonts.ready);

    const dims = await page.evaluate(() => {
      const el = document.querySelector('.pdf24_02');
      if (!el) return null;

      const view = document.querySelector('.pdf24_view');
      const origStyle = view ? view.style.cssText : '';
      if (view) {
        view.style.fontSize = '1em';
        view.style.transform = 'scale(1)';
      }

      const rect = el.getBoundingClientRect();
      if (view) view.style.cssText = origStyle;

      return { w: Math.ceil(rect.width), h: Math.ceil(rect.height) };
    });

    console.log('размер страницы (px):', dims);

    await page.pdf({
      path: OUT_PATH,
      printBackground: true,
      width: dims ? Math.ceil(dims.w * SAFE_PDF_SCALE) + 'px' : '560px',
      height: dims ? Math.ceil(dims.h * SAFE_PDF_SCALE) + 'px' : '1488px',
      scale: SAFE_PDF_SCALE,
      margin: { top: '0', right: '0', bottom: '0', left: '0' },
    });

    const size = fs.statSync(OUT_PATH).size;
    console.log('сохранено:', OUT_PATH, `(${(size / 1024).toFixed(1)} KB)`);
  } catch (e) {
    console.error(e);
    process.exitCode = 1;
  } finally {
    if (browser) {
      await browser.close().catch(() => {});
    }
  }
  if (process.exitCode) {
    process.exit(process.exitCode);
  }
})();
