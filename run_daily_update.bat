@echo off
chcp 65001 > nul
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8

cd /d "C:\Users\lblac\OneDrive\Apps\RS_Clan_Analytics"

echo.
echo ==========================================
echo RS Clan Analytics daily update STARTED
echo %date% %time%
echo ==========================================

echo =============================== >> daily_update_log.txt
echo Daily update started: %date% %time% >> daily_update_log.txt

call .venv\Scripts\activate.bat

echo.
echo [1/2] Running clan totals...
echo [1/2] Running clan totals... >> daily_update_log.txt

python ingest_clan_totals.py >> daily_update_log.txt 2>&1

if errorlevel 1 (
    echo.
    echo ERROR: Clan totals failed. See daily_update_log.txt
    echo ERROR: Clan totals failed at %date% %time% >> daily_update_log.txt
    goto end_failed
)

echo.
echo [1/2] Clan totals complete.
echo [1/2] Clan totals complete. >> daily_update_log.txt

echo.
echo [2/2] Running skill collector...
echo [2/2] Running skill collector... >> daily_update_log.txt

python ingest_player.py >> daily_update_log.txt 2>&1

if errorlevel 1 (
    echo.
    echo ERROR: Skill collector failed. See daily_update_log.txt
    echo ERROR: Skill collector failed at %date% %time% >> daily_update_log.txt
    goto end_failed
)

echo.
echo [2/2] Skill collector complete.
echo [2/2] Skill collector complete. >> daily_update_log.txt

echo.
echo ==========================================
echo RS Clan Analytics daily update FINISHED OK
echo %date% %time%
echo ==========================================

echo Daily update finished OK: %date% %time% >> daily_update_log.txt
echo. >> daily_update_log.txt
goto end_success

:end_failed
echo.
echo ==========================================
echo RS Clan Analytics daily update FAILED
echo %date% %time%
echo Check daily_update_log.txt
echo ==========================================

echo Daily update FAILED: %date% %time% >> daily_update_log.txt
echo. >> daily_update_log.txt
exit /b 1

:end_success
exit /b 0