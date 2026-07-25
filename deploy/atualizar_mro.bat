@echo off
REM ============================================================================
REM  Sistema MRO — atualizacao no PC-servidor (v5.5.0 / F5)
REM
REM  Uso:  atualizar_mro.bat C:\caminho\mro-5.6.0.zip
REM
REM  Sequencia: para a tarefa -> backup do banco -> troca app\ -> religa.
REM  O banco NAO e tocado: vive em dados\, fora de app\.
REM  Copie este arquivo para C:\MRO\atualizar_mro.bat.
REM ============================================================================
setlocal

set "MRO_RAIZ=%~dp0"
set "PACOTE=%~1"
set "TAREFA=Sistema MRO"

if "%PACOTE%"=="" (
    echo ERRO: informe o zip da release. Ex: atualizar_mro.bat C:\temp\mro-5.6.0.zip
    exit /b 1
)
if not exist "%PACOTE%" (
    echo ERRO: pacote nao encontrado: %PACOTE%
    exit /b 1
)

echo [1/5] Parando a tarefa "%TAREFA%"...
schtasks /End /TN "%TAREFA%" >nul 2>&1
REM Espera o processo soltar o banco antes de mexer em qualquer arquivo.
timeout /t 5 /nobreak >nul

echo [2/5] Backup do banco...
set "CARIMBO=%DATE:~6,4%%DATE:~3,2%%DATE:~0,2%-%TIME:~0,2%%TIME:~3,2%%TIME:~6,2%"
set "CARIMBO=%CARIMBO: =0%"
if not exist "%MRO_RAIZ%dados\backups\" mkdir "%MRO_RAIZ%dados\backups"
if exist "%MRO_RAIZ%dados\mro.db" (
    copy /Y "%MRO_RAIZ%dados\mro.db" "%MRO_RAIZ%dados\backups\mro.db.bak-%CARIMBO%-pre-atualizacao" >nul
    if errorlevel 1 (
        echo ERRO: backup falhou. Atualizacao ABORTADA.
        schtasks /Run /TN "%TAREFA%" >nul 2>&1
        exit /b 1
    )
) else (
    echo   Aviso: dados\mro.db nao existe ainda — seguindo sem backup.
)

echo [3/5] Guardando a versao anterior em app_anterior\...
if exist "%MRO_RAIZ%app_anterior" rmdir /S /Q "%MRO_RAIZ%app_anterior"
if exist "%MRO_RAIZ%app" move "%MRO_RAIZ%app" "%MRO_RAIZ%app_anterior" >nul

echo [4/5] Extraindo a nova versao...
powershell -NoProfile -Command "Expand-Archive -LiteralPath '%PACOTE%' -DestinationPath '%MRO_RAIZ%app' -Force"
if errorlevel 1 (
    echo ERRO na extracao — restaurando a versao anterior.
    if exist "%MRO_RAIZ%app" rmdir /S /Q "%MRO_RAIZ%app"
    move "%MRO_RAIZ%app_anterior" "%MRO_RAIZ%app" >nul
    schtasks /Run /TN "%TAREFA%" >nul 2>&1
    exit /b 1
)

echo [5/5] Religando...
schtasks /Run /TN "%TAREFA%"

echo.
echo Atualizacao concluida. Versao anterior preservada em app_anterior\.
echo Rollback: pare a tarefa, apague app\, renomeie app_anterior\ para app\ e religue.
exit /b 0
