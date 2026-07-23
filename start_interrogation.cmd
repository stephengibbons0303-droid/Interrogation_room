@echo off
rem Starts the whole interrogation stack - double-click and play.
rem
rem Each service opens minimized and is skipped if its port is already
rem listening, so running this twice is harmless. Closing the four minimized
rem windows is how you stop everything.
rem
rem Ports are this repo's registered allocations - see ~/.claude/PORTS.md
rem (backend 8013, frontend 5185, speech pair C 7677 STT / 7678 TTS).
rem
rem Pass --no-open to skip launching the browser at the end, or --dry to only
rem PRINT what would be started (nothing is launched, browser stays shut).
setlocal
cd /d "%~dp0"

set VOICE_PY=%USERPROFILE%\.claude\voice\.venv\Scripts\python.exe
set BACKEND_PY=%~dp0backend\.venv\Scripts\python.exe

set RUN=start
set NOOPEN=
if "%~1"=="--no-open" set NOOPEN=1
if "%~1"=="--dry" set RUN=echo DRY start& set NOOPEN=1

echo Interrogation Room - starting services...

netstat -ano | findstr ":7678" | findstr "LISTENING" >nul
if not errorlevel 1 (
  echo   TTS       :7678  already running
) else (
  echo   TTS       :7678  starting - Kokoro
  %RUN% "Interrogation TTS :7678" /min cmd /k %VOICE_PY% backend\speech\tts_server.py
)

netstat -ano | findstr ":7677" | findstr "LISTENING" >nul
if not errorlevel 1 (
  echo   STT       :7677  already running
) else (
  echo   STT       :7677  starting - Whisper large-v3, check its window says CUDA
  %RUN% "Interrogation STT :7677" /min cmd /k %VOICE_PY% backend\speech\stt_server.py
)

netstat -ano | findstr ":8013" | findstr "LISTENING" >nul
if not errorlevel 1 (
  echo   Backend   :8013  already running
) else (
  echo   Backend   :8013  starting
  %RUN% "Interrogation Backend :8013" /min cmd /k %BACKEND_PY% -m uvicorn main:app --app-dir backend --port 8013
)

netstat -ano | findstr ":5185" | findstr "LISTENING" >nul
if not errorlevel 1 (
  echo   Frontend  :5185  already running
) else (
  echo   Frontend  :5185  starting
  rem The spawned window re-checks the port itself. Next.js silently hops to
  rem 5186 if 5185 is taken, and a second frontend on the wrong port is the one
  rem duplicate that does not crash loudly - it just sits there being wrong.
  %RUN% "Interrogation Frontend :5185" /min cmd /k "netstat -ano | findstr :5185 | findstr LISTENING >nul && (echo Frontend already on 5185 - close this window) || npm --prefix frontend run dev -- -p 5185"
)

if defined NOOPEN goto done

echo Waiting for the frontend to come up...
set tries=0
:waitloop
netstat -ano | findstr ":5185" | findstr "LISTENING" >nul
if not errorlevel 1 goto open
set /a tries+=1
if %tries% geq 30 goto open
ping -n 3 127.0.0.1 >nul
goto waitloop

:open
start "" http://localhost:5185

:done
echo Done. Services run minimized - close their windows to stop them.
ping -n 4 127.0.0.1 >nul
