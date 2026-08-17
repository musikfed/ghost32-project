param([Parameter(Mandatory=$true)][string]$Path,[Parameter(Mandatory=$true)][string]$OldBlockFile,[Parameter(Mandatory=$true)][string]$NewBlockFile,[switch]$NoBackup)
$ErrorActionPreference="Stop"
# EN: Refuse ambiguous/no-match replacement. / RU: Не заменяем, если совпадений 0 или больше одного.
$Text=Get-Content -LiteralPath $Path -Raw -Encoding UTF8; $Old=Get-Content -LiteralPath $OldBlockFile -Raw -Encoding UTF8; $New=Get-Content -LiteralPath $NewBlockFile -Raw -Encoding UTF8
$Count=([regex]::Matches($Text,[regex]::Escape($Old))).Count
if($Count -ne 1){throw "Expected exactly one old block in '$Path', found $Count. File not changed."}
if(-not $NoBackup){Copy-Item -LiteralPath $Path -Destination "$Path.bak" -Force}
[System.IO.File]::WriteAllText((Resolve-Path $Path),$Text.Replace($Old,$New),[System.Text.UTF8Encoding]::new($false)); Write-Host "Patched $Path" -ForegroundColor Green
