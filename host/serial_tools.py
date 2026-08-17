from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

import httpx
from serial.tools import list_ports

from .board_profiles import BoardProfileError, compatible_profiles, get_firmware, get_profile

ROOT = Path(__file__).resolve().parents[1]
DEVICE_DIR = ROOT / "device"
FIRMWARE_DIR = ROOT / "firmware"


class SerialToolError(RuntimeError):
    pass


def ports() -> list[dict[str, str]]:
    result = []
    for port in sorted(list_ports.comports(), key=lambda p: p.device):
        result.append(
            {
                "device": port.device,
                "description": port.description or "",
                "hwid": port.hwid or "",
                "vid": f"{port.vid:04X}" if port.vid is not None else "",
                "pid": f"{port.pid:04X}" if port.pid is not None else "",
                "serial_number": port.serial_number or "",
                "manufacturer": port.manufacturer or "",
            }
        )
    return result


def _python_tool(module: str, *args: str) -> list[str]:
    r"""Run a CLI module with the exact interpreter that hosts Studio.

    This deliberately avoids PATH/venv activation assumptions on Windows.
    If Studio runs from .venv\Scripts\python.exe, esptool/mpremote are loaded
    from that same .venv even when .venv\Scripts is not present in PATH.
    """
    return [sys.executable, "-m", module, *args]


def _run(args: list[str], timeout: int = 120) -> str:
    try:
        proc = subprocess.run(
            args,
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise SerialToolError(f"Command timed out: {' '.join(args)}") from exc
    output = (proc.stdout or "") + (proc.stderr or "")
    if proc.returncode != 0:
        clean = output.strip()
        if "No module named esptool" in clean:
            raise SerialToolError("esptool is missing from Studio .venv. Run REPAIR_ENV.cmd (Windows) or ./REPAIR_ENV_LINUX.sh (Linux), then start Studio again.")
        if "No module named mpremote" in clean:
            raise SerialToolError("mpremote is missing from Studio .venv. Run REPAIR_ENV.cmd (Windows) or ./REPAIR_ENV_LINUX.sh (Linux), then start Studio again.")
        raise SerialToolError(clean or f"Command failed with code {proc.returncode}")
    return output.strip()


def _normalise_chip(text: str) -> str:
    upper = text.upper().replace("_", "-")
    for label, key in (
        ("ESP32-S3", "esp32s3"),
        ("ESP32-C3", "esp32c3"),
        ("ESP32-C6", "esp32c6"),
        ("ESP32-S2", "esp32s2"),
        ("ESP32-H2", "esp32h2"),
        ("ESP32", "esp32"),
    ):
        if label in upper:
            return key
    return "unknown"


def _parse_size_mb(text: str, label: str) -> int | None:
    match = re.search(rf"{re.escape(label)}[^\n\r:]*:\s*([0-9]+(?:\.[0-9]+)?)\s*([KMG]B)", text, re.I)
    if not match:
        return None
    value = float(match.group(1))
    unit = match.group(2).upper()
    if unit == "KB":
        value /= 1024
    elif unit == "GB":
        value *= 1024
    return int(round(value))


def probe_device(port: str) -> dict:
    output = _run(_python_tool("esptool", "--port", port, "flash-id"), 75)
    chip = _normalise_chip(output)
    flash_mb = _parse_size_mb(output, "Detected flash size")

    psram_mb = None
    psram_match = re.search(r"(?:PSRAM|SPIRAM)[^\n\r]*?([0-9]+)\s*MB", output, re.I)
    if psram_match:
        psram_mb = int(psram_match.group(1))

    mac_match = re.search(r"MAC:\s*([0-9A-Fa-f:]{11,})", output)
    revision_match = re.search(r"(?:Chip type|Chip is):\s*([^\r\n]+)", output, re.I)

    matches = compatible_profiles(chip, flash_mb)
    return {
        "port": port,
        "chip": chip,
        "chip_text": revision_match.group(1).strip() if revision_match else chip,
        "flash_mb": flash_mb,
        "psram_mb": psram_mb,
        "mac": mac_match.group(1) if mac_match else "",
        "compatible_profiles": [
            {
                "id": p["id"],
                "name": p["name"],
                "match_score": p.get("match_score", 0),
                "memory": p.get("memory", {}),
                "verified": bool(p.get("verified")),
            }
            for p in matches
        ],
        "log": output,
    }


def _firmware_path(firmware: dict) -> Path:
    return FIRMWARE_DIR / str(firmware["filename"])


def ensure_firmware(firmware_id: str) -> tuple[Path, bool, str]:
    try:
        firmware = get_firmware(firmware_id)
    except BoardProfileError as exc:
        raise SerialToolError(str(exc)) from exc

    target = _firmware_path(firmware)
    if target.exists() and target.stat().st_size > 100_000:
        digest = hashlib.sha256(target.read_bytes()).hexdigest()
        return target, False, digest

    url = str(firmware.get("url", ""))
    if not url.startswith("https://micropython.org/"):
        raise SerialToolError("Firmware is missing and its source URL is not an approved MicroPython URL")

    tmp = target.with_suffix(target.suffix + ".download")
    try:
        with httpx.stream("GET", url, follow_redirects=True, timeout=90.0) as response:
            response.raise_for_status()
            with tmp.open("wb") as handle:
                for chunk in response.iter_bytes():
                    handle.write(chunk)
        if tmp.stat().st_size < 100_000:
            raise SerialToolError("Downloaded firmware is unexpectedly small")
        tmp.replace(target)
    except Exception as exc:
        try:
            tmp.unlink(missing_ok=True)
        except Exception:
            pass
        raise SerialToolError(
            f"Cannot download {firmware['filename']} from official MicroPython server. "
            f"Check Internet access or place the file manually in {FIRMWARE_DIR}. Error: {exc}"
        ) from exc

    digest = hashlib.sha256(target.read_bytes()).hexdigest()
    return target, True, digest


def flash_micropython(port: str, profile_id: str, erase: bool = True, baud: int = 460800) -> dict[str, str]:
    try:
        profile = get_profile(profile_id)
    except BoardProfileError as exc:
        raise SerialToolError(str(exc)) from exc

    probe = probe_device(port)
    expected_chip = str(profile.get("chip", "")).lower()
    if probe["chip"] != expected_chip:
        raise SerialToolError(
            f"Board profile expects {expected_chip}, but esptool detected {probe['chip_text']}. "
            "Choose a compatible profile before flashing."
        )

    firmware, downloaded, digest = ensure_firmware(str(profile["firmware_id"]))
    logs = ["== Device probe ==\n" + probe["log"]]
    if downloaded:
        logs.append(f"Downloaded official MicroPython firmware: {firmware.name}\nSHA256: {digest}")
    else:
        logs.append(f"Firmware: {firmware.name}\nSHA256: {digest}")

    chip = expected_chip
    if erase:
        logs.append(_run(_python_tool("esptool", "--chip", chip, "--port", port, "erase-flash"), 90))
    logs.append(
        _run(
            _python_tool(
                "esptool",
                "--chip",
                chip,
                "--port",
                port,
                "--baud",
                str(baud),
                "write-flash",
                "0x0",
                str(firmware),
            ),
            240,
        )
    )
    return {
        "message": f"MicroPython flashed for {profile['name']}",
        "firmware": firmware.name,
        "sha256": digest,
        "log": "\n\n".join(logs),
    }


def _mpremote(port: str, *commands: str, timeout: int = 45) -> str:
    return _run(_python_tool("mpremote", "connect", port, *commands), timeout)


def install_runtime(port: str, profile_id: str, ssid: str = "", password: str = "", token: str = "") -> dict[str, str]:
    required = ["boot.py", "main.py", "config_store.py", "pin_manager.py", "wifi_manager.py", "server.py"]
    for filename in required:
        if not (DEVICE_DIR / filename).exists():
            raise SerialToolError(f"Missing device file: {filename}")

    if not token.strip():
        raise SerialToolError("API token is required for provisioning")

    try:
        profile = get_profile(profile_id)
    except BoardProfileError as exc:
        raise SerialToolError(str(exc)) from exc

    probe = probe_device(port)
    if probe["chip"] != str(profile["chip"]).lower():
        raise SerialToolError(
            f"Selected profile is {profile['chip']}, but connected chip is {probe['chip_text']}."
        )

    board_payload = {
        "id": profile["id"],
        "name": profile["name"],
        "chip": profile["chip"],
        "family": profile.get("family", ""),
        "memory": profile.get("memory", {}),
        "verified": bool(profile.get("verified")),
        "pins": profile.get("pins", []),
    }
    config = {
        "ssid": ssid,
        "password": password,
        "api_token": token.strip(),
        "ap_ssid_prefix": "ESP32Studio-Setup",
        "ap_password": "esp32studio",
        "board": board_payload,
    }

    logs: list[str] = ["== Device probe ==\n" + probe["log"]]
    with tempfile.TemporaryDirectory(prefix=".studio-tmp-", dir=ROOT) as tmp:
        tmp_path = Path(tmp)
        config_path = tmp_path / "config.json"
        config_path.write_text(json.dumps(config, ensure_ascii=False), encoding="utf-8")

        for filename in required:
            source = DEVICE_DIR / filename
            local_source = str(source.relative_to(ROOT))
            logs.append(_mpremote(port, "fs", "cp", local_source, f":{filename}"))
        local_config = str(config_path.relative_to(ROOT))
        logs.append(_mpremote(port, "fs", "cp", local_config, ":config.json"))
        logs.append(_mpremote(port, "reset"))

    return {"message": f"Runtime installed for {profile['name']} and device reset", "log": "\n".join(logs)}


def read_device_files(port: str) -> dict[str, str]:
    return {"log": _mpremote(port, "fs", "ls")}

# ---------------------------------------------------------------------------
# Progress-aware workers used by Studio 2.2 job API.
# They intentionally coexist with the synchronous helpers above for backwards
# compatibility and diagnostics scripts.


def _parse_probe_output(port: str, output: str) -> dict:
    chip = _normalise_chip(output)
    flash_mb = _parse_size_mb(output, "Detected flash size")
    psram_mb = None
    psram_match = re.search(r"(?:PSRAM|SPIRAM)[^\n\r]*?([0-9]+)\s*MB", output, re.I)
    if psram_match:
        psram_mb = int(psram_match.group(1))
    mac_match = re.search(r"MAC:\s*([0-9A-Fa-f:]{11,})", output)
    revision_match = re.search(r"(?:Chip type|Chip is):\s*([^\r\n]+)", output, re.I)
    matches = compatible_profiles(chip, flash_mb)
    return {
        "port": port,
        "chip": chip,
        "chip_text": revision_match.group(1).strip() if revision_match else chip,
        "flash_mb": flash_mb,
        "psram_mb": psram_mb,
        "mac": mac_match.group(1) if mac_match else "",
        "compatible_profiles": [
            {
                "id": p["id"],
                "name": p["name"],
                "match_score": p.get("match_score", 0),
                "memory": p.get("memory", {}),
                "verified": bool(p.get("verified")),
            }
            for p in matches
        ],
        "log": output,
    }


def _stream_run(args: list[str], handle, stage_id: str, timeout: int = 120, parse_percent: bool = False) -> str:
    """Run a host CLI while streaming its real output into a job.

    A reader thread prevents a silent child process from blocking timeout
    handling on Windows pipes. esptool's carriage-return progress is parsed
    as it arrives; no synthetic timer is used.
    """
    import os
    import queue
    import threading
    import time

    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    try:
        proc = subprocess.Popen(
            args,
            cwd=ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=0,
            env=env,
        )
    except OSError as exc:
        raise SerialToolError(f"Cannot start command: {' '.join(args)}: {exc}") from exc

    stream_queue: queue.Queue[str | None] = queue.Queue()
    assert proc.stdout is not None

    def reader() -> None:
        try:
            while True:
                ch = proc.stdout.read(1)
                if not ch:
                    break
                stream_queue.put(ch)
        finally:
            stream_queue.put(None)

    threading.Thread(target=reader, name="studio-cli-reader", daemon=True).start()

    started = time.monotonic()
    output_parts: list[str] = []
    line = ""
    last_pct = -1
    eof = False
    while not eof:
        if time.monotonic() - started > timeout:
            proc.kill()
            try:
                proc.wait(timeout=2)
            except Exception:
                pass
            raise SerialToolError(f"Command timed out: {' '.join(args)}")
        try:
            ch = stream_queue.get(timeout=0.1)
        except queue.Empty:
            if proc.poll() is not None:
                continue
            continue
        if ch is None:
            eof = True
            continue
        output_parts.append(ch)
        line += ch
        if parse_percent:
            match = re.search(r"(?:\(|\b)(\d{1,3})\s*%", line)
            if match:
                pct = max(0, min(100, int(match.group(1))))
                if pct != last_pct:
                    last_pct = pct
                    handle.stage_progress(stage_id, pct, f"{pct}%")
        if ch in "\r\n":
            clean = line.strip("\r\n")
            if clean:
                handle.append_log(clean)
            line = ""

    if line.strip():
        handle.append_log(line.strip())
    try:
        returncode = proc.wait(timeout=3)
    except subprocess.TimeoutExpired:
        proc.kill()
        raise SerialToolError(f"Command did not exit cleanly: {' '.join(args)}")
    output = "".join(output_parts).strip()
    if returncode != 0:
        if "No module named esptool" in output:
            raise SerialToolError("esptool is missing from Studio .venv. Run REPAIR_ENV.cmd (Windows) or ./REPAIR_ENV_LINUX.sh (Linux), then start Studio again.")
        if "No module named mpremote" in output:
            raise SerialToolError("mpremote is missing from Studio .venv. Run REPAIR_ENV.cmd (Windows) or ./REPAIR_ENV_LINUX.sh (Linux), then start Studio again.")
        raise SerialToolError(output or f"Command failed with code {returncode}")
    return output

def probe_device_job(port: str, handle) -> dict:
    handle.stage("probe", progress=1, detail=f"Opening {port}")
    output = _stream_run(_python_tool("esptool", "--port", port, "flash-id"), handle, "probe", 75, False)
    result = _parse_probe_output(port, output)
    if result.get('mac'):
        handle.set_project(
            'device:' + result['mac'].lower().replace(':', ''),
            f"{result['chip_text']} · {port}",
            port=port, mac=result['mac'], chip=result['chip'], flash_mb=result.get('flash_mb'),
        )
    handle.stage_done("probe", f"{result['chip_text']} · {result.get('flash_mb') or '?'} MB flash")
    return result


def ensure_firmware_job(firmware_id: str, handle) -> tuple[Path, bool, str]:
    try:
        firmware = get_firmware(firmware_id)
    except BoardProfileError as exc:
        raise SerialToolError(str(exc)) from exc

    target = _firmware_path(firmware)
    handle.stage("firmware", progress=1, detail=str(firmware["filename"]))
    if target.exists() and target.stat().st_size > 100_000:
        digest = hashlib.sha256(target.read_bytes()).hexdigest()
        handle.stage_done("firmware", "Firmware already cached")
        return target, False, digest

    url = str(firmware.get("url", ""))
    if not url.startswith("https://micropython.org/"):
        raise SerialToolError("Firmware is missing and its source URL is not an approved MicroPython URL")
    tmp = target.with_suffix(target.suffix + ".download")
    try:
        with httpx.stream("GET", url, follow_redirects=True, timeout=90.0) as response:
            response.raise_for_status()
            total = int(response.headers.get("content-length") or 0)
            received = 0
            with tmp.open("wb") as file_handle:
                for chunk in response.iter_bytes():
                    file_handle.write(chunk)
                    received += len(chunk)
                    if total > 0:
                        pct = min(99, int(received / total * 100))
                        handle.stage_progress("firmware", pct, f"{received // 1024} / {total // 1024} KB")
                    else:
                        handle.stage("firmware", progress=None, detail=f"{received // 1024} KB downloaded")
        if tmp.stat().st_size < 100_000:
            raise SerialToolError("Downloaded firmware is unexpectedly small")
        tmp.replace(target)
    except Exception as exc:
        try:
            tmp.unlink(missing_ok=True)
        except Exception:
            pass
        if isinstance(exc, SerialToolError):
            raise
        raise SerialToolError(
            f"Cannot download {firmware['filename']} from official MicroPython server. "
            f"Check Internet access or place the file manually in {FIRMWARE_DIR}. Error: {exc}"
        ) from exc
    digest = hashlib.sha256(target.read_bytes()).hexdigest()
    handle.stage_done("firmware", f"Downloaded · SHA256 {digest[:12]}…")
    return target, True, digest


def flash_micropython_job(port: str, profile_id: str, erase: bool, baud: int, handle) -> dict[str, str]:
    try:
        profile = get_profile(profile_id)
    except BoardProfileError as exc:
        raise SerialToolError(str(exc)) from exc

    probe = probe_device_job(port, handle)
    if probe.get('mac'):
        handle.set_project(
            'device:' + probe['mac'].lower().replace(':', ''),
            f"{profile['name']} · {port}",
            profile_id=profile_id, profile_name=profile.get('name', ''), port=port, mac=probe['mac'],
        )
    expected_chip = str(profile.get("chip", "")).lower()
    if probe["chip"] != expected_chip:
        raise SerialToolError(
            f"Board profile expects {expected_chip}, but esptool detected {probe['chip_text']}. Choose a compatible profile before flashing."
        )

    firmware, downloaded, digest = ensure_firmware_job(str(profile["firmware_id"]), handle)
    chip = expected_chip

    if erase:
        handle.stage("erase", progress=None, detail="Erasing flash")
        _stream_run(_python_tool("esptool", "--chip", chip, "--port", port, "erase-flash"), handle, "erase", 120, False)
        handle.stage_done("erase", "Flash erased")
    else:
        handle.stage_done("erase", "Skipped")

    handle.stage("flash", progress=0, detail=f"{firmware.name} @ {baud}")
    output = _stream_run(
        _python_tool("esptool", "--chip", chip, "--port", port, "--baud", str(baud), "write-flash", "0x0", str(firmware)),
        handle,
        "flash",
        300,
        True,
    )
    handle.stage_done("flash", "100% written")

    handle.stage("verify", progress=50, detail="Checking esptool result")
    verified = bool(re.search(r"verified|hash of data", output, re.I))
    handle.stage_done("verify", "Hash verified" if verified else "write-flash completed successfully")
    return {
        "message": f"MicroPython flashed for {profile['name']}",
        "firmware": firmware.name,
        "downloaded": downloaded,
        "sha256": digest,
        "verified": verified,
        "probe": probe,
    }


def install_runtime_job(port: str, profile_id: str, ssid: str, password: str, token: str, handle) -> dict[str, str]:
    required = ["boot.py", "main.py", "config_store.py", "pin_manager.py", "wifi_manager.py", "server.py"]
    for filename in required:
        if not (DEVICE_DIR / filename).exists():
            raise SerialToolError(f"Missing device file: {filename}")
    if not token.strip():
        raise SerialToolError("API token is required for provisioning")
    try:
        profile = get_profile(profile_id)
    except BoardProfileError as exc:
        raise SerialToolError(str(exc)) from exc

    probe = probe_device_job(port, handle)
    if probe.get('mac'):
        handle.set_project(
            'device:' + probe['mac'].lower().replace(':', ''),
            f"{profile['name']} · {port}",
            profile_id=profile_id, profile_name=profile.get('name', ''), port=port, mac=probe['mac'],
        )
    if probe["chip"] != str(profile["chip"]).lower():
        raise SerialToolError(f"Selected profile is {profile['chip']}, but connected chip is {probe['chip_text']}.")

    handle.stage("prepare", progress=25, detail="Building config.json")
    board_payload = {
        "id": profile["id"], "name": profile["name"], "chip": profile["chip"],
        "family": profile.get("family", ""), "memory": profile.get("memory", {}),
        "verified": bool(profile.get("verified")), "pins": profile.get("pins", []),
    }
    config = {
        "ssid": ssid, "password": password, "api_token": token.strip(),
        "ap_ssid_prefix": "ESP32Studio-Setup", "ap_password": "esp32studio", "board": board_payload,
    }
    handle.stage_done("prepare", "Runtime config ready")

    with tempfile.TemporaryDirectory(prefix=".studio-tmp-", dir=ROOT) as tmp:
        tmp_path = Path(tmp)
        config_path = tmp_path / "config.json"
        config_path.write_text(json.dumps(config, ensure_ascii=False), encoding="utf-8")
        upload_items = [(DEVICE_DIR / filename, filename) for filename in required] + [(config_path, "config.json")]
        handle.stage("upload", progress=0, detail=f"0 / {len(upload_items)} files")
        for index, (source, remote_name) in enumerate(upload_items, start=1):
            local_source = str(source.relative_to(ROOT))
            handle.append_log(f"Uploading {remote_name}")
            _stream_run(_python_tool("mpremote", "connect", port, "fs", "cp", local_source, f":{remote_name}"), handle, "upload", 60, False)
            pct = int(index / len(upload_items) * 100)
            handle.stage_progress("upload", pct, f"{index} / {len(upload_items)} files · {remote_name}")
        handle.stage_done("upload", f"{len(upload_items)} files uploaded")

    # IMPORTANT: verify the filesystem BEFORE the final hard reset.
    # mpremote fs/exec uses raw REPL and auto-soft-reset, which leaves main.py
    # stopped. The final operation must therefore be a hard reset so the
    # on-device runtime boots and starts its HTTP API.
    handle.stage("verify", progress=20, detail="Reading filesystem")
    listing = _stream_run(_python_tool("mpremote", "connect", port, "fs", "ls"), handle, "verify", 45, False)
    missing = [name for name in required if name not in listing]
    if missing:
        raise SerialToolError(f"Runtime verify failed; missing: {', '.join(missing)}")
    handle.stage_done("verify", "Runtime files verified")

    handle.stage("reset", progress=None, detail="Starting installed runtime")
    _stream_run(_python_tool("mpremote", "connect", port, "reset"), handle, "reset", 30, False)
    handle.stage_done("reset", "Hard reset complete; main.py starts normally")
    return {"message": f"Runtime installed for {profile['name']} and started", "listing": listing, "probe": probe}


def read_device_files_job(port: str, handle) -> dict[str, str]:
    handle.stage("connect", progress=None, detail=f"Connecting {port}")
    handle.stage_done("connect", "Connected")
    handle.stage("files", progress=None, detail="Reading root filesystem")
    listing = ""
    try:
        listing = _stream_run(_python_tool("mpremote", "connect", port, "fs", "ls"), handle, "files", 45, False)
        handle.stage_done("files", "Filesystem read")
    finally:
        # USB filesystem access interrupts a running main.py. Always hard-reset
        # afterwards so Wi-Fi/API runtime is restored automatically.
        handle.stage("reset", progress=None, detail="Restarting device runtime")
        try:
            _stream_run(_python_tool("mpremote", "connect", port, "reset"), handle, "reset", 30, False)
            handle.stage_done("reset", "Runtime restarted")
        except Exception as exc:
            handle.append_log(f"Warning: automatic runtime restart failed: {exc}")
            raise
    return {"message": "Filesystem read through mpremote; runtime restarted", "log": listing}
