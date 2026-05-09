#!/usr/bin/env python3
"""
Простой веб-редактор rocket_last/config.py и перезапуск systemd-юнита mitm.

По умолчанию слушает только 127.0.0.1 — зайти с ноутбука: 
  ssh -L 8899:127.0.0.1:8899 root@СЕРВЕР
  открыть http://127.0.0.1:8899

Переменные окружения:
  CONFIG_WEB_TOKEN  — если задан, в форме нужен тот же токен (поле или ?token=)
  MITM_SYSTEMD_UNIT — имя юнита (по умолчанию mitm-rocket)
"""
from __future__ import annotations

import argparse
import ast
import html
import os
import shutil
import subprocess
import sys
import urllib.parse
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path


def _config_path() -> Path:
    return Path(__file__).resolve().parent / "config.py"


def _page(content: str, msg: str | None, token: str | None, error: bool) -> str:
    esc = html.escape(content)
    note = ""
    if msg:
        color = "#c00" if error else "#060"
        note = f'<p style="color:{color};font-weight:bold">{html.escape(msg)}</p>'
    token_field = ""
    if token is not None:
        token_field = '<p>Токен: <input name="token" type="password" autocomplete="off" style="width:20em"/></p>'
    return f"""<!DOCTYPE html>
<html lang="ru">
<head><meta charset="utf-8"/><title>config.py</title></head>
<body>
<h1>rocket_last / config.py</h1>
{note}
<form method="post" action="/save">
{token_field}
<textarea name="content" rows="28" cols="100" style="font-family:monospace">{esc}</textarea>
<p><button type="submit">Сохранить и перезапустить mitm</button></p>
</form>
<p><small>Перед записью делается копия config.py.bak. Проверяется синтаксис Python.</small></p>
</body>
</html>"""


class Handler(BaseHTTPRequestHandler):
    token: str | None = None
    unit: str = "mitm-rocket"

    def log_message(self, fmt: str, *args) -> None:
        sys.stderr.write("%s - - [%s] %s\n" % (self.address_string(), self.log_date_time_string(), fmt % args))

    def _check_token(self, form: dict[str, list[str]]) -> bool:
        if self.token is None:
            return True
        got = (form.get("token") or [""])[0]
        return got == self.token

    def do_GET(self) -> None:
        if self.path.rsplit("?", 1)[0] not in ("/", ""):
            self.send_error(404)
            return
        raw = _config_path().read_text(encoding="utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(
            _page(raw, None, self.token if self.token else None, False).encode("utf-8")
        )

    def do_POST(self) -> None:
        if self.path != "/save":
            self.send_error(404)
            return
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length).decode("utf-8")
        form = urllib.parse.parse_qs(body, keep_blank_values=True)
        if not self._check_token(form):
            self.send_response(403)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(
                _page(_config_path().read_text(encoding="utf-8"), "Неверный токен", self.token, True).encode(
                    "utf-8"
                )
            )
            return
        text = (form.get("content") or [""])[0].replace("\r\n", "\n")
        if not text.endswith("\n"):
            text += "\n"
        try:
            ast.parse(text)
        except SyntaxError as e:
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(
                _page(form.get("content", [""])[0], f"Синтаксис Python: {e}", self.token, True).encode("utf-8")
            )
            return
        cfg = _config_path()
        bak = cfg.with_suffix(".py.bak")
        try:
            shutil.copy2(cfg, bak)
        except OSError as e:
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(_page(text, f"Не удалось сделать .bak: {e}", self.token, True).encode("utf-8"))
            return
        try:
            cfg.write_text(text, encoding="utf-8")
        except OSError as e:
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(_page(text, f"Запись файла: {e}", self.token, True).encode("utf-8"))
            return
        r = subprocess.run(
            ["systemctl", "restart", self.unit],
            capture_output=True,
            text=True,
        )
        if r.returncode != 0:
            err = (r.stderr or r.stdout or "").strip() or f"exit {r.returncode}"
            msg = f"Файл сохранён, но systemctl restart {self.unit} не удался: {err}"
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(_page(text, msg, self.token, True).encode("utf-8"))
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(
            _page(text, f"Сохранено, {self.unit} перезапущен.", self.token, False).encode("utf-8")
        )


def main() -> None:
    p = argparse.ArgumentParser(description="Редактор config.py + restart mitm systemd unit")
    p.add_argument("--host", default=os.environ.get("CONFIG_WEB_HOST", "127.0.0.1"))
    p.add_argument("--port", type=int, default=int(os.environ.get("CONFIG_WEB_PORT", "8899")))
    args = p.parse_args()
    token = os.environ.get("CONFIG_WEB_TOKEN")
    if token == "":
        token = None
    unit = os.environ.get("MITM_SYSTEMD_UNIT", "mitm-rocket")
    Handler.token = token
    Handler.unit = unit
    addr = (args.host, args.port)
    httpd = HTTPServer(addr, Handler)
    print(f"config editor: http://{args.host}:{args.port}/  (unit={unit})", file=sys.stderr)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nexit", file=sys.stderr)


if __name__ == "__main__":
    main()
