@echo off
setlocal
cd /d "%~dp0"

for /f %%I in ('powershell.exe -NoProfile -Command "Get-Date -Format yyyyMMdd-HHmmss-ffffff"') do set "NWO_SYNC_ID=%%I"
python -m nwoassets sync-runtime . -o "reports\sync-runtime-%NWO_SYNC_ID%.json"
if errorlevel 1 (
  echo Falha ao sincronizar os assets. Consulte o relatorio e a mensagem acima.
  exit /b 1
)

echo Assets sincronizados com o servidor e o client.
exit /b 0
