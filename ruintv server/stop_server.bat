@echo off
REM Stops the RUIN.TO supervisor (start_server.vbs) and every program it keeps alive
REM (server.py, relay.py, library.py, grab.py). The supervisor dies FIRST, otherwise its
REM 5-second loop restarts the others while we are still killing them.
REM Run this before zipping, moving or deleting the folders.

setlocal

echo Stopping the supervisor first...
powershell -NoProfile -Command "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match 'start_server\.vbs' } | ForEach-Object { Write-Host ('  ' + $_.Name + ' (' + $_.ProcessId + ')'); Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"
timeout /t 2 /nobreak >nul

echo.
echo Stopping services...
powershell -NoProfile -Command "Get-CimInstance Win32_Process | Where-Object { $_.ProcessId -ne $PID -and $_.CommandLine -match 'server\.py|relay\.py|library\.py|grab\.py' } | ForEach-Object { Write-Host ('  ' + $_.Name + ' (' + $_.ProcessId + ')'); Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"
timeout /t 2 /nobreak >nul

echo.
echo Second sweep (children that came back)...
powershell -NoProfile -Command "Get-CimInstance Win32_Process | Where-Object { $_.ProcessId -ne $PID -and $_.CommandLine -match 'server\.py|relay\.py|library\.py|grab\.py|start_server\.vbs' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"
timeout /t 2 /nobreak >nul

echo.
echo Still alive:
powershell -NoProfile -Command "$left = Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match 'server\.py|relay\.py|library\.py|grab\.py|start_server\.vbs' }; if ($left) { $left | ForEach-Object { '  ' + $_.Name + ' ' + $_.ProcessId } } else { '  nothing' }"

echo.
echo Done. If the list above says "nothing", the folders and logs are free to zip.
pause