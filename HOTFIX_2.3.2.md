# Historical network hotfix note — 2.3.2 baseline

Fixes a Wi-Fi API hang where TCP port 80 could remain reachable while HTTP requests timed out with zero response bytes.

## Fixes

- Device HTTP client sockets now get a 3-second receive timeout, so one incomplete/broken connection cannot freeze the single-threaded MicroPython server.
- Listen backlog increased from 3 to 5.
- Host ESP32 HTTP client uses `httpx.Client(..., trust_env=False)` so LAN traffic does not inherit HTTP(S)_PROXY environment settings.
- Host error messages are board-neutral (`ESP32 device`) instead of hard-coded ESP32-C3.

## Recovery after upgrading runtime

After installing the runtime, the last USB operation must be a hardware reset. Then test:

```powershell
curl.exe -v --noproxy "*" --connect-timeout 3 --max-time 5 http://<ESP32-IP>/api/info
```

If curl still reports a source address from a VPN/TUN adapter (for example 172.x.x.x) rather than the physical LAN address, configure that VPN/TUN application to bypass the local `192.168.0.0/16` network or force a direct LAN route.
