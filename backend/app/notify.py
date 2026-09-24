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
"""
from __future__ import annotations
import os
import random
import re
import time
from typing import Callable

import httpx

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

# @username (в нижнем регистре) → числовой chat_id; заполняется вебхуком Telegram после /start
TELEGRAM_CHATS: dict[str, int] = {}


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


def send_telegram(contact: str, text: str, client: httpx.Client | None = None) -> dict:
    token = os.environ.get("PK_TG_BOT_TOKEN")
    if not token:
        return {"ok": False, "skipped": "not_configured"}
    chat_id = contact if re.fullmatch(r"-?\d+", contact) else TELEGRAM_CHATS.get(contact.lstrip("@").lower())
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
    """Рассылает событие получателям с учётом их настроек и ведёт журнал доставки."""

    def __init__(self, senders: dict[str, Callable[[str, str], dict]] | None = None):
        self.senders = senders or {"telegram": send_telegram, "vk": send_vk}
        self.log: list[dict] = []

    def dispatch(self, event: str, text: str, recipients: dict[str, dict]) -> list[dict]:
        """recipients: user_id → настройки уведомлений. Возвращает записи журнала по этой рассылке."""
        out = []
        body = f"{EVENT_TITLES.get(event, event)}\n\n{text}"
        for uid, s in recipients.items():
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
                out.append(rec)
        return out


notifier = Notifier()
