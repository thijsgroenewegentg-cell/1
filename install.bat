@echo off
REM =========================================================
REM  VoiceOS - simple installer ^& launcher (Windows)
REM  No downloads needed: uses Python or Node you already have.
REM =========================================================
title VoiceOS
cd /d "%~dp0"

echo.
echo    VoiceOS v1.0 - Say it once, let it go.
echo.

REM Already running? Just open it.
curl -s --max-time 2 http://localhost:8080 >nul 2>nul
if %errorlevel%==0 (
  echo    VoiceOS is already running - opening it.
  start "" http://localhost:8080
  exit /b 0
)

where python >nul 2>nul
if %errorlevel%==0 (
  echo    Starting VoiceOS at http://localhost:8080
  start "" http://localhost:8080
  python -m http.server 8080 --bind 127.0.0.1
  exit /b 0
)

where py >nul 2>nul
if %errorlevel%==0 (
  echo    Starting VoiceOS at http://localhost:8080
  start "" http://localhost:8080
  py -m http.server 8080 --bind 127.0.0.1
  exit /b 0
)

where node >nul 2>nul
if %errorlevel%==0 (
  echo    Starting VoiceOS at http://localhost:8080
  start "" http://localhost:8080
  node -e "const http=require('http'),fs=require('fs'),path=require('path');const types={'.html':'text/html','.css':'text/css','.js':'text/javascript','.png':'image/png','.webmanifest':'application/manifest+json'};http.createServer((req,res)=>{let f=path.join(process.cwd(),decodeURIComponent(req.url.split('?')[0]));if(f.endsWith(path.sep))f+='index.html';fs.readFile(f,(e,d)=>{if(e){res.writeHead(404);res.end('not found');return;}res.writeHead(200,{'Content-Type':types[path.extname(f)]||'application/octet-stream'});res.end(d);});}).listen(8080,'127.0.0.1');"
  exit /b 0
)

echo    Neither Python nor Node was found on this PC.
echo    Install either one ^(both free^), then double-click this file again.
echo       Python: https://www.python.org/downloads/
echo       Node:   https://nodejs.org/
echo.
pause
