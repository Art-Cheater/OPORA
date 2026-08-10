#Requires -Version 5.1
<#
.SYNOPSIS
  Регистрирует ежедневный бэкап БД OPORA в Планировщике заданий Windows (03:00).
  Запускать от имени администратора.
#>
$ErrorActionPreference = "Stop"

$ScriptPath = Join-Path $PSScriptRoot "backup-db.ps1"
if (-not (Test-Path $ScriptPath)) {
    throw "Не найден $ScriptPath"
}

$TaskName = "OPORA_DB_Backup_Daily"
$Argument = "-NoProfile -ExecutionPolicy Bypass -File `"$ScriptPath`""

$existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($existing) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    Write-Host "==> Старая задача $TaskName удалена"
}

$Action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument $Argument
$Trigger = New-ScheduledTaskTrigger -Daily -At 3:00am
$Settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -MultipleInstances IgnoreNew

$Principal = New-ScheduledTaskPrincipal `
    -UserId $env:USERNAME `
    -LogonType Interactive `
    -RunLevel Highest

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $Action `
    -Trigger $Trigger `
    -Settings $Settings `
    -Principal $Principal `
    -Description "Ежедневный бэкап PostgreSQL OPORA на рабочий стол (Desktop\OPORA_backups)" | Out-Null

Write-Host "==> Задача '$TaskName' зарегистрирована (ежедневно в 03:00)."
Write-Host "==> Проверка вручную: powershell -File `"$ScriptPath`""
