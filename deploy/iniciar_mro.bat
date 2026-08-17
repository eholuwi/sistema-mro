@echo off
REM ============================================================================
REM  Sistema MRO — inicializacao no PC-servidor (v5.5.0 / F5)
REM
REM  Layout esperado (ver docs/INSTALACAO_SERVIDOR.md):
REM    C:\MRO\runtime\   Python embeddable + dependencias (pip --target)
REM    C:\MRO\app\       codigo do sistema (esta pasta e substituida a cada release)
REM    C:\MRO\dados\     mro.db + backups\  (FORA de app\, sobrevive a atualizacao)
REM
REM  Copie este arquivo para C:\MRO\iniciar_mro.bat.
REM  Chamado pelo Agendador de Tarefas em "Ao iniciar o computador".
REM ============================================================================
setlocal

REM v6.8.2 - este mesmo bat se rechama com --abrir-navegador (ver o fim do arquivo).
if /I "%~1"=="--abrir-navegador" goto abrir_navegador

set "MRO_RAIZ=%~dp0"
set "MRO_DB_PATH=%MRO_RAIZ%dados\mro.db"

REM v5.8.0 — o Python EMBEDDABLE ignora PYTHONPATH: a presenca do python*._pth ao lado do
REM python.exe substitui a busca padrao de caminhos. Quem coloca Lib\site-packages no
REM sys.path e a linha correspondente do ._pth (secao 1 do INSTALACAO_SERVIDOR.md, ou
REM scripts/portatil.py, que grava sozinho). Mantido so como rede para o caso de o runtime
REM ser um CPython normal. MRO_DB_PATH acima nao sofre disso — e variavel comum.
set "PYTHONPATH=%MRO_RAIZ%runtime\Lib\site-packages"

if not exist "%MRO_RAIZ%dados\" mkdir "%MRO_RAIZ%dados"

REM v6.8.2 - AVISO DE PASTA SINCRONIZADA. Era do launcher.py, que saiu junto com o
REM MRO.exe; sem ele ninguem mais avisaria. OneDrive/Dropbox/Google Drive seguram lock
REM no mro.db e no -wal, e dois processos escrevendo no mesmo arquivo corrompem o banco.
REM Avisa e SEGUE - o launcher tambem nao impedia; a decisao e de quem instalou.
echo %MRO_RAIZ% | findstr /I /C:"OneDrive" /C:"Dropbox" /C:"Google Drive" >nul
if not errorlevel 1 (
    echo.
    echo  AVISO: esta pasta parece estar dentro de um sincronizador de nuvem
    echo         ^(OneDrive / Dropbox / Google Drive^). Ele segura lock no mro.db
    echo         e pode CORROMPER o banco. Mova a pasta do MRO para fora dele.
    echo.
)

REM v6.8.2 - QUEM ABRE O NAVEGADOR passou a ser este bat. Ate a v6.8.1 era o MRO.exe
REM (deploy/launcher.py), que saiu junto com o PyInstaller; o `streamlit run` daqui roda
REM com --server.headless=true e NAO abre nada sozinho. Sem esta parte o duplo clique no
REM atalho abriria so a janela preta, contrariando o LEIA-ME ("o navegador abre sozinho").
REM Dispara uma copia deste proprio bat em paralelo (`start /B`, sem janela nova): ela
REM espera a porta aceitar conexao e so entao abre o navegador.
REM `set MRO_SEM_NAVEGADOR=1` desliga - e o caso da tarefa agendada rodando como SYSTEM,
REM que nao tem area de trabalho para abrir nada.
if not defined MRO_SEM_NAVEGADOR start "" /B "%~f0" --abrir-navegador

REM Porta e bind vem de app\.streamlit\config.toml (copia de deploy/config-servidor.toml).
REM Repetidos aqui em linha de comando para que a subida nao dependa do arquivo estar no lugar.
REM v5.8.0 — `-s` exclui o site-packages do USUARIO (%APPDATA%\Python\...). Sem ele o
REM embeddable com `import site` habilitado enxerga os pacotes globais da maquina: na do
REM dev funciona, na limpa quebra.
"%MRO_RAIZ%runtime\python.exe" -s -m streamlit run "%MRO_RAIZ%app\app.py" ^
    --server.headless=true ^
    --server.address=0.0.0.0 ^
    --server.port=8501 ^
    --server.fileWatcherType=none ^
    --browser.gatherUsageStats=false

REM Se o Streamlit cair, o codigo de saida sobe para o Agendador, que reinicia a tarefa.
REM E quando alguem abriu por duplo clique e quebrou: sem este `pause` a janela piscava
REM e sumia com o erro dentro dela ("rodei e nao deu nada"). Agora trava na tela.
if errorlevel 1 (
    echo.
    echo =====================================================================
    echo  ERRO: o Sistema MRO nao subiu. A causa esta nas mensagens ACIMA.
    echo  Se a janela fechou antes, reabra o prompt e rode este comando:
    echo    "%MRO_RAIZ%runtime\python.exe" -s -c "import streamlit"
    echo  Se ele reclamar de algum modulo, o runtime esta incompleto - refaca
    echo  o pacote portatil ou reinstale as dependencias.
    echo =====================================================================
    pause
)
exit /b %ERRORLEVEL%

REM ============================================================================
REM  v6.8.2 - Abertura do navegador (roda em paralelo, chamada la de cima)
REM
REM  Espera a porta ACEITAR conexao antes de abrir. Abrir antes mostraria "nao foi
REM  possivel conectar" no navegador e a pessoa concluiria que o sistema nao subiu -
REM  era exatamente por isso que o launcher.py fazia poll de socket antes de chamar
REM  o webbrowser.
REM
REM  NAO use `timeout` para a espera: com stdin redirecionado ele aborta na hora
REM  ("nao ha suporte para o redirecionamento de entrada") e o laco daria as 40 voltas
REM  em milissegundos. Armadilha medida na v6.6.0 e travada por teste. `ping` no
REM  loopback nao le stdin e espera de verdade: N segundos = N+1 pings.
REM ============================================================================
:abrir_navegador
set /a _T=0
:_espera_porta
REM O `:8501 ` com espaco no fim casa a coluna do endereco local; o segundo findstr exige
REM LISTENING para nao confundir uma conexao de SAIDA para a porta 8501 de outra maquina
REM (que aparece como ESTABLISHED e tambem contem ":8501") com o servidor local no ar.
netstat -an | findstr /C:":8501 " | findstr /I "LISTENING" >nul 2>&1
if not errorlevel 1 goto _abrir_url
set /a _T+=1
if %_T% GEQ 40 exit /b 0
ping -n 2 127.0.0.1 >nul 2>&1
goto _espera_porta
:_abrir_url
start "" http://localhost:8501
exit /b 0
