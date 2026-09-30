"""Каталог предприятий для сбора: чтение и запись базы sm01_catalog (PostgreSQL), журнал запуска в sm01_ingest.

По всей стране в базе больше 150 тысяч карточек — все сразу в память сервера на 2 ГБ не помещаются. Поэтому хранилище держит
лёгкий индекс всех предприятий (id → ИНН, дата сверки с реестрами, сайт, есть ли продукция из реестров Минпромторга и МСП),
а карточки загружает порциями — только те, что сейчас проверяются (load), и выгружает после записи (flush, unload).
Карточки — в прежнем виде (словари company.json, списки продукции и источников): правила слияния (merge.py) меняют их,
а save() записывает изменённые карточки одной транзакцией и увеличивает ревизию каталога: по ней API понимает, что данные
обновились. Промежуточные записи порций (flush) ревизию не увеличивают — API перечитает каталог один раз, в конце сбора.
Ничего не удаляет; продукция, заведённая вручную, при сверке не трогается.
"""
from __future__ import annotations
import re

from psycopg.rows import tuple_row

from pkdb import connect
from pkdb import catalog as cat
from pkdb import ingest

TRANSLIT = dict(zip("абвгдеёжзийклмнопрстуфхцчшщъыьэюя",
                    ["a", "b", "v", "g", "d", "e", "e", "zh", "z", "i", "y", "k", "l", "m", "n", "o", "p", "r", "s", "t", "u", "f",
                     "h", "ts", "ch", "sh", "sch", "", "y", "", "e", "yu", "ya"]))
CHUNK = 1000        # карточек за один запрос загрузки
FLUSH_AT = 2000     # изменённых карточек в памяти, после которых flush() пишет их в базу

# строка индекса: ИНН, дата сверки с реестрами (registry.checked_at), сайт, есть источник Минпромторга, есть источник реестра МСП
I_INN, I_CHECKED, I_SITE, I_MINPROM, I_RMSP = range(5)
INDEX_SQL = """SELECT c.id, c.inn, r.checked_at::text, c.site, mp.company_id IS NOT NULL, rm.company_id IS NOT NULL
               FROM company c LEFT JOIN company_registry r ON r.company_id = c.id
               LEFT JOIN source mp ON mp.id = c.id || '-minprom' LEFT JOIN source rm ON rm.id = c.id || '-rmsp'"""


class _Loaded(dict):
    """Загруженные карточки (продукция, источники) — как словарь всего каталога: «in» и get видят все предприятия базы,
    обращение к ещё не загруженному загружает его. Перебор (items, values, len) — только загруженные."""
    def __init__(self, store: "Store"):
        super().__init__()
        self._store = store

    def __missing__(self, cid):
        self._store.load([cid])
        if dict.__contains__(self, cid):
            return dict.__getitem__(self, cid)
        raise KeyError(cid)

    def __contains__(self, cid):
        return dict.__contains__(self, cid) or cid in self._store.index

    def get(self, cid, default=None):
        return self[cid] if cid in self else default


def slug(name: str) -> str:
    s = "".join(TRANSLIT.get(ch, ch) for ch in name.lower())
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return s[:40].strip("-") or "company"


class Store:
    def __init__(self, readonly: bool = False):
        """readonly — проверка без записи (dry-run): flush ничего не пишет, карточки остаются в памяти."""
        with connect("catalog") as c:
            self.index: dict[str, tuple] = {r[0]: r[1:] for r in c.cursor(row_factory=tuple_row).execute(INDEX_SQL)}
            dic = cat.load_dictionaries(c)
        self.readonly = readonly
        self.companies: dict[str, dict] = _Loaded(self)    # загруженные карточки (load)
        self.products: dict[str, list] = _Loaded(self)
        self.sources: dict[str, list] = _Loaded(self)
        self.okved: dict[str, str | None] = dic["okved"]
        self.okpd2: dict[str, str | None] = dic["okpd2"]
        self.regions: dict[str, dict] = dic["regions"]
        self.dirty: set[str] = set()
        self.new: set[str] = set()
        self.products_dirty: set[str] = set()   # у предприятия изменилась продукция (например, по реестру МСП)
        self.pending = False                    # записано без увеличения ревизии каталога (flush)
        self._product_ids: set[str] | None = None
        self._okved0, self._regions0, self._okpd20 = dict(self.okved), {k: dict(v) for k, v in self.regions.items()}, dict(self.okpd2)

    # ---------- индекс и загрузка карточек ----------
    def exists(self, cid: str) -> bool:
        return cid in self.index

    def ids(self) -> list[str]:
        return list(self.index)

    def inn(self, cid: str) -> str | None:
        return self.index[cid][I_INN]

    def site(self, cid: str) -> str | None:
        c = dict.get(self.companies, cid)   # загруженная карточка (могла измениться) или индекс; без загрузки
        return c.get("site") if c else (self.index.get(cid) or (None,) * 5)[I_SITE]

    def by_inn(self) -> dict[str, str]:
        return {v[I_INN]: cid for cid, v in self.index.items() if v[I_INN]}

    def load(self, ids) -> None:
        """Загрузить карточки (с продукцией и источниками), которых ещё нет в памяти."""
        todo = [i for i in dict.fromkeys(ids) if not dict.__contains__(self.companies, i) and i in self.index]
        if not todo:
            return
        with connect("catalog") as c:
            for k in range(0, len(todo), CHUNK):
                comps, prods, srcs = cat.load_companies(c, todo[k:k + CHUNK])
                for cid, co in comps.items():
                    self.companies[cid], self.products[cid], self.sources[cid] = co, prods[cid], srcs[cid]

    def unload(self, ids=None) -> None:
        """Выгрузить из памяти карточки без несохранённых изменений (все загруженные, если ids не задан)."""
        for cid in list(self.companies if ids is None else ids):
            if cid not in self.dirty and cid not in self.new:
                self.companies.pop(cid, None)
                self.products.pop(cid, None)
                self.sources.pop(cid, None)

    def flush(self, force: bool = False) -> None:
        """Изменённые карточки — в базу без увеличения ревизии (когда их накопилось FLUSH_AT или force), остальные — из памяти."""
        if self.readonly or not (force or len(self.dirty) >= FLUSH_AT):
            return
        self.save(bump=False)
        self.unload()

    def product_ids(self) -> set[str]:
        """id всех позиций продукции каталога (новой позиции нужен id, которого ещё нет)."""
        if self._product_ids is None:
            with connect("catalog") as c:
                self._product_ids = {r[0] for r in c.cursor(row_factory=tuple_row).execute("SELECT id FROM product")}
        return self._product_ids | {p["id"] for lst in self.products.values() for p in lst}

    def new_id(self, short: str) -> str:
        base = slug(re.sub(r"[«»\"]", "", short))
        cid, n = base, 2
        while cid in self.companies:   # весь каталог и добавленные в этом проходе (_Loaded)
            cid, n = f"{base}-{n}", n + 1
        return cid

    def add(self, company: dict, sources: list[dict]):
        cid = company["id"]
        self.companies[cid], self.products[cid], self.sources[cid] = company, [], sources
        self.index[cid] = (company.get("inn"), None, company.get("site"), False, False)
        self.dirty.add(cid)
        self.new.add(cid)

    # ---------- запись ----------
    def save(self, note: str | None = None, bump: bool = True) -> int | None:
        """Записать изменённые карточки и справочники одной транзакцией. bump — увеличить ревизию каталога (в том числе за
        прежние flush); возвращает новую ревизию."""
        okved_changed = {k: v for k, v in self.okved.items() if self._okved0.get(k, ...) != v}
        regions_changed = {k: v for k, v in self.regions.items() if self._regions0.get(k) != v}
        okpd2_changed = {k: v for k, v in self.okpd2.items() if self._okpd20.get(k, ...) != v}
        if not (self.dirty or okved_changed or regions_changed or okpd2_changed):
            if bump and self.pending:
                with connect("catalog") as c:
                    rev = cat.bump_revision(c, note)
                    c.commit()
                self.pending = False
                return rev
            return None
        ids = sorted(self.dirty)
        rev = None
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
            if bump:
                rev = cat.bump_revision(c, note)
            c.commit()
        self.pending = not bump
        for cid in ids:   # индекс — по записанным карточкам: следующие этапы сбора видят новые даты сверки, сайты и источники
            co, srcs = self.companies[cid], self.sources[cid]
            self.index[cid] = (co.get("inn"), (co.get("registry") or {}).get("checked_at"), co.get("site"),
                               any(s["id"] == f"{cid}-minprom" for s in srcs), any(s["id"] == f"{cid}-rmsp" for s in srcs))
        if self._product_ids is not None:
            self._product_ids |= {p["id"] for x in ids for p in self.products[x]}
        self.dirty.clear()
        self.new.clear()
        self.products_dirty.clear()
        self._okved0, self._regions0, self._okpd20 = dict(self.okved), {k: dict(v) for k, v in self.regions.items()}, dict(self.okpd2)
        return rev

    def write_log(self, name: str, log: dict):
        with connect("ingest") as g:
            ingest.write_run(g, name, log)
            g.commit()
