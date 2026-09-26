"""Каталог предприятий для API: читается из базы sm01_catalog и держится в памяти сервера.

Подбор поставщиков сравнивает запрос с каждой карточкой, поэтому каталог (несколько тысяч карточек) удобнее держать
в памяти процесса API, а не в браузере. Когда сбор записал новые данные, ревизия каталога растёт — API замечает это
не позже чем через PK_REVISION_TTL секунд и перечитывает каталог. Поверх данных сбора накладываются решения
модератора из sm01_moderation: ручной статус проверки и отключённые источники.
"""
from __future__ import annotations
import math
import os
import threading
import time

from pkdb import connect
from pkdb import catalog as cat

REVISION_TTL = float(os.environ.get("PK_REVISION_TTL", "5"))


class DataRepo:
    def __init__(self):
        self.revision: int | None = None
        self.companies: dict[str, dict] = {}
        self.products: dict[str, dict] = {}
        self.sources: dict[str, dict] = {}
        self.reload()

    def reload(self):
        with connect("catalog") as c:
            rev = cat.revision(c)
            comps, prods, srcs = cat.load_companies(c)
            dic = cat.load_dictionaries(c)
        companies, products, sources = {}, {}, {}
        for cid, co in comps.items():
            co["products"], co["sources"] = prods[cid], srcs[cid]
            companies[cid] = co
            for p in co["products"]:
                products[p["id"]] = p
            for s in co["sources"]:
                sources[s["id"]] = {**s, "company_id": cid}
        self.companies, self.products, self.sources = companies, products, sources
        self.collected_status = {cid: c["verification_status"] for cid, c in companies.items()}   # статус по данным сбора, без решений модератора
        self.okved, self.okpd2, self.regions = dic["okved"], dic["okpd2"], dic["regions"]
        self.cities = {k: tuple(v) for k, v in dic["cities"].items()}
        self.relations = dic["relations"]
        self.dictionaries = dic
        self.revision = rev
        self.apply_moderation()
        self.checked_at = time.monotonic()

    def apply_moderation(self):
        """Ручные статусы проверки и отключённые источники из базы модерации (поверх данных сбора)."""
        for cid, c in self.companies.items():
            c["verification_status"] = self.collected_status[cid]
        for s in self.sources.values():
            s.pop("is_disabled", None)
        try:
            with connect("moderation") as m:
                overrides = m.execute("SELECT company_id, status FROM status_override").fetchall()
                flags = m.execute("SELECT source_id, disabled FROM source_flag").fetchall()
        except Exception:
            return   # база модерации недоступна: каталог работает по данным сбора
        for o in overrides:
            if o["company_id"] in self.companies:
                self.companies[o["company_id"]]["verification_status"] = o["status"]
        for f in flags:
            if f["source_id"] in self.sources and f["disabled"]:
                self.sources[f["source_id"]]["is_disabled"] = True

    def distance_km(self, a: str | None, b: str | None) -> int | None:
        if a not in self.cities or b not in self.cities:
            return None
        (la1, lo1), (la2, lo2) = self.cities[a], self.cities[b]
        r = math.radians
        h = math.sin(r(la2 - la1) / 2) ** 2 + math.cos(r(la1)) * math.cos(r(la2)) * math.sin(r(lo2 - lo1) / 2) ** 2
        return round(2 * 6371 * math.asin(math.sqrt(h)))


_repo: DataRepo | None = None
_lock = threading.Lock()


def get_repo() -> DataRepo:
    """Каталог; перечитывается, когда сбор записал новую ревизию (проверка не чаще раза в PK_REVISION_TTL секунд)."""
    global _repo
    with _lock:
        if _repo is None:
            _repo = DataRepo()
        elif time.monotonic() - _repo.checked_at > REVISION_TTL:
            with connect("catalog") as c:
                rev = cat.revision(c)
            if rev != _repo.revision:
                _repo.reload()
            else:
                _repo.checked_at = time.monotonic()
        return _repo


def drop_cache() -> None:
    """Сбросить каталог в памяти (тесты, смена базы)."""
    global _repo
    with _lock:
        _repo = None
