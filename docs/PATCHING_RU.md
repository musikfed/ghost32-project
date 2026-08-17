# Патчи на будущее

## Linux: unified diff
```bash
git diff -- device/server.py > server-fix.patch
git apply --check server-fix.patch
git apply server-fix.patch
# или: ./tools/apply-patch.sh server-fix.patch
```
Без Git скрипт использует `patch -p1`.

## PowerShell: точная замена блока
Сохрани старый кусок в `old.txt`, новый в `new.txt`:
```powershell
.\tools\Replace-Block.ps1 -Path .\device\server.py -OldBlockFile .\old.txt -NewBlockFile .\new.txt
```
Будет создан `.bak`; изменение произойдёт только если старый блок найден ровно один раз. Если установлен Git for Windows, `git apply --check` и `git apply` работают в PowerShell так же.
