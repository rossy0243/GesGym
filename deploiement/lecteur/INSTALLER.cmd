@echo off
setlocal
cd /d "%~dp0"

rem Lanceur de l'installation permanente.
rem
rem Il existe pour supprimer les quatre facons de ne rien voir se passer :
rem un double-clic sur le .ps1 l'ouvre dans l'editeur au lieu de l'executer ;
rem la strategie d'execution refuse les scripts ; un fichier venu d'une cle USB
rem est marque comme provenant d'internet ; et la fenetre se referme avant
rem qu'on ait pu lire l'erreur.

net session >nul 2>&1
if not "%errorlevel%"=="0" (
    echo Cette installation demande les droits administrateur.
    echo Une demande d'autorisation va s'afficher.
    echo.
    powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b
)

echo ================================================
echo   RoyalGym - installation du tunnel du lecteur
echo ================================================
echo.

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0tunnel-permanent.ps1" %*

echo.
echo ================================================
echo Appuyez sur une touche pour fermer cette fenetre.
pause >nul
