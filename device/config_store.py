try:
    import ujson as json
except ImportError:
    import json

CONFIG_PATH = "/config.json"

DEFAULTS = {
    "ssid": "",
    "password": "",
    "api_token": "",
    "ap_ssid_prefix": "ESP32Studio-Setup",
    "ap_password": "esp32studio",
    "board": {},
}


def load_config():
    data = DEFAULTS.copy()
    try:
        with open(CONFIG_PATH, "r") as handle:
            loaded = json.load(handle)
        if isinstance(loaded, dict):
            data.update(loaded)
    except Exception:
        pass
    return data


def save_config(data):
    merged = DEFAULTS.copy()
    merged.update(data)
    temp = CONFIG_PATH + ".tmp"
    with open(temp, "w") as handle:
        json.dump(merged, handle)
    try:
        import os
        try:
            os.remove(CONFIG_PATH)
        except OSError:
            pass
        os.rename(temp, CONFIG_PATH)
    except Exception:
        pass
    return merged
