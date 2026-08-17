# ============================================================================
#  Sistema MRO - cria o atalho "MRO" na area de trabalho (v6.8.2)
#
#  Para que serve: o zip portatil ja vem com um MRO.lnk apontando para C:\MRO.
#  Se o pacote foi extraido em OUTRO caminho (ou o atalho se perdeu), rode este
#  script com botao direito > "Executar com o PowerShell". Ele recria o atalho
#  apontando para o iniciar_mro.bat desta pasta, usando o mro.ico ao lado.
#
#  NAO precisa de admin. NAO sobe o sistema - so cria o atalho.
# ============================================================================

$RAIZ = $PSScriptRoot
$BAT  = Join-Path $RAIZ 'iniciar_mro.bat'
$ICO  = Join-Path $RAIZ 'mro.ico'

if (-not (Test-Path $BAT)) {
    Write-Host 'ERRO: nao achei iniciar_mro.bat ao lado deste script.'
    Write-Host '      O criar_atalho.ps1 tem que ficar na raiz da instalacao.'
    Read-Host 'Enter para fechar'
    exit 1
}
if (-not (Test-Path $ICO)) {
    Write-Host "ERRO: nao achei o icone mro.ico em $RAIZ"
    Read-Host 'Enter para fechar'
    exit 1
}

$desktop = [Environment]::GetFolderPath('Desktop')
$atalho  = Join-Path $desktop 'MRO.lnk'

$wsh = New-Object -ComObject WScript.Shell
$s   = $wsh.CreateShortcut($atalho)
$s.TargetPath       = $BAT
$s.WorkingDirectory = $RAIZ
$s.IconLocation     = "$ICO,0"
$s.Description      = 'Sistema MRO'
$s.Save()

Write-Host "Atalho criado: $atalho"
Write-Host 'De dois cliques nele para abrir o sistema.'
Read-Host 'Enter para fechar'
