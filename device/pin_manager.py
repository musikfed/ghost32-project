from machine import ADC, PWM, Pin

VALID_MODES = ("UNCONFIGURED", "INPUT", "INPUT_PULLUP", "INPUT_PULLDOWN", "OUTPUT", "PWM", "ADC")

# Backward-compatible fallback for a controller that still has a Studio 2.0 config.json.
LEGACY_C3_PIN_DEFS = [
    {"gpio": 0, "adc": True, "pwm": True, "output": True, "available": True, "risk": "", "danger": False, "label": "GPIO0", "note": ""},
    {"gpio": 1, "adc": True, "pwm": True, "output": True, "available": True, "risk": "", "danger": False, "label": "GPIO1", "note": ""},
    {"gpio": 2, "adc": True, "pwm": True, "output": True, "available": True, "risk": "strapping", "danger": True, "label": "GPIO2 / STRAP", "note": "Boot strapping pin."},
    {"gpio": 3, "adc": True, "pwm": True, "output": True, "available": True, "risk": "", "danger": False, "label": "GPIO3", "note": ""},
    {"gpio": 4, "adc": True, "pwm": True, "output": True, "available": True, "risk": "", "danger": False, "label": "GPIO4", "note": ""},
    {"gpio": 5, "adc": True, "pwm": True, "output": True, "available": True, "risk": "adc2", "danger": False, "label": "GPIO5 / ADC2", "note": ""},
    {"gpio": 6, "adc": False, "pwm": True, "output": True, "available": True, "risk": "", "danger": False, "label": "GPIO6", "note": ""},
    {"gpio": 7, "adc": False, "pwm": True, "output": True, "available": True, "risk": "", "danger": False, "label": "GPIO7", "note": ""},
    {"gpio": 8, "adc": False, "pwm": True, "output": True, "available": True, "risk": "strapping-led", "danger": True, "label": "GPIO8 / LED / STRAP", "note": ""},
    {"gpio": 9, "adc": False, "pwm": True, "output": True, "available": True, "risk": "strapping-boot", "danger": True, "label": "GPIO9 / BOOT / STRAP", "note": ""},
    {"gpio": 10, "adc": False, "pwm": True, "output": True, "available": True, "risk": "", "danger": False, "label": "GPIO10", "note": ""},
    {"gpio": 20, "adc": False, "pwm": True, "output": True, "available": True, "risk": "uart-rx", "danger": False, "label": "GPIO20 / UART RX", "note": ""},
    {"gpio": 21, "adc": False, "pwm": True, "output": True, "available": True, "risk": "uart-tx", "danger": False, "label": "GPIO21 / UART TX", "note": ""},
]


class PinManager:
    def __init__(self, pin_defs=None):
        if not isinstance(pin_defs, list) or not pin_defs:
            pin_defs = LEGACY_C3_PIN_DEFS
        self.pin_defs = pin_defs
        self.defs = {}
        self.state = {}
        for raw in pin_defs:
            try:
                gpio = int(raw.get("gpio"))
            except Exception:
                continue
            info = {
                "gpio": gpio,
                "label": str(raw.get("label", "GPIO%d" % gpio)),
                "adc": bool(raw.get("adc", False)),
                "pwm": bool(raw.get("pwm", True)),
                "output": bool(raw.get("output", True)),
                "available": bool(raw.get("available", True)),
                "risk": str(raw.get("risk", "") or ""),
                "danger": bool(raw.get("danger", False)),
                "note": str(raw.get("note", "") or ""),
                "aliases": raw.get("aliases", []) if isinstance(raw.get("aliases", []), list) else [],
            }
            self.defs[gpio] = info
            self.state[gpio] = {
                "mode": "UNCONFIGURED",
                "obj": None,
                "value": None,
                "duty_u16": 0,
                "frequency": 1000,
            }

    def _require(self, gpio):
        gpio = int(gpio)
        if gpio not in self.defs:
            raise ValueError("GPIO is not present in this board profile")
        return self.defs[gpio]

    def _release(self, gpio):
        entry = self.state[gpio]
        obj = entry.get("obj")
        if obj is not None:
            try:
                obj.deinit()
            except Exception:
                pass
        entry["obj"] = None

    def set_mode(self, gpio, mode, force=False):
        gpio = int(gpio)
        info = self._require(gpio)
        mode = str(mode).upper()
        if mode not in VALID_MODES:
            raise ValueError("Unsupported mode")
        if not info["available"] and mode != "UNCONFIGURED":
            raise ValueError("This GPIO is locked/reserved by the selected board profile")
        if info["danger"] and not force and mode != "UNCONFIGURED":
            raise ValueError("This pin can affect boot, USB or memory. Retry with force=true if you understand the risk.")
        if mode == "ADC" and not info["adc"]:
            raise ValueError("ADC is not available on this GPIO")
        if mode == "PWM" and not info["pwm"]:
            raise ValueError("PWM/output is not available on this GPIO")
        if mode == "OUTPUT" and not info["output"]:
            raise ValueError("Output mode is not available on this GPIO")

        self._release(gpio)
        entry = self.state[gpio]
        entry["mode"] = mode
        entry["value"] = None

        if mode == "UNCONFIGURED":
            return self.describe(gpio)
        try:
            if mode == "INPUT":
                entry["obj"] = Pin(gpio, Pin.IN)
            elif mode == "INPUT_PULLUP":
                entry["obj"] = Pin(gpio, Pin.IN, Pin.PULL_UP)
            elif mode == "INPUT_PULLDOWN":
                entry["obj"] = Pin(gpio, Pin.IN, Pin.PULL_DOWN)
            elif mode == "OUTPUT":
                entry["obj"] = Pin(gpio, Pin.OUT, value=0)
                entry["value"] = 0
            elif mode == "PWM":
                entry["obj"] = PWM(Pin(gpio), freq=entry["frequency"], duty_u16=entry["duty_u16"])
            elif mode == "ADC":
                entry["obj"] = ADC(Pin(gpio))
        except Exception:
            entry["mode"] = "UNCONFIGURED"
            entry["obj"] = None
            entry["value"] = None
            raise
        return self.describe(gpio)

    def write(self, gpio, value):
        gpio = int(gpio)
        self._require(gpio)
        entry = self.state[gpio]
        if entry["mode"] != "OUTPUT":
            raise ValueError("GPIO is not in OUTPUT mode")
        value = 1 if int(value) else 0
        entry["obj"].value(value)
        entry["value"] = value
        return self.describe(gpio)

    def set_pwm(self, gpio, duty_u16, frequency):
        gpio = int(gpio)
        self._require(gpio)
        entry = self.state[gpio]
        if entry["mode"] != "PWM":
            raise ValueError("GPIO is not in PWM mode")
        duty_u16 = max(0, min(65535, int(duty_u16)))
        frequency = max(1, min(1000000, int(frequency)))
        entry["obj"].freq(frequency)
        entry["obj"].duty_u16(duty_u16)
        entry["duty_u16"] = duty_u16
        entry["frequency"] = frequency
        return self.describe(gpio)

    def describe(self, gpio):
        gpio = int(gpio)
        info = self._require(gpio)
        entry = self.state[gpio]
        value = entry.get("value")
        mode = entry["mode"]
        obj = entry.get("obj")
        try:
            if mode in ("INPUT", "INPUT_PULLUP", "INPUT_PULLDOWN", "OUTPUT") and obj is not None:
                value = obj.value()
            elif mode == "ADC" and obj is not None:
                value = obj.read_u16()
            elif mode == "PWM":
                value = entry["duty_u16"]
        except Exception as exc:
            value = None
            error = str(exc)
        else:
            error = ""

        return {
            "gpio": gpio,
            "label": info["label"],
            "mode": mode,
            "value": value,
            "adc": info["adc"],
            "pwm": info["pwm"],
            "output": info["output"],
            "available": info["available"],
            "risk": info["risk"],
            "danger": info["danger"],
            "note": info["note"],
            "aliases": info["aliases"],
            "duty_u16": entry["duty_u16"],
            "frequency": entry["frequency"],
            "error": error,
        }

    def snapshot(self):
        result = []
        for item in self.pin_defs:
            try:
                gpio = int(item.get("gpio"))
                if gpio in self.defs:
                    result.append(self.describe(gpio))
            except Exception:
                pass
        return result
