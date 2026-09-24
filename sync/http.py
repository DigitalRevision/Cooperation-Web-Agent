"""HTTP-клиент с паузой между запросами к одному сайту, повторами и остановкой источника после серии ошибок."""
from __future__ import annotations
import threading
import time
from urllib.parse import urlsplit

import httpx

from . import config


class SourceError(Exception):
    """Источник не ответил или ответил не так, как ожидалось (капча, HTML вместо JSON, 4xx/5xx)."""


class Http:
    def __init__(self, delay: float = config.DELAY, retries: int = config.RETRIES, client: httpx.Client | None = None):
        self.delay = delay
        self.retries = retries
        self.client = client or httpx.Client(timeout=config.TIMEOUT, follow_redirects=True,
                                             headers={"User-Agent": config.USER_AGENT, "Accept": "application/json, text/plain, */*"})
        self._last: dict[str, float] = {}
        self._locks: dict[str, threading.Lock] = {}
        self._guard = threading.Lock()
        self.fails: dict[str, int] = {}   # подряд идущие ошибки по сайту
        self.requests = 0

    def _wait(self, host: str):
        with self._guard:
            lock = self._locks.setdefault(host, threading.Lock())
        lock.acquire()
        pause = self._last.get(host, 0) + max(self.delay, config.HOST_DELAY.get(host, 0)) - time.monotonic()
        if pause > 0:
            time.sleep(pause)
        return lock

    def request(self, method: str, url: str, **kw) -> httpx.Response:
        host = urlsplit(url).hostname or ""
        if self.fails.get(host, 0) >= 5:
            raise SourceError(f"{host}: источник отключён до следующего запуска после 5 ошибок подряд")
        err = None
        for attempt in range(self.retries):
            lock = self._wait(host)
            try:
                r = self.client.request(method, url, **kw)
                self.requests += 1
            except httpx.HTTPError as e:
                err = SourceError(f"{host}: {type(e).__name__}")
                r = None
            finally:
                self._last[host] = time.monotonic()
                lock.release()
            if r is not None and r.status_code < 400:
                self.fails[host] = 0
                return r
            if r is not None and "captcha" in r.text[:500].lower():
                # сайт ФНС попросил ввести цифры с картинки: до конца запуска к нему не обращаемся
                self.fails[host] = 5
                raise SourceError(f"{host}: требуется капча, источник отложен до следующего запуска")
            if r is not None:
                err = SourceError(f"{host}: HTTP {r.status_code}")
                if r.status_code not in (429, 500, 502, 503, 504):
                    break
            time.sleep(2 ** attempt)
        self.fails[host] = self.fails.get(host, 0) + 1
        raise err

    def json(self, method: str, url: str, **kw):
        r = self.request(method, url, **kw)
        try:
            data = r.json()
        except ValueError:
            raise SourceError(f"{urlsplit(url).hostname}: ответ не JSON (возможно, капча или защита от ботов)")
        if isinstance(data, dict) and data.get("captchaRequired"):
            self.fails[urlsplit(url).hostname or ""] = 5
            raise SourceError(f"{urlsplit(url).hostname}: требуется капча, источник отложен до следующего запуска")
        return data

    def blocked(self, url: str) -> bool:
        return self.fails.get(urlsplit(url).hostname or "", 0) >= 5
