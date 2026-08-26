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
    $dossierExe = Join-Path $env:LOCALAPPDATA "RoyalGym\tunnel"
    $exe = Join-Path $dossierExe "cloudflared.exe"
    $dossierUtilisateur = Join-Path $env:USERPROFILE ".cloudflared"

    # Le service tourne sous le compte SYSTEME. Un emplacement commun a toute
    # la machine evite de dependre d'un profil utilisateur.
    $dossierService = "C:\ProgramData\RoyalGym\tunnel"

    foreach ($chemin in @($dossierExe, $dossierUtilisateur, $dossierService)) {
        if (-not (Test-Path $chemin)) {
            New-Item -ItemType Directory -Force -Path $chemin | Out-Null
        }
    }

    # --- 1. Le programme ---------------------------------------------------
    Etape "1/7  Programme cloudflared"
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
    Etape "2/7  Liaison avec le lecteur"
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
    Etape "3/7  Autorisation Cloudflare"
    $certificat = Join-Path $dossierUtilisateur "cert.pem"
    if (Test-Path $certificat) {
        Write-Host "     deja autorisee"
    } else {
        Write-Host "     une adresse va s'afficher, puis votre navigateur"
        Write-Host "     s'ouvrira : choisissez $Domaine et autorisez."
        & $exe tunnel login
        if (-not (Test-Path $certificat)) {
            Write-Host "     autorisation non terminee." -ForegroundColor Red
            Write-Host "     Relancez INSTALLER.cmd une fois connecte a Cloudflare."
            return
        }
        Write-Host "     autorisee" -ForegroundColor Green
    }

    # --- 4. Le tunnel -------------------------------------------------------
    Etape "4/7  Tunnel $nomTunnel"
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

    $identifiantsUtilisateur = Join-Path $dossierUtilisateur "$identifiant.json"
    if (-not (Test-Path $identifiantsUtilisateur)) {
        Write-Host "     fichier d'identifiants introuvable :" -ForegroundColor Red
        Write-Host "     $identifiantsUtilisateur" -ForegroundColor Red
        Write-Host "     Supprimez le tunnel dans Cloudflare, puis relancez."
        return
    }

    # --- 5. Configuration et nom public -------------------------------------
    Etape "5/7  Configuration"
    $identifiantsService = Join-Path $dossierService "$identifiant.json"
    Copy-Item -Path $identifiantsUtilisateur -Destination $identifiantsService -Force

    # Le tunnel ne publie qu'une chose : le lecteur. Le reste est refuse.
    $config = Join-Path $dossierService "config.yml"
    $contenu = @"
tunnel: $identifiant
credentials-file: $identifiantsService

ingress:
  - hostname: $hote
    service: http://${Lecteur}:${Port}
  - service: http_status:404
"@
    Set-Content -Path $config -Value $contenu -Encoding utf8
    Write-Host "     ecrite dans $config"

    & $exe tunnel route dns --overwrite-dns $nomTunnel $hote
    Write-Host "     $hote associe au tunnel" -ForegroundColor Green

    # --- 6. Service Windows --------------------------------------------------
    Etape "6/7  Service Windows"
    # On declare le service nous-memes plutot que d'utiliser
    # "cloudflared service install" : celui-ci enregistre un chemin sans le
    # moindre argument, et le service meurt a la seconde ou il demarre.
    if (Get-Service -Name "cloudflared" -ErrorAction SilentlyContinue) {
        Stop-Service -Name "cloudflared" -Force -ErrorAction SilentlyContinue
        & sc.exe delete cloudflared | Out-Null
        Start-Sleep -Seconds 3
    }

    $chemin = '"' + $exe + '" --config "' + $config + '" --no-autoupdate tunnel run'
    New-Service -Name "cloudflared" -DisplayName "RoyalGym - tunnel du lecteur" `
        -BinaryPathName $chemin -StartupType Automatic | Out-Null

    # Redemarrage automatique si le processus tombe : une coupure de courant
    # ne doit pas laisser la salle sans liaison jusqu'a la prochaine visite.
    & sc.exe failure cloudflared reset= 86400 `
        actions= restart/5000/restart/10000/restart/30000 | Out-Null

    Start-Service -Name "cloudflared"
    Start-Sleep -Seconds 5
    Write-Host "     $((Get-Service cloudflared).Status), demarrage automatique" -ForegroundColor Green

    # --- 7. Verification de bout en bout -------------------------------------
    Etape "7/7  Verification"
    # Le service peut tourner sans que le tunnel soit rattache. Seule une
    # requete reelle sur le nom public le prouve.
    Write-Host "     patientez, le tunnel s'annonce a Cloudflare..."
    Start-Sleep -Seconds 12

    # curl.exe est livre avec Windows 10 et rend le code sans lever
    # d'exception : Invoke-WebRequest affichait l'erreur brute juste avant la
    # ligne de conclusion, ce qui brouillait la lecture.
    $code = 0
    try {
        $code = [int](& curl.exe -s -o NUL -w "%{http_code}" --max-time 25 `
            "https://$hote/ISAPI/System/deviceInfo" 2>$null)
    } catch { $code = 0 }

    if ($code -eq 401) {
        # Le lecteur reclame ses identifiants : la chaine complete repond.
        Write-Host "     le lecteur repond a travers le tunnel" -ForegroundColor Green
    } elseif ($code -eq 530) {
        Write-Host "     le tunnel n'est pas rattache (erreur 1033)" -ForegroundColor Red
        Write-Host "     Lancez : Restart-Service cloudflared"
    } elseif ($code -eq 403) {
        Write-Host "     Cloudflare bloque l'appel (erreur 1010)" -ForegroundColor Yellow
        Write-Host "     Desactivez Browser Integrity Check pour $hote :"
        Write-Host "     Cloudflare > Rules > Configuration Rules."
    } elseif ($code -eq 0) {
        Write-Host "     aucune reponse du nom public" -ForegroundColor Red
        Write-Host "     Verifiez que $Domaine est bien gere par Cloudflare."
    } else {
        Write-Host "     reponse inattendue : HTTP $code" -ForegroundColor Yellow
    }

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
