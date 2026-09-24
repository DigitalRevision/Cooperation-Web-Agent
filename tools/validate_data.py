"""CI-проверка Git-репозитория данных: каждое значение имеет источник, коды не выдуманы, статусы корректны."""
import json, re, sys, glob, os
ROOT = os.path.join(os.path.dirname(__file__), "..", "data")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend", "app"))
from validators import inn_ok, ogrn_ok, kpp_ok, okpo_ok  # контрольные суммы, как на сервере и сайте
err = []
okved = {x["code"] for x in json.load(open(f"{ROOT}/okved/okved.json", encoding="utf-8"))}
okpd2 = {x["code"] for x in json.load(open(f"{ROOT}/okpd2/okpd2.json", encoding="utf-8"))}
for d in glob.glob(f"{ROOT}/companies/*/"):
    c = json.load(open(d + "company.json", encoding="utf-8")); P = json.load(open(d + "products.json", encoding="utf-8")); S = json.load(open(d + "sources.json", encoding="utf-8"))
    sid = {s["id"] for s in S}
    cid = c["id"]
    if c["verification_status"] not in {"VERIFIED", "PARTIALLY_VERIFIED", "UNVERIFIED", "OUTDATED"}: err.append(f"{cid}: bad status")
    if c.get("inn") and not re.fullmatch(r"\d{10}|\d{12}", c["inn"]): err.append(f"{cid}: bad INN")
    if c.get("ogrn") and not re.fullmatch(r"\d{13}|\d{15}", c["ogrn"]): err.append(f"{cid}: bad OGRN")
    if c.get("inn") and not inn_ok(c["inn"]): err.append(f"{cid}: INN checksum")
    if c.get("ogrn") and not ogrn_ok(c["ogrn"]): err.append(f"{cid}: OGRN checksum")
    if c.get("kpp") and not kpp_ok(c["kpp"]): err.append(f"{cid}: bad KPP")
    if c.get("okpo") and not okpo_ok(c["okpo"]): err.append(f"{cid}: OKPO checksum")
    if c.get("okved_main") and c["okved_main"] not in okved: err.append(f"{cid}: OKVED not in dictionary")
    if c.get("inn") and not any(s["source_type"] in ("EGRUL_AGGREGATOR", "GISP", "FNS") for s in S): err.append(f"{cid}: INN without registry source")
    if c["verification_status"] == "VERIFIED" and not any(s["source_type"] == "OFFICIAL_SITE" and s["fetch_status"] == "OK" for s in S): err.append(f"{cid}: VERIFIED without readable official site")
    for k in ("technologies", "materials", "capacities", "certificates", "sites"):
        for x in c.get(k) or []:
            if x.get("source_id") not in sid: err.append(f"{cid}.{k}: missing source")
    for p in P:
        if p["source_id"] not in sid: err.append(f"{p['id']}: missing source")
        if p.get("okpd2") and p["okpd2"]["code"] not in okpd2: err.append(f"{p['id']}: OKPD2 not in dictionary")
        if p.get("price") and not p["price"].get("source_id"): err.append(f"{p['id']}: price without source")
print("\n".join(err) or "data OK")
sys.exit(1 if err else 0)
