"""Кабинет сайта: новости, телефоны, график включения."""

from __future__ import annotations

import html
import os
import re
import secrets
import time
from datetime import date
from http.cookies import SimpleCookie
from pathlib import Path
from urllib.parse import parse_qs

import admin_auth
import content
import dbmap

UPLOADS = Path(os.environ.get("KIROVSVET_UPLOADS", Path(__file__).resolve().parent / "uploads"))
_FAILS: dict[str, list[float]] = {}
_CLOCK = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")
_DAY = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def handle_get(handler, path: str) -> None:
    if path in ("/admin", "/admin/"):
        _page(handler)
        return
    if path in ("/admin/login", "/admin/login/"):
        _login_page(handler, "")
        return
    handler._bytes(404, b"not found", "text/plain; charset=utf-8", cache="no-store")


def handle_post(handler, path: str) -> None:
    try:
        fields, files = _read_form(handler)
    except ValueError:
        handler._bytes(413, "Слишком большой запрос".encode(), "text/plain; charset=utf-8", cache="no-store")
        return
    if path in ("/admin/login", "/admin/login/"):
        _login(handler, fields)
        return
    session = _session(handler)
    if session is None or fields.get("csrf") != session["csrf"]:
        _redirect(handler, "/admin/login/")
        return
    if path in ("/admin/logout", "/admin/logout/"):
        _set_cookie(handler, "", clear=True)
        _redirect(handler, "/admin/login/")
        return
    try:
        connection = dbmap.connect()
    except Exception:
        _redirect(handler, "/admin/?e=db")
        return
    try:
        if path in ("/admin/phones", "/admin/phones/"):
            content.save_phones(connection, _phones(fields))
        elif path in ("/admin/schedule", "/admin/schedule/"):
            content.save_offsets(connection, _minutes(fields.get("after")), _minutes(fields.get("before")))
        elif path in ("/admin/schedule-day", "/admin/schedule-day/"):
            content.save_day(connection, _date(fields.get("day")), _clock(fields.get("on")), _clock(fields.get("off")))
        elif path in ("/admin/schedule-day/delete", "/admin/schedule-day/delete/"):
            content.delete_day(connection, _date(fields.get("day")))
        elif path in ("/admin/news", "/admin/news/"):
            image_name = _store_image(files.get("image"))
            if not (fields.get("title") or "").strip():
                raise ValueError("Нужен заголовок")
            fields["date"] = _date(fields.get("date")).isoformat()
            content.save_news(connection, fields, image_name)
        elif path in ("/admin/news/delete", "/admin/news/delete/"):
            content.delete_news(connection, fields.get("id") or "")
        else:
            handler._bytes(404, b"not found", "text/plain; charset=utf-8", cache="no-store")
            return
    except ValueError as exc:
        _redirect(handler, "/admin/?e=" + _code(str(exc)))
        return
    except Exception:
        _redirect(handler, "/admin/?e=save")
        return
    finally:
        connection.close()
    _redirect(handler, "/admin/?ok=1")


def news_page(article: dict, styles: str) -> bytes:
    paragraphs = "".join(f"<p>{html.escape(part)}</p>" for part in article["body"].split("\n") if part.strip())
    image = f'<img src="{html.escape(article["image"])}" alt="">' if article.get("image") else ""
    page = f"""<!doctype html>
<html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(article["title"])} — Кировсвет</title>
<meta name="description" content="{html.escape(article["lead"])}">
{styles}
<style>
  body {{ margin: 0; background: var(--bg, #f5f5f7); color: var(--text, #1d1d1f); font: 17px/1.5 Golos Text, sans-serif; }}
  .wrap {{ max-width: 760px; margin: 0 auto; padding: 28px 20px 64px; }}
  a {{ color: inherit; }}
  h1 {{ font-family: Montserrat, sans-serif; letter-spacing: -0.03em; line-height: 1.15; }}
  .lead {{ font-size: 1.15rem; }}
  img {{ width: 100%; border-radius: 18px; }}
</style></head><body>
<main class="wrap">
  <p><a href="/novosti/">Все новости</a></p>
  <time datetime="{html.escape(article["date"])}">{html.escape(_rus_date(article["date"]))}</time>
  <h1>{html.escape(article["title"])}</h1>
  <p class="lead">{html.escape(article["lead"])}</p>
  {image}
  {paragraphs}
</main></body></html>"""
    return page.encode("utf-8")


def _page(handler) -> None:
    session = _session(handler)
    if session is None:
        _redirect(handler, "/admin/login/")
        return
    try:
        connection = dbmap.connect()
        state = content.admin_state(connection)
        connection.close()
    except Exception:
        _html(handler, _layout(session, "<p class='err'>База ещё без таблиц кабинета. Запустите деплой Опоры и обновите страницу.</p>"))
        return
    query = parse_qs(handler.path.split("?", 1)[1] if "?" in handler.path else "")
    note = ""
    if query.get("ok"):
        note = "<p class='ok'>Сохранено. На сайте появится в течение нескольких секунд.</p>"
    if query.get("e"):
        note = "<p class='err'>Не сохранилось. Проверьте поля и попробуйте ещё раз.</p>"
    _html(handler, _layout(session, note + _phones_form(session, state) + _schedule_form(session, state) + _news_form(session, state)))


def _login(handler, fields: dict) -> None:
    ip = handler.headers.get("X-Real-IP") or handler.client_address[0]
    if _blocked(ip):
        _login_page(handler, "Слишком много попыток. Подождите десять минут.")
        return
    try:
        connection = dbmap.connect()
        user = admin_auth.authenticate(connection, fields.get("email", ""), fields.get("password", ""))
        connection.close()
    except Exception:
        _login_page(handler, "База сейчас недоступна.")
        return
    if user is None:
        _remember_fail(ip)
        _login_page(handler, "Неверный логин или у этой учётной записи нет входа в кабинет сайта.")
        return
    csrf = secrets.token_urlsafe(18)
    _set_cookie(handler, admin_auth.sign_session(user[0], user[1], csrf))
    _redirect(handler, "/admin/")


def _phones(fields: dict) -> dict:
    phones = {}
    for key in content.PHONE_KEYS:
        phone = (fields.get(f"{key}_phone") or "").strip()
        if not re.search(r"\d", phone):
            raise ValueError("phone")
        phones[key] = {
            "title": fields.get(f"{key}_title") or "",
            "note": fields.get(f"{key}_note") or "",
            "phone": phone,
            "hours": fields.get(f"{key}_hours") or "",
        }
    return phones


def _minutes(raw: str | None) -> int:
    try:
        value = int(raw or "")
    except ValueError as exc:
        raise ValueError("minutes") from exc
    if not 0 <= value <= 180:
        raise ValueError("minutes")
    return value


def _clock(raw: str | None) -> str:
    value = (raw or "").strip()
    if not _CLOCK.match(value):
        raise ValueError("time")
    return value


def _date(raw: str | None) -> date:
    value = (raw or "").strip()
    if not _DAY.match(value):
        raise ValueError("date")
    year, month, day = (int(part) for part in value.split("-"))
    return date(year, month, day)


def _store_image(upload) -> str | None:
    if not upload:
        return None
    _filename, data = upload
    if not data:
        return None
    if len(data) > 4_000_000:
        raise ValueError("image")
    ext = content.image_ext(data)
    if ext is None:
        raise ValueError("image")
    folder = UPLOADS / "news"
    folder.mkdir(parents=True, exist_ok=True)
    name = f"{secrets.token_hex(16)}.{ext}"
    (folder / name).write_bytes(data)
    return name


def _phones_form(session: dict, state: dict) -> str:
    labels = {
        "dispatcher": "Диспетчерская",
        "reception": "Приёмная",
        "tech": "Технический отдел",
        "edds": "ЕДДС",
    }
    rows = []
    for key in content.PHONE_KEYS:
        item = state["phones"].get(key) or {}
        rows.append(f"""
        <fieldset>
          <legend>{labels[key]}</legend>
          <label>Подпись <input name="{key}_title" value="{html.escape(item.get("title") or labels[key])}"></label>
          <label>Номер <input name="{key}_phone" required value="{html.escape(item.get("phone") or "")}"></label>
          <label>Пояснение <input name="{key}_note" value="{html.escape(item.get("note") or "")}"></label>
          <label>Часы <input name="{key}_hours" value="{html.escape(item.get("hours") or "")}"></label>
        </fieldset>""")
    return f"""<section id="phones"><h2>Телефоны</h2>
      <form method="post" action="/admin/phones/">{_csrf(session)}{''.join(rows)}
      <button type="submit">Сохранить телефоны</button></form></section>"""


def _schedule_form(session: dict, state: dict) -> str:
    schedule = state["schedule"]
    days = "".join(
        f"""<li><b>{html.escape(_rus_date(item["date"]))}</b> включение {html.escape(item["on"])}, отключение {html.escape(item["off"])}
        <form method="post" action="/admin/schedule-day/delete/">{_csrf(session)}
        <input type="hidden" name="day" value="{html.escape(item["date"])}"><button type="submit">Убрать</button></form></li>"""
        for item in schedule["days"]
    ) or "<li>Особых дней нет — весь график считается по закату.</li>"
    return f"""<section id="schedule"><h2>Расписание включения</h2>
      <form method="post" action="/admin/schedule/">{_csrf(session)}
        <label>Минут после заката <input name="after" type="number" min="0" max="180" required value="{schedule["on_after_sunset"]}"></label>
        <label>Минут до восхода <input name="before" type="number" min="0" max="180" required value="{schedule["off_before_sunrise"]}"></label>
        <button type="submit">Сохранить смещение</button>
      </form>
      <h3>Особый день</h3>
      <p>Если на дату заданы часы, они заменяют расчёт. Отключение — утро следующего дня.</p>
      <form method="post" action="/admin/schedule-day/">{_csrf(session)}
        <label>Дата <input name="day" type="date" required></label>
        <label>Включение <input name="on" type="time" required></label>
        <label>Отключение <input name="off" type="time" required></label>
        <button type="submit">Записать день</button>
      </form>
      <ul>{days}</ul></section>"""


def _news_form(session: dict, state: dict) -> str:
    items = []
    for item in state["news_all"]:
        mark = "на сайте" if item["published"] else "скрыта"
        items.append(f"""<li><b>{html.escape(item["title"])}</b> · {html.escape(_rus_date(item["date"]))} · {mark}
          <form method="post" action="/admin/news/delete/">{_csrf(session)}
          <input type="hidden" name="id" value="{html.escape(item["id"])}"><button type="submit">Удалить</button></form></li>""")
    return f"""<section id="news"><h2>Новости</h2>
      <form method="post" action="/admin/news/" enctype="multipart/form-data">{_csrf(session)}
        <label>Заголовок <input name="title" required maxlength="200"></label>
        <label>Дата <input name="date" type="date" required value="{date.today().isoformat()}"></label>
        <label>Коротко <input name="lead" maxlength="500"></label>
        <label>Текст <textarea name="body" rows="8"></textarea></label>
        <label>Фото, до 4 МБ <input name="image" type="file" accept="image/jpeg,image/png,image/webp"></label>
        <label class="check"><input name="published" type="checkbox" value="1" checked> Показать на сайте</label>
        <button type="submit">Опубликовать новость</button>
      </form>
      <ul>{''.join(items) or '<li>Новостей из кабинета пока нет.</li>'}</ul></section>"""


def _layout(session: dict, body: str) -> str:
    name = html.escape(session.get("name") or "")
    return f"""<!doctype html><html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><meta name="robots" content="noindex">
<title>Кабинет сайта — Кировсвет</title>
<style>
  body {{ margin: 0; background: #f5f5f7; color: #1d1d1f; font: 16px/1.45 sans-serif; }}
  main {{ max-width: 820px; margin: 0 auto; padding: 24px 16px 64px; }}
  h1 {{ font-size: 1.6rem; }}
  section {{ background: #fff; border-radius: 16px; padding: 18px; margin: 16px 0; }}
  label {{ display: grid; gap: 4px; margin: 8px 0; }}
  input, textarea {{ font: inherit; padding: 8px 10px; border: 1px solid #d0d0d5; border-radius: 8px; }}
  button {{ font: inherit; background: #14213d; color: #fff; border: 0; border-radius: 999px; padding: 8px 16px; cursor: pointer; }}
  fieldset {{ border: 1px solid #e5e5ea; border-radius: 12px; margin: 10px 0; }}
  .ok {{ background: #e7f6ee; padding: 10px 12px; border-radius: 10px; }}
  .err {{ background: #fdecee; padding: 10px 12px; border-radius: 10px; }}
  li form {{ display: inline; }}
  .top {{ display: flex; justify-content: space-between; gap: 12px; align-items: center; }}
</style></head><body><main>
<div class="top"><h1>Кабинет сайта</h1>
<form method="post" action="/admin/logout/">{_csrf(session)}<button type="submit">Выйти</button></form></div>
<p>{name}. <a href="/">Открыть сайт</a></p>
{body}
</main></body></html>"""


def _login_page(handler, error: str) -> None:
    message = f"<p class='err'>{html.escape(error)}</p>" if error else ""
    page = f"""<!doctype html><html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><meta name="robots" content="noindex">
<title>Вход — кабинет Кировсвета</title>
<style>
  body {{ margin: 0; min-height: 100vh; display: grid; place-items: center; background: #f5f5f7; font: 16px/1.45 sans-serif; }}
  form {{ width: min(420px, calc(100% - 32px)); background: #fff; border-radius: 16px; padding: 24px; display: grid; gap: 10px; }}
  input {{ font: inherit; padding: 10px; border: 1px solid #d0d0d5; border-radius: 8px; }}
  button {{ font: inherit; background: #14213d; color: #fff; border: 0; border-radius: 999px; padding: 10px 16px; }}
  .err {{ color: #9f1239; }}
</style></head><body>
<form method="post" action="/admin/login/">
  <h1>Кабинет Кировсвета</h1>
  <p>Тот же логин, что в Опоре. Войти могут администратор и директор.</p>
  {message}
  <label>Почта <input name="email" type="email" autocomplete="username" required></label>
  <label>Пароль <input name="password" type="password" autocomplete="current-password" required></label>
  <button type="submit">Войти</button>
</form></body></html>"""
    _html(handler, page)


def _csrf(session: dict) -> str:
    return f'<input type="hidden" name="csrf" value="{html.escape(session["csrf"])}">'


def _session(handler) -> dict | None:
    cookie = SimpleCookie(handler.headers.get("Cookie"))
    morsel = cookie.get("ks_admin")
    if morsel is None:
        return None
    return admin_auth.read_session(morsel.value)


def _set_cookie(handler, value: str, clear: bool = False) -> None:
    secure = handler.headers.get("X-Forwarded-Proto", "") == "https"
    bits = ["ks_admin=" + ("" if clear else value), "Path=/admin", "HttpOnly", "SameSite=Lax"]
    if clear:
        bits.append("Max-Age=0")
    if secure:
        bits.append("Secure")
    handler._pending_cookie = "; ".join(bits)


def _redirect(handler, location: str) -> None:
    handler.send_response(303)
    handler.send_header("Location", location)
    handler.send_header("Cache-Control", "no-store")
    if getattr(handler, "_pending_cookie", ""):
        handler.send_header("Set-Cookie", handler._pending_cookie)
    handler.end_headers()


def _html(handler, page: str) -> None:
    data = page.encode("utf-8")
    handler.send_response(200)
    handler.send_header("Content-Type", "text/html; charset=utf-8")
    handler.send_header("Content-Length", str(len(data)))
    handler.send_header("Cache-Control", "no-store")
    handler.send_header("X-Robots-Tag", "noindex")
    if getattr(handler, "_pending_cookie", ""):
        handler.send_header("Set-Cookie", handler._pending_cookie)
    handler.end_headers()
    handler.wfile.write(data)


def _read_form(handler):
    ctype = handler.headers.get("Content-Type", "")
    length = int(handler.headers.get("Content-Length") or "0")
    if length < 0 or length > 5_000_000:
        raise ValueError("size")
    body = handler.rfile.read(length)
    if "multipart/form-data" not in ctype:
        parsed = parse_qs(body.decode("utf-8", "replace"), keep_blank_values=True)
        return {key: values[-1] for key, values in parsed.items()}, {}
    marker = "boundary="
    if marker not in ctype:
        raise ValueError("boundary")
    boundary = ctype.split(marker, 1)[1].split(";", 1)[0].strip().strip('"').encode("utf-8")
    fields: dict[str, str] = {}
    files: dict[str, tuple[str, bytes]] = {}
    for part in body.split(b"--" + boundary)[1:]:
        if part.startswith(b"--"):
            continue
        head, _, data = part.partition(b"\r\n\r\n")
        if not head:
            continue
        data = data.removesuffix(b"\r\n")
        disposition = head.decode("utf-8", "replace")
        name = _piece(disposition, "name")
        if not name:
            continue
        filename = _piece(disposition, "filename")
        if filename:
            files[name] = (filename, data)
        else:
            fields[name] = data.decode("utf-8", "replace")
    return fields, files


def _piece(header: str, key: str) -> str:
    match = re.search(rf'{key}="([^"]*)"', header)
    return match.group(1) if match else ""


def _blocked(ip: str) -> bool:
    now = time.time()
    recent = [stamp for stamp in _FAILS.get(ip, []) if now - stamp < 600]
    _FAILS[ip] = recent
    return len(recent) >= 8


def _remember_fail(ip: str) -> None:
    _FAILS.setdefault(ip, []).append(time.time())


def _code(_text: str) -> str:
    return "fields"


def _rus_date(iso: str) -> str:
    try:
        year, month, day = (int(part) for part in iso.split("-"))
    except ValueError:
        return iso
    months = "января февраля марта апреля мая июня июля августа сентября октября ноября декабря".split()
    return f"{day} {months[month - 1]} {year}"
