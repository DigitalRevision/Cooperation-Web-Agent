"""Синхронизация с реестрами: разбор ответов источников, статусы, риски, слияние с базой, полный проход без сети.

Фикстуры — урезанные реальные ответы pb.nalog.ru («Ортех», ФИО физлиц заменены) и bo.nalog.gov.ru (ООО «Март»).
Запуск из корня репозитория: python -m pytest sync/tests -q
"""
import io
import json
import zipfile
from datetime import date
from pathlib import Path


from sync import merge, risks, run
from sync.providers import fedresurs, girbo, opendata, pb
from sync.providers.util import address_numbers, nice_address, nice_city, nice_name, same_address
from sync.store import Store
from pkdb import connect, testing
from pkdb import catalog as cat
from pkdb import ingest

FX = Path(__file__).parent / "fixtures"
TODAY = date(2026, 9, 24)
TEST_NEW_INN = "3435109665"   # ООО «Март»: компания, которую тесты добавляют как новую


def fx(name):
    return json.loads((FX / name).read_text(encoding="utf-8"))


def result(inn, **src):
    """Ответ проверки компании в формате run.check: ok — источники, которые ответили."""
    return {"inn": inn, "girbo_row": None, "ok": list(src), "not_found": [], "errors": {}, **src}


FED_BANKRUPT = {"guid": "b5c8", "url": "https://fedresurs.ru/companies/b5c8", "status_text": "Юридическое лицо признано несостоятельным (банкротом)",
                "is_active": True, "bankrupt": True, "cases": [], "active_case": {"number": "А12-5342/2025", "stage_code": "Tender", "stage": "Конкурсное производство"},
                "intents_recent": []}


# ---------- разбор ответов ----------

def test_names_and_addresses_from_registry_format():
    assert nice_name('ООО "НПО "ОРТЕХ-ЖКХ-ИНЖИНЕРИНГ"') == ("ООО «НПО «Ортех-ЖКХ-Инжинеринг»»", "НПО «Ортех-ЖКХ-Инжинеринг»")
    assert nice_name('АО "ВМЗ"') == ("АО «ВМЗ»", "ВМЗ") and nice_name('АО "НЗНП"')[0] == "АО «НЗНП»" and nice_name('ООО "МАРТ"')[0] == "ООО «Март»"
    assert nice_city("РОСТОВ-НА-ДОНУ") == "Ростов-на-Дону" and nice_city("БЫКОВ ОТРОГ") == "Быков Отрог"
    assert risks.rub(454_000) == "454 тыс. ₽" and risks.rub(2_345_678) == "2,3 млн ₽"
    assert nice_address("404122, ВОЛГОГРАДСКАЯ ОБЛАСТЬ, Г. ВОЛЖСКИЙ, УЛ. ГОРЬКОГО, Д. 1") == "404122, Волгоградская область, г. Волжский, ул. Горького, д. 1"
    # один адрес в разной записи: изменением не считается
    assert address_numbers("404122, г. Волжский, ул. Горького, д. 1") == address_numbers("404122, ВОЛГОГРАДСКАЯ ОБЛАСТЬ, Г. ВОЛЖСКИЙ, УЛ. ГОРЬКОГО, Д. 1")
    reg = nice_address("400075, ВОЛГОГРАДСКАЯ ОБЛАСТЬ, Г.О. ГОРОД-ГЕРОЙ ВОЛГОГРАД, Г. ВОЛГОГРАД, ПР-Д НЕФТЯНИКОВ, Д. 2, ОФИС 14")
    assert reg == "400075, Волгоградская область, г. Волгоград, пр-д Нефтяников, д. 2, офис 14"
    assert nice_address("101000, Г.МОСКВА, УЛ. ПОКРОВКА, Д. 40") == "101000, г. Москва, ул. Покровка, д. 40"
    assert same_address("400075, г. Волгоград, пр-д Нефтяников, д. 2", reg) and not same_address("400075, г. Волгоград, ул. Мира, д. 7", reg)


def test_pb_card_parse_bankrupt_company():
    p = pb.parse(fx("pb_ortech.json"))
    assert p["inn"] == "3460057668" and p["status_text"] == "Процесс банкротства"
    assert p["stage_text"] == "В отношении ЮЛ открыто конкурсное производство" and p["stage_date"] == "2025-10-10"
    assert round(p["arrears"]) == 19306897 and p["headcount"] == 30 and p["headcount_year"] == 2025
    assert p["girbo_id"] == "9193261" and p["okved_main"] == "71.12" and ("71.12", p["okved_main_name"]) in p["okved_all"]
    assert not p["invalid"] and not p["mass_head"] and p["head"]["position"] == "КОНКУРСНЫЙ УПРАВЛЯЮЩИЙ"


def test_girbo_financials_in_thousands():
    rep = fx("girbo_bfo_mart.json")
    years = girbo.parse_bfo(rep)
    assert [y["year"] for y in years] == [2025, 2024, 2023, 2022, 2021]
    y23 = next(y for y in years if y["year"] == 2023)
    assert y23["revenue"] == 466850 and y23["net_profit"] == 248179 and y23["equity"] == 269111 and y23["assets"] == 322758


def test_fedresurs_parse_active_case_and_recent_intents():
    bk = {"intentionMessages": [{"datePublish": "2026-02-14T14:32:21", "typeName": "Намерение кредитора обратиться в суд"},
                                {"datePublish": "2024-01-31T10:03:35", "typeName": "Намерение кредитора обратиться в суд"}],
          "legalCases": [{"number": "А12-5342/2025", "status": {"code": "Tender", "name": "Конкурсное производство"},
                          "lastPublications": [{"datePublish": "2026-09-18T20:34:02", "typeName": "Сообщение"}]}]}
    f = fedresurs.parse({"guid": "g1", "status": "Признано банкротом", "isActive": True}, bk, TODAY)
    assert f["bankrupt"] and f["active_case"]["number"] == "А12-5342/2025"
    assert [x["date"] for x in f["intents_recent"]] == ["2026-02-14"]
    ok = fedresurs.parse({"guid": "g2", "status": None, "isActive": True}, {"legalCases": [{"number": "А12-1/2020", "status": {"code": "Completed", "name": "Завершено"}}]}, TODAY)
    assert not ok["bankrupt"] and ok["active_case"] is None


def test_opendata_scan_and_lookup(tmp_path):
    xml = ('<?xml version="1.0" encoding="UTF-8"?><Файл><Документ ИдДок="1" ДатаСост="01.08.2026"><СведНП НаимОрг="А" ИННЮЛ="3460057668"/>'
           '<СведНедоим НаимНалог="Страховые взносы" ОбщСумНедоим="7771567.67"/><СведНедоим НаимНалог="Суммы пеней" ОбщСумНедоим="3045297.44"/></Документ>'
           '<Документ ИдДок="2" ДатаСост="01.08.2026"><СведНП НаимОрг="Б" ИННЮЛ="7700000000"/><СведНедоим НаимНалог="НДС" ОбщСумНедоим="5"/></Документ></Файл>')
    z = tmp_path / "debtam.zip"
    with zipfile.ZipFile(z, "w") as f:
        f.writestr("a.xml", xml)
    as_of, recs = opendata.scan(z, {"3460057668", "3435109665"})
    assert as_of == "2026-08-01" and set(recs) == {"3460057668"}
    od = {"debtam": {"as_of": as_of, "records": recs}}
    assert round(opendata.lookup(od, "3460057668")["arrears"]) == 10816865
    assert opendata.lookup(od, "3435109665")["arrears"] == 0.0   # нет в наборе должников — нет долга


# ---------- статус и риски ----------

def test_status_priority_and_texts():
    assert risks.status({"end_date": "2024-10-15"}, None, None)[:2] == ("LIQUIDATED", "Ликвидировано 15.10.2024")
    code, text, by = risks.status({"end_date": None}, pb.parse(fx("pb_ortech.json")), FED_BANKRUPT)
    assert code == "BANKRUPTCY" and text == "Банкротство: конкурсное производство с 10.10.2025, дело А12-5342/2025" and set(by) == {"fedresurs", "pb"}
    assert risks.status({"end_date": None}, {"status_text": "Находится в стадии ликвидации", "stage_date": "2026-05-01"}, None)[:2] == ("LIQUIDATING", "В стадии ликвидации с 01.05.2026")
    assert risks.status({"end_date": None}, None, {"bankrupt": False, "intents_recent": []})[0] == "ACTIVE"
    assert risks.status(None, None, None) == (None, None, [])
    assert risks.status_of_text("Банкротство: конкурсное производство с 10.10.2025") == "BANKRUPTCY"
    assert risks.status_of_text("Ликвидировано 15.10.2024") == "LIQUIDATED" and risks.status_of_text("Действующее") == "ACTIVE"


def test_risk_signals_rules():
    fin = {"years": [{"year": 2025, "revenue": 4000, "net_profit": -900, "assets": 500, "equity": -100},
                     {"year": 2024, "revenue": 20000, "net_profit": 10, "assets": 900, "equity": 800}]}
    pbd = {"invalid": True, "no_reports": False, "arrears": 2_500_000, "arrears_period": "08.2026", "mass_address": 12,
           "mass_head": False, "head": None, "vestnik": 0}
    fed = {"bankrupt": False, "intents_recent": [{"date": "2026-03-01", "type": "Намерение"}]}
    s = {x["code"]: x for x in risks.signals(pbd, fed, fin, None, "ACTIVE", TODAY)}
    assert set(s) == {"INVALID_DATA", "TAX_ARREARS", "MASS_ADDRESS", "BANKRUPTCY_INTENT", "NEGATIVE_EQUITY", "LOSS", "REVENUE_DROP"}
    assert s["TAX_ARREARS"]["level"] == "high" and "2,5 млн ₽" in s["TAX_ARREARS"]["text"]
    # открытые данные важнее «Прозрачного бизнеса»: долга нет — сигнала нет
    s2 = {x["code"] for x in risks.signals(pbd, None, None, None, "ACTIVE", TODAY, od={"arrears": 0.0})}
    assert "TAX_ARREARS" not in s2
    # у банкрота намерения кредиторов уже не отдельный риск
    assert "BANKRUPTCY_INTENT" not in {x["code"] for x in risks.signals(None, fed, None, None, "BANKRUPTCY", TODAY)}
    # у ликвидированной компании достаточно метки закрытия
    assert risks.signals(pbd, fed, fin, None, "LIQUIDATED", TODAY) == []


# ---------- слияние с базой ----------

def test_liquidation_marks_company_outdated_and_logs_history(repo):
    st = Store()
    ch = merge.update(st, "vnm", result("3446003396", egrul={"end_date": "2026-09-20", "kpp": "344601001", "ogrn": "1023404238384"},
                                        fedresurs={"bankrupt": False, "intents_recent": [], "url": "https://fedresurs.ru/companies/x"}), TODAY)
    c = st.companies["vnm"]
    assert c["status_code"] == "LIQUIDATED" and c["legal_status"] == "Ликвидировано 20.09.2026" and c["verification_status"] == "OUTDATED"
    assert [x["kind"] for x in ch] == ["status"] and c["history"][0]["new"] == "Ликвидировано 20.09.2026"
    assert {s["id"] for s in st.sources["vnm"]} >= {"vnm-egrul", "vnm-fedresurs"}


def test_bankruptcy_keeps_curated_text_and_is_not_downgraded_by_partial_run(repo):
    st = Store()
    before = st.companies["ortech"]["legal_status"]
    merge.update(st, "ortech", result("3460057668", egrul={"end_date": None}, fedresurs=FED_BANKRUPT, pb=pb.parse(fx("pb_ortech.json"))), TODAY)
    c = st.companies["ortech"]
    assert c["status_code"] == "BANKRUPTCY" and c["legal_status"] == before   # тот же статус: ручной текст не трогаем
    assert any(s["code"] == "TAX_ARREARS" for s in c["risk_signals"]) and c["registry"]["headcount"] == 30
    # Федресурс не ответил, ЕГРЮЛ показывает действующую: понижать до «действующее» нельзя
    res = result("3460057668", egrul={"end_date": None})
    res["errors"]["fedresurs"] = "fedresurs.ru: HTTP 503"
    merge.update(st, "ortech", res, TODAY)
    assert c["status_code"] == "BANKRUPTCY" and any(s["code"] == "TAX_ARREARS" for s in c["risk_signals"])
    assert next(s for s in st.sources["ortech"] if s["id"] == "ortech-fedresurs")["fetch_status"] == "FAILED"


def test_requisites_update_but_catalog_name_and_address_format_kept(repo):
    st = Store()
    c = st.companies["vnm"]
    name, addr = c["name"], c["address"]
    ch = merge.update(st, "vnm", result("3446003396", egrul={"end_date": None, "kpp": "344601002", "legal_name": c["legal_name"].lower()}), TODAY)
    assert c["kpp"] == "344601002" and c["name"] == name and c["address"] == addr
    assert [(x["field"], x["old"], x["new"]) for x in ch] == [("КПП", "344601001", "344601002")]


def test_branch_keeps_site_address_when_registry_has_head_office(repo):
    st = Store()
    addr = st.companies["vtz"]["address"]
    merge.update(st, "vtz", result(st.companies["vtz"]["inn"], egrul={"end_date": None},
                                   fedresurs={"bankrupt": False, "intents_recent": [], "url": "u", "address": "101000, Г.МОСКВА, УЛ. ПОКРОВКА, Д. 40, СТР. 2А"}), TODAY)
    assert st.companies["vtz"]["address"] == addr


def test_new_company_created_from_registries_and_bundled(repo):
    st = Store()
    p = pb.parse(fx("pb_ortech.json"))
    p.update(inn="3435109665", status_text="Действующая организация", stage_text=None, stage_date=None, short_name='ООО "МАРТ"',
             legal_name='ОБЩЕСТВО С ОГРАНИЧЕННОЙ ОТВЕТСТВЕННОСТЬЮ "МАРТ"', okved_main="28.9", okved_main_name="Производство прочих машин специального назначения",
             okved_all=[("28.9", "Производство прочих машин специального назначения"), ("25.62", "Обработка металлических изделий механическая")],
             address="404103, ВОЛГОГРАДСКАЯ ОБЛАСТЬ, Г. ВОЛЖСКИЙ, УЛ. АЛЕКСАНДРОВА, Д. 58", city="ВОЛЖСКИЙ", region_code="34")
    res = result("3435109665", egrul={"end_date": None, "ogrn": "1113435009467", "kpp": "343501001", "reg_date": "2011-08-16", "short_name": 'ООО "МАРТ"'},
                 fedresurs={"bankrupt": False, "intents_recent": [], "url": "https://fedresurs.ru/companies/m"}, pb=p,
                 girbo={"girbo_id": "2321101", "url": "https://bo.nalog.gov.ru/organizations-card/2321101", "years": girbo.parse_bfo(fx("girbo_bfo_mart.json")), "okpo": "12345678"})
    cid, ch = merge.create(st, res, TODAY)
    c = st.companies[cid]
    assert cid == "mart" and c["name"] == "ООО «Март»" and c["city"] == "Волжский" and c["industry"] == "Машиностроение"
    assert c["status_code"] == "ACTIVE" and c["verification_status"] == "PARTIALLY_VERIFIED" and c["origin"] == "registry_sync"
    assert c["okved_extra"] == ["25.62"] and {"Механическая обработка металлических изделий"} <= {x["name"] for x in c["capabilities_declared"]}
    assert c["registry"]["finance"][0]["year"] == 2025 and c["okpo"] == "12345678"
    assert [x["kind"] for x in ch] == ["added"] and c["history"][0]["kind"] == "added"
    rev0 = st.save()
    again = Store()
    assert again.companies["mart"] == c and again.sources["mart"] == st.sources["mart"] and again.products["mart"] == []
    assert again.okved["28.9"] == "Производство прочих машин специального назначения"
    with connect("catalog") as conn:
        assert cat.revision(conn) == rev0


def test_catalog_round_trip_keeps_every_field(repo):
    """Карточка, записанная в таблицы и прочитанная обратно, совпадает с исходной — ничего не теряется."""
    seed = {x["company"]["id"]: x for x in json.loads(testing.SEED.read_text(encoding="utf-8"))["companies"]}
    st = Store()

    def drop(v):
        if isinstance(v, dict):
            return {k: drop(x) for k, x in v.items() if x not in (None, [], {})}
        if isinstance(v, float):   # суммы в JSON несли шум двоичной арифметики, numeric хранит точные копейки
            return round(v, 6)
        return [drop(x) for x in v] if isinstance(v, list) else v

    for cid, x in seed.items():
        assert drop(st.companies[cid]) == drop(x["company"]), cid
        assert drop(st.products[cid]) == drop(x["products"]) and drop(st.sources[cid]) == drop(x["sources"]), cid
    # неизвестное схеме поле сохраняется в extra и возвращается
    st.companies["vnm"]["new_field"] = {"a": 1}
    st.dirty.add("vnm")
    st.save()
    assert Store().companies["vnm"]["new_field"] == {"a": 1}


# ---------- полный проход без сети ----------

def test_full_run_offline(repo, monkeypatch):
    rows = [{"girbo_id": "1", "inn": "3435109665", "ogrn": "1113435009467", "short_name": 'ООО "МАРТ"', "okved_main": "28.9", "status": "ACTIVE",
             "status_date": None, "city": "ВОЛЖСКИЙ", "revenue_k": 160966, "period": "2025"},
            {"girbo_id": "2", "inn": "3444000000", "ogrn": "1", "short_name": 'ООО "МАЛО"', "okved_main": "25.11", "status": "ACTIVE",
             "status_date": None, "city": "ВОЛГОГРАД", "revenue_k": 0, "period": "2025"},  # без выручки — «пустая» компания, не берём
            {"girbo_id": "3", "inn": "3444000001", "ogrn": "2", "short_name": 'ООО "ЗАКРЫТО"', "okved_main": "25.11", "status": "LIQUIDATED",
             "status_date": None, "city": "ВОЛГОГРАД", "revenue_k": 99999, "period": "2025"}]
    monkeypatch.setattr(girbo, "discover", lambda http, okved, reg, **kw: iter(rows if okved == "28" and reg["query"] == "Волгоградская" else []))
    monkeypatch.setattr(run.egrul, "fetch", lambda http, inn: {"end_date": "2024-10-15" if inn == "3443144920" else None, "short_name": 'ООО "МАРТ"',
                                                               "legal_name": 'ОБЩЕСТВО С ОГРАНИЧЕННОЙ ОТВЕТСТВЕННОСТЬЮ "МАРТ"' if inn == "3435109665" else None,
                                                               "ogrn": None, "kpp": None, "reg_date": "2011-08-16"})
    monkeypatch.setattr(run.fedresurs, "fetch", lambda http, inn: {"bankrupt": inn == "3460057668", "intents_recent": [], "active_case": None,
                                                                   "url": "https://fedresurs.ru/companies/x"})
    monkeypatch.setattr(run.pb, "fetch", lambda http, inn: None)
    monkeypatch.setattr(run.girbo, "fetch", lambda http, inn, gid=None: {"girbo_id": gid, "url": "https://bo.nalog.gov.ru/organizations-card/1", "years": [],
                                                                        "okpo": None, "okved_main": "28.9", "okved_main_name": "Производство прочих машин специального назначения"}
                        if inn == "3435109665" else None)
    # порог 0 в настройке не пускает компании без выручки: правило «не брать пустые компании» действует всегда
    doc = run.run(run.parse_args(["--no-opendata", "--min-revenue", "0", "--delay", "0", "--workers", "2"]))
    assert doc["stats"]["added"] == 1 and doc["found"] == 3
    with connect("ingest") as g:
        st = ingest.read_status(g)
        assert st["state"] == "idle" and st["last_run"]["stats"]["added"] == 1 and not ingest.lock_active(g)
        log = ingest.read_run(g)
        assert log["stats"]["added"] == 1 and log["trigger"] == "вручную из командной строки" and any(x["kind"] == "added" for x in log["changes"])
    st = Store()
    assert "mart" in st.companies and "malo" not in st.companies and "zakryto" not in st.companies   # порог выручки и статус
    vzbt = st.companies["vzbt"]
    assert vzbt["status_code"] == "LIQUIDATED" and vzbt["verification_status"] == "OUTDATED"
    assert st.okved["28.9"] == "Производство прочих машин специального назначения" and st.companies["mart"]["subindustry"] == st.okved["28.9"]


def test_run_control_lock_request_and_schedule(repo):
    from datetime import datetime
    from sync import control
    assert control.acquire({"trigger": "тест"}) and not control.acquire({"trigger": "второй"})   # второй запуск не пускаем
    # сбор при занятой блокировке пропускается и ничего не пишет
    assert run.run(run.parse_args(["--no-discover", "--no-opendata"])) is None
    control.release()
    assert control.acquire({"trigger": "упал"})
    with connect("ingest") as g:   # процесс упал час назад: блокировка не обновлялась
        g.execute("UPDATE sync_lock SET heartbeat_at = now() - interval '1 hour'")
        g.commit()
    assert control.acquire({"trigger": "после аварии"})                                         # брошенная блокировка снимается
    control.release()
    control.request_run("dev-admin")
    assert control.take_request()["requested_by"] == "dev-admin" and control.take_request() is None
    assert run.next_run("00:01", datetime(2026, 9, 25, 0, 0)) == datetime(2026, 9, 25, 0, 1)
    assert run.next_run("00:01", datetime(2026, 9, 25, 0, 1)) == datetime(2026, 9, 26, 0, 1)


def test_girbo_okpo_skips_invalid_checksum():
    # ГИР БО иногда отдаёт в поле ОКПО код ОКТМО: такой номер не берём, ищем верный в более ранних отчётах
    reports = [{"period": "2025", "organizationInfo": {"okpo": "60701000"}},
               {"period": "2024", "organizationInfo": {"okpo": "44448753"}}]
    assert girbo.parse_okpo(reports) == "44448753"
    assert girbo.parse_okpo(reports[:1]) is None

