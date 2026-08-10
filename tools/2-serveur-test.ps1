<#
    ETAPE 2 - Serveur GesGym pour le test du lecteur.

    Demarre Django en acceptant l'adresse 192.0.0.100, celle par laquelle le
    lecteur viendra deposer ses evenements.

    Laisse cette fenetre OUVERTE pendant tous les tests : chaque scan s'y
    affiche en direct, et tout est aussi enregistre dans
    tools\journal-serveur.txt

    Pour arreter : Ctrl+C
#>

$ErrorActionPreference = "Continue"

$projectRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $projectRoot ".venv\Scripts\python.exe"
$journal = Join-Path $PSScriptRoot "journal-serveur.txt"

if (-not (Test-Path $python)) {
    Write-Host "Python introuvable : $python" -ForegroundColor Red
    exit 1
}

$env:DJANGO_ALLOWED_HOSTS = "127.0.0.1,localhost,192.168.1.71,192.0.0.100"

Write-Host ""
Write-Host "=== SERVEUR DE TEST GESGYM ===" -ForegroundColor Cyan
Write-Host ""
Write-Host "Interface  : http://127.0.0.1:8000"
Write-Host "Identifiant: test-lecteur"
Write-Host ""
Write-Host "URL webhook a saisir dans le lecteur :" -ForegroundColor Yellow

$webhook = & $python (Join-Path $projectRoot "manage.py") shell -c @"
from access.models import AccessDevice
device = AccessDevice.objects.first()
print(device.webhook_token if device else '')
"@ | Select-Object -Last 1

if ([string]::IsNullOrWhiteSpace($webhook)) {
    Write-Host "  AUCUN LECTEUR ENREGISTRE DANS L'APPLICATION." -ForegroundColor Red
    Write-Host "  Ouvre Controle d'acces > Lecteurs > Lancer la detection," -ForegroundColor Red
    Write-Host "  puis 'Utiliser ce lecteur'. L'URL apparaitra sur sa fiche." -ForegroundColor Red
} else {
    Write-Host "  http://192.0.0.100:8000/access/devices/webhook/$webhook/" -ForegroundColor Green
}

Write-Host ""
Write-Host "Journal : $journal"
Write-Host "Laisse cette fenetre ouverte. Ctrl+C pour arreter."
Write-Host ""

Set-Location $projectRoot

# La fusion des flux est faite par cmd, pas par PowerShell : en 5.1, un `2>&1`
# cote PowerShell emballe chaque ligne d'erreur d'un programme externe dans un
# objet d'erreur. Django journalisant sur la sortie d'erreur, tous ses messages
# normaux ressortaient alors comme des echecs (NativeCommandError).
cmd /c "`"$python`" manage.py runserver 0.0.0.0:8000 2>&1" | Tee-Object -FilePath $journal
