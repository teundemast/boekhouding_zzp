@echo off
rem Dubbelklik dit bestand om de boekhouding te starten.
rem Zolang dit venster open staat, draait het programma. Sluiten = afsluiten.
title Boekhouding - laat dit venster open staan
cd /d "%~dp0"

where python >nul 2>&1
if errorlevel 1 (
    echo.
    echo   Python is niet gevonden op deze computer.
    echo.
    echo   Dit programma heeft Python nodig. Installeren duurt twee minuten:
    echo.
    echo     1. Ga naar  https://www.python.org/downloads/
    echo     2. Klik op de gele knop "Download Python"
    echo     3. BELANGRIJK: zet in het installatievenster een vinkje bij
    echo        "Add python.exe to PATH", onderaan het scherm
    echo     4. Klik op Install Now
    echo     5. Start je computer opnieuw op en dubbelklik dit bestand nog eens
    echo.
    pause
    exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
    echo.
    echo   Eenmalige installatie. Dit duurt een minuut of twee, even geduld...
    echo.
    python -m venv .venv
    if errorlevel 1 goto installatiefout
    .venv\Scripts\python.exe -m pip install --quiet --upgrade pip
    .venv\Scripts\python.exe -m pip install --quiet -r requirements.txt
    if errorlevel 1 goto installatiefout
    echo   Klaar. Het programma start nu.
    echo.
)

.venv\Scripts\python.exe -m tools.run %*
if errorlevel 1 (
    echo.
    echo   Er ging iets mis. Hierboven staat waarom.
    pause
)
exit /b 0

:installatiefout
echo.
echo   De installatie is niet gelukt. Hierboven staat waarom.
echo   Verwijder de map .venv en probeer het nog eens.
echo.
pause
exit /b 1
