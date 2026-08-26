<#
    Tunnel permanent - adresse fixe, service Windows, redemarrage automatique.

    Ne lancez pas ce fichier directement : double-cliquez INSTALLER.cmd, qui
    demande les droits administrateur, contourne la strategie d'execution et
    garde la fenetre ouverte pour que vous puissiez lire ce qui s'est passe.

    Le domaine royalgym.site doit etre gere par Cloudflare. Ce n'est pas le
    domaine du site des membres : celui-ci n'est jamais touche.

    Pour une autre salle ou un autre lecteur :
        INSTALLER.cmd -Salle bandal -Lecteur 192.168.1.50
#>

param(
    [string]$Salle = "royal",
    [string]$Domaine = "royalgym.site",
    [string]$Lecteur = "192.168.1.188",
    [int]$Port = 80
)

$ErrorActionPreference = "Stop"

# Tout est trace : si la fenetre se ferme malgre tout, le journal reste.
$journal = Join-Path $env:LOCALAPPDATA "RoyalGym\installation-tunnel.log"
$dossierJournal = Split-Path $journal -Parent
if (-not (Test-Path $dossierJournal)) {
    New-Item -ItemType Directory -Force -Path $dossierJournal | Out-Null
}
try { Start-Transcript -Path $journal -Append | Out-Null } catch { }

function Etape($texte) {
    Write-Host ""
    Write-Host $texte -ForegroundColor Cyan
}

try {
    Write-Host "Salle   : $Salle"
    Write-Host "Domaine : $Domaine"
    Write-Host "Lecteur : $Lecteur port $Port"

    $identite = [Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()
    if (-not $identite.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
        Write-Host ""
        Write-Host "Droits administrateur absents." -ForegroundColor Red
        Write-Host "Fermez cette fenetre et double-cliquez INSTALLER.cmd."
        return
    }

    $nomTunnel = "royalgym-$Salle"
    $hote = "$Salle.$Domaine"
    $dossier = Join-Path $env:LOCALAPPDATA "RoyalGym\tunnel"
    $exe = Join-Path $dossier "cloudflared.exe"
    $dossierCloudflare = Join-Path $env:USERPROFILE ".cloudflared"
    $configuration = Join-Path $dossierCloudflare "config.yml"

    foreach ($chemin in @($dossier, $dossierCloudflare)) {
        if (-not (Test-Path $chemin)) {
            New-Item -ItemType Directory -Force -Path $chemin | Out-Null
        }
    }

    # --- 1. Le programme ---------------------------------------------------
    Etape "1/6  Programme cloudflared"
    if (Test-Path $exe) {
        Write-Host "     deja present"
    } else {
        Write-Host "     telechargement (environ 55 Mo), patientez..."
        $source = "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe"
        Invoke-WebRequest -Uri $source -OutFile $exe -UseBasicParsing
        Write-Host "     telecharge"
    }
    try { Unblock-File -Path $exe } catch { }

    # --- 2. Le lecteur repond-il ? -----------------------------------------
    Etape "2/6  Liaison avec le lecteur"
    $liaison = Test-NetConnection -ComputerName $Lecteur -Port $Port -WarningAction SilentlyContinue
    if (-not $liaison.TcpTestSucceeded) {
        Write-Host "     le lecteur ne repond pas sur $Lecteur : $Port" -ForegroundColor Red
        Write-Host ""
        Write-Host "     Verifiez qu'il est allume, et que cette machine est"
        Write-Host "     bien sur le meme reseau. Son adresse figure sur sa"
        Write-Host "     fiche dans l'application."
        return
    }
    Write-Host "     le lecteur repond" -ForegroundColor Green

    # --- 3. Autorisation Cloudflare ----------------------------------------
    Etape "3/6  Autorisation Cloudflare"
    $certificat = Join-Path $dossierCloudflare "cert.pem"
    if (Test-Path $certificat) {
        Write-Host "     deja autorisee"
    } else {
        Write-Host "     votre navigateur va s'ouvrir : choisissez $Domaine,"
        Write-Host "     puis revenez ici."
        & $exe tunnel login
        if (-not (Test-Path $certificat)) {
            Write-Host "     autorisation non terminee." -ForegroundColor Red
            Write-Host "     Relancez INSTALLER.cmd une fois connecte a Cloudflare."
            return
        }
        Write-Host "     autorisee" -ForegroundColor Green
    }

    # --- 4. Le tunnel -------------------------------------------------------
    Etape "4/6  Tunnel $nomTunnel"
    $existants = (& $exe tunnel list 2>&1 | Out-String)
    if ($existants -match [regex]::Escape($nomTunnel)) {
        Write-Host "     existe deja, reutilise"
    } else {
        & $exe tunnel create $nomTunnel
        Write-Host "     cree" -ForegroundColor Green
    }

    # Le fichier d'identifiants porte l'identifiant du tunnel, pas son nom.
    $ligne = (& $exe tunnel list 2>&1 | Out-String) -split "`n" |
        Where-Object { $_ -match [regex]::Escape($nomTunnel) } |
        Select-Object -First 1
    $identifiant = ($ligne -split "\s+" | Where-Object { $_ } | Select-Object -First 1)

    $fichierIdentifiants = Join-Path $dossierCloudflare "$identifiant.json"
    if (-not (Test-Path $fichierIdentifiants)) {
        Write-Host "     fichier d'identifiants introuvable :" -ForegroundColor Red
        Write-Host "     $fichierIdentifiants" -ForegroundColor Red
        Write-Host "     Supprimez le tunnel dans Cloudflare, puis relancez."
        return
    }

    # --- 5. Configuration et nom public -------------------------------------
    Etape "5/6  Configuration"
    # Le tunnel ne publie qu'une chose : le lecteur. Le reste est refuse.
    $contenu = @"
tunnel: $identifiant
credentials-file: $fichierIdentifiants

ingress:
  - hostname: $hote
    service: http://${Lecteur}:${Port}
  - service: http_status:404
"@
    Set-Content -Path $configuration -Value $contenu -Encoding utf8
    Write-Host "     ecrite dans $configuration"

    & $exe tunnel route dns --overwrite-dns $nomTunnel $hote
    Write-Host "     $hote associe au tunnel" -ForegroundColor Green

    # --- 6. Service Windows --------------------------------------------------
    Etape "6/6  Service Windows"
    # Sans service, le tunnel meurt avec la session : apres une coupure de
    # courant, personne ne penserait a le relancer.
    $service = Get-Service -Name "cloudflared" -ErrorAction SilentlyContinue
    if ($service) {
        Restart-Service -Name "cloudflared"
        Write-Host "     redemarre"
    } else {
        & $exe service install
        Start-Service -Name "cloudflared"
        Write-Host "     installe et demarre"
    }
    Set-Service -Name "cloudflared" -StartupType Automatic
    Write-Host "     demarrage automatique active" -ForegroundColor Green

    Write-Host ""
    Write-Host "----------------------------------------------" -ForegroundColor Green
    Write-Host " Termine." -ForegroundColor Green
    Write-Host "----------------------------------------------" -ForegroundColor Green
    Write-Host ""
    Write-Host " Dans l'application, fiche du lecteur, bouton Modifier :"
    Write-Host ""
    Write-Host "   Adresse ou nom d'hote : $hote"
    Write-Host "   Port                  : 443"
    Write-Host "   Lecteur joint par un tunnel (HTTPS) : coche"
    Write-Host "   Mot de passe          : laisser vide"
    Write-Host ""
    Write-Host " Puis protegez ce nom par un jeton Cloudflare Access."
    Write-Host " Sans ce jeton, le lecteur est joignable par qui connait" -ForegroundColor Yellow
    Write-Host " l'adresse. La marche a suivre est dans LISEZMOI.md." -ForegroundColor Yellow
}
catch {
    Write-Host ""
    Write-Host "L'installation s'est interrompue." -ForegroundColor Red
    Write-Host $_.Exception.Message -ForegroundColor Red
    Write-Host ""
    Write-Host "Le detail est conserve dans :"
    Write-Host "   $journal"
}
finally {
    try { Stop-Transcript | Out-Null } catch { }
}
