"""Проверка реквизитов по контрольным суммам (алгоритмы ФНС для ИНН и ОГРН, Росстата для ОКПО).

Те же алгоритмы работают на сайте (site/src/01-core.js), чтобы ошибка ловилась ещё до отправки формы.
"""
import re


def _digits(s: str) -> list[int]:
    return [int(ch) for ch in s]


def inn_ok(s: str) -> bool:
    if not re.fullmatch(r"\d{10}|\d{12}", s or ""):
        return False
    n = _digits(s)

    def cs(w):
        return sum(a * b for a, b in zip(w, n)) % 11 % 10

    if len(s) == 10:
        return cs([2, 4, 10, 3, 5, 9, 4, 6, 8]) == n[9]
    return cs([7, 2, 4, 10, 3, 5, 9, 4, 6, 8]) == n[10] and cs([3, 7, 2, 4, 10, 3, 5, 9, 4, 6, 8]) == n[11]


def ogrn_ok(s: str) -> bool:
    if re.fullmatch(r"\d{13}", s or ""):
        return int(s[:12]) % 11 % 10 == int(s[12])
    if re.fullmatch(r"\d{15}", s or ""):
        return int(s[:14]) % 13 % 10 == int(s[14])
    return False


def kpp_ok(s: str) -> bool:
    return bool(re.fullmatch(r"\d{4}[\dA-Z]{2}\d{3}", s or ""))


def okpo_ok(s: str) -> bool:
    if not re.fullmatch(r"\d{8}|\d{10}", s or ""):
        return False
    n = _digits(s)
    body = n[:-1]

    def total(shift):
        return sum(x * ((i + shift) % 10 + 1) for i, x in enumerate(body)) % 11

    c = total(0)
    if c == 10:
        c = total(2)
        if c == 10:
            c = 0
    return c == n[-1]
