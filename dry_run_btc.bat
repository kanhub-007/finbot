@echo off
title Finbot Dry-Run — BTC 1m on Mainnet

cd /d C:\HAL\Github\finbot

set "PYTHONPATH=."
set "FINBOT_HYPERLIQUID_TESTNET=false"
set "FINBOT_MODE=dry_run"

echo ==========================================
echo   Finbot Dry-Run (Mainnet, No Private Key)
echo   Symbol: BTC   Interval: 1m
echo ==========================================
echo.

set "STRATEGY=%~dp0tests\fixtures\strategies\amt_dip_buyer_final.yaml"

.venv313\Scripts\python.exe -m finbot.presentation.cli.main run --live-data --symbol BTC --interval 1m --strategy "%STRATEGY%"

pause
