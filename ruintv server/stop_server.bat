@echo off
REM Stops the RUIN.TO supervisor (start_server.vbs), every service it keeps alive
REM (server.py, relay.py, library.py, grab.py), and any child ffmpeg/yt-dlp workers.
REM Pass --nopause when calling from another script.

setlocal

echo Stopping the supervisor first...
powershell -NoProfile -Command "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match 'start_server\.vbs' } | ForEach-Object { Write-Host ('  ' + $_.Name + ' (' + $_.ProcessId + ')'); Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"
timeout /t 2 /nobreak >nul

echo.
echo Stopping services and child workers...
powershell -NoProfile -Command "$svcs = Get-CimInstance Win32_Process | Where-Object { $_.ProcessId -ne $PID -and $_.CommandLine -match 'server\.py|relay\.py|library\.py|grab\.py' }; $svcPids = @($svcs | ForEach-Object { $_.ProcessId }); $children = Get-CimInstance Win32_Process | Where-Object { ($svcPids -contains $_.ParentProcessId) -or ($_.Name -match '^(ffmpeg|ffprobe|yt-dlp)\.exe$' -and $_.CommandLine -match 'D:\\movies') }; ($children + $svcs) | Sort-Object ProcessId -Unique | ForEach-Object { Write-Host ('  ' + $_.Name + ' (' + $_.ProcessId + ')'); Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"
timeout /t 2 /nobreak >nul

echo.
echo Second sweep (children that came back)...
powershell -NoProfile -Command "Get-CimInstance Win32_Process | Where-Object { $_.ProcessId -ne $PID -and ($_.CommandLine -match 'server\.py|relay\.py|library\.py|grab\.py|start_server\.vbs' -or ($_.Name -match '^(ffmpeg|ffprobe|yt-dlp)\.exe$' -and $_.CommandLine -match 'D:\\movies')) } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"
timeout /t 2 /nobreak >nul

echo.
echo Still alive:
powershell -NoProfile -Command "$left = Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match 'server\.py|relay\.py|library\.py|grab\.py|start_server\.vbs' }; if ($left) { $left | ForEach-Object { '  ' + $_.Name + ' ' + $_.ProcessId } } else { '  nothing' }"

echo.
echo Done. If the list above says "nothing", the folders and logs are free to zip.
if /I not "%~1"=="--nopause" if /I not "%~1"=="/nopause" pause