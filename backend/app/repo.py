"""Доступ к Git-репозиторию данных (data/). В продуктиве тот же интерфейс читает PostgreSQL (см. sql/schema.sql, tools/load_to_postgres.py)."""
from __future__ import annotations
import json, math, os, subprocess
from functools import lru_cache
from pathlib import Path

DATA_DIR = Path(os.environ.get("PK_DATA_DIR", Path(__file__).resolve().parents[2] / "data"))


def _read(p: Path):
    with open(p, encoding="utf-8") as f:
        return json.load(f)


class DataRepo:
    def __init__(self, root: Path = DATA_DIR):
        self.root = root
        self.reload()

    def reload(self):
        self.companies: dict[str, dict] = {}
        self.products: dict[str, dict] = {}
        self.sources: dict[str, dict] = {}
        for d in sorted((self.root / "companies").iterdir()):
            c = _read(d / "company.json")
            c["products"] = _read(d / "products.json")
            c["sources"] = _read(d / "sources.json")
            self.companies[c["id"]] = c
            for p in c["products"]:
                self.products[p["id"]] = p
            for s in c["sources"]:
                self.sources[s["id"]] = {**s, "company_id": c["id"]}
        self.okved = {x["code"]: x["name"] for x in _read(self.root / "okved/okved.json")}
        self.okpd2 = {x["code"]: x["name"] for x in _read(self.root / "okpd2/okpd2.json")}
        self.regions = {x["code"]: x for x in _read(self.root / "regions/regions.json")}
        self.cities = {x["city"]: (x["lat"], x["lon"]) for x in _read(self.root / "regions/cities.json")}
        self.relations = _read(self.root / "relations/relations.json")
        self.revision = self._git_rev()

    def _git_rev(self) -> str | None:
        try:
            return subprocess.check_output(["git", "-C", str(self.root), "rev-parse", "--short", "HEAD"], text=True, stderr=subprocess.DEVNULL).strip()
        except Exception:
            return None

    def distance_km(self, a: str | None, b: str | None) -> int | None:
        if a not in self.cities or b not in self.cities:
            return None
        (la1, lo1), (la2, lo2) = self.cities[a], self.cities[b]
        r = math.radians
        h = math.sin(r(la2 - la1) / 2) ** 2 + math.cos(r(la1)) * math.cos(r(la2)) * math.sin(r(lo2 - lo1) / 2) ** 2
        return round(2 * 6371 * math.asin(math.sqrt(h)))


@lru_cache
def get_repo() -> DataRepo:
    return DataRepo()
