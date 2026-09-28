@echo off
title agent-rdp connect
rem set RDP_HOST=replica-host
rem set RDP_USER=user
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0connect.ps1"
