"""Данные сайта на сервере: сессии, коллекции с правами доступа, личный кабинет, цепочки, каталог для браузера, перенос из браузера."""
import gzip
import json

from fastapi.testclient import TestClient

from app import main
from app.auth import staff_id
from pkdb import connect

c = TestClient(main.app)
MOD = {"Authorization": "Bearer dev-admin"}


def session():
    r = c.post("/api/v1/session")
    assert r.status_code == 201
    return {"Authorization": "Bearer " + r.json()["token"]}, r.json()["user"]["id"]


def test_session_identifies_user_and_token_is_not_stored():
    h, uid = session()
    assert c.get("/api/v1/session", headers=h).json()["user"] == {"id": uid, "role": "user"}
    assert c.get("/api/v1/session", headers={"Authorization": "Bearer nope"}).status_code == 401
    with connect("accounts") as a:
        hashes = [r["token_hash"] for r in a.execute("SELECT token_hash FROM user_session")]
    assert len(hashes) == 1 and h["Authorization"].split()[1] not in hashes[0]


def test_offer_is_shared_and_only_author_or_moderator_can_change_it():
    alice, a_id = session()
    bob, _ = session()
    doc = {"title": "Прокат круглый 40Х", "kind_label": "Материалы", "company_name": "ООО Тест", "qty": "1 000,5", "unit": "т",
           "price": {"value": 125000, "currency": "₽", "unit": "т", "date": "2026-09-24", "negotiable": True}, "author": "подделка",
           "status": "NEW", "created_at": "2026-09-26T08:00:00.000Z", "custom": "сохранится"}
    r = c.put("/api/v1/store/offers/o-1", headers=alice, json=doc).json()
    assert r["author"] == a_id and r["qty"] == 1000.5 and r["price"]["value"] == 125000 and r["custom"] == "сохранится"
    assert r["created_at"] == "2026-09-26T08:00:00.000Z"
    # запись видна всем, в том числе без входа — модератор больше не зависит от браузера автора
    assert [x["id"] for x in c.get("/api/v1/store/offers").json()] == ["o-1"]
    assert c.put("/api/v1/store/offers/o-1", headers=bob, json={**doc, "title": "чужое"}).status_code == 403
    assert c.delete("/api/v1/store/offers/o-1", headers=bob).status_code == 403
    assert c.put("/api/v1/store/offers/o-1", headers=MOD, json={**doc, "status": "NEW"}).json()["author"] == a_id   # модератор не становится автором
    assert c.put("/api/v1/store/offers/o-2", json=doc).status_code == 401
    # отклонённое модератором видит только автор
    assert c.put("/api/v1/store/decisions/offers:o-1", headers=alice, json={"coll": "offers", "item_id": "o-1", "status": "REJECTED"}).status_code == 403
    assert c.put("/api/v1/store/decisions/offers:o-1", headers=MOD, json={"coll": "offers", "item_id": "o-1", "status": "REJECTED", "comment": "нет цены"}).status_code == 200
    assert c.get("/api/v1/store/offers", headers=bob).json() == [] and len(c.get("/api/v1/store/offers", headers=alice).json()) == 1
    assert c.delete("/api/v1/store/offers/o-1", headers=alice).status_code == 204


def test_request_and_response_by_different_users():
    buyer, b_id = session()
    seller, s_id = session()
    rq = {"what": "Трубная заготовка", "qty": "500", "unit": "т", "period": "мес", "region": "34", "city": "Волгоград", "budget": "",
          "deadline": "2026-12-01", "extra": "ГОСТ", "target_company": "", "status": "NEW"}
    r = c.put("/api/v1/store/requests/r-1", headers=buyer, json=rq).json()
    assert r["author"] == b_id and r["qty"] == 500 and r["deadline"] == "2026-12-01" and r["extra"] == "ГОСТ" and r["budget"] is None
    resp = c.put("/api/v1/store/responses/resp-1", headers=seller, json={"request_id": "r-1", "company": "ООО Прокат", "text": "Готовы", "price": "70 000"}).json()
    assert resp["author"] == s_id
    assert c.put("/api/v1/store/responses/resp-2", headers=seller, json={"request_id": "нет-такой", "text": "x"}).status_code == 404
    assert [x["id"] for x in c.get("/api/v1/store/responses").json()] == ["resp-1"]


def test_registration_is_private_and_contacts_live_in_accounts_db():
    user, uid = session()
    other, _ = session()
    reg = {"account": {"fio": "Петров С. Н.", "position": "Сбыт", "email": "p@example.ru", "phone": "+7 (8442) 11-22-33"},
           "company": {"name": "АО «Завод «Метеор»", "inn": "3435000717", "ogrn": "1023402012050", "kpp": "343501001"},
           "base_id": "meteor", "from_base": ["inn"], "status": "PENDING", "submitted_at": "2026-09-26T08:00:00.000Z", "edit": False}
    assert c.put(f"/api/v1/store/registrations/{uid}", headers=other, json=reg).status_code == 403
    r = c.put(f"/api/v1/store/registrations/{uid}", headers=user, json=reg).json()
    assert r["account"]["fio"] == "Петров С. Н." and r["company"]["inn"] == "3435000717" and r["base_id"] == "meteor"
    assert c.get("/api/v1/store/registrations", headers=other).json() == []                 # чужую регистрацию не видно
    assert [x["id"] for x in c.get("/api/v1/store/registrations", headers=MOD).json()] == [uid]   # модератор видит все
    # ФИО и телефон — только в базе пользователей, в базе модерации их нет
    with connect("moderation") as m:
        row = m.execute("SELECT * FROM registration WHERE user_id = %s", (uid,)).fetchone()
    assert "Петров" not in json.dumps(row, default=str, ensure_ascii=False)
    # решение пишет только модератор; пользователь видит своё решение
    dec = {"status": "APPROVED", "comment": "", "submitted_at": reg["submitted_at"], "company_name": "АО «Завод «Метеор»"}
    assert c.put(f"/api/v1/store/moderation/{uid}", headers=user, json=dec).status_code == 403
    assert c.put(f"/api/v1/store/moderation/{uid}", headers=MOD, json=dec).json()["moderator"] == staff_id("dev-admin")
    assert c.get("/api/v1/store/moderation", headers=user).json()[0]["submitted_at"] == reg["submitted_at"]
    assert c.get("/api/v1/store/moderation", headers=other).json() == []
    assert c.put(f"/api/v1/store/reps/{uid}", headers=user, json={"company_id": "meteor"}).status_code == 403
    assert c.put(f"/api/v1/store/reps/{uid}", headers=MOD, json={"company_id": "meteor", "company_name": "Метеор"}).status_code == 200
    assert c.get("/api/v1/store").json()["reps"][0]["company_id"] == "meteor"


def test_override_and_source_flag_apply_to_api_catalog():
    assert c.put("/api/v1/store/overrides/vzmk", headers=MOD, json={"company_id": "vzmk", "status": "BAD"}).status_code == 422
    assert c.put("/api/v1/store/overrides/vzmk", headers=MOD, json={"company_id": "vzmk", "status": "VERIFIED"}).status_code == 200
    assert "vzmk" in [x["id"] for x in c.get("/api/v1/companies?size=100").json()["items"]]
    prod = lambda: next(k for k in next(x for x in c.post("/api/v1/search", json={"text": "трубная заготовка"}).json()["results"]
                                         if x["company_id"] == "ko")["criteria"] if k["k"] == "PRODUCT_MATCH")["r"]
    assert prod() == "yes"
    c.put("/api/v1/store/sourceflags/ko-site", headers=MOD, json={"disabled": True})
    assert prod() == "no"   # продукция из отключённого источника в подборе не участвует (остаётся совпадение по ОКВЭД)


def test_profile_round_trip_and_server_notices_survive_save():
    h, uid = session()
    prof = {"favorites": ["c:ko", "p:ko-billet"], "compare": ["c:vnm"], "saved": [{"text": "насос", "at": "2026-09-26T08:00:00.000Z"}],
            "city": "Волжский", "companies": [{"company_id": "ko", "role": "Снабжение", "status": "Ожидает подтверждения модератором"}],
            "warehouses": [{"id": "w1", "name": "Склад №1", "type": "Склад", "city": "Волгоград", "capacity": "2000 м²"}],
            "account": {"fio": "Иванов И. И.", "position": "Снабжение", "email": "i@example.ru", "registered_at": "2026-09-26T08:00:00.000Z"},
            "company": {"name": "ООО Тест", "inn": "3435000717", "base_id": "ko", "from_base": ["inn"], "status": "На проверке у модератора",
                        "submitted_at": "2026-09-26T08:00:00.000Z"},
            "notify": {"channels": {"telegram": {"on": True, "contact": "@test_user"}, "vk": {"on": False, "contact": ""}},
                       "events": {"moderation": {"telegram": True, "vk": False}}},
            "inbox": [{"id": "n1", "ev": "moderation", "title": "Проверка", "text": "Отправлено", "link": "#cabinet", "at": "2026-09-01T08:00:00.000Z",
                       "read": False, "via": []}],
            "seen": {"req": ["r-1"], "resp": [], "risk": {}}, "signedOut": False, "theme": "светлая"}
    assert c.put("/api/v1/me/profile", headers=h, json=prof).status_code == 200
    got = c.get("/api/v1/me", headers=h).json()["profile"]
    assert got == prof
    # сервер добавил уведомление после того, как сайт прочитал профиль: сохранение старой копии его не стирает
    main.nt.notifier.dispatch("moderation", "Решение модератора", {uid: main.nt.default_settings()})
    c.put("/api/v1/me/profile", headers=h, json={**prof, "inbox": [{**prof["inbox"][0], "read": True}]})
    box = c.get("/api/v1/me", headers=h).json()["profile"]["inbox"]
    assert [x["text"] for x in box] == ["Решение модератора", "Отправлено"] and box[1]["read"] is True
    # настройки каналов из кабинета видны API уведомлений
    assert c.get("/api/v1/me/notifications", headers=h).json()["channels"]["telegram"] == {"enabled": True, "contact": "@test_user"}


def test_chains_belong_to_owner():
    h, _ = session()
    other, _ = session()
    ch = {"id": "chain-1", "title": "Насос", "buyer_city": "Волгоград", "kind": "chain", "created_at": "2026-09-26T08:00:00.000Z",
          "nodes": [{"id": "a", "step": "Прокат", "company_id": "ko", "product_id": "ko-round", "status": "SELECTED", "history": []},
                    {"id": "b", "step": "Насос", "req_text": "центробежный", "company_id": "livgm", "product_id": None, "status": "DECLINED",
                     "history": [{"company_id": "vnm", "to": "livgm", "at": "2026-09-26T09:00:00.000Z", "reason": "поставщик отказался"}]}],
          "edges": [{"from": "a", "to": "b", "type": "POTENTIAL_RELATION", "qty": "50", "unit": "т/мес"}]}
    saved = c.put("/api/v1/me/chains/chain-1", headers=h, json=ch).json()
    assert saved["nodes"][1]["history"][0]["reason"] == "поставщик отказался" and saved["edges"][0]["qty"] == "50"
    assert [x["id"] for x in c.get("/api/v1/me", headers=h).json()["chains"]] == ["chain-1"]
    assert c.get("/api/v1/me", headers=other).json()["chains"] == []
    assert c.put("/api/v1/me/chains/chain-1", headers=other, json=ch).status_code == 404
    assert c.delete("/api/v1/me/chains/chain-1", headers=h).status_code == 204 and c.get("/api/v1/me", headers=h).json()["chains"] == []


def test_bundle_is_light_compressed_and_cached():
    r = c.get("/api/v1/bundle", headers={"Accept-Encoding": "gzip"})
    assert r.status_code == 200 and r.headers["etag"]
    b = r.json()
    assert len(b["companies"]) == 28 and b["okved"] and b["cities"]["Волгоград"]
    ko = next(x for x in b["companies"] if x["id"] == "ko")
    assert ko["_light"] and "history" not in ko and all(set(s) <= {"id", "source_type", "fetch_status", "source_url"} for s in ko["sources"])
    assert c.get("/api/v1/bundle", headers={"If-None-Match": r.headers["etag"]}).status_code == 304
    # полная карточка — при открытии предприятия
    full = c.get("/api/v1/companies/ko").json()
    assert full["sources"][0]["source_title"] and "products" in full


def test_bundle_keeps_crawl_log_short():
    """После поиска сайтов в журнале обхода десятки тысяч адресов: в каталог для сайта — итоги и последние записи с ошибками."""
    from pkdb import ingest, tx
    items = [{"url": f"https://site{i}.ru/", "status": "OK" if i % 10 else "HTTP_404", "note": None, "fetched_at": "2026-09-26"} for i in range(1000)]
    with tx("ingest") as g:
        ingest.write_crawl_log(g, "2026-09-26", items)
    try:
        b = c.get("/api/v1/bundle").json()
        assert b["crawl_summary"]["total"] == 1000 and b["crawl_summary"]["failed"] == 100
        assert len(b["crawl_log"]) == 300 + 70                           # последние 300 и последние ошибки, которых среди них нет
        assert sum(x["status"] != "OK" for x in b["crawl_log"]) == 100
    finally:
        with tx("ingest") as g:
            g.execute("TRUNCATE crawl_log RESTART IDENTITY")


def test_import_from_browser_storage():
    h, uid = session()
    local = {"collections": {
        "offers": [{"id": "o-local", "title": "Моё предложение", "author": "local", "created_at": "2026-09-20T10:00:00.000Z"},
                   {"id": "o-alien", "title": "Чужое", "author": "кто-то"}],
        "requests": [{"id": "r-local", "what": "Нужен насос", "author": "local"}],
        "responses": [{"id": "resp-local", "request_id": "r-local", "text": "Есть", "author": "local"}],
        "registrations": [{"id": "local", "account": {"fio": "Сидоров"}, "company": {"name": "ООО Ромашка", "inn": "3435000717"}, "status": "PENDING"}],
        "reports": [{"id": "x-1", "kind": "override", "company_id": "ko", "status": "VERIFIED", "author": "local"}],
    }, "profile": {"city": "Камышин", "favorites": ["c:ko"]}, "chains": [{"id": "chain-l", "title": "Локальная", "nodes": [], "edges": []}]}
    r = c.post("/api/v1/me/import-local", headers=h, json=local).json()["imported"]
    assert r == {"offers": 1, "requests": 1, "responses": 1, "reports": 0, "registrations": 1, "product_edits": 0, "profile": 1, "chains": 1}
    assert c.get("/api/v1/store/registrations", headers=MOD).json()[0]["id"] == uid
    # повторный перенос ничего не дублирует
    again = c.post("/api/v1/me/import-local", headers=h, json=local).json()["imported"]
    assert sum(again.values()) == 0


def test_bundle_carries_registry_models_compactly():
    """Крупный завод с сотнями моделей в реестре Минпромторга: в облегчённом каталоге — все позиции компактно
    (номер, наименование, код), описание и характеристики — в полной карточке."""
    from datetime import date
    from sync import merge
    from sync.store import Store
    recs = [{"Registernumber": str(1000 + i), "Productname": f"Прокат модель {i}", "OKPD2": f"24.10.{i % 5 + 1}", "TNVED": "7208", "Nameofregulations": "ГОСТ",
             "Docdate": "2024-01-01", "Docvalidtill": "2027-01-01", "Docname": "Акт экспертизы ТПП", "Docdatebasis": "2023-12-01", "Score": None,
             "Percentage": None} for i in range(30)]
    st = Store()
    own = len(st.products["ko"])
    merge.apply_minprom(st, "ko", recs, "2026-09-25", date(2026, 9, 26))
    st.save()
    try:
        from app import bundle, repo
        repo.drop_cache(); bundle.reset()
        b = c.get("/api/v1/bundle").json()
        ko = next(x for x in b["companies"] if x["id"] == "ko")
        assert len(ko["products"]) == own and all(p["source_id"] != "ko-minprom" for p in ko["products"])
        assert len(ko["rp"]) == 30 and ko["rp"][0] == ["1000", "Прокат модель 0", "24.10.1"] and ko["rpd"] == "2026-09-25"
        assert b["rp_categories"]["24"] and "pt" not in ko
        assert "24.10.1" in b["okpd2"] and "24.10" in b["okpd2"]      # подробный код (без названия) и его группировка с названием
        full = c.get("/api/v1/companies/ko").json()
        assert len(full["products"]) == own + 30 and full["products"][-1]["params"]
        assert {p["id"] for p in full["products"]} >= {f"ko-rpp-{1000 + i}" for i in range(30)}
    finally:
        st = Store()
        merge.apply_minprom(st, "ko", None, "2026-09-25", date(2026, 9, 26))
        st.save()
