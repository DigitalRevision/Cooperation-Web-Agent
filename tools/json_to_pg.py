"""Перенос базы из JSON-файлов (прежний Git-репозиторий data/) в PostgreSQL и проверка переноса.

  python tools/json_to_pg.py                     # перенести data/ в базы sm01_catalog и sm01_ingest и проверить
  python tools/json_to_pg.py --data-dir путь     # другой каталог с JSON (например, результат seed-скрипта)
  python tools/json_to_pg.py --replace           # очистить каталог и журналы сбора перед переносом
  python tools/json_to_pg.py --verify-only       # только сверить базу с файлами
  python tools/json_to_pg.py --if-empty          # перенести, только если каталог в базе пуст (первый запуск start-local.cmd)

Проверка: каждая карточка, продукция, источники, справочники и журналы сбора читаются из базы обратно
и сравниваются с исходными файлами. Пустые значения (null, [], {}) при сравнении не различаются.
Пользовательских данных (заявки, регистрации, цепочки) в файлах нет: они жили в браузерах, их переносит
сайт при первом входе (POST /api/v1/me/import-local).
"""
from __future__ import annotations
import argparse
import glob
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pkdb import connect  # noqa: E402
from pkdb import catalog as cat  # noqa: E402
from pkdb import ingest  # noqa: E402

BATCH = 500


def read(p: Path):
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


def load_files(data: Path) -> dict:
    comps, prods, srcs = {}, {}, {}
    for d in sorted((data / "companies").iterdir()):
        if not (d / "company.json").exists():
            continue
        c = read(d / "company.json")
        comps[c["id"]] = c
        prods[c["id"]] = read(d / "products.json") if (d / "products.json").exists() else []
        srcs[c["id"]] = read(d / "sources.json") if (d / "sources.json").exists() else []
    opt = lambda rel, default: read(data / rel) if (data / rel).exists() else default
    runs = {}
    for p in sorted((data / "sync").glob("*.json")) if (data / "sync").is_dir() else []:
        if p.name not in ("latest.json", "status.json", "run-request.json"):
            runs[p.stem] = read(p)
    crawl = {}
    for p in sorted(glob.glob(str(data / "sources" / "crawl_log_*.json"))):
        crawl[Path(p).stem.removeprefix("crawl_log_")] = read(Path(p))
    return {"companies": comps, "products": prods, "sources": srcs,
            "okved": {x["code"]: x["name"] for x in opt("okved/okved.json", [])},
            "okpd2": {x["code"]: x["name"] for x in opt("okpd2/okpd2.json", [])},
            "regions": {x["code"]: x for x in opt("regions/regions.json", [])},
            "cities": opt("regions/cities.json", []), "relations": opt("relations/relations.json", []),
            "materials": opt("materials/materials.json", []), "technologies": opt("technologies/technologies.json", []),
            "runs": runs, "status": opt("sync/status.json", None), "crawl": crawl}


def check_duplicates(data: Path, f: dict) -> list[str]:
    """data/products/*.json и data/sources/sources.json — производные копии; переносить их не нужно, если они совпадают."""
    notes = []
    byid = {p["id"]: p for lst in f["products"].values() for p in lst}
    diff = [p.name for p in (data / "products").glob("*.json") if read(p) != byid.get(read(p)["id"])] if (data / "products").is_dir() else []
    notes.append(f"data/products: {'совпадает с продукцией карточек' if not diff else 'расходится: ' + ', '.join(diff[:5])}")
    if (data / "sources" / "sources.json").exists():
        allsrc = read(data / "sources" / "sources.json")
        mine = [dict(s, company_id=cid) for cid in sorted(f["companies"]) for s in f["sources"][cid]]
        notes.append("data/sources/sources.json: " + ("совпадает с источниками карточек" if allsrc == mine else f"расходится ({len(allsrc)} против {len(mine)})"))
    return notes


def wipe(conn_cat, conn_ing):
    conn_cat.execute("TRUNCATE relation, product_material, product_param, product, source, company_history, company_finance, company_registry, "
                     "company_risk_signal, company_discrepancy_value, company_discrepancy, company_capability, company_site, company_certificate, "
                     "company_capacity, company_material, company_technology, company_okved, company, city, region, okved, okpd2, material, technology")
    conn_ing.execute("TRUNCATE sync_change, sync_error, sync_run, crawl_log RESTART IDENTITY")
    conn_ing.execute("UPDATE sync_state SET status = '{}'")


def import_all(f: dict) -> None:
    with connect("catalog") as c, connect("ingest") as g:
        n = c.execute("SELECT count(*) AS n FROM company").fetchone()["n"]
        if n and not ARGS.replace:
            raise SystemExit(f"В sm01_catalog уже {n} предприятий. Для повторного переноса запустите с --replace.")
        if ARGS.replace:
            wipe(c, g)
        cur = c.cursor()
        cur.executemany("INSERT INTO region (code, name, is_pilot) VALUES (%s,%s,%s)",
                        [(r["code"], r["name"], bool(r.get("pilot"))) for r in f["regions"].values()])
        cur.executemany("INSERT INTO city (name, lat, lon, note) VALUES (%s,%s,%s,%s)", [(x["city"], x["lat"], x["lon"], x.get("note")) for x in f["cities"]])
        cur.executemany("INSERT INTO okved (code, name) VALUES (%s,%s)", list(f["okved"].items()))
        cur.executemany("INSERT INTO okpd2 (code, name) VALUES (%s,%s)", list(f["okpd2"].items()))
        cur.executemany("INSERT INTO material (name) VALUES (%s)", [(x,) for x in f["materials"]])
        cur.executemany("INSERT INTO technology (name) VALUES (%s)", [(x,) for x in f["technologies"]])
        ids = sorted(f["companies"])
        for i in range(0, len(ids), BATCH):
            part = ids[i:i + BATCH]
            cat.save_companies(c, [f["companies"][x] for x in part], {x: f["sources"][x] for x in part}, {x: f["products"][x] for x in part})
            log(f"  предприятия: {min(i + BATCH, len(ids))} из {len(ids)}")
        cur.executemany("INSERT INTO relation (id, from_company, from_product, to_company, to_product, type, basis, pos) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
                        [(r["id"], r["from"], r.get("from_product"), r["to"], r.get("to_product"), r["type"], r["basis"], i)
                         for i, r in enumerate(f["relations"])])
        cat.bump_revision(c, "перенос из JSON")
        for name, doc in f["runs"].items():
            ingest.write_run(g, name, doc)
        for day, items in f["crawl"].items():
            ingest.write_crawl_log(g, day, items)
        if f["status"]:
            st = {k: v for k, v in f["status"].items() if k not in ("state", "stage", "done", "total", "daemon_at")}
            ingest.update_status(g, st, f["status"].get("updated_at") or "")
        c.commit(); g.commit()


def norm(v):
    """Пустые значения не различаются; числа сравниваются по значению. Суммы в JSON несли шум двоичной арифметики
    (1130848.8399999999): numeric в базе хранит точные копейки (1130848.84), поэтому дробные числа сравниваются до 6 знаков."""
    if isinstance(v, dict):
        return {k: norm(x) for k, x in v.items() if x not in (None, [], {}, "")}
    if isinstance(v, list):
        return [norm(x) for x in v]
    if isinstance(v, float):
        return round(v, 6)
    return v


def first_diff(a, b, path=""):
    if isinstance(a, dict) and isinstance(b, dict):
        for k in sorted(set(a) | set(b)):
            if a.get(k) != b.get(k):
                return first_diff(a.get(k), b.get(k), f"{path}.{k}")
    if isinstance(a, list) and isinstance(b, list) and len(a) == len(b):
        for i, (x, y) in enumerate(zip(a, b)):
            if x != y:
                return first_diff(x, y, f"{path}[{i}]")
    return f"{path}: файл {json.dumps(a, ensure_ascii=False)[:200]} ≠ база {json.dumps(b, ensure_ascii=False)[:200]}"


def verify(f: dict) -> list[str]:
    errors = []
    with connect("catalog") as c, connect("ingest") as g:
        comps, prods, srcs = cat.load_companies(c)
        dic = cat.load_dictionaries(c)
        if set(comps) != set(f["companies"]):
            errors.append(f"набор предприятий: в файлах {len(f['companies'])}, в базе {len(comps)}")
        for cid, c0 in f["companies"].items():
            if cid not in comps:
                continue
            for what, a, b in (("карточка", c0, comps[cid]), ("продукция", f["products"][cid], prods[cid]), ("источники", f["sources"][cid], srcs[cid])):
                if norm(a) != norm(b):
                    errors.append(f"{cid} ({what}) {first_diff(norm(a), norm(b))}")
        okved_needed = {x for x in f["okved"]}
        if {k: v for k, v in dic["okved"].items() if k in okved_needed} != f["okved"]:
            errors.append("справочник ОКВЭД расходится")
        extra_okved = sorted(set(dic["okved"]) - okved_needed)
        if extra_okved:
            errors.append(f"в карточках есть коды ОКВЭД вне справочника, заведены без названия: {', '.join(extra_okved)}")
        for key in ("okpd2", "materials", "technologies"):
            a, b = f[key], dic[key]
            if (sorted(a) if isinstance(a, list) else a) != (sorted(b) if isinstance(b, list) else b):
                errors.append(f"справочник {key} расходится")
        if {k: {**v, "pilot": bool(v.get("pilot"))} for k, v in f["regions"].items()} != dic["regions"]:
            errors.append("справочник регионов расходится")
        if norm(sorted(f["cities"], key=lambda x: x["city"])) != norm(dic["cities_full"]):
            errors.append("справочник городов расходится")
        if norm(f["relations"]) != norm(dic["relations"]):
            errors.append("связи предприятий расходятся")
        for name, doc in f["runs"].items():
            got = ingest.read_run(g, name)
            if norm(doc) != norm(got):
                errors.append(f"журнал сбора {name}: {first_diff(norm(doc), norm(got))}")
        want = [x for day in sorted(f["crawl"]) for x in f["crawl"][day]]
        if norm(want) != norm(ingest.read_crawl_log(g)):
            errors.append("журнал обхода расходится")
    return errors


def main(argv=None) -> int:
    global ARGS
    ap = argparse.ArgumentParser(prog="python tools/json_to_pg.py", description="Перенос базы из JSON в PostgreSQL")
    ap.add_argument("--data-dir", default=os.environ.get("PK_DATA_DIR", str(ROOT / "data")))
    ap.add_argument("--replace", action="store_true", help="очистить каталог и журналы сбора перед переносом")
    ap.add_argument("--verify-only", action="store_true")
    ap.add_argument("--if-empty", action="store_true", help="ничего не делать, если каталог в базе уже заполнен или файлов нет")
    ARGS = ap.parse_args(argv)
    data = Path(ARGS.data_dir)
    if ARGS.if_empty:
        with connect("catalog") as c:
            n = c.execute("SELECT count(*) AS n FROM company").fetchone()["n"]
        if n or not (data / "companies").is_dir():
            log(f"перенос не нужен: в базе {n} предприятий" if n else f"перенос не нужен: нет каталога {data / 'companies'}")
            return 0
    t0 = time.time()
    log(f"чтение {data}")
    f = load_files(data)
    log(f"  предприятий {len(f['companies'])}, позиций {sum(map(len, f['products'].values()))}, источников {sum(map(len, f['sources'].values()))}, "
        f"журналов сбора {len(f['runs'])}, журналов обхода {len(f['crawl'])}")
    for n in check_duplicates(data, f):
        log("  " + n)
    if not ARGS.verify_only:
        log("перенос в PostgreSQL")
        import_all(f)
    log("проверка: чтение из базы и сравнение с файлами")
    errors = verify(f)
    for e in errors[:50]:
        log("  ✗ " + e)
    real = [e for e in errors if not e.startswith("в карточках есть коды ОКВЭД")]
    log(("перенос проверен, расхождений нет" if not real else f"расхождений: {len(real)}") + f" ({time.time() - t0:.0f} с)")
    return 1 if real else 0


if __name__ == "__main__":
    sys.exit(main())
