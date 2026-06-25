import sqlite3
import os
import logging
from datetime import datetime
from contextlib import contextmanager

DB_PATH = "mro.db"
logger = logging.getLogger(__name__)

def get_connection():
    conn = sqlite3.connect(DB_PATH, timeout=5.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
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

    # ══════════════════════════════════════════════════════════════════════════════
    # PADRONIZAÇÃO DE LISTAS MESTRAS (v2.0.0)
    # ══════════════════════════════════════════════════════════════════════════════
    
    # 1. CENTROS DE CUSTO (Padrão: CÓDIGO - NOME)
    centros_custo = [
    "21101 - GERENCIA PRODUCAO", "21102 - WI-FI INFORMATICA", "21103 - BATERIA CELULAR", "21104 - BATERIA GPS", 
    "21105 - PTH", "21106 - MANUTENÇÃO", "21107 - QUALIDADE", "21108 - BATERIA NOTEBOOK", 
    "21109 - WI-FI AUDIO VIDEO", "21110 - EYELET", "21111 - SMD AUDIO VIDEO", "21112 - BATERIA PARA TABLET", 
    "21115 - SMD", "21116 - ADAPTADORES", "21117 - ENGENHARIA DE MANUFATURA", "21119 - BATERIA PARA FONE DE OUVIDO", 
    "21120 - ENGENHARIA MANUFATURA SMD", "21121 - MAO DE OBRA DIRETA", "21122 - ENGENHARIA MANUFATURA ADAPTADORES", "21123 - ADAPTADOR CELULAR", 
    "21124 - TRANSFORMADOR", "21125 - MODEM (ASKEY)", "21126 - TAMPOGRAFIA DE BATERIA DE CELULAR", "21127 - TAMPOGRAFIA DE MODEM", 
    "21128 - SUBPR ADAPTADOR DE CELULAR", "21129 - SUBPR MODEM", "21130 - FPCB BATERIA DE CELULAR", "21131 - FPCB BATERIA DE NOTEBOOK", 
    "21132 - SUBP PCBA MODEM", "21133 - TAMPOGRAFIA DE BATERIA DE DE NOTE/TABLET", "21134 - BATERIA PARA SMART WATCH", "21191 - COMPRAS", 
    "21192 - PCP", "21194 - ALMOXARIFADO", "21203 - EXPEDI.TDI", "21210 - BATERIA PARA CELULAR", 
    "21211 - BATERIA PARA NOTEBOOK", "21212 - WI-FI WLAN", "21213 - WI-FI AUDIO/VIDEO", "21214 - ADAPTADOR", 
    "21215 - ADAPTADOR PARA CELULAR", "21216 - MODEM", "21217 - CORREDOR DE IMPORTACAO", "21218 - BATERIA PARA TABLET", 
    "21301 - ENGENHARIA PRODUTO", "90401 - FINANCEIRO", "90402 - DSI", "90501 - RECURSOS HUMANOS", 
    "90502 - SERVICOS GERAIS", "90503 - APRENDIZES", "90604 - SERVICOS AO CLIENTE", "90701 - GERENCIA DA PLANTA", 
    "90702 - MELHORIA CONTINUA", "99000 - ATIVO PASSIVO RES. F"
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
        "SALA-ALMOXARIFADO" # Padronizado com hífen
    ]
    locais.extend(locais_especiais)

    # 3. AUTORIZADORES (Mantidos)
    autorizadores = [
        "Gestor", "Líder", "Reserva", "Técnico"
    ]

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

    cols_sc = {r[1] for r in conn.execute("PRAGMA table_info(solicitacoes_compra)")}
    novas_cols_sc = {
        "solicitante": "TEXT",
        "descricao_solicitacao": "TEXT",
        "status_protheus": "TEXT",
        "prioridade_critica": "INTEGER DEFAULT 0",
        "origem_importacao": "TEXT",
        "data_importacao": "TEXT",
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

    conn.commit()
    _migrar(conn)
    _migrar_inventario_tipo_livre(conn)
    conn.execute("PRAGMA optimize;")
    conn.close()
    logger.info("Banco de dados criado/verificado com sucesso. Versão 2.1.0")


def _migrar(conn):
    cols_inv = {r[1] for r in conn.execute("PRAGMA table_info(inventario)")}
    if "data_inventario" not in cols_inv:
        conn.execute("ALTER TABLE inventario ADD COLUMN data_inventario TEXT")
        logger.info("  ↳ Migração: data_inventario adicionada.")

    cols_mov = {r[1] for r in conn.execute("PRAGMA table_info(movimentacoes)")}
    if "requisicao_id" not in cols_mov:
        conn.execute("ALTER TABLE movimentacoes ADD COLUMN requisicao_id INTEGER")
        logger.info("  ↳ Migração: requisicao_id em movimentacoes adicionada.")

    cols_isc = {r[1] for r in conn.execute("PRAGMA table_info(itens_sc)")}
    if "numero_po" not in cols_isc:
        conn.execute("ALTER TABLE itens_sc ADD COLUMN numero_po TEXT")
        logger.info("  ↳ Migração: numero_po em itens_sc adicionada.")

    conn.commit()


def _backup_db(sufixo="pre-migracao"):
    """Copia mro.db para um arquivo .bak com timestamp antes de migração destrutiva.
    Faz checkpoint do WAL para garantir que o arquivo principal esteja atualizado.
    Não falha a migração se o backup não puder ser feito (apenas loga)."""
    import shutil
    try:
        if not os.path.exists(DB_PATH):
            return None
        cp = sqlite3.connect(DB_PATH, timeout=5.0)
        cp.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        cp.close()
        carimbo = datetime.now().strftime("%Y%m%d-%H%M%S")
        destino = f"{DB_PATH}.bak-{carimbo}-{sufixo}"
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
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='inventario'"
    ).fetchone()
    if not row or not row[0]:
        return
    sql_atual = row[0]
    # Se o CHECK de tipo_material não está mais presente, a migração já rodou.
    if "tipo_material" not in sql_atual or "CHECK(tipo_material" not in sql_atual.replace(" ", "").replace("CHECK (", "CHECK("):
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
        "id", "part_number", "nome_item", "descricao", "unidade", "importancia",
        "tipo_material", "setor_responsavel", "local_armazenagem", "caixa_identificacao",
        "estoque_atual", "estoque_minimo", "estoque_seguranca", "consumo_medio_diario",
        "lead_time_dias", "previsao_ruptura_dias", "ultima_sc_id", "data_inventario",
        "data_criacao", "data_atualizacao",
    ]
    lista_cols = ", ".join(cols_orig)

    conn.commit()                       # garante que não há transação aberta
    iso_anterior = conn.isolation_level
    conn.isolation_level = None         # autocommit: permite toggle de foreign_keys
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
        conn.execute(
            f"INSERT INTO inventario_new ({lista_cols}) SELECT {lista_cols} FROM inventario"
        )
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
