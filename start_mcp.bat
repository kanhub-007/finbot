@echo off
title Finbot — MCP Server + Telegram

cd /d C:\HAL\Github\finbot

set "PYTHONPATH=."
set "FINBOT_TRANSPORT=http"

echo ==========================================
echo   Finbot MCP Server + Telegram
echo.
echo   HTTP API: http://127.0.0.1:8006
echo   Mode:     (from .env FINBOT_MODE)
echo ==========================================
echo.
echo Telegram commands:
echo   /run    - Start a trading bot
echo   /status - View bot status
echo   /stop   - Stop the bot
echo   /panic  - Emergency stop + cancel orders
echo   /whoami - Show your Telegram user ID
echo.

.venv313\Scripts\python.exe run_mcp.py

pause
