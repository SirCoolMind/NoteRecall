@echo off
REM NoteRecall - Windows launcher.
REM Installs uv if missing, builds .venv, installs requirements, starts the
REM server, and opens the browser once the server answers.
setlocal
cd /d "%~dp0"

if not defined HOST set "HOST=127.0.0.1"
if not defined PORT set "PORT=8756"
set "URL=http://%HOST%:%PORT%"

echo === NoteRecall ===

REM 1. uv
set "PATH=%USERPROFILE%\.local\bin;%USERPROFILE%\.cargo\bin;%PATH%"
where uv >nul 2>&1
if not errorlevel 1 goto have_uv
echo [1/4] Installing uv (Python toolchain manager)...
powershell -NoProfile -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
set "PATH=%USERPROFILE%\.local\bin;%USERPROFILE%\.cargo\bin;%PATH%"
where uv >nul 2>&1
if errorlevel 1 goto uv_failed
goto uv_done
:have_uv
echo [1/4] uv found.
goto uv_done
:uv_failed
echo ERROR: could not install uv. See https://docs.astral.sh/uv/ and retry.
pause
exit /b 1
:uv_done

REM 2. virtual environment (uv downloads Python itself if needed)
set "PY=.venv\Scripts\python.exe"
if exist "%PY%" goto have_venv
echo [2/4] Creating Python 3.12 environment in .venv ...
uv venv --python 3.12 .venv
if errorlevel 1 goto fail
goto venv_done
:have_venv
echo [2/4] Environment .venv found.
:venv_done

:deps
REM 3. dependencies (skipped when requirements are unchanged)
set "HAS_GPU=0"
nvidia-smi >nul 2>&1
if not errorlevel 1 set "HAS_GPU=1"
set "STAMP=.venv\.requirements.stamp"
set "NEWSTAMP=.venv\.requirements.new"
type requirements.txt > "%NEWSTAMP%"
if "%HAS_GPU%"=="1" type requirements-gpu.txt >> "%NEWSTAMP%"
if not exist "%STAMP%" goto install_deps
fc /b "%STAMP%" "%NEWSTAMP%" >nul 2>&1
if errorlevel 1 goto install_deps
echo [3/4] Dependencies up to date.
del "%NEWSTAMP%" >nul 2>&1
goto deps_done
:install_deps
echo [3/4] Installing dependencies...
uv pip install --python "%PY%" -r requirements.txt
if errorlevel 1 goto fail
if not "%HAS_GPU%"=="1" goto no_gpu
echo       NVIDIA GPU detected - adding CUDA libraries (~2.3 GB)...
uv pip install --python "%PY%" -r requirements-gpu.txt
if errorlevel 1 goto fail
goto gpu_done
:no_gpu
echo       No NVIDIA GPU - skipping CUDA libraries (CPU mode).
:gpu_done
move /y "%NEWSTAMP%" "%STAMP%" >nul
:deps_done

REM Speaker-detection models (~165 MB), only fetched once.
if exist "models\nemo_en_titanet_large.onnx" goto models_done
echo       Downloading speaker models...
if not exist models mkdir models
set "BASE=https://github.com/k2-fsa/sherpa-onnx/releases/download"
curl.exe -L -o "models\nemo_en_titanet_large.onnx" "%BASE%/speaker-recongition-models/nemo_en_titanet_large.onnx"
if errorlevel 1 goto models_failed
curl.exe -L -o "models\seg.tar.bz2" "%BASE%/speaker-segmentation-models/sherpa-onnx-pyannote-segmentation-3-0.tar.bz2"
if errorlevel 1 goto models_failed
tar.exe -xjf "models\seg.tar.bz2" -C models
if errorlevel 1 goto models_failed
del "models\seg.tar.bz2" >nul 2>&1
goto models_done
:models_failed
echo       Speaker model download failed - finish it from the in-app setup panel.
del "models\nemo_en_titanet_large.onnx" >nul 2>&1
del "models\seg.tar.bz2" >nul 2>&1
:models_done

REM 4. start the server; open the browser once it responds (only the first time:
REM after an in-app update the server exits with code 75 and comes back in this same tab)
if defined RESTARTED goto run_server
start "" /min powershell -NoProfile -WindowStyle Hidden -Command "$u='%URL%/api/status'; for($i=0;$i -lt 300;$i++){ try{ Invoke-WebRequest $u -UseBasicParsing -TimeoutSec 2 | Out-Null; Start-Process '%URL%'; break }catch{ Start-Sleep 1 } }"
echo [4/4] Starting NoteRecall at %URL% (close this window to stop)
:run_server
"%PY%" server.py
set "RC=%errorlevel%"
if "%RC%"=="75" goto restart
pause
exit /b 0

:restart
echo.
echo NoteRecall was updated and is restarting...
set "RESTARTED=1"
goto deps

:fail
echo.
echo ERROR: setup failed. See the messages above.
pause
exit /b 1
