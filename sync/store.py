"""Чтение и запись Git-репозитория данных (data/) и сборка бандла сайта site/data.json.

В отличие от seed-скриптов, ничего не удаляет: перезаписываются только изменённые компании и справочники.
"""
from __future__ import annotations
import glob
import json
import os
import re
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = Path(os.environ.get("PK_DATA_DIR", ROOT / "data"))
SITE = ROOT / "site"

TRANSLIT = dict(zip("абвгдеёжзийклмнопрстуфхцчшщъыьэюя",
                    ["a", "b", "v", "g", "d", "e", "e", "zh", "z", "i", "y", "k", "l", "m", "n", "o", "p", "r", "s", "t", "u", "f",
                     "h", "ts", "ch", "sh", "sch", "", "y", "", "e", "yu", "ya"]))


def _read(p: Path):
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def _write(p: Path, obj, compact: bool = False):
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        if compact:
            json.dump(obj, f, ensure_ascii=False, separators=(",", ":"))
        else:
            json.dump(obj, f, ensure_ascii=False, indent=2)
    os.replace(tmp, p)


def slug(name: str) -> str:
    s = "".join(TRANSLIT.get(ch, ch) for ch in name.lower())
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return s[:40].strip("-") or "company"


class Store:
    def __init__(self, data: Path = DATA, site: Path = SITE):
        self.data, self.site = Path(data), Path(site)
        self.companies: dict[str, dict] = {}   # id → company.json
        self.products: dict[str, list] = {}
        self.sources: dict[str, list] = {}
        self.dirty: set[str] = set()
        for d in sorted((self.data / "companies").iterdir()):
            if (d / "company.json").exists():
                c = _read(d / "company.json")
                self.companies[c["id"]] = c
                self.products[c["id"]] = _read(d / "products.json") if (d / "products.json").exists() else []
                self.sources[c["id"]] = _read(d / "sources.json") if (d / "sources.json").exists() else []
        self.okved = {x["code"]: x["name"] for x in _read(self.data / "okved/okved.json")}
        self.regions = {x["code"]: x for x in _read(self.data / "regions/regions.json")}
        self._okved0, self._regions0 = dict(self.okved), dict(self.regions)

    def by_inn(self) -> dict[str, str]:
        return {c["inn"]: cid for cid, c in self.companies.items() if c.get("inn")}

    def new_id(self, short: str) -> str:
        base = slug(re.sub(r"[«»\"]", "", short))
        cid, n = base, 2
        while cid in self.companies or (self.data / "companies" / cid).exists():
            cid, n = f"{base}-{n}", n + 1
        return cid

    def add(self, company: dict, sources: list[dict]):
        cid = company["id"]
        self.companies[cid], self.products[cid], self.sources[cid] = company, [], sources
        self.dirty.add(cid)

    def save(self):
        for cid in sorted(self.dirty):
            d = self.data / "companies" / cid
            _write(d / "company.json", self.companies[cid])
            _write(d / "sources.json", self.sources[cid])
            if not (d / "products.json").exists():
                _write(d / "products.json", self.products[cid])
        if self.okved != self._okved0:
            _write(self.data / "okved/okved.json", [{"code": k, "name": v} for k, v in sorted(self.okved.items(), key=lambda kv: [int(x) for x in kv[0].split(".")])])
        if self.regions != self._regions0:
            _write(self.data / "regions/regions.json", sorted(self.regions.values(), key=lambda r: (not r.get("pilot"), r["code"])))
        if self.dirty:
            allsrc = [dict(s, company_id=cid) for cid in sorted(self.companies) for s in self.sources[cid]]
            _write(self.data / "sources/sources.json", allsrc)
        self.dirty.clear()

    def bundle(self, generated_at: str, sync_summary: dict | None = None) -> dict:
        """Единый файл для фронтенда в формате seed-скриптов. Порядок компаний сохраняется, новые идут в конец."""
        try:
            order = [c["id"] for c in _read(self.site / "data.json")["companies"]]
        except (OSError, ValueError, KeyError):
            order = []
        pos = {cid: i for i, cid in enumerate(order)}
        comps = []
        for cid in sorted(self.companies, key=lambda x: (pos.get(x, len(pos)), self.companies[x].get("added_at", ""), x)):
            c = dict(self.companies[cid])
            c["sources"] = self.sources[cid]
            c["products"] = [{k: v for k, v in p.items() if k != "company_id"} for p in self.products[cid]]
            comps.append(c)
        crawl = []
        for p in sorted(glob.glob(str(self.data / "sources/crawl_log_*.json"))):
            crawl += _read(Path(p))
        b = {"generated_at": generated_at, "companies": comps, "okved": self.okved,
             "okpd2": {x["code"]: x["name"] for x in _read(self.data / "okpd2/okpd2.json")},
             "regions": self.regions,
             "cities": {x["city"]: [x["lat"], x["lon"]] for x in _read(self.data / "regions/cities.json")},
             "relations": _read(self.data / "relations/relations.json"), "crawl_log": crawl}
        if sync_summary:
            b["sync"] = sync_summary
        return b

    def write_bundle(self, generated_at: str, sync_summary: dict | None = None) -> Path:
        out = self.site / "data.json"
        # бандл для браузера без отступов: при тысячах компаний это треть размера
        _write(out, self.bundle(generated_at, sync_summary), compact=True)
        if (self.site / "dist").is_dir():
            shutil.copy(out, self.site / "dist" / "data.json")
        return out

    def write_log(self, name: str, log: dict):
        _write(self.data / "sync" / f"{name}.json", log)
        _write(self.data / "sync" / "latest.json", log)
