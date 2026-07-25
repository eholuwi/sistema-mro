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

set "MRO_RAIZ=%~dp0"
set "MRO_DB_PATH=%MRO_RAIZ%dados\mro.db"
set "PYTHONPATH=%MRO_RAIZ%runtime\Lib\site-packages"

if not exist "%MRO_RAIZ%dados\" mkdir "%MRO_RAIZ%dados"

REM Porta e bind vem de app\.streamlit\config.toml (copia de deploy/config-servidor.toml).
REM Repetidos aqui em linha de comando para que a subida nao dependa do arquivo estar no lugar.
"%MRO_RAIZ%runtime\python.exe" -m streamlit run "%MRO_RAIZ%app\app.py" ^
    --server.headless=true ^
    --server.address=0.0.0.0 ^
    --server.port=8501 ^
    --server.fileWatcherType=none ^
    --browser.gatherUsageStats=false

REM Se o Streamlit cair, o codigo de saida sobe para o Agendador, que reinicia a tarefa.
exit /b %ERRORLEVEL%
