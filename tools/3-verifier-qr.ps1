<#
    Le lecteur sait-il lire un QR code ?

    A lancer avec Proton VPN ferme. Ne modifie rien sur le lecteur.
    Resultat complet dans tools\verdict-qr.txt

    Ce script n'echoue jamais en silence : toute erreur, y compris celles des
    programmes appeles, est ecrite a l'ecran et dans le fichier.
#>

$ErrorActionPreference = "Continue"

$projectRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $projectRoot ".venv\Scripts\python.exe"
$manage = Join-Path $projectRoot "manage.py"
$rapport = Join-Path $PSScriptRoot "verdict-qr.txt"

# Tee-Object plutot que Start-Transcript : le transcript ne capture pas la
# sortie d'erreur des executables natifs, ce qui produisait un rapport vide
# alors que le script avait echoue.
$sortie = New-Object System.Collections.Generic.List[string]

function Trace($texte, $couleur = "Gray") {
    Write-Host $texte -ForegroundColor $couleur
    $sortie.Add($texte)
}

Trace ""
Trace "=== LE LECTEUR SAIT-IL LIRE UN QR CODE ? ===" "Cyan"
Trace "Date : $(Get-Date -Format 'dd/MM/yyyy HH:mm:ss')"
Trace ""

$echec = $false

# --- 1. Environnement -------------------------------------------------------
if (-not (Test-Path $python)) {
    Trace "ECHEC : interpreteur Python introuvable." "Red"
    Trace "  Attendu ici : $python"
    Trace "  Recree l'environnement : py -3.12 -m venv .venv puis"
    Trace "  .venv\Scripts\python.exe -m pip install -r requirements.txt"
    $echec = $true
}
elseif (-not (Test-Path $manage)) {
    Trace "ECHEC : manage.py introuvable ($manage)." "Red"
    Trace "  Lance ce script depuis le dossier tools du projet."
    $echec = $true
}

# --- 2. VPN -----------------------------------------------------------------
if (-not $echec) {
    $protonProcs = @(Get-Process -ErrorAction SilentlyContinue | Where-Object { $_.ProcessName -match "Proton" })
    $protun = Get-NetAdapter -ErrorAction SilentlyContinue | Where-Object { $_.Name -eq "ProTUN" -and $_.Status -eq "Up" }

    if ($protonProcs.Count -gt 0 -or $protun) {
        Trace "ECHEC : Proton VPN est encore actif, le lecteur est injoignable." "Red"
        Trace "  Processus Proton : $($protonProcs.Count)"
        Trace "  Adaptateur ProTUN actif : $([bool]$protun)"
        Trace "  Settings > Kill switch > desactiver, puis Quit. Puis relance ce script."
        $echec = $true
    }
}

# --- 3. Interrogation du lecteur --------------------------------------------
if (-not $echec) {
    Trace "Interrogation du lecteur en cours..." "Yellow"
    Trace ""

    # 2>&1 : la sortie d'erreur est fusionnee pour etre capturee elle aussi.
    $resultat = & $python $manage verifier_qr 2>&1 | ForEach-Object { $_.ToString() }
    $code = $LASTEXITCODE

    foreach ($ligne in $resultat) { Trace $ligne }

    if ($code -ne 0 -or -not $resultat) {
        Trace ""
        Trace "ECHEC : la commande s'est terminee anormalement (code $code)." "Red"
        $echec = $true
    }
}

Trace ""
Trace "Rapport enregistre dans : $rapport"
Trace ""

$sortie | Set-Content -Path $rapport -Encoding UTF8

if ($echec) { exit 1 }
exit 0
