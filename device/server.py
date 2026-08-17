import gc
import machine
import os
import socket
import sys
import time
import ubinascii

try:
    import ujson as json
except ImportError:
    import json

from config_store import load_config, save_config
from pin_manager import PinManager
from wifi_manager import WifiManager

MAX_HEADER = 8192
MAX_BODY = 65536
START_MS = time.ticks_ms()

config = load_config()
board_config = config.get("board", {}) if isinstance(config.get("board", {}), dict) else {}
pins = PinManager(board_config.get("pins", []))
wifi = WifiManager(config)


STATUS_TEXT = {
    200: "OK",
    201: "Created",
    204: "No Content",
    400: "Bad Request",
    401: "Unauthorized",
    404: "Not Found",
    405: "Method Not Allowed",
    409: "Conflict",
    413: "Payload Too Large",
    500: "Internal Server Error",
}


def _json_bytes(data):
    return json.dumps(data).encode("utf-8")


def _percent_decode(value):
    value = value.replace("+", " ")
    out = []
    i = 0
    while i < len(value):
        if value[i] == "%" and i + 2 < len(value):
            try:
                out.append(chr(int(value[i + 1:i + 3], 16)))
                i += 3
                continue
            except Exception:
                pass
        out.append(value[i])
        i += 1
    return "".join(out)


def _target_parts(target):
    if "?" not in target:
        return target, {}
    path, raw = target.split("?", 1)
    query = {}
    for part in raw.split("&"):
        if not part:
            continue
        if "=" in part:
            key, value = part.split("=", 1)
        else:
            key, value = part, ""
        query[_percent_decode(key)] = _percent_decode(value)
    return path, query


def _safe_path(path):
    if not path:
        raise ValueError("path is required")
    if "\x00" in path or "\\" in path:
        raise ValueError("invalid path")
    if not path.startswith("/"):
        path = "/" + path
    parts = []
    for item in path.split("/"):
        if item in ("", "."):
            continue
        if item == "..":
            raise ValueError("parent traversal is not allowed")
        parts.append(item)
    return "/" + "/".join(parts)


def _authorized(headers):
    expected = str(config.get("api_token", "") or "")
    if not expected:
        return True
    return headers.get("x-api-token", "") == expected


def _read_request(conn):
    data = b""
    while b"\r\n\r\n" not in data:
        chunk = conn.recv(512)
        if not chunk:
            break
        data += chunk
        if len(data) > MAX_HEADER:
            raise ValueError("headers too large")
    if b"\r\n\r\n" not in data:
        raise ValueError("incomplete request")

    header_bytes, body = data.split(b"\r\n\r\n", 1)
    lines = header_bytes.decode("utf-8", "replace").split("\r\n")
    request_line = lines[0].split(" ")
    if len(request_line) < 2:
        raise ValueError("invalid request line")
    method = request_line[0].upper()
    target = request_line[1]
    headers = {}
    for line in lines[1:]:
        if ":" in line:
            key, value = line.split(":", 1)
            headers[key.strip().lower()] = value.strip()

    content_length = int(headers.get("content-length", "0") or "0")
    if content_length > MAX_BODY:
        raise MemoryError("payload too large")
    while len(body) < content_length:
        chunk = conn.recv(min(1024, content_length - len(body)))
        if not chunk:
            break
        body += chunk
    if len(body) < content_length:
        raise ValueError("incomplete request body")
    return method, target, headers, body[:content_length]


def _send_all(conn, data):
    view = memoryview(data)
    sent = 0
    while sent < len(data):
        count = conn.send(view[sent:])
        if count is None:
            return
        if count <= 0:
            raise OSError("socket send failed")
        sent += count


def _send_response(conn, status, body=b"", content_type="application/json; charset=utf-8"):
    if isinstance(body, str):
        body = body.encode("utf-8")
    status_text = STATUS_TEXT.get(status, "OK")
    header = (
        "HTTP/1.1 %d %s\r\n"
        "Connection: close\r\n"
        "Cache-Control: no-store\r\n"
        "Content-Type: %s\r\n"
        "Content-Length: %d\r\n"
        "\r\n"
    ) % (status, status_text, content_type, len(body))
    _send_all(conn, header.encode("utf-8"))
    if body:
        _send_all(conn, body)


def _error(status, message):
    return status, _json_bytes({"ok": False, "error": str(message)}), "application/json; charset=utf-8", False


def _ok(data=None, reboot=False, status=200):
    if data is None:
        data = {"ok": True}
    elif isinstance(data, dict) and "ok" not in data:
        data["ok"] = True
    return status, _json_bytes(data), "application/json; charset=utf-8", reboot


def _parse_json(body):
    if not body:
        return {}
    try:
        return json.loads(body.decode("utf-8"))
    except Exception:
        raise ValueError("invalid JSON")


def _system_info():
    try:
        uname = os.uname()
        machine_name = uname.machine
    except Exception:
        machine_name = str(board_config.get("family", "ESP32"))
    version = getattr(sys.implementation, "version", None)
    if version:
        micropython_version = ".".join(str(x) for x in version[:3])
    else:
        micropython_version = "unknown"
    try:
        device_id = ubinascii.hexlify(machine.unique_id()).decode()
    except Exception:
        device_id = ""
    return {
        "device_id": device_id,
        "board": board_config.get("name", "ESP32 board"),
        "board_id": board_config.get("id", "legacy"),
        "chip": board_config.get("chip", "unknown"),
        "family": board_config.get("family", "ESP32"),
        "memory_profile": board_config.get("memory", {}),
        "profile_verified": bool(board_config.get("verified", False)),
        "machine": machine_name,
        "micropython": micropython_version,
        "exposed_gpio": [item.get("gpio") for item in pins.pin_defs if isinstance(item, dict)],
        "api_version": 3,
        "programming": {"wifi_files": True, "usb_firmware": True, "multiboard_profiles": True},
    }


def _status():
    gc.collect()
    return {
        "wifi": wifi.status(),
        "pins": pins.snapshot(),
        "uptime_ms": time.ticks_diff(time.ticks_ms(), START_MS),
        "free_memory": gc.mem_free(),
        "api_token_required": bool(config.get("api_token")),
    }


def _fs_list(path):
    path = _safe_path(path or "/")
    items = []
    for item in os.ilistdir(path):
        name = item[0]
        kind = item[1] if len(item) > 1 else 0
        size = item[3] if len(item) > 3 else 0
        is_dir = bool(kind & 0x4000)
        child = (path.rstrip("/") + "/" + name) if path != "/" else "/" + name
        items.append({"name": name, "path": child, "directory": is_dir, "size": size})
    items.sort(key=lambda entry: (not entry["directory"], entry["name"]))
    return {"path": path, "items": items}


def _fs_read(path):
    path = _safe_path(path)
    with open(path, "rb") as handle:
        data = handle.read(MAX_BODY + 1)
    if len(data) > MAX_BODY:
        raise ValueError("file is larger than Wi-Fi editor limit")
    return data


def _fs_write(path, body):
    path = _safe_path(path)
    if path == "/":
        raise ValueError("cannot overwrite root")
    temp = path + ".studio_tmp"
    with open(temp, "wb") as handle:
        handle.write(body)
    try:
        os.remove(path)
    except OSError:
        pass
    os.rename(temp, path)
    return {"path": path, "bytes": len(body)}


def _dispatch(method, target, headers, body):
    path, query = _target_parts(target)

    if method == "GET" and path == "/api/info":
        return _ok(_system_info())
    if method == "GET" and path == "/api/status":
        return _ok(_status())

    if not _authorized(headers):
        return _error(401, "invalid or missing X-API-Token")

    if method == "GET" and path == "/api/auth/check":
        return _ok({"authorized": True})

    if method == "GET" and path == "/api/fs/list":
        return _ok(_fs_list(query.get("path", "/")))
    if method == "GET" and path == "/api/fs":
        try:
            data = _fs_read(query.get("path", ""))
            return 200, data, "text/plain; charset=utf-8", False
        except OSError:
            return _error(404, "file not found")
    if method == "PUT" and path == "/api/fs":
        return _ok(_fs_write(query.get("path", ""), body), status=201)
    if method == "DELETE" and path == "/api/fs":
        file_path = _safe_path(query.get("path", ""))
        try:
            os.remove(file_path)
        except OSError:
            return _error(404, "file not found")
        return _ok({"path": file_path, "deleted": True})

    if method == "POST" and path == "/api/wifi":
        payload = _parse_json(body)
        config["ssid"] = str(payload.get("ssid", ""))[:64]
        config["password"] = str(payload.get("password", ""))[:128]
        save_config(config)
        return _ok({"wifi_saved": True, "reboot_required": True})

    if method == "POST" and path == "/api/reboot":
        return _ok({"rebooting": True}, reboot=True)

    parts = path.strip("/").split("/")
    if len(parts) == 4 and parts[0] == "api" and parts[1] == "pins" and method == "POST":
        try:
            gpio = int(parts[2])
            action = parts[3]
            payload = _parse_json(body)
            if action == "mode":
                return _ok({"pin": pins.set_mode(gpio, payload.get("mode", ""), bool(payload.get("force", False)))})
            if action == "write":
                return _ok({"pin": pins.write(gpio, payload.get("value", 0))})
            if action == "pwm":
                return _ok({"pin": pins.set_pwm(gpio, payload.get("duty_u16", 0), payload.get("frequency", 1000))})
            return _error(404, "unknown pin action")
        except ValueError as exc:
            return _error(409, exc)
        except Exception as exc:
            return _error(500, exc)

    return _error(404, "not found")


def _client(conn):
    reboot = False
    try:
        method, target, headers, body = _read_request(conn)
        status, response_body, content_type, reboot = _dispatch(method, target, headers, body)
        _send_response(conn, status, response_body, content_type)
    except MemoryError:
        _send_response(conn, 413, _json_bytes({"ok": False, "error": "payload too large"}))
    except ValueError as exc:
        _send_response(conn, 400, _json_bytes({"ok": False, "error": str(exc)}))
    except Exception as exc:
        try:
            sys.print_exception(exc)
        except Exception:
            print("Request error:", exc)
        try:
            _send_response(conn, 500, _json_bytes({"ok": False, "error": str(exc)}))
        except Exception:
            pass
    finally:
        try:
            conn.close()
        except Exception:
            pass
        gc.collect()
    if reboot:
        time.sleep_ms(250)
        machine.reset()


def run():
    print("Starting Wi-Fi...")
    wifi_state = wifi.start()
    print("Wi-Fi:", wifi_state)
    if config.get("api_token"):
        print("API token: configured")
    else:
        print("WARNING: API token is empty; protected endpoints are open")

    address = socket.getaddrinfo("0.0.0.0", 80)[0][-1]
    server = socket.socket()
    try:
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    except Exception:
        pass
    server.bind(address)
    server.listen(5)
    print("ESP32 MultiBoard Studio API: http://%s/" % wifi_state.get("ip", "device"))

    while True:
        try:
            conn, addr = server.accept()
            # Never let one incomplete/broken HTTP client freeze the whole runtime.
            # This is especially important with VPN/TUN/proxy software on Windows.
            try:
                conn.settimeout(3)
            except Exception:
                pass
            _client(conn)
        except Exception as exc:
            try:
                sys.print_exception(exc)
            except Exception:
                print("Server error:", exc)
            gc.collect()
