"""Small HTTP layer: timeouts, bounded retries, and error messages that never leak URLs or keys."""

from __future__ import annotations

import logging
import time
from typing import Any, Callable, Optional

import httpx

from .models import ProviderError

log = logging.getLogger(__name__)

USER_AGENT = "Jobwise/1.0 (desktop job search; contact: see application settings)"
_RETRY_STATUS = {429, 500, 502, 503, 504}


class HttpClient:
    def __init__(
        self,
        transport: Optional[httpx.BaseTransport] = None,
        timeout: float = 20.0,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self._client = httpx.Client(
            transport=transport,
            timeout=timeout,
            follow_redirects=True,
            headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
        )
        self._sleep = sleep

    def close(self) -> None:
        self._client.close()

    def request_json(
        self,
        method: str,
        url: str,
        *,
        label: str,
        params: Optional[dict[str, Any]] = None,
        headers: Optional[dict[str, str]] = None,
        json: Any = None,
        auth: Optional[tuple[str, str]] = None,
        retries: int = 2,
    ) -> Any:
        """Return parsed JSON or raise ProviderError. ``label`` is the provider's display name."""
        resp: Optional[httpx.Response] = None
        for attempt in range(retries + 1):
            try:
                resp = self._client.request(method, url, params=params, headers=headers, json=json, auth=auth)
            except httpx.TimeoutException as exc:
                if attempt < retries:
                    self._sleep(1.0 + attempt)
                    continue
                raise ProviderError(f"{label} took too long to respond.") from exc
            except httpx.HTTPError as exc:  # connection errors, DNS, TLS ...
                if attempt < retries:
                    self._sleep(1.0 + attempt)
                    continue
                log.info("%s network error: %s", label, type(exc).__name__)
                raise ProviderError(f"Could not reach {label}. Check your internet connection.") from exc

            if resp.status_code in _RETRY_STATUS and attempt < retries:
                delay = 1.5 * (2**attempt)
                try:
                    delay = min(float(resp.headers.get("retry-after", delay)), 6.0)
                except ValueError:
                    pass
                self._sleep(delay)
                continue
            break

        assert resp is not None
        code = resp.status_code
        if code in (401, 403):
            raise ProviderError(f"{label} rejected the credentials. Check the API key in Settings.")
        if code == 404:
            raise ProviderError(f"{label} could not find that endpoint (HTTP 404).")
        if code == 429:
            raise ProviderError(f"{label} rate limit reached. Try again later.")
        if code >= 400:
            raise ProviderError(f"{label} returned an error (HTTP {code}).")
        try:
            return resp.json()
        except ValueError as exc:
            raise ProviderError(f"{label} returned an unreadable response.") from exc
