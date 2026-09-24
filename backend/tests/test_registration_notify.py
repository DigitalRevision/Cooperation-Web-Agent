"""Регистрация представителя компании и уведомления в Telegram и ВКонтакте."""
import pytest
from fastapi.testclient import TestClient

from app import main
from app import notify as nt
from app.validators import inn_ok, ogrn_ok, kpp_ok, okpo_ok

c = TestClient(main.app)
H = {"Authorization": "Bearer dev-user"}
A = {"Authorization": "Bearer dev-admin"}

METEOR = {"name": "АО «Завод «Метеор»", "legal_name": "АКЦИОНЕРНОЕ ОБЩЕСТВО \"ЗАВОД \"МЕТЕОР\"", "inn": "3435000717",
          "ogrn": "1023402012050", "kpp": "343501001", "okved_main": "26.11.2", "address": "404122, г. Волжский, ул. Горького, д. 1"}
ACCOUNT = {"fio": "Петров Сергей Николаевич", "position": "Начальник отдела сбыта", "email": "s.petrov@example.ru", "consent": True}


@pytest.fixture(autouse=True)
def clean_state():
    main.REGISTRATIONS.clear(); main.NOTIFY.clear(); nt.TELEGRAM_CHATS.clear(); nt.notifier.inbox.clear()
    sent = []
    fake = {ch: (lambda ch: lambda contact, text: sent.append((ch, contact, text)) or {"ok": True})(ch) for ch in nt.CHANNELS}
    old = nt.notifier.senders
    nt.notifier.senders = fake
    yield sent
    nt.notifier.senders = old


def test_checksums_on_real_requisites():
    assert inn_ok("3446003396") and ogrn_ok("1023404238384") and kpp_ok("344601001")   # Волгограднефтемаш
    assert okpo_ok("00217610") and not okpo_ok("00217611")
    assert not inn_ok("3446003397") and not ogrn_ok("1023404238385") and not kpp_ok("34460100")


def test_suggest_returns_requisites():
    r = c.get("/api/v1/suggest/companies", params={"q": "метеор"}).json()
    assert r and r[0]["id"] == "meteor" and r[0]["inn"] == "3435000717" and r[0]["kpp"] == "343501001"
    assert c.get("/api/v1/suggest/companies", params={"q": "3446003"}).json()[0]["id"] == "vnm"


def test_registration_requires_valid_requisites_and_manual_check():
    bad = {**METEOR, "inn": "3435000718"}
    assert c.post("/api/v1/registration", headers=H, json={"account": ACCOUNT, "company": bad, "data_checked": True}).status_code == 422
    assert c.post("/api/v1/registration", headers=H, json={"account": ACCOUNT, "company": METEOR, "data_checked": False}).status_code == 422
    assert c.post("/api/v1/registration", headers=H, json={"account": {**ACCOUNT, "consent": False}, "company": METEOR, "data_checked": True}).status_code == 422
    no_kpp = {**METEOR, "kpp": None}
    assert c.post("/api/v1/registration", headers=H, json={"account": ACCOUNT, "company": no_kpp, "data_checked": True}).status_code == 422
    r = c.post("/api/v1/registration", headers=H, json={"account": ACCOUNT, "company": METEOR, "base_company_id": "meteor", "data_checked": True})
    assert r.status_code == 201 and r.json()["status"] == "PENDING_MODERATION"
    assert c.get("/api/v1/registration", headers=H).json()["company"]["inn"] == "3435000717"


def test_notification_settings_normalize_and_validate():
    s = c.put("/api/v1/me/notifications", headers=H, json={"channels": {
        "telegram": {"enabled": True, "contact": "https://t.me/s_petrov_meteor"},
        "vk": {"enabled": True, "contact": "https://vk.com/id123456"}}}).json()
    assert s["channels"]["telegram"]["contact"] == "@s_petrov_meteor"
    assert s["channels"]["vk"]["contact"] == "id123456"
    assert c.put("/api/v1/me/notifications", headers=H, json={"channels": {"telegram": {"enabled": True, "contact": "no spaces allowed"}}}).status_code == 422


def test_moderation_notifies_only_enabled_channels(clean_state):
    sent = clean_state
    c.post("/api/v1/registration", headers=H, json={"account": ACCOUNT, "company": METEOR, "base_company_id": "meteor", "data_checked": True})
    c.put("/api/v1/me/notifications", headers=H, json={"channels": {
        "telegram": {"enabled": True, "contact": "123456789"}, "vk": {"enabled": False, "contact": "id1"}}})
    r = c.patch("/api/v1/admin/registrations/dev-user", headers=A, json={"status": "APPROVED"})
    assert r.status_code == 200 and r.json()["status"] == "APPROVED"
    assert [(ch, to) for ch, to, _ in sent] == [("telegram", "123456789")]
    assert "подтверждены" in sent[0][2]


def test_event_toggle_and_channel_off_stop_delivery(clean_state):
    sent = clean_state
    c.post("/api/v1/registration", headers=H, json={"account": ACCOUNT, "company": METEOR, "base_company_id": "meteor", "data_checked": True})
    c.put("/api/v1/me/notifications", headers=H, json={"channels": {"telegram": {"enabled": True, "contact": "123456789"}},
                                                      "events": {"moderation": {"telegram": False}}})
    c.patch("/api/v1/admin/registrations/dev-user", headers=A, json={"status": "APPROVED"})
    assert sent == []                                            # событие выключено
    c.put("/api/v1/me/notifications", headers=H, json={"channels": {"telegram": {"enabled": False, "contact": "123456789"}}})
    assert c.post("/api/v1/me/notifications/test", headers=H).json()["sent"] == []   # канал выключен


def test_new_request_notifies_matched_supplier(clean_state):
    sent = clean_state
    # представитель «Красного Октября» (dev-user) подписан на новые заявки в Telegram
    ko = {"name": "АО «Корпорация Красный Октябрь»", "legal_name": "АКЦИОНЕРНОЕ ОБЩЕСТВО \"КОРПОРАЦИЯ КРАСНЫЙ ОКТЯБРЬ\"",
          "inn": "3459080648", "ogrn": "1203400006072", "kpp": "345901001", "okved_main": "24.10.6", "address": "400007, г. Волгоград, пр-кт им. В.И. Ленина, д. 110"}
    c.post("/api/v1/registration", headers=H, json={"account": ACCOUNT, "company": ko, "base_company_id": "ko", "data_checked": True})
    c.put("/api/v1/me/notifications", headers=H, json={"channels": {"telegram": {"enabled": True, "contact": "@ko_sales"}},
                                                      "events": {"moderation": {"telegram": False}}})
    req = {"what": "Нужна трубная заготовка из стали 40Х", "quantity": 500, "unit": "т", "period": "мес", "region": "34"}
    # пока модератор не подтвердил права, заявки компании представителю не приходят
    c.post("/api/v1/requests", headers=A, json=req)
    assert sent == [] and c.get("/api/v1/me/inbox", headers=H).json()["items"] == []
    c.patch("/api/v1/admin/registrations/dev-user", headers=A, json={"status": "APPROVED"})
    # заявку создаёт другой пользователь
    c.post("/api/v1/requests", headers=A, json=req)
    assert len(sent) == 1 and sent[0][0] == "telegram" and sent[0][1] == "@ko_sales"
    assert "трубная заготовка" in sent[0][2]


def test_telegram_webhook_links_username_and_sender_needs_token(monkeypatch):
    start = {"message": {"text": "/start", "from": {"username": "Ko_Sales"}, "chat": {"id": 777}}}
    url = "/api/v1/notify/telegram/webhook"
    # без секрета вебхук закрыт: иначе любой привязал бы чужой @username к своему чату
    monkeypatch.delenv("PK_TG_WEBHOOK_SECRET", raising=False)
    assert c.post(url, json=start).status_code == 503
    monkeypatch.setenv("PK_TG_WEBHOOK_SECRET", "s3cret")
    assert c.post(url, json=start).status_code == 403
    assert c.post(url, json=start, headers={"X-Telegram-Bot-Api-Secret-Token": "wrong"}).status_code == 403
    assert nt.TELEGRAM_CHATS == {}
    r = c.post(url, json=start, headers={"X-Telegram-Bot-Api-Secret-Token": "s3cret"})
    assert r.json()["linked"] == "@Ko_Sales" and nt.TELEGRAM_CHATS["ko_sales"] == 777
    monkeypatch.delenv("PK_TG_BOT_TOKEN", raising=False)
    monkeypatch.delenv("PK_VK_GROUP_TOKEN", raising=False)
    assert nt.send_telegram("@ko_sales", "x")["skipped"] == "not_configured"
    assert nt.send_vk("id1", "x")["skipped"] == "not_configured"


def test_site_inbox_gets_every_notice_and_records_bot_copies(clean_state):
    c.post("/api/v1/registration", headers=H, json={"account": ACCOUNT, "company": METEOR, "base_company_id": "meteor", "data_checked": True})
    # каналы выключены: уведомление всё равно появляется на сайте, копий в мессенджеры нет
    c.patch("/api/v1/admin/registrations/dev-user", headers=A, json={"status": "REJECTED", "comment": "Нужна доверенность"})
    box = c.get("/api/v1/me/inbox", headers=H).json()
    assert box["unread"] == 1 and box["items"][0]["event"] == "moderation" and box["items"][0]["via"] == []
    assert "доверенность" in box["items"][0]["text"] and box["items"][0]["link"] == "#cabinet.company"
    # Telegram включён: на сайте новое уведомление, в via отмечена доставленная копия
    c.put("/api/v1/me/notifications", headers=H, json={"channels": {"telegram": {"enabled": True, "contact": "123456789"}}})
    c.patch("/api/v1/admin/registrations/dev-user", headers=A, json={"status": "APPROVED"})
    box = c.get("/api/v1/me/inbox", headers=H).json()
    assert box["unread"] == 2 and box["items"][0]["via"] == [{"channel": "telegram", "ok": True, "skipped": None}]
    # прочитать одно, затем все
    assert c.post("/api/v1/me/inbox/read", headers=H, json={"ids": [box["items"][0]["id"]]}).json()["marked"] == 1
    assert c.get("/api/v1/me/inbox?unread_only=true", headers=H).json()["unread"] == 1
    assert c.post("/api/v1/me/inbox/read", headers=H, json={}).json()["marked"] == 1
    # тестовое уведомление в ленту не попадает
    c.post("/api/v1/me/notifications/test", headers=H)
    assert len(c.get("/api/v1/me/inbox", headers=H).json()["items"]) == 2


VALID_REGISTRATION = {
    "account": {"fio": "Иванов Иван Иванович", "position": "Начальник отдела снабжения", "email": "ivanov@example.com",
                "phone": "+7 999 111-22-33", "consent": True},
    "company": {"name": "ООО ТестМаш", "legal_name": "Общество с ограниченной ответственностью \"ТестМаш\"",
                "inn": "3662159260", "ogrn": "1103668038231", "kpp": "362001001", "okpo": "69480539", "okved_main": "10.13.1",
                "reg_date": "2010-11-26", "address": "396420, Воронежская область, г. Павловск, ул. Гоголя, 40б",
                "postal_address": "396420, Воронежская область, г. Павловск, ул. Гоголя, 40б", "site": "https://example.com",
                "phone": "+7 499 123-45-67", "email": "info@example.com"},
    "data_checked": True,
}


def test_registration_endpoint_accepts_valid_payload():
    r = c.post("/api/v1/registration", json=VALID_REGISTRATION, headers=H)
    assert r.status_code == 201, r.text
    assert r.json()["status"] == "PENDING_MODERATION" and r.json()["account"]["fio"] == "Иванов Иван Иванович"


def test_notification_settings_are_stored_for_user():
    r = c.put("/api/v1/me/notifications", headers=H, json={
        "channels": {"telegram": {"enabled": True, "contact": "@testuser"}, "vk": {"enabled": False, "contact": ""}},
        "events": {"new_requests": {"telegram": True, "vk": False}, "moderation": {"telegram": True, "vk": False}}})
    assert r.status_code == 200, r.text
    assert r.json()["channels"]["telegram"]["contact"] == "@testuser"
    assert r.json()["events"]["new_requests"]["telegram"] is True and r.json()["events"]["new_requests"]["vk"] is False
