"""Начальный набор каталога для новой установки: 28 предприятий первичного сбора (исследование 24.09.2026 и участники
регионального отделения) с продукцией, источниками и справочниками.

Это фиксированные исходные данные, как миграция схемы: работающая платформа их не меняет и в Git ничего не записывает.
Загружаются только в пустой каталог; остальное добавляет ежедневный сбор из реестров.

  python -m pkdb.seed            # загрузить, если каталог пуст
"""

from __future__ import annotations

import json
from pathlib import Path

from .. import catalog as cat
from ..db import connect

SEED = Path(__file__).parent / "catalog_seed.json"
CATALOG_TABLES = (
    "product_material, product_param, product, source, company_history, company_finance, company_registry, "
    "company_risk_signal, company_discrepancy_value, company_discrepancy, company_capability, company_site, company_certificate, "
    "company_capacity, company_material, company_technology, company_okved, company, city, region, okved, okpd2, material, technology"
)


def load(replace: bool = False) -> int:
    """Загрузить начальный набор. Без replace — только в пустой каталог. Возвращает число загруженных предприятий."""
    f = json.loads(SEED.read_text(encoding="utf-8"))
    with connect("catalog") as c:
        if replace:
            c.execute(f"TRUNCATE {CATALOG_TABLES}")
        elif c.execute("SELECT count(*) AS n FROM company").fetchone()["n"]:
            return 0
        cur = c.cursor()
        cur.executemany(
            "INSERT INTO region (code, name, is_pilot) VALUES (%s,%s,%s) ON CONFLICT DO NOTHING",
            [(r["code"], r["name"], bool(r.get("pilot"))) for r in f["regions"]],
        )
        cur.executemany(
            "INSERT INTO city (name, lat, lon, note) VALUES (%s,%s,%s,%s) ON CONFLICT DO NOTHING",
            [(x["city"], x["lat"], x["lon"], x.get("note")) for x in f["cities"]],
        )
        cur.executemany(
            "INSERT INTO okved (code, name) VALUES (%s,%s) ON CONFLICT DO NOTHING",
            [(x["code"], x["name"]) for x in f["okved"]],
        )
        cur.executemany(
            "INSERT INTO okpd2 (code, name) VALUES (%s,%s) ON CONFLICT DO NOTHING",
            [(x["code"], x["name"]) for x in f["okpd2"]],
        )
        cur.executemany(
            "INSERT INTO material (name) VALUES (%s) ON CONFLICT DO NOTHING",
            [(x,) for x in f["materials"]],
        )
        cur.executemany(
            "INSERT INTO technology (name) VALUES (%s) ON CONFLICT DO NOTHING",
            [(x,) for x in f["technologies"]],
        )
        items = f["companies"]
        cat.save_companies(
            c,
            [x["company"] for x in items],
            {x["company"]["id"]: x["sources"] for x in items},
            {x["company"]["id"]: x["products"] for x in items},
        )
        cat.bump_revision(c, "начальный набор каталога")
        c.commit()
    return len(items)
