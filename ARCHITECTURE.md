# Architecture — 2.5.0

```text
React UI (browser)
        |
        v
FastAPI host (Windows 11 / Linux, Python 3.13)
   | USB/serial                 | LAN HTTP
   v                            v
esptool + mpremote         ESP32 MicroPython runtime
                                |
                                +-- GPIO / files / Wi-Fi API
```

Persistent host state is per-user: LocalAppData on Windows, XDG data directory on Linux. Cloud tokens use Windows Credential Manager or Linux Secret Service. Full Git publish runs Secret Scrubber before GitHub/GitLab API calls and supports both text and binary project files.

The Wi‑Fi runtime/client pair is pinned to the known-working 2.3.2 implementation in 2.5.0.
