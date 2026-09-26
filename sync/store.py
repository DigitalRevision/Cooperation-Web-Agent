"""Каталог предприятий для сбора: чтение и запись базы sm01_catalog (PostgreSQL), журнал запуска в sm01_ingest.

Карточки загружаются в память в прежнем виде (словари company.json, списки продукции и источников), правила слияния
(merge.py) меняют их, а save() записывает изменённые карточки одной транзакцией и увеличивает ревизию каталога:
по ней API понимает, что данные обновились. Ничего не удаляет; продукция, заведённая вручную, при сверке не трогается.
"""
from __future__ import annotations
import re

from pkdb import connect
from pkdb import catalog as cat
from pkdb import ingest

TRANSLIT = dict(zip("абвгдеёжзийклмнопрстуфхцчшщъыьэюя",
                    ["a", "b", "v", "g", "d", "e", "e", "zh", "z", "i", "y", "k", "l", "m", "n", "o", "p", "r", "s", "t", "u", "f",
                     "h", "ts", "ch", "sh", "sch", "", "y", "", "e", "yu", "ya"]))


def slug(name: str) -> str:
    s = "".join(TRANSLIT.get(ch, ch) for ch in name.lower())
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return s[:40].strip("-") or "company"


class Store:
    def __init__(self):
        with connect("catalog") as c:
            self.companies, self.products, self.sources = cat.load_companies(c)
            dic = cat.load_dictionaries(c)
        self.okved: dict[str, str | None] = dic["okved"]
        self.okpd2: dict[str, str | None] = dic["okpd2"]
        self.regions: dict[str, dict] = dic["regions"]
        self.dirty: set[str] = set()
        self.new: set[str] = set()
        self.products_dirty: set[str] = set()   # у предприятия изменилась продукция (например, по реестру МСП)
        self._okved0, self._regions0, self._okpd20 = dict(self.okved), {k: dict(v) for k, v in self.regions.items()}, dict(self.okpd2)

    def by_inn(self) -> dict[str, str]:
        return {c["inn"]: cid for cid, c in self.companies.items() if c.get("inn")}

    def new_id(self, short: str) -> str:
        base = slug(re.sub(r"[«»\"]", "", short))
        cid, n = base, 2
        while cid in self.companies:
            cid, n = f"{base}-{n}", n + 1
        return cid

    def add(self, company: dict, sources: list[dict]):
        cid = company["id"]
        self.companies[cid], self.products[cid], self.sources[cid] = company, [], sources
        self.dirty.add(cid)
        self.new.add(cid)

    def save(self, note: str | None = None) -> int | None:
        """Записать изменённые карточки и справочники одной транзакцией. Возвращает новую ревизию каталога."""
        okved_changed = {k: v for k, v in self.okved.items() if self._okved0.get(k, ...) != v}
        regions_changed = {k: v for k, v in self.regions.items() if self._regions0.get(k) != v}
        okpd2_changed = {k: v for k, v in self.okpd2.items() if self._okpd20.get(k, ...) != v}
        if not (self.dirty or okved_changed or regions_changed or okpd2_changed):
            return None
        ids = sorted(self.dirty)
        with connect("catalog") as c:
            if okved_changed:
                cat.save_okved(c, okved_changed)
            if regions_changed:
                cat.save_regions(c, regions_changed)
            if okpd2_changed:
                cat.save_okpd2(c, okpd2_changed)
            for i in range(0, len(ids), 500):
                part = ids[i:i + 500]
                cat.save_companies(c, [self.companies[x] for x in part], {x: self.sources[x] for x in part},
                                   {x: self.products[x] for x in part if x in self.new or x in self.products_dirty})
            rev = cat.bump_revision(c, note)
            c.commit()
        self.dirty.clear()
        self.new.clear()
        self.products_dirty.clear()
        self._okved0, self._regions0, self._okpd20 = dict(self.okved), {k: dict(v) for k, v in self.regions.items()}, dict(self.okpd2)
        return rev

    def write_log(self, name: str, log: dict):
        with connect("ingest") as g:
            ingest.write_run(g, name, log)
            g.commit()
