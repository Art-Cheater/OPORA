"""Новости, телефоны и график включения, которые правит кабинет."""

from __future__ import annotations

import re
import uuid
from datetime import date, datetime, timezone

PHONE_KEYS = ("dispatcher", "reception", "tech", "edds")

_SLUG_MAP = str.maketrans({
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e",
    "ж": "zh", "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m",
    "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
    "ф": "f", "х": "h", "ц": "c", "ч": "ch", "ш": "sh", "щ": "sch", "ъ": "",
    "ы": "y", "ь": "", "э": "e", "ю": "yu", "я": "ya",
})


def tel_from_phone(phone: str) -> str:
    digits = re.sub(r"\D", "", phone or "")
    if len(digits) == 6:
        digits = "78332" + digits
    elif len(digits) == 11 and digits.startswith("8"):
        digits = "7" + digits[1:]
    elif len(digits) == 10:
        digits = "7" + digits
    return f"+{digits}" if digits else ""


def slugify(title: str) -> str:
    raw = (title or "").strip().lower().translate(_SLUG_MAP)
    slug = re.sub(r"[^a-z0-9]+", "-", raw).strip("-")
    return (slug or "novost")[:70]


def image_ext(data: bytes) -> str | None:
    if data.startswith(b"\xff\xd8\xff"):
        return "jpg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if len(data) >= 12 and data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        return "webp"
    return None


def _rows(connection, sql: str, params=()):
    with connection.cursor() as cursor:
        cursor.execute(sql, params)
        return cursor.fetchall()


def _one(connection, sql: str, params=()):
    with connection.cursor() as cursor:
        cursor.execute(sql, params)
        return cursor.fetchone()


def public_content(connection) -> dict:
    phones = {}
    for key, title, note, phone, hours in _rows(
        connection,
        """
        SELECT key, title, note, phone, hours
        FROM kirovsvet_contacts
        ORDER BY sort_order, key
        """,
    ):
        phones[key] = {
            "title": title,
            "note": note or "",
            "phone": phone,
            "tel": tel_from_phone(phone),
            "hours": hours or "",
        }
    schedule = _one(
        connection,
        "SELECT on_after_sunset, off_before_sunrise FROM kirovsvet_schedule WHERE id = 1",
    )
    days = [
        {"date": day.isoformat(), "on": on_time, "off": off_time}
        for day, on_time, off_time in _rows(
            connection,
            """
            SELECT day, on_time, off_time
            FROM kirovsvet_schedule_days
            ORDER BY day
            """,
        )
    ]
    news = []
    for slug, title, lead, published_on, image_name in _rows(
        connection,
        """
        SELECT slug, title, lead, published_on, image_name
        FROM kirovsvet_news
        WHERE deleted_at IS NULL AND is_published IS TRUE
        ORDER BY published_on DESC, created_at DESC
        LIMIT 50
        """,
    ):
        news.append({
            "slug": slug,
            "date": published_on.isoformat(),
            "title": title,
            "lead": lead,
            "image": f"/uploads/news/{image_name}" if image_name else None,
        })
    return {
        "phones": phones,
        "schedule": {
            "on_after_sunset": int(schedule[0]) if schedule else 15,
            "off_before_sunrise": int(schedule[1]) if schedule else 15,
            "days": days,
        },
        "news": news,
    }


def news_article(connection, slug: str):
    row = _one(
        connection,
        """
        SELECT slug, title, lead, body, published_on, image_name
        FROM kirovsvet_news
        WHERE slug = %s AND deleted_at IS NULL AND is_published IS TRUE
        """,
        (slug,),
    )
    if row is None:
        return None
    slug, title, lead, body, published_on, image_name = row
    return {
        "slug": slug,
        "title": title,
        "lead": lead,
        "body": body or "",
        "date": published_on.isoformat(),
        "image": f"/uploads/news/{image_name}" if image_name else None,
    }


def admin_state(connection) -> dict:
    state = public_content(connection)
    state["news_all"] = []
    for item_id, slug, title, lead, body, published_on, image_name, is_published in _rows(
        connection,
        """
        SELECT id, slug, title, lead, body, published_on, image_name, is_published
        FROM kirovsvet_news
        WHERE deleted_at IS NULL
        ORDER BY published_on DESC, created_at DESC
        """,
    ):
        state["news_all"].append({
            "id": str(item_id),
            "slug": slug,
            "title": title,
            "lead": lead,
            "body": body or "",
            "date": published_on.isoformat(),
            "image": f"/uploads/news/{image_name}" if image_name else None,
            "published": bool(is_published),
        })
    return state


def save_phones(connection, phones: dict[str, dict]) -> None:
    with connection.cursor() as cursor:
        for key in PHONE_KEYS:
            item = phones.get(key) or {}
            cursor.execute(
                """
                UPDATE kirovsvet_contacts
                SET title = %s, note = %s, phone = %s, hours = %s
                WHERE key = %s
                """,
                (
                    (item.get("title") or "")[:120],
                    (item.get("note") or "")[:300],
                    (item.get("phone") or "")[:40],
                    (item.get("hours") or "")[:120],
                    key,
                ),
            )
    connection.commit()


def save_offsets(connection, after_sunset: int, before_sunrise: int) -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            UPDATE kirovsvet_schedule
            SET on_after_sunset = %s, off_before_sunrise = %s
            WHERE id = 1
            """,
            (after_sunset, before_sunrise),
        )
    connection.commit()


def save_day(connection, day: date, on_time: str, off_time: str) -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO kirovsvet_schedule_days (day, on_time, off_time)
            VALUES (%s, %s, %s)
            ON CONFLICT (day) DO UPDATE SET on_time = EXCLUDED.on_time, off_time = EXCLUDED.off_time
            """,
            (day, on_time, off_time),
        )
    connection.commit()


def delete_day(connection, day: date) -> None:
    with connection.cursor() as cursor:
        cursor.execute("DELETE FROM kirovsvet_schedule_days WHERE day = %s", (day,))
    connection.commit()


def save_news(connection, fields: dict, image_name: str | None) -> str:
    item_id = (fields.get("id") or "").strip()
    title = (fields.get("title") or "").strip()[:200]
    lead = (fields.get("lead") or "").strip()[:500]
    body = (fields.get("body") or "").strip()[:20000]
    published_on = fields["date"]
    is_published = fields.get("published") == "1"
    now = datetime.now(timezone.utc)
    if item_id:
        found = _one(connection, "SELECT slug FROM kirovsvet_news WHERE id = %s AND deleted_at IS NULL", (item_id,))
        if found is None:
            raise ValueError("Новость не найдена")
        with connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE kirovsvet_news
                SET title = %s, lead = %s, body = %s, published_on = %s,
                    is_published = %s, updated_at = %s,
                    image_name = COALESCE(%s, image_name)
                WHERE id = %s AND deleted_at IS NULL
                """,
                (title, lead, body, published_on, is_published, now, image_name, item_id),
            )
        connection.commit()
        return found[0]
    slug = _unique_slug(connection, slugify(title))
    new_id = str(uuid.uuid4())
    with connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO kirovsvet_news
              (id, slug, title, lead, body, image_name, published_on, is_published, created_at, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (new_id, slug, title, lead, body, image_name, published_on, is_published, now, now),
        )
    connection.commit()
    return slug


def delete_news(connection, item_id: str) -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            "UPDATE kirovsvet_news SET deleted_at = %s WHERE id = %s AND deleted_at IS NULL",
            (datetime.now(timezone.utc), item_id),
        )
    connection.commit()


def _unique_slug(connection, base: str) -> str:
    slug = base
    n = 2
    while _one(connection, "SELECT 1 FROM kirovsvet_news WHERE slug = %s", (slug,)):
        slug = f"{base[:60]}-{n}"
        n += 1
    return slug
