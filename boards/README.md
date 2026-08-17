# Board profiles

Studio 2.1 loads every `boards/profiles/*.json` file at startup.

To add another board, copy `esp32-s3-generic.json`, change `id`, `name`, memory and `pins`, then restart Studio.

Important fields per pin:
- `gpio`: ESP GPIO number (not header position).
- `available`: false locks the pin in the UI/runtime.
- `adc`, `pwm`, `output`: allowed capabilities.
- `danger`: requires explicit confirmation before the runtime captures the pin.
- `risk`, `note`, `aliases`: UI hints.

Exact clone board identity cannot usually be derived from USB VID/PID. The host probes the SoC/flash with esptool and then filters compatible profiles.
