#Requires -Version 5.1
<#
.SYNOPSIS
  Обновляет код с origin/main и пересобирает Docker-контейнеры OPORA.
  Данные PostgreSQL (том postgres_data) не удаляются.
#>
$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $RepoRoot

Write-Host "==> OPORA deploy: $RepoRoot"

if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    throw "Git не найден в PATH. Установите Git for Windows."
}
if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    throw "Docker не найден в PATH. Установите Docker Desktop и дождитесь его запуска."
}

Write-Host "==> git fetch / reset to origin/main"
git fetch origin
git checkout main
git reset --hard origin/main

if (-not (Test-Path (Join-Path $RepoRoot ".env"))) {
    throw "Файл .env не найден. Скопируйте .env.example в .env и заполните секреты."
}

Write-Host "==> docker compose up --build -d"
docker compose up --build -d

Write-Host "==> Готово. Сайт: http://localhost:5000"
docker compose ps
