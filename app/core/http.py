"""Rate-limited HTTP session shared by all fetchers.

Each host gets its own BrowserSession which enforces a minimum delay between
requests (token-bucket style), sends browser-like headers, retries with
exponential backoff and can maintain cookies (needed for LeetCode).
"""
from __future__ import annotations

import logging
import threading
import time
from urllib.parse import urlparse

import requests

from .. import config

log = logging.getLogger("http")


class HostThrottle:
    def __init__(self, min_delay: float):
        self.min_delay = min_delay
        self._last = 0.0
        self._lock = threading.Lock()

    def wait(self) -> None:
        with self._lock:
            wait = self._last + self.min_delay - time.monotonic()
            if wait > 0:
                time.sleep(wait)
            self._last = time.monotonic()


class BrowserSession:
    def __init__(self, host: str, min_delay: float | None = None):
        self.host = host
        self.throttle = HostThrottle(min_delay or config.RATE_LIMITS.get(host, 1.5))
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": config.USER_AGENT,
            "Accept-Language": "en-US,en;q=0.9",
        })
        self.session.max_redirects = 20

    # ------------------------------------------------------------------
    def _full_url(self, path_or_url: str) -> str:
        if path_or_url.startswith("http"):
            return path_or_url
        return f"https://{self.host}{path_or_url if path_or_url.startswith('/') else '/' + path_or_url}"

    def get(self, path: str, *, referer: str | None = None,
            headers: dict | None = None, params: dict | None = None,
            allow_403: bool = False) -> tuple[int, str] | None:
        """Returns (status, text) or None when we gave up after retries/403=allowed."""
        url = self._full_url(path)
        hdrs = dict(headers or {})
        if referer:
            hdrs["Referer"] = referer
        for attempt in range(config.MAX_RETRIES + 1):
            self.throttle.wait()
            try:
                r = self.session.get(
                    url, params=params, headers=hdrs or None,
                    timeout=config.REQUEST_TIMEOUT, stream=False,
                )
                if r.status_code in (403, 429) and not allow_403 and attempt < config.MAX_RETRIES:
                    wait = 8 * (attempt + 1)
                    log.warning("host=%s status=%s retry in %ss (%s)",
                                self.host, r.status_code, wait, url)
                    time.sleep(wait)
                    continue
                try:
                    text = r.text
                except Exception:
                    text = ""
                return r.status_code, text
            except requests.RequestException as exc:
                if attempt >= config.MAX_RETRIES:
                    log.warning("host=%s error: %s url=%s", self.host, exc, url)
                    return None
                time.sleep(4 * (attempt + 1))
        return None

    def post_json(self, path: str, payload: dict, *, referer: str | None = None,
                  headers: dict | None = None) -> tuple[int, str] | None:
        url = self._full_url(path)
        hdrs = {"Content-Type": "application/json"}
        if referer:
            hdrs["Referer"] = referer
        hdrs.update(headers or {})
        for attempt in range(config.MAX_RETRIES + 1):
            self.throttle.wait()
            try:
                r = self.session.post(url, json=payload, headers=hdrs,
                                      timeout=config.REQUEST_TIMEOUT)
                if r.status_code in (403, 429) and attempt < config.MAX_RETRIES:
                    time.sleep(8 * (attempt + 1))
                    continue
                return r.status_code, r.text
            except requests.RequestException as exc:
                if attempt >= config.MAX_RETRIES:
                    log.warning("host=%s POST error: %s", self.host, exc)
                    return None
                time.sleep(4 * (attempt + 1))
        return None


class SessionHub:
    """One BrowserSession per host, shared across fetchers."""

    def __init__(self) -> None:
        self._sessions: dict[str, BrowserSession] = {}
        self._lock = threading.Lock()

    def for_url(self, url: str) -> BrowserSession:
        host = urlparse(url).netloc.split(":")[0]
        return self.for_host(host)

    def for_host(self, host: str) -> BrowserSession:
        with self._lock:
            if host not in self._sessions:
                self._sessions[host] = BrowserSession(host)
            return self._sessions[host]

    def cookie_jar_ready(self, host: str, warm_path: str) -> None:
        """Fetch a page to seed cookies (may 403 on CF, which is fine)."""
        s = self.for_host(host)
        s.get(warm_path, allow_403=True)


hub = SessionHub()