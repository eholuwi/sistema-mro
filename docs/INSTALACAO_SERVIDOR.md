# Instalação no PC-servidor (v5.5.0 / F5)

Objetivo: os compradores (Miguel, Davi) e o almoxarifado abrem `http://<pc>:8501` no
navegador. **Zero instalação na máquina deles.** O sistema roda num único PC da rede.

---

## Layout

```
C:\MRO\
├── runtime\            Python embeddable + dependências
├── app\                código do sistema  ← substituído inteiro a cada release
├── dados\
│   ├── mro.db          o banco
│   └── backups\        .bak automáticos (migração e sync)
├── iniciar_mro.bat
└── atualizar_mro.bat
```

**A separação `app\` ↔ `dados\` é o ponto central.** A atualização troca `app\` inteira;
se o banco morasse lá dentro, toda atualização levaria o dado junto.

---

## 1. Runtime

Baixe o **Python embeddable (amd64)** de python.org e extraia em `C:\MRO\runtime\`.

> Use a **mesma minor version validada em desenvolvimento e no CI**. Conferir com
> `python --version` na máquina de dev e o `python-version` de
> `.github/workflows/verify.yml`. O `docs/PLANO_V5_EVOLUCAO.md` original sugeriu 3.12;
> o que vale é bater com o que a suíte valida, porque `requirements.txt` está com
> versões fixadas e nem toda wheel existe para toda minor.

O embeddable vem com imports isolados. Habilite `site`:

1. Abra `C:\MRO\runtime\python*._pth`.
2. Descomente a linha `import site` (tire o `#`).
3. Acrescente uma linha `Lib\site-packages`.

Instale as dependências (do `requirements.txt` da release):

```bat
cd C:\MRO\runtime
curl -o get-pip.py https://bootstrap.pypa.io/get-pip.py
python.exe get-pip.py
python.exe -m pip install --target=Lib\site-packages -r C:\caminho\requirements.txt
```

Teste: `C:\MRO\runtime\python.exe -c "import streamlit, pandas; print('ok')"`

---

## 2. Aplicação

Gere o pacote na máquina de desenvolvimento:

```powershell
python scripts/release.py          # → dist/mro-5.5.0.zip
```

Extraia o conteúdo em `C:\MRO\app\`. Copie os dois `.bat` de `deploy/` para `C:\MRO\`.

O pacote já traz `.streamlit/config.toml` com a config de produção (headless,
`0.0.0.0:8501`) — não é a mesma do repositório, que é só tema para dev.

---

## 3. Banco

- **Instalação nova:** crie `C:\MRO\dados\`. O banco nasce sozinho na primeira subida.
- **Migrando de um MRO existente:** copie o `mro.db` atual para `C:\MRO\dados\mro.db`
  **com o app parado**. Leve junto os `mro.db-wal` / `mro.db-shm` se existirem — sem
  eles você perde o que ainda não foi para o arquivo principal.

O `iniciar_mro.bat` define `MRO_DB_PATH=C:\MRO\dados\mro.db`. Sem essa variável o
sistema usaria o `mro.db` ao lado de `database.py`, isto é, **dentro de `app\`** — que
é apagada a cada atualização.

Na primeira subida a migração roda sozinha e grava um `.bak` em `dados\backups\`.

---

## 4. Auto-start (Agendador de Tarefas)

Criar tarefa:

- **Nome:** `Sistema MRO` — o `atualizar_mro.bat` procura por esse nome exato.
- **Executar:** mesmo com o usuário desconectado · **Executar com privilégios mais altos**
- **Disparador:** Ao iniciar o computador
- **Ação:** iniciar programa → `C:\MRO\iniciar_mro.bat`
- **Configurações:** "Reiniciar a cada 1 minuto" · "Tentar reiniciar até 3 vezes" ·
  desmarcar "Parar a tarefa se for executada por mais de..." (o app roda continuamente)

---

## 5. Firewall

```powershell
New-NetFirewallRule -DisplayName "Sistema MRO (8501)" -Direction Inbound `
  -Protocol TCP -LocalPort 8501 -Action Allow -Profile Domain,Private
```

Deixe `Public` de fora — é uma aplicação de rede interna, sem autenticação.

---

## 6. Verificação

1. `http://localhost:8501` no próprio servidor.
2. `http://<nome-ou-ip>:8501` de outra máquina.
3. **Reboot-test:** reinicie o servidor e confirme que o app volta sozinho.
4. Navegue as 9 páginas, com atenção a **Movimentação** e **Ficha 360**.
5. Confirme que o `.bak` da primeira subida está em `C:\MRO\dados\backups\`.

---

## 7. Atualizar

```bat
C:\MRO\atualizar_mro.bat C:\temp\mro-5.6.0.zip
```

Sequência: para a tarefa → backup do banco → move `app\` para `app_anterior\` →
extrai a nova → religa. Se a extração falhar, ele restaura sozinho a versão anterior.

**Rollback manual:** pare a tarefa, apague `app\`, renomeie `app_anterior\` para `app\`,
religue. O banco não é tocado pela atualização — mas se a nova versão tiver rodado uma
migração de schema, o rollback do código exige restaurar também o `.bak` correspondente.

---

## 8. Backup e restauração

Os `.bak` automáticos (antes de migração e no sync diário da API) ficam em
`C:\MRO\dados\backups\`. Eles cobrem migração, **não** perda de disco: configure uma
cópia de `C:\MRO\dados\` para outro destino.

Restaurar:

```bat
schtasks /End /TN "Sistema MRO"
copy /Y C:\MRO\dados\backups\mro.db.bak-<carimbo>-<sufixo> C:\MRO\dados\mro.db
del C:\MRO\dados\mro.db-wal C:\MRO\dados\mro.db-shm
schtasks /Run /TN "Sistema MRO"
```

Apagar o `-wal`/`-shm` é obrigatório: restaurar o `.db` deixando um WAL de outra geração
mistura dois estados do banco.

---

## Limitações conhecidas

- **Sem autenticação.** Qualquer um na rede interna que alcance a porta 8501 usa o
  sistema. Aceitável para rede corporativa; não exponha à internet.
- **Ponto único de falha.** Se o PC-servidor cair, todos ficam sem sistema. A migração
  para um servidor de TI é trivial: copiar `C:\MRO\` e recriar tarefa e regra de firewall.
- **SQLite multiusuário** aguenta a escala de uso atual (poucos usuários simultâneos,
  escritas curtas) com WAL + `busy_timeout=5000`. Não é um SGBD de rede.
