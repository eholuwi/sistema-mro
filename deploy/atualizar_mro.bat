@echo off
REM ============================================================================
REM  Sistema MRO - atualizacao manual no PC-servidor (break-glass)
REM
REM  TRES formas de usar, todas equivalentes:
REM    1. ARRASTE o mro-<versao>.zip para cima deste arquivo   <- a mais facil
REM    2. Duplo clique (ele procura o zip mais novo em Downloads/Desktop/temp)
REM    3. Linha de comando:  C:\MRO\atualizar_mro.bat C:\temp\mro-6.6.0.zip
REM
REM  Sequencia: para o sistema -> backup do banco -> troca app\ -> religa.
REM  O banco NAO e tocado: vive em dados\, fora de app\.
REM  Este arquivo mora na RAIZ da instalacao (C:\MRO\atualizar_mro.bat), fora de
REM  app\, de proposito: e o caminho de recuperacao para quando o app nao sobe, e
REM  um atualizador que vive dentro da pasta que ele substitui nao recupera nada.
REM
REM  O caminho NORMAL a partir da v6.6.0 e pelo proprio app (Configuracoes >
REM  Atualizacao), que usa deploy\aplicar_atualizacao.bat. Este aqui e o plano B.
REM ============================================================================
setlocal enabledelayedexpansion

set "MRO_RAIZ=%~dp0"
set "PACOTE=%~1"
set "TAREFA=Sistema MRO"

REM Codigo de saida: 0 = ok/cancelado pelo usuario, 1 = falhou. Todo caminho de erro
REM passa por :fim, que PAUSA antes de fechar - a janela fechando sozinha era o motivo
REM de "rodei e nao deu nada". O `exit /b` continua honesto para quem chamar por script.
set "ERRO=0"

echo.
echo === Sistema MRO - atualizacao manual ===
echo.

REM Sem argumento (duplo clique): procura o zip mais novo nos lugares de sempre.
if "%PACOTE%"=="" (
    echo Nenhum pacote informado - procurando o mro-*.zip mais recente...
    for %%D in ("%USERPROFILE%\Downloads" "%USERPROFILE%\Desktop" "C:\temp" "%MRO_RAIZ%.") do (
        if not defined PACOTE (
            for /f "delims=" %%F in ('dir /b /o-d "%%~D\mro-*.zip" 2^>nul') do (
                if not defined PACOTE set "PACOTE=%%~D\%%F"
            )
        )
    )
)

if "%PACOTE%"=="" (
    echo.
    echo Nao achei nenhum pacote.
    echo.
    echo Arraste o arquivo mro-^<versao^>.zip para cima deste .bat,
    echo ou deixe o zip na pasta Downloads e rode de novo.
    set "ERRO=1"
    goto fim
)
if not exist "%PACOTE%" (
    echo ERRO: pacote nao encontrado: %PACOTE%
    set "ERRO=1"
    goto fim
)
if not exist "%MRO_RAIZ%app" (
    echo ERRO: nao achei "%MRO_RAIZ%app".
    echo        Este .bat precisa ficar na RAIZ da instalacao, ao lado da pasta app\.
    set "ERRO=1"
    goto fim
)

echo Pacote : %PACOTE%
echo Destino: %MRO_RAIZ%app
echo.
set "OK="
set /p "OK=Atualizar agora? (S/N): "
if /I not "%OK%"=="S" (
    echo Cancelado - nada foi alterado.
    goto fim
)
echo.

echo [1/5] Parando o sistema...
schtasks /Query /TN "%TAREFA%" >nul 2>&1
if not errorlevel 1 (
    set "TEM_TAREFA=1"
    schtasks /End /TN "%TAREFA%" >nul 2>&1
)
REM Espera o processo soltar o banco antes de mexer em qualquer arquivo.
ping -n 6 127.0.0.1 >nul 2>&1

echo [2/5] Backup do banco...
set "CARIMBO=%DATE:~6,4%%DATE:~3,2%%DATE:~0,2%-%TIME:~0,2%%TIME:~3,2%%TIME:~6,2%"
set "CARIMBO=%CARIMBO: =0%"
if not exist "%MRO_RAIZ%dados\backups\" mkdir "%MRO_RAIZ%dados\backups"
if exist "%MRO_RAIZ%dados\mro.db" (
    copy /Y "%MRO_RAIZ%dados\mro.db" "%MRO_RAIZ%dados\backups\mro.db.bak-%CARIMBO%-pre-atualizacao" >nul
    if errorlevel 1 (
        echo ERRO: backup falhou. Atualizacao ABORTADA.
        goto religar
    )
) else (
    echo   Aviso: dados\mro.db nao existe ainda - seguindo sem backup.
)

echo [3/5] Guardando a versao anterior em app_anterior\...
if exist "%MRO_RAIZ%app_anterior" rmdir /S /Q "%MRO_RAIZ%app_anterior"
if exist "%MRO_RAIZ%app" move "%MRO_RAIZ%app" "%MRO_RAIZ%app_anterior" >nul

REM v5.8.0 - se o move falhou (alguem segurando arquivo em app\), ABORTAR aqui.
REM Sem esta guarda o script seguia e o Expand-Archive -Force do passo 4 escrevia por
REM cima da versao antiga: duas versoes misturadas na mesma pasta, sem aviso nenhum.
if exist "%MRO_RAIZ%app" (
    echo ERRO: nao consegui mover app\ - algo ainda esta usando a pasta.
    echo        FECHE a janela preta do MRO e tente de novo.
    echo        Atualizacao ABORTADA - nada foi alterado.
    REM Aborta ANTES do Expand-Archive. `goto fim` em vez de `exit /b 1` direto so para
    REM a janela PAUSAR e mostrar o motivo; o codigo de saida 1 vem do ERRO.
    set "ERRO=1"
    goto fim
)

echo [4/5] Extraindo a nova versao...
powershell -NoProfile -Command "Expand-Archive -LiteralPath '%PACOTE%' -DestinationPath '%MRO_RAIZ%app' -Force"
if errorlevel 1 goto restaurar
if not exist "%MRO_RAIZ%app\app.py" goto restaurar
set "TROCOU=1"
goto religar

:restaurar
echo ERRO na extracao - restaurando a versao anterior.
if exist "%MRO_RAIZ%app" rmdir /S /Q "%MRO_RAIZ%app"
move "%MRO_RAIZ%app_anterior" "%MRO_RAIZ%app" >nul 2>&1

:religar
echo [5/5] Religando...
REM Dois caminhos, porque nem toda instalacao usa tarefa agendada. A versao anterior
REM so chamava `schtasks /Run`: em maquina SEM a tarefa (o caso do PC da sala MRO, onde
REM o antivirus corporativo tratou a tarefa como ameaca) o sistema ficava NO CHAO depois
REM da atualizacao, sem nenhuma mensagem dizendo isso. (Eram tres ate a v6.8.1, quando
REM o MRO.exe ainda existia.)
if defined TEM_TAREFA (
    schtasks /Run /TN "%TAREFA%" >nul 2>&1
    echo   tarefa agendada reiniciada
) else (
    REM v6.8.2 - o ramo do MRO.exe saiu junto com o PyInstaller. Quem sobe o sistema
    REM sempre foi este bat; o exe so dava o duplo clique, hoje feito pelo atalho MRO.lnk
    REM (que aponta para ele). Um `if exist MRO.exe` aqui seria ramo morto.
    if exist "%MRO_RAIZ%iniciar_mro.bat" (
        start "" "%MRO_RAIZ%iniciar_mro.bat"
        echo   iniciar_mro.bat reiniciado
    ) else (
        echo   AVISO: nao achei como religar - abra o MRO manualmente.
    )
)

echo.
if defined TROCOU (
    echo Atualizacao CONCLUIDA. Versao anterior preservada em app_anterior\.
    echo Rollback: feche o MRO, apague app\, renomeie app_anterior\ para app\ e religue.
) else (
    echo NAO atualizado - o sistema voltou na versao anterior.
    set "ERRO=1"
)

:fim
echo.
pause
exit /b %ERRO%
