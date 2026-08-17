@echo off
REM ============================================================================
REM  Sistema MRO - MOTOR da atualizacao pelo app (v6.6.0)
REM
REM  Uso:  aplicar_atualizacao.bat <zip> <pid-do-streamlit> <raiz-da-instalacao>
REM
REM  Quem chama e `services/atualizacao.py:disparar()`, num processo DESTACADO. Este
REM  script mata o app, troca `app\` e religa - por isso ele NAO pode rodar de dentro
REM  de `app\`: o proprio app o copia para `dados\atualizacoes\` antes de disparar.
REM
REM  Diferencas para o `atualizar_mro.bat` da raiz (que continua existindo):
REM    - mata o PID do Streamlit, nao so a tarefa agendada (cobre o modo duplo clique);
REM    - espera a PORTA liberar em vez de um `timeout /t 5` cego;
REM    - religa sozinho pelos dois caminhos de subida;
REM    - restaura `app_anterior\` e religa em QUALQUER falha;
REM    - escreve `ultima_atualizacao.log` ao lado de si (processo destacado nao tem
REM      console: sem o log, um fracasso vira tela em branco sem rastro).
REM
REM  O `atualizar_mro.bat` da raiz e o break-glass e NAO depende de nada dentro de
REM  `app\` - um atualizador que mora na pasta que ele substitui nao serve de
REM  recuperacao. A semelhanca entre os dois e deliberada; `tests/test_v660_atualizacao.py`
REM  trava os invariantes comuns (nome da tarefa, backup antes da troca, abortar se o
REM  move falhar).
REM
REM  Tudo que este arquivo IMPRIME e ASCII: o console do Windows abre em cp850/cp1252.
REM ============================================================================
setlocal enabledelayedexpansion

set "PACOTE=%~1"
set "PIDAPP=%~2"
set "RAIZ_ARG=%~3"
set "TAREFA=Sistema MRO"
set "PORTA=8501"
set "LOG=%~dp0ultima_atualizacao.log"
set "LIMITE=40"

REM Sem argumento de raiz, deduz: este bat vive em <raiz>\dados\atualizacoes\.
if "%RAIZ_ARG%"=="" set "RAIZ_ARG=%~dp0..\.."
for %%I in ("%RAIZ_ARG%") do set "RAIZ=%%~fI"

> "%LOG%" echo === Sistema MRO - atualizacao em %DATE% %TIME% ===
call :log "Pacote : %PACOTE%"
call :log "Raiz   : %RAIZ%"
call :log "PID app: %PIDAPP%"

REM Cada guarda em BLOCO, nao em `if ... & exit /b`: o `&` do cmd separa no parse e o
REM `exit` rodaria sempre, inclusive quando a condicao NAO bate.
if "%PACOTE%"=="" (
    call :log "ERRO: nenhum pacote informado."
    exit /b 1
)
if not exist "%PACOTE%" (
    call :log "ERRO: pacote nao encontrado: %PACOTE%"
    exit /b 1
)
if not exist "%RAIZ%\app" (
    call :log "ERRO: nao achei %RAIZ%\app - raiz errada, nada foi alterado."
    exit /b 1
)

REM ---------------------------------------------------------------- 1/6 parar
REM Folga antes de matar o app: quem clicou "Instalar agora" ainda esta esperando o
REM Streamlit terminar de desenhar a mensagem "recarregue em ~30 segundos". Sem a pausa,
REM o taskkill chega primeiro e a pessoa ve a aba morrer sem explicacao nenhuma.
call :dormir 3
call :log "[1/6] Parando o sistema..."
schtasks /Query /TN "%TAREFA%" >nul 2>&1
if not errorlevel 1 (
    set "TEM_TAREFA=1"
    schtasks /End /TN "%TAREFA%" >nul 2>&1
    call :log "      tarefa agendada encerrada"
)
if not "%PIDAPP%"=="" if not "%PIDAPP%"=="0" (
    taskkill /PID %PIDAPP% /T /F >nul 2>&1
    call :log "      processo %PIDAPP% encerrado"
)

REM ------------------------------------------------------- 2/6 esperar a porta
call :log "[2/6] Aguardando a porta %PORTA% liberar..."
set /a ESPERA=0
:aguardar
netstat -an | findstr /C:":%PORTA% " | findstr /C:"LISTENING" >nul 2>&1
if errorlevel 1 goto porta_livre
set /a ESPERA+=1
if !ESPERA! GEQ %LIMITE% (
    call :log "      AVISO: porta ainda ocupada apos %LIMITE%s - seguindo mesmo assim"
    goto porta_livre
)
call :dormir 1
goto aguardar
:porta_livre
call :log "      ok (%ESPERA%s)"

REM --------------------------------------------------------------- 3/6 backup
call :log "[3/6] Backup do banco..."
set "CARIMBO=%DATE:~6,4%%DATE:~3,2%%DATE:~0,2%-%TIME:~0,2%%TIME:~3,2%%TIME:~6,2%"
set "CARIMBO=%CARIMBO: =0%"
if not exist "%RAIZ%\dados\backups\" mkdir "%RAIZ%\dados\backups"
if exist "%RAIZ%\dados\mro.db" (
    copy /Y "%RAIZ%\dados\mro.db" "%RAIZ%\dados\backups\mro.db.bak-%CARIMBO%-pre-atualizacao" >nul
    if errorlevel 1 (
        call :log "ERRO: backup falhou. Atualizacao ABORTADA - nada foi alterado."
        goto religar
    )
    call :log "      mro.db.bak-%CARIMBO%-pre-atualizacao"
) else (
    call :log "      aviso: dados\mro.db ainda nao existe - seguindo sem backup"
)

REM ----------------------------------------------------- 4/6 guardar a antiga
call :log "[4/6] Guardando a versao anterior em app_anterior\..."
if exist "%RAIZ%\app_anterior" rmdir /S /Q "%RAIZ%\app_anterior"
move "%RAIZ%\app" "%RAIZ%\app_anterior" >nul 2>&1

REM Guarda da v5.8.0: sem ela o Expand-Archive -Force do passo 5 escreveria por cima
REM da versao antiga e duas versoes se misturariam na mesma pasta, sem aviso nenhum.
if exist "%RAIZ%\app" (
    call :log "ERRO: nao consegui mover app\ - algo ainda esta usando a pasta."
    call :log "      Atualizacao ABORTADA - nada foi alterado."
    goto religar
)

REM ---------------------------------------------------------- 5/6 nova versao
call :log "[5/6] Extraindo a nova versao..."
powershell -NoProfile -Command "Expand-Archive -LiteralPath '%PACOTE%' -DestinationPath '%RAIZ%\app' -Force" >>"%LOG%" 2>&1
if errorlevel 1 goto restaurar
if not exist "%RAIZ%\app\app.py" goto restaurar
set "TROCOU=1"
call :log "      ok"
goto religar

:restaurar
call :log "ERRO na extracao - restaurando a versao anterior."
if exist "%RAIZ%\app" rmdir /S /Q "%RAIZ%\app"
move "%RAIZ%\app_anterior" "%RAIZ%\app" >nul 2>&1

REM ---------------------------------------------------------------- 6/6 subir
:religar
call :log "[6/6] Religando..."
if defined TEM_TAREFA (
    schtasks /Run /TN "%TAREFA%" >nul 2>&1
    call :log "      tarefa agendada reiniciada"
) else (
    REM v6.8.2 - o ramo do MRO.exe saiu junto com o PyInstaller. Quem sobe o sistema
    REM sempre foi o iniciar_mro.bat; o exe so dava o duplo clique, hoje feito pelo
    REM atalho MRO.lnk (que aponta para o bat). Um `if exist MRO.exe` seria ramo morto.
    if exist "%RAIZ%\iniciar_mro.bat" (
        start "" "%RAIZ%\iniciar_mro.bat"
        call :log "      iniciar_mro.bat reiniciado"
    ) else (
        call :log "      AVISO: nao achei como religar - abra o MRO manualmente."
    )
)
REM A mensagem final tem que dizer a verdade: no caminho de rollback a versao anterior
REM voltou para app\ e NAO existe app_anterior\ nenhuma para apontar.
if defined TROCOU (
    call :log "Concluido. Versao anterior preservada em app_anterior\."
    exit /b 0
)
call :log "NAO atualizado - o sistema voltou na versao anterior."
exit /b 1

:log
echo %~1
>>"%LOG%" echo %~1
exit /b 0

REM Pausa de %1 segundos. NAO use `timeout` aqui: quem lanca este bat e o app, com
REM stdin redirecionado para DEVNULL, e nessa condicao o `timeout` aborta na hora com
REM "nao ha suporte para o redirecionamento de entrada". O efeito seria silencioso e
REM grave: a espera da porta (passo 2) rodaria as 40 voltas em milissegundos e desistiria
REM antes de o Streamlit soltar o banco. `ping` para loopback nao le stdin e espera de
REM verdade - N segundos = N+1 pings.
:dormir
set /a _PINGS=%~1+1
ping -n %_PINGS% 127.0.0.1 >nul 2>&1
exit /b 0
