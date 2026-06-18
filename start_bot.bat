@echo off
title Finbot — Live Trading Runtime

cd /d C:\HAL\Github\finbot

set "PYTHONPATH=."

echo ==========================================
echo   Finbot Live Trading Runtime
echo.
echo   Mode:     (from .env FINBOT_MODE)
echo   Strategy: strategies\amt_dip_buyer_final.yaml
echo   Symbol:   BTC    Interval: 1h
echo ==========================================
echo.

.venv313\Scripts\python.exe -m finbot.presentation.cli.main run --live-data --strategy strategies/amt_dip_buyer_final.yaml --symbol BTC --interval 1h

pause
