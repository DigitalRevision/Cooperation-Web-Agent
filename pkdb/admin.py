"""Администрирование пользователей платформы.

  python -m pkdb.admin set-role <id пользователя> moderator   # роли: user, company_admin, moderator, admin
  python -m pkdb.admin users [--role moderator]               # список пользователей (без персональных данных)

Id пользователя виден в личном кабинете и в списке регистраций у модератора.
"""
from __future__ import annotations
import argparse
import sys

from .db import connect

ROLES = ("user", "company_admin", "moderator", "admin")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m pkdb.admin")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("set-role", help="назначить роль пользователю")
    r.add_argument("user_id")
    r.add_argument("role", choices=ROLES)
    u = sub.add_parser("users", help="список пользователей")
    u.add_argument("--role", choices=ROLES)
    args = ap.parse_args(argv)
    with connect("accounts") as c:
        if args.cmd == "set-role":
            n = c.execute("UPDATE app_user SET role = %s WHERE id = %s AND kind <> 'staff'", (args.role, args.user_id)).rowcount
            c.commit()
            print(f"{args.user_id}: роль {args.role}" if n else f"пользователь {args.user_id} не найден")
            return 0 if n else 1
        q = "SELECT id, role, kind, created_at, last_seen_at FROM app_user" + (" WHERE role = %s" if args.role else "") + " ORDER BY created_at"
        for row in c.execute(q, (args.role,) if args.role else ()):
            print(f"{row['id']}\t{row['role']}\t{row['kind']}\t{row['created_at']:%Y-%m-%d %H:%M}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
