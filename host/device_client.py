from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlsplit

import httpx


class DeviceError(RuntimeError):
    pass


def normalize_device_url(value: str) -> str:
    value = value.strip()
    if not value:
        raise ValueError("Device URL is required")
    if "://" not in value:
        value = "http://" + value
    parsed = urlsplit(value)
    if parsed.scheme != "http":
        raise ValueError("Only http:// device URLs are supported")
    if not parsed.hostname:
        raise ValueError("Invalid device URL")
    if parsed.path not in ("", "/") or parsed.query or parsed.fragment:
        raise ValueError("Use only host/IP and optional port, without a path")
    port = f":{parsed.port}" if parsed.port else ""
    return f"http://{parsed.hostname}{port}"


@dataclass
class DeviceConnection:
    base_url: str = "http://192.168.4.1"
    token: str = ""


class DeviceClient:
    def __init__(self) -> None:
        self.connection = DeviceConnection()

    def configure(self, base_url: str, token: str = "") -> DeviceConnection:
        self.connection = DeviceConnection(normalize_device_url(base_url), token.strip())
        return self.connection

    def _headers(self) -> dict[str, str]:
        headers = {"Accept": "application/json"}
        if self.connection.token:
            headers["X-API-Token"] = self.connection.token
        return headers

    def request(self, method: str, path: str, **kwargs) -> httpx.Response:
        timeout = kwargs.pop("timeout", 8.0)
        headers = self._headers()
        headers.update(kwargs.pop("headers", {}))
        try:
            # ESP32 lives on the LAN. Do not inherit HTTP(S)_PROXY from Windows/shell.
            # TUN/VPN routing is diagnosed separately, but environment proxies must not
            # be used for local device traffic.
            with httpx.Client(timeout=timeout, trust_env=False) as client:
                response = client.request(
                    method,
                    self.connection.base_url + path,
                    headers=headers,
                    **kwargs,
                )
        except httpx.HTTPError as exc:
            raise DeviceError(f"Cannot reach ESP32 device: {exc}") from exc

        if response.status_code >= 400:
            detail = response.text.strip()[:800] or response.reason_phrase
            raise DeviceError(f"ESP32 device returned {response.status_code}: {detail}")
        return response

    def json(self, method: str, path: str, **kwargs):
        response = self.request(method, path, **kwargs)
        try:
            return response.json()
        except ValueError as exc:
            raise DeviceError("ESP32 device returned invalid JSON") from exc


client = DeviceClient()
