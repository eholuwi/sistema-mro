# Gate de qualidade do Sistema MRO.
#
# Exit 0 = pronto. Exit 1 = o loop continua.
# Este script e o criterio de parada OBJETIVO do projeto: nenhuma alteracao e
# considerada concluida sem ele verde. Substitui "parece bom".
#
# Uso:  .\verify.ps1          (tudo — antes de commitar)
#       .\verify.ps1 -Rapido  (pula o format check, p/ loop apertado)
#
# NAO substitui a validacao no app real (regra inviolavel nº6 do CLAUDE.md): a suite
# cobre services/ e database.py, mas ui/ so tem o smoke de render por rota.

param([switch]$Rapido)

$ErrorActionPreference = "Continue"

# Usa o venv do projeto quando existir. Sem isso o gate passaria ou reprovaria
# conforme o interpretador ativo no shell — e a versao do ruff muda o veredito.
$py = if (Test-Path "$PSScriptRoot\venv\Scripts\python.exe") {
    "$PSScriptRoot\venv\Scripts\python.exe"
} else { "python" }

$falhas = @()

function Etapa($nome, $bloco) {
    Write-Host "==> $nome" -ForegroundColor Cyan
    & $bloco
    if ($LASTEXITCODE -ne 0) {
        $script:falhas += $nome
        Write-Host "    FALHOU: $nome" -ForegroundColor Red
    }
}

if (-not $Rapido) {
    Etapa "ruff format --check" { & $py -m ruff format --check . }
}
Etapa "ruff check" { & $py -m ruff check . }
Etapa "pytest"     { & $py -m pytest -q }

Write-Host ""
if ($falhas.Count -gt 0) {
    Write-Host "VERIFY: FALHOU ($($falhas -join ', '))" -ForegroundColor Red
    exit 1
}
Write-Host "VERIFY: OK" -ForegroundColor Green
exit 0
