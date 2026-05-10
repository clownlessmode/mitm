#!/usr/bin/env python3
"""
Админка для платежных карточек rocket_last с перезапуском mitm-сервиса.

Сценарий:
  - одна карточка = один платеж
  - можно добавить/редактировать/удалить несколько карточек
  - все карточки добавляются в историю одновременно
"""
from __future__ import annotations

import argparse
import html
import hmac
import os
import secrets
import subprocess
import sys
import urllib.parse
from http.server import BaseHTTPRequestHandler, HTTPServer

import runtime_config

PAYMENT_FIELDS = (
    ("type", "Тип платежа (SBP/CARD)", "text", "SBP"),
    ("history_new_payment_name", "Имя в истории", "text", "Денис Н."),
    ("history_new_payment_amount", "Сумма платежа", "number", "1000"),
    ("direction", "Направление суммы", "select", ""),
    ("details_new_payment_name", "Имя в деталях", "text", "ДЕНИС Н."),
    ("transaction_date", "Дата (YYYY-MM-DD)", "text", "2026-05-09"),
    ("transaction_time", "Время (HH:MM:SS)", "text", "19:44:03"),
    ("transaction_time_zone", "Часовой пояс (+0700)", "text", "+0700"),
    ("sbp_telephone", "Телефон SBP", "text", "+7 900 000-00-00"),
    ("bank", "Банк (TBANK/SBERBANK/...)", "text", "TBANK"),
    ("card_number", "Маска карты", "text", "2200 **** **** 5206"),
)

DIRECTION_OPTIONS = (
    ("OUTGOING", "Списание (−)"),
    ("INCOMING", "Зачисление (+)"),
)

BANK_OPTIONS = [
    "TBANK",
    "SBERBANK",
    "VTB",
    "OZON",
    "UNKNOWN",
    "WB",
    "ALPHA",
    "SOVKOM",
    "DALNEVOSTOCHNIY",
    "RAIFAIZEN",
]

STYLE = """
body { font-family: Inter, Arial, sans-serif; margin: 0; background: #f4f6f8; color: #1d2733; }
.wrap { display: grid; grid-template-columns: 320px 1fr; min-height: 100vh; }
.sidebar { background: #17212b; color: #e9eef4; padding: 20px 16px; }
.sidebar h2 { margin: 0 0 12px; font-size: 18px; }
.profile-item { border: 1px solid #2e3b49; border-radius: 10px; padding: 10px; margin-bottom: 10px; background: #1f2a36; }
.profile-item.active { border-color: #3cb179; background: #1d3a2f; }
.profile-item .row { display: flex; gap: 6px; margin-top: 8px; }
.profile-item form { display: inline; }
.btn { border: 0; border-radius: 8px; padding: 8px 10px; cursor: pointer; font-weight: 600; font-size: 13px; }
.btn-main { background: #3cb179; color: white; }
.btn-soft { background: #364759; color: #d9e2ec; }
.btn-danger { background: #a53b44; color: white; }
.content { padding: 24px; }
.card { background: white; border-radius: 12px; padding: 20px; box-shadow: 0 6px 24px rgba(18, 38, 63, 0.08); }
.grid { display: grid; grid-template-columns: repeat(2, minmax(280px, 1fr)); gap: 12px 16px; }
.field { display: flex; flex-direction: column; gap: 6px; }
label { font-size: 13px; color: #4a5a6a; }
input { border: 1px solid #d6dee6; border-radius: 8px; padding: 10px; font-size: 14px; }
select { border: 1px solid #d6dee6; border-radius: 8px; padding: 10px; font-size: 14px; background: white; }
.top { display: flex; justify-content: space-between; align-items: center; margin-bottom: 14px; }
.note { margin: 0 0 16px; padding: 10px 12px; border-radius: 8px; }
.note.ok { background: #e7f8ee; color: #15653f; }
.note.err { background: #fdeced; color: #8b2130; }
.token { margin-top: 14px; }
.footer-actions { margin-top: 18px; display: flex; gap: 10px; align-items: center; }
.small { font-size: 12px; color: #5c6b79; margin-top: 8px; }
"""


def _restart_service(unit: str) -> tuple[bool, str]:
    result = subprocess.run(["systemctl", "restart", unit], capture_output=True, text=True)
    if result.returncode == 0:
        return True, f"Сервис {unit} перезапущен."
    err = (result.stderr or result.stdout or "").strip() or f"exit {result.returncode}"
    return False, f"Данные сохранены, но restart {unit} не удался: {err}"


def _parse_form(handler: BaseHTTPRequestHandler) -> dict[str, list[str]]:
    length = int(handler.headers.get("Content-Length", "0"))
    body = handler.rfile.read(length).decode("utf-8")
    return urllib.parse.parse_qs(body, keep_blank_values=True)


def _first(form: dict[str, list[str]], key: str, default: str = "") -> str:
    return (form.get(key) or [default])[0]


def _render_page(store: dict[str, object], edit_index: int, message: str, is_error: bool, token_enabled: bool) -> str:
    payments: list[dict[str, object]] = store["payments"]
    last_balance = int(store["last_balance"])
    if edit_index < 0 or edit_index >= len(payments):
        selected = runtime_config.sanitize_payment({}, fallback={})
        edit_index = -1
    else:
        selected = payments[edit_index]

    def esc(v: object) -> str:
        return html.escape(str(v))

    note_class = "err" if is_error else "ok"
    note_html = f'<p class="note {note_class}">{esc(message)}</p>' if message else ""
    list_html_parts: list[str] = []
    for idx, payment in enumerate(payments):
        active_cls = " active" if idx == edit_index else ""
        card_title = f"{idx + 1}. {payment['history_new_payment_name'] or 'Без имени'}"
        subtitle = f"{payment['type']} · {payment['history_new_payment_amount']} ₽ · {payment['bank']}"
        list_html_parts.append(
            f"""
            <div class="profile-item{active_cls}">
              <div><strong>{esc(card_title)}</strong></div>
              <div class="small">{esc(subtitle)}</div>
              <div class="row">
                <form method="get" action="/">
                  <input type="hidden" name="edit" value="{idx}"/>
                  <button class="btn btn-soft" type="submit">Редактировать</button>
                </form>
                <form method="post" action="/payment/delete">
                  <input type="hidden" name="index" value="{idx}"/>
                  <button class="btn btn-danger" type="submit">Удалить</button>
                </form>
              </div>
            </div>
            """
        )

    fields_html: list[str] = []
    for key, label, input_type, placeholder in PAYMENT_FIELDS:
        value = selected.get(key, "")
        if key == "bank":
            options = []
            current = str(value).strip().upper()
            known = set(BANK_OPTIONS)
            for bank_name in BANK_OPTIONS:
                sel = " selected" if bank_name == current else ""
                options.append(f'<option value="{esc(bank_name)}"{sel}>{esc(bank_name)}</option>')
            if current and current not in known:
                options.append(f'<option value="{esc(current)}" selected>{esc(current)}</option>')
            fields_html.append(
                f"""
                <div class="field">
                  <label for="{key}">{esc(label)}</label>
                  <select id="{key}" name="{key}">
                    {"".join(options)}
                  </select>
                </div>
                """
            )
        elif key == "direction":
            current = str(value).strip().upper()
            options = []
            for code, title in DIRECTION_OPTIONS:
                sel = " selected" if code == current else ""
                options.append(f'<option value="{esc(code)}"{sel}>{esc(title)}</option>')
            fields_html.append(
                f"""
                <div class="field">
                  <label for="{key}">{esc(label)}</label>
                  <select id="{key}" name="{key}">
                    {"".join(options)}
                  </select>
                </div>
                """
            )
        else:
            fields_html.append(
                f"""
                <div class="field">
                  <label for="{key}">{esc(label)}</label>
                  <input id="{key}" name="{key}" type="{input_type}" value="{esc(value)}" placeholder="{esc(placeholder)}"/>
                </div>
                """
            )

    return f"""<!DOCTYPE html>
<html lang="ru">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width,initial-scale=1"/>
  <title>rocket_last admin</title>
  <style>{STYLE}</style>
</head>
<body>
  <div class="wrap">
    <aside class="sidebar">
      <h2>Карточки платежей</h2>
      {"".join(list_html_parts)}
      <form method="get" action="/">
        <button class="btn btn-main" type="submit">+ Новый платеж</button>
      </form>
    </aside>
    <main class="content">
      <div class="card">
        <div class="top">
          <h1 style="margin:0">Платежи для истории</h1>
          <div class="small">всего карточек: {len(payments)}</div>
        </div>
        {note_html}
        <form method="post" action="/settings/save" style="margin-bottom:14px">
          <div class="field" style="max-width:320px">
            <label for="last_balance">Баланс после всех платежей</label>
            <input id="last_balance" name="last_balance" type="number" value="{last_balance}"/>
          </div>
          <div class="footer-actions">
            <button class="btn btn-main" type="submit">Сохранить баланс</button>
          </div>
        </form>
        <hr style="border:none;border-top:1px solid #e8edf2;margin:12px 0 16px"/>
        <form method="post" action="/payment/save">
          <input type="hidden" name="edit_index" value="{edit_index}"/>
          <div class="grid">
            {"".join(fields_html)}
          </div>
          <div class="footer-actions">
            <button class="btn btn-main" type="submit">Сохранить карточку + перезапуск mitm</button>
          </div>
        </form>
        {"<form method='post' action='/logout' style='margin-top:10px'><button class='btn btn-soft' type='submit'>Выйти</button></form>" if token_enabled else ""}
        <p class="small">
          Хранение: <code>rocket_last/payments.json</code>. После любого изменения данные
          синхронизируются в <code>rocket_last/config.py</code> и сервис перезапускается.
        </p>
      </div>
    </main>
  </div>
</body>
</html>"""


class Handler(BaseHTTPRequestHandler):
    token: str | None = None
    unit: str = "mitm-rocket"
    sessions: set[str] = set()

    def log_message(self, fmt: str, *args) -> None:
        sys.stderr.write("%s - - [%s] %s\n" % (self.address_string(), self.log_date_time_string(), fmt % args))

    def _token_required(self) -> bool:
        return bool(self.token)

    def _token_valid(self, provided: str) -> bool:
        if self.token is None:
            return True
        return hmac.compare_digest(provided, self.token)

    def _current_session(self) -> str:
        cookie = self.headers.get("Cookie", "")
        parts = [part.strip() for part in cookie.split(";")]
        for part in parts:
            if part.startswith("admin_session="):
                return part.split("=", 1)[1].strip()
        return ""

    def _is_authenticated(self) -> bool:
        if not self._token_required():
            return True
        sid = self._current_session()
        return bool(sid and sid in self.sessions)

    def _login_page(self, message: str = "") -> str:
        note = f'<p class="note err">{html.escape(message)}</p>' if message else ""
        return f"""<!DOCTYPE html>
<html lang="ru">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width,initial-scale=1"/>
  <title>rocket_last admin login</title>
  <style>{STYLE}</style>
</head>
<body>
  <main class="content" style="max-width:540px;margin:40px auto;">
    <div class="card">
      <h1 style="margin-top:0">Вход в админку</h1>
      {note}
      <form method="post" action="/login">
        <div class="field">
          <label for="token">Токен</label>
          <input id="token" name="token" type="password" autocomplete="off" autofocus/>
        </div>
        <div class="footer-actions">
          <button class="btn btn-main" type="submit">Войти</button>
        </div>
      </form>
    </div>
  </main>
</body>
</html>"""

    def _respond_login(self, message: str = "", status_code: int = 200) -> None:
        self.send_response(status_code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(self._login_page(message).encode("utf-8"))

    def _redirect(self, location: str) -> None:
        self.send_response(303)
        self.send_header("Location", location)
        self.end_headers()

    def _respond(self, edit_index: int = -1, message: str = "", is_error: bool = False) -> None:
        store = runtime_config.ensure_store()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(
            _render_page(
                store=store,
                edit_index=edit_index,
                message=message,
                is_error=is_error,
                token_enabled=self._token_required(),
            ).encode("utf-8")
        )

    def _save_settings(self, form: dict[str, list[str]]) -> tuple[bool, str]:
        store = runtime_config.ensure_store()
        store["last_balance"] = int(float(_first(form, "last_balance", "0") or "0"))
        runtime_config.save_store(store)
        runtime_config.write_legacy_config_from_store(store)
        ok, msg = _restart_service(self.unit)
        return ok, f"Баланс сохранён. {msg}"

    def _save_payment(self, form: dict[str, list[str]]) -> tuple[bool, str, int]:
        store = runtime_config.ensure_store()
        payments = list(store["payments"])
        edit_index_raw = _first(form, "edit_index", "-1").strip()
        try:
            edit_index = int(edit_index_raw)
        except ValueError:
            edit_index = -1
        raw_payment = {
            "type": _first(form, "type"),
            "history_new_payment_name": _first(form, "history_new_payment_name"),
            "history_new_payment_amount": _first(form, "history_new_payment_amount"),
            "direction": _first(form, "direction"),
            "details_new_payment_name": _first(form, "details_new_payment_name"),
            "transaction_date": _first(form, "transaction_date"),
            "transaction_time": _first(form, "transaction_time"),
            "transaction_time_zone": _first(form, "transaction_time_zone"),
            "sbp_telephone": _first(form, "sbp_telephone"),
            "bank": _first(form, "bank"),
            "card_number": _first(form, "card_number"),
        }
        payment = runtime_config.sanitize_payment(raw_payment)
        if 0 <= edit_index < len(payments):
            payments[edit_index] = payment
        else:
            payments.insert(0, payment)
            edit_index = 0
        store["payments"] = payments
        runtime_config.save_store(store)
        runtime_config.write_legacy_config_from_store(store)
        ok, msg = _restart_service(self.unit)
        return ok, f"Карточка сохранена. {msg}", edit_index

    def _delete_payment(self, index: int) -> tuple[bool, str]:
        store = runtime_config.ensure_store()
        payments = list(store["payments"])
        if index < 0 or index >= len(payments):
            return False, "Карточка для удаления не найдена."
        del payments[index]
        if not payments:
            payments = [runtime_config.sanitize_payment({})]
        store["payments"] = payments
        runtime_config.save_store(store)
        runtime_config.write_legacy_config_from_store(store)
        ok, msg = _restart_service(self.unit)
        return ok, f"Карточка удалена. {msg}"

    def do_GET(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path in ("/login", "/login/"):
            if self._is_authenticated():
                self._redirect("/")
                return
            self._respond_login()
            return

        if parsed.path not in ("/", ""):
            self.send_error(404)
            return

        if not self._is_authenticated():
            self._redirect("/login")
            return

        query = urllib.parse.parse_qs(parsed.query, keep_blank_values=True)
        edit = _first(query, "edit", "-1").strip()
        try:
            edit_index = int(edit)
        except ValueError:
            edit_index = -1
        self._respond(edit_index=edit_index)

    def do_POST(self) -> None:
        if self.path == "/login":
            if not self._token_required():
                self._redirect("/")
                return
            form = _parse_form(self)
            provided = _first(form, "token")
            if not self._token_valid(provided):
                self._respond_login("Неверный токен.", status_code=403)
                return
            sid = secrets.token_urlsafe(32)
            self.sessions.add(sid)
            self.send_response(303)
            self.send_header("Location", "/")
            self.send_header("Set-Cookie", f"admin_session={sid}; HttpOnly; SameSite=Lax; Max-Age=2592000; Path=/")
            self.end_headers()
            return

        if self.path == "/logout":
            sid = self._current_session()
            if sid and sid in self.sessions:
                self.sessions.remove(sid)
            self.send_response(303)
            self.send_header("Location", "/login")
            self.send_header("Set-Cookie", "admin_session=; HttpOnly; SameSite=Lax; Max-Age=0; Path=/")
            self.end_headers()
            return

        if self.path not in ("/settings/save", "/payment/save", "/payment/delete"):
            self.send_error(404)
            return

        if not self._is_authenticated():
            self._redirect("/login")
            return

        try:
            form = _parse_form(self)
            if self.path == "/settings/save":
                ok, msg = self._save_settings(form)
                self._respond(message=msg, is_error=not ok)
                return

            if self.path == "/payment/save":
                ok, msg, edit_index = self._save_payment(form)
                self._respond(edit_index=edit_index, message=msg, is_error=not ok)
                return

            index = int(_first(form, "index", "-1"))
            ok, msg = self._delete_payment(index)
            self._respond(message=msg, is_error=not ok)
        except (OSError, ValueError) as exc:
            self._respond(message=f"Ошибка: {exc}", is_error=True)


def main() -> None:
    p = argparse.ArgumentParser(description="rocket_last payments admin + restart mitm unit")
    p.add_argument("--host", default=os.environ.get("CONFIG_WEB_HOST", "127.0.0.1"))
    p.add_argument("--port", type=int, default=int(os.environ.get("CONFIG_WEB_PORT", "8899")))
    args = p.parse_args()

    token = os.environ.get("CONFIG_WEB_TOKEN")
    if token == "":
        token = None
    unit = os.environ.get("MITM_SYSTEMD_UNIT", "mitm-rocket")

    Handler.token = token
    Handler.unit = unit
    store = runtime_config.ensure_store()
    runtime_config.write_legacy_config_from_store(store)

    addr = (args.host, args.port)
    httpd = HTTPServer(addr, Handler)
    print(f"config admin: http://{args.host}:{args.port}/  (unit={unit})", file=sys.stderr)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nexit", file=sys.stderr)


if __name__ == "__main__":
    main()
