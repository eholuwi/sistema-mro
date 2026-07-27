# Instalação no PC-servidor (v5.8.0)

Objetivo: os compradores (Miguel, Davi) e o almoxarifado abrem `http://<pc>:8501` no
navegador. **Zero instalação na máquina deles.** O sistema roda num único PC da rede.

---

## Layout

```
C:\MRO\
├── MRO.exe             launcher (v5.8.0) — dois cliques e o sistema sobe
├── runtime\            Python embeddable + dependências
├── app\                código do sistema  ← substituído inteiro a cada release
├── dados\
│   ├── mro.db          o banco
│   └── backups\        .bak automáticos (migração e sync) + os manuais
├── iniciar_mro.bat
├── atualizar_mro.bat
└── instalar_servidor.ps1
```

**A separação `app\` ↔ `dados\` é o ponto central.** A atualização troca `app\` inteira;
se o banco morasse lá dentro, toda atualização levaria o dado junto.

---

## 0. Caminho rápido — pacote portátil (recomendado)

O pacote portátil traz o `runtime\` **já montado**, com as dependências instaladas. As
seções 1 e 2 abaixo existem para quando não dá para usá-lo.

**Na máquina de desenvolvimento:**

```powershell
python scripts/portatil.py           # → dist/mro-portatil-5.8.0.zip  (~148 MB)
```

Precisa de Windows, do **mesmo minor** de Python que o CI valida (o build aborta se não
bater) e de internet na primeira vez — o embeddable fica em cache em `build/cache/`.
`--pular-deps` reaproveita o `runtime\` já montado; `--pular-exe`, o `MRO.exe`.

**Na máquina destino (não precisa de Python, nem de admin, nem de internet):**

1. Extraia o zip em **`C:\MRO`**.

   > ⚠️ **Não extraia dentro do OneDrive / Dropbox / Google Drive.** O sincronizador
   > segura lock no `mro.db` e no `-wal` e pode corromper o banco. O `MRO.exe` avisa se
   > detectar isso, mas não impede.

2. Dois cliques em **`MRO.exe`**. O navegador abre sozinho; a janela preta mostra o
   endereço de rede (`http://<ip>:8501`) para os outros usuários.

   **Fechar a janela preta para o sistema.** O Streamlit morre junto — não fica processo
   órfão segurando a porta.

3. **Só se o sistema tiver que subir sozinho quando o PC liga:** botão direito em
   `instalar_servidor.ps1` › *Executar com o PowerShell*. Ele pede admin e faz o que as
   seções 4 e 5 mandam fazer na mão (tarefa agendada `Sistema MRO` + firewall na 8501).
   Para uso avulso, os dois cliques no `MRO.exe` bastam.

**Migrando de um MRO existente:** copie o `mro.db` (mais os `-wal`/`-shm`, se houver) para
`C:\MRO\dados\` **com o app parado**, antes do primeiro boot. Ver seção 3.

---

## Caminho manual (quando não dá para usar o pacote)

As seções 1 e 2 montam o `runtime\` e o `app\` à mão — é o que o `scripts/portatil.py`
automatiza. Use se o build portátil não estiver disponível ou se você precisar de um
runtime diferente do que o CI valida.

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

Teste: `C:\MRO\runtime\python.exe -s -c "import streamlit, pandas; print('ok')"`

> ⚠️ **O `-s` não é decoração.** Com `import site` habilitado, o embeddable também coloca
> `%APPDATA%\Python\Python3XX\site-packages` no `sys.path` — os pacotes globais da máquina.
> Sem `-s`, o teste acima passa mesmo com o `pip install` incompleto, e a quebra só aparece
> num PC que não tenha Python instalado. `iniciar_mro.bat` e `MRO.exe` já usam `-s`.
>
> ⚠️ **O embeddable IGNORA `PYTHONPATH`** — a presença do `python*._pth` substitui a busca
> padrão de caminhos. Quem coloca `Lib\site-packages` no `sys.path` é a linha do `._pth` que
> você acabou de acrescentar; a variável no `iniciar_mro.bat` é só rede para o caso de o
> runtime ser um CPython normal. Se o `import streamlit` falhar, o problema está no `._pth`.

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

> **Atalho:** `instalar_servidor.ps1` (botão direito › *Executar com o PowerShell*) faz esta
> seção e a próxima sozinho, e é idempotente. O passo a passo abaixo é a referência do que
> ele cria — e o caminho manual se a política da máquina bloquear o script.

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
6. Se subiu pelo `MRO.exe`: **feche a janela preta** e confirme no Gerenciador de Tarefas
   que nenhum `python.exe` sobrou.

> ⚠️ **Servidor no ar não prova que a migração rodou.** O Streamlit só executa o `app.py`
> quando uma sessão de navegador conecta — `http://localhost:8501` responde com o `dados\`
> ainda vazio. É o passo 5 (o `.bak`) que confirma, não o passo 1.

---

## 7. Atualizar

```bat
C:\MRO\atualizar_mro.bat C:\temp\mro-5.8.0.zip
```

Sequência: para a tarefa → backup do banco → move `app\` para `app_anterior\` →
extrai a nova → religa. Se a extração falhar, ele restaura sozinho a versão anterior.

O zip aqui é o de **release** (`scripts/release.py`), não o portátil: só `app\` é
substituída. O `runtime\` e o `MRO.exe` ficam como estão — o exe não precisa ser refeito a
cada versão, porque ele só congela o launcher.

> ⚠️ **Feche o `MRO.exe` antes.** Se o sistema tiver subido por dois cliques, não há tarefa
> agendada para o `schtasks /End` parar e a pasta `app\` continua em uso. Desde a v5.8.0 o
> script **aborta** nesse caso em vez de misturar duas versões na mesma pasta.

**Rollback manual:** pare a tarefa, apague `app\`, renomeie `app_anterior\` para `app\`,
religue. O banco não é tocado pela atualização — mas se a nova versão tiver rodado uma
migração de schema, o rollback do código exige restaurar também o `.bak` correspondente.

---

## 8. Backup e restauração

Todos os `.bak` ficam em `C:\MRO\dados\backups\` — pasta que **sobrevive à atualização**,
porque está fora de `app\`. Três origens:

| Origem | Quando |
|---|---|
| `pre-migracao`, `req-status-v470`, … | automático, antes de uma migração de schema |
| `sync-api` | automático, no máximo 1×/dia no sync da API |
| `manual` | **você clicou** em *Configurações › Backup do Banco › Fazer backup agora* |

**Backup sob demanda (v5.8.0)** — aba **Configurações**, bloco *Backup do Banco*:

- **Pasta de destino (opcional)** — um caminho local ou de rede (`D:\Backups`,
  `\\servidor\backups\mro`). O botão copia o `.bak` para lá **além** de `backups\`. É isto
  que fecha a lacuna que esta seção admitia até a v5.7.0: os `.bak` cobrem migração, não
  perda de disco.
  - Se a pasta não existir ou estiver sem permissão, a tela avisa e **o backup em
    `backups\` é feito de todo jeito** — só a cópia extra falha.
  - ⚠️ O destino é gravado **no banco**, e o banco viaja com o servidor. Ao mudar de
    máquina, confira o campo: um `D:\Backups` de outro PC chega junto.
- **Baixar este backup** — entrega o `.bak` pelo navegador, na máquina de quem clicou. É o
  único caminho para tirar uma cópia do servidor sem acesso ao disco dele.

> **Não há retenção automática.** Nada apaga `.bak` antigo, e o botão manual acelera o
> acúmulo (~2,7 MB cada). Limpe `C:\MRO\dados\backups\` de tempo em tempo.

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
- **O pacote portátil é grande** — ~148 MB zipado, ~440 MB extraído, dos quais 427 MB são o
  `runtime\`. É o preço de não instalar nada na máquina destino. Passe por pendrive ou
  compartilhamento, não por e-mail.
- **`MRO.exe` pode ser barrado por antivírus.** Executável gerado por PyInstaller
  (`--onefile`) às vezes cai em falso positivo heurístico. Se acontecer, o
  `iniciar_mro.bat` faz a mesma coisa e não é um binário — ou libere o exe na exceção do
  antivírus corporativo.
- **Nunca coloque a pasta dentro do OneDrive/Dropbox.** O sincronizador segura lock no
  `mro.db` e no `-wal`; dois processos escrevendo no mesmo arquivo corrompem o banco. O
  `MRO.exe` avisa, mas não impede.
