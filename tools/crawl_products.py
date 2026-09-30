"""Официальные сайты и позиции продукции по результатам обхода краулером (sm01_ingest: crawl_page, site_discovery).

  python tools/crawl_products.py auto [--since 7] [--companies ko,kzbi] [--review-out review.json] [--dry-run]
      всё, что краулер нашёл и подтвердил, — в каталог без ручной проверки:
      сайты, подтверждённые ИНН, ОГРН или названием с адресом из ЕГРЮЛ, — в карточку (поле «Сайт», источник «Официальный сайт»);
      позиции с решением accept (отдельная страница позиции в каталоге сайта) — в продукцию предприятия;
      у известных позиций, найденных на сайте, — новая дата проверки. Остальное (review, сайты с совпавшим только названием)
      — в файл --review-out для модератора.

Или в два шага, с проверкой модератором:

  python tools/crawl_products.py review [--out review.json] [--companies ko,kzbi] [--since 7]
      кандидаты: пункты меню каталога и карточки продукции, заголовки страниц разделов, позиции на страницах услуг.
      Отсеиваются навигация, новости, кнопки («Подробнее», «Скачать»), ссылки-фильтры на ту же страницу.
      Каждому кандидату — решение accept/reject/review с причиной; уже известные позиции сопоставляются по названию.
  python tools/crawl_products.py apply review.json
      одобренные (accept) позиции записываются в sm01_catalog: источник — страница официального сайта, где позиция
      опубликована; код ОКПД2 — только класс по словарю, со статусом INFERRED («присвоено, требует подтверждения»).
      У известных позиций, найденных на сайте, обновляется дата проверки; у источников сайта — результат обхода.

Принцип платформы: ничего не дополняется «по памяти». Название позиции — дословно со страницы, у позиции — ссылка
на страницу-источник; характеристики — только из таблиц этой страницы.
"""
from __future__ import annotations
import argparse
import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))

from pkdb import connect  # noqa: E402
from sync import sitecrawl  # noqa: E402
from sync.sitecrawl import apply_report, build_report, load_pages, okpd2_names  # noqa: E402
from sync.store import Store  # noqa: E402


def cmd_review(args):
    only = set(args.companies.split(",")) if args.companies else None
    pages = load_pages(args.since, only)
    with connect("catalog") as c:
        from pkdb import catalog as cat
        comps, prods, _ = cat.load_companies(c, list(pages))
    report = build_report(pages, comps, prods)
    Path(args.out).write_text(json.dumps(report, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    print(f"\nфайл на проверку: {args.out}  (decision: accept — записать, reject — нет, review — решить вручную)")


def cmd_apply(args):
    report = json.loads(Path(args.file).read_text(encoding="utf-8"))
    pages_all = load_pages(args.since, {r["company_id"] for r in report})
    st = Store(readonly=args.dry_run)
    st.load([r["company_id"] for r in report])
    total_new = apply_report(st, report, pages_all, okpd2_names(), date.today().isoformat())
    if args.dry_run:
        print(f"\nпроверка без записи: новых позиций {total_new}")
        return
    rev = st.save(f"продукция с официальных сайтов: +{total_new}")
    print(f"\nзаписано: новых позиций {total_new}, ревизия каталога {rev}")


def cmd_auto(args):
    only = set(args.companies.split(",")) if args.companies else None
    st = Store(readonly=args.dry_run)
    res = sitecrawl.apply_new(st, date.today().isoformat(), window_days=args.since, only=only)
    print(f"сайты: подтверждено краулером {res['confirmed']}, записано в карточки {len(res['sites'])}, "
          f"на решение модератора {len(res['candidate_sites'])}")
    if args.review_out:
        Path(args.review_out).write_text(json.dumps({"sites": res["candidate_sites"], "products": res["review"]}, ensure_ascii=False, indent=1,
                                                    default=str), encoding="utf-8")
        print(f"на проверку модератору: сайтов {len(res['candidate_sites'])}, позиций {sum(len(r['candidates']) for r in res['review'])} — {args.review_out}")
    if args.dry_run:
        print(f"проверка без записи: сайтов {len(res['sites'])}, новых позиций {res['products']}")
        return
    rev = st.save(f"краулер: сайтов +{len(res['sites'])}, позиций +{res['products']}")
    print(f"записано: сайтов {len(res['sites'])}, новых позиций {res['products']}, ревизия каталога {rev}")


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python tools/crawl_products.py")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("review", help="кандидаты в позиции продукции на проверку")
    r.add_argument("--out", default="crawl_review.json")
    r.add_argument("--companies")
    r.add_argument("--since", type=int, default=7, help="страницы обхода за последние N дней")
    a = sub.add_parser("apply", help="записать одобренные позиции в каталог")
    a.add_argument("file")
    a.add_argument("--since", type=int, default=7)
    a.add_argument("--dry-run", action="store_true")
    u = sub.add_parser("auto", help="найденные краулером сайты и позиции — в каталог без ручной проверки")
    u.add_argument("--since", type=int, default=7, help="страницы обхода за последние N дней")
    u.add_argument("--companies")
    u.add_argument("--review-out", help="файл для модератора: сайты с совпавшим только названием и позиции review")
    u.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)
    {"review": cmd_review, "apply": cmd_apply, "auto": cmd_auto}[args.cmd](args)


if __name__ == "__main__":
    main()
