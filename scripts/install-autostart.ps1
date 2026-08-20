#Requires -Version 5.1
<#
.SYNOPSIS
  Регистрирует автозапуск OPORA: после загрузки Windows, при входе
  и каждые 5 минут, если контейнеры остановились.
  Запускать от имени администратора.
#>
$ErrorActionPreference = "Stop"

$ScriptPath = Join-Path $PSScriptRoot "ensure-up.ps1"
if (-not (Test-Path $ScriptPath)) {
    throw "Не найден $ScriptPath"
}

$TaskName = "OPORA_Containers_Autostart"
$Argument = "-NoProfile -ExecutionPolicy Bypass -File `"$ScriptPath`""

$existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($existing) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    Write-Host "==> Старая задача $TaskName удалена"
}

$Action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument $Argument
$AtStartup = New-ScheduledTaskTrigger -AtStartup
$AtLogOn = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$Watch = New-ScheduledTaskTrigger -Once -At ((Get-Date).AddMinutes(1))
$Watch.Repetition = $(
    New-ScheduledTaskTrigger `
        -Once `
        -At (Get-Date) `
        -RepetitionInterval (New-TimeSpan -Minutes 5) `
        -RepetitionDuration (New-TimeSpan -Days 3650)
).Repetition
$Triggers = @($AtStartup, $AtLogOn, $Watch)
$Settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -MultipleInstances IgnoreNew `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 1)

$Principal = New-ScheduledTaskPrincipal `
    -UserId $env:USERNAME `
    -LogonType Interactive `
    -RunLevel Highest

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $Action `
    -Trigger $Triggers `
    -Settings $Settings `
    -Principal $Principal `
    -Description "Поднимает контейнеры OPORA (web + db) после перезагрузки и если они упали" | Out-Null

Write-Host "==> Задача '$TaskName' зарегистрирована."
Write-Host "==> Триггеры: старт Windows, вход в систему, каждые 5 минут."
Write-Host "==> В Docker Desktop включите: Settings → General → Start Docker Desktop when you sign in"
Write-Host "==> Проверка: powershell -File `"$ScriptPath`""
