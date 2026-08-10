#Requires -Version 5.1
<#
.SYNOPSIS
  Ежедневный бэкап PostgreSQL (контейнер opora_db) на рабочий стол.
  Каталог: %USERPROFILE%\Desktop\OPORA_backups
  Хранение: 14 дней.
#>
$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $PSScriptRoot
$EnvFile = Join-Path $RepoRoot ".env"
$ContainerName = "opora_db"
$KeepDays = 14

$Desktop = [Environment]::GetFolderPath("Desktop")
$BackupDir = Join-Path $Desktop "OPORA_backups"
New-Item -ItemType Directory -Force -Path $BackupDir | Out-Null

function Get-DotEnvValue {
    param(
        [string]$Path,
        [string]$Key,
        [string]$Default = ""
    )
    if (-not (Test-Path $Path)) { return $Default }
    foreach ($line in Get-Content $Path -Encoding UTF8) {
        $t = $line.Trim()
        if ($t -match '^\s*#' -or $t -eq "") { continue }
        if ($t -match "^\s*$([regex]::Escape($Key))\s*=\s*(.*)$") {
            $val = $Matches[1].Trim()
            if ($val.StartsWith('"') -and $val.EndsWith('"')) {
                $val = $val.Substring(1, $val.Length - 2)
            }
            return $val
        }
    }
    return $Default
}

$PgUser = Get-DotEnvValue -Path $EnvFile -Key "POSTGRES_USER" -Default "opora_user"
$PgDb = Get-DotEnvValue -Path $EnvFile -Key "POSTGRES_DB" -Default "opora"

$running = docker inspect -f "{{.State.Running}}" $ContainerName 2>$null
if ($running -ne "true") {
    throw "Контейнер $ContainerName не запущен. Бэкап пропущен."
}

$stamp = Get-Date -Format "yyyy-MM-dd"
$outFile = Join-Path $BackupDir "opora_$stamp.dump"

Write-Host "==> Бэкап $PgDb -> $outFile"
docker exec $ContainerName pg_dump -U $PgUser -d $PgDb -Fc -f "/tmp/opora_backup.dump"
docker cp "${ContainerName}:/tmp/opora_backup.dump" $outFile
docker exec $ContainerName rm -f /tmp/opora_backup.dump

if (-not (Test-Path $outFile)) {
    throw "Файл бэкапа не создан: $outFile"
}

$cutoff = (Get-Date).AddDays(-$KeepDays)
Get-ChildItem -Path $BackupDir -Filter "opora_*.dump" -File |
    Where-Object { $_.LastWriteTime -lt $cutoff } |
    ForEach-Object {
        Write-Host "==> Удаление старого бэкапа: $($_.Name)"
        Remove-Item $_.FullName -Force
    }

Write-Host "==> Готово: $outFile ($([math]::Round((Get-Item $outFile).Length / 1MB, 2)) MB)"
