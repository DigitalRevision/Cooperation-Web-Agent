"""Статус юрлица и сигналы риска по данным реестров.

Статус (status_code): ACTIVE, REORGANIZING, LIQUIDATING, BANKRUPTCY, LIQUIDATED. Старший статус побеждает:
ликвидированная после банкротства компания получает LIQUIDATED.
Сигнал риска: {code, level: high|mid|low, title, text, source}. source — ключ источника (egrul, pb, girbo, fedresurs, checko),
при слиянии заменяется на id записи в sources.json компании.
"""
from __future__ import annotations
from datetime import date

from .providers.util import ru_date

RANK = {"ACTIVE": 0, "REORGANIZING": 1, "LIQUIDATING": 2, "BANKRUPTCY": 3, "LIQUIDATED": 4}


def rub(x: float | None) -> str:
    if x is None:
        return "—"
    a = abs(x)
    for div, unit, digits in ((1e9, "млрд ₽", 1), (1e6, "млн ₽", 1), (1e3, "тыс. ₽", 0), (1, "₽", 0)):
        if a >= div or div == 1:
            return f"{x / div:.{digits}f}".replace(".", ",") + " " + unit


def status_of_text(legal_status: str | None) -> str | None:
    """Код статуса по тексту legal_status — для записей, заведённых вручную до синхронизации."""
    t = (legal_status or "").lower()
    if not t:
        return None
    if "банкрот" in t:
        return "BANKRUPTCY"
    if "стадии ликвидации" in t:
        return "LIQUIDATING"
    if "ликвидир" in t or "прекращ" in t:
        return "LIQUIDATED"
    if "реорганиз" in t:
        return "REORGANIZING"
    return "ACTIVE"


def status(egrul: dict | None, pb: dict | None, fed: dict | None, girbo_row: dict | None = None) -> tuple[str | None, str | None, list[str]]:
    """Возвращает (status_code, legal_status, источники статуса) или (None, None, []), если ни один источник не ответил.

    Источники статуса нужны при слиянии: понизить статус (например, «банкротство» → «действующее»)
    можно только если все источники, на которых он держался, ответили в этом запуске.
    """
    if not (egrul or pb or fed or girbo_row):
        return None, None, []
    code, text, by = "ACTIVE", "Действующее", [k for k, v in (("egrul", egrul), ("pb", pb), ("fedresurs", fed)) if v]
    pb_txt = " ".join(filter(None, [(pb or {}).get("status_text"), (pb or {}).get("stage_text")])).lower()

    def up(c: str, t: str, src: list[str]):
        nonlocal code, text, by
        if RANK[c] > RANK[code]:
            code, text, by = c, t, src

    if "реорганизац" in pb_txt:
        up("REORGANIZING", "В стадии реорганизации", ["pb"])
    if "ликвидац" in pb_txt:
        d = (pb or {}).get("stage_date")
        up("LIQUIDATING", "В стадии ликвидации" + (f" с {ru_date(d)}" if d else ""), ["pb"])
    fed_b, pb_b = bool((fed or {}).get("bankrupt")), "банкрот" in pb_txt or "конкурсн" in pb_txt
    if fed_b or pb_b:
        case = (fed or {}).get("active_case") or {}
        stage = (case.get("stage") or "").lower() or ((pb or {}).get("stage_text") or "процедура банкротства").lower()
        stage = stage.replace("в отношении юл открыто ", "").replace("находится в процедуре банкротства", "процедура банкротства")
        d = (pb or {}).get("stage_date") if pb_b else None
        up("BANKRUPTCY", f"Банкротство: {stage}" + (f" с {ru_date(d)}" if d else "") + (f", дело {case['number']}" if case.get("number") else ""),
           [k for k, f in (("fedresurs", fed_b), ("pb", pb_b)) if f])
    end = (egrul or {}).get("end_date")
    pb_end = bool((pb or {}).get("liquidated")) or "прекратил" in pb_txt or "исключен" in pb_txt
    if end or pb_end:
        up("LIQUIDATED", "Ликвидировано" + (f" {ru_date(end)}" if end else ""), [k for k, f in (("egrul", end), ("pb", pb_end)) if f])
    if not (egrul or pb or fed) and girbo_row and girbo_row.get("status") in RANK:
        c = girbo_row["status"]
        up(c, {"LIQUIDATED": "Деятельность прекращена", "LIQUIDATING": "В стадии ликвидации",
               "REORGANIZING": "В стадии реорганизации", "BANKRUPTCY": "Банкротство", "ACTIVE": "Действующее"}[c], ["girbo"])
        by = ["girbo"]
    return code, text, by


def signals(pb: dict | None, fed: dict | None, fin: dict | None, chk: dict | None, status_code: str | None, today: date,
            od: dict | None = None) -> list[dict]:
    out = []
    if status_code == "LIQUIDATED":
        return out   # юрлица нет: достаточно метки закрытия, остальные риски не имеют смысла

    def add(code, level, title, text, source):
        out.append({"code": code, "level": level, "title": title, "text": text, "source": source})

    # задолженность: открытые данные ФНС по всем компаниям сразу, «Прозрачный бизнес» — если набор не загрузился
    if od and "arrears" in od:
        if od["arrears"] >= 1000:
            items = sorted(od.get("arrears_items") or [], key=lambda x: -x["sum"])[:3]
            add("TAX_ARREARS", "high" if od["arrears"] >= 1e6 else "mid", "Задолженность по налогам и взносам",
                f"Недоимка, пени и штрафы {rub(od['arrears'])} на {ru_date(od.get('arrears_date'))}"
                + (": " + "; ".join(f"{x['tax'].lower()} {rub(x['sum'])}" for x in items) if items else "") + ".", "opendata")
        pb = dict(pb or {}, arrears=None, tax_debt_flag=False) if pb else None

    if pb:
        if pb.get("invalid"):
            add("INVALID_DATA", "high", "Недостоверные сведения в ЕГРЮЛ", "ФНС отметила сведения о юрлице (адрес, руководитель или учредитель) как недостоверные.", "pb")
        if pb.get("no_reports"):
            add("NO_REPORTS", "high", "Не сдаёт налоговую отчётность", "Компания не представляет налоговую отчётность более года.", "pb")
        if pb.get("arrears") and pb["arrears"] >= 1000:
            lvl = "high" if pb["arrears"] >= 1e6 else "mid"
            add("TAX_ARREARS", lvl, "Задолженность по налогам и взносам",
                f"Недоимка, пени и штрафы {rub(pb['arrears'])}" + (f" на {pb['arrears_period']}" if pb.get("arrears_period") else "") + ".", "pb")
        elif pb.get("tax_debt_flag"):
            add("TAX_ARREARS", "mid", "Задолженность по налогам", "Задолженность по налогам и сборам более 1000 ₽.", "pb")
        if pb.get("mass_address", 0) >= 10:
            add("MASS_ADDRESS", "mid", "Адрес массовой регистрации", f"По адресу компании зарегистрировано ещё {pb['mass_address']} юрлиц.", "pb")
        if pb.get("mass_head"):
            n = (pb.get("head") or {}).get("companies")
            add("MASS_HEAD", "mid", "Массовый руководитель", f"Руководитель одновременно возглавляет {n} юрлиц." if n else "ФНС отметила руководителя как массового.", "pb")
        if pb.get("vestnik"):
            add("VESTNIK", "low", "Сообщения в «Вестнике государственной регистрации»",
                "Опубликованы сообщения о реорганизации, ликвидации, уменьшении капитала или выходе участника. Проверьте их содержание.", "pb")
    if fed and status_code != "BANKRUPTCY" and fed.get("intents_recent"):
        last = max(x["date"] or "" for x in fed["intents_recent"])
        n = len(fed["intents_recent"])
        add("BANKRUPTCY_INTENT", "mid", "Намерение обратиться в суд о банкротстве",
            f"За год опубликовано {n} сообщ. кредиторов или ФНС о намерении подать заявление о банкротстве, последнее {ru_date(last)}.", "fedresurs")
    years = (fin or {}).get("years") or []
    if years:
        y0 = years[0]
        # отчётность за год сдаётся до 31 марта и публикуется в ГИР БО к лету
        if y0["year"] < (today.year - 1 if today.month >= 6 else today.year - 2):
            add("NO_FINANCIALS", "low", "Нет свежей бухгалтерской отчётности", f"Последняя опубликованная отчётность за {y0['year']} год.", "girbo")
        if y0.get("equity") is not None and y0["equity"] < 0:
            add("NEGATIVE_EQUITY", "high", "Отрицательные чистые активы", f"Капитал и резервы {rub(y0['equity'] * 1000)} на конец {y0['year']} года: обязательства больше активов.", "girbo")
        if y0.get("net_profit") is not None and y0["net_profit"] < 0:
            add("LOSS", "mid", "Убыток по итогам года", f"Чистый убыток {rub(-y0['net_profit'] * 1000)} за {y0['year']} год.", "girbo")
        if len(years) > 1 and years[1]["year"] == y0["year"] - 1:
            r0, r1 = y0.get("revenue"), years[1].get("revenue")
            if r0 is not None and r1 and r1 >= 10000 and r0 < r1 * 0.5:
                add("REVENUE_DROP", "mid", "Выручка упала больше чем вдвое",
                    f"{rub(r1 * 1000)} за {years[1]['year']} → {rub(r0 * 1000)} за {y0['year']}.", "girbo")
    if chk:
        if chk.get("unfair_supplier"):
            add("UNFAIR_SUPPLIER", "high", "В реестре недобросовестных поставщиков", "Компания включена в РНП по 44-ФЗ или 223-ФЗ.", "checko")
        if chk.get("sanctions"):
            add("SANCTIONS", "mid", "Под иностранными санкциями", "Компания в санкционных списках: возможны сложности с платежами и поставками импортных комплектующих.", "checko")
        if chk.get("disqualified"):
            add("DISQUALIFIED", "mid", "Дисквалифицированные лица в руководстве", "В органах управления есть дисквалифицированные лица.", "checko")
        if chk.get("cases_defendant"):
            n, s = chk["cases_defendant"], chk.get("cases_claims_sum") or 0
            add("COURTS_DEFENDANT", "mid" if n >= 3 or s >= 1e6 else "low", "Арбитражные дела в роли ответчика",
                f"{n} дел за 3 года" + (f", сумма исков {rub(s)}" if s else "") + ".", "checko")
        if chk.get("enforcements_debt"):
            d = chk["enforcements_debt"]
            add("ENFORCEMENTS", "high" if d >= 1e6 else "mid", "Исполнительные производства ФССП",
                f"{chk['enforcements']} производств, остаток долга {rub(d)}.", "checko")
    order = {"high": 0, "mid": 1, "low": 2}
    return sorted(out, key=lambda x: order[x["level"]])


def facts(pb: dict | None, fin: dict | None, od: dict | None = None) -> dict:
    """Показатели для карточки: выручка, прибыль, численность, налоги, режим, категория МСП."""
    f = {k: v for k, v in (od or {}).items() if k in ("headcount", "headcount_year", "taxes_paid", "taxes_year", "tax_mode", "arrears", "arrears_date") and v is not None}
    years = (fin or {}).get("years") or []
    if years:
        f["finance"] = [{k: y[k] for k in ("year", "revenue", "net_profit", "assets", "equity")} for y in years[:3]]
    if pb:
        for k in ("headcount", "headcount_year", "taxes_paid", "taxes_year", "msp", "tax_mode", "capital", "arrears"):
            if pb.get(k) is not None and k not in f:
                f[k] = pb[k]
        if pb.get("head"):
            f["head"] = {k: pb["head"][k] for k in ("name", "position")}
        if not years and pb.get("revenue_rub") is not None:
            f["finance"] = [{"year": pb["revenue_year"], "revenue": round(pb["revenue_rub"] / 1000), "net_profit": None, "assets": None, "equity": None}]
    return f
