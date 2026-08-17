# ESP32 MultiBoard Studio 2.5.0 — RU

Локальная React + FastAPI + MicroPython Studio для ESP32-C3/S3. Версия 2.5.0 поддерживает **Windows 11 и Linux**, сохраняет проверенный Wi‑Fi стек 2.3.2 и публикует полный проект в GitHub/GitLab с Secret Scrubber.

## Установка Windows
Требуется Python 3.13, `uv`, Node.js/npm.
```powershell
.\SETUP.cmd
.\START_STUDIO.cmd
```

## Установка Linux
Требуется Python 3.13, `uv`, Node.js/npm. На Debian/Ubuntu доступ к `/dev/ttyACM*`/`/dev/ttyUSB*` часто требует группы `dialout`.
```bash
chmod +x SETUP_LINUX.sh START_STUDIO_LINUX.sh REPAIR_ENV_LINUX.sh
./SETUP_LINUX.sh
./START_STUDIO_LINUX.sh
```
Диагностика:
```bash
./scripts/diagnose.sh
```
Постоянное хранение GitHub/GitLab token в Linux использует `secret-tool` (обычно пакет `libsecret-tools`). Если его нет, токен остаётся только в текущей сессии.

## Wi‑Fi baseline
`device/server.py` и `host/device_client.py` в 2.5.0 оставлены **байт-в-байт как в рабочей 2.3.2**. Это сделано специально: Git/Linux-функции не должны менять проверенный сетевой путь.

## Git: что публикуется
Режим **Full Studio Source** публикует исходники React/FastAPI/MicroPython, board profiles, Windows/Linux scripts, документацию, `uv.lock`, `package-lock.json`, а после локальной сборки также `frontend/dist`; firmware `.bin` тоже разрешён.

Не публикуются: `.venv`, `node_modules`, `.git`, Python-кэши, локальные SQLite/log и credential-файлы. Secret Scrubber дополнительно вырезает найденные токены/пароли из текстов. То есть принцип — «весь проект», но без зависимостей, мусора и секретов.

## Патчи
Linux/unified diff и PowerShell exact-block replacement описаны в [docs/PATCHING_RU.md](docs/PATCHING_RU.md). Готовые helpers: `tools/apply-patch.sh` и `tools/Replace-Block.ps1`.

## Двуязычные комментарии
Для новых и существенно изменённых мест используем:
```python
# EN: Explain non-trivial behavior.
# RU: Объясняем нетривиальное поведение.
```
Подробнее: [docs/CODE_STYLE_RU_EN.md](docs/CODE_STYLE_RU_EN.md).

## Порт 8765
2.5.0 перед запуском проверяет порт. Если там уже работает старая Studio, новая версия **не откроет браузер на чужом backend**, а покажет понятную ошибку. Можно выбрать другой порт:
```powershell
$env:GHOST32_PORT=8766; .\START_STUDIO.cmd
```
```bash
GHOST32_PORT=8766 ./START_STUDIO_LINUX.sh
```
