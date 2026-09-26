"""Уведомления представителям компаний в Telegram и ВКонтакте.

Каналы включаются и выключаются пользователем по отдельности, для каждого события свой переключатель.
Токены берутся из окружения:
  PK_TG_BOT_TOKEN   — токен бота Telegram (получить у @BotFather);
  PK_VK_GROUP_TOKEN — ключ доступа сообщества ВКонтакте с правом «сообщения сообщества».
Без токена канал считается не настроенным: отправка пропускается и попадает в журнал, ошибки не возникает.

Особенности каналов:
  Telegram — бот может писать только тем, кто нажал /start. Числовой chat_id узнаём из вебхука
  (/api/v1/notify/telegram/webhook) и связываем с @username из настроек пользователя.
  ВКонтакте — сообщество может писать тем, кто разрешил сообщения от сообщества.

Настройки каналов, лента уведомлений на сайте и привязки Telegram хранятся в базе sm01_accounts.
"""
from __future__ import annotations
import os
import random
import re
import time
import uuid
from typing import Callable

import httpx
from psycopg.types.json import Jsonb

from pkdb import tx

CHANNELS = ("telegram", "vk")
EVENTS = ("new_requests", "responses", "messages", "risks", "moderation")
EVENT_TITLES = {
    "new_requests": "Новая заявка по профилю вашей компании",
    "responses": "Новый отклик",
    "messages": "Новое сообщение",
    "risks": "Новый риск у предприятия из избранного",
    "moderation": "Проверка компании модератором",
    "test": "Тестовое уведомление",
}
VK_API_VERSION = "5.199"



def link_telegram(username: str, chat_id: int) -> None:
    """@username (в нижнем регистре) → числовой chat_id; вызывается вебхуком Telegram после /start."""
    with tx("accounts") as c:
        c.execute("INSERT INTO telegram_link (username, chat_id) VALUES (%s, %s) ON CONFLICT (username) DO UPDATE SET chat_id = EXCLUDED.chat_id, "
                  "linked_at = now()", (username.lower(), chat_id))


def telegram_chat(username: str) -> int | None:
    with tx("accounts") as c:
        r = c.execute("SELECT chat_id FROM telegram_link WHERE username = %s", (username.lower(),)).fetchone()
    return r["chat_id"] if r else None


def normalize_contact(channel: str, value: str | None) -> str | None:
    """Приводит контакт к единому виду. Пустая строка — контакт не указан; ValueError — формат не распознан."""
    v = (value or "").strip()
    if not v:
        return ""
    if channel == "telegram":
        if re.fullmatch(r"-?\d{5,15}", v):
            return v
        name = re.sub(r"^https?://t\.me/", "", v).lstrip("@")
        if re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{4,31}", name):
            return "@" + name
        raise ValueError("Telegram: укажите @username или числовой ID чата")
    if channel == "vk":
        name = re.sub(r"^https?://(m\.)?vk\.(com|ru)/", "", v).lstrip("@")
        if re.fullmatch(r"id\d+|[A-Za-z0-9_.]{2,32}", name):
            return name
        raise ValueError("ВКонтакте: укажите ссылку на страницу, id123456 или короткое имя")
    raise ValueError("Неизвестный канал")


def default_settings() -> dict:
    return {"channels": {ch: {"enabled": False, "contact": ""} for ch in CHANNELS},
            "events": {ev: {ch: True for ch in CHANNELS} for ev in EVENTS}}


def settings_for(uids) -> dict[str, dict]:
    """Настройки уведомлений пользователей; у кого их нет — настройки по умолчанию (каналы выключены)."""
    uids = [u for u in dict.fromkeys(uids) if u]
    out = {u: default_settings() for u in uids}
    if not uids:
        return out
    with tx("accounts") as c:
        for r in c.execute("SELECT * FROM notify_channel WHERE user_id = ANY(%s)", (uids,)):
            out[r["user_id"]]["channels"][r["channel"]] = {"enabled": r["enabled"], "contact": r["contact"]}
        for r in c.execute("SELECT * FROM notify_event WHERE user_id = ANY(%s)", (uids,)):
            out[r["user_id"]]["events"].setdefault(r["event"], {})[r["channel"]] = r["enabled"]
    return out


def save_settings(uid: str, s: dict) -> None:
    with tx("accounts") as c:
        c.execute("INSERT INTO app_user (id, kind) VALUES (%s, 'legacy') ON CONFLICT DO NOTHING", (uid,))
        cur = c.cursor()
        cur.executemany("INSERT INTO notify_channel (user_id, channel, enabled, contact) VALUES (%s,%s,%s,%s) ON CONFLICT (user_id, channel) "
                        "DO UPDATE SET enabled = EXCLUDED.enabled, contact = EXCLUDED.contact",
                        [(uid, ch, bool(cfg.get("enabled")), cfg.get("contact") or "") for ch, cfg in s["channels"].items()])
        cur.executemany("INSERT INTO notify_event (user_id, event, channel, enabled) VALUES (%s,%s,%s,%s) ON CONFLICT (user_id, event, channel) "
                        "DO UPDATE SET enabled = EXCLUDED.enabled",
                        [(uid, ev, ch, bool(v)) for ev, per in s["events"].items() for ch, v in per.items()])


def send_telegram(contact: str, text: str, client: httpx.Client | None = None) -> dict:
    token = os.environ.get("PK_TG_BOT_TOKEN")
    if not token:
        return {"ok": False, "skipped": "not_configured"}
    chat_id = contact if re.fullmatch(r"-?\d+", contact) else telegram_chat(contact.lstrip("@"))
    if chat_id is None:
        return {"ok": False, "skipped": "waiting_start", "hint": "Пользователь ещё не отправил боту /start"}
    c = client or httpx.Client(timeout=10)
    r = c.post(f"https://api.telegram.org/bot{token}/sendMessage", json={"chat_id": chat_id, "text": text, "disable_web_page_preview": True})
    data = r.json()
    return {"ok": bool(data.get("ok")), "error": data.get("description")}


def send_vk(contact: str, text: str, client: httpx.Client | None = None) -> dict:
    token = os.environ.get("PK_VK_GROUP_TOKEN")
    if not token:
        return {"ok": False, "skipped": "not_configured"}
    params = {"access_token": token, "v": VK_API_VERSION, "random_id": random.getrandbits(31), "message": text}
    m = re.fullmatch(r"id(\d+)", contact)
    if m:
        params["user_id"] = m.group(1)
    else:
        params["domain"] = contact
    c = client or httpx.Client(timeout=10)
    data = c.post("https://api.vk.com/method/messages.send", data=params).json()
    err = data.get("error")
    return {"ok": err is None, "error": err.get("error_msg") if err else None}


class Notifier:
    """Рассылает событие получателям: запись в ленту на сайте и копии в мессенджеры по настройкам.

    Лента на сайте получает каждое уведомление, кроме тестового. В поле via записываются каналы,
    куда ушла копия, и результат отправки, чтобы в кабинете было видно, что дошло до Telegram и ВКонтакте.
    inbox=False — только копии в мессенджеры (ленту для событий сайта собирает сам сайт).
    """

    def __init__(self, senders: dict[str, Callable[[str, str], dict]] | None = None):
        self.senders = senders or {"telegram": send_telegram, "vk": send_vk}
        self.log: list[dict] = []

    def dispatch(self, event: str, text: str, recipients: dict[str, dict], link: str = "", inbox: bool = True) -> list[dict]:
        """recipients: user_id → настройки уведомлений. Возвращает записи журнала по этой рассылке."""
        out = []
        body = f"{EVENT_TITLES.get(event, event)}\n\n{text}"
        for uid, s in recipients.items():
            item = None
            if event != "test" and inbox:
                item = {"id": uuid.uuid4().hex, "event": event, "title": EVENT_TITLES.get(event, event), "text": text,
                        "link": link, "at": time.time(), "read": False, "via": []}
            for ch in CHANNELS:
                cfg = s["channels"].get(ch, {})
                if not cfg.get("enabled") or not cfg.get("contact"):
                    continue
                if event != "test" and not s["events"].get(event, {}).get(ch, False):
                    continue
                try:
                    res = self.senders[ch](cfg["contact"], body)
                except httpx.HTTPError as e:
                    res = {"ok": False, "error": str(e)}
                rec = {"user": uid, "channel": ch, "event": event, "at": time.time(), **res}
                self.log.append(rec)
                del self.log[:-1000]
                out.append(rec)
                if item is not None:
                    item["via"].append({"channel": ch, "ok": res.get("ok", False), "skipped": res.get("skipped")})
            if item is not None:
                add_inbox(uid, item)
        return out


def add_inbox(uid: str, item: dict) -> None:
    with tx("accounts") as c:
        c.execute("INSERT INTO app_user (id, kind) VALUES (%s, 'legacy') ON CONFLICT DO NOTHING", (uid,))
        c.execute("INSERT INTO inbox_notice (user_id, id, event, title, text, link, at, read, via) VALUES (%s,%s,%s,%s,%s,%s, to_timestamp(%s), %s, %s)",
                  (uid, item["id"], item["event"], item["title"], item["text"], item["link"], item["at"], item["read"], Jsonb(item["via"])))
        c.execute("DELETE FROM inbox_notice WHERE user_id = %s AND id IN (SELECT id FROM inbox_notice WHERE user_id = %s ORDER BY at DESC OFFSET 200)",
                  (uid, uid))


notifier = Notifier()
