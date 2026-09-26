"""Продукция предприятий: реестр МСП ФНС, восстановление повреждённого архива, позиции с официальных сайтов."""
import importlib.util
import io
import zipfile
from contextlib import contextmanager
from datetime import date
from pathlib import Path

from sync import merge
from sync.providers import opendata, rmsp
from sync.store import Store

ROOT = Path(__file__).resolve().parents[2]
TODAY = date(2026, 9, 26)


def rmsp_xml(docs: list[str]) -> bytes:
    body = "".join(docs)
    return f'<?xml version="1.0" encoding="UTF-8"?><Файл ИдФайл="t" ВерсФорм="4.02" ТипИнф="РЕЕСТРМСП" КолДок="{len(docs)}">{body}</Файл>'.encode("utf-8")


def rmsp_doc(inn: str, prods: list[tuple[str, str, str]]) -> str:
    sv = "".join(f'<СвПрод КодПрод="{c}" НаимПрод="{n}" ПрОтнПрод="{i}"/>' for c, n, i in prods)
    return (f'<Документ ИдДок="{inn}" ДатаСост="10.09.2026" ДатаВклМСП="10.08.2016" ВидСубМСП="1" КатСубМСП="2" ПризНовМСП="2">'
            f'<ОргВклМСП НаимОрг="ООО &quot;ТЕСТ&quot;" ИННЮЛ="{inn}"/><СведМН КодРегион="34"/>{sv}</Документ>')


def make_zip(files: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in files.items():
            z.writestr(name, data)
    return buf.getvalue()


def test_rmsp_scan_takes_only_our_inns_and_unescapes_names(tmp_path):
    p = tmp_path / "rsmp.zip"
    p.write_bytes(make_zip({"a.xml": rmsp_xml([rmsp_doc("3435109665", [("25.11.23.119", "Конструкции &quot;МК&quot; прочие", "2"),
                                                                        ("28.22.14.159", "Краны мостовые", "1")]),
                                               rmsp_doc("7700000000", [("10.11.11", "Мясо", "2")])]),
                            "b.xml": rmsp_xml([rmsp_doc("3444000001", [])])}))
    as_of, recs, bad = rmsp.scan(p, {"3435109665", "3444000001"}, log=lambda *a: None)
    assert as_of == "2026-09-10" and bad == [] and set(recs) == {"3435109665"}   # без продукции — не запись
    r = recs["3435109665"]
    assert r["category"] == "малое предприятие" and r["products"][0] == {"code": "25.11.23.119", "name": 'Конструкции "МК" прочие', "innovative": False}
    assert r["products"][1]["innovative"] is True


def test_rmsp_scan_reports_damaged_file(tmp_path):
    good = rmsp_xml([rmsp_doc("3435109665", [("28.22.14.159", "Краны мостовые", "2")])])
    raw = bytearray(make_zip({"a.xml": good * 3, "b.xml": good}))
    info = zipfile.ZipFile(io.BytesIO(bytes(raw))).getinfo("a.xml")
    start = info.header_offset + 30 + len("a.xml".encode()) + 10
    raw[start:start + 40] = b"\xff" * 40                                          # порча сжатых данных внутри файла
    p = tmp_path / "rsmp.zip"
    p.write_bytes(bytes(raw))
    _, recs, bad = rmsp.scan(p, {"3435109665"}, log=lambda *a: None)
    assert bad == ["a.xml"] and "3435109665" in recs                               # второй файл прочитан


class FakeHttp:
    """Сервер, отдающий байты архива по HTTP Range."""
    def __init__(self, data: bytes):
        self.data, self.client = data, self

    @contextmanager
    def stream(self, method, url, headers=None, timeout=None):
        a, b = headers["Range"].removeprefix("bytes=").split("-")
        a, b = int(a), int(b) if b else len(self.data) - 1
        chunk = self.data[a:b + 1]

        class R:
            status_code = 206
            headers = {"content-range": f"bytes {a}-{b}/{len(self.data)}"}

            def iter_bytes(self, n):
                for i in range(0, len(chunk), n):
                    yield chunk[i:i + n]
        yield R()


def test_damaged_download_is_detected_and_repaired_by_range(tmp_path):
    files = {f"f{i}.xml": rmsp_xml([rmsp_doc(f"34350000{i:02d}", [("28.22", f"Краны {i}", "2")])]) * 20 for i in range(12)}
    original = make_zip(files)
    broken = bytearray(original)
    z = zipfile.ZipFile(io.BytesIO(original))
    infos = sorted(z.infolist(), key=lambda i: i.header_offset)
    a, b = infos[3].header_offset + 7, infos[8].header_offset + 5
    broken[a:b] = bytes((x + 1) % 256 for x in broken[a:b])                       # другие байты в середине, как при сбое потока
    p = tmp_path / "rsmp.zip"
    p.write_bytes(bytes(broken))
    ranges = opendata.verify_zip(p)
    assert ranges and ranges[0][0] <= a and ranges[-1][1] >= infos[8].header_offset - 1
    opendata.patch_ranges(FakeHttp(original), "https://file.nalog.ru/x.zip", p, ranges)
    assert opendata.verify_zip(p) == [] and p.read_bytes() == original
    with zipfile.ZipFile(p) as zz:
        assert zz.testzip() is None
        assert opendata.member_range(zz, "f0.xml")[0] == 0


def test_rmsp_products_replace_only_their_own(repo):
    st = Store()
    seed = [p["id"] for p in st.products["vnm"]]
    rec = {"date": "2026-09-10", "category": "среднее предприятие",
           "products": [{"code": "28.13.14.110", "name": "насосы центробежные", "innovative": True},
                        {"code": "33.12.19.000", "name": "Услуги по ремонту прочего оборудования", "innovative": False}]}
    ch = merge.apply_rmsp(st, "vnm", rec, TODAY)
    ids = [p["id"] for p in st.products["vnm"]]
    assert ids[:len(seed)] == seed and ids[len(seed):] == ["vnm-okpd2-28-13-14-110", "vnm-okpd2-33-12-19-000"]
    pump, repair = st.products["vnm"][-2:]
    assert pump["name"] == "Насосы центробежные" and pump["okpd2"] == {"code": "28.13.14.110", "name": "насосы центробежные", "status": "SOURCE"}
    assert "инновационная" in pump["description"] and pump["source_id"] == "vnm-rmsp" and repair["kind"] == "service"
    assert any(s["id"] == "vnm-rmsp" and s["source_type"] == "FNS_RMSP" for s in st.sources["vnm"])
    assert [x["kind"] for x in ch] == ["products"] and st.companies["vnm"]["history"][0]["new"] == "2 поз."
    assert merge.apply_rmsp(st, "vnm", rec, TODAY) == []                       # те же данные — без изменений
    st.save()
    st2 = Store()
    assert [p["id"] for p in st2.products["vnm"]] == ids                      # записано в базу, ручные позиции на месте
    merge.apply_rmsp(st2, "vnm", {**rec, "products": rec["products"][:1]}, TODAY)
    assert [p["id"] for p in st2.products["vnm"]] == seed + ["vnm-okpd2-28-13-14-110"]
    merge.apply_rmsp(st2, "vnm", None, TODAY)                                 # предприятие убрало продукцию из реестра
    assert [p["id"] for p in st2.products["vnm"]] == seed and not any(s["id"] == "vnm-rmsp" for s in st2.sources["vnm"])


def test_rmsp_okpd2_names_fill_only_empty_dictionary_entries(repo, tmp_path):
    """Названия кодов ОКПД2 собираются тем же проходом по архиву реестра МСП из всех документов (не только предприятий базы)
    и заполняют справочник только там, где названия нет."""
    from collections import Counter
    from pkdb import tx
    names: dict[str, Counter] = {}
    xml = rmsp_xml([rmsp_doc("7700000000", [("27.32.13", "Провода и кабели электронные и электрические прочие  Эта группировка включает: провода", "2"),
                                            ("56.10.11.129-0000", "Услуги ресторанов", "2")]),
                    rmsp_doc("7700000001", [("27.32.13", "Провода и кабели электронные и электрические прочие", "2"),
                                            ("24.10", "Другое название класса", "2")])])
    z = tmp_path / "rsmp.zip"
    z.write_bytes(make_zip({"a.xml": xml}))
    rmsp.scan(z, set(), log=lambda *a: None, okpd2=names)
    got = {k: v.most_common(1)[0][0] for k, v in names.items()}
    assert got["27.32.13"] == "Провода и кабели электронные и электрические прочие"          # без пояснения классификатора
    st = Store()
    before = st.okpd2["24.10"]
    assert before and merge.apply_okpd2_names(st, got) == 1                                  # только 27.32.13
    assert st.okpd2["24.10"] == before and "56.10.11.129-0000" not in st.okpd2              # название первичного сбора не заменено
    st.save()
    with tx("catalog") as c:
        assert c.execute("SELECT name FROM okpd2 WHERE code = '27.32.13'").fetchone()["name"].startswith("Провода и кабели")


def load_tool():
    spec = importlib.util.spec_from_file_location("crawl_products", ROOT / "tools" / "crawl_products.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def page(url, h1="", hop=1, menu=(), sections=(), crumbs=(), text=""):
    return {"url": url, "status": "OK", "fetched_at": None, "text": text, "source_url": "https://ukz.test/",
            "e": {"h1": h1, "hop": hop, "catalog_menu": [{"name": n, "url": u, "cls": c} for n, u, c in menu], "cards": [],
                  "sections": list(sections), "breadcrumbs": list(crumbs), "specs": []}}


def test_site_candidates_keep_catalog_items_and_drop_navigation():
    t = load_tool()
    pages = {t.canon(p["url"]): p for p in [
        page("https://ukz.test/", "Урюпинский крановый завод", hop=0, text="мостовые краны козловые краны",
             menu=[("Мостовые краны", "https://ukz.test/catalog/mostovye/", "catalog-menu__item"),
                   ("Тали электрические", "https://ukz.test/catalog/tali/", "catalog-menu__item"),
                   ("Подробнее", "https://ukz.test/catalog/tali/", "catalog-menu__item"),
                   ("Завод отметил 70-летие", "https://ukz.test/news/70/", "catalog-menu__item"),
                   ("Сервис", "https://ukz.test/service/", "t228__list_item")]),
        page("https://ukz.test/catalog/mostovye/", "Мостовые краны", crumbs=["Главная", "Краны"]),
        page("https://ukz.test/catalog/tali/", "Тали электрические канатные"),
        page("https://ukz.test/service/", "Услуги", sections=["Ремонт кранов", "Монтаж подъёмных сооружений", "Отправить заявку"]),
        page("https://ukz.test/news/70/", "Завод отметил 70-летие"),
    ]}
    existing = [{"id": "ukz-bridge", "name": "Мостовые краны"}, {"id": "ukz-gantry", "name": "Козловые краны"}]
    cand, confirmed = t.candidates("ukz", pages, existing)
    by = {c["name"]: c for c in cand}
    assert {x["id"] for x in confirmed} == {"ukz-bridge", "ukz-gantry"}          # по названию на сайте и по тексту страницы
    tali = by["Тали электрические канатные"]                                     # название — заголовок страницы позиции
    assert tali["decision"] == "accept" and tali["url"] == "https://ukz.test/catalog/tali/" and "Тали электрические" in tali["alt"]
    assert by["Ремонт кранов"]["decision"] == "review" and by["Ремонт кранов"]["kind"] == "service"
    assert by["Отправить заявку"]["decision"] == "reject"
    assert "Подробнее" not in by and "Завод отметил 70-летие" not in by       # кнопка и новость не кандидаты


def test_okpd2_class_by_head_word_and_specs_cleanup():
    t = load_tool()
    okpd2 = {"28.13": "Насосы и компрессоры прочие", "25.62": "Услуги по механической обработке металлических изделий", "24.10": "Прокат"}
    assert t.infer_okpd2("Насосы КМ консольные моноблочные", okpd2) == {"code": "28.13", "name": "Насосы и компрессоры прочие", "status": "INFERRED"}
    assert t.infer_okpd2('Станция (шкаф) управления и защиты СУиЗ "Лоцман+" для погружных насосов', okpd2) is None   # не насос
    assert t.infer_okpd2("Услуги по резке листового проката", okpd2, "service")["code"] == "25.62"                     # услуга, не прокат
    sitewide = {("Тип конструкции", "вакуумные")}
    specs = [["Тип конструкции", "вакуумные"], ["Наименование", "Значение"], ["2950", "1475"], ["Подача, м³/ч", "8 - 2500"]]
    assert t.clean_specs(specs, sitewide) == [{"name": "Подача, м³/ч", "value": "8 - 2500"}]
    assert t.tidy("ТАЛИ ЭЛЕКТРИЧЕСКИЕ С УМЕНЬШЕННОЙ ВЫСОТОЙ (Цена по запросу)") == "Тали электрические с уменьшенной высотой"
    assert t.tidy("ГНОМ Ф, ФР") == "ГНОМ Ф, ФР"                                                                      # модели не трогаем
    assert t.short_title("Станция (шкаф) управления и защиты HMS Control G - автоматика для дренажного насоса (ГНОМ и аналоги) и его двигателя") \
        == "Станция (шкаф) управления и защиты HMS Control G"


MPT_HEADER = ("Nameoforg,OGRN,INN,Orgaddr,Productmanufaddress,Regnumber,Ektrudp,Docdate,Docvalidtill,Enddate,Registernumber,Productname,OKPD2,TNVED,"
              "Nameofregulations,Score,Percentage,Scoredesc,Iselectronicproduct,Isai,ElectronicProductLevel,Docname,Docdatebasis,Docnum,Docvalidtilltpp,Mptdep,Resdocnum")


def mpt_row(inn, reg, name, okpd2="28.13.14.110", valid="2027-04-09", end="-"):
    return (f'"ООО ""ТЕСТ""",1023404238384,{inn},-,-,-,-,2024-04-10,{valid},{end},{reg},"{name}",{okpd2},8413 70 300 0,'
            f'ТУ 3631-001-00217610-2014,185.0,-,-,-,Нет,-,Акт экспертизы ТПП,2024-03-15,012-01-00080,-,Департамент,-')


def test_minpromtorg_registry_takes_only_valid_records(tmp_path):
    from sync.providers import minpromtorg
    p = tmp_path / "reestr-products-20260925.csv"
    p.write_text("\n".join([MPT_HEADER, mpt_row("3446003396", "100", "Насос НД630-90"), mpt_row("3446003396", "101", "Насос старый", valid="2025-01-01"),
                            mpt_row("3446003396", "102", "Насос исключённый", end="2025-02-28"), mpt_row("7700000000", "103", "Чужой насос")]) + "\n",
                 encoding="utf-8")
    as_of, recs = minpromtorg.scan(p, {"3446003396"}, TODAY)
    assert as_of == "2026-09-25" and [r["Registernumber"] for r in recs["3446003396"]] == ["100"]
    r = recs["3446003396"][0]
    assert r["Productname"] == "Насос НД630-90" and r["TNVED"] == "8413 70 300 0" and r["Enddate"] is None
    assert minpromtorg.ensure(None, TODAY, cache=tmp_path) == p          # свежий файл из кеша — без обращения к серверу


def test_minpromtorg_products_merge_and_branches(repo):
    st = Store()
    seed = [p["id"] for p in st.products["vnm"]]
    recs = [{"INN": "3446003396", "Registernumber": "100", "Productname": "Насос НД630-90", "OKPD2": "28.13.14.110", "TNVED": "8413 70 300 0",
             "Nameofregulations": "ТУ 3631-001", "Docdate": "2024-04-10", "Docvalidtill": "2027-04-09", "Enddate": None, "Docname": "Акт экспертизы ТПП",
             "Docdatebasis": "2024-03-15", "Score": "185.0", "Percentage": None, "Mptdep": "Департамент"}]
    ch = merge.apply_minprom(st, "vnm", recs, "2026-09-25", TODAY)
    p = st.products["vnm"][-1]
    assert [x["id"] for x in st.products["vnm"]] == seed + ["vnm-rpp-100"] and p["okpd2"] == {"code": "28.13.14.110", "name": None, "status": "SOURCE"}
    assert {"name": "Реестровая запись Минпромторга", "value": "100"} in p["params"] and {"name": "Баллы локализации", "value": "185"} in p["params"]
    assert "акт экспертизы тпп от 15.03.2024" in p["description"].lower() and "действует до 09.04.2027" in p["description"]
    assert any(s["id"] == "vnm-minprom" and s["source_type"] == "MPT_REESTR" for s in st.sources["vnm"]) and ch[0]["kind"] == "products"
    assert merge.apply_minprom(st, "vnm", recs, "2026-09-25", TODAY) == []
    st.save()
    assert Store().products["vnm"][-1]["okpd2"]["name"] is None                          # код без названия: NULL, не выдумка
    # филиал заведён с ИНН головной компании: продукция всех её заводов не приписывается филиалу
    assert merge.apply_minprom(st, "vtz", recs, "2026-09-25", TODAY) == [] and not any(p["source_id"] == "vtz-minprom" for p in st.products["vtz"])
    merge.apply_minprom(st, "vnm", None, "2026-09-25", TODAY)                           # записи исключены из реестра
    assert [x["id"] for x in st.products["vnm"]] == seed


def test_minpromtorg_renewal_keeps_latest_record():
    recs = [{"Registernumber": "7", "Productname": "Кран", "OKPD2": "28.22", "Docdate": "2024-10-04", "Docvalidtill": "2027-10-03", "Docname": "Акт экспертизы ТПП",
             "Docdatebasis": "2024-08-19"},
            {"Registernumber": "7", "Productname": "Кран", "OKPD2": "28.22", "Docdate": "2026-05-26", "Docvalidtill": "2030-06-23", "Docname": "Акт экспертизы ТПП",
             "Docdatebasis": "2026-04-28"}]
    out = merge.minprom_products("ukz", recs, "2026-09-25")
    assert len(out) == 1 and "действует до 23.06.2030" in out[0]["description"]
