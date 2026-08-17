import network
import time
import ubinascii
from machine import unique_id


class WifiManager:
    def __init__(self, config):
        self.config = config
        self.sta = network.WLAN(network.STA_IF)
        self.ap = network.WLAN(network.AP_IF)
        self.mode = "offline"

    def start(self, timeout_ms=15000):
        ssid = self.config.get("ssid", "")
        password = self.config.get("password", "")
        if ssid:
            self.sta.active(True)
            if not self.sta.isconnected():
                self.sta.connect(ssid, password)
            start = time.ticks_ms()
            while not self.sta.isconnected() and time.ticks_diff(time.ticks_ms(), start) < timeout_ms:
                time.sleep_ms(250)
            if self.sta.isconnected():
                self.mode = "station"
                try:
                    self.ap.active(False)
                except Exception:
                    pass
                return self.status()
        return self.start_ap()

    def start_ap(self):
        suffix = ubinascii.hexlify(unique_id()).decode()[-4:].upper()
        prefix = self.config.get("ap_ssid_prefix", "ESP32C3-Setup") or "ESP32C3-Setup"
        password = self.config.get("ap_password", "esp32c3setup") or "esp32c3setup"
        self.ap.active(True)
        self.ap.config(essid="%s-%s" % (prefix, suffix), password=password)
        self.mode = "access-point"
        return self.status()

    def status(self):
        if self.sta.active() and self.sta.isconnected():
            ip = self.sta.ifconfig()[0]
            ssid = self.config.get("ssid", "")
            try:
                rssi = self.sta.status("rssi")
            except Exception:
                rssi = None
            return {"mode": "station", "connected": True, "ip": ip, "ssid": ssid, "rssi": rssi}
        if self.ap.active():
            return {
                "mode": "access-point",
                "connected": True,
                "ip": self.ap.ifconfig()[0],
                "ssid": self.ap.config("essid"),
                "rssi": None,
            }
        return {"mode": "offline", "connected": False, "ip": "", "ssid": "", "rssi": None}
