@echo off
title OpenClaw 启动器
wsl -d Ubuntu-24.04 systemctl --user start openclaw-gateway
timeout /t 3 /nobreak >nul
start http://127.0.0.1:18789/
echo ✅ OpenClaw 已启动
pause
