#!/usr/bin/env python3
"""
Админка для профилей платежей rocket_last с перезапуском mitm-сервиса.

Фичи:
  - несколько профилей (создать/редактировать/удалить)
  - выбор активного профиля
  - запись снапшота активного профиля в config.py (для совместимости)
  - restart systemd-юнита после изменений
"""
from __future__ import annotations

import argparse
import ast
import html
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.parse
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import runtime_config

FIELDS = (
    ("id", "ID профиля (латиница/цифры/-/_)", "text", "profile-1"),
    ("title", "Название профиля", "text", "profile-1"),
    ("type", "Тип платежа (SBP/CARD)", "text", "SBP"),
    ("last_balance", "Баланс после платежа", "number", "5000"),
    ("history_new_payment_name", "Имя в истории", "text", "Денис Н."),
    ("history_new_payment_amount", "Сумма платежа", "number", "1000"),
    ("details_new_payment_name", "Имя в деталях", "text", "ДЕНИС Н."),
    ("transaction_date", "Дата (YYYY-MM-DD)", "text", "2026-05-09"),
    ("transaction_time", "Время (HH:MM:SS)", "text", "19:44:03"),
    ("transaction_time_zone", "Часовой пояс (+0700)", "text", "+0700"),
    ("sbp_telephone", "Телефон SBP", "text", "+7 900 000-00-00"),
    ("bank", "Банк (TBANK/SBERBANK/...)", "text", "TBANK"),
    ("card_number", "Маска карты", "text", "2200 **** **** 5206"),
)

STYLE = """
body { font-family: Inter, Arial, sans-serif; margin: 0; background: #f4f6f8; color: #1d2733; }
.wrap { display: grid; grid-template-columns: 280px 1fr; min-height: 100vh; }
.sidebar { background: #17212b; color: #e9eef4; padding: 20px 16px; }
.sidebar h2 { margin: 0 0 16px; font-size: 18px; }
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
textarea { border: 1px solid #d6dee6; border-radius: 8px; padding: 10px; font-size: 13px; font-family: ui-monospace, SFMono-Regular, Menlo, monospace; width: 100%; min-height: 180px; box-sizing: border-box; }
.top { display: flex; justify-content: space-between; align-items: center; margin-bottom: 14px; }
.note { margin: 0 0 16px; padding: 10px 12px; border-radius: 8px; }
.note.ok { background: #e7f8ee; color: #15653f; }
.note.err { background: #fdeced; color: #8b2130; }
.token { margin-top: 14px; }
.footer-actions { margin-top: 18px; display: flex; gap: 10px; align-items: center; }
.small { font-size: 12px; color: #5c6b79; margin-top: 8px; }
"""


def _config_path() -> Path:
    return Path(__file__).resolve().parent / "config.py"


def _safe_id(raw: str) -> str:
    value = raw.strip().lower()
    value = re.sub(r"[^a-z0-9_-]+", "-", value)
    value = re.sub(r"-{2,}", "-", value).strip("-")
    return value or "profile"


def _restart_service(unit: str) -> tuple[bool, str]:
    result = subprocess.run(["systemctl", "restart", unit], capture_output=True, text=True)
    if result.returncode == 0:
        return True, f"Сервис {unit} перезапущен."
    err = (result.stderr or result.stdout or "").strip() or f"exit {result.returncode}"
    return False, f"Профиль сохранён, но restart {unit} не удался: {err}"


def _sync_active_to_legacy_config(store: dict[str, object]) -> None:
    profiles = store["profiles"]
    active_id = store["active_profile_id"]
    active = next((p for p in profiles if p["id"] == active_id), profiles[0])
    data = runtime_config.sanitize_profile_data(active["data"])

    text = f"""# Central settings for rocket_last scripts.
# This file is auto-synced from profiles.json (active profile: {active["id"]}).
last_balance = {int(data["last_balance"])}
type = {data["type"]!r}

history_new_payment_name = {data["history_new_payment_name"]!r}
history_new_payment_amount = {int(data["history_new_payment_amount"])}
details_new_payment_name = {data["details_new_payment_name"]!r}

transaction_date = {data["transaction_date"]!r}
transaction_time = {data["transaction_time"]!r}
transaction_time_zone = {data["transaction_time_zone"]!r}

sbp_telephone = {data["sbp_telephone"]!r}
bank = {data["bank"]!r}
card_number = {data["card_number"]!r}


def transaction_tz_suffix() -> str:
    raw = str(transaction_time_zone).strip()
    if not raw:
        return "+0000"
    u = raw.upper()
    if u in ("Z", "UTC"):
        return "+0000"
    compact = raw.replace(":", "")
    if len(compact) == 5 and compact[0] in "+-" and compact[1:].isdigit():
        return compact
    return "+0000"
"""
    ast.parse(text)
    cfg = _config_path()
    shutil.copy2(cfg, cfg.with_suffix(".py.bak"))
    cfg.write_text(text, encoding="utf-8")


def _parse_form(handler: BaseHTTPRequestHandler) -> dict[str, list[str]]:
    length = int(handler.headers.get("Content-Length", "0"))
    body = handler.rfile.read(length).decode("utf-8")
    return urllib.parse.parse_qs(body, keep_blank_values=True)


def _first(form: dict[str, list[str]], key: str, default: str = "") -> str:
    return (form.get(key) or [default])[0]


def _render_page(store: dict[str, object], selected_id: str, message: str, is_error: bool, token_enabled: bool) -> str:
    profiles = store["profiles"]
    active_id = str(store["active_profile_id"])
    selected = next((p for p in profiles if p["id"] == selected_id), profiles[0])
    selected_data = runtime_config.sanitize_profile_data(selected["data"])

    def esc(v: object) -> str:
        return html.escape(str(v))

    note_class = "err" if is_error else "ok"
    note_html = f'<p class="note {note_class}">{esc(message)}</p>' if message else ""
    token_field = (
        '<div class="token field"><label>Токен</label><input type="password" name="token" autocomplete="off"/></div>'
        if token_enabled
        else ""
    )

    list_html_parts: list[str] = []
    for profile in profiles:
        pid = str(profile["id"])
        title = str(profile["title"])
        active_cls = " active" if pid == active_id else ""
        active_badge = " (active)" if pid == active_id else ""
        list_html_parts.append(
            f"""
            <div class="profile-item{active_cls}">
              <div><strong>{esc(title)}</strong>{esc(active_badge)}</div>
              <div class="small">{esc(pid)}</div>
              <div class="row">
                <form method="get" action="/">
                  <input type="hidden" name="id" value="{esc(pid)}"/>
                  <button class="btn btn-soft" type="submit">Редактировать</button>
                </form>
                <form method="post" action="/profile/activate">
                  <input type="hidden" name="id" value="{esc(pid)}"/>
                  <button class="btn btn-main" type="submit">Сделать активным</button>
                </form>
              </div>
            </div>
            """
        )

    fields_html: list[str] = []
    for key, label, input_type, placeholder in FIELDS:
        if key == "title":
            value = selected.get("title", "")
        elif key == "id":
            value = selected.get("id", "")
        else:
            value = selected_data.get(key)
        fields_html.append(
            f"""
            <div class="field">
              <label for="{key}">{esc(label)}</label>
              <input id="{key}" name="{key}" type="{input_type}" value="{esc(value)}" placeholder="{esc(placeholder)}"/>
            </div>
            """
        )

    payments_json = json.dumps(selected_data.get("payments", []), ensure_ascii=False, indent=2)

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
      <h2>Профили платежей</h2>
      {"".join(list_html_parts)}
      <form method="get" action="/">
        <input type="hidden" name="id" value="__new__"/>
        <button class="btn btn-main" type="submit">+ Новый профиль</button>
      </form>
    </aside>
    <main class="content">
      <div class="card">
        <div class="top">
          <h1 style="margin:0">Редактор профиля</h1>
          <div class="small">active: {esc(active_id)}</div>
        </div>
        {note_html}
        <form method="post" action="/profile/save">
          <input type="hidden" name="original_id" value="{esc(selected.get("id", ""))}"/>
          <div class="grid">
            {"".join(fields_html)}
          </div>
          <div class="field" style="margin-top:12px">
            <label for="payments_json">
              Список платежей JSON (будут добавляться в историю сразу все, по порядку сверху вниз)
            </label>
            <textarea id="payments_json" name="payments_json" placeholder='[{{"type":"SBP","history_new_payment_name":"Иван","history_new_payment_amount":1000}}]'>{esc(payments_json)}</textarea>
          </div>
          {token_field}
          <div class="footer-actions">
            <button class="btn btn-main" type="submit">Сохранить профиль + перезапуск mitm</button>
          </div>
        </form>
        <form method="post" action="/profile/delete" style="margin-top:12px">
          <input type="hidden" name="id" value="{esc(selected.get("id", ""))}"/>
          <button class="btn btn-danger" type="submit">Удалить профиль</button>
        </form>
        <p class="small">
          Хранение: <code>rocket_last/profiles.json</code>. После любого изменения активный профиль
          синхронизируется в <code>rocket_last/config.py</code> и сервис перезапускается.
        </p>
      </div>
    </main>
  </div>
</body>
</html>"""


class Handler(BaseHTTPRequestHandler):
    token: str | None = None
    unit: str = "mitm-rocket"

    def log_message(self, fmt: str, *args) -> None:
        sys.stderr.write("%s - - [%s] %s\n" % (self.address_string(), self.log_date_time_string(), fmt % args))

    def _token_valid(self, form: dict[str, list[str]]) -> bool:
        if self.token is None:
            return True
        return _first(form, "token") == self.token

    def _respond(self, selected_id: str, message: str = "", is_error: bool = False) -> None:
        store = runtime_config.ensure_store()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(
            _render_page(
                store=store,
                selected_id=selected_id if selected_id else str(store["active_profile_id"]),
                message=message,
                is_error=is_error,
                token_enabled=self.token is not None,
            ).encode("utf-8")
        )

    def _save_profile(self, form: dict[str, list[str]]) -> tuple[bool, str, str]:
        store = runtime_config.ensure_store()
        profiles = list(store["profiles"])
        original_id = _first(form, "original_id").strip()
        title = _first(form, "title").strip() or "Profile"
        new_id = _safe_id(_first(form, "id").strip() or title)
        active_id = str(store["active_profile_id"])

        data_raw = {
            "type": _first(form, "type"),
            "last_balance": _first(form, "last_balance"),
            "history_new_payment_name": _first(form, "history_new_payment_name"),
            "history_new_payment_amount": _first(form, "history_new_payment_amount"),
            "details_new_payment_name": _first(form, "details_new_payment_name"),
            "transaction_date": _first(form, "transaction_date"),
            "transaction_time": _first(form, "transaction_time"),
            "transaction_time_zone": _first(form, "transaction_time_zone"),
            "sbp_telephone": _first(form, "sbp_telephone"),
            "bank": _first(form, "bank"),
            "card_number": _first(form, "card_number"),
        }
        payments_json = _first(form, "payments_json").strip()
        if payments_json:
            try:
                parsed = json.loads(payments_json)
            except json.JSONDecodeError as exc:
                return False, f"payments_json: невалидный JSON ({exc})", original_id or "__new__"
            if not isinstance(parsed, list):
                return False, "payments_json: ожидается JSON-массив", original_id or "__new__"
            data_raw["payments"] = parsed
        else:
            data_raw["payments"] = []
        data = runtime_config.sanitize_profile_data(data_raw)

        if original_id and original_id != "__new__":
            target = next((p for p in profiles if p["id"] == original_id), None)
            if target is None:
                return False, "Профиль для обновления не найден.", original_id
            if new_id != original_id and any(p["id"] == new_id for p in profiles):
                return False, f"id {new_id!r} уже существует.", original_id
            target["id"] = new_id
            target["title"] = title
            target["data"] = data
            if active_id == original_id:
                active_id = new_id
        else:
            if any(p["id"] == new_id for p in profiles):
                return False, f"id {new_id!r} уже существует.", "__new__"
            profiles.append({"id": new_id, "title": title, "data": data})
            if len(profiles) == 1:
                active_id = new_id

        new_store = {"active_profile_id": active_id, "profiles": profiles}
        runtime_config.save_store(new_store)
        _sync_active_to_legacy_config(new_store)
        ok, msg = _restart_service(self.unit)
        return ok, f"Профиль сохранён. {msg}", new_id

    def _delete_profile(self, profile_id: str) -> tuple[bool, str, str]:
        store = runtime_config.ensure_store()
        profiles = list(store["profiles"])
        if len(profiles) <= 1:
            return False, "Нельзя удалить единственный профиль.", profile_id

        keep = [p for p in profiles if p["id"] != profile_id]
        if len(keep) == len(profiles):
            return False, "Профиль для удаления не найден.", profile_id

        active_id = str(store["active_profile_id"])
        if active_id == profile_id:
            active_id = keep[0]["id"]
        new_store = {"active_profile_id": active_id, "profiles": keep}
        runtime_config.save_store(new_store)
        _sync_active_to_legacy_config(new_store)
        ok, msg = _restart_service(self.unit)
        return ok, f"Профиль удалён. {msg}", active_id

    def _activate_profile(self, profile_id: str) -> tuple[bool, str]:
        store = runtime_config.ensure_store()
        profiles = store["profiles"]
        if not any(p["id"] == profile_id for p in profiles):
            return False, "Профиль для активации не найден."

        new_store = {"active_profile_id": profile_id, "profiles": profiles}
        runtime_config.save_store(new_store)
        _sync_active_to_legacy_config(new_store)
        ok, msg = _restart_service(self.unit)
        return ok, f"Активный профиль обновлён. {msg}"

    def do_GET(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path not in ("/", ""):
            self.send_error(404)
            return
        query = urllib.parse.parse_qs(parsed.query, keep_blank_values=True)
        selected_id = _first(query, "id").strip()
        if selected_id == "__new__":
            store = runtime_config.ensure_store()
            placeholder = {
                "id": "",
                "title": "Новый профиль",
                "data": runtime_config.sanitize_profile_data({}),
            }
            store = {"active_profile_id": store["active_profile_id"], "profiles": [placeholder, *store["profiles"]]}
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(_render_page(store, "__new__", "", False, self.token is not None).encode("utf-8"))
            return
        self._respond(selected_id=selected_id)

    def do_POST(self) -> None:
        if self.path not in ("/profile/save", "/profile/delete", "/profile/activate"):
            self.send_error(404)
            return
        form = _parse_form(self)
        if not self._token_valid(form):
            self._respond(selected_id="", message="Неверный токен.", is_error=True)
            return

        try:
            if self.path == "/profile/save":
                ok, msg, selected_id = self._save_profile(form)
                self._respond(selected_id=selected_id, message=msg, is_error=not ok)
                return

            if self.path == "/profile/delete":
                ok, msg, selected_id = self._delete_profile(_first(form, "id").strip())
                self._respond(selected_id=selected_id, message=msg, is_error=not ok)
                return

            ok, msg = self._activate_profile(_first(form, "id").strip())
            self._respond(selected_id=_first(form, "id").strip(), message=msg, is_error=not ok)
        except (OSError, ValueError, SyntaxError) as exc:
            self._respond(selected_id="", message=f"Ошибка: {exc}", is_error=True)


def main() -> None:
    p = argparse.ArgumentParser(description="rocket_last profiles admin + restart mitm unit")
    p.add_argument("--host", default=os.environ.get("CONFIG_WEB_HOST", "127.0.0.1"))
    p.add_argument("--port", type=int, default=int(os.environ.get("CONFIG_WEB_PORT", "8899")))
    args = p.parse_args()

    token = os.environ.get("CONFIG_WEB_TOKEN")
    if token == "":
        token = None
    unit = os.environ.get("MITM_SYSTEMD_UNIT", "mitm-rocket")

    Handler.token = token
    Handler.unit = unit
    runtime_config.ensure_store()

    addr = (args.host, args.port)
    httpd = HTTPServer(addr, Handler)
    print(f"config admin: http://{args.host}:{args.port}/  (unit={unit})", file=sys.stderr)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nexit", file=sys.stderr)


if __name__ == "__main__":
    main()
