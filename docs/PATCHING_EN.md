# Future patching

## Linux: unified diff
```bash
git diff -- device/server.py > server-fix.patch
git apply --check server-fix.patch
git apply server-fix.patch
# or: ./tools/apply-patch.sh server-fix.patch
```
Without Git the helper falls back to `patch -p1`.

## PowerShell: exact block replacement
Save the old block as `old.txt`, the new block as `new.txt`:
```powershell
.\tools\Replace-Block.ps1 -Path .\device\server.py -OldBlockFile .\old.txt -NewBlockFile .\new.txt
```
A `.bak` file is created and the edit is refused unless the old block occurs exactly once. With Git for Windows, `git apply` works in PowerShell too.
