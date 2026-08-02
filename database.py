import sqlite3
import os
import re
import unicodedata
import logging
from datetime import datetime
from contextlib import contextmanager

# `services.constants` não importa nada do projeto (só `re`), então não há ciclo:
# database continua sendo a camada mais baixa que TOCA o banco.
from services.constants import VERSAO

# v5.5.0 (F5) — caminho do banco resolvido de forma ABSOLUTA e sobrescrevível por env.
# Sem MRO_DB_PATH (dev do Luis): resolve p/ o mro.db ao lado deste arquivo — o mesmo lugar
# onde o antigo "mro.db" relativo já caía quando o Streamlit roda a partir de sistema-mro/.
# No servidor: MRO_DB_PATH=C:\MRO\dados\mro.db (banco fora da pasta do app, distribuível).
DB_PATH = os.environ.get("MRO_DB_PATH") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "mro.db")
logger = logging.getLogger(__name__)


def _normalizar_nome(valor):
    """Normalização de nome idêntica a services.db_functions._normalizar_txt
    (NFKD, remove acentos, minúsculo, colapsa espaços). Duplicada aqui de forma
    intencional para que database.py não dependa de services (evita import cíclico)."""
    if valor is None:
        return ""
    texto = unicodedata.normalize("NFKD", str(valor).strip())
    texto = "".join(ch for ch in texto if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", texto).lower()


def get_connection():
    conn = sqlite3.connect(DB_PATH, timeout=5.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    # v5.5.0 (F5) — acesso concorrente (compradores via navegador): espera até 5 s por um
    # lock em vez de estourar "database is locked" imediatamente. Complementa o WAL.
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


@contextmanager
def transaction(conn=None):
    """Context manager de conexao/transacao (Fase 4.2A / DT-7).

    conn=None  -> abre conexao propria; commit ao sair sem erro; rollback em
                  excecao; close sempre (via finally). Propaga a excecao.
    conn!=None -> yield da conexao recebida sem tocar em commit/rollback/close.
                  O chamador externo gerencia o ciclo de vida.

    Substitui o padrao close_conn dos helpers e o try/finally manual das
    funcoes de leitura. Uso em escrita: with transaction() as conn: ...
    Uso em helper: with transaction(conn_externa) as c: ...
    """
    if conn is not None:
        yield conn
        return
    c = get_connection()
    try:
        yield c
        c.commit()
    except Exception:
        c.rollback()
        raise
    finally:
        c.close()


def criar_banco():
    conn = get_connection()
    c = conn.cursor()

    c.execute("""
        CREATE TABLE IF NOT EXISTS listas (
            id      INTEGER PRIMARY KEY AUTOINCREMENT,
            tipo    TEXT NOT NULL,
            valor   TEXT NOT NULL,
            ativo   INTEGER DEFAULT 1,
            UNIQUE(tipo, valor)
        )
    """)

    # v5.8.0 — chave/valor de parâmetros globais (hoje só `backup_destino`).
    # NÃO usar `listas` para isto: `adicionar_valor_lista` faz .strip().upper() (destrói o
    # caso de um caminho) e `remover_valor_lista` é soft-delete (ativo=0) contra um
    # UNIQUE(tipo,valor) — regravar o mesmo valor depois de trocá-lo bateria em
    # IntegrityError, que é exatamente o uso de um campo editado várias vezes.
    c.execute("""
        CREATE TABLE IF NOT EXISTS configuracoes (
            chave   TEXT PRIMARY KEY,
            valor   TEXT
        )
    """)

    # ══════════════════════════════════════════════════════════════════════════════
    # PADRONIZAÇÃO DE LISTAS MESTRAS (v2.0.0)
    # ══════════════════════════════════════════════════════════════════════════════

    # 1. CENTROS DE CUSTO (Padrão: CÓDIGO - NOME)
    centros_custo = [
        "21101 - GERENCIA PRODUCAO",
        "21102 - WI-FI INFORMATICA",
        "21103 - BATERIA CELULAR",
        "21104 - BATERIA GPS",
        "21105 - PTH",
        "21106 - MANUTENÇÃO",
        "21107 - QUALIDADE",
        "21108 - BATERIA NOTEBOOK",
        "21109 - WI-FI AUDIO VIDEO",
        "21110 - EYELET",
        "21111 - SMD AUDIO VIDEO",
        "21112 - BATERIA PARA TABLET",
        "21115 - SMD",
        "21116 - ADAPTADORES",
        "21117 - ENGENHARIA DE MANUFATURA",
        "21119 - BATERIA PARA FONE DE OUVIDO",
        "21120 - ENGENHARIA MANUFATURA SMD",
        "21121 - MAO DE OBRA DIRETA",
        "21122 - ENGENHARIA MANUFATURA ADAPTADORES",
        "21123 - ADAPTADOR CELULAR",
        "21124 - TRANSFORMADOR",
        "21125 - MODEM (ASKEY)",
        "21126 - TAMPOGRAFIA DE BATERIA DE CELULAR",
        "21127 - TAMPOGRAFIA DE MODEM",
        "21128 - SUBPR ADAPTADOR DE CELULAR",
        "21129 - SUBPR MODEM",
        "21130 - FPCB BATERIA DE CELULAR",
        "21131 - FPCB BATERIA DE NOTEBOOK",
        "21132 - SUBP PCBA MODEM",
        "21133 - TAMPOGRAFIA DE BATERIA DE DE NOTE/TABLET",
        "21134 - BATERIA PARA SMART WATCH",
        "21191 - COMPRAS",
        "21192 - PCP",
        "21194 - ALMOXARIFADO",
        "21203 - EXPEDI.TDI",
        "21210 - BATERIA PARA CELULAR",
        "21211 - BATERIA PARA NOTEBOOK",
        "21212 - WI-FI WLAN",
        "21213 - WI-FI AUDIO/VIDEO",
        "21214 - ADAPTADOR",
        "21215 - ADAPTADOR PARA CELULAR",
        "21216 - MODEM",
        "21217 - CORREDOR DE IMPORTACAO",
        "21218 - BATERIA PARA TABLET",
        "21301 - ENGENHARIA PRODUTO",
        "90401 - FINANCEIRO",
        "90402 - DSI",
        "90501 - RECURSOS HUMANOS",
        "90502 - SERVICOS GERAIS",
        "90503 - APRENDIZES",
        "90604 - SERVICOS AO CLIENTE",
        "90701 - GERENCIA DA PLANTA",
        "90702 - MELHORIA CONTINUA",
        "99000 - ATIVO PASSIVO RES. F",
    ]

    # 2. LOCAIS DE ARMAZENAGEM (Padrão: TIPO-NÚMERO ou NOME ÚNICO)
    locais = []

    # ARM-01 até ARM-30
    for i in range(1, 31):
        locais.append(f"ARM-{i:02d}")

    # MRO-01 até MRO-35
    for i in range(1, 36):
        locais.append(f"MRO-{i:02d}")

    # ARM-EXP-01 até ARM-EXP-10
    for i in range(1, 11):
        locais.append(f"ARM-EXP-{i:02d}")

    # GAIOLA-01 até GAIOLA-03
    for i in range(1, 4):
        locais.append(f"GAIOLA-{i:02d}")

    # Locais Especiais
    locais_especiais = [
        "TENDA",
        "SUPERMERCADO",
        "SALA-ALMOXARIFADO",  # Padronizado com hífen
    ]
    locais.extend(locais_especiais)

    # 3. AUTORIZADORES (Mantidos)
    autorizadores = ["Gestor", "Líder", "Reserva", "Técnico"]

    # Inserção no Banco (INSERT OR IGNORE evita duplicatas em migrações)
    for cc in centros_custo:
        c.execute("INSERT OR IGNORE INTO listas (tipo, valor) VALUES (?,?)", ("centro_custo", cc))

    for loc in locais:
        c.execute("INSERT OR IGNORE INTO listas (tipo, valor) VALUES (?,?)", ("local", loc))

    for aut in autorizadores:
        c.execute("INSERT OR IGNORE INTO listas (tipo, valor) VALUES (?,?)", ("autorizador", aut))

    c.execute("""
        CREATE TABLE IF NOT EXISTS inventario (
            id                    INTEGER PRIMARY KEY AUTOINCREMENT,
            part_number           TEXT UNIQUE NOT NULL,
            nome_item             TEXT NOT NULL,
            descricao             TEXT,
            unidade               TEXT CHECK(unidade IN ('GL','UN','CX','RL','PCT','LT','RM')),
            importancia           TEXT CHECK(importancia IN ('Parada de Linha','Importante','Admin')),
            tipo_material         TEXT CHECK(tipo_material IN ('Expediente','Consumivel','Spare Parts','Uniforme','Improdutivo')),
            setor_responsavel     TEXT CHECK(setor_responsavel IN ('Improdutivo','Engenharia de SMT','LED DRIVER','MANUTENÇÃO','PRODUÇÃO','QUALIDADE','ALMOXARIFADO','ADMINISTRATIVO','SESMT')),
            local_armazenagem     TEXT,
            caixa_identificacao   TEXT,
            estoque_atual         REAL DEFAULT 0,
            estoque_minimo        REAL DEFAULT 0,
            estoque_seguranca     REAL DEFAULT 0,
            consumo_medio_diario  REAL DEFAULT 0,
            lead_time_dias        INTEGER DEFAULT 0,
            previsao_ruptura_dias REAL DEFAULT 999,
            ultima_sc_id          INTEGER,
            data_inventario       TEXT,
            data_criacao          TEXT DEFAULT CURRENT_TIMESTAMP,
            data_atualizacao      TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (ultima_sc_id) REFERENCES solicitacoes_compra(id)
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS movimentacoes (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            item_id        INTEGER NOT NULL,
            tipo           TEXT CHECK(tipo IN ('entrada','saida','devolucao')),
            quantidade     REAL NOT NULL,
            saldo_apos     REAL,
            data_hora      TEXT NOT NULL,
            centro_custo   TEXT,
            setor          TEXT,
            solicitante    TEXT,
            emitente       TEXT,
            observacao     TEXT,
            motivo         TEXT,
            sc_item_id     INTEGER,
            requisicao_id  INTEGER,
            FOREIGN KEY (item_id)       REFERENCES inventario(id) ON DELETE CASCADE,
            FOREIGN KEY (sc_item_id)    REFERENCES itens_sc(id),
            FOREIGN KEY (requisicao_id) REFERENCES requisicoes(id)
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS solicitacoes_compra (
            id                INTEGER PRIMARY KEY AUTOINCREMENT,
            numero_sc         TEXT NOT NULL UNIQUE,
            data_abertura     TEXT NOT NULL,
            data_aprovacao    TEXT,
            numero_po         TEXT,
            fornecedor        TEXT,
            data_prev_entrega TEXT,
            status            TEXT CHECK(status IN (
                'Aguardando Aprovação','Em Cotação','Pedido Emitido',
                'Aguardando Entrega','Parcial','Recebido','Cancelado'
            )) DEFAULT 'Aguardando Aprovação',
            observacoes       TEXT,
            data_criacao      TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS itens_sc (
            id                    INTEGER PRIMARY KEY AUTOINCREMENT,
            sc_id                 INTEGER NOT NULL,
            item_id               INTEGER NOT NULL,
            numero_po             TEXT,
            quantidade_solicitada REAL NOT NULL,
            quantidade_recebida   REAL DEFAULT 0,
            data_necessidade      TEXT,
            observacao_item       TEXT,
            FOREIGN KEY (sc_id)   REFERENCES solicitacoes_compra(id) ON DELETE CASCADE,
            FOREIGN KEY (item_id) REFERENCES inventario(id)
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS requisicoes (
            id                 INTEGER PRIMARY KEY AUTOINCREMENT,
            numero_requisicao  TEXT UNIQUE NOT NULL,
            data_hora          TEXT NOT NULL,
            setor              TEXT NOT NULL,
            emitente           TEXT NOT NULL,
            centro_custo       TEXT NOT NULL,
            autorizador_tipo   TEXT,
            autorizador_nome   TEXT,
            entrega_individual INTEGER DEFAULT 0,
            destinatarios      TEXT,
            sesmt              INTEGER DEFAULT 0,
            sesmt_responsavel  TEXT,
            observacoes        TEXT,
            status             TEXT CHECK(status IN ('Aberta','Parcial','Entregue','Cancelada')) DEFAULT 'Aberta',
            tipo_fluxo         TEXT,
            aprovado_por       TEXT,
            aprovado_em        TEXT,
            data_criacao       TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS itens_requisicao (
            id                    INTEGER PRIMARY KEY AUTOINCREMENT,
            requisicao_id         INTEGER NOT NULL,
            item_id               INTEGER NOT NULL,
            quantidade_solicitada REAL NOT NULL,
            quantidade_atendida   REAL NOT NULL,
            FOREIGN KEY (requisicao_id) REFERENCES requisicoes(id) ON DELETE CASCADE,
            FOREIGN KEY (item_id)       REFERENCES inventario(id)
        )
    """)

    # ── Fase 1 / v2.1.0 — novas tabelas (criação não-destrutiva) ──────────────

    # Item 1: auditoria de cargas em lote (ex.: base do Neidson)
    c.execute("""
        CREATE TABLE IF NOT EXISTS log_importacoes (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            tipo            TEXT NOT NULL,
            arquivo         TEXT,
            data_hora       TEXT DEFAULT CURRENT_TIMESTAMP,
            total_planilha  INTEGER DEFAULT 0,
            atualizados     INTEGER DEFAULT 0,
            ignorados       INTEGER DEFAULT 0,
            detalhe_json    TEXT
        )
    """)

    # Item 2: histórico de alteração de Part Number (rastreabilidade PN antigo↔novo)
    c.execute("""
        CREATE TABLE IF NOT EXISTS part_numbers_historico (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            item_id     INTEGER NOT NULL,
            pn_antigo   TEXT NOT NULL,
            pn_novo     TEXT NOT NULL,
            data_hora   TEXT DEFAULT CURRENT_TIMESTAMP,
            usuario     TEXT,
            motivo      TEXT,
            FOREIGN KEY (item_id) REFERENCES inventario(id) ON DELETE CASCADE
        )
    """)

    # Item 3: formulário de sugestões/feedback dos usuários
    c.execute("""
        CREATE TABLE IF NOT EXISTS feedbacks (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            data_hora      TEXT DEFAULT CURRENT_TIMESTAMP,
            tipo           TEXT NOT NULL,
            titulo         TEXT NOT NULL,
            descricao      TEXT,
            autor          TEXT,
            pagina_origem  TEXT,
            status         TEXT DEFAULT 'Novo',
            prioridade     TEXT,
            resposta       TEXT
        )
    """)

    # ── v2.2.0 — Ingestão & Fundação de Dados (criação não-destrutiva) ─────────

    # Histórico de preços por item (alimentado por SCM/SC7 do Relatório de SCs).
    c.execute("""
        CREATE TABLE IF NOT EXISTS precos_historico (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            item_id        INTEGER NOT NULL,
            data           TEXT,
            preco_unitario REAL,
            moeda          TEXT,
            fornecedor     TEXT,
            numero_sc      TEXT,
            numero_po      TEXT,
            origem         TEXT,
            lead_time_dias INTEGER,
            data_registro  TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (item_id) REFERENCES inventario(id) ON DELETE CASCADE
        )
    """)

    # Cadastro mestre de fornecedores (aba FORNECEDORES / Protheus SA1).
    c.execute("""
        CREATE TABLE IF NOT EXISTS fornecedores (
            id                INTEGER PRIMARY KEY AUTOINCREMENT,
            codigo            TEXT NOT NULL,
            loja              TEXT,
            razao_social      TEXT,
            nome_fantasia     TEXT,
            cnpj              TEXT,
            email             TEXT,
            telefone          TEXT,
            contato           TEXT,
            cond_pagto        TEXT,
            ativo             INTEGER DEFAULT 1,
            ultima_importacao TEXT,
            UNIQUE(codigo, loja)
        )
    """)

    # Relação material↔fornecedor (último preço/lead time observados → "melhor fornecedor").
    c.execute("""
        CREATE TABLE IF NOT EXISTS fornecedor_item (
            id                 INTEGER PRIMARY KEY AUTOINCREMENT,
            item_id            INTEGER NOT NULL,
            fornecedor_codigo  TEXT,
            fornecedor_loja    TEXT,
            fornecedor_nome    TEXT,
            ultimo_preco       REAL,
            ultimo_lead_time   INTEGER,
            ultima_data        TEXT,
            FOREIGN KEY (item_id) REFERENCES inventario(id) ON DELETE CASCADE,
            UNIQUE(item_id, fornecedor_codigo, fornecedor_loja)
        )
    """)

    # Solicitantes MRO (dinâmico, da aba SCM USERS). Substitui a constante fixa
    # SOLICITANTES_MRO: quem tem incluir_mro=1 é considerado no escopo MRO.
    c.execute("""
        CREATE TABLE IF NOT EXISTS solicitantes_mro (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            nome         TEXT NOT NULL,
            nome_norm    TEXT NOT NULL UNIQUE,
            departamento TEXT,
            gerente      TEXT,
            aprovador    TEXT,
            status       TEXT,
            incluir_mro  INTEGER DEFAULT 0,
            data_registro TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Foto diária do saldo por item → base p/ estoque médio, giro, tempo em estoque
    # e evolução do valor imobilizado (decisão rev.3 do blueprint).
    c.execute("""
        CREATE TABLE IF NOT EXISTS estoque_snapshots (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            item_id       INTEGER NOT NULL,
            data          TEXT NOT NULL,
            estoque_atual REAL,
            valor_estoque REAL,
            FOREIGN KEY (item_id) REFERENCES inventario(id) ON DELETE CASCADE,
            UNIQUE(item_id, data)
        )
    """)

    # ── v2.5.0 — Assistente de Reposição (Planejamento) ───────────────────────
    # Log de DESFECHO de cada sugestão de reposição (auditoria + calibração
    # futura). O motor recalcula as sugestões ao vivo (listar_inventario); esta
    # tabela guarda a FOTO do cálculo no momento da decisão do comprador. Aditiva,
    # não-destrutiva; NÃO altera a base do Neidson (mín/máx/lead time/categoria).
    c.execute("""
        CREATE TABLE IF NOT EXISTS sugestoes_reposicao (
            id                 INTEGER PRIMARY KEY AUTOINCREMENT,
            item_id            INTEGER NOT NULL,
            data_geracao       TEXT DEFAULT CURRENT_TIMESTAMP,
            cobertura_dias     REAL,
            rop                REAL,
            alvo               REAL,
            horizonte_dias     INTEGER,
            qtd_sugerida       REAL,
            fornecedor_sugerido TEXT,
            prioridade         TEXT,
            justificativa      TEXT,
            desfecho           TEXT DEFAULT 'gerada',
            sc_id              INTEGER,
            data_desfecho      TEXT,
            observacao         TEXT,
            FOREIGN KEY (item_id) REFERENCES inventario(id) ON DELETE CASCADE,
            FOREIGN KEY (sc_id) REFERENCES solicitacoes_compra(id) ON DELETE SET NULL
        )
    """)

    # Seed dos solicitantes MRO atuais. v3.7.0: + Juan Tarco Pinheiro de Araujo (A5).
    for _nome in (
        "Jasiva Lopes",
        "Luis Gabriel Arruda de Oliveira",
        "Sidinei Correa Alfon",
        "Juan Tarco Pinheiro de Araujo",
    ):
        _norm = _normalizar_nome(_nome)
        c.execute(
            "INSERT OR IGNORE INTO solicitantes_mro (nome, nome_norm, incluir_mro) VALUES (?,?,1)",
            (_nome, _norm),
        )
        # Garante incluir_mro=1 mesmo se a linha já existir (ex.: importada via SCM USERS
        # com incluir_mro=0). Idempotente — não há UI admin para marcar manualmente.
        c.execute("UPDATE solicitantes_mro SET incluir_mro=1 WHERE nome_norm=?", (_norm,))

    # ── Monitor de SC (v3.9.0) — grade editável e persistente do Almoxarifado ──────
    # Substitui a planilha FUP por e-mail. HÍBRIDO: o sistema preenche/atualiza as
    # colunas TÉCNICAS todo dia (por linha_id estável); o almox edita as MANUAIS
    # (status_po/fornecedor/comentario/responsavel) e marca "Revisado" (reset diário).
    # `linha_id` = 'sys:<itens_sc.id>' para linhas de sistema (estável mesmo com PN
    # repetido em SCs diferentes ou a mesma SC/PN 2×) e 'man:<uuid>' para linhas manuais.
    # `ativo` esconde itens que saíram do pendente sem perder as anotações; `removido`
    # é o tombstone de linha de sistema apagada à mão. Backup antes de criar a tabela.
    _monitor_novo = "monitor_sc" not in {
        r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    if _monitor_novo:
        # Commit antes do backup: `_backup_db` abre uma SEGUNDA conexão para o
        # `wal_checkpoint(TRUNCATE)`. Com a transação desta conexão ainda aberta, o
        # checkpoint espera o busy_timeout inteiro, devolve SQLITE_BUSY e o .bak sai
        # sem o conteúdo do WAL. Os CREATE TABLE acima são `IF NOT EXISTS` — commitar
        # aqui é idempotente e não altera o resultado da criação.
        conn.commit()
        _backup_db("pre-monitor-sc-v390")
    c.execute("""
        CREATE TABLE IF NOT EXISTS monitor_sc (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            linha_id      TEXT NOT NULL UNIQUE,
            numero_sc     TEXT,
            part_number   TEXT,
            nome_item     TEXT,
            status_calc   TEXT,
            unidade       TEXT,
            tam_po        REAL,
            saldo_po      REAL,
            esgotado_em   TEXT,
            faltando_dias REAL,
            po            TEXT,
            status_po     TEXT,
            fornecedor    TEXT,
            comentario    TEXT,
            responsavel   TEXT,
            revisado      INTEGER DEFAULT 0,
            revisado_data TEXT,
            origem        TEXT DEFAULT 'sistema',
            ativo         INTEGER DEFAULT 1,
            removido      INTEGER DEFAULT 0,
            data_criacao  TEXT DEFAULT CURRENT_TIMESTAMP,
            data_atualizacao TEXT
        )
    """)
    # Marcador do sync diário (1 linha) — evita re-sincronizar a cada rerun.
    c.execute("""
        CREATE TABLE IF NOT EXISTS monitor_sc_sync (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            ultima_sync TEXT
        )
    """)
    # v4.4.0 — grade LIVRE do Monitor (planilha colável do Excel, colunas genéricas
    # A, B, C…). Documento único em JSON; NÃO interfere no grid técnico nem no sync.
    c.execute("""
        CREATE TABLE IF NOT EXISTS monitor_livre (
            id               INTEGER PRIMARY KEY CHECK (id = 1),
            dados_json       TEXT,
            data_atualizacao TEXT
        )
    """)

    # v4.9.0 — GUARDA-CHUVA (controle MANUAL): acordo de congelamento de preço com o
    # fornecedor para entregas parciais. 100% manual e DESACOPLADO das SCs importadas
    # (itens_sc): o usuário cadastra produto + código de fornecedor + qtd negociada e
    # move o card pelos 4 estágios (estagio é EXPLÍCITO/editável, não derivado). O saldo
    # residual = qtd_negociada − qtd_recebida é derivado na leitura. Não toca estoque
    # nem movimentacoes (é controle, não ledger).
    c.execute("""
        CREATE TABLE IF NOT EXISTS guarda_chuva (
            id                INTEGER PRIMARY KEY AUTOINCREMENT,
            item_id           INTEGER NOT NULL REFERENCES inventario(id),
            fornecedor_codigo TEXT NOT NULL,
            fornecedor_nome   TEXT,
            qtd_negociada     REAL DEFAULT 0,
            qtd_recebida      REAL DEFAULT 0,
            preco_congelado   REAL,
            qtd_ideal_mes     REAL,
            estagio           TEXT DEFAULT 'Pedido Colocado',
            numero_po         TEXT,
            data_acordo       TEXT,
            validade          TEXT,
            observacao        TEXT,
            criado_em         TEXT,
            atualizado_em     TEXT
        )
    """)
    c.execute("CREATE INDEX IF NOT EXISTS idx_guarda_chuva_item ON guarda_chuva(item_id)")

    # v5.9.0 — GUARDA-CHUVA POR PEDIDO. O modelo da v4.9.0 acima trata o acordo como
    # (material × fornecedor) e `numero_po` é texto decorativo que nada lê; um pedido
    # real tem N itens e não existia como entidade. Estas 3 tabelas são ADITIVAS: a
    # `guarda_chuva` antiga fica intacta (só deixa de ser exibida), então nada migra e
    # nenhum dado se perde.
    #
    # A mesma invariante da v4.9.0 vale aqui: é CONTROLE, não ledger — abate o saldo do
    # acordo e NÃO toca `inventario.estoque_atual` nem `movimentacoes`.
    #
    # Cuidado com o nome: "guarda-chuva" tem três sentidos no código — este acordo
    # manual, o pedido sobre `itens_sc` (v4.5.7, `atualizar_pedido_guarda_chuva`) e o
    # `estoque_em_transito` de planejamento.py.
    #
    # Backup UMA vez, só na criação real das tabelas e só se já houver dados: a regra do
    # projeto é "nenhuma alteração de schema sem backup". O `commit()` vem ANTES do
    # `_backup_db` porque os CREATE/ALTER acima deixam transação aberta e o
    # `wal_checkpoint(TRUNCATE)` devolveria BUSY, gravando um .bak incompleto.
    _tem_gc_pedido = c.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='guarda_chuva_pedido'"
    ).fetchone()
    if not _tem_gc_pedido and c.execute("SELECT 1 FROM inventario LIMIT 1").fetchone():
        conn.commit()
        _backup_db("guarda-chuva-pedido-v590")
    c.execute("""
        CREATE TABLE IF NOT EXISTS guarda_chuva_pedido (
            id                INTEGER PRIMARY KEY AUTOINCREMENT,
            numero_pedido     TEXT NOT NULL UNIQUE,
            numero_sc         TEXT,
            fornecedor_codigo TEXT,
            fornecedor_nome   TEXT,
            meses_acordo      INTEGER DEFAULT 2,
            estagio           TEXT DEFAULT 'Pedido Colocado',
            origem            TEXT,
            observacao        TEXT,
            criado_em         TEXT,
            atualizado_em     TEXT
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS guarda_chuva_item (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            pedido_id        INTEGER NOT NULL REFERENCES guarda_chuva_pedido(id) ON DELETE CASCADE,
            item_id          INTEGER NOT NULL REFERENCES inventario(id),
            qtd_negociada    REAL DEFAULT 0,
            qtd_prevista_mes REAL,
            preco_congelado  REAL,
            observacao       TEXT,
            criado_em        TEXT,
            atualizado_em    TEXT,
            UNIQUE(pedido_id, item_id)
        )
    """)
    # Tabela filha do recebimento: permite as 1..12 colunas DINÂMICAS de mês sem 12
    # colunas mortas na linha do item. O saldo residual segue derivado na leitura
    # (qtd_negociada − SUM(quantidade)), como já era na v4.9.0.
    c.execute("""
        CREATE TABLE IF NOT EXISTS guarda_chuva_recebimento (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            gc_item_id    INTEGER NOT NULL REFERENCES guarda_chuva_item(id) ON DELETE CASCADE,
            mes_seq       INTEGER NOT NULL,
            quantidade    REAL DEFAULT 0,
            atualizado_em TEXT,
            UNIQUE(gc_item_id, mes_seq)
        )
    """)
    c.execute("CREATE INDEX IF NOT EXISTS idx_gc_item_pedido ON guarda_chuva_item(pedido_id)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_gc_receb_item ON guarda_chuva_recebimento(gc_item_id)")

    # v5.1.0 (F2) — Itens de SC cujo PN NÃO está no inventário MRO. Antes eram
    # simplesmente descartados na ingestão (Excel e API); agora ficam registrados aqui,
    # ligados à SC, para visibilidade completa do ciclo SC→PO e futura "promoção" ao
    # inventário. Aditiva; UNIQUE(sc_id, part_number) garante upsert idempotente.
    c.execute("""
        CREATE TABLE IF NOT EXISTS itens_sc_externos (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            sc_id            INTEGER NOT NULL,
            part_number      TEXT NOT NULL,
            descricao        TEXT,
            quantidade       REAL DEFAULT 0,
            unidade          TEXT,
            preco_unitario   REAL DEFAULT 0,
            valor_total      REAL DEFAULT 0,
            numero_po        TEXT,
            data_necessidade TEXT,
            origem           TEXT,
            data_registro    TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (sc_id) REFERENCES solicitacoes_compra(id) ON DELETE CASCADE,
            UNIQUE(sc_id, part_number)
        )
    """)

    # v6.1.0 — Usuários e login local (100% local, sem dependência externa: nem OIDC,
    # nem API do SCM, nem TI). Tabela NOVA e vazia ao migrar — não toca linha existente,
    # portanto aditiva e sem `_backup_db` (mesmo padrão de `itens_sc_externos`, v5.1.0).
    # Se algum dia o seed passar a reescrever linha existente, exige backup antes.
    #
    # pin_hash   = 'pbkdf2:sha256:200000:<salt_hex>:<hash_hex>' | NULL = sem PIN (não autentica).
    # nome_norm  = `_normalizar_nome` (mesma regra de `solicitantes_mro`) — identidade da pessoa.
    # ident_norm = chave de BUSCA do login: nome_norm sem ponto e sem espaço, para que
    #              "Jasiva Lopes", "jasiva.lopes" e " JASIVA  LOPES " caiam na mesma conta.
    # solic_mro_id liga ao solicitante de origem com ON DELETE SET NULL: tirar alguém do
    #              escopo MRO nunca pode apagar o usuário (e sua senha) junto.
    c.execute("""
        CREATE TABLE IF NOT EXISTS usuarios (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            nome          TEXT NOT NULL,
            nome_norm     TEXT NOT NULL UNIQUE,
            login         TEXT,
            ident_norm    TEXT NOT NULL UNIQUE,
            pin_hash      TEXT,
            papel         TEXT NOT NULL DEFAULT 'requisitante',
            departamento  TEXT,
            ativo         INTEGER DEFAULT 1,
            solic_mro_id  INTEGER REFERENCES solicitantes_mro(id) ON DELETE SET NULL,
            ultimo_login  TEXT,
            data_registro TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # v5.1.0 (F2) — código Protheus do solicitante (ex.: "001054"), necessário para o
    # endpoint ByUser do sync SCM. Resolvido por nome via /Usuario (ou preenchido à mão
    # em Configurações). Nullable — solicitantes sem código apenas não entram no sync.
    cols_sm = {r[1] for r in conn.execute("PRAGMA table_info(solicitantes_mro)")}
    if "codigo" not in cols_sm:
        conn.execute("ALTER TABLE solicitantes_mro ADD COLUMN codigo TEXT")
        logger.info("  -> Migracao: codigo em solicitantes_mro adicionada.")

    cols_sc = {r[1] for r in conn.execute("PRAGMA table_info(solicitacoes_compra)")}
    novas_cols_sc = {
        "solicitante": "TEXT",
        "descricao_solicitacao": "TEXT",
        "status_protheus": "TEXT",
        "prioridade_critica": "INTEGER DEFAULT 0",
        "origem_importacao": "TEXT",
        "data_importacao": "TEXT",
        # v3.5.0 — Dashboard de Comprador: comprador real (coluna do Relatório),
        # data de emissão do PO (DT Emissão), saving (R$) e departamento por SC.
        "comprador": "TEXT",
        "data_po": "TEXT",
        "saving": "REAL",
        "departamento": "TEXT",
        # v5.1.0 (F2) — Sincronização SCM persistente (API → mro.db). sc_id_scm é o id
        # inteiro da SC na API (fonte de dedup ao lado de numero_sc); centro_custo vem do
        # ByUser/Timeline; data_sync_api marca a última vez que a API atualizou esta SC.
        "sc_id_scm": "INTEGER",
        "centro_custo": "TEXT",
        "data_sync_api": "TEXT",
        # v5.2.0 (F3) — código da cotação (CTxxxxx) vindo do ByUser; ponte para o detalhe
        # "ao vivo" da cotação (GetByCodigo) na página SCM Integrado. Já era extraído por
        # normalizar_sc_api; agora é persistido.
        "cotacao_codigo": "TEXT",
    }
    for col, tipo in novas_cols_sc.items():
        if col not in cols_sc:
            conn.execute(f"ALTER TABLE solicitacoes_compra ADD COLUMN {col} {tipo}")
            logger.info("  -> Migracao: %s em solicitacoes_compra adicionada.", col)

    cols_isc = {r[1] for r in conn.execute("PRAGMA table_info(itens_sc)")}
    novas_cols_isc = {
        "descricao_detalhada": "TEXT",
        "quantidade_pedido": "REAL DEFAULT 0",
        "fornecedor_item": "TEXT",
        "data_prev_nfe": "TEXT",
        "documento_nf": "TEXT",
        "quantidade_nfe": "REAL DEFAULT 0",
        "saldo_residual": "REAL DEFAULT 0",
        "status_item": "TEXT DEFAULT 'Aberto'",
        "ruptura": "INTEGER DEFAULT 0",
        "divergencia_compra": "INTEGER DEFAULT 0",
        "ultima_importacao": "TEXT",
        # v2.2.0 — pilar financeiro (captura de preço do Relatório de SCs / SC7)
        "preco_unitario": "REAL DEFAULT 0",
        "valor_total": "REAL DEFAULT 0",
        "moeda": "TEXT",
        # v5.1.0 (F2) — origem do item ('excel' | 'api_scm'), para rastrear a fonte que
        # preencheu a linha (a API enriquece, o Excel é fallback).
        "origem": "TEXT",
    }
    for col, tipo in novas_cols_isc.items():
        if col not in cols_isc:
            conn.execute(f"ALTER TABLE itens_sc ADD COLUMN {col} {tipo}")
            logger.info("  -> Migracao: %s em itens_sc adicionada.", col)

    # Indices de performance (v2.0.2 / DT-9): FKs nao geram indice automatico no
    # SQLite. part_number ja possui indice via UNIQUE (sqlite_autoindex_inventario_1),
    # portanto idx_inv_pn nao e recriado (seria redundante).
    c.execute("CREATE INDEX IF NOT EXISTS idx_mov_item    ON movimentacoes(item_id)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_mov_data    ON movimentacoes(data_hora)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_itens_sc_sc ON itens_sc(sc_id)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_pnhist_item ON part_numbers_historico(item_id)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_pnhist_antigo ON part_numbers_historico(pn_antigo)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_feedback_status ON feedbacks(status)")
    # v2.2.0 — índices de apoio à ingestão rica e às novas telas
    c.execute("CREATE INDEX IF NOT EXISTS idx_itens_sc_item ON itens_sc(item_id)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_sc_status     ON solicitacoes_compra(status)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_precos_item   ON precos_historico(item_id)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_forn_cod_loja ON fornecedores(codigo, loja)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_snap_item_data ON estoque_snapshots(item_id, data)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_forn_item     ON fornecedor_item(item_id)")
    # v2.5.0 — histórico de sugestões de reposição (consultas por item e por data).
    c.execute("CREATE INDEX IF NOT EXISTS idx_sugest_item   ON sugestoes_reposicao(item_id)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_sugest_data   ON sugestoes_reposicao(data_geracao)")
    # v5.1.0 (F2) — apoio ao sync SCM e às consultas por solicitante/comprador/id-API.
    c.execute("CREATE INDEX IF NOT EXISTS idx_sc_solicitante ON solicitacoes_compra(solicitante)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_sc_comprador   ON solicitacoes_compra(comprador)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_sc_scmid       ON solicitacoes_compra(sc_id_scm)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_isc_ext_sc     ON itens_sc_externos(sc_id)")
    # v6.1.0 — o filtro de menu por papel e a guarda do "último almoxarife" consultam
    # por papel a cada render; `ident_norm`/`nome_norm` já têm índice via UNIQUE.
    c.execute("CREATE INDEX IF NOT EXISTS idx_usuarios_papel ON usuarios(papel)")

    conn.commit()
    _migrar(conn)
    _migrar_inventario_tipo_livre(conn)

    # v2.2.0 — novas colunas de inventario. Executado APÓS o rebuild de
    # _migrar_inventario_tipo_livre (que recria a tabela com um conjunto fixo de
    # colunas); do contrário estas colunas seriam descartadas no rebuild.
    # preco_referencia/data_preco_ref: valoração; estoque_seguranca_calculado:
    # sugestão (o estoque_seguranca passa a ser parâmetro MANUAL do gestor).
    cols_inv0 = {r[1] for r in conn.execute("PRAGMA table_info(inventario)")}
    for col, tipo in {
        "preco_referencia": "REAL DEFAULT 0",
        "data_preco_ref": "TEXT",
        "estoque_seguranca_calculado": "REAL DEFAULT 0",
        # v2.2.1 — cálculos de série (consumo multi-janela, tendência) e Lead Time
        # calculado como SUGESTÃO (não sobrescreve lead_time_dias / base do Neidson).
        "consumo_30d": "REAL DEFAULT 0",
        "consumo_60d": "REAL DEFAULT 0",
        "consumo_90d": "REAL DEFAULT 0",
        "tendencia_pct": "REAL",
        "tendencia_label": "TEXT",
        "lead_time_calculado": "INTEGER",
        "lead_time_calculado_amostras": "INTEGER DEFAULT 0",
        "lead_time_calculado_origem": "TEXT",
        # v2.6.0 — Ficha 360: caminho da imagem do produto (arquivo em docs/itens/,
        # fora do SQLite para nao inchar o .db). Nullable; nao afeta a base do Neidson.
        "imagem_path": "TEXT",
        # v2.9.0 — Conversão de Unidades (Fundação). O item é CADASTRADO numa unidade
        # de estoque (`unidade`, base do Neidson) mas COMPRADO em outra (L, KG, par,
        # bombona…). `unidade_compra` (livre: L/KG/P/BB… — NÃO entra no CHECK de
        # `unidade`) e `fator_conversao` (quantas unidade_compra cabem em 1 unidade de
        # estoque) são CURADOS: o sistema sugere, o gestor confirma. NULL/1 = no-op
        # (comportamento idêntico ao de hoje para os itens de UM única).
        "unidade_compra": "TEXT",
        "fator_conversao": "REAL DEFAULT 1",
        # v3.4.0 — 2ª locação: 2º ponto de armazenagem do mesmo item (Contagem Física),
        # independente do Ajuste Rápido de Movimentações.
        "local_armazenagem_2": "TEXT",
    }.items():
        if col not in cols_inv0:
            conn.execute(f"ALTER TABLE inventario ADD COLUMN {col} {tipo}")
            logger.info("  -> Migracao: %s em inventario adicionada.", col)
    conn.commit()

    # v2.4.0 — lead time por linha SC7 em precos_historico (delta Dt.Entrega − DT
    # Emissao). Persiste o dado que a v2.2.1 calculava e descartava, permitindo
    # atribuir lead time ao fornecedor via numero_po (SC7 × SCM). Coluna nullable.
    cols_ph = {r[1] for r in conn.execute("PRAGMA table_info(precos_historico)")}
    if "lead_time_dias" not in cols_ph:
        conn.execute("ALTER TABLE precos_historico ADD COLUMN lead_time_dias INTEGER")
        logger.info("  -> Migracao: lead_time_dias em precos_historico adicionada.")
        conn.commit()

    # v2.9.0 — UM de compra observada por linha de PO (abas SCM/SC7 do Relatório de
    # SCs). Fonte da SUGESTÃO de `inventario.unidade_compra`; a ingestão a capturava
    # e descartava antes desta versão. Coluna livre e nullable.
    if "unidade" not in cols_ph:
        conn.execute("ALTER TABLE precos_historico ADD COLUMN unidade TEXT")
        logger.info("  -> Migracao: unidade em precos_historico adicionada.")
        conn.commit()

    # v3.3.0 — Correção do estoque de segurança (bug dos "números quebrados"): o
    # recebimento de SC gravava a SUGESTÃO (consumo × lead time × 1,5, fracionária) na
    # coluna MANUAL `estoque_seguranca`, contaminando o parâmetro do gestor.
    #   (a) normaliza a SUGESTÃO calculada p/ inteiro (arredonda p/ cima, como o novo cálculo);
    #   (b) reseta valores MANUAIS não-inteiros (só podiam vir do bug) p/ 0 → o efetivo cai
    #       para a sugestão. Inteiros do gestor são preservados. Idempotente.
    conn.execute("""
        UPDATE inventario
           SET estoque_seguranca_calculado = CAST(estoque_seguranca_calculado AS INTEGER)
               + (estoque_seguranca_calculado > CAST(estoque_seguranca_calculado AS INTEGER))
         WHERE estoque_seguranca_calculado IS NOT NULL
           AND estoque_seguranca_calculado <> CAST(estoque_seguranca_calculado AS INTEGER)
    """)
    conn.commit()
    _tem_frac = conn.execute(
        """SELECT 1 FROM inventario
            WHERE estoque_seguranca IS NOT NULL
              AND estoque_seguranca <> CAST(estoque_seguranca AS INTEGER) LIMIT 1"""
    ).fetchone()
    if _tem_frac:
        _backup_db("fix-seguranca-v330")
        conn.execute(
            """UPDATE inventario SET estoque_seguranca = 0
                WHERE estoque_seguranca IS NOT NULL
                  AND estoque_seguranca <> CAST(estoque_seguranca AS INTEGER)"""
        )
        conn.commit()
        logger.info("  -> v3.3.0: estoque_seguranca manual fracionário resetado (bug corrigido).")

    conn.execute("PRAGMA optimize;")
    conn.close()
    # v6.0.0 — a versão vem de services/constants (fonte única). Este log dizia 5.7.0
    # com o app na 5.9.0, porque era um literal que ninguém lembrava de bumpar.
    logger.info("Banco de dados criado/verificado com sucesso. Versão %s", VERSAO)


def _migrar(conn):
    cols_inv = {r[1] for r in conn.execute("PRAGMA table_info(inventario)")}
    if "data_inventario" not in cols_inv:
        conn.execute("ALTER TABLE inventario ADD COLUMN data_inventario TEXT")
        logger.info("  ↳ Migração: data_inventario adicionada.")

    cols_mov = {r[1] for r in conn.execute("PRAGMA table_info(movimentacoes)")}
    if "requisicao_id" not in cols_mov:
        conn.execute("ALTER TABLE movimentacoes ADD COLUMN requisicao_id INTEGER")
        logger.info("  ↳ Migração: requisicao_id em movimentacoes adicionada.")
    # v4.3.0 — subtipo do lançamento manual (Ajuste Rápido de 4 tipos). Coluna
    # nullable e aditiva: o CHECK de `tipo` permanece ('entrada','saida','devolucao');
    # os 4 rótulos da UI mapeiam para esses 3 tipos e guardam o rótulo aqui.
    if "motivo" not in cols_mov:
        conn.execute("ALTER TABLE movimentacoes ADD COLUMN motivo TEXT")
        logger.info("  ↳ Migração: motivo em movimentacoes adicionada.")

    cols_isc = {r[1] for r in conn.execute("PRAGMA table_info(itens_sc)")}
    if "numero_po" not in cols_isc:
        conn.execute("ALTER TABLE itens_sc ADD COLUMN numero_po TEXT")
        logger.info("  ↳ Migração: numero_po em itens_sc adicionada.")

    # v4.7.0 — Requisição Digital: ciclo de vida (Aberta→Parcial→Entregue/Cancelada).
    # Coluna aditiva. Requisições legadas usavam o modelo de baixa-na-criação (o estoque
    # já saiu quando a requisição foi criada), logo são retro-marcadas como 'Entregue'.
    # Backup antes de tocar dados legados (regra do projeto: schema só com backup).
    cols_req = {r[1] for r in conn.execute("PRAGMA table_info(requisicoes)")}
    if "status" not in cols_req:
        if conn.execute("SELECT 1 FROM requisicoes LIMIT 1").fetchone():
            # Mesmo motivo do backup do monitor_sc: os ALTER TABLE acima deixam
            # transação aberta. Sem este commit o backup sai incompleto justamente
            # antes do UPDATE que reescreve o status das requisições legadas.
            conn.commit()
            _backup_db("req-status-v470")
        conn.execute("ALTER TABLE requisicoes ADD COLUMN status TEXT DEFAULT 'Aberta'")
        conn.execute("UPDATE requisicoes SET status='Entregue'")  # legado: baixa já feita na criação
        logger.info("  ↳ Migração v4.7.0: status em requisicoes adicionada (legado → Entregue).")

    # v5.6.0 — backfill de `itens_sc.origem`. A coluna existe desde a v5.1.0, mas só o sync
    # da API a preenchia: o ingestor Excel nunca gravou, e a tela do SCM Integrado mostrava
    # "Origem" sempre vazia. Como nenhuma SC chegou pela API (nenhuma tem `sc_id_scm`), todo
    # item já gravado é comprovadamente de origem Excel. Idempotente: na segunda execução o
    # SELECT não encontra nada. Nunca regride linhas já marcadas 'api_scm'/'manual'.
    if (
        "origem" in cols_isc
        and conn.execute("SELECT 1 FROM itens_sc WHERE origem IS NULL LIMIT 1").fetchone()
    ):
        # Mesmo motivo do backup da v4.7.0: os ALTER TABLE acima deixam transação aberta e
        # sem este commit o backup sai incompleto, justamente antes de reescrever dados.
        conn.commit()
        _backup_db("itens-sc-origem-v560")
        conn.execute("UPDATE itens_sc SET origem='excel' WHERE origem IS NULL")
        logger.info("  ↳ Migração v5.6.0: itens_sc.origem retroativa → 'excel'.")

    # v5.7.0 — fonte de verdade do recebimento. Até aqui o import do Protheus e a edição
    # manual sobrescreviam `itens_sc.quantidade_recebida` com a "Qtd Entregue" do ERP,
    # apagando o recebimento parcial que o almoxarifado havia conferido na doca. A partir
    # de agora `quantidade_recebida` é escrita SÓ pelo MRO (`registrar_recebimento_sc`) e o
    # número do Protheus vive nesta coluna espelho, usada apenas para exibir divergência.
    # Aditiva e sem backfill: NULL = "o Protheus ainda não declarou nada para esta linha",
    # que é a verdade — o valor hoje em `quantidade_recebida` pode ser tanto do ERP quanto
    # do MRO, e chutar um deles inventaria divergência onde não há. O primeiro import
    # preenche o espelho naturalmente.
    if "quantidade_recebida_protheus" not in cols_isc:
        if conn.execute("SELECT 1 FROM itens_sc LIMIT 1").fetchone():
            # Mesmo motivo do backup da v4.7.0/v5.6.0: os ALTER TABLE acima deixam transação
            # aberta e sem este commit o `wal_checkpoint` devolve BUSY e o .bak sai incompleto.
            conn.commit()
            _backup_db("itens-sc-recebida-protheus-v570")
        conn.execute("ALTER TABLE itens_sc ADD COLUMN quantidade_recebida_protheus REAL")
        logger.info("  ↳ Migração v5.7.0: quantidade_recebida_protheus em itens_sc adicionada.")

    # v5.7.0 — a Requisição Padrão volta a existir ao lado da Digital (decisão nº1 da
    # entrevista de 27/07/2026), e esta coluna registra por qual fluxo cada pedido nasceu:
    # 'Padrão' baixa o estoque na criação, 'Digital' só na entrega. Sem ela as duas viram a
    # mesma linha no histórico e não há como auditar por que uma requisição já nasceu
    # Entregue. Aditiva e SEM backfill: NULL = requisição legada, exibida como "—". Inferir
    # o fluxo das antigas pela data seria chute — a Padrão foi removida na v4.7.0 e o corte
    # não é limpo (a migração da v4.7.0 já retro-marcou as legadas como 'Entregue').
    if "tipo_fluxo" not in cols_req:
        if conn.execute("SELECT 1 FROM requisicoes LIMIT 1").fetchone():
            # Mesmo motivo dos backups da v4.7.0/v5.6.0: os ALTER TABLE acima deixam
            # transação aberta e sem este commit o `wal_checkpoint` devolve BUSY e o .bak
            # sai incompleto.
            conn.commit()
            _backup_db("requisicoes-tipo-fluxo-v570")
        conn.execute("ALTER TABLE requisicoes ADD COLUMN tipo_fluxo TEXT")
        logger.info("  ↳ Migração v5.7.0: tipo_fluxo em requisicoes adicionada (legado → NULL).")

    # v6.2.0 — aprovação do gestor (tela "Aprovações do Setor"). Registra QUEM autorizou o
    # pedido do setor e QUANDO. NÃO é status (fora do CHECK de `status`, de propósito) e NÃO
    # bloqueia separação/entrega: é a autorização antecipada do fluxo self-service, paralela
    # ao `autorizador_*`, que continua sendo exigido do almoxarife na ENTREGA. Aditiva e sem
    # backfill: NULL = "nenhum gestor aprovou", que é a verdade sobre todo o legado — as
    # requisições anteriores nasceram sem esta etapa. O guard olha as DUAS colunas e cada
    # ALTER tem o seu `if`: o sqlite3 não abre transação para DDL, então um crash entre os
    # dois ADD COLUMN deixaria a primeira coluna já commitada, e um guard só em
    # `aprovado_por` nunca mais completaria a segunda.
    if "aprovado_por" not in cols_req or "aprovado_em" not in cols_req:
        if conn.execute("SELECT 1 FROM requisicoes LIMIT 1").fetchone():
            # Mesmo motivo dos backups da v4.7.0/v5.6.0/v5.7.0: os ALTER TABLE acima deixam
            # transação aberta e sem este commit o `wal_checkpoint` devolve BUSY e o .bak
            # sai incompleto.
            conn.commit()
            _backup_db("requisicoes-aprovacao-gestor-v620")
        if "aprovado_por" not in cols_req:
            conn.execute("ALTER TABLE requisicoes ADD COLUMN aprovado_por TEXT")
        if "aprovado_em" not in cols_req:
            conn.execute("ALTER TABLE requisicoes ADD COLUMN aprovado_em TEXT")
        logger.info("  ↳ Migração v6.2.0: aprovado_por/aprovado_em em requisicoes adicionadas.")

    conn.commit()


def diretorio_backups():
    """Pasta dos backups: `backups/` ao lado do banco (v5.5.0 / F5).

    No servidor o banco fica em `C:\\MRO\\dados\\mro.db`, então os .bak caem em
    `C:\\MRO\\dados\\backups\\` — fora da pasta do app, que é substituída inteira a
    cada atualização (`atualizar_mro.bat`)."""
    return os.path.join(os.path.dirname(os.path.abspath(DB_PATH)), "backups")


def _backup_db(sufixo="pre-migracao"):
    """Copia o banco para `backups/` com timestamp antes de migração destrutiva.
    Faz checkpoint do WAL para garantir que o arquivo principal esteja atualizado.
    Não falha a migração se o backup não puder ser feito (apenas loga)."""
    import shutil

    try:
        if not os.path.exists(DB_PATH):
            return None
        cp = sqlite3.connect(DB_PATH, timeout=5.0)
        # `PRAGMA wal_checkpoint` NÃO levanta exceção quando falha: devolve
        # (busy, n_wal, n_checkpoint) com busy=1 em SQLITE_BUSY. Sem checar esse
        # retorno, um checkpoint bloqueado vira falso sucesso e o .bak é gravado sem
        # o WAL — exatamente antes de uma migração destrutiva.
        busy, _, _ = cp.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
        cp.close()
        if busy:
            logger.warning(
                "  ↳ Checkpoint do WAL retornou BUSY (lock ativo): o backup '%s' pode estar "
                "incompleto. Verifique se há transação aberta antes do backup.",
                sufixo,
            )
        destino_dir = diretorio_backups()
        os.makedirs(destino_dir, exist_ok=True)
        carimbo = datetime.now().strftime("%Y%m%d-%H%M%S")
        nome = f"{os.path.basename(DB_PATH)}.bak-{carimbo}-{sufixo}"
        destino = os.path.join(destino_dir, nome)
        shutil.copy2(DB_PATH, destino)
        logger.info("  ↳ Backup do banco criado: %s", destino)
        return destino
    except Exception as e:
        logger.warning("  ↳ Não foi possível criar backup automático: %s", e)
        return None


def _migrar_inventario_tipo_livre(conn):
    """Migração v2.1.0 (Item 1): libera tipo_material (remove CHECK) e adiciona
    estoque_maximo. Como SQLite não remove CHECK via ALTER, faz rebuild seguro da
    tabela (procedimento oficial de 12 passos), preservando ids e FKs por item_id.

    Guarda: só executa se o CHECK em tipo_material ainda existir. Idempotente.
    """
    row = conn.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='inventario'").fetchone()
    if not row or not row[0]:
        return
    sql_atual = row[0]
    # Se o CHECK de tipo_material não está mais presente, a migração já rodou.
    if "tipo_material" not in sql_atual or "CHECK(tipo_material" not in sql_atual.replace(" ", "").replace(
        "CHECK (", "CHECK("
    ):
        # Garante apenas que estoque_maximo exista (caso de schema já sem CHECK).
        cols = {r[1] for r in conn.execute("PRAGMA table_info(inventario)")}
        if "estoque_maximo" not in cols:
            conn.execute("ALTER TABLE inventario ADD COLUMN estoque_maximo REAL DEFAULT 0")
            conn.commit()
            logger.info("  ↳ Migração: estoque_maximo adicionada em inventario.")
        return

    logger.info("  ↳ Migração v2.1.0: rebuild de inventario (tipo_material livre + estoque_maximo)...")
    _backup_db("inventario-rebuild")

    # Colunas preservadas (mesma ordem do schema original), copiadas 1:1.
    cols_orig = [
        "id",
        "part_number",
        "nome_item",
        "descricao",
        "unidade",
        "importancia",
        "tipo_material",
        "setor_responsavel",
        "local_armazenagem",
        "caixa_identificacao",
        "estoque_atual",
        "estoque_minimo",
        "estoque_seguranca",
        "consumo_medio_diario",
        "lead_time_dias",
        "previsao_ruptura_dias",
        "ultima_sc_id",
        "data_inventario",
        "data_criacao",
        "data_atualizacao",
    ]
    lista_cols = ", ".join(cols_orig)

    conn.commit()  # garante que não há transação aberta
    iso_anterior = conn.isolation_level
    conn.isolation_level = None  # autocommit: permite toggle de foreign_keys
    try:
        conn.execute("PRAGMA foreign_keys=OFF")
        conn.execute("BEGIN")
        conn.execute("""
            CREATE TABLE inventario_new (
                id                    INTEGER PRIMARY KEY AUTOINCREMENT,
                part_number           TEXT UNIQUE NOT NULL,
                nome_item             TEXT NOT NULL,
                descricao             TEXT,
                unidade               TEXT CHECK(unidade IN ('GL','UN','CX','RL','PCT','LT','RM')),
                importancia           TEXT CHECK(importancia IN ('Parada de Linha','Importante','Admin')),
                tipo_material         TEXT,
                setor_responsavel     TEXT CHECK(setor_responsavel IN ('Improdutivo','Engenharia de SMT','LED DRIVER','MANUTENÇÃO','PRODUÇÃO','QUALIDADE','ALMOXARIFADO','ADMINISTRATIVO','SESMT')),
                local_armazenagem     TEXT,
                caixa_identificacao   TEXT,
                estoque_atual         REAL DEFAULT 0,
                estoque_minimo        REAL DEFAULT 0,
                estoque_maximo        REAL DEFAULT 0,
                estoque_seguranca     REAL DEFAULT 0,
                consumo_medio_diario  REAL DEFAULT 0,
                lead_time_dias        INTEGER DEFAULT 0,
                previsao_ruptura_dias REAL DEFAULT 999,
                ultima_sc_id          INTEGER,
                data_inventario       TEXT,
                data_criacao          TEXT DEFAULT CURRENT_TIMESTAMP,
                data_atualizacao      TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (ultima_sc_id) REFERENCES solicitacoes_compra(id)
            )
        """)
        conn.execute(f"INSERT INTO inventario_new ({lista_cols}) SELECT {lista_cols} FROM inventario")
        conn.execute("DROP TABLE inventario")
        conn.execute("ALTER TABLE inventario_new RENAME TO inventario")
        problemas = conn.execute("PRAGMA foreign_key_check").fetchall()
        if problemas:
            conn.execute("ROLLBACK")
            raise RuntimeError(f"foreign_key_check falhou no rebuild de inventario: {problemas}")
        conn.execute("COMMIT")
        conn.execute("PRAGMA foreign_keys=ON")
        logger.info("  ↳ Rebuild de inventario concluído com sucesso (FKs íntegras).")
    except Exception:
        try:
            conn.execute("ROLLBACK")
        except Exception:
            pass
        conn.execute("PRAGMA foreign_keys=ON")
        raise
    finally:
        conn.isolation_level = iso_anterior


if __name__ == "__main__":
    from services.logging_config import setup_logging

    setup_logging()
    criar_banco()
