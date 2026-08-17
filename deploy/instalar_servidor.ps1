# ============================================================================
#  Sistema MRO — auto-start no PC-servidor (v5.8.0)
#
#  Faz o que ate a v5.7.0 eram as secoes 4 e 5 de docs/INSTALACAO_SERVIDOR.md, na mao,
#  pela GUI: tarefa agendada "Ao iniciar o computador" + regra de firewall na 8501.
#
#  Uso: botao direito > "Executar com o PowerShell"  (ele se auto-eleva se precisar).
#  Opcional — so faz falta se o sistema tem que subir sozinho no boot. Para uso avulso,
#  dois cliques no atalho MRO bastam.
#
#  Idempotente: remove a tarefa e a regra antes de recriar, entao pode rodar de novo.
# ============================================================================

$ErrorActionPreference = 'Stop'

$TAREFA = 'Sistema MRO'   # nome EXATO — atualizar_mro.bat procura por esta string.
$PORTA  = 8501
$REGRA  = "Sistema MRO ($PORTA)"

# ── Auto-elevacao ────────────────────────────────────────────────────────────
$identidade = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal  = New-Object Security.Principal.WindowsPrincipal($identidade)
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Host 'Preciso de privilegios de administrador — reabrindo elevado...'
    Start-Process powershell.exe -Verb RunAs -ArgumentList @(
        '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', "`"$PSCommandPath`""
    )
    exit 0
}

# $PSScriptRoot, nao C:\MRO fixo: o pacote pode ter sido extraido em outro lugar.
$RAIZ = $PSScriptRoot
$BAT  = Join-Path $RAIZ 'iniciar_mro.bat'

if (-not (Test-Path $BAT)) {
    Write-Host "ERRO: nao encontrei $BAT." -ForegroundColor Red
    Write-Host 'Este script tem que ficar na mesma pasta do iniciar_mro.bat e do atalho MRO.'
    Read-Host 'Enter para fechar'
    exit 1
}

Write-Host "Sistema MRO — instalando auto-start a partir de $RAIZ"

# ── 1. Tarefa agendada ───────────────────────────────────────────────────────
Write-Host "[1/2] Tarefa agendada `"$TAREFA`"..."

try { Unregister-ScheduledTask -TaskName $TAREFA -Confirm:$false -ErrorAction Stop } catch {}

$acao = New-ScheduledTaskAction -Execute $BAT -WorkingDirectory $RAIZ
$disparador = New-ScheduledTaskTrigger -AtStartup
# S4U = roda com o usuario desconectado, sem guardar senha. Highest porque a regra de
# firewall e a porta baixa-privilegio do Streamlit pedem elevacao no primeiro boot.
$principalTarefa = New-ScheduledTaskPrincipal -UserId 'SYSTEM' -LogonType ServiceAccount -RunLevel Highest
$config = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit ([TimeSpan]::Zero) `
    -StartWhenAvailable

Register-ScheduledTask -TaskName $TAREFA -Action $acao -Trigger $disparador `
    -Principal $principalTarefa -Settings $config -Force | Out-Null
Write-Host '      OK — sobe sozinho ao ligar o PC, reinicia 3x se cair.'

# ── 2. Firewall ──────────────────────────────────────────────────────────────
Write-Host "[2/2] Regra de firewall na porta $PORTA..."

try { Remove-NetFirewallRule -DisplayName $REGRA -ErrorAction Stop } catch {}

# Profile Domain,Private de proposito: o MRO nao tem autenticacao. Public de fora.
New-NetFirewallRule -DisplayName $REGRA -Direction Inbound -Protocol TCP `
    -LocalPort $PORTA -Action Allow -Profile Domain,Private | Out-Null
Write-Host '      OK — liberado em Domain e Private (Public de fora: nao ha login no MRO).'

# ── Sobe agora ───────────────────────────────────────────────────────────────
Write-Host ''
Write-Host 'Iniciando o sistema...'
Start-ScheduledTask -TaskName $TAREFA

$ip = (Get-NetIPAddress -AddressFamily IPv4 |
    Where-Object { $_.IPAddress -notlike '127.*' -and $_.PrefixOrigin -ne 'WellKnown' } |
    Select-Object -First 1).IPAddress

Write-Host ''
Write-Host 'Pronto.' -ForegroundColor Green
Write-Host "  Neste PC:  http://localhost:$PORTA"
if ($ip) { Write-Host "  Na rede:   http://${ip}:$PORTA" }
Write-Host ''
Write-Host 'Reboot-test: reinicie o PC e confirme que o sistema volta sozinho.'
Read-Host 'Enter para fechar'
