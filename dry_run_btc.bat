@echo off
title Finbot Dry-Run — BTC 1m

cd /d C:\HAL\Github\finbot

set "PYTHONPATH=."
set "FINBOT_HYPERLIQUID_TESTNET=false"
set "FINBOT_MODE=dry_run"

echo === Finbot Dry-Run ===
echo Symbol:  BTC
echo Interval: 1m
echo Mode:    dry_run (mainnet websocket, no orders)
echo.
echo Watching for candles... Ctrl+C to stop.
echo.

.venv313\Scripts\python.exe -m finbot.presentation.cli.main run --live-data --symbol BTC --interval 1m --strategy C:\HAL\Github\finbar\strategies\amt_dip_buyer_final.yaml

echo.
echo Bot stopped.
pause
