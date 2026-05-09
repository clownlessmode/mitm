#!/usr/bin/env python3
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parent
GEN_PDF = ROOT / "gen_pdf.js"


def section(title: str) -> None:
    print("\n" + "=" * 80)
    print(title)
    print("=" * 80)


def run(cmd: list[str], *, cwd: Path | None = None, timeout: int = 60) -> tuple[int, str, str]:
    try:
        p = subprocess.run(
            cmd,
            cwd=str(cwd) if cwd else None,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return p.returncode, p.stdout, p.stderr
    except subprocess.TimeoutExpired as exc:
        out = exc.stdout or ""
        err = exc.stderr or ""
        return 124, str(out), str(err) + "\n[TIMEOUT]"
    except Exception as exc:  # pragma: no cover
        return 1, "", f"[EXCEPTION] {exc}"


def print_cmd_result(name: str, code: int, out: str, err: str) -> None:
    print(f"\n--- {name}")
    print(f"exit_code={code}")
    if out.strip():
        print("[stdout]")
        print(out.strip())
    if err.strip():
        print("[stderr]")
        print(err.strip())


def which(name: str) -> str:
    return shutil.which(name) or ""


def write_smoke_js(path: Path) -> None:
    path.write_text(
        """const fs = require('fs');
const path = require('path');
const chromiumPath = process.env.CHROMIUM_PATH || '';
async function main() {
  let pw;
  try {
    pw = require('playwright');
  } catch (e) {
    console.error('playwright require failed:', e.message);
    process.exit(2);
  }
  const { chromium } = pw;
  const launchOptions = {};
  if (chromiumPath) {
    launchOptions.executablePath = chromiumPath;
    launchOptions.args = ['--no-sandbox', '--disable-setuid-sandbox'];
  }
  const browser = await chromium.launch(launchOptions);
  const page = await browser.newPage();
  await page.setContent('<html><body><h1>pw smoke</h1></body></html>');
  const out = path.resolve(process.argv[2]);
  await page.pdf({ path: out, printBackground: true, width: '560px', height: '800px' });
  await browser.close();
  const stat = fs.statSync(out);
  console.log('OK pdf generated', out, 'size=', stat.size);
}
main().catch((e) => {
  console.error('smoke failed:', e && e.stack ? e.stack : e);
  process.exit(1);
});
""",
        encoding="utf-8",
    )


def write_html_sample(path: Path) -> None:
    path.write_text(
        """<!doctype html>
<html>
  <head><meta charset="utf-8"><title>pdf test</title></head>
  <body>
    <div class="pdf24_view">
      <div class="pdf24_02">
        <h1>rocket_last pdf test</h1>
        <p>If you see this in PDF, gen_pdf.js works.</p>
      </div>
    </div>
  </body>
</html>
""",
        encoding="utf-8",
    )


def main() -> int:
    section("ENV")
    print(f"python={sys.executable}")
    print(f"cwd={Path.cwd()}")
    print(f"script_root={ROOT}")
    print(f"GEN_PDF exists={GEN_PDF.exists()} path={GEN_PDF}")
    print(f"CHROMIUM_PATH={os.environ.get('CHROMIUM_PATH', '')!r}")

    section("BINARIES")
    for name in ("node", "npm", "npx", "chromium", "chromium-browser"):
        resolved = which(name)
        print(f"{name}: {resolved or 'NOT FOUND'}")
        if resolved:
            code, out, err = run([resolved, "--version"])
            print_cmd_result(f"{name} --version", code, out, err)

    section("PLAYWRIGHT REQUIRE CHECK")
    code, out, err = run(
        ["node", "-e", "try{require('playwright');console.log('playwright:ok')}catch(e){console.error(e.message);process.exit(2)}"],
        cwd=ROOT,
    )
    print_cmd_result("node require('playwright')", code, out, err)

    with tempfile.TemporaryDirectory(prefix="rocket_pdf_diag_") as td:
        tmp = Path(td)
        smoke_js = tmp / "pw_smoke.js"
        smoke_pdf = tmp / "pw_smoke.pdf"
        write_smoke_js(smoke_js)

        section("PLAYWRIGHT SMOKE PDF")
        code, out, err = run(["node", str(smoke_js), str(smoke_pdf)], cwd=ROOT, timeout=90)
        print_cmd_result("node pw_smoke.js", code, out, err)
        print(f"smoke_pdf_exists={smoke_pdf.exists()} size={smoke_pdf.stat().st_size if smoke_pdf.exists() else 0}")

        html = tmp / "sample.html"
        out_pdf = tmp / "sample_from_genpdf.pdf"
        write_html_sample(html)

        section("PROJECT gen_pdf.js TEST")
        code, out, err = run(["node", str(GEN_PDF), str(html), str(out_pdf)], cwd=ROOT, timeout=90)
        print_cmd_result("node gen_pdf.js sample.html", code, out, err)
        print(f"gen_pdf_exists={out_pdf.exists()} size={out_pdf.stat().st_size if out_pdf.exists() else 0}")

    section("DONE")
    print("Скопируй весь вывод этого скрипта и пришли его.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

