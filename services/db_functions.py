import sqlite3, json, re, unicodedata
import logging
from datetime import datetime, date, timedelta
from database import transaction
from services.constants import (
    MARGEM_ATENCAO,
    FATOR_ESTOQUE_MAXIMO,
    JANELA_CONSUMO_DIAS,
    PREVISAO_RUPTURA_SEM_RISCO,
    SNAPSHOT_RETENCAO_DIAS,
    RELATORIO_SCS_ABAS,
    decodificar_moeda,
    JANELAS_CONSUMO,
    TENDENCIA_LIMIAR_PCT,
    GIRO_JANELA_DIAS,
    LEAD_TIME_MAX_DIAS,
    ABC_LIMIAR_A,
    ABC_LIMIAR_B,
    VALOR_CONSUMIDO_JANELA_DIAS,
    MOEDA_PADRAO,
    SAIDA_REAL_WHERE,
    STATUS_SEM_MOVIMENTACAO,
    FATOR_CONVERSAO_PADRAO,
    CC_INVENTARIO,
    CC_EDICAO,
    extrair_fator_embalagem,
    TIPOS,
    UNIDADES,
)
from services import consumo_sc7 as CS7
from collections import Counter
import pandas as pd

logger = logging.getLogger(__name__)

# ══════════════════════════════════════════════════════════════════════════════
# CONSTANTES E HELPERS PARA IMPORTAÇÃO PROTHEUS
# ══════════════════════════════════════════════════════════════════════════════

SOLICITANTES_MRO = {
    "jasiva lopes",
    "luis gabriel arruda de oliveira",
    "sidinei correa alfon",
    "juan tarco pinheiro de araujo",
}

PALAVRAS_CRITICAS = ("parada", "critico", "critica", "urgente", "linha")


def _solicitantes_mro_norm(conn):
    """Conjunto de nomes normalizados no escopo MRO.

    v2.2.0: passa a ler da tabela `solicitantes_mro` (incluir_mro=1), tornando o
    filtro dinâmico. Faz fallback para a constante SOLICITANTES_MRO se a tabela
    ainda não existir ou estiver vazia (compatibilidade)."""
    try:
        rows = conn.execute("SELECT nome_norm FROM solicitantes_mro WHERE incluir_mro=1").fetchall()
        nomes = {r[0] for r in rows if r[0]}
        if nomes:
            return nomes
    except Exception:
        pass
    return set(SOLICITANTES_MRO)


def listar_solicitantes_mro(apenas_incluidos=True):
    """v5.1.0 (F2) — solicitantes para a gestão do escopo MRO em Configurações.
    `apenas_incluidos=True` → incluir_mro=1 (o escopo do sync); False → candidatos
    (incluir_mro=0, vindos da aba SCM USERS)."""
    alvo = 1 if apenas_incluidos else 0
    with transaction() as conn:
        rows = conn.execute(
            "SELECT id, nome, codigo, departamento FROM solicitantes_mro WHERE incluir_mro=? ORDER BY nome",
            (alvo,),
        ).fetchall()
    return [dict(r) for r in rows]


def marcar_solicitante_mro(nome, incluir=True):
    """v5.1.0 (F2) — inclui/remove um solicitante do escopo MRO (incluir_mro). Cria a linha
    se o nome for novo (não veio da aba SCM USERS). Retorna (ok, msg)."""
    nome = (nome or "").strip()
    if not nome:
        return False, "Nome vazio."
    norm = _normalizar_txt(nome)
    with transaction() as conn:
        conn.execute(
            """
            INSERT INTO solicitantes_mro (nome, nome_norm, incluir_mro) VALUES (?,?,?)
            ON CONFLICT(nome_norm) DO UPDATE SET incluir_mro=excluded.incluir_mro, nome=excluded.nome
        """,
            (nome, norm, 1 if incluir else 0),
        )
    return True, ("Solicitante incluído no escopo MRO." if incluir else "Solicitante removido do escopo MRO.")


def definir_codigo_solicitante_mro(solicitante_id, codigo):
    """v5.1.0 (F2) — override manual do código Protheus de um solicitante MRO."""
    codigo = (codigo or "").strip() or None
    with transaction() as conn:
        conn.execute("UPDATE solicitantes_mro SET codigo=? WHERE id=?", (codigo, solicitante_id))
    return True


def obter_cadastro_mro_para_cruzamento():
    """v4.6.0 — cadastro MRO para o Monitor de SC 2.0 (cruzamento SCM × SC7).

    Retorna ``(solicitantes_mro, pns_mro, dep_por_solic)`` numa única conexão:
    - ``solicitantes_mro``: nomes normalizados no escopo MRO (incluir_mro=1);
    - ``pns_mro``: conjunto de part numbers cadastrados no inventário;
    - ``dep_por_solic``: mapa ``nome_norm → departamento`` (mesma derivação do
      Dashboard SCM). Só LEITURA — o cruzamento em si não grava nada.
    """
    with transaction() as conn:
        solicitantes = _solicitantes_mro_norm(conn)
        pns = {r[0] for r in conn.execute("SELECT part_number FROM inventario") if r[0]}
        dep_por_solic = {}
        for r in conn.execute("SELECT nome, departamento FROM solicitantes_mro"):
            dep = (r["departamento"] or "").strip()
            if dep:
                dep_por_solic[_normalizar_txt(r["nome"])] = dep
    return solicitantes, pns, dep_por_solic


# ══════════════════════════════════════════════════════════════════════════════
# STATUS
# ══════════════════════════════════════════════════════════════════════════════


def calcular_status_inventario(estoque_atual, estoque_minimo, estoque_em_transito):
    """
    v2.2: Status baseado no estoque FÍSICO atual vs Mínimo.
    Regras:
    - Estoque <= Mínimo → 🔴 COMPRAR (Risco de ruptura imediato)
    - Mínimo < Estoque <= (Mínimo * 1.2) → 🟡 ATENÇÃO (Perto do limite)
    - Estoque > (Mínimo * 1.2) → 🟢 OK (Estoque confortável)

    Obs: Se estoque_minimo for 0 ou None, considera-se OK se tiver estoque > 0.
    """
    # ✅ CORREÇÃO: Tratar None como 0 para evitar TypeError
    if estoque_atual is None:
        estoque_atual = 0
    if estoque_minimo is None:
        estoque_minimo = 0

    # Proteção contra divisão por zero ou mínimo não definido
    if estoque_minimo <= 0:
        return "🟢 OK" if estoque_atual > 0 else "🔴 COMPRAR"

    # REGRA DE OURO: Se está no mínimo ou abaixo, é CRÍTICO
    if estoque_atual <= estoque_minimo:
        return "🔴 COMPRAR"

    # ZONA DE ATENÇÃO: Acima do mínimo, mas dentro de 20% de margem
    limite_atencao = estoque_minimo * MARGEM_ATENCAO
    if estoque_atual <= limite_atencao:
        return "🟡 ATENÇÃO"

    # ESTOQUE CONFORTÁVEL
    return "🟢 OK"


def calcular_cobertura(estoque_atual, consumo_diario):
    """Dias de cobertura = estoque atual / consumo diário.

    v2.2.1: torna explícito quantos dias o estoque dura no ritmo atual. Sem
    consumo, retorna a sentinela de "sem risco". v3.1.0: deixou de somar o
    Saldo Residual (Guarda-Chuva) — pedido do PO para refletir só o estoque
    físico disponível; o guarda-chuva segue considerado no gatilho de
    reposição (`_disponivel`/ROP em services/planejamento.py), que é uma
    decisão diferente (quando comprar) desta métrica (quantos dias de estoque)."""
    consumo = consumo_diario or 0
    if consumo <= 0:
        return PREVISAO_RUPTURA_SEM_RISCO
    return round((estoque_atual or 0) / consumo, 1)


def filtrar_itens_por_busca(itens, busca):
    """Filtra uma lista de itens (dicts no formato de `listar_inventario`) por
    substring no Part Number, nome ou descrição (case-insensitive). Usado pela
    busca de materiais em Controle de SC → Fornecedores & Cotação (v3.1.0)."""
    if not busca:
        return itens
    b = busca.lower()
    return [
        i
        for i in itens
        if b in (i.get("part_number") or "").lower()
        or b in (i.get("nome_item") or "").lower()
        or b in (i.get("descricao") or "").lower()
    ]


def calcular_status_sc(data_aprovacao, numero_po, fornecedor, tem_pendente):
    if not tem_pendente:
        return "SC Concluída"
    if numero_po and fornecedor:
        return "Aguardando Entrega"
    if numero_po and not fornecedor:
        return "Verificar Fornecedor"
    if data_aprovacao and not numero_po:
        return "Cotação"
    return "Aprovação Gestor"


# ══════════════════════════════════════════════════════════════════════════════
# LISTAS CONFIGURÁVEIS
# ══════════════════════════════════════════════════════════════════════════════


def listar_valores(tipo):
    with transaction() as conn:
        rows = conn.execute(
            "SELECT valor FROM listas WHERE tipo=? AND ativo=1 ORDER BY valor", (tipo,)
        ).fetchall()
    return [r["valor"] for r in rows]


def adicionar_valor_lista(tipo, valor):
    try:
        with transaction() as conn:
            conn.execute("INSERT INTO listas (tipo,valor) VALUES (?,?)", (tipo, valor.strip().upper()))
        return True, f"'{valor.upper()}' adicionado."
    except sqlite3.IntegrityError:
        return False, f"'{valor}' já existe."
    except Exception as e:
        return False, str(e)


def remover_valor_lista(tipo, valor):
    try:
        with transaction() as conn:
            conn.execute("UPDATE listas SET ativo=0 WHERE tipo=? AND valor=?", (tipo, valor))
        return True, f"'{valor}' removido."
    except Exception as e:
        return False, str(e)


# ── v6.5.1 — Tipos de Material e Unidades administráveis ──────────────────────
# Os dois campos são TEXT livre no `inventario` (sem CHECK) e as opções vinham de
# constantes hardcoded. Passam a ser listas mestras editáveis em Configurações,
# reusando a tabela `listas` — sem schema novo. Diferença para as outras 5 listas:
# aqui o CASO importa ("Spare Parts" não pode virar "SPARE PARTS"), por isso a
# adição usa `adicionar_valor_lista_txt` e não `adicionar_valor_lista`.
# tipo da lista -> (coluna do inventario, fallback de constants.py)
_LISTAS_INVENTARIO = {
    "tipo_material": ("tipo_material", TIPOS),
    "unidade": ("unidade", UNIDADES),
}


def _semear_lista_inventario(conn, tipo):
    """Semeia UMA vez a lista com o que já está em uso no `inventario`.

    Só roda quando não existe NENHUMA linha do tipo (contando as `ativo=0`): assim é
    idempotente e nunca ressuscita um valor que o admin removeu de propósito. Insere
    preservando o caso — passar por `adicionar_valor_lista` (que faz `.upper()`)
    destruiria "Spare Parts". Banco sem inventário (instalação nova) cai nas
    constantes, para a lista não nascer vazia.
    """
    coluna, fallback = _LISTAS_INVENTARIO[tipo]
    ja_tem = conn.execute("SELECT COUNT(*) AS n FROM listas WHERE tipo=?", (tipo,)).fetchone()["n"]
    if ja_tem:
        return
    rows = conn.execute(
        f"SELECT DISTINCT TRIM({coluna}) AS v FROM inventario "  # noqa: S608 - coluna vem do mapa acima
        f"WHERE {coluna} IS NOT NULL AND TRIM({coluna}) <> ''"
    ).fetchall()
    valores = [r["v"] for r in rows] or list(fallback)
    conn.executemany(
        "INSERT OR IGNORE INTO listas (tipo,valor) VALUES (?,?)",
        [(tipo, v) for v in valores],
    )


def listar_valores_material(tipo, fallback=True):
    """Lista administrável de `tipo_material` / `unidade` (semeia na 1ª leitura).

    `fallback=True` (cadastro de itens) devolve as constantes quando a lista ativa
    está vazia — o selectbox nunca pode nascer sem opção. `fallback=False`
    (Configurações) mostra a verdade da lista, inclusive vazia.
    """
    if tipo not in _LISTAS_INVENTARIO:
        raise ValueError(f"Lista '{tipo}' não é lista de material.")
    with transaction() as conn:
        _semear_lista_inventario(conn, tipo)
        rows = conn.execute(
            "SELECT valor FROM listas WHERE tipo=? AND ativo=1 ORDER BY valor", (tipo,)
        ).fetchall()
    valores = [r["valor"] for r in rows]
    if not valores and fallback:
        return list(_LISTAS_INVENTARIO[tipo][1])
    return valores


def adicionar_valor_lista_txt(tipo, valor):
    """Adiciona à lista PRESERVANDO o caso digitado (ver `_LISTAS_INVENTARIO`).

    Reativa em vez de inserir quando o valor já existe: `remover_valor_lista` é
    soft-delete (`ativo=0`) contra um `UNIQUE(tipo,valor)`, então re-adicionar o
    mesmo valor por `INSERT` bateria em `IntegrityError` (armadilha documentada em
    `database.criar_banco`). A busca é case-insensitive para não conviverem "UN" e
    "Un" como opções distintas.
    """
    v = (valor or "").strip()
    if not v:
        return False, "O valor não pode estar vazio."
    try:
        with transaction() as conn:
            row = conn.execute(
                "SELECT id, valor, ativo FROM listas WHERE tipo=? AND UPPER(valor)=UPPER(?)",
                (tipo, v),
            ).fetchone()
            if row is None:
                conn.execute("INSERT INTO listas (tipo,valor) VALUES (?,?)", (tipo, v))
                return True, f"'{v}' adicionado."
            if row["ativo"]:
                return False, f"'{row['valor']}' já existe."
            conn.execute("UPDATE listas SET ativo=1 WHERE id=?", (row["id"],))
            return True, f"'{row['valor']}' reativado."
    except Exception as e:
        return False, str(e)


def contar_itens_com_valor(tipo, valor):
    """Quantos itens do inventário ainda usam este tipo/unidade (guarda de remoção).

    Remover é soft-delete e não quebra item nenhum — o texto continua gravado no
    `inventario`; a contagem existe só para o admin saber o que está tirando do menu.
    """
    if tipo not in _LISTAS_INVENTARIO:
        raise ValueError(f"Lista '{tipo}' não é lista de material.")
    coluna = _LISTAS_INVENTARIO[tipo][0]
    with transaction() as conn:
        row = conn.execute(
            f"SELECT COUNT(*) AS n FROM inventario "  # noqa: S608 - coluna vem do mapa acima
            f"WHERE UPPER(TRIM({coluna})) = UPPER(TRIM(?))",
            ((valor or "").strip(),),
        ).fetchone()
    return int(row["n"] or 0)


def _setores_do_historico(conn):
    """Setores distintos já usados no histórico (movimentações + requisições),
    sem nulos/vazios. Ambas as tabelas têm a coluna `setor` (ver criar_requisicao)."""
    rows = conn.execute(
        "SELECT DISTINCT setor FROM ("
        "  SELECT setor FROM movimentacoes"
        "  UNION SELECT setor FROM requisicoes"
        ") WHERE setor IS NOT NULL AND TRIM(setor) <> ''"
    ).fetchall()
    return [str(r["setor"]).strip() for r in rows if str(r["setor"]).strip()]


def listar_setores_conhecidos():
    """Setores para o select da Requisição: união (case-insensitive) dos setores
    cadastrados em Configurações com os já usados no histórico de movimentações e
    requisições. Padroniza a escolha sem esconder os setores reais que nunca foram
    formalmente cadastrados. Retorna lista ordenada, sem duplicatas nem vazios."""
    vistos = {}  # chave normalizada (UPPER) -> forma exibida (primeira vista vence)

    def _add(v):
        v = str(v).strip() if v is not None else ""
        if v:
            vistos.setdefault(v.upper(), v)

    for v in listar_valores("setor"):  # Configurações primeiro (forma cadastrada vence)
        _add(v)
    with transaction() as conn:
        for v in _setores_do_historico(conn):
            _add(v)
    return sorted(vistos.values(), key=lambda s: s.upper())


def sincronizar_setores_config():
    """Registra em Configurações (lista 'setor') os setores que já aparecem no
    histórico mas ainda não foram cadastrados. Idempotente — `adicionar_valor_lista`
    faz UPPER + dedupe. Retorna a lista dos setores efetivamente adicionados."""
    cadastrados = {s.upper() for s in listar_valores("setor")}
    with transaction() as conn:
        historico = _setores_do_historico(conn)
    adicionados = []
    for s in historico:
        if s.upper() not in cadastrados:
            ok, _ = adicionar_valor_lista("setor", s)
            if ok:
                adicionados.append(s.upper())
                cadastrados.add(s.upper())
    return adicionados


# ══════════════════════════════════════════════════════════════════════════════
# INVENTÁRIO
# ══════════════════════════════════════════════════════════════════════════════


def listar_inventario():
    with transaction() as conn:
        rows = conn.execute(
            """
        SELECT i.*,
        sc.numero_sc      AS sc_numero,
        sc.numero_po      AS sc_po,
        sc.fornecedor     AS sc_fornecedor,
        sc.data_aprovacao AS sc_aprovacao,
        sc.status         AS sc_status_raw,
        COALESCE((
            SELECT SUM(COALESCE(isc.saldo_residual, 0))
            FROM itens_sc isc
            JOIN solicitacoes_compra s2 ON s2.id = isc.sc_id
            WHERE isc.item_id = i.id
            AND s2.status NOT IN ('Recebido','Cancelado')
        ), 0) AS estoque_em_transito,
        (SELECT COUNT(*) FROM movimentacoes m
            WHERE m.item_id = i.id AND """
            + SAIDA_REAL_WHERE
            + """) AS qtd_requisicoes,
        (SELECT MAX(m.data_hora) FROM movimentacoes m
            WHERE m.item_id = i.id AND """
            + SAIDA_REAL_WHERE
            + """) AS ultima_requisicao_data
        FROM inventario i
        LEFT JOIN solicitacoes_compra sc ON sc.id = i.ultima_sc_id
        ORDER BY
        CASE i.importancia
            WHEN 'Parada de Linha' THEN 1
            WHEN 'Importante'      THEN 2
            WHEN 'Admin'           THEN 3 ELSE 4 END,
        i.part_number
        """
        ).fetchall()

    # v2.9.0 (forward-only): UM de compra DOMINANTE por item (a que o fornecedor mais
    # cobra), para o sinal de "revisar unidade". Uma varredura só (vs. subconsulta por
    # item) e consistente com a sugestão de conversão (mesma função de mapeamento).
    mapa_uc = mapear_unidade_compra_por_item()

    # v2.10.0 (diagnóstico): padrão de demanda (SBC) e classe XYZ por item, DERIVADOS
    # na leitura (sem coluna nova) numa única varredura de movimentacoes (evita N+1).
    # Import local para manter db_functions como camada baixa (classificacao depende
    # de constants/database, não de db_functions).
    from services.classificacao import classificar_todos

    mapa_cls = classificar_todos()

    resultado = []
    for r in rows:
        item = dict(r)

        # 1. Status do Material (Baseado em Estoque Físico vs Mínimo)
        item["status_estoque_fisico"] = calcular_status_inventario(
            item.get("estoque_atual", 0) or 0,
            item.get("estoque_minimo", 0) or 0,
            item.get("estoque_em_transito", 0) or 0,
        )

        # v2.7.0: "Sem Movimentação" — item que NUNCA teve consumo real (nenhuma
        # saída por requisição) sai da lista de compra e ganha status próprio,
        # sobrepondo 🔴/🟡/🟢. O status físico fica preservado em
        # `status_estoque_fisico` (revisão/Ficha). Decisão do PO: vale para TODO
        # item sem consumo, inclusive "Parada de Linha" (segue visível no
        # Assistente de Reposição via toggle). NÃO altera a base do Neidson.
        item["qtd_requisicoes"] = int(item.get("qtd_requisicoes") or 0)
        item["sem_movimentacao"] = item["qtd_requisicoes"] == 0
        item["status_material"] = (
            STATUS_SEM_MOVIMENTACAO if item["sem_movimentacao"] else item["status_estoque_fisico"]
        )

        # v2.2.1: dias de cobertura explícito. v3.1.0: estoque atual / consumo (sem
        # somar o guarda-chuva — pedido do PO; ver docstring de calcular_cobertura).
        item["dias_cobertura"] = calcular_cobertura(
            item.get("estoque_atual", 0) or 0,
            item.get("consumo_medio_diario", 0) or 0,
        )

        # v2.9.0 (forward-only): item cuja UM de compra DOMINANTE difere da de estoque
        # e que AINDA NÃO FOI CURADO (fator=1 → recebimento soma cru, risco de ledger
        # corrompido). Sinaliza "⚠️ revisar unidade" na Ficha/Inventário, linkando à
        # curadoria. Não reescreve nada; some assim que o gestor define o fator (≠1).
        _fator = item.get("fator_conversao")
        _nao_curado = _fator is None or abs((_fator or 1) - 1) < 1e-9
        _uc_dom = mapa_uc.get(item["id"])
        _um_diverge = bool(_uc_dom) and _uc_dom.upper() != (item.get("unidade") or "").upper()
        item["unidade_divergente"] = _um_diverge and _nao_curado

        # v2.10.0 (diagnóstico): padrão de demanda (SBC) e classe XYZ derivados. Itens
        # sem saída real não aparecem no mapa → ficam None ("sem dados"). Só apoio à
        # decisão (não altera status/reposição); rótulo de confiança acompanha na Ficha.
        _cls = mapa_cls.get(item["id"]) or {}
        item["padrao_demanda"] = _cls.get("padrao_demanda")
        item["classe_xyz"] = _cls.get("classe_xyz")

        # 2. Status da SC (Lógica Refinada v2.3)
        sc_num = item.get("sc_numero")
        sc_status_raw = item.get("sc_status_raw")
        saldo_transito = item.get("estoque_em_transito", 0)

        if not sc_num:
            item["status_sc"] = "Sem SC"
        elif sc_status_raw in ["Recebido", "Cancelado"]:
            item["status_sc"] = "SC Concluída"
        elif saldo_transito > 0:
            item["status_sc"] = calcular_status_sc(
                item["sc_aprovacao"], item["sc_po"], item["sc_fornecedor"], True
            )
        else:
            if sc_status_raw:
                item["status_sc"] = f"{sc_status_raw}"
            else:
                item["status_sc"] = "SC Concluída"

        # Compatibilidade com código legado
        item["status_display"] = item["status_material"]
        # Máximo: usa o valor apurado (ex.: base do Neidson) quando > 0;
        # senão mantém o fallback histórico (mínimo * fator).
        maximo_armazenado = item.get("estoque_maximo") or 0
        item["estoque_maximo"] = (
            maximo_armazenado
            if maximo_armazenado > 0
            else (item.get("estoque_minimo") or 0) * FATOR_ESTOQUE_MAXIMO
        )
        resultado.append(item)

    return resultado


def buscar_item_por_id(item_id):
    with transaction() as conn:
        r = conn.execute("SELECT * FROM inventario WHERE id=?", (item_id,)).fetchone()
    return dict(r) if r else None


def _mov_inline(
    conn,
    item_id,
    tipo,
    quantidade,
    saldo_apos,
    observacao,
    agora,
    centro_custo=CC_EDICAO,
    responsavel="Sistema",
):
    """Insere uma movimentação usando a conexão/transação CORRENTE (sem abrir
    outra). v2.2.0: mantém o ledger contínuo (saldo_apos) quando o saldo muda
    fora de registrar_movimentacao — ex.: saldo inicial no cadastro. Evita as
    'quebras' de continuidade observadas no histórico."""
    conn.execute(
        """
        INSERT INTO movimentacoes
            (item_id,tipo,quantidade,saldo_apos,data_hora,
             centro_custo,setor,solicitante,emitente,observacao)
        VALUES (?,?,?,?,?,?,?,?,?,?)
    """,
        (
            item_id,
            tipo,
            quantidade,
            saldo_apos,
            agora,
            centro_custo,
            "",
            responsavel,
            responsavel,
            observacao,
        ),
    )


def salvar_item(
    part_number,
    nome_item,
    descricao,
    unidade,
    importancia,
    tipo_material,
    setor,
    local,
    caixa,
    estoque_atual,
    estoque_minimo,
    lead_time,
    item_id=None,
    unidade_compra=None,
    fator_conversao=None,
):
    """Cria/edita um item. v2.9.0: aceita `unidade_compra` e `fator_conversao`
    (curadoria da conversão) como kwargs — `item_id` permanece o 13º posicional
    (compat). Na edição, usa COALESCE — só grava o que o gestor confirmar (None
    preserva o valor atual); nunca sobrescreve automaticamente."""
    agora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        estoque_atual = float(estoque_atual or 0)
        with transaction() as conn:
            if item_id:
                antigo = conn.execute(
                    "SELECT estoque_atual FROM inventario WHERE id=?", (item_id,)
                ).fetchone()
                estoque_antigo = float(antigo["estoque_atual"] or 0) if antigo else 0.0
                conn.execute(
                    """
                    UPDATE inventario SET
                        part_number=?,nome_item=?,descricao=?,unidade=?,
                        importancia=?,tipo_material=?,setor_responsavel=?,
                        local_armazenagem=?,caixa_identificacao=?,
                        estoque_atual=?,estoque_minimo=?,lead_time_dias=?,
                        unidade_compra=COALESCE(?, unidade_compra),
                        fator_conversao=COALESCE(?, fator_conversao),
                        data_atualizacao=?
                    WHERE id=?
                """,
                    (
                        part_number,
                        nome_item,
                        descricao,
                        unidade,
                        importancia,
                        tipo_material,
                        setor,
                        local,
                        caixa,
                        estoque_atual,
                        estoque_minimo,
                        lead_time,
                        unidade_compra,
                        fator_conversao,
                        agora,
                        item_id,
                    ),
                )
                # Integridade do ledger: se o saldo mudou pela edição, registra o
                # delta como movimentação (evita alterar o saldo de forma "silenciosa").
                delta = estoque_atual - estoque_antigo
                if abs(delta) > 1e-9:
                    _mov_inline(
                        conn,
                        item_id,
                        "entrada" if delta > 0 else "saida",
                        abs(delta),
                        estoque_atual,
                        "Ajuste via edição de item",
                        agora,
                    )
            else:
                cur = conn.execute(
                    """
                    INSERT INTO inventario
                        (part_number,nome_item,descricao,unidade,importancia,
                         tipo_material,setor_responsavel,local_armazenagem,
                         caixa_identificacao,estoque_atual,estoque_minimo,lead_time_dias,
                         unidade_compra,fator_conversao)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                    (
                        part_number,
                        nome_item,
                        descricao,
                        unidade,
                        importancia,
                        tipo_material,
                        setor,
                        local,
                        caixa,
                        estoque_atual,
                        estoque_minimo,
                        lead_time,
                        unidade_compra,
                        fator_conversao if fator_conversao is not None else FATOR_CONVERSAO_PADRAO,
                    ),
                )
                novo_id = cur.lastrowid
                # Saldo inicial vira "entrada" → origem do ledger para snapshots/giro.
                if estoque_atual > 0:
                    _mov_inline(
                        conn,
                        novo_id,
                        "entrada",
                        estoque_atual,
                        estoque_atual,
                        "Saldo inicial (cadastro)",
                        agora,
                    )
            _recalcular_ruptura_by_pn(conn, part_number)
        return True, "Item salvo com sucesso."
    except sqlite3.IntegrityError:
        return False, f"Part Number '{part_number}' já existe."
    except Exception as e:
        return False, str(e)


def desmarcar_inventariado(item_id):
    agora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        with transaction() as conn:
            conn.execute(
                "UPDATE inventario SET data_inventario=NULL,data_atualizacao=? WHERE id=?", (agora, item_id)
            )
        return True, "Inventário removido."
    except Exception as e:
        return False, str(e)


def _recalcular_ruptura_by_pn(conn, part_number):
    # conn=None -> transaction() abre, comita e fecha; conn externo -> yield puro.
    with transaction(conn) as c:
        r = c.execute(
            "SELECT id,estoque_atual,consumo_medio_diario,lead_time_dias FROM inventario WHERE part_number=?",
            (part_number,),
        ).fetchone()
        if not r:
            return
        consumo = r["consumo_medio_diario"] or 0
        ruptura = (r["estoque_atual"] / consumo) if consumo > 0 else PREVISAO_RUPTURA_SEM_RISCO
        # v3.7.0: o Estoque de Segurança foi desativado (o buffer virou o próprio Mínimo
        # do Neidson). Não recalculamos mais `estoque_seguranca_calculado` — só a
        # previsão de ruptura (usada pelo Monitor de SC). As colunas de segurança
        # permanecem no schema (não-destrutivo), mas ficam órfãs.
        c.execute(
            """
            UPDATE inventario SET previsao_ruptura_dias=?,data_atualizacao=? WHERE id=?
        """,
            (ruptura, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), r["id"]),
        )


def _recalcular_ruptura_by_id(conn, item_id):
    with transaction(conn) as c:
        r = c.execute("SELECT part_number FROM inventario WHERE id=?", (item_id,)).fetchone()
        if r:
            _recalcular_ruptura_by_pn(c, r["part_number"])


def setor_dominante_por_item(item_ids=None, conn=None):
    """{item_id: setor dominante} derivado do CONSUMO REAL (saídas por requisição).

    v3.7.0 — Para cada item, o setor mais frequente entre suas saídas reais
    (`SAIDA_REAL_WHERE`), ignorando setores vazios. Itens sem consumo real não entram
    no mapa (o chamador aplica o fallback, ex.: '—'). UMA única query — evita N
    consultas por render. Substitui o `inventario.setor_responsavel` (98% 'Improdutivo',
    inútil) como base do "Setor" no Dashboard de Comprador (Setores em aberto) e no
    Assistente de Reposição (coluna/filtro Setor).

    v5.9.0 — o setor é normalizado com `UPPER(TRIM(...))`. O mesmo setor chega grafado
    de formas diferentes ('ADAPTADOR' e 'ADAPTADOR ', 'TI' e 'ti', 'Almoxarifado' e
    'ALMOXARIFADO'): 68 valores distintos que são 59 setores reais. Sem isso o mesmo
    setor aparecia duas vezes nos rankings, cada uma com parte do total."""
    with transaction(conn) as c:
        rows = c.execute(f"""
            SELECT item_id, UPPER(TRIM(setor)) AS setor, COUNT(*) AS n
            FROM movimentacoes
            WHERE {SAIDA_REAL_WHERE}
              AND setor IS NOT NULL AND TRIM(setor) <> ''
            GROUP BY item_id, UPPER(TRIM(setor))
        """).fetchall()
    filtro = set(item_ids) if item_ids is not None else None
    por_item = {}
    for r in rows:
        if filtro is not None and r["item_id"] not in filtro:
            continue
        por_item.setdefault(r["item_id"], Counter())[r["setor"]] += r["n"]
    return {iid: cont.most_common(1)[0][0] for iid, cont in por_item.items()}


# ══════════════════════════════════════════════════════════════════════════════
# MONITOR DE SC (v3.9.0) — grade editável e persistente (substitui a planilha FUP)
# ══════════════════════════════════════════════════════════════════════════════

# Colunas MANUAIS (o almox edita e persistem) × TÉCNICAS (o sistema recalcula no sync).
# v3.11.0: STATUS PO passou a ser TÉCNICA — derivada do status da SC/PO (aba SCM) no sync.
MONITOR_COLS_MANUAIS = ("fornecedor", "comentario", "responsavel")
MONITOR_COLS_TECNICAS = (
    "numero_sc",
    "part_number",
    "nome_item",
    "status_calc",
    "unidade",
    "tam_po",
    "saldo_po",
    "esgotado_em",
    "faltando_dias",
    "po",
    "status_po",
)

# Nº máximo de linhas exibidas no Monitor (v3.11.0): o comprador vê só as ~15 mais urgentes
# do dia; o almox (Juan) mantém a grade enxuta. Linhas manuais têm prioridade de exibição.
MONITOR_MAX_LINHAS = 15


def _monitor_status(estoque, minimo):
    """STATUS (criticidade) derivado do estoque físico vs mínimo, p/ o Monitor de SC.
    Estoque 0 → ESTOQUE Ø; ≤ mínimo → CRÍTICO; senão vazio (decisão do plano/D1)."""
    e = float(estoque or 0)
    m = float(minimo or 0)
    if e <= 0:
        return "🔴 ESTOQUE Ø"
    if m > 0 and e <= m:
        return "🟡 CRÍTICO"
    return ""


def sincronizar_monitor_sc(conn=None, hoje=None, force=False):
    """Sync diário do Monitor de SC (v3.9.0 / C2). HÍBRIDO:
      1. Reseta 'Revisado' das linhas cujo revisado_data < hoje (o checkbox reseta todo dia).
      2. Recalcula/upserta as colunas TÉCNICAS de cada item PENDENTE de SC aberta, por
         linha_id estável ('sys:<itens_sc.id>') — PRESERVA as colunas manuais e o tombstone
         'removido'. Linhas de sistema que saíram do pendente ficam inativas (ativo=0), sem
         perder anotações; itens novos viram linha nova.
    Idempotente e gated por dia (tabela monitor_sc_sync) — pode rodar a cada abertura do
    app. `force=True` ignora o gate (ex.: logo após um import). Retorna nº de linhas de
    sistema ativas."""
    hoje = hoje or date.today()
    hoje_iso = hoje.strftime("%Y-%m-%d")
    agora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with transaction(conn) as c:
        if not force:
            r = c.execute("SELECT ultima_sync FROM monitor_sc_sync WHERE id=1").fetchone()
            if r and r["ultima_sync"] == hoje_iso:
                return -1  # já sincronizado hoje

        # 1) Reset diário do "Revisado pelo Almox".
        c.execute(
            "UPDATE monitor_sc SET revisado=0 "
            "WHERE revisado=1 AND (revisado_data IS NULL OR revisado_data < ?)",
            (hoje_iso,),
        )

        # 2) Desativa todas as linhas de sistema; as pendentes serão reativadas no upsert.
        c.execute("UPDATE monitor_sc SET ativo=0 WHERE origem='sistema'")

        rows = c.execute("""
            SELECT isc.id AS item_sc_id, sc.numero_sc, sc.status AS status_sc,
                   isc.numero_po AS po_item, sc.numero_po AS po_sc,
                   inv.part_number, inv.nome_item, inv.unidade,
                   inv.estoque_atual, inv.estoque_minimo, inv.previsao_ruptura_dias,
                   isc.quantidade_solicitada AS tam_po,
                   COALESCE(isc.saldo_residual,
                            isc.quantidade_solicitada - isc.quantidade_recebida) AS saldo_po
            FROM itens_sc isc
            JOIN solicitacoes_compra sc ON sc.id = isc.sc_id
            JOIN inventario inv ON inv.id = isc.item_id
            WHERE sc.status NOT IN ('Recebido', 'Cancelado')
              AND COALESCE(isc.saldo_residual,
                           isc.quantidade_solicitada - isc.quantidade_recebida) > 0
        """).fetchall()
        ativos = 0
        for r in rows:
            linha_id = f"sys:{r['item_sc_id']}"
            status_calc = _monitor_status(r["estoque_atual"], r["estoque_minimo"])
            rupt = r["previsao_ruptura_dias"]
            esgotado_em, faltando = None, None
            if rupt is not None and rupt < PREVISAO_RUPTURA_SEM_RISCO:
                faltando = round(float(rupt), 1)
                esgotado_em = (hoje + timedelta(days=int(rupt))).strftime("%Y-%m-%d")
            po = r["po_item"] or r["po_sc"] or ""
            # v3.11.0: STATUS PO derivado automaticamente do status da SC/PO (aba SCM),
            # chaveado pela linha da SC — substitui a digitação manual do almox.
            status_po = (r["status_sc"] or "").strip()
            c.execute(
                """
                INSERT INTO monitor_sc
                    (linha_id, numero_sc, part_number, nome_item, status_calc, unidade,
                     tam_po, saldo_po, esgotado_em, faltando_dias, po, status_po,
                     origem, ativo, data_atualizacao)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?, 'sistema', 1, ?)
                ON CONFLICT(linha_id) DO UPDATE SET
                    numero_sc=excluded.numero_sc, part_number=excluded.part_number,
                    nome_item=excluded.nome_item, status_calc=excluded.status_calc,
                    unidade=excluded.unidade, tam_po=excluded.tam_po, saldo_po=excluded.saldo_po,
                    esgotado_em=excluded.esgotado_em, faltando_dias=excluded.faltando_dias,
                    po=excluded.po, status_po=excluded.status_po,
                    ativo=1, data_atualizacao=excluded.data_atualizacao
            """,
                (
                    linha_id,
                    r["numero_sc"],
                    r["part_number"],
                    r["nome_item"],
                    status_calc,
                    r["unidade"],
                    r["tam_po"],
                    r["saldo_po"],
                    esgotado_em,
                    faltando,
                    po,
                    status_po,
                    agora,
                ),
            )
            ativos += 1

        c.execute(
            "INSERT INTO monitor_sc_sync (id, ultima_sync) VALUES (1, ?) "
            "ON CONFLICT(id) DO UPDATE SET ultima_sync=excluded.ultima_sync",
            (hoje_iso,),
        )
    return ativos


def listar_monitor_sc(conn=None):
    """Linhas VISÍVEIS do Monitor: itens de sistema ainda pendentes (ativo=1) + linhas
    manuais, exceto tombstones (removido=1). Mais urgente primeiro (menor 'faltando').
    v3.11.0: limitado às MONITOR_MAX_LINHAS mais urgentes — o comprador vê só a fila do dia.
    As linhas manuais (do almox) têm prioridade e sempre entram dentro do limite."""
    with transaction(conn) as c:
        rows = c.execute("""
            SELECT * FROM monitor_sc
            WHERE removido=0 AND (origem='manual' OR ativo=1)
            ORDER BY (faltando_dias IS NULL), faltando_dias ASC, numero_sc
        """).fetchall()
    rows = [dict(r) for r in rows]
    if len(rows) <= MONITOR_MAX_LINHAS:
        return rows
    manuais = [r for r in rows if r.get("origem") == "manual"]
    sistema = [r for r in rows if r.get("origem") != "manual"]
    n_sis = max(0, MONITOR_MAX_LINHAS - len(manuais))
    return (sistema[:n_sis] + manuais)[:MONITOR_MAX_LINHAS]


def salvar_monitor_sc(registros, linha_ids_originais, conn=None, hoje=None):
    """Persiste as edições do grid do Monitor (C3). `registros` = lista de dicts (colunas
    do banco + 'linha_id' possivelmente vazio para linhas novas). Faz UPDATE das linhas
    existentes (técnicas + manuais + revisado), INSERT das novas (origem='manual') e, para
    as que sumiram do grid, tombstone (sistema → removido=1) ou DELETE (manual). Retorna
    (atualizadas, inseridas, removidas)."""
    import uuid as _uuid

    hoje_iso = (hoje or date.today()).strftime("%Y-%m-%d")
    agora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    editaveis = list(MONITOR_COLS_TECNICAS) + list(MONITOR_COLS_MANUAIS)
    orig = set(linha_ids_originais or [])
    vistos, upd, ins = set(), 0, 0
    with transaction(conn) as c:
        for reg in registros:
            lid = reg.get("linha_id")
            lid = None if (lid is None or str(lid).strip() == "" or str(lid).lower() == "nan") else str(lid)
            dados = {col: reg.get(col) for col in editaveis}
            rev = 1 if reg.get("revisado") in (True, 1, "1", "true", "True") else 0
            dados["revisado"] = rev
            dados["revisado_data"] = hoje_iso if rev else None
            if lid and lid in orig:
                vistos.add(lid)
                sets = ", ".join(f"{k}=?" for k in dados)
                c.execute(
                    f"UPDATE monitor_sc SET {sets}, data_atualizacao=? WHERE linha_id=?",
                    (*dados.values(), agora, lid),
                )
                upd += 1
            else:
                new_lid = f"man:{_uuid.uuid4().hex[:12]}"
                cols = list(dados.keys()) + ["linha_id", "origem", "ativo", "removido", "data_atualizacao"]
                vals = list(dados.values()) + [new_lid, "manual", 1, 0, agora]
                c.execute(
                    f"INSERT INTO monitor_sc ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})", vals
                )
                ins += 1
        rem = 0
        for lid in orig - vistos:
            r = c.execute("SELECT origem FROM monitor_sc WHERE linha_id=?", (lid,)).fetchone()
            if not r:
                continue
            if r["origem"] == "sistema":
                c.execute(
                    "UPDATE monitor_sc SET removido=1, data_atualizacao=? WHERE linha_id=?", (agora, lid)
                )
            else:
                c.execute("DELETE FROM monitor_sc WHERE linha_id=?", (lid,))
            rem += 1
    return upd, ins, rem


# v4.4.0 — grade LIVRE do Monitor (planilha colável). v4.6.0 — passa a guardar
# também as COLUNAS customizadas (criar/remover coluna), num shape retrocompatível
# {"colunas": [...], "linhas": [...]}; documento único (id=1) em JSON.
PLANILHA_LIVRE_COLS_PADRAO = list("ABCDEFGHIJ")


def _colunas_das_linhas(linhas):
    """Deriva a lista de colunas (preservando ordem de 1ª aparição) das linhas;
    cai no padrão A..J se as linhas não tiverem chaves."""
    cols = []
    for linha in linhas or []:
        for k in linha.keys() if isinstance(linha, dict) else []:
            if k not in cols:
                cols.append(k)
    return cols or list(PLANILHA_LIVRE_COLS_PADRAO)


def carregar_planilha_livre():
    """v4.6.0 — grade LIVRE do Monitor com colunas customizadas. Retorna sempre
    ``{"colunas": [...], "linhas": [...]}``. Normaliza o legado (lista de dicts,
    v4.4.0) para o shape novo, sem perder dados."""
    with transaction() as conn:
        r = conn.execute("SELECT dados_json FROM monitor_livre WHERE id=1").fetchone()
    if not r or not r["dados_json"]:
        return {"colunas": list(PLANILHA_LIVRE_COLS_PADRAO), "linhas": []}
    try:
        dados = json.loads(r["dados_json"])
    except Exception:
        return {"colunas": list(PLANILHA_LIVRE_COLS_PADRAO), "linhas": []}
    if isinstance(dados, dict):  # shape v4.6.0
        linhas = dados.get("linhas") if isinstance(dados.get("linhas"), list) else []
        colunas = dados.get("colunas") if isinstance(dados.get("colunas"), list) else None
        return {"colunas": colunas or _colunas_das_linhas(linhas), "linhas": linhas}
    if isinstance(dados, list):  # legado v4.4.0
        return {"colunas": _colunas_das_linhas(dados), "linhas": dados}
    return {"colunas": list(PLANILHA_LIVRE_COLS_PADRAO), "linhas": []}


def salvar_planilha_livre(colunas, linhas):
    """v4.6.0 — persiste a grade LIVRE (colunas + linhas) como JSON em linha única
    (id=1). Independente do grid técnico e do sync. Retorna nº de linhas salvas."""
    colunas = list(colunas or []) or _colunas_das_linhas(linhas)
    dados = json.dumps({"colunas": colunas, "linhas": list(linhas or [])}, ensure_ascii=False)
    agora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with transaction() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO monitor_livre (id, dados_json, data_atualizacao) VALUES (1, ?, ?)",
            (dados, agora),
        )
    return len(linhas or [])


def carregar_monitor_livre():
    """v4.4.0 (compat) — retorna só as LINHAS da grade livre (lista de dicts).
    Delega ao shape novo (v4.6.0). Mantido p/ retrocompatibilidade."""
    return carregar_planilha_livre()["linhas"]


def salvar_monitor_livre(registros):
    """v4.4.0 (compat) — persiste só as LINHAS (deriva as colunas das chaves).
    Delega a `salvar_planilha_livre`. Retorna nº de linhas salvas."""
    return salvar_planilha_livre(_colunas_das_linhas(registros), registros)


# ══════════════════════════════════════════════════════════════════════════════
# MOVIMENTAÇÕES
# ══════════════════════════════════════════════════════════════════════════════


def registrar_movimentacao(
    item_id,
    tipo,
    quantidade,
    centro_custo,
    solicitante,
    emitente,
    setor="",
    observacao="",
    sc_item_id=None,
    requisicao_id=None,
    data_hora=None,
    motivo=None,
):
    try:
        with transaction() as conn:
            r = conn.execute(
                "SELECT estoque_atual,part_number FROM inventario WHERE id=?", (item_id,)
            ).fetchone()
            if not r:
                return False, "Item não encontrado."

            estoque = r["estoque_atual"]
            if tipo == "saida" and quantidade > 0 and quantidade > estoque:
                return False, f"Estoque insuficiente. Disponível: {estoque}"

            if quantidade == 0:
                novo_saldo = estoque
            else:
                novo_saldo = (
                    estoque + quantidade if tipo in ("entrada", "devolucao") else estoque - quantidade
                )

            agora = data_hora or datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            conn.execute(
                """
                INSERT INTO movimentacoes
                    (item_id,tipo,quantidade,saldo_apos,data_hora,
                     centro_custo,setor,solicitante,emitente,observacao,sc_item_id,requisicao_id,motivo)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
                (
                    item_id,
                    tipo,
                    quantidade,
                    novo_saldo,
                    agora,
                    centro_custo,
                    setor,
                    solicitante,
                    emitente,
                    observacao,
                    sc_item_id,
                    requisicao_id,
                    motivo,
                ),
            )

            if quantidade != 0:
                conn.execute(
                    "UPDATE inventario SET estoque_atual=?,data_atualizacao=? WHERE id=?",
                    (novo_saldo, agora, item_id),
                )
                if tipo in ("saida", "devolucao"):
                    _recalcular_consumo(conn, item_id)
                _recalcular_ruptura_by_id(conn, item_id)

        return True, f"Novo saldo: {novo_saldo}"
    except Exception as e:
        return False, str(e)


def _consumo_janela(c, item_id, ini_dias, fim_dias=0):
    """Consumo médio diário (saídas) na janela [now-ini_dias, now-fim_dias).
    fim_dias=0 → janela recente terminando hoje; fim_dias>0 → janela anterior."""
    r = c.execute(
        """SELECT COALESCE(SUM(quantidade),0) AS total FROM movimentacoes
           WHERE item_id=? AND tipo='saida'
             AND data_hora >= datetime('now', ?)
             AND data_hora <  datetime('now', ?)""",
        (item_id, f"-{ini_dias} days", f"-{fim_dias} days"),
    ).fetchone()
    dias = max(ini_dias - fim_dias, 1)
    return (r["total"] or 0) / dias


def _recalcular_consumo(conn, item_id):
    """Recalcula o consumo médio diário em várias janelas (30/60/90) e a tendência.

    v2.2.1: `consumo_medio_diario` continua sendo a janela primária (30d). Tendência
    compara o consumo dos últimos 30d com o dos 30d anteriores (dias 31–60)."""
    with transaction(conn) as c:
        janelas = {}
        for j in JANELAS_CONSUMO:
            janelas[j] = _consumo_janela(c, item_id, j)
        consumo_30 = janelas.get(30, _consumo_janela(c, item_id, JANELA_CONSUMO_DIAS))
        consumo_prev_30 = _consumo_janela(c, item_id, 60, 30)  # dias 31–60

        if consumo_prev_30 > 0:
            tendencia_pct = (consumo_30 - consumo_prev_30) / consumo_prev_30 * 100.0
        elif consumo_30 > 0:
            tendencia_pct = 100.0  # sem base anterior, mas passou a consumir
        else:
            tendencia_pct = 0.0

        if tendencia_pct > TENDENCIA_LIMIAR_PCT:
            tendencia_label = "Alta"
        elif tendencia_pct < -TENDENCIA_LIMIAR_PCT:
            tendencia_label = "Queda"
        else:
            tendencia_label = "Estável"

        c.execute(
            """UPDATE inventario SET
                 consumo_medio_diario=?, consumo_30d=?, consumo_60d=?, consumo_90d=?,
                 tendencia_pct=?, tendencia_label=?
               WHERE id=?""",
            (
                consumo_30,
                janelas.get(30, consumo_30),
                janelas.get(60, 0.0),
                janelas.get(90, 0.0),
                round(tendencia_pct, 1),
                tendencia_label,
                item_id,
            ),
        )
        # v6.4.0 — a sugestão de Mín/Máx é `consumo × lead time` e `consumo × 60 d`:
        # acabou de mudar a metade "consumo" da conta, então ela é recalculada aqui, na
        # mesma transação. Sem isso a sugestão envelheceria em silêncio, e a tela
        # ofereceria "usar calculado" com um número de semanas atrás.
        recalcular_min_max_calculado(item_id, c)


def _data_limite_sql(data, fim_do_dia=False):
    """Normaliza `date`/`datetime`/str para o formato do ledger ('YYYY-MM-DD HH:MM:SS').

    `data_hora` é TEXT e a comparação é lexicográfica: sem o fim-do-dia explícito,
    `data_hora <= '2026-07-27'` deixaria de fora TODAS as movimentações do próprio 27,
    que gravam hora ('2026-07-27 14:08:23' > '2026-07-27'). Erro clássico e silencioso."""
    if not data:
        return None
    texto = data.strftime("%Y-%m-%d") if hasattr(data, "strftime") else str(data).strip()[:10]
    return f"{texto} 23:59:59" if fim_do_dia else f"{texto} 00:00:00"


def listar_movimentacoes(item_id=None, limit=200, data_inicio=None, data_fim=None):
    """Ledger cru (mais recente primeiro), com os vínculos já resolvidos.

    v5.7.0 (CP4) — ganhou recorte de período e `limit=None` (= SEM `LIMIT`). Os defaults
    preservam exatamente o comportamento das duas telas que já a usavam (Histórico e
    Ficha 360); quem precisa do histórico inteiro é o Relatório de Movimentações, que
    passa `limit=None` em vez do antigo teto de 5.000 — teto que cortava as movimentações
    mais ANTIGAS em silêncio (o `ORDER BY ... DESC` faz o corte pela cauda).

    Os `LEFT JOIN` trazem o que hoje só existe empacotado dentro da string `observacao`:
    nº da requisição e seu fluxo, NF, PO e nº da SC. São aditivos — quem já consumia a
    função continua lendo as mesmas chaves. O período é FECHADO nos dois extremos."""
    where, params = [], []
    if item_id:
        where.append("m.item_id=?")
        params.append(item_id)
    ini = _data_limite_sql(data_inicio)
    if ini:
        where.append("m.data_hora>=?")
        params.append(ini)
    fim = _data_limite_sql(data_fim, fim_do_dia=True)
    if fim:
        where.append("m.data_hora<=?")
        params.append(fim)

    sql = f"""
        SELECT m.*, i.part_number, i.nome_item,
               r.numero_requisicao, r.tipo_fluxo,
               isc.documento_nf, isc.numero_po,
               sc.numero_sc
        FROM movimentacoes m
        JOIN inventario i ON i.id=m.item_id
        LEFT JOIN requisicoes r ON r.id=m.requisicao_id
        LEFT JOIN itens_sc isc ON isc.id=m.sc_item_id
        LEFT JOIN solicitacoes_compra sc ON sc.id=isc.sc_id
        {"WHERE " + " AND ".join(where) if where else ""}
        ORDER BY m.data_hora DESC
    """
    if limit is not None:
        sql += " LIMIT ?"
        params.append(limit)

    with transaction() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [dict(r) for r in rows]


# v5.7.0 (CP4) — prefixos de Observação que identificam a origem de um lançamento no
# legado. `motivo` só passou a ser gravado na v4.3.0 e está 0% preenchido nas 2.822 linhas
# do histórico real, então para tudo que é anterior o texto é a única pista. A ordem
# importa: o primeiro prefixo que casar vence.
_PREFIXOS_CATEGORIA = (
    ("saldo inicial", "Saldo Inicial"),
    ("ajuste via edição de item", "Ajuste por Edição"),
    ("ajuste:", "Ajuste Manual"),
    ("ajuste —", "Ajuste Manual"),
    ("ajuste -", "Ajuste Manual"),
)


def categoria_movimentacao(m):
    """Rótulo amigável de uma movimentação para o Histórico e para o relatório.

    v4.3.0 — deriva de (motivo, tipo, vínculo). Os lançamentos do Ajuste Rápido guardam o
    rótulo em `motivo` (Entrada Avulsa / Devolução / Perda de Material / Saída Avulsa).

    v5.7.0 (CP4) — separa os TRÊS caminhos de ajuste, que até aqui desabavam juntos em
    "Entrada"/"Saída" e tornavam impossível responder às perguntas da decisão nº7 (quanto
    se perdeu no período · quais itens vivem divergindo · reconciliação do saldo):

      • **Ajuste de Inventário** — contagem física que mexeu no saldo (`CC_INVENTARIO`);
      • **Ajuste por Edição** — o saldo mudou ao editar o cadastro do item (`CC_EDICAO`);
      • **Ajuste Manual** — correção de balcão pelo Ajuste Rápido sem `motivo` (legado).

    A ordem das checagens é preservada de propósito: `quantidade == 0` continua vindo
    ANTES do vínculo e da derivação (é o que `tests/test_v430_ajuste_pn.py` afirma), senão
    a Conferência de Inventário — que existe justamente para registrar contagem sem
    alteração de saldo — viraria "Ajuste de Inventário" e inflaria a divergência."""
    motivo = (m.get("motivo") or "").strip()
    if motivo:
        return motivo
    if (m.get("quantidade") or 0) == 0:
        return "Conferência"
    tipo = m.get("tipo")
    if tipo == "saida" and m.get("requisicao_id"):
        return "Requisição"

    obs = (m.get("observacao") or "").strip().lower()
    for prefixo, rotulo in _PREFIXOS_CATEGORIA:
        if obs.startswith(prefixo):
            return rotulo
    # O CC é o sinal forte do legado: os templates da tela de Inventário mudaram cinco
    # vezes ("Ajuste Físico", "Ajuste de Qtd", "174 UN Caixa: …"), mas o CC nunca mudou.
    cc = (m.get("centro_custo") or "").strip().upper()
    if cc == CC_INVENTARIO:
        return "Ajuste de Inventário"
    if cc == CC_EDICAO:
        return "Ajuste por Edição"
    return {"entrada": "Entrada", "saida": "Saída", "devolucao": "Devolução"}.get(tipo, tipo or "—")


# ══════════════════════════════════════════════════════════════════════════════
# REQUISIÇÕES
# ══════════════════════════════════════════════════════════════════════════════

# v5.7.0 (decisão nº1 da entrevista de 27/07/2026) — os dois fluxos convivem: o **Padrão** é
# o da operação real (o material sai no balcão, a baixa é na criação) e o **Digital** é o
# protótipo de vitrine do self-service (baixa só na entrega). Gravado em
# `requisicoes.tipo_fluxo`; NULL é requisição legada, anterior à coluna.
FLUXO_PADRAO = "Padrão"
FLUXO_DIGITAL = "Digital"


# v6.5.0 — quantas vezes reemitir o número quando o `UNIQUE` reprova a inserção. Três
# basta: cada tentativa relê o `MAX` já com a linha do concorrente commitada, então só
# perderia de novo quem levasse mais um empate exato — e a alternativa a errar três vezes
# seguidas é o erro na tela, não um laço infinito segurando a transação aberta.
TENTATIVAS_NUMERO_REQUISICAO = 3


def _gerar_numero_requisicao(conn):
    """v6.5.0 — numeração sequencial simples e GLOBAL: 1, 2, 3, … N.

    Até a v6.4.0 o número era `REQ-AAAAMMDD-NNN`, derivado de um `COUNT(*)` do dia. A
    operação pediu o número curto que se lê em voz alta na guarita, e a data — único
    conteúdo que o formato antigo carregava — já vive em `data_hora`, que é o que a
    Portaria e o cartão exibem.

    `MAX + 1` sobre os números puramente numéricos. O filtro `GLOB` importa em dois
    momentos: ele ignora o legado `REQ-…` de um banco que ainda não migrou e os números
    sintéticos dos testes ('REQ-TEST-3-1'), que envenenariam o `CAST` — `CAST('12A' AS
    INTEGER)` é 12, e um número inventado por fixture passaria a ditar o próximo da fila.

    Continua sendo read-then-write não atômico, exatamente como o `COUNT` que substituiu:
    a barreira real sempre foi o `UNIQUE` da coluna. O que muda é que o contador deixou de
    ser por dia e virou global, o que alarga a janela entre dois almoxarifes criando
    pedidos ao mesmo tempo — por isso `_inserir_requisicao` agora tenta de novo em vez de
    devolver o `IntegrityError` cru."""
    r = conn.execute("""
        SELECT MAX(CAST(numero_requisicao AS INTEGER)) AS ultimo FROM requisicoes
        WHERE numero_requisicao NOT GLOB '*[^0-9]*'
    """).fetchone()
    return str(int((r["ultimo"] if r else None) or 0) + 1)


def _inserir_requisicao(
    conn,
    setor,
    emitente,
    centro_custo,
    autorizador_tipo,
    autorizador_nome,
    entrega_individual,
    destinatarios,
    sesmt,
    sesmt_responsavel,
    itens,
    observacoes,
    tipo_fluxo,
    agora,
):
    """v5.7.0 — Escrita do pedido: a linha em `requisicoes` mais os itens, sempre com
    `quantidade_atendida=0`. Extraído de `criar_requisicao` para que a Requisição Padrão
    (que baixa estoque na criação) reuse exatamente a mesma escrita em vez de duplicá-la.

    Nasce **Aberta** nos dois fluxos; quem baixa estoque corrige o status depois, via
    `_calcular_status_requisicao`. Não abre transação: o chamador é o dono dela — é o que
    permite à Padrão criar e baixar atomicamente. Devolve `(req_id, numero_requisicao)`.

    v6.5.0 — com o número sequencial GLOBAL (antes era por dia), duas criações simultâneas
    passam a disputar o mesmo `MAX + 1`. A colisão sempre foi barrada pelo `UNIQUE`; o que
    faltava era reagir a ela. O `IntegrityError` da coluna do número vira nova tentativa —
    o SQLite faz rollback só do INSERT que falhou (`ON CONFLICT ABORT`), então a transação
    do chamador continua íntegra e a Padrão não perde a baixa de estoque que já fez.
    Qualquer OUTRO `IntegrityError` sobe na hora: repetir uma FK inválida três vezes só
    esconderia o defeito real."""
    for tentativa in range(TENTATIVAS_NUMERO_REQUISICAO):
        num = _gerar_numero_requisicao(conn)
        try:
            cur = conn.execute(
                """INSERT INTO requisicoes
                (numero_requisicao,data_hora,setor,emitente,centro_custo,autorizador_tipo,
                 autorizador_nome,entrega_individual,destinatarios,sesmt,sesmt_responsavel,
                 observacoes,status,tipo_fluxo)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?, 'Aberta', ?)""",
                (
                    num,
                    agora,
                    setor,
                    emitente,
                    centro_custo,
                    autorizador_tipo,
                    autorizador_nome,
                    1 if entrega_individual else 0,
                    json.dumps(destinatarios or [], ensure_ascii=False),
                    1 if sesmt else 0,
                    sesmt_responsavel,
                    observacoes,
                    tipo_fluxo,
                ),
            )
            break
        except sqlite3.IntegrityError as e:
            if "numero_requisicao" not in str(e) or tentativa == TENTATIVAS_NUMERO_REQUISICAO - 1:
                raise
            logger.warning("Número de requisição %s já em uso; reemitindo.", num)
    req_id = cur.lastrowid
    for it in itens:
        conn.execute(
            "INSERT INTO itens_requisicao (requisicao_id,item_id,quantidade_solicitada,quantidade_atendida) VALUES (?,?,?,0)",
            (req_id, it["item_id"], float(it.get("quantidade_solicitada", 0))),
        )
    return req_id, num


def _itens_requisicao_validos(itens):
    """Itens com quantidade > 0. Comum aos dois fluxos de criação."""
    return [it for it in (itens or []) if float(it.get("quantidade_solicitada", 0)) > 0]


def criar_requisicao(
    setor,
    emitente,
    centro_custo,
    autorizador_tipo,
    autorizador_nome,
    entrega_individual,
    destinatarios,
    sesmt,
    sesmt_responsavel,
    itens,
    observacoes="",
):
    """v4.7.0 — Requisição Digital: cria a requisição no estado **Aberta**, sem baixar
    estoque. A baixa passou a acontecer só na ENTREGA (ver `entregar_requisicao`), o que
    habilita atendimento parcial e em lote (o jeito do Juan). Os itens entram com
    `quantidade_atendida=0`. O autorizador é opcional aqui (registrado na entrega).

    Assinatura preservada para compatibilidade; `quantidade_atendida` eventualmente
    presente em `itens` é ignorada (a atendida é decidida na entrega).

    v5.7.0 — **o contrato de estoque não muda**: continua sem baixar nada (é o que
    `tests/test_requisicao.py::test_criacao_nao_baixa_estoque` fixa desde a v4.7.0). O
    único acréscimo é o carimbo `tipo_fluxo='Digital'`, que separa este pedido do fluxo
    Padrão no histórico. Para criar baixando estoque, use `criar_requisicao_com_baixa`."""
    if not itens:
        return False, "Adicione ao menos um item."
    itens_validos = _itens_requisicao_validos(itens)
    if not itens_validos:
        return False, "Adicione ao menos um item com quantidade > 0."
    agora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        with transaction() as conn:
            _, num = _inserir_requisicao(
                conn,
                setor,
                emitente,
                centro_custo,
                autorizador_tipo,
                autorizador_nome,
                entrega_individual,
                destinatarios,
                sesmt,
                sesmt_responsavel,
                itens_validos,
                observacoes,
                FLUXO_DIGITAL,
                agora,
            )
        return True, num
    except Exception as e:
        return False, str(e)


def _calcular_status_requisicao(conn, req_id):
    """Deriva o status de uma requisição a partir dos itens: nada atendido → 'Aberta';
    tudo atendido (atendida >= solicitada em todos) → 'Entregue'; caso intermediário →
    'Parcial'. Nunca sobrescreve 'Cancelada' (tratado pelo chamador)."""
    itens = conn.execute(
        "SELECT quantidade_solicitada, quantidade_atendida FROM itens_requisicao WHERE requisicao_id=?",
        (req_id,),
    ).fetchall()
    if not itens:
        return "Aberta"
    total_atendido = sum(float(i["quantidade_atendida"] or 0) for i in itens)
    if total_atendido <= 0:
        return "Aberta"
    if all(float(i["quantidade_atendida"] or 0) >= float(i["quantidade_solicitada"] or 0) for i in itens):
        return "Entregue"
    return "Parcial"


def validar_data_saida(data_saida, agora=None):
    """v5.9.0 — Normaliza a data REAL da saída do material. Devolve `(valor, erro)`.

    Retroagir é livre (é a data de verdade do consumo — decisão do usuário); o FUTURO é
    recusado. Data futura envenenaria todas as janelas `datetime('now','-N days')` que
    calculam consumo, giro, ABC e cobertura, além da ordenação do ledger.

    `None` significa "material saindo agora" e passa direto — quem chama usa `agora`."""
    if data_saida is None:
        return None, None
    if isinstance(data_saida, datetime):
        data_saida = data_saida.strftime("%Y-%m-%d %H:%M:%S")
    data_saida = str(data_saida).strip()
    if not data_saida:
        return None, None
    try:
        dt = datetime.strptime(data_saida[:19], "%Y-%m-%d %H:%M:%S")
    except ValueError:
        try:
            dt = datetime.strptime(data_saida[:10], "%Y-%m-%d")
        except ValueError:
            return None, f"Data de saída inválida: {data_saida!r}."
    limite = datetime.strptime(agora, "%Y-%m-%d %H:%M:%S") if agora else datetime.now()
    if dt > limite:
        return None, "A data da saída não pode estar no futuro."
    return dt.strftime("%Y-%m-%d %H:%M:%S"), None


def _baixar_item_requisicao(conn, req, item_req_id, item_id, quantidade, agora, data_saida=None):
    """v5.7.0 — A baixa real de UM item de requisição, do jeito que a v4.7.0 já fazia na
    entrega: movimentação `saida` amarrada à requisição (`requisicao_id`), `UPDATE` do
    saldo, acúmulo em `quantidade_atendida` e recálculo de consumo/ruptura.

    Extraído de `entregar_requisicao` para que a Requisição Padrão baixe pelo MESMO
    caminho — sem isto haveria duas escritas de estoque a manter em sincronia, e o ledger
    da Padrão nasceria diferente do da Digital. Recusa quantidade maior que o saldo
    (contrato da entrega); a Padrão nunca esbarra nisso porque já entra com
    `min(solicitada, estoque)`. Não abre transação: quem chama é o dono dela.

    v5.9.0 — `data_saida` (já validada por `validar_data_saida`) é a data REAL em que o
    material saiu, quando o lançamento é retroativo; `agora` continua sendo o instante do
    LANÇAMENTO. Só a movimentação retroage: `inventario.data_atualizacao` registra quando
    o cadastro foi tocado, e a numeração da requisição deriva da data dela — retroagir
    qualquer um dos dois quebraria auditoria e numeração.

    Limitação registrada: `saldo_apos` é o saldo no instante do lançamento, não no
    instante retroagido; com lançamento retroativo ele deixa de ser monotônico na ordem de
    data. Nenhum cálculo do sistema lê `saldo_apos` (é coluna de auditoria visual), mas
    quem ler o extrato precisa saber — por isso o instante do lançamento vai na
    observação."""
    r_est = conn.execute(
        "SELECT estoque_atual, part_number FROM inventario WHERE id=?", (item_id,)
    ).fetchone()
    if not r_est or r_est["estoque_atual"] < quantidade:
        pn = r_est["part_number"] if r_est else "Item"
        raise Exception(f"Estoque insuficiente para {pn} (disp.: {r_est['estoque_atual'] if r_est else 0}).")
    novo_saldo = r_est["estoque_atual"] - quantidade
    saida_em = data_saida or agora
    observacao = f"Req {req['numero_requisicao']}"
    if data_saida and data_saida != agora:
        observacao += f" · saída retroativa (lançada em {agora})"
    conn.execute(
        "INSERT INTO movimentacoes (item_id,tipo,quantidade,saldo_apos,data_hora,centro_custo,setor,solicitante,emitente,observacao,requisicao_id) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (
            item_id,
            "saida",
            quantidade,
            novo_saldo,
            saida_em,
            req["centro_custo"],
            req["setor"],
            req["emitente"],
            req["emitente"],
            observacao,
            req["id"],
        ),
    )
    conn.execute(
        "UPDATE inventario SET estoque_atual=?, data_atualizacao=? WHERE id=?",
        (novo_saldo, agora, item_id),
    )
    conn.execute(
        "UPDATE itens_requisicao SET quantidade_atendida = quantidade_atendida + ? WHERE id=?",
        (quantidade, item_req_id),
    )
    _recalcular_consumo(conn, item_id)
    _recalcular_ruptura_by_id(conn, item_id)


def criar_requisicao_com_baixa(
    setor,
    emitente,
    centro_custo,
    autorizador_tipo,
    autorizador_nome,
    entrega_individual,
    destinatarios,
    sesmt,
    sesmt_responsavel,
    itens,
    observacoes="",
    data_saida=None,
):
    """v5.7.0 — **Requisição Padrão** (decisões nº1 e nº2 da entrevista de 27/07/2026): o
    fluxo real do balcão, em que o material sai na hora. Cria o pedido e baixa o estoque na
    MESMA transação — ou tudo acontece, ou nada.

    Falta de saldo **não recusa o pedido**: baixa `min(solicitada, estoque_atual)` de cada
    item e o restante fica pendente, exatamente como a operação faz hoje no papel. O status
    sai de `_calcular_status_requisicao` e a requisição entra na Fila de Separação com o
    que faltou — é o que substitui a regra antiga de "recusa e avisa qual item"
    (`docs/prompt.md:38`). Item sem nenhum saldo simplesmente não gera movimentação: sem
    baixa nenhuma o pedido nasce `Aberta`, inteiro na fila.

    Exige autorizador (material só sai autorizado) e, se SESMT, o responsável — as mesmas
    validações de `entregar_requisicao`, aqui na criação porque é aqui que o material sai.

    Devolve `(True, {"numero", "status", "faltas": [...]})`, com `faltas` listando o que
    ficou pendente para a tela poder dizer o que foi para a fila."""
    if not itens:
        return False, "Adicione ao menos um item."
    itens_validos = _itens_requisicao_validos(itens)
    if not itens_validos:
        return False, "Adicione ao menos um item com quantidade > 0."
    if not autorizador_nome or not str(autorizador_nome).strip():
        return False, "Informe o autorizador (gestor): na Requisição Padrão o material sai na criação."
    if sesmt and not (sesmt_responsavel and str(sesmt_responsavel).strip()):
        return False, "Material SESMT: informe o responsável do SESMT."
    agora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    data_saida, erro = validar_data_saida(data_saida, agora)
    if erro:
        return False, erro
    try:
        with transaction() as conn:
            req_id, num = _inserir_requisicao(
                conn,
                setor,
                emitente,
                centro_custo,
                autorizador_tipo,
                autorizador_nome,
                entrega_individual,
                destinatarios,
                sesmt,
                sesmt_responsavel if sesmt else "",
                itens_validos,
                observacoes,
                FLUXO_PADRAO,
                agora,
            )
            req = {
                "id": req_id,
                "numero_requisicao": num,
                "setor": setor,
                "emitente": emitente,
                "centro_custo": centro_custo,
            }
            faltas = []
            for it in listar_itens_requisicao(req_id, conn=conn):
                solicitada = float(it["quantidade_solicitada"])
                disponivel = float(it["estoque_atual"] or 0)
                atendida = min(solicitada, disponivel)
                if atendida > 0:
                    _baixar_item_requisicao(
                        conn, req, it["id"], it["item_id"], atendida, agora, data_saida=data_saida
                    )
                if atendida < solicitada:
                    faltas.append(
                        {
                            "part_number": it["part_number"],
                            "nome_item": it["nome_item"],
                            "unidade": it["unidade"],
                            "solicitada": solicitada,
                            "atendida": atendida,
                            "falta": solicitada - atendida,
                        }
                    )
            novo_status = _calcular_status_requisicao(conn, req_id)
            conn.execute("UPDATE requisicoes SET status=? WHERE id=?", (novo_status, req_id))
        return True, {"numero": num, "status": novo_status, "faltas": faltas}
    except Exception as e:
        return False, str(e)


def entregar_requisicao(
    req_id,
    entregas,
    autorizador_tipo,
    autorizador_nome,
    sesmt=False,
    sesmt_responsavel="",
    data_saida=None,
):
    """v4.7.0 — Registra a ENTREGA (baixa) de itens de uma requisição Aberta/Parcial.

    `entregas`: lista de {"item_req_id": id, "quantidade": q}. Para cada item, dá baixa
    real no estoque (movimentação 'saida' com requisicao_id), acumula `quantidade_atendida`
    e recalcula consumo/ruptura. Atualiza os dados de autorização na requisição e recalcula
    o status (Parcial/Entregue). Atômico: qualquer falha reverte tudo.

    Regras: exige autorizador (material só sai autorizado); se `sesmt`, exige o responsável.

    v5.9.0 — `data_saida` opcional: a data/hora REAL em que o material saiu, para o
    lançamento retroativo ("Material saindo agora" desmarcado na tela). `None` = agora,
    que é o comportamento de sempre — a assinatura segue retrocompatível.
    """
    if not autorizador_nome or not str(autorizador_nome).strip():
        return False, "Informe o autorizador (gestor) para liberar a entrega."
    if sesmt and not (sesmt_responsavel and str(sesmt_responsavel).strip()):
        return False, "Material SESMT: informe o responsável do SESMT."
    entregas = [e for e in (entregas or []) if float(e.get("quantidade", 0)) > 0]
    if not entregas:
        return False, "Informe ao menos um item com quantidade a entregar."
    agora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    data_saida, erro = validar_data_saida(data_saida, agora)
    if erro:
        return False, erro
    try:
        with transaction() as conn:
            req = conn.execute(
                """SELECT id, numero_requisicao, setor, emitente, centro_custo, status,
                          rejeitado_por, rejeitado_em, motivo_rejeicao, reenviado_em
                   FROM requisicoes WHERE id=?""",
                (req_id,),
            ).fetchone()
            if not req:
                raise Exception("Requisição não encontrada.")
            if req["status"] not in ("Aberta", "Parcial"):
                raise Exception(f"Requisição {req['status']}: não é possível entregar.")
            # v6.4.0 — requisição DEVOLVIDA pelo gestor não sai do almoxarifado (decisão do
            # Luis em 05/08/2026: "se não foi aprovada pelo gestor, não podemos entregar o
            # material"). A trava vive AQUI, e não só no filtro da fila: sumir da lista é
            # conveniência de tela, e qualquer outro caminho até a entrega — link direto,
            # tela futura, chamada de serviço — passaria por cima dela.
            #
            # ⚠️ Isto NÃO torna a aprovação obrigatória. Só a rejeição EXPLÍCITA bloqueia;
            # requisição que o gestor ainda não olhou continua entregável, como desde a
            # v6.2.0. Exigir aprovação para toda entrega pararia a operação inteira: em
            # 05/08/2026 o `mro.db` tem 1.132 requisições e ZERO aprovadas.
            if req["rejeitado_em"] and not req["reenviado_em"]:
                raise Exception(
                    f"Requisição devolvida por {req['rejeitado_por']} em {req['rejeitado_em']} "
                    f"(motivo: {req['motivo_rejeicao'] or '—'}). O requisitante precisa ajustar "
                    "e reenviar antes de o material sair."
                )
            for e in entregas:
                q = float(e["quantidade"])
                ir = conn.execute(
                    "SELECT id, item_id, quantidade_atendida FROM itens_requisicao WHERE id=? AND requisicao_id=?",
                    (e["item_req_id"], req_id),
                ).fetchone()
                if not ir:
                    raise Exception("Item da requisição não encontrado.")
                _baixar_item_requisicao(conn, req, ir["id"], ir["item_id"], q, agora, data_saida=data_saida)
            novo_status = _calcular_status_requisicao(conn, req_id)
            conn.execute(
                """UPDATE requisicoes SET status=?, autorizador_tipo=?, autorizador_nome=?,
                       sesmt=?, sesmt_responsavel=? WHERE id=?""",
                (
                    novo_status,
                    autorizador_tipo,
                    autorizador_nome,
                    1 if sesmt else 0,
                    sesmt_responsavel if sesmt else "",
                    req_id,
                ),
            )
        return True, novo_status
    except Exception as e:
        return False, str(e)


def adicionar_itens_requisicao(req_id, itens):
    """v4.7.0 — Adiciona itens a uma requisição (caso 'escreve no mesmo papel').
    Itens entram com `quantidade_atendida=0`. Não altera baixa.

    v5.7.0 (decisão nº4 da entrevista de 27/07/2026) — passa a aceitar requisição
    **Entregue**, que REABRE como `Parcial`. Só `Cancelada` é recusada: nela não há o que
    reabrir.

    O `UPDATE` do status no fim é a metade indispensável da mudança, não um detalhe: sem
    ele, o item novo entra numa requisição que continua marcada `Entregue`, some da fila
    (`listar_requisicoes_abertas` filtra por Aberta/Parcial) e é recusado por
    `entregar_requisicao` — um item órfão, invisível e não entregável. Por isso liberar a
    guarda e recalcular o status andam sempre juntos."""
    itens_validos = [it for it in (itens or []) if float(it.get("quantidade_solicitada", 0)) > 0]
    if not itens_validos:
        return False, "Adicione ao menos um item com quantidade > 0."
    try:
        with transaction() as conn:
            req = conn.execute("SELECT status FROM requisicoes WHERE id=?", (req_id,)).fetchone()
            if not req:
                raise Exception("Requisição não encontrada.")
            if req["status"] == "Cancelada":
                raise Exception("Requisição Cancelada: não aceita novos itens.")
            for it in itens_validos:
                conn.execute(
                    "INSERT INTO itens_requisicao (requisicao_id,item_id,quantidade_solicitada,quantidade_atendida) VALUES (?,?,?,0)",
                    (req_id, it["item_id"], float(it["quantidade_solicitada"])),
                )
            novo_status = _calcular_status_requisicao(conn, req_id)
            conn.execute("UPDATE requisicoes SET status=? WHERE id=?", (novo_status, req_id))
        reaberta = req["status"] == "Entregue" and novo_status != "Entregue"
        msg = f"{len(itens_validos)} item(ns) adicionado(s)."
        if reaberta:
            msg += f" Requisição reaberta como {novo_status} e de volta à fila de separação."
        return True, msg
    except Exception as e:
        return False, str(e)


def remover_item_requisicao(item_req_id):
    """v4.7.0 — Remove um item ainda NÃO atendido de uma requisição Aberta/Parcial."""
    try:
        with transaction() as conn:
            ir = conn.execute(
                "SELECT id, requisicao_id, quantidade_atendida FROM itens_requisicao WHERE id=?",
                (item_req_id,),
            ).fetchone()
            if not ir:
                raise Exception("Item não encontrado.")
            if float(ir["quantidade_atendida"] or 0) > 0:
                raise Exception("Item já entregue (parcial/total): não pode ser removido.")
            req = conn.execute("SELECT status FROM requisicoes WHERE id=?", (ir["requisicao_id"],)).fetchone()
            if req and req["status"] not in ("Aberta", "Parcial"):
                raise Exception(f"Requisição {req['status']}: não pode ser editada.")
            conn.execute("DELETE FROM itens_requisicao WHERE id=?", (item_req_id,))
        return True, "Item removido."
    except Exception as e:
        return False, str(e)


def atualizar_item_requisicao(item_req_id, quantidade):
    """v6.4.0 — Corrige a quantidade solicitada de um item ainda NÃO atendido.

    Nasce com o ciclo de rejeição: o gestor devolve o pedido dizendo "10 é demais, peça 2",
    e até aqui o requisitante só sabia REMOVER o item e adicioná-lo de novo — perdendo a
    ordem da lista e exigindo dois passos para uma correção de um número.

    Mesmas guardas de `remover_item_requisicao`, e pelos mesmos motivos: item já entregue
    (parcial ou total) não se mexe, porque a quantidade solicitada é a referência contra a
    qual a baixa foi conferida; e requisição fora de Aberta/Parcial não se edita.
    Quantidade tem de ser > 0 — zerar seria remover pela porta dos fundos, sem passar pela
    checagem de item já atendido."""
    try:
        qtd = float(quantidade)
    except (TypeError, ValueError):
        return False, "Quantidade inválida."
    if qtd <= 0:
        return False, "A quantidade deve ser maior que zero (para tirar o item, use Remover)."
    try:
        with transaction() as conn:
            ir = conn.execute(
                "SELECT id, requisicao_id, quantidade_atendida FROM itens_requisicao WHERE id=?",
                (item_req_id,),
            ).fetchone()
            if not ir:
                raise Exception("Item não encontrado.")
            if float(ir["quantidade_atendida"] or 0) > 0:
                raise Exception("Item já entregue (parcial/total): a quantidade não pode ser alterada.")
            req = conn.execute("SELECT status FROM requisicoes WHERE id=?", (ir["requisicao_id"],)).fetchone()
            if req and req["status"] not in ("Aberta", "Parcial"):
                raise Exception(f"Requisição {req['status']}: não pode ser editada.")
            conn.execute("UPDATE itens_requisicao SET quantidade_solicitada=? WHERE id=?", (qtd, item_req_id))
        return True, f"Quantidade alterada para {qtd:g}."
    except Exception as e:
        return False, str(e)


def cancelar_requisicao(req_id):
    """v4.7.0 — Cancela uma requisição **Aberta** (nada entregue, nada a estornar)."""
    try:
        with transaction() as conn:
            req = conn.execute("SELECT status FROM requisicoes WHERE id=?", (req_id,)).fetchone()
            if not req:
                raise Exception("Requisição não encontrada.")
            if req["status"] != "Aberta":
                raise Exception(f"Só requisições Abertas podem ser canceladas (esta está {req['status']}).")
            conn.execute("UPDATE requisicoes SET status='Cancelada' WHERE id=?", (req_id,))
        return True, "Requisição cancelada."
    except Exception as e:
        return False, str(e)


def aprovar_requisicao(req_id, gestor_nome):
    """v6.2.0 — Registra a aprovação do gestor do setor. **NÃO é bloqueante.**

    Grava só `aprovado_por`/`aprovado_em`: não toca `status` (nenhum status novo — decisão
    de 02/08/2026) nem `autorizador_tipo`/`autorizador_nome`, que continuam sendo exigidos
    do almoxarife na ENTREGA (`entregar_requisicao`). O almoxarife pode separar e entregar
    uma requisição não aprovada exatamente como antes; a aprovação é um registro paralelo
    da autorização antecipada do setor, não uma trava.

    A primeira aprovação vale: aprovar de novo devolve `(True, "Já aprovada por…")` e não
    sobrescreve. Quem aprovou primeiro é o dado com valor de auditoria, e uma segunda
    chamada é quase sempre duplo-clique ou refresh — reescrever apagaria o registro certo.

    `aprovado_em` usa `datetime.now()` (hora local), como `data_hora` das requisições, e
    não `CURRENT_TIMESTAMP` do SQLite, que é UTC: as duas datas aparecem lado a lado na
    tela da Portaria e um pedido apareceria "aprovado" 3 horas depois de entregue."""
    gestor = str(gestor_nome or "").strip()
    if not gestor:
        return False, "Informe o nome de quem está aprovando."
    agora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        with transaction() as conn:
            req = conn.execute(
                """SELECT numero_requisicao, status, aprovado_por, aprovado_em,
                          rejeitado_por, rejeitado_em, reenviado_em
                   FROM requisicoes WHERE id=?""",
                (req_id,),
            ).fetchone()
            if not req:
                raise Exception("Requisição não encontrada.")
            if req["status"] == "Cancelada":
                raise Exception("Requisição Cancelada: não pode ser aprovada.")
            # v6.4.0 — guarda simétrica à de `rejeitar_requisicao`: enquanto o pedido está
            # com o requisitante, aprová-lo deixaria a Portaria com dois carimbos
            # contraditórios. Não é beco sem saída — basta o requisitante reenviar (mesmo
            # sem mudar nada) para o pedido voltar e poder ser aprovado.
            if req["rejeitado_em"] and not req["reenviado_em"]:
                raise Exception(
                    f"Requisição devolvida por {req['rejeitado_por']} e ainda não reenviada "
                    "pelo requisitante: não pode ser aprovada."
                )
            if req["aprovado_por"]:
                return True, f"Já aprovada por {req['aprovado_por']} em {req['aprovado_em']}."
            conn.execute(
                "UPDATE requisicoes SET aprovado_por=?, aprovado_em=? WHERE id=?",
                (gestor, agora, req_id),
            )
        return True, f"Requisição {req['numero_requisicao']} aprovada."
    except Exception as e:
        return False, str(e)


def rejeitar_requisicao(req_id, gestor_nome, motivo):
    """v6.4.0 — O gestor DEVOLVE a requisição ao requisitante, com o motivo.

    Decisão do Luis (05/08/2026): rejeitar não é um "não" final, é o começo de um ciclo —
    o requisitante lê o motivo, ajusta o pedido e reenvia (`reenviar_requisicao`), e ele
    volta para a fila do gestor. Por isso o **motivo é obrigatório**: é o único canal que
    diz à outra ponta o que corrigir, e uma rejeição muda faz o requisitante reenviar o
    mesmo pedido.

    Como a aprovação da v6.2.0, **não é bloqueante e não cria status**: o pedido sai da
    fila de aprovação (via `_clausulas_aprovacao`), mas continua na fila de separação do
    almoxarife, que segue podendo entregar. Rejeição registra a posição do setor; quem
    libera material continua sendo o almoxarifado.

    Ao contrário de `aprovar_requisicao` — onde a PRIMEIRA aprovação vence, porque é
    carimbo de auditoria e a 2ª chamada é quase sempre duplo-clique — rejeitar de novo
    **sobrescreve**: é o estado corrente de um ciclo que pode se repetir, e o motivo que
    vale é sempre o último (o requisitante precisa ver o que ainda está errado, não o que
    já corrigiu).

    Requisição já aprovada é recusada: aprovado e rejeitado ao mesmo tempo deixaria a
    Portaria com dois carimbos contraditórios e ninguém sabendo qual vale."""
    gestor = str(gestor_nome or "").strip()
    motivo_txt = str(motivo or "").strip()
    if not gestor:
        return False, "Informe o nome de quem está rejeitando."
    if not motivo_txt:
        return False, "Explique o motivo — é o que diz ao requisitante o que ajustar."
    agora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        with transaction() as conn:
            req = conn.execute(
                "SELECT numero_requisicao, status, aprovado_por FROM requisicoes WHERE id=?",
                (req_id,),
            ).fetchone()
            if not req:
                raise Exception("Requisição não encontrada.")
            if req["status"] == "Cancelada":
                raise Exception("Requisição Cancelada: não há o que rejeitar.")
            if req["aprovado_por"]:
                raise Exception(f"Requisição já aprovada por {req['aprovado_por']}: não pode ser rejeitada.")
            conn.execute(
                """UPDATE requisicoes
                   SET rejeitado_por=?, rejeitado_em=?, motivo_rejeicao=?, reenviado_em=NULL
                   WHERE id=?""",
                (gestor, agora, motivo_txt, req_id),
            )
        return True, f"Requisição {req['numero_requisicao']} devolvida ao requisitante."
    except Exception as e:
        return False, str(e)


def reenviar_requisicao(req_id):
    """v6.4.0 — O requisitante devolve à fila do gestor a requisição que foi rejeitada.

    Fecha o ciclo aberto por `rejeitar_requisicao`. Grava `reenviado_em` em vez de LIMPAR
    `rejeitado_*`: assim o gestor reencontra o pedido sabendo o que ele mesmo havia pedido
    para ajustar. É `reenviado_em > rejeitado_em` que devolve o pedido à fila (ver
    `_clausulas_aprovacao`), e é por isso que uma nova rejeição zera este campo — o ciclo
    pode se repetir quantas vezes for preciso.

    Recusa reenvio sem rejeição pendente: reenviar o que ninguém devolveu não significa
    nada, e deixaria `reenviado_em` preenchido num pedido que nunca saiu da fila."""
    agora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        with transaction() as conn:
            req = conn.execute(
                """SELECT numero_requisicao, status, rejeitado_em, reenviado_em
                   FROM requisicoes WHERE id=?""",
                (req_id,),
            ).fetchone()
            if not req:
                raise Exception("Requisição não encontrada.")
            if req["status"] == "Cancelada":
                raise Exception("Requisição Cancelada: não pode ser reenviada.")
            if not req["rejeitado_em"]:
                raise Exception("Esta requisição não foi rejeitada — não há o que reenviar.")
            if req["reenviado_em"]:
                return True, "Já reenviada — está na fila do gestor."
            conn.execute("UPDATE requisicoes SET reenviado_em=? WHERE id=?", (agora, req_id))
        return True, f"Requisição {req['numero_requisicao']} reenviada para aprovação."
    except Exception as e:
        return False, str(e)


def listar_requisicoes_abertas(incluir_entregues=False):
    """v4.7.0 — Fila de separação: requisições Aberta/Parcial (mais antigas primeiro),
    com contagem de itens e do que ainda falta atender.

    v5.7.0 — `incluir_entregues` traz também as **Entregues**, para que o "Adicionar Item"
    (que desde a v5.7.0 as reabre como `Parcial`) seja alcançável pela tela. Sem esse
    parâmetro a requisição Entregue não é selecionável na fila e a liberação no serviço
    ficaria inútil na prática. `Cancelada` nunca entra: não aceita item novo.
    O default preserva a fila de trabalho do almoxarife — só o que falta separar.

    v6.4.0 — requisição **devolvida** pelo gestor sai da fila (decisão do Luis em
    05/08/2026: sem o aval do gestor o material não sai). Volta sozinha quando o
    requisitante reenviar, pelo mesmo `DEVOLVIDA_WHERE` que rege as filas de aprovação —
    uma regra só, para a fila do almoxarife e a do gestor nunca discordarem sobre o que
    está em aberto. A trava de verdade está em `entregar_requisicao`; aqui é a metade que
    tira o pedido da frente de quem separa."""
    status = "('Aberta','Parcial','Entregue')" if incluir_entregues else "('Aberta','Parcial')"
    with transaction() as conn:
        rows = conn.execute(f"""
            SELECT r.*,
                   COUNT(ir.id) AS total_itens,
                   SUM(CASE WHEN ir.quantidade_atendida < ir.quantidade_solicitada THEN 1 ELSE 0 END) AS itens_pendentes
            FROM requisicoes r
            LEFT JOIN itens_requisicao ir ON ir.requisicao_id = r.id
            WHERE r.status IN {status}
              AND NOT ({DEVOLVIDA_WHERE})
            GROUP BY r.id
            ORDER BY r.data_hora ASC
        """).fetchall()
    return [dict(r) for r in rows]


def _consultar_requisicoes(filtro="", params=(), ordem="r.data_hora DESC", limit=None):
    """SELECT canônico das requisições: a linha de `requisicoes` mais os agregados
    `total_itens`/`total_atendido` dos seus itens.

    v6.2.0 — extraído de `listar_requisicoes` quando a Portaria (busca por número) e o
    Gestor (fila do setor) passaram a precisar exatamente do mesmo shape. Só o `WHERE` e a
    ordem mudam entre os três; duplicar o SELECT deixaria três lugares para manter em
    sincronia — e uma tela mostrando um agregado diferente da outra é justamente o tipo de
    divergência que ninguém percebe. Não cobre `listar_requisicoes_abertas`, cujo agregado
    é outro (`itens_pendentes`, a fila de separação do almoxarife)."""
    sql = f"""
        SELECT r.*,
               COUNT(ir.id) AS total_itens,
               SUM(ir.quantidade_atendida) AS total_atendido
        FROM requisicoes r
        LEFT JOIN itens_requisicao ir ON ir.requisicao_id=r.id
        {filtro}
        GROUP BY r.id
        ORDER BY {ordem}
    """
    params = list(params)
    if limit is not None:
        sql += " LIMIT ?"
        params.append(limit)
    with transaction() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [dict(r) for r in rows]


def listar_requisicoes(limit=100, emitente=None):
    """v5.7.0 — `emitente` filtra as requisições de um solicitante (comparação
    case-insensitive, para não perder 'Joao' × 'JOAO'). Alimenta a Visão do Solicitante da
    Fila, que mostra TODOS os status — inclusive Entregue/Cancelada, que é justamente o que
    quem pediu o material quer acompanhar."""
    filtro, params = "", []
    if emitente and str(emitente).strip():
        filtro = "WHERE UPPER(TRIM(r.emitente)) = UPPER(TRIM(?))"
        params.append(str(emitente).strip())
    return _consultar_requisicoes(filtro, params, limit=limit)


def buscar_requisicao_por_numero(numero):
    """v6.2.0 — Consulta da Portaria: uma requisição pelo NÚMERO completo, com os itens.

    Busca case-insensitive e com TRIM nas pontas ('req-20260802-001 ' acha
    'REQ-20260802-001'): quem digita é o porteiro num terminal compartilhado, lendo o
    número de um papel. Devolve o mesmo shape de `listar_requisicoes` com a chave extra
    `itens` (de `listar_itens_requisicao`). Número vazio/None → None, sem consultar o
    banco — string vazia não pode casar com requisição nenhuma.

    v6.5.0 — com o número virando o inteiro `1..N`, entrada só de dígitos perde os zeros à
    esquerda ('0123' acha 123): quem copia de um papel escrito à mão não tem como saber
    quantos zeros o sistema guardou, e a busca não pode punir isso. O `str(int(...))`
    também normaliza '000' para '0', que simplesmente não acha nada — correto, porque
    número de requisição começa em 1. O formato antigo `REQ-…` continua aceito
    literalmente: os cartões já impressos não voltam para reimprimir."""
    numero = str(numero or "").strip()
    if not numero:
        return None
    if numero.isdigit():
        numero = str(int(numero))
    reqs = _consultar_requisicoes("WHERE UPPER(TRIM(r.numero_requisicao)) = UPPER(TRIM(?))", [numero])
    if not reqs:
        return None
    req = reqs[0]
    req["itens"] = listar_itens_requisicao(req["id"])
    return req


# v6.4.0 — requisição DEVOLVIDA ao requisitante: o gestor rejeitou e ela ainda não voltou.
#
# O predicado não compara datas de propósito. A primeira versão perguntava
# `reenviado_em > rejeitado_em`, e o teste do ciclo completo mostrou o furo: `data_hora`
# tem resolução de SEGUNDO, então rejeitar e reenviar no mesmo segundo empata a comparação
# e o pedido fica preso fora da fila. Como `rejeitar_requisicao` **sempre zera
# `reenviado_em`**, vale o invariante "reenviado_em não-nulo ⇒ o reenvio é posterior à
# última rejeição" — e a pergunta vira simplesmente "voltou ou não voltou", sem relógio
# nenhum no meio. O ciclo continua se repetindo quantas vezes for preciso.
#
# Nenhum ramo produz NULL (`IS NULL`/`IS NOT NULL` nunca são NULL), então o `NOT (...)` do
# outro lado é seguro para quem nunca foi rejeitado.
DEVOLVIDA_WHERE = "r.rejeitado_em IS NOT NULL AND r.reenviado_em IS NULL"


def buscar_requisicoes_por_emitente(nome, limit=50):
    """v6.4.0 — Consulta da Portaria pelo NOME de quem pediu, com os itens de cada uma.

    Quem chega na guarita sem o papel na mão sabe o próprio nome, não o número do pedido.
    Devolve o shape de `listar_requisicoes` com a chave extra `itens`, igual a
    `buscar_requisicao_por_numero` — a tela desenha o mesmo cartão nos dois caminhos.

    É um envelope sobre `listar_requisicoes(emitente=…)`, que já faz o casamento
    `UPPER(TRIM())`: escrever um segundo SELECT com o mesmo filtro daria duas versões da
    mesma busca para manter em sincronia.

    ⚠️ **Nome vazio devolve `[]` sem consultar.** `listar_requisicoes(emitente="")` cai no
    ramo "sem filtro" e devolve a base INTEIRA — na Portaria isso seria despejar as
    requisições de todos os funcionários para quem apertasse Consultar com o campo em
    branco. Mesma negativa por omissão de `buscar_requisicao_por_numero`."""
    nome = str(nome or "").strip()
    if not nome:
        return []
    reqs = listar_requisicoes(limit=limit, emitente=nome)
    for req in reqs:
        req["itens"] = listar_itens_requisicao(req["id"])
    return reqs


def _clausulas_aprovacao(so_abertas, apenas_aprovadas, apenas_rejeitadas=False):
    """v6.3.0 — Recorte comum às duas filas de aprovação (por setor e consolidada).

    Só o `WHERE` inicial difere entre elas; status e metade aprovada/não aprovada são a
    mesma regra, e uma cópia num dos lados faria a fila do gestor e a do almoxarife
    divergirem em silêncio — o pedido some de uma e continua na outra.

    v6.4.0 — as filas passam a ter TRÊS metades, não duas: aguardando, já aprovadas e
    **devolvidas ao requisitante**. Quem foi rejeitado sai de "aguardando" (senão o gestor
    reveria para sempre o pedido que ele mesmo devolveu) e volta assim que o requisitante
    reenviar. A regra mora aqui, uma vez só, pelo mesmo motivo da v6.3.0."""
    partes = []
    if so_abertas:
        partes.append("AND r.status IN ('Aberta','Parcial')")
    if apenas_rejeitadas:
        partes.append("AND r.aprovado_por IS NULL")
        partes.append(f"AND ({DEVOLVIDA_WHERE})")
    elif apenas_aprovadas:
        partes.append("AND r.aprovado_por IS NOT NULL")
    else:
        partes.append("AND r.aprovado_por IS NULL")
        partes.append(f"AND NOT ({DEVOLVIDA_WHERE})")
    return partes


def listar_requisicoes_para_aprovacao(
    so_abertas=True, apenas_aprovadas=False, apenas_rejeitadas=False, limite=100
):
    """v6.3.0 — Fila CONSOLIDADA: tudo o que há para aprovar, de TODOS os setores.

    É a visão do almoxarife (admin), que não tem departamento cadastrado e precisa da fila
    inteira de uma vez — não de um setor por vez (pedido do Luis em 02/08/2026, ao testar a
    v6.2.0). O setor deixa de ser filtro e vira a informação principal da lista.

    **Função irmã de `listar_requisicoes_por_setor`, e não um valor especial dela, de
    propósito.** Lá, setor vazio devolve `[]` para negar por omissão: gestor sem
    departamento não pode virar administrador por acidente. Se "todos os setores" fosse um
    `setor=None` daquela função, um `usuario["departamento"]` faltando — exatamente o caso
    que a negativa existe para cobrir — passaria a entregar a empresa inteira. Aqui não há
    parâmetro de setor: chegar ao consolidado exige chamar esta função pelo nome.

    Demais parâmetros e shape idênticos aos da irmã, inclusive a ordem ASC (fila se atende
    pelo começo)."""
    filtro = " ".join(["WHERE 1=1", *_clausulas_aprovacao(so_abertas, apenas_aprovadas, apenas_rejeitadas)])
    return _consultar_requisicoes(filtro, [], ordem="r.data_hora ASC", limit=limite)


def listar_requisicoes_por_setor(
    setor, so_abertas=True, apenas_aprovadas=False, apenas_rejeitadas=False, limite=100
):
    """v6.2.0 — Requisições de um SETOR, para a tela "Aprovações do Setor" (Gestor).

    O filtro é igualdade simples de setor (case/trim insensível), decisão do Luis em
    02/08/2026: `requisicoes.setor` e `usuarios.departamento` são vocabulários distintos e
    a interseção é parcial, mas a criação pelo Requisitante já pré-preenche o setor com o
    departamento — o fluxo novo casa, e o legado de setor divergente fica de fora (a tela
    tem seletor de setor para alcançá-lo).

    - `so_abertas=True` → só 'Aberta'/'Parcial' (a fila de quem ainda pode ser aprovado);
      False → todos os status.
    - `apenas_aprovadas=True` → só `aprovado_por IS NOT NULL`; False → só `IS NULL`.
      As duas metades são telas diferentes ("aguardando" × "já aprovadas"), por isso o
      parâmetro não tem um estado "as duas".
    - Ordem ASC (mais antiga primeiro), como a fila do almoxarife: fila se atende pelo
      começo.

    `setor` vazio → lista vazia, sem consultar (nega por omissão: gestor sem departamento
    não pode acabar vendo o setor de todo mundo). Quem precisa de TODOS os setores chama
    `listar_requisicoes_para_aprovacao` — esta função não tem valor que faça isso."""
    setor = str(setor or "").strip()
    if not setor:
        return []
    filtro = [
        "WHERE UPPER(TRIM(r.setor)) = UPPER(TRIM(?))",
        *_clausulas_aprovacao(so_abertas, apenas_aprovadas, apenas_rejeitadas),
    ]
    return _consultar_requisicoes(" ".join(filtro), [setor], ordem="r.data_hora ASC", limit=limite)


def listar_emitentes_requisicao():
    """v5.7.0 — Solicitantes que já abriram requisição, para o seletor da Visão do
    Solicitante. Sai do histórico real (`requisicoes.emitente`) e não de uma lista curada:
    o objetivo é simular "quem sou eu" entre pessoas que de fato existem na operação.
    Deduplica por forma normalizada (a primeira grafia vista vence) e ordena."""
    vistos = {}
    with transaction() as conn:
        rows = conn.execute(
            "SELECT emitente FROM requisicoes WHERE emitente IS NOT NULL AND TRIM(emitente) <> '' "
            "GROUP BY UPPER(TRIM(emitente)) ORDER BY MAX(data_hora) DESC"
        ).fetchall()
    for r in rows:
        v = str(r["emitente"]).strip()
        if v:
            vistos.setdefault(v.upper(), v)
    return sorted(vistos.values(), key=lambda s: s.upper())


def listar_itens_requisicao(req_id, conn=None):
    """v5.7.0 — `conn` opcional (padrão do projeto) para que a Requisição Padrão leia os
    itens que acabou de inserir DENTRO da própria transação, em vez de abrir uma segunda
    conexão com escrita pendente na primeira. `ORDER BY` explícito porque a Padrão percorre
    esta lista para baixar estoque e montar as faltas — ordem de exibição não pode depender
    do plano de consulta."""
    with transaction(conn) as c:
        rows = c.execute(
            """
            SELECT ir.*,i.part_number,i.nome_item,i.unidade,i.estoque_atual
            FROM itens_requisicao ir
            JOIN inventario i ON i.id=ir.item_id
            WHERE ir.requisicao_id=?
            ORDER BY ir.id
        """,
            (req_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def mapa_pn_por_requisicao():
    """Índice {requisicao_id: "pn1 pn2 ... nome1 nome2 ..."} (minúsculas) para busca
    textual por material/PN no Histórico de Requisições (v4.3.0). Uma única query com
    GROUP_CONCAT, evitando o N+1 de chamar listar_itens_requisicao por requisição."""
    with transaction() as conn:
        rows = conn.execute("""
            SELECT ir.requisicao_id            AS rid,
                   GROUP_CONCAT(i.part_number, ' ') AS pns,
                   GROUP_CONCAT(i.nome_item, ' ')   AS nomes
            FROM itens_requisicao ir
            JOIN inventario i ON i.id = ir.item_id
            GROUP BY ir.requisicao_id
        """).fetchall()
    return {r["rid"]: f"{r['pns'] or ''} {r['nomes'] or ''}".lower() for r in rows}


# ══════════════════════════════════════════════════════════════════════════════
# COMPRAS (SC)
# ══════════════════════════════════════════════════════════════════════════════


def _saldo_status_item_sc(qtd_negociada, qtd_recebida):
    """(saldo_residual, status_item) de uma linha de `itens_sc`.

    v5.7.0 — `qtd_recebida` é SEMPRE o recebimento do MRO (`itens_sc.quantidade_recebida`),
    nunca o número do Protheus (`quantidade_recebida_protheus`): o saldo pendente do
    almoxarifado é o que foi conferido na doca, não o que o ERP declarou. Derivar o saldo do
    espelho faria o pendente saltar de volta a cada import, que era o defeito da v5.6.0."""
    negociada = qtd_negociada or 0
    recebida = qtd_recebida or 0
    saldo = max(negociada - recebida, 0)
    return saldo, ("Recebido" if saldo <= 0 else ("Parcial" if recebida > 0 else "Aberto"))


def _recebimento_mro_item_sc(conn, numero_sc, item_id):
    """Recebimento já gravado pelo MRO para o par (SC, item), ou `None` se a linha não existe.

    v5.7.0 — os importadores precisam desse valor ANTES de resolver o `sc_id` (o status da SC
    depende do saldo, e o saldo depende do recebimento), por isso a busca é pelo `numero_sc`."""
    if not numero_sc or not item_id:
        return None
    row = conn.execute(
        """
        SELECT isc.quantidade_recebida AS qtd
        FROM itens_sc isc JOIN solicitacoes_compra sc ON sc.id = isc.sc_id
        WHERE sc.numero_sc=? AND isc.item_id=?
    """,
        (numero_sc, item_id),
    ).fetchone()
    return None if row is None else (row["qtd"] or 0)


def criar_sc(numero_sc, data_abertura, itens, observacoes=""):
    if not itens:
        return False, "Adicione ao menos um item."
    try:
        with transaction() as conn:
            sc = conn.execute("SELECT id FROM solicitacoes_compra WHERE numero_sc=?", (numero_sc,)).fetchone()
            if sc:
                sc_id = sc["id"]
                conn.execute(
                    """
                    UPDATE solicitacoes_compra SET data_abertura=?, observacoes=?
                    WHERE id=?
                """,
                    (data_abertura, observacoes, sc_id),
                )
            else:
                cur = conn.execute(
                    """
                    INSERT INTO solicitacoes_compra (numero_sc,data_abertura,observacoes)
                    VALUES (?,?,?)
                """,
                    (numero_sc, data_abertura, observacoes),
                )
                sc_id = cur.lastrowid

            criados, atualizados = 0, 0
            for it in itens:
                qtd_solicitada = _to_float(it.get("quantidade_solicitada", 0))
                qtd_negociada = _to_float(it.get("quantidade_pedido", qtd_solicitada)) or qtd_solicitada
                qtd_recebida = _to_float(it.get("quantidade_recebida", 0))
                divergencia = 1 if abs(qtd_solicitada - qtd_negociada) > 0.0001 else 0
                existente = conn.execute(
                    "SELECT id, quantidade_recebida FROM itens_sc WHERE sc_id=? AND item_id=?",
                    (sc_id, it["item_id"]),
                ).fetchone()
                # v5.7.0 — só o MRO escreve `quantidade_recebida`. Em linha que já existe, o
                # número informado aqui é leitura do Protheus: vai para a coluna espelho e o
                # saldo continua saindo do recebimento do MRO. Em linha nova não há o que
                # preservar, então o valor inicializa as duas colunas.
                recebida_mro = (existente["quantidade_recebida"] or 0) if existente else qtd_recebida
                saldo, status_item = _saldo_status_item_sc(qtd_negociada, recebida_mro)
                dados = (
                    it.get("numero_po") or None,
                    qtd_solicitada,
                    qtd_recebida,
                    it.get("data_necessidade"),
                    it.get("observacao_item", ""),
                    qtd_negociada,
                    it.get("fornecedor_item") or None,
                    it.get("data_prev_nfe") or None,
                    saldo,
                    status_item,
                    divergencia,
                )
                if existente:
                    conn.execute(
                        """
                        UPDATE itens_sc SET
                            numero_po=?, quantidade_solicitada=?, quantidade_recebida_protheus=?,
                            data_necessidade=?, observacao_item=?, quantidade_pedido=?,
                            fornecedor_item=?, data_prev_nfe=?, saldo_residual=?,
                            status_item=?, divergencia_compra=?
                        WHERE id=?
                    """,
                        (*dados, existente["id"]),
                    )
                    atualizados += 1
                else:
                    # v5.6.0 — `origem` só no INSERT: item criado à mão nasce 'manual', mas
                    # editar por aqui um item que veio do Excel/API não reescreve a origem dele.
                    conn.execute(
                        """
                        INSERT INTO itens_sc
                            (sc_id,item_id,numero_po,quantidade_solicitada,quantidade_recebida_protheus,
                             data_necessidade,observacao_item,quantidade_pedido,fornecedor_item,
                             data_prev_nfe,saldo_residual,status_item,divergencia_compra,
                             quantidade_recebida,origem)
                        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    """,
                        (sc_id, it["item_id"], *dados, qtd_recebida, "manual"),
                    )
                    criados += 1
                conn.execute("UPDATE inventario SET ultima_sc_id=? WHERE id=?", (sc_id, it["item_id"]))
        return True, f"SC {numero_sc} salva. Itens criados: {criados}. Atualizados: {atualizados}."
    except sqlite3.IntegrityError:
        return False, f"SC '{numero_sc}' já existe."
    except Exception as e:
        return False, str(e)


def atualizar_sc(
    sc_id,
    data_aprovacao=None,
    numero_po=None,
    fornecedor=None,
    data_prev_entrega=None,
    status=None,
    observacoes=None,
    itens=None,
):
    """
    Atualiza uma SC com lógica inteligente de status e gestão segura de conexão.
    - Se PO e Fornecedor forem preenchidos -> Sugerir 'Pedido Emitido'
    - Se todos os itens estiverem recebidos -> Forçar 'Recebido'
    - Garante que a conexão seja sempre fechada para evitar 'database is locked'.
    """
    try:
        with transaction() as conn:
            campos, vals = [], []

            if status is None:
                sc_atual = conn.execute(
                    "SELECT status FROM solicitacoes_compra WHERE id=?", (sc_id,)
                ).fetchone()
                status_atual_db = sc_atual["status"] if sc_atual else "Aguardando Aprovação"
                tem_forn_geral = bool(fornecedor and str(fornecedor).strip())
                tem_po_geral = bool(numero_po and str(numero_po).strip())
                tem_po_item = False
                tem_forn_item = False
                if itens:
                    for it in itens:
                        if it.get("numero_po") and str(it.get("numero_po")).strip():
                            tem_po_item = True
                        if it.get("fornecedor_item") and str(it.get("fornecedor_item")).strip():
                            tem_forn_item = True
                if (tem_forn_geral or tem_forn_item) and (tem_po_geral or tem_po_item):
                    if status_atual_db not in ["Recebido", "Cancelado"]:
                        status = "Aguardando Entrega"
                elif data_aprovacao and status_atual_db == "Aguardando Aprovação":
                    status = "Em Cotação"
                else:
                    status = status_atual_db

            if data_aprovacao is not None:
                campos.append("data_aprovacao=?")
                vals.append(data_aprovacao)
            if numero_po is not None:
                campos.append("numero_po=?")
                vals.append(numero_po)
            if fornecedor is not None:
                campos.append("fornecedor=?")
                vals.append(fornecedor)
            if data_prev_entrega is not None:
                campos.append("data_prev_entrega=?")
                vals.append(data_prev_entrega)
            if status is not None:
                campos.append("status=?")
                vals.append(status)
            if observacoes is not None:
                campos.append("observacoes=?")
                vals.append(observacoes)

            if campos:
                vals.append(sc_id)
                conn.execute(f"UPDATE solicitacoes_compra SET {','.join(campos)} WHERE id=?", vals)

            if itens:
                for it in itens:
                    item_sc_id = it.get("item_sc_id") or it.get("id")
                    if not item_sc_id:
                        continue
                    qtd_solicitada = _to_float(it.get("quantidade_solicitada", 0))
                    qtd_negociada = _to_float(it.get("quantidade_pedido", qtd_solicitada)) or qtd_solicitada
                    # v5.7.0 — o saldo sai do recebimento GRAVADO, nunca do `quantidade_recebida`
                    # que veio no payload: a tela só devolve o número que leu, e derivar o saldo
                    # dele deixaria o pendente à mercê de qualquer chamador. A coluna em si já
                    # não era escrita aqui desde a v4.5.7 — agora o cálculo também não a usa.
                    row_rec = conn.execute(
                        "SELECT quantidade_recebida FROM itens_sc WHERE id=? AND sc_id=?",
                        (item_sc_id, sc_id),
                    ).fetchone()
                    saldo, status_item = _saldo_status_item_sc(
                        qtd_negociada, row_rec["quantidade_recebida"] if row_rec else 0
                    )
                    divergencia = 1 if abs(qtd_solicitada - qtd_negociada) > 0.0001 else 0
                    conn.execute(
                        """
                        UPDATE itens_sc SET
                            numero_po=?, quantidade_solicitada=?, quantidade_pedido=?,
                            fornecedor_item=?, data_prev_nfe=?, data_necessidade=?,
                            observacao_item=?, saldo_residual=?, status_item=?,
                            divergencia_compra=?
                        WHERE id=? AND sc_id=?
                    """,
                        (
                            it.get("numero_po") or None,
                            qtd_solicitada,
                            qtd_negociada,
                            it.get("fornecedor_item") or None,
                            it.get("data_prev_nfe") or None,
                            it.get("data_necessidade") or None,
                            it.get("observacao_item") or "",
                            saldo,
                            status_item,
                            divergencia,
                            item_sc_id,
                            sc_id,
                        ),
                    )

            pend = conn.execute(
                """
                SELECT COUNT(*) AS n FROM itens_sc
                WHERE sc_id=? AND COALESCE(saldo_residual, quantidade_solicitada-quantidade_recebida) > 0
            """,
                (sc_id,),
            ).fetchone()["n"]
            if pend == 0 and status != "Cancelado":
                conn.execute("UPDATE solicitacoes_compra SET status='Recebido' WHERE id=?", (sc_id,))
            elif pend > 0 and status == "Recebido":
                conn.execute("UPDATE solicitacoes_compra SET status='Parcial' WHERE id=?", (sc_id,))

        return True, "SC atualizada."
    except Exception as e:
        return False, str(e)


def _normalizar_txt(valor):
    if valor is None:
        return ""
    texto = str(valor).strip()
    texto = unicodedata.normalize("NFKD", texto)
    texto = "".join(ch for ch in texto if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", texto).lower()


def _normalizar_coluna(coluna):
    return _normalizar_txt(coluna).replace(".", " ").replace("/", " ").strip()


def _coluna(df, nomes):
    mapa = {_normalizar_coluna(c): c for c in df.columns}
    for nome in nomes:
        chave = _normalizar_coluna(nome)
        if chave in mapa:
            return mapa[chave]
    return None


def _valor(row, coluna, padrao=None):
    if not coluna:
        return padrao
    valor = row.get(coluna, padrao)
    try:
        if pd.isna(valor):
            return padrao
    except Exception:
        pass
    return valor


def _to_float(valor):
    if valor is None:
        return 0.0
    try:
        if pd.isna(valor):
            return 0.0
    except Exception:
        pass
    if isinstance(valor, (int, float)):
        return float(valor)
    texto = str(valor).strip()
    if not texto:
        return 0.0
    texto = texto.replace(".", "").replace(",", ".") if "," in texto else texto
    try:
        return float(texto)
    except ValueError:
        return 0.0


def _to_date_str(valor):
    if valor is None:
        return None
    try:
        if pd.isna(valor):
            return None
        dt = pd.to_datetime(valor, errors="coerce", dayfirst=True)
        if pd.isna(dt):
            return None
        return dt.strftime("%Y-%m-%d")
    except Exception:
        return None


def _status_sc_importado(status_protheus, saldo_residual):
    status_norm = _normalizar_txt(status_protheus)
    if "rejeit" in status_norm or "cancel" in status_norm:
        return "Cancelado"
    if saldo_residual <= 0:
        return "Recebido"
    if "pedido" in status_norm:
        return "Pedido Emitido"
    if "cot" in status_norm:
        return "Em Cota\u00e7\u00e3o"
    if "aprov" in status_norm or "rascunho" in status_norm:
        return "Aguardando Aprova\u00e7\u00e3o"
    return "Aguardando Aprova\u00e7\u00e3o"


def _tem_prioridade_critica(justificativa):
    texto = _normalizar_txt(justificativa)
    return any(palavra in texto for palavra in PALAVRAS_CRITICAS)


def _garantir_item_importado(conn, part_number, nome_item, descricao, prioridade_critica):
    item = conn.execute(
        "SELECT id, importancia FROM inventario WHERE part_number=?", (part_number,)
    ).fetchone()
    importancia = "Parada de Linha" if prioridade_critica else "Importante"
    if item:
        if prioridade_critica and item["importancia"] != "Parada de Linha":
            conn.execute(
                "UPDATE inventario SET importancia=?, data_atualizacao=? WHERE id=?",
                (importancia, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), item["id"]),
            )
        return item["id"]

    cur = conn.execute(
        """
        INSERT INTO inventario
            (part_number,nome_item,descricao,unidade,importancia,tipo_material,
             setor_responsavel,estoque_atual,estoque_minimo)
        VALUES (?,?,?,?,?,?,?,?,?)
    """,
        (
            part_number,
            nome_item or part_number,
            descricao or nome_item or "",
            "UN",
            importancia,
            "Spare Parts",
            "Improdutivo",
            0,
            0,
        ),
    )
    return cur.lastrowid


def importar_solicitacoes_protheus(arquivo_excel, nome_arquivo="Solicitacoes.xlsx"):
    df = pd.read_excel(arquivo_excel)
    if df.empty:
        return False, {"erro": "A planilha esta vazia."}

    colunas = {
        "numero_sc": _coluna(df, ["Numero da Solicitacao", "N\u00famero da Solicita\u00e7\u00e3o"]),
        "descricao_sc": _coluna(
            df, ["Descricao da Solicitacao", "Descri\u00e7\u00e3o da Solicita\u00e7\u00e3o"]
        ),
        "status": _coluna(df, ["Status"]),
        "justificativa": _coluna(df, ["Justificativa/Projeto", "Justificativa", "Projeto"]),
        "solicitante": _coluna(df, ["Solicitante"]),
        "produto": _coluna(df, ["Produto", "Partnumber", "Part Number"]),
        "descricao_item": _coluna(
            df, ["Descricao Detalhada", "Descri\u00e7\u00e3o Detalhada", "Nome do item"]
        ),
        "quantidade": _coluna(df, ["Quantidade"]),
        "data_necessidade": _coluna(df, ["Data Necessidade"]),
        "emissao": _coluna(df, ["Emissao", "Emiss\u00e3o"]),
        "aprovacao": _coluna(df, ["Aprovacao", "Aprova\u00e7\u00e3o"]),
        "pedido": _coluna(df, ["Pedido", "Numero PC", "N\u00famero PC"]),
        "quantidade_pedido": _coluna(df, ["Quantidade.1", "Quantidade 1"]),
        "fornecedor": _coluna(df, ["Nome Fantasia"]),
        "previsao_nfe": _coluna(df, ["Previsao NFe", "Previs\u00e3o NFe"]),
        "qtd_entregue": _coluna(df, ["Qtd.Entregue", "Qtd Entregue"]),
        "documento": _coluna(df, ["Documento"]),
        "quantidade_nfe": _coluna(df, ["Quantidade NFe"]),
        # v5.6.0 — mapeamento aditivo: este export nem sempre traz centro de custo. Se a
        # coluna não existir, `_coluna` devolve None e o COALESCE do UPDATE preserva o
        # valor que a ingestão do Relatório de SCs já tiver gravado.
        "centro_custo": _coluna(df, ["Centro Custo", "Centro de Custo", "CC", "C.Custo"]),
    }

    obrigatorias = ["numero_sc", "solicitante", "produto", "quantidade"]
    faltantes = [nome for nome in obrigatorias if not colunas[nome]]
    if faltantes:
        return False, {"erro": f"Colunas obrigatorias ausentes: {', '.join(faltantes)}"}

    agora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    hoje = datetime.now().date()
    stats = {
        "linhas_lidas": int(len(df)),
        "linhas_importadas": 0,
        "linhas_ignoradas": 0,
        "scs_criadas": 0,
        "scs_atualizadas": 0,
        "itens_criados": 0,
        "itens_atualizados": 0,
        "rupturas": 0,
        "divergencias": 0,
        "criticos": 0,
    }
    ignorados = []

    try:
        with transaction() as conn:
            solic_mro = _solicitantes_mro_norm(conn)
            for idx, row in df.iterrows():
                solicitante = str(_valor(row, colunas["solicitante"], "")).strip()
                if _normalizar_txt(solicitante) not in solic_mro:
                    stats["linhas_ignoradas"] += 1
                    if len(ignorados) < 10:
                        ignorados.append(
                            {
                                "linha": int(idx) + 2,
                                "motivo": "Solicitante fora do escopo",
                                "solicitante": solicitante,
                            }
                        )
                    continue

                numero_sc = str(_valor(row, colunas["numero_sc"], "")).strip()
                part_number = str(_valor(row, colunas["produto"], "")).strip()
                status_protheus = str(_valor(row, colunas["status"], "") or "").strip()

                # 🚫 Filtro 1: Ignorar Status "Rascunho" ou "Rejeitado"
                if _normalizar_txt(status_protheus) in ("rascunho", "rejeitado"):
                    stats["linhas_ignoradas"] += 1
                    if len(ignorados) < 10:
                        ignorados.append(
                            {
                                "linha": int(idx) + 2,
                                "motivo": "Status ignorado (Rascunho/Rejeitado)",
                                "status": status_protheus,
                            }
                        )
                    continue

                # 🚫 Filtro 2: Ignorar Produto "Generico"
                if _normalizar_txt(part_number) == "generico":
                    stats["linhas_ignoradas"] += 1
                    if len(ignorados) < 10:
                        ignorados.append(
                            {"linha": int(idx) + 2, "motivo": "Produto Genérico", "produto": part_number}
                        )
                    continue

                if not numero_sc or not part_number:
                    stats["linhas_ignoradas"] += 1
                    if len(ignorados) < 10:
                        ignorados.append({"linha": int(idx) + 2, "motivo": "SC ou produto vazio"})
                    continue

                descricao_item = str(_valor(row, colunas["descricao_item"], part_number)).strip()
                justificativa = str(_valor(row, colunas["justificativa"], "") or "").strip()
                # v5.6.0 — centro de custo (opcional neste export; None preserva o já gravado).
                centro_custo = str(_valor(row, colunas["centro_custo"], "") or "").strip()
                centro_custo = centro_custo if centro_custo and centro_custo != "-" else None
                qtd_sc = _to_float(_valor(row, colunas["quantidade"], 0))
                qtd_entregue = _to_float(_valor(row, colunas["qtd_entregue"], 0))
                qtd_pedido = _to_float(_valor(row, colunas["quantidade_pedido"], 0))
                qtd_nfe = _to_float(_valor(row, colunas["quantidade_nfe"], 0))
                qtd_negociada = qtd_pedido or qtd_sc
                prioridade_critica = _tem_prioridade_critica(justificativa)
                data_necessidade = _to_date_str(_valor(row, colunas["data_necessidade"], None))
                divergencia = bool(qtd_pedido and abs(qtd_sc - qtd_pedido) > 0.0001)
                # v5.7.0 — saldo/status/ruptura só são calculados depois de resolver o item_id,
                # porque agora dependem do recebimento do MRO e não mais de `qtd_entregue`.
                # status_protheus já foi extraído acima

                # 🚫 Filtro 3: Verificar se o Item (PN) já existe no Banco MRO
                item_existente = conn.execute(
                    "SELECT id, importancia FROM inventario WHERE part_number=?", (part_number,)
                ).fetchone()

                if not item_existente:
                    stats["linhas_ignoradas"] += 1
                    if len(ignorados) < 10:
                        ignorados.append(
                            {
                                "linha": int(idx) + 2,
                                "motivo": "Item não cadastrado no MRO DB",
                                "produto": part_number,
                                "descricao": descricao_item,
                            }
                        )
                    continue  # Pula para a próxima linha do Excel

                item_id = item_existente["id"]

                # v5.7.0 — fonte de verdade do recebimento é o MRO. `qtd_entregue` (Protheus)
                # passa a alimentar só a coluna espelho: quando a linha já existe, saldo, status
                # e ruptura saem de `itens_sc.quantidade_recebida`, então um recebimento parcial
                # conferido na doca sobrevive à reimportação. Linha nova não tem o que preservar
                # e o número do Protheus inicializa as duas colunas.
                recebida_mro = _recebimento_mro_item_sc(conn, numero_sc, item_id)
                if recebida_mro is None:
                    recebida_mro = qtd_entregue
                saldo_residual, status_item = _saldo_status_item_sc(qtd_negociada, recebida_mro)
                ruptura = bool(
                    data_necessidade
                    and saldo_residual > 0
                    and datetime.strptime(data_necessidade, "%Y-%m-%d").date() < hoje
                )

                # Opcional: Atualizar a importância se o Protheus indicar criticidade e o banco não tiver
                if prioridade_critica and item_existente["importancia"] != "Parada de Linha":
                    conn.execute(
                        "UPDATE inventario SET importancia=?, data_atualizacao=? WHERE id=?",
                        ("Parada de Linha", agora, item_id),
                    )

                status = _status_sc_importado(status_protheus, saldo_residual)
                numero_po = str(_valor(row, colunas["pedido"], "") or "").strip()
                fornecedor = str(_valor(row, colunas["fornecedor"], "") or "").strip()
                data_prev = _to_date_str(_valor(row, colunas["previsao_nfe"], None))
                data_abertura = _to_date_str(_valor(row, colunas["emissao"], None)) or hoje.strftime(
                    "%Y-%m-%d"
                )
                data_aprovacao = _to_date_str(_valor(row, colunas["aprovacao"], None))
                descricao_sc = str(_valor(row, colunas["descricao_sc"], "") or "").strip()

                antes_item = conn.execute(
                    "SELECT id FROM inventario WHERE part_number=?", (part_number,)
                ).fetchone()
                if antes_item:
                    stats["itens_atualizados"] += 1
                else:
                    stats["itens_criados"] += 1

                sc = conn.execute(
                    "SELECT id FROM solicitacoes_compra WHERE numero_sc=?", (numero_sc,)
                ).fetchone()
                if sc:
                    sc_id = sc["id"]
                    conn.execute(
                        """
                        UPDATE solicitacoes_compra SET
                            data_abertura=?, data_aprovacao=?, numero_po=?, fornecedor=?,
                            data_prev_entrega=?, status=?, observacoes=?, solicitante=?,
                            descricao_solicitacao=?, status_protheus=?, prioridade_critica=?,
                            origem_importacao=?, data_importacao=?,
                            centro_custo=COALESCE(?, centro_custo)
                        WHERE id=?
                    """,
                        (
                            data_abertura,
                            data_aprovacao,
                            numero_po or None,
                            fornecedor or None,
                            data_prev,
                            status,
                            justificativa,
                            solicitante,
                            descricao_sc,
                            status_protheus,
                            1 if prioridade_critica else 0,
                            nome_arquivo,
                            agora,
                            centro_custo,
                            sc_id,
                        ),
                    )
                    stats["scs_atualizadas"] += 1
                else:
                    cur = conn.execute(
                        """
                        INSERT INTO solicitacoes_compra
                            (numero_sc,data_abertura,data_aprovacao,numero_po,fornecedor,
                             data_prev_entrega,status,observacoes,solicitante,
                             descricao_solicitacao,status_protheus,prioridade_critica,
                             origem_importacao,data_importacao,centro_custo)
                        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    """,
                        (
                            numero_sc,
                            data_abertura,
                            data_aprovacao,
                            numero_po or None,
                            fornecedor or None,
                            data_prev,
                            status,
                            justificativa,
                            solicitante,
                            descricao_sc,
                            status_protheus,
                            1 if prioridade_critica else 0,
                            nome_arquivo,
                            agora,
                            centro_custo,
                        ),
                    )
                    sc_id = cur.lastrowid
                    stats["scs_criadas"] += 1

                item_sc = conn.execute(
                    """
                    SELECT id FROM itens_sc
                    WHERE sc_id=? AND item_id=?
                """,
                    (sc_id, item_id),
                ).fetchone()
                dados_item = (
                    numero_po or None,
                    qtd_sc,
                    qtd_entregue,
                    data_necessidade,
                    justificativa,
                    descricao_item,
                    qtd_negociada,
                    fornecedor or None,
                    data_prev,
                    str(_valor(row, colunas["documento"], "") or "").strip() or None,
                    qtd_nfe,
                    saldo_residual,
                    status_item,
                    1 if ruptura else 0,
                    1 if divergencia else 0,
                    agora,
                )
                if item_sc:
                    conn.execute(
                        """
                        UPDATE itens_sc SET
                            numero_po=?, quantidade_solicitada=?, quantidade_recebida_protheus=?,
                            data_necessidade=?, observacao_item=?, descricao_detalhada=?,
                            quantidade_pedido=?, fornecedor_item=?, data_prev_nfe=?,
                            documento_nf=?, quantidade_nfe=?, saldo_residual=?,
                            status_item=?, ruptura=?, divergencia_compra=?, ultima_importacao=?
                        WHERE id=?
                    """,
                        (*dados_item, item_sc["id"]),
                    )
                else:
                    conn.execute(
                        """
                        INSERT INTO itens_sc
                            (sc_id,item_id,numero_po,quantidade_solicitada,quantidade_recebida_protheus,
                             data_necessidade,observacao_item,descricao_detalhada,
                             quantidade_pedido,fornecedor_item,data_prev_nfe,documento_nf,
                             quantidade_nfe,saldo_residual,status_item,ruptura,divergencia_compra,
                             ultima_importacao,quantidade_recebida)
                        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    """,
                        (sc_id, item_id, *dados_item, qtd_entregue),
                    )

                conn.execute("UPDATE inventario SET ultima_sc_id=? WHERE id=?", (sc_id, item_id))
                stats["linhas_importadas"] += 1
                stats["rupturas"] += 1 if ruptura else 0
                stats["divergencias"] += 1 if divergencia else 0
                stats["criticos"] += 1 if prioridade_critica else 0

        stats["ignorados_amostra"] = ignorados
        return True, stats
    except Exception as e:
        return False, {"erro": str(e)}


def _ler_planilha_com_header(arquivo_excel, marcadores=("PN", "Part Number", "Partnumber", "Produto")):
    """Lê a 1ª aba detectando a linha de cabeçalho real.

    Algumas exportações trazem uma linha de título (ex.: '358itens') antes do
    cabeçalho. Procura nas primeiras linhas a que contém um dos marcadores (PN/Part
    Number) e a usa como cabeçalho. Levanta ValueError se não encontrar.
    """
    # Reposiciona o ponteiro (uploads do Streamlit podem ser lidos mais de uma vez).
    try:
        arquivo_excel.seek(0)
    except (AttributeError, ValueError):
        pass
    bruto = pd.read_excel(arquivo_excel, header=None)
    if bruto.empty:
        return bruto
    marcadores_norm = {_normalizar_txt(m) for m in marcadores}
    header_idx = None
    for i in range(min(len(bruto), 15)):
        celulas = {_normalizar_txt(v) for v in bruto.iloc[i].tolist()}
        if celulas & marcadores_norm:
            header_idx = i
            break
    if header_idx is None:
        raise ValueError("Cabeçalho com a coluna 'PN' não foi encontrado nas primeiras linhas da planilha.")
    df = bruto.iloc[header_idx + 1 :].copy()
    df.columns = [str(c).strip() if c is not None else "" for c in bruto.iloc[header_idx].tolist()]
    return df.reset_index(drop=True)


def _parse_lead_time_dias(valor):
    """Extrai um inteiro de dias de valores como '20 dias', '20', 20, 20.0."""
    if valor is None:
        return None
    if isinstance(valor, (int, float)):
        try:
            if pd.isna(valor):
                return None
        except Exception:
            pass
        return int(valor)
    m = re.search(r"\d+", str(valor))
    return int(m.group()) if m else None


def importar_inventario_neidson(arquivo_excel, nome_arquivo="Inventario.xlsx", dry_run=False):
    """Atualiza Tipo/Categoria, Mínimo, Máximo e Lead Time dos itens existentes com
    a base apurada pelo Sr. Neidson (Item 1 / v2.1.0).

    Regras:
    - Casa por part_number; **só atualiza** os 4 campos apurados (não toca estoque
      atual, nome, descrição etc.).
    - PNs não encontrados na base são **apenas relatados** (não cria itens novos).
    - Idempotente: rodar 2x produz o mesmo resultado.
    - dry_run=True apenas simula (nenhuma gravação), para pré-visualização na UI.
    - Em execução real, grava auditoria em `log_importacoes`.
    """
    try:
        df = _ler_planilha_com_header(arquivo_excel)
    except Exception as e:
        return False, {"erro": f"Falha ao ler a planilha: {e}"}
    if df.empty:
        return False, {"erro": "A planilha está vazia."}

    colunas = {
        "pn": _coluna(df, ["PN", "Part Number", "Partnumber", "Produto"]),
        "categoria": _coluna(df, ["Tipo / Categoria", "Tipo/Categoria", "Tipo", "Categoria"]),
        "minimo": _coluna(df, ["Mínimo (30 dias)", "Minimo (30 dias)", "Mínimo", "Minimo"]),
        "maximo": _coluna(
            df, ["Máximo ( 60 dias)", "Máximo (60 dias)", "Maximo (60 dias)", "Máximo", "Maximo"]
        ),
        "lead_time": _coluna(df, ["LEADTIME TOTAL", "Lead Time Total", "Leadtime", "Lead Time"]),
    }
    if not colunas["pn"]:
        return False, {"erro": "Coluna de Part Number (PN) não encontrada na planilha."}
    if not any(colunas[c] for c in ("categoria", "minimo", "maximo", "lead_time")):
        return False, {"erro": "Nenhuma coluna de dados (Tipo, Mínimo, Máximo, Lead Time) encontrada."}

    agora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    stats = {
        "linhas_lidas": int(len(df)),
        "atualizados": 0,
        "ignorados": 0,
        "pns_nao_encontrados": [],
        "pns_duplicados_planilha": [],
        "dry_run": bool(dry_run),
    }
    vistos = set()

    try:
        with transaction() as conn:
            for _, row in df.iterrows():
                pn = str(_valor(row, colunas["pn"], "") or "").strip()
                if not pn:
                    stats["ignorados"] += 1
                    continue
                if pn in vistos:
                    stats["pns_duplicados_planilha"].append(pn)
                vistos.add(pn)

                item = conn.execute("SELECT id FROM inventario WHERE part_number=?", (pn,)).fetchone()
                if not item:
                    stats["ignorados"] += 1
                    stats["pns_nao_encontrados"].append(pn)
                    continue

                sets, vals = [], []
                if colunas["categoria"]:
                    cat = _valor(row, colunas["categoria"], None)
                    cat = str(cat).strip() if cat is not None and str(cat).strip() else None
                    if cat:
                        sets.append("tipo_material=?")
                        vals.append(cat)
                if colunas["minimo"]:
                    sets.append("estoque_minimo=?")
                    vals.append(_to_float(_valor(row, colunas["minimo"], None)))
                if colunas["maximo"]:
                    sets.append("estoque_maximo=?")
                    vals.append(_to_float(_valor(row, colunas["maximo"], None)))
                if colunas["lead_time"]:
                    lt = _parse_lead_time_dias(_valor(row, colunas["lead_time"], None))
                    if lt is not None:
                        sets.append("lead_time_dias=?")
                        vals.append(lt)

                if not sets:
                    stats["ignorados"] += 1
                    continue

                if not dry_run:
                    sets.append("data_atualizacao=?")
                    vals.append(agora)
                    vals.append(item["id"])
                    conn.execute(f"UPDATE inventario SET {', '.join(sets)} WHERE id=?", vals)
                    _recalcular_ruptura_by_id(conn, item["id"])
                stats["atualizados"] += 1

            if not dry_run:
                detalhe = json.dumps(
                    {
                        "pns_nao_encontrados": stats["pns_nao_encontrados"],
                        "pns_duplicados_planilha": sorted(set(stats["pns_duplicados_planilha"])),
                    },
                    ensure_ascii=False,
                )
                conn.execute(
                    """INSERT INTO log_importacoes
                        (tipo, arquivo, data_hora, total_planilha, atualizados, ignorados, detalhe_json)
                       VALUES (?,?,?,?,?,?,?)""",
                    (
                        "inventario_neidson",
                        nome_arquivo,
                        agora,
                        stats["linhas_lidas"],
                        stats["atualizados"],
                        stats["ignorados"],
                        detalhe,
                    ),
                )
        stats["pns_duplicados_planilha"] = sorted(set(stats["pns_duplicados_planilha"]))
        return True, stats
    except Exception as e:
        return False, {"erro": str(e)}


def listar_itens_sc(sc_id):
    with transaction() as conn:
        rows = conn.execute(
            """
            SELECT isc.*, i.part_number, i.nome_item, i.unidade,
                   sc.data_abertura, sc.data_aprovacao,
                   COALESCE(isc.quantidade_pedido, isc.quantidade_solicitada) AS quantidade_negociada,
                   COALESCE(isc.saldo_residual, COALESCE(isc.quantidade_pedido, isc.quantidade_solicitada)-isc.quantidade_recebida) AS pendente,
                   (
                       SELECT MAX(m.data_hora) FROM movimentacoes m
                       WHERE m.sc_item_id=isc.id AND m.tipo='entrada'
                   ) AS ultima_data_recebimento
            FROM itens_sc isc
            JOIN inventario i ON i.id=isc.item_id
            JOIN solicitacoes_compra sc ON sc.id=isc.sc_id
            WHERE isc.sc_id=? ORDER BY isc.id
        """,
            (sc_id,),
        ).fetchall()

    hoje = datetime.now()
    resultado = []
    for r in rows:
        item = dict(r)
        data_referencia = item.get("data_aprovacao") or item.get("data_abertura")
        dias_atendimento = 0
        if data_referencia:
            try:
                for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
                    try:
                        dt_ref = datetime.strptime(data_referencia, fmt)
                        dias_atendimento = max((hoje - dt_ref).days, 0)
                        break
                    except ValueError:
                        continue
            except Exception:
                dias_atendimento = 0
        item["dias_atendimento"] = dias_atendimento
        resultado.append(item)
    return resultado


def registrar_recebimento_sc(
    sc_id,
    item_sc_id,
    qtd_recebida,
    centro_custo,
    solicitante,
    emitente,
    fornecedor,
    data_recebimento,
    obs_nf="",
):
    # DT-2: recebimento atomico via transaction(). Qualquer falha faz rollback total.
    try:
        with transaction() as conn:
            # (1) Validacao (somente leitura; retornos antecipados nao persistem nada)
            sc_item = conn.execute("SELECT * FROM itens_sc WHERE id=?", (item_sc_id,)).fetchone()
            if not sc_item:
                return False, "Item da SC nao encontrado."

            negociada = sc_item["quantidade_pedido"] or sc_item["quantidade_solicitada"] or 0
            pendente = sc_item["saldo_residual"]
            if pendente is None or pendente <= 0:
                pendente = max(negociada - (sc_item["quantidade_recebida"] or 0), 0)
            if qtd_recebida <= 0:
                return False, "Quantidade recebida deve ser maior que zero."
            if qtd_recebida > pendente:
                return False, f"Excede o pendente ({pendente})."

            item_id = sc_item["item_id"]
            nova_rec = (sc_item["quantidade_recebida"] or 0) + qtd_recebida
            novo_saldo = max(negociada - nova_rec, 0)
            status_item = "Recebido" if novo_saldo <= 0 else "Parcial"
            agora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            data_mov = (
                f"{data_recebimento} {datetime.now().strftime('%H:%M:%S')}"
                if data_recebimento and len(str(data_recebimento)) == 10
                else (data_recebimento or agora)
            )
            nf = (obs_nf or "").strip()

            # (2) Atualiza itens_sc
            conn.execute(
                """
                UPDATE itens_sc SET
                    quantidade_recebida=?, saldo_residual=?, status_item=?,
                    documento_nf=COALESCE(NULLIF(?, ''), documento_nf),
                    quantidade_nfe=?, fornecedor_item=COALESCE(NULLIF(?, ''), fornecedor_item),
                    ultima_importacao=?
                WHERE id=?
            """,
                (nova_rec, novo_saldo, status_item, nf, qtd_recebida, fornecedor or "", agora, item_sc_id),
            )

            # (3) Atualiza fornecedor da solicitacao
            conn.execute(
                """
                UPDATE solicitacoes_compra
                SET fornecedor=COALESCE(NULLIF(?, ''), fornecedor)
                WHERE id=?
            """,
                (fornecedor or "", sc_id),
            )

            # (4)+(5) Entrada de estoque INLINE na mesma transacao.
            # v2.9.0 — CONVERSÃO: `qtd_recebida` chega na UNIDADE DE COMPRA (consistente
            # com itens_sc.quantidade_pedido, gravada pela ingestão na UM do PO). O
            # ledger/estoque vive na UNIDADE DE ESTOQUE, então converte:
            #   incremento_estoque = qtd_recebida / fator_conversao.
            # itens_sc.quantidade_recebida (nova_rec) segue na UM de compra (item 2 acima).
            # fator=1 (os ~318 itens de UM única) → incremento == qtd_recebida (no-op).
            r_est = conn.execute(
                "SELECT estoque_atual, unidade, unidade_compra, fator_conversao FROM inventario WHERE id=?",
                (item_id,),
            ).fetchone()
            if not r_est:
                raise ValueError("Item nao encontrado no inventario.")
            _fator = r_est["fator_conversao"]
            fator = _fator if (_fator and _fator > 0) else 1
            incremento_estoque = qtd_recebida / fator
            novo_estoque = (r_est["estoque_atual"] or 0) + incremento_estoque
            obs_mov = f"NF: {nf}" if nf else "Recebimento SC"
            if fator != 1:
                _uc = r_est["unidade_compra"] or "?"
                _ue = r_est["unidade"] or "?"
                obs_mov += f" · convertido: {qtd_recebida:g} {_uc} ÷ {fator:g} = {incremento_estoque:g} {_ue}"
            conn.execute(
                """
                INSERT INTO movimentacoes
                    (item_id,tipo,quantidade,saldo_apos,data_hora,
                     centro_custo,setor,solicitante,emitente,observacao,sc_item_id,requisicao_id)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
            """,
                (
                    item_id,
                    "entrada",
                    incremento_estoque,
                    novo_estoque,
                    data_mov,
                    centro_custo,
                    "",
                    solicitante,
                    emitente,
                    obs_mov,
                    item_sc_id,
                    None,
                ),
            )
            conn.execute(
                "UPDATE inventario SET estoque_atual=?,data_atualizacao=? WHERE id=?",
                (novo_estoque, agora, item_id),
            )

            # (6) Recalcula ruptura + segurança (SUGESTÃO) reusando a função canônica.
            #     v3.3.0: NÃO sobrescreve mais o estoque_seguranca MANUAL do gestor — o
            #     bug antigo gravava aqui consumo×lead×1,5 (fracionário) na coluna manual,
            #     contaminando o parâmetro do gestor com "números quebrados".
            _recalcular_ruptura_by_id(conn, item_id)

            # (7) Atualiza status da SC
            pend = conn.execute(
                """
                SELECT COUNT(*) AS n FROM itens_sc
                WHERE sc_id=? AND COALESCE(saldo_residual, quantidade_solicitada-quantidade_recebida) > 0
            """,
                (sc_id,),
            ).fetchone()["n"]
            status_novo = "Recebido" if pend == 0 else "Parcial"
            conn.execute("UPDATE solicitacoes_compra SET status=? WHERE id=?", (status_novo, sc_id))

            # (8) Recalcula o Lead Time CALCULADO como sugestão (não sobrescreve o
            #     cadastrado / base do Neidson). v2.2.1.
            _recalcular_lead_time_calculado(conn, item_id)

        return True, f"Recebimento registrado. SC {'fechada' if pend == 0 else 'parcial'}."
    except Exception as e:
        return False, f"Erro ao registrar recebimento: {e}"


def listar_scs(apenas_abertas=True):
    filtro = (
        "WHERE COALESCE(isc.saldo_residual, isc.quantidade_solicitada-isc.quantidade_recebida) > 0 AND sc.status NOT IN ('Cancelado') "
        if apenas_abertas
        else " "
    )
    with transaction() as conn:
        rows = conn.execute(f"""
            SELECT sc.*,
            COUNT(isc.id) AS total_itens,
            SUM(isc.quantidade_solicitada) AS total_solicitado,
            SUM(COALESCE(isc.quantidade_pedido, isc.quantidade_solicitada)) AS total_negociado,
            SUM(isc.quantidade_recebida) AS total_recebido,
            SUM(COALESCE(isc.saldo_residual, COALESCE(isc.quantidade_pedido, isc.quantidade_solicitada)-isc.quantidade_recebida)) AS total_pendente,
            MIN(isc.data_necessidade) AS proxima_necessidade,
            GROUP_CONCAT(DISTINCT i.importancia) AS importancias_itens,
            GROUP_CONCAT(DISTINCT i.part_number) AS pns_itens
            FROM solicitacoes_compra sc
            LEFT JOIN itens_sc isc ON isc.sc_id=sc.id
            LEFT JOIN inventario i ON i.id=isc.item_id
            {filtro}
            GROUP BY sc.id ORDER BY sc.data_abertura DESC
        """).fetchall()
    resultado = [dict(r) for r in rows]

    def peso_criticidade(sc):
        importancias = sc.get("importancias_itens") or ""
        if "Parada de Linha" in importancias:
            return 1
        if "Importante" in importancias:
            return 2
        if "Admin" in importancias:
            return 3
        return 4

    try:
        resultado.sort(key=lambda x: (peso_criticidade(x), x.get("data_abertura") or ""))
    except Exception:
        pass
    return resultado


def buscar_scs_por_item(item_id, apenas_abertas=True):
    filtro = (
        "AND COALESCE(isc.saldo_residual, COALESCE(isc.quantidade_pedido, isc.quantidade_solicitada)-isc.quantidade_recebida) > 0 AND sc.status NOT IN ('Cancelado')"
        if apenas_abertas
        else ""
    )
    with transaction() as conn:
        rows = conn.execute(
            f"""
            SELECT sc.id, sc.numero_sc, sc.numero_po, sc.fornecedor, sc.status, sc.data_abertura,
                   isc.id AS item_sc_id, isc.numero_po AS po_item,
                   COALESCE(isc.fornecedor_item, sc.fornecedor) AS fornecedor_item,
                   isc.quantidade_solicitada,
                   COALESCE(isc.quantidade_pedido, isc.quantidade_solicitada) AS quantidade_negociada,
                   isc.quantidade_recebida, isc.quantidade_recebida_protheus,
                   COALESCE(isc.saldo_residual, COALESCE(isc.quantidade_pedido, isc.quantidade_solicitada)-isc.quantidade_recebida) AS pendente,
                   isc.data_necessidade, isc.data_prev_nfe, isc.documento_nf, isc.status_item,
                   isc.preco_unitario, isc.valor_total, isc.moeda
            FROM itens_sc isc JOIN solicitacoes_compra sc ON sc.id=isc.sc_id
            WHERE isc.item_id=? {filtro}
            ORDER BY sc.data_abertura DESC
        """,
            (item_id,),
        ).fetchall()
    return [dict(r) for r in rows]


# Campos editáveis de um pedido (linha de itens_sc) pelo kanban do Guarda-Chuva (v4.5.7).
# `quantidade_recebida` NÃO está aqui de propósito: só muda via registrar_recebimento_sc
# (ledger). Campos de texto vazios gravam NULL; quantidade_pedido é numérica.
_CAMPOS_PEDIDO_GC = {
    "numero_po": "texto",
    "fornecedor_item": "texto",
    "data_necessidade": "texto",
    "data_prev_nfe": "texto",
    "documento_nf": "texto",
    "observacao_item": "texto",
    "quantidade_pedido": "num",
}


def obter_pedido_sc(item_sc_id):
    """v4.5.7 — Um único pedido (linha de itens_sc) com os mesmos campos derivados de
    `buscar_scs_por_item` (pendente, quantidade_negociada, documento_nf, datas…), acrescido
    de PN/nome/unidade do item. Usado pelo dialog do kanban para reler valores FRESCOS do
    banco a cada render (essencial após um recebimento parcial dentro do mesmo dialog)."""
    if not item_sc_id:
        return None
    with transaction() as conn:
        r = conn.execute(
            """
            SELECT sc.id, sc.numero_sc, sc.numero_po, sc.fornecedor, sc.status, sc.data_abertura,
                   isc.id AS item_sc_id, isc.numero_po AS po_item,
                   COALESCE(isc.fornecedor_item, sc.fornecedor) AS fornecedor_item,
                   isc.quantidade_solicitada,
                   COALESCE(isc.quantidade_pedido, isc.quantidade_solicitada) AS quantidade_negociada,
                   isc.quantidade_recebida, isc.quantidade_recebida_protheus,
                   COALESCE(isc.saldo_residual, COALESCE(isc.quantidade_pedido, isc.quantidade_solicitada)-isc.quantidade_recebida) AS pendente,
                   isc.data_necessidade, isc.data_prev_nfe, isc.documento_nf, isc.status_item,
                   isc.observacao_item,
                   i.part_number, i.nome_item, i.unidade
            FROM itens_sc isc
            JOIN solicitacoes_compra sc ON sc.id=isc.sc_id
            JOIN inventario i ON i.id=isc.item_id
            WHERE isc.id=?
        """,
            (item_sc_id,),
        ).fetchone()
    return dict(r) if r else None


def atualizar_pedido_guarda_chuva(item_sc_id, campos):
    """v4.5.7 — Edita os METADADOS de um pedido (linha de itens_sc) a partir do kanban do
    Guarda-Chuva: Nº PO, fornecedor, Data necessidade, Data prev. entrega, NF (documento_nf),
    observação e quantidade negociada (quantidade_pedido). Recomputa saldo_residual/status_item
    a partir do quantidade_recebida EXISTENTE e sincroniza o status da SC-pai.

    NUNCA altera quantidade_recebida nem escreve em movimentacoes/inventario — o recebimento
    (Qtd entregue) passa exclusivamente por `registrar_recebimento_sc`, mantendo o ledger
    íntegro. Campo de texto vazio grava NULL (permite limpar a NF = 'voltar' o card de
    NF Emitida para Aguardando Entrega). `campos` traz só as chaves realmente editadas."""
    if not item_sc_id:
        return False, "Pedido inválido."
    try:
        with transaction() as conn:
            row = conn.execute("SELECT * FROM itens_sc WHERE id=?", (item_sc_id,)).fetchone()
            if not row:
                return False, "Pedido (item da SC) não encontrado."
            sc_id = row["sc_id"]

            set_cols, vals = [], []
            for chave, tipo in _CAMPOS_PEDIDO_GC.items():
                if chave not in campos:
                    continue
                bruto = campos[chave]
                if tipo == "num":
                    valor = _to_float(bruto)
                else:
                    valor = (str(bruto).strip() or None) if bruto is not None else None
                set_cols.append(f"{chave}=?")
                vals.append(valor)

            # Valores efetivos para recomputar saldo/status/divergência (usa o valor editado
            # de quantidade_pedido quando presente; caso contrário o já gravado).
            negociada = (
                _to_float(campos["quantidade_pedido"])
                if "quantidade_pedido" in campos
                else (row["quantidade_pedido"] or row["quantidade_solicitada"] or 0)
            )
            solicitada = row["quantidade_solicitada"] or 0
            saldo, status_item = _saldo_status_item_sc(negociada, row["quantidade_recebida"])
            divergencia = 1 if abs(solicitada - negociada) > 0.0001 else 0

            set_cols += ["saldo_residual=?", "status_item=?", "divergencia_compra=?"]
            vals += [saldo, status_item, divergencia]

            vals.append(item_sc_id)
            conn.execute(f"UPDATE itens_sc SET {','.join(set_cols)} WHERE id=?", vals)

            # Sincroniza o status da SC-pai (mesma regra de atualizar_sc), sem tocar 'Cancelado'.
            sc_status = conn.execute(
                "SELECT status FROM solicitacoes_compra WHERE id=?", (sc_id,)
            ).fetchone()["status"]
            pend = conn.execute(
                """
                SELECT COUNT(*) AS n FROM itens_sc
                WHERE sc_id=? AND COALESCE(saldo_residual,
                      COALESCE(quantidade_pedido, quantidade_solicitada)-quantidade_recebida) > 0
            """,
                (sc_id,),
            ).fetchone()["n"]
            if sc_status != "Cancelado":
                if pend == 0:
                    conn.execute("UPDATE solicitacoes_compra SET status='Recebido' WHERE id=?", (sc_id,))
                elif sc_status == "Recebido":
                    conn.execute("UPDATE solicitacoes_compra SET status='Parcial' WHERE id=?", (sc_id,))
        return True, "Pedido atualizado."
    except Exception as e:
        return False, str(e)


# ══════════════════════════════════════════════════════════════════════════════
# GUARDA-CHUVA MANUAL (v4.9.0) — controle de acordos de congelamento de preço por
# (produto + fornecedor), com entregas parciais. 100% MANUAL e desacoplado das SCs
# importadas (itens_sc): tabela própria `guarda_chuva`, estágio EXPLÍCITO/editável,
# saldo derivado (negociada − recebida). NÃO toca estoque/movimentacoes (é controle,
# não ledger). Ver database.py (CREATE TABLE guarda_chuva).
# ══════════════════════════════════════════════════════════════════════════════

GUARDA_CHUVA_ESTAGIOS = ("Pedido Colocado", "Aguardando Entrega", "NF Emitida", "Recebido")

# Campos editáveis de um acordo pelo kanban/dialog do Guarda-Chuva.
_CAMPOS_GUARDA_CHUVA = {
    "fornecedor_codigo": "texto",
    "fornecedor_nome": "texto",
    "qtd_negociada": "num",
    "qtd_recebida": "num",
    "preco_congelado": "num",
    "qtd_ideal_mes": "num",
    "estagio": "texto",
    "numero_po": "texto",
    "data_acordo": "texto",
    "validade": "texto",
    "observacao": "texto",
}


def criar_guarda_chuva(
    item_id,
    fornecedor_codigo,
    *,
    fornecedor_nome=None,
    qtd_negociada=0,
    preco_congelado=None,
    qtd_ideal_mes=None,
    numero_po=None,
    data_acordo=None,
    validade=None,
    observacao=None,
    estagio="Pedido Colocado",
):
    """Cria um acordo guarda-chuva (produto + código de fornecedor). Controle manual:
    não toca estoque/movimentacoes. Retorna (ok, id) ou (False, msg)."""
    if not item_id:
        return False, "Selecione um material."
    cod = str(fornecedor_codigo).strip() if fornecedor_codigo is not None else ""
    if not cod:
        return False, "Informe o código do fornecedor."
    if estagio not in GUARDA_CHUVA_ESTAGIOS:
        estagio = "Pedido Colocado"
    agora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        with transaction() as conn:
            cur = conn.execute(
                """INSERT INTO guarda_chuva
                   (item_id, fornecedor_codigo, fornecedor_nome, qtd_negociada, qtd_recebida,
                    preco_congelado, qtd_ideal_mes, estagio, numero_po, data_acordo, validade,
                    observacao, criado_em, atualizado_em)
                   VALUES (?,?,?,?,0,?,?,?,?,?,?,?,?,?)""",
                (
                    int(item_id),
                    cod,
                    (fornecedor_nome or None),
                    _to_float(qtd_negociada),
                    (_to_float(preco_congelado) if preco_congelado not in (None, "") else None),
                    (_to_float(qtd_ideal_mes) if qtd_ideal_mes not in (None, "") else None),
                    estagio,
                    (numero_po or None),
                    (data_acordo or None),
                    (validade or None),
                    (observacao or None),
                    agora,
                    agora,
                ),
            )
            return True, cur.lastrowid
    except Exception as e:
        return False, str(e)


def listar_guarda_chuva(item_id=None):
    """Acordos guarda-chuva (todos ou de um item), com PN/nome/unidade e `saldo_residual`
    derivado (qtd_negociada − qtd_recebida). Mais recentes primeiro."""
    filtro = "WHERE g.item_id=?" if item_id else ""
    params = (int(item_id),) if item_id else ()
    with transaction() as conn:
        rows = conn.execute(
            f"""
            SELECT g.*, i.part_number, i.nome_item, i.unidade,
                   (COALESCE(g.qtd_negociada,0) - COALESCE(g.qtd_recebida,0)) AS saldo_residual
            FROM guarda_chuva g JOIN inventario i ON i.id = g.item_id
            {filtro}
            ORDER BY g.atualizado_em DESC, g.id DESC
        """,
            params,
        ).fetchall()
    return [dict(r) for r in rows]


def obter_guarda_chuva(gc_id):
    """Um acordo guarda-chuva (fresco do banco) para o dialog de edição."""
    if not gc_id:
        return None
    with transaction() as conn:
        r = conn.execute(
            """
            SELECT g.*, i.part_number, i.nome_item, i.unidade,
                   (COALESCE(g.qtd_negociada,0) - COALESCE(g.qtd_recebida,0)) AS saldo_residual
            FROM guarda_chuva g JOIN inventario i ON i.id = g.item_id
            WHERE g.id=?
        """,
            (int(gc_id),),
        ).fetchone()
    return dict(r) if r else None


def atualizar_guarda_chuva(gc_id, campos):
    """Edita um acordo guarda-chuva (chaves em `_CAMPOS_GUARDA_CHUVA`). Controle manual:
    não mexe em estoque/movimentacoes. Se qtd_recebida ≥ qtd_negociada (>0), coerção do
    estágio para 'Recebido'. Retorna (ok, msg)."""
    if not gc_id:
        return False, "Acordo inválido."
    try:
        with transaction() as conn:
            row = conn.execute("SELECT * FROM guarda_chuva WHERE id=?", (int(gc_id),)).fetchone()
            if not row:
                return False, "Acordo não encontrado."
            set_cols, vals = [], []
            estagio_setado = False
            for chave, tipo in _CAMPOS_GUARDA_CHUVA.items():
                if chave not in campos:
                    continue
                bruto = campos[chave]
                if tipo == "num":
                    valor = _to_float(bruto) if bruto not in (None, "") else None
                else:
                    valor = (str(bruto).strip() or None) if bruto is not None else None
                if chave == "estagio":
                    if valor not in GUARDA_CHUVA_ESTAGIOS:
                        valor = row["estagio"]
                    estagio_setado = True
                set_cols.append(f"{chave}=?")
                vals.append(valor)
            if not set_cols:
                return True, "Nada para atualizar."
            # Coerência: recebeu tudo → 'Recebido' (só se o estágio não foi setado à mão).
            neg = (
                _to_float(campos["qtd_negociada"])
                if "qtd_negociada" in campos
                else (row["qtd_negociada"] or 0)
            )
            rec = (
                _to_float(campos["qtd_recebida"]) if "qtd_recebida" in campos else (row["qtd_recebida"] or 0)
            )
            if neg > 0 and rec >= neg and not estagio_setado:
                set_cols.append("estagio=?")
                vals.append("Recebido")
            set_cols.append("atualizado_em=?")
            vals.append(datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
            vals.append(int(gc_id))
            conn.execute(f"UPDATE guarda_chuva SET {','.join(set_cols)} WHERE id=?", vals)
        return True, "Acordo atualizado."
    except Exception as e:
        return False, str(e)


def registrar_recebimento_guarda_chuva(gc_id, qtd):
    """Recebimento parcial (MANUAL) de um acordo: acumula em qtd_recebida (limitado ao
    negociado) e, se zerar o saldo, move para 'Recebido'. NÃO toca estoque/movimentacoes.
    Retorna (ok, msg)."""
    if not gc_id:
        return False, "Acordo inválido."
    q = _to_float(qtd)
    if q <= 0:
        return False, "Quantidade a receber deve ser maior que zero."
    try:
        with transaction() as conn:
            row = conn.execute("SELECT * FROM guarda_chuva WHERE id=?", (int(gc_id),)).fetchone()
            if not row:
                return False, "Acordo não encontrado."
            neg = row["qtd_negociada"] or 0
            nova_rec = (row["qtd_recebida"] or 0) + q
            if neg > 0:
                nova_rec = min(nova_rec, neg)
            estagio = "Recebido" if (neg > 0 and nova_rec >= neg) else row["estagio"]
            conn.execute(
                "UPDATE guarda_chuva SET qtd_recebida=?, estagio=?, atualizado_em=? WHERE id=?",
                (nova_rec, estagio, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), int(gc_id)),
            )
        return True, f"Recebimento de {q:g} registrado."
    except Exception as e:
        return False, str(e)


def remover_guarda_chuva(gc_id):
    """Exclui um acordo guarda-chuva. Retorna (ok, msg)."""
    if not gc_id:
        return False, "Acordo inválido."
    try:
        with transaction() as conn:
            conn.execute("DELETE FROM guarda_chuva WHERE id=?", (int(gc_id),))
        return True, "Acordo removido."
    except Exception as e:
        return False, str(e)


def saldo_total_por_material(item_id):
    """'Saldo total de todos os fornecedores' do material: soma de (negociada − recebida),
    só saldos positivos, sobre TODOS os acordos guarda-chuva do item."""
    if not item_id:
        return 0.0
    total = sum(max(float(g.get("saldo_residual") or 0), 0.0) for g in listar_guarda_chuva(item_id))
    return round(total, 2)


def itens_com_sc_aberta(conn=None):
    """Conjunto de item_id que têm ao menos uma SC ABERTA (saldo residual > 0 e SC não
    Cancelada) — mesma definição de 'aberta' de listar_scs(apenas_abertas=True). Usado pelo
    Assistente (v3.10.0) para mostrar só material crítico que ainda NÃO virou SC."""
    with transaction(conn) as c:
        rows = c.execute("""
            SELECT DISTINCT isc.item_id
            FROM itens_sc isc JOIN solicitacoes_compra sc ON sc.id = isc.sc_id
            WHERE sc.status NOT IN ('Cancelado')
              AND COALESCE(isc.saldo_residual,
                           isc.quantidade_solicitada - isc.quantidade_recebida) > 0
              AND isc.item_id IS NOT NULL
        """).fetchall()
    return {r["item_id"] for r in rows}


def listar_recebimentos_sc(limit=300):
    """Recebimentos (entradas de estoque) vinculados a SC, mais recentes primeiro.
    v3.11.0: enriquecido com fornecedor, PO, unidade, qtd solicitada e saldo pendente
    para a Linha do Tempo detalhada."""
    with transaction() as conn:
        rows = conn.execute(
            """
            SELECT m.data_hora, sc.numero_sc, i.part_number, i.nome_item, i.unidade,
                   m.quantidade, isc.documento_nf, m.emitente, m.observacao,
                   COALESCE(isc.numero_po, sc.numero_po) AS numero_po,
                   COALESCE(isc.fornecedor_item, sc.fornecedor) AS fornecedor,
                   isc.quantidade_solicitada AS qtd_solicitada,
                   COALESCE(isc.saldo_residual,
                            isc.quantidade_solicitada - isc.quantidade_recebida) AS pendente,
                   sc.status AS status_sc
            FROM movimentacoes m
            JOIN itens_sc isc ON isc.id=m.sc_item_id
            JOIN solicitacoes_compra sc ON sc.id=isc.sc_id
            JOIN inventario i ON i.id=m.item_id
            WHERE m.tipo='entrada' AND m.sc_item_id IS NOT NULL
            ORDER BY m.data_hora DESC LIMIT ?
        """,
            (limit,),
        ).fetchall()
    return [dict(r) for r in rows]


def obter_dados_dashboard(limit_abc=10):
    """
    Retorna dados para o Dashboard:
    - Curva ABC das saídas do MÊS ANTERIOR.
    - KPIs de estoque atuais (Snapshot).
    """
    hoje = date.today()
    primeiro_dia_mes_atual = hoje.replace(day=1)
    ultimo_dia_mes_anterior = primeiro_dia_mes_atual - timedelta(days=1)
    primeiro_dia_mes_anterior = ultimo_dia_mes_anterior.replace(day=1)
    periodo_inicio = primeiro_dia_mes_anterior.strftime("%Y-%m-%d")
    periodo_fim = ultimo_dia_mes_anterior.strftime("%Y-%m-%d")

    abc_query = """
        SELECT
            i.part_number,
            i.nome_item,
            SUM(m.quantidade) as total_saida
        FROM movimentacoes m
        JOIN inventario i ON m.item_id = i.id
        WHERE m.tipo = 'saida'
          AND m.requisicao_id IS NOT NULL
          AND m.data_hora >= ?
          AND m.data_hora <= ? || ' 23:59:59'
        GROUP BY i.id
        ORDER BY total_saida DESC
        LIMIT ?
    """

    with transaction() as conn:
        try:
            abc_rows = conn.execute(abc_query, (periodo_inicio, periodo_fim, limit_abc)).fetchall()
        except Exception as e:
            logger.exception("Erro na query ABC: %s", e)
            abc_rows = []

        itens = conn.execute(
            f"""SELECT i.estoque_atual, i.estoque_minimo, i.data_inventario,
                   (SELECT COUNT(*) FROM movimentacoes m
                      WHERE m.item_id = i.id AND {SAIDA_REAL_WHERE}) AS qtd_requisicoes
                FROM inventario i"""
        ).fetchall()

    ok = atencao = comprar = inv_ok = sem_movimentacao = 0
    for r in itens:
        est = r["estoque_atual"] or 0
        mn = r["estoque_minimo"] or 0
        # v2.7.0: item sem consumo real fica em balde próprio e NÃO conta como
        # crítico/atenção/ok — coerente com o status "⚪ Sem Movimentação".
        if (r["qtd_requisicoes"] or 0) == 0:
            sem_movimentacao += 1
        else:
            status = calcular_status_inventario(est, mn, 0)
            if "COMPRAR" in status:
                comprar += 1
            elif "ATENÇÃO" in status:
                atencao += 1
            else:
                ok += 1
        if r["data_inventario"]:
            inv_ok += 1

    return {
        "abc": [dict(r) for r in abc_rows],
        "kpis": {
            "total": len(itens),
            "ok": ok,
            "atencao": atencao,
            "comprar": comprar,
            "sem_movimentacao": sem_movimentacao,
            "inv_ok": inv_ok,
            "periodo_abc": f"{periodo_inicio} a {periodo_fim}",
        },
    }


def atualizar_localizacao_e_inventariar(item_id, novo_local, nova_caixa, novo_local_2=None):
    """
    Atualiza a localização primária, a 2ª locação e a caixa/observação do item.
    Aceita valores vazios. v3.4.0: 2ª locação (`local_armazenagem_2`) — um 2º ponto de
    armazenagem do mesmo item, distinto do Ajuste Rápido de Movimentações.
    """
    agora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    nova_caixa = nova_caixa or ""
    novo_local = novo_local or ""
    novo_local_2 = novo_local_2 or ""
    try:
        with transaction() as conn:
            conn.execute(
                "UPDATE inventario SET local_armazenagem=?, local_armazenagem_2=?, caixa_identificacao=?, data_inventario=?, data_atualizacao=? WHERE id=?",
                (novo_local, novo_local_2, nova_caixa, agora, agora, item_id),
            )
        return True, agora
    except Exception as e:
        return False, str(e)


# ══════════════════════════════════════════════════════════════════════════════
# EXPORTAÇÃO
# ══════════════════════════════════════════════════════════════════════════════


def exportar_inventario_df():
    itens = listar_inventario()
    if not itens:
        return pd.DataFrame()

    # v2.2.1: enriquece com giro / tempo em estoque (calculado sob demanda a partir
    # dos snapshots). Uma conexão compartilhada evita 1 transação por item.
    # v2.3.0: + valoração (preço/valor em estoque/valor consumido) e classe ABC-valor.
    with transaction() as conn:
        classe_abc = {x["item_id"]: x["classe"] for x in obter_abc_valor(conn=conn)}
        for it in itens:
            g = calcular_giro(it["id"], conn=conn)
            it["giro_anual"] = g["giro_anual"]
            it["tempo_medio_dias"] = g["tempo_medio_dias"]
            preco, origem, _moeda = _preco_valoracao(conn, it["id"])
            it["preco_ref"] = round(preco, 2)
            it["preco_origem"] = origem or "—"
            it["valor_estoque"] = round(float(it.get("estoque_atual", 0) or 0) * preco, 2)
            # v3.1.0: Valor Consumido passou de janela fixa de 90d para YTD (Year to
            # Date — desde 01/01 do ano corrente), a pedido do PO.
            vc = calcular_valor_consumido(it["id"], dias=dias_ytd(), conn=conn)
            it["valor_consumido_ytd"] = vc["valor"]
            it["classe_abc_valor"] = classe_abc.get(it["id"], "—")
            # v2.7.0: coluna de transparência de consumo real. "Sem movimentação"
            # quando nunca houve requisição; senão "N req · últ. dd/mm".
            if it.get("sem_movimentacao"):
                it["movimentacao"] = "Sem movimentação"
            else:
                ult = it.get("ultima_requisicao_data")
                ult_txt = f" · últ. {ult[8:10]}/{ult[5:7]}" if ult else ""
                it["movimentacao"] = f"{it.get('qtd_requisicoes', 0)} req{ult_txt}"

    # v2.0.2 / v2.2.1: estrutura de exportação
    colunas = [
        "part_number",
        "nome_item",
        "descricao",
        "unidade",
        "importancia",
        "tipo_material",
        "local_armazenagem",
        "estoque_atual",
        "estoque_minimo",
        "estoque_maximo",
        "estoque_em_transito",
        "dias_cobertura",
        "consumo_medio_diario",
        "consumo_30d",
        "consumo_60d",
        "consumo_90d",
        "tendencia_label",
        "tendencia_pct",
        "movimentacao",
        "lead_time_dias",
        "lead_time_calculado",
        "lead_time_calculado_origem",
        "giro_anual",
        "tempo_medio_dias",
        "previsao_ruptura_dias",
        "preco_ref",
        "preco_origem",
        "valor_estoque",
        "valor_consumido_ytd",
        "classe_abc_valor",
        "padrao_demanda",
        "classe_xyz",
        "sc_numero",
        "status_material",
        "status_sc",
        "data_inventario",
        "caixa_identificacao",  # Campo reutilizado para Obs Operacional
    ]

    df = pd.DataFrame(itens)[[c for c in colunas if c in pd.DataFrame(itens).columns]]

    # Renomear para exportação clara e operacional
    # Mapeamento seguro: se a coluna existir, renomeia.
    rename_map = {
        "part_number": "PN",
        "nome_item": "Nome",
        "descricao": "Descrição",
        "unidade": "UN",
        "importancia": "Importância",
        "tipo_material": "Tipo",
        "local_armazenagem": "Local",
        "estoque_atual": "Estoque Atual",
        "estoque_minimo": "Mínimo",
        "estoque_maximo": "Máximo",
        "estoque_seguranca": "Segurança",
        "estoque_em_transito": "Saldo Residual (Guarda-Chuva)",
        "dias_cobertura": "Cobertura(d)",
        "consumo_medio_diario": "Consumo/Dia",
        "consumo_30d": "Consumo 30d",
        "consumo_60d": "Consumo 60d",
        "consumo_90d": "Consumo 90d",
        "tendencia_label": "Tendência",
        "tendencia_pct": "Tendência %",
        "movimentacao": "Movimentação",
        "lead_time_dias": "Lead Time(d)",
        "lead_time_calculado": "Lead Time Calc(d)",
        "lead_time_calculado_origem": "LT Calc Origem",
        "giro_anual": "Giro(anual)",
        "tempo_medio_dias": "Tempo Estoque(d)",
        "previsao_ruptura_dias": "Ruptura(d)",
        "preco_ref": "Preço Ref",
        "preco_origem": "Origem Preço",
        "valor_estoque": "Valor em Estoque",
        "valor_consumido_ytd": "Valor Consumido(YTD)",
        "classe_abc_valor": "Classe ABC(valor)",
        "padrao_demanda": "Padrão Demanda",
        "classe_xyz": "Classe XYZ",
        "sc_numero": "Última SC",
        "status_material": "Status Material",
        "status_sc": "Status SC",
        "data_inventario": "Inventariado",
        "caixa_identificacao": "Obs. Inventário",  # NOVO NOME NA EXPORTAÇÃO
    }

    # Filtra apenas colunas que existem no DF antes de renomear
    cols_presentes = [c for c in colunas if c in df.columns]
    df = df[cols_presentes]

    # Aplica rename apenas nas colunas presentes
    df.rename(columns={k: v for k, v in rename_map.items() if k in df.columns}, inplace=True)

    return df


# ── v5.7.0 (CP4) — Relatório de Movimentações ────────────────────────────────
#
# Os templates que o código já montou dentro de `observacao` ao longo das versões. A
# coluna é string escrita à mão e empilha quatro semânticas em oito templates; aqui elas
# voltam a ser dado. Só entram como FALLBACK do legado — a FK sempre ganha, porque o
# texto mente: há linha cuja Observação é 'F61846' (que é o PO) e cujo `documento_nf`
# real é 169357.
# v6.5.0 — as duas grafias do número convivem POR DECISÃO. A renumeração reescreveu
# `requisicoes.numero_requisicao`, mas NÃO as 2.320 observações que citam o número antigo:
# o texto é histórico, a FK é a fonte da verdade (é a regra do bloco acima), e reescrever
# 2.320 strings para corrigir uma coluna de fallback seria trocar risco por nada. A
# alternativa `REQ-…` vem primeiro na ordem porque `\d+` sozinho não casaria com ela.
_RX_OBS_REQ = re.compile(r"\b(?:requisi[cç][aã]o|req)\s+(REQ-\d{8}-\d{3}|\d+)\b", re.I)
_RX_OBS_NF = re.compile(r"^\s*NF:\s*([^|·]+)", re.I)
_RX_OBS_VINCULO_SC = re.compile(r"\(\s*vinculado\s+[àa]\s+SC\s+\d+\s*\)", re.I)
_RX_OBS_AJUSTE = re.compile(r"^\s*(?:ajuste:|ajuste\s*[—-])\s*", re.I)


def _rotulo_documento(prefixo, valor):
    """'41494' → 'SC 41494'; 'SC-2026-001' → 'SC-2026-001' (não duplica o prefixo)."""
    valor = (valor or "").strip()
    if not valor:
        return ""
    return valor if valor.upper().startswith(prefixo) else f"{prefixo} {valor}"


def _limpar_residuo(texto):
    """Remove separadores órfãos deixados pela extração ('… | · ' → '…')."""
    texto = re.sub(r"[|·]\s*(?=[|·])", "", texto)
    texto = re.sub(r"\s{2,}", " ", texto)
    return texto.strip(" \t|·—-")


def _explodir_linha_movimentacao(m):
    """v5.7.0 (CP4) — desempacota UMA movimentação nas colunas do relatório.

    Função pura de propósito (recebe o dict de `listar_movimentacoes`, não abre conexão):
    é o coração do item 9 e precisa de teste próprio, sem banco no caminho.

    Regra única: **FK primeiro, texto só como fallback**. A FK cobre 100% das saídas por
    requisição (venham do fluxo Padrão ou do Digital — os dois gravam o mesmo ledger pelo
    mesmo helper) e 100% das entradas vinculadas a SC. O regex existe para as linhas
    anteriores às FKs, não para competir com elas.

    A Observação sai como RESÍDUO: o que sobra depois de extraído o que virou coluna. Nas
    1.887 saídas por requisição isso zera a coluna — o texto era só 'Req REQ-…', que agora
    é a coluna Nº Requisição."""
    obs = (m.get("observacao") or "").strip()
    residuo = obs

    numero_req = (m.get("numero_requisicao") or "").strip()
    achado = _RX_OBS_REQ.search(obs)
    if not numero_req and achado:
        numero_req = achado.group(1)
    if achado:
        residuo = _RX_OBS_REQ.sub("", residuo)

    nf = (m.get("documento_nf") or "").strip()
    achado_nf = _RX_OBS_NF.search(obs)
    if not nf and achado_nf:
        nf = achado_nf.group(1).strip()
    if achado_nf:
        residuo = _RX_OBS_NF.sub("", residuo)

    sc_po = " · ".join(
        p
        for p in (
            _rotulo_documento("SC", m.get("numero_sc")),
            _rotulo_documento("PO", m.get("numero_po")),
        )
        if p
    )
    if sc_po:
        residuo = _RX_OBS_VINCULO_SC.sub("", residuo)

    # O prefixo 'AJUSTE:' virou a coluna Categoria; o que vem depois dele é a nota real
    # do almoxarife ('MATERIAL PAGO SEM REQUISIÇÃO') e precisa sobreviver.
    residuo = _RX_OBS_AJUSTE.sub("", residuo)

    return {
        "Data/Hora": m.get("data_hora"),
        "PN": m.get("part_number"),
        "Item": m.get("nome_item"),
        "Categoria": categoria_movimentacao(m),
        "Tipo": m.get("tipo"),
        "Qtd": m.get("quantidade"),
        "Saldo Pós": m.get("saldo_apos"),
        "Centro de Custo": m.get("centro_custo") or "",
        "Setor": m.get("setor") or "",
        "Solicitante": m.get("solicitante") or "",
        "Responsável": m.get("emitente") or "",
        "Nº Requisição": numero_req,
        "Fluxo": (m.get("tipo_fluxo") or "").strip(),
        "NF": nf,
        "SC/PO": sc_po,
        "Motivo": (m.get("motivo") or "").strip(),
        "Observação": _limpar_residuo(residuo),
    }


COLUNAS_RELATORIO_MOVIMENTACOES = (
    "Data/Hora",
    "PN",
    "Item",
    "Categoria",
    "Tipo",
    "Qtd",
    "Saldo Pós",
    "Centro de Custo",
    "Setor",
    "Solicitante",
    "Responsável",
    "Nº Requisição",
    "Fluxo",
    "NF",
    "SC/PO",
    "Motivo",
    "Observação",
)


def exportar_movimentacoes_df(
    item_id=None,
    tipos_selecionados=None,
    categorias_selecionadas=None,
    data_inicio=None,
    data_fim=None,
):
    """Relatório de Movimentações — exportação larga, para rateio mensal e para auditoria.

    v5.7.0 (CP4, item 9 + decisão nº6) — duas mudanças de fundo:

    1. **Sem teto.** O antigo `limit=5000` cortava as movimentações mais ANTIGAS em
       silêncio (o ledger vem em ordem decrescente). No ritmo atual — 2.822 linhas em
       três meses — o corte começaria a apagar histórico em ~6 meses, sem nenhum aviso.
       Recorte agora é escolha explícita de quem exporta, via período.
    2. **Colunas explodidas.** Centro de custo, setor, solicitante, nº da requisição, seu
       fluxo, NF, PO e SC já existiam no banco e não saíam na planilha; quem precisasse
       rastrear tinha de ler a Observação com o olho. Ver `_explodir_linha_movimentacao`.

    Ajuste continua SEM Centro de Custo (decisão nº3): é correção do almoxarifado, não
    consumo de setor — célula vazia é a informação correta, não um dado faltando."""
    movs = listar_movimentacoes(item_id=item_id, limit=None, data_inicio=data_inicio, data_fim=data_fim)

    if not movs:
        return pd.DataFrame()

    # Filtro de tipo em memória (mesma lógica que você usa no app.py)
    if tipos_selecionados:
        movs = [m for m in movs if m["tipo"] in tipos_selecionados]

    # v4.3.0 — filtro por categoria derivada (Requisição, Perda de Material, etc.),
    # espelhando o filtro do Histórico na tela.
    if categorias_selecionadas:
        movs = [m for m in movs if categoria_movimentacao(m) in categorias_selecionadas]

    # B-01: se o filtro de tipo zerou o resultado, retorna DataFrame vazio
    # (evita ValueError ao reatribuir colunas a um DataFrame sem linhas).
    if not movs:
        return pd.DataFrame()

    return pd.DataFrame(
        [_explodir_linha_movimentacao(m) for m in movs],
        columns=list(COLUNAS_RELATORIO_MOVIMENTACOES),
    )


def _mediana(valores):
    """Mediana de uma lista de números (robusta a outliers)."""
    if not valores:
        return None
    vs = sorted(valores)
    n = len(vs)
    m = n // 2
    return vs[m] if n % 2 else (vs[m - 1] + vs[m]) / 2.0


def _gravar_lead_time_calculado(conn, item_id, deltas, origem):
    """Grava o Lead Time CALCULADO (mediana dos deltas em dias) como SUGESTÃO.

    v2.2.1: NUNCA toca `lead_time_dias` (base do Neidson permanece intacta). Filtra
    para 1 ≤ delta ≤ LEAD_TIME_MAX_DIAS (delta 0 = mesmo dia não é lead time útil e
    poluiria a mediana). Só grava se houver amostras válidas."""
    validos = [d for d in deltas if d is not None and 1 <= d <= LEAD_TIME_MAX_DIAS]
    if not validos:
        return
    calc = int(round(_mediana(validos)))
    conn.execute(
        """UPDATE inventario SET
             lead_time_calculado=?, lead_time_calculado_amostras=?, lead_time_calculado_origem=?
           WHERE id=?""",
        (calc, len(validos), origem, item_id),
    )


def _recalcular_lead_time_calculado(conn, item_id):
    """Lead Time real por RECEBIMENTO: mediana de (1ª entrada vinculada à SC −
    data_abertura da SC), por item. Grava em `lead_time_calculado` (sugestão).

    Substitui a antiga `_recalcular_lead_time_real`, que sobrescrevia
    `lead_time_dias` (violando a base do Neidson)."""
    try:
        rows = conn.execute(
            """
            SELECT sc.data_abertura AS abertura,
                   MIN(m.data_hora) AS chegada
            FROM itens_sc isc
            JOIN solicitacoes_compra sc ON sc.id = isc.sc_id
            JOIN movimentacoes m ON m.sc_item_id = isc.id AND m.tipo = 'entrada'
            WHERE isc.item_id = ? AND sc.data_abertura IS NOT NULL
            GROUP BY isc.id
        """,
            (item_id,),
        ).fetchall()

        deltas = []
        for row in rows:
            try:
                ab = pd.to_datetime(row["abertura"], errors="coerce")
                ch = pd.to_datetime(row["chegada"], errors="coerce")
                if pd.isna(ab) or pd.isna(ch):
                    continue
                deltas.append((ch - ab).days)
            except Exception:
                continue
        _gravar_lead_time_calculado(conn, item_id, deltas, "Recebimento")
    except Exception as e:
        logger.exception("Erro ao recalcular lead time (recebimento): %s", e)


def _amostras_consumo_30d(c, item_id=None):
    """{item_id: nº de saídas na janela de 30 d} — o "quantas amostras" da sugestão de
    Mín/Máx, irmão de `lead_time_calculado_amostras`.

    Conta por `tipo='saida'` (e não por `SAIDA_REAL_WHERE`) de propósito: é exatamente o
    recorte que `_consumo_janela` usa para calcular `consumo_medio_diario`, a base da
    sugestão. Contar por um filtro mais estrito diria "3 amostras" para um número tirado de
    5 saídas — o rótulo tem de descrever o dado que realmente entrou na conta."""
    where = "AND item_id=?" if item_id else ""
    params = (f"-{JANELA_CONSUMO_DIAS} days", item_id) if item_id else (f"-{JANELA_CONSUMO_DIAS} days",)
    rows = c.execute(
        f"""SELECT item_id, COUNT(*) AS n FROM movimentacoes
            WHERE tipo='saida' AND data_hora >= datetime('now', ?) {where}
            GROUP BY item_id""",
        params,
    ).fetchall()
    return {r["item_id"]: r["n"] for r in rows}


def recalcular_min_max_calculado(item_id=None, conn=None):
    """Recalcula e GRAVA a sugestão de Mín/Máx (v6.4.0). `item_id=None` → base inteira.

    Irmã de `_gravar_lead_time_calculado`: escreve só nas colunas `*_calculado` e jamais em
    `estoque_minimo`/`estoque_maximo` — a base do Sr. Neidson continua sendo alterada
    apenas por quem clica em "Usar calculado".

    Roda junto de `_recalcular_consumo` (a cada saída/devolução) e em
    `atualizar_item_inventario` quando o lead time muda, que são as DUAS entradas da
    fórmula. Assim a sugestão fica exatamente tão fresca quanto o `consumo_medio_diario`
    que a alimenta — nem mais nem menos.

    ⚠️ **`planejamento` é importado aqui dentro**, não no topo: ele importa
    `db_functions` (`listar_inventario`, `obter_fornecedores_por_item`), e um import no
    topo fecharia o ciclo. Mesmo recurso usado por `listar_inventario` com
    `classificar_todos`. A leitura é direta de `inventario` (e não via
    `listar_inventario`) porque a fórmula só precisa de consumo + lead time: passar pelo
    inventário completo arrastaria a curva ABC e a classificação de demanda da base
    inteira para gravar dois números."""
    from services import planejamento as P

    where, params = ("WHERE id=?", (item_id,)) if item_id else ("", ())
    with transaction(conn) as c:
        rows = c.execute(
            f"""SELECT id, consumo_medio_diario, lead_time_dias, lead_time_calculado,
                       lead_time_calculado_amostras, lead_time_calculado_origem
                FROM inventario {where}""",
            params,
        ).fetchall()
        amostras = _amostras_consumo_30d(c, item_id)
        sc7 = CS7.consumo_sc7_por_item(c, item_id)
        for r in rows:
            dados = dict(r)
            # v6.5.0 — o consumo por PEDIDO ATENDIDO entra na fórmula quando existe, e
            # `calcular_min_max_sugerido` o prefere ao `consumo_medio_diario`. `n_pedidos
            # >= 1` (garantido por quem devolveu o número) é a guarda equivalente ao
            # `amostras > 0` da janela de 30 d: houve compra real no período.
            info = sc7.get(r["id"])
            if info and info["consumo_mensal"] is not None:
                dados["consumo_sc7_diario"] = round(info["consumo_mensal"] / 30, 4)
                dados["consumo_sc7_rotulo"] = CS7.rotulo_consumo(info)
            # As amostras entram na fórmula, não só no rótulo: zero saídas na janela
            # significa `consumo_medio_diario` sem lastro recente (coluna persistida, só
            # recalculada quando o item se move) — e nesse caso não há sugestão a dar.
            sug = P.calcular_min_max_sugerido(dados, amostras=amostras.get(r["id"], 0))
            c.execute(
                """UPDATE inventario SET
                     minimo_calculado=?, maximo_calculado=?, min_max_amostras=?, min_max_origem=?
                   WHERE id=?""",
                (sug["minimo"], sug["maximo"], amostras.get(r["id"], 0), sug["origem"], r["id"]),
            )
    return len(rows)


def atualizar_item_inventario(item_id, dados_atualizados):
    """
    Atualiza um item no inventário.
    Nota: O status_material é calculado dinamicamente na leitura (listar_inventario),
    não sendo salvo fisicamente no banco nesta versão do schema.
    """
    try:
        with transaction() as conn:
            current_row = conn.execute("SELECT * FROM inventario WHERE id=?", (item_id,)).fetchone()
            if not current_row:
                return False, "Item não encontrado."
            fields = []
            values = []
            # part_number NÃO entra aqui: alterações de PN passam por alterar_part_number(),
            # que valida unicidade e registra histórico (Item 2 / v2.1.0).
            allowed_fields = [
                "nome_item",
                "descricao",
                "unidade",
                "tipo_material",
                "importancia",
                "estoque_minimo",
                "estoque_maximo",
                "lead_time_dias",
                "local_armazenagem",
                # v4.5.6 — 2ª locação agora também editável em Gerenciar Itens → Editar
                # (antes só era gravada pela Contagem Física do Saldo em Estoque).
                "local_armazenagem_2",
                "caixa_identificacao",
                "consumo_medio_diario",
                "setor_responsavel",
                # v2.2.0 — estoque de segurança agora é MANUAL (parâmetro do gestor)
                "estoque_seguranca",
                # v2.9.0 — curadoria da conversão de unidades (só grava o que o gestor
                # confirmar; não sobrescreve automaticamente).
                "unidade_compra",
                "fator_conversao",
                # v6.4.0 — o requisitante vê o saldo deste item? (default 1). As colunas
                # `minimo_calculado`/`maximo_calculado`/`min_max_*` NÃO entram nesta lista:
                # são derivadas de `recalcular_min_max_calculado`, não campos de formulário.
                "mostrar_saldo_requisitante",
            ]
            for key in allowed_fields:
                if key in dados_atualizados:
                    fields.append(f"{key}=?")
                    values.append(dados_atualizados[key])
            if not fields:
                return False, "Nenhum dado válido para atualizar."
            fields.append("data_atualizacao=?")
            values.append(datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
            values.append(item_id)
            conn.execute(f"UPDATE inventario SET {', '.join(fields)} WHERE id=?", values)
            # v6.4.0 — lead time é a outra metade da fórmula do Mín/Máx sugerido. Mudou
            # aqui, a sugestão tem de acompanhar na mesma transação: senão a tela mostraria
            # "mínimo calculado" pelo lead time antigo logo depois de o gestor corrigi-lo.
            if "lead_time_dias" in dados_atualizados:
                recalcular_min_max_calculado(item_id, conn)
        return True, "Item atualizado com sucesso!"
    except Exception as e:
        return False, str(e)


# ══════════════════════════════════════════════════════════════════════════════
# CONVERSÃO DE UNIDADES — sugestão da curadoria (v2.9.0)
# ══════════════════════════════════════════════════════════════════════════════


def mapear_unidade_compra_por_item(item_ids=None, conn=None):
    """{item_id: UM de compra} = a unidade mais frequente observada em
    `precos_historico.unidade` (capturada da ingestão SCM/SC7).

    Espelha o padrão de mapear_categoria_sc_por_item / mapear_cc_por_item (v2.8.0):
    mais frequente, com desempate pela linha de preço MAIS RECENTE. Itens sem UM
    observada não entram no mapa. Data-driven — não inventa; é a base da sugestão de
    conversão (a UM que o fornecedor realmente cobra)."""
    with transaction(conn) as c:
        rows = c.execute("""
            SELECT item_id, TRIM(unidade) AS unidade, COALESCE(data, '') AS d
            FROM precos_historico
            WHERE unidade IS NOT NULL AND TRIM(unidade) <> ''
        """).fetchall()
    filtro = set(item_ids) if item_ids is not None else None
    por_item = {}
    for r in rows:
        if filtro is not None and r["item_id"] not in filtro:
            continue
        por_item.setdefault(r["item_id"], []).append((r["unidade"], r["d"]))
    mapa = {}
    for iid, lst in por_item.items():
        cont = Counter(u for u, _ in lst)
        top = max(cont.values())
        candidatas = {u for u, n in cont.items() if n == top}
        # desempate: UM da linha de preço mais recente entre as candidatas
        mapa[iid] = max((d, u) for u, d in lst if u in candidatas)[1]
    return mapa


def sugerir_conversao(item, unidade_observada=None, conn=None):
    """Sugestão de conversão para a curadoria (Gerenciar Itens). NÃO persiste — só
    devolve o que o gestor confirma (assistente, não piloto automático).

    Devolve {unidade_compra_sugerida, fator_sugerido, origem}:
      - `fator_sugerido`: extraído por regex da DESCRIÇÃO (ex.: 'BOMBONA C/ 5,0 LT'
        → 5). Só vem preenchido quando há padrão claro; senão None (gestor preenche —
        o sistema não inventa fator).
      - `unidade_compra_sugerida`: a UM observada nos POs (SC7/SCM) quando difere da
        unidade de estoque; senão a própria unidade de estoque.
      - `origem`: rótulo de transparência de onde veio cada parte da sugestão.

    `item` é um dict de inventário (usa `id`, `nome_item`, `descricao`, `unidade`).
    `unidade_observada` pode ser passada pelo chamador (evita reconsultar em lote)
    ou é buscada aqui."""
    unidade_estoque = (item.get("unidade") or "").strip()
    if unidade_observada is None and item.get("id"):
        unidade_observada = mapear_unidade_compra_por_item([item["id"]], conn=conn).get(item["id"])
    unidade_observada = (unidade_observada or "").strip() or None

    # O padrão de embalagem ("C/ 5,0 LT", "CX C/ 4000PCS") mora no NOME do item na base
    # do Neidson (`descricao` guarda notas livres como "Consumo: 6 LT/dia"); varre os dois.
    texto = f"{item.get('nome_item') or ''} {item.get('descricao') or ''}"
    fator_desc = extrair_fator_embalagem(texto)

    # UM de compra sugerida: a observada nos POs quando diverge da de estoque.
    if unidade_observada and unidade_observada.upper() != unidade_estoque.upper():
        unidade_compra_sugerida = unidade_observada
    else:
        unidade_compra_sugerida = unidade_estoque or None

    origens = []
    if fator_desc:
        origens.append("fator da descrição (padrão “C/…”)")
    if unidade_observada:
        origens.append(f"UM observada nos POs: {unidade_observada}")
    origem = "; ".join(origens) if origens else "sem padrão claro — preencher manualmente"

    return {
        "unidade_compra_sugerida": unidade_compra_sugerida,
        "fator_sugerido": fator_desc,  # None quando não há padrão claro
        "origem": origem,
    }


# ══════════════════════════════════════════════════════════════════════════════
# ALTERAÇÃO DE PART NUMBER (Item 2 / v2.1.0)
# ══════════════════════════════════════════════════════════════════════════════


def alterar_part_number(item_id, novo_pn, motivo="", usuario=None):
    """Altera o Part Number de um item preservando TODO o histórico.

    Movimentações, SCs e requisições são ligadas por item_id (não pelo texto do PN),
    portanto a troca não perde rastreabilidade. A relação PN antigo↔novo fica
    registrada em part_numbers_historico, e o PN antigo continua localizável via
    buscar_item_por_pn().
    """
    novo_pn = (novo_pn or "").strip()
    if not novo_pn:
        return False, "Informe o novo Part Number."
    try:
        with transaction() as conn:
            atual = conn.execute("SELECT part_number FROM inventario WHERE id=?", (item_id,)).fetchone()
            if not atual:
                return False, "Item não encontrado."
            pn_antigo = atual["part_number"]
            if novo_pn == pn_antigo:
                return False, "O novo Part Number é igual ao atual."
            conflito = conn.execute(
                "SELECT id FROM inventario WHERE part_number=? AND id<>?", (novo_pn, item_id)
            ).fetchone()
            if conflito:
                return False, f"O Part Number '{novo_pn}' já pertence a outro item."
            agora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            conn.execute(
                "UPDATE inventario SET part_number=?, data_atualizacao=? WHERE id=?",
                (novo_pn, agora, item_id),
            )
            conn.execute(
                """INSERT INTO part_numbers_historico
                       (item_id, pn_antigo, pn_novo, data_hora, usuario, motivo)
                   VALUES (?,?,?,?,?,?)""",
                (item_id, pn_antigo, novo_pn, agora, (usuario or None), (motivo or None)),
            )
            _recalcular_ruptura_by_pn(conn, novo_pn)
        return True, f"Part Number alterado de '{pn_antigo}' para '{novo_pn}'."
    except sqlite3.IntegrityError:
        return False, f"O Part Number '{novo_pn}' já existe."
    except Exception as e:
        return False, str(e)


def listar_historico_part_number(item_id=None):
    """Histórico de alterações de PN (mais recentes primeiro). Se item_id=None,
    retorna de todos os itens, com o PN atual e nome para exibição."""
    with transaction() as conn:
        if item_id:
            rows = conn.execute(
                "SELECT * FROM part_numbers_historico WHERE item_id=? ORDER BY data_hora DESC", (item_id,)
            ).fetchall()
        else:
            rows = conn.execute(
                """SELECT h.*, i.part_number AS pn_atual, i.nome_item
                   FROM part_numbers_historico h
                   LEFT JOIN inventario i ON i.id = h.item_id
                   ORDER BY h.data_hora DESC"""
            ).fetchall()
    return [dict(r) for r in rows]


def buscar_item_por_pn(termo):
    """Localiza um item pelo PN atual OU por um PN antigo (histórico). Retorna dict ou None."""
    termo = (termo or "").strip()
    if not termo:
        return None
    with transaction() as conn:
        r = conn.execute("SELECT * FROM inventario WHERE part_number=?", (termo,)).fetchone()
        if r:
            return dict(r)
        h = conn.execute(
            "SELECT item_id FROM part_numbers_historico WHERE pn_antigo=? ORDER BY data_hora DESC LIMIT 1",
            (termo,),
        ).fetchone()
        if h:
            r = conn.execute("SELECT * FROM inventario WHERE id=?", (h["item_id"],)).fetchone()
            return dict(r) if r else None
    return None


# ══════════════════════════════════════════════════════════════════════════════
# FEEDBACK / SUGESTÕES (Item 3 / v2.1.0)
# ══════════════════════════════════════════════════════════════════════════════


def registrar_feedback(tipo, titulo, descricao="", autor=None, pagina_origem=None, prioridade=None):
    tipo = (tipo or "").strip()
    titulo = (titulo or "").strip()
    if not tipo:
        return False, "Selecione o tipo de feedback."
    if not titulo:
        return False, "Informe um título para o feedback."
    try:
        with transaction() as conn:
            conn.execute(
                """INSERT INTO feedbacks
                       (data_hora, tipo, titulo, descricao, autor, pagina_origem, status, prioridade)
                   VALUES (?,?,?,?,?,?, 'Novo', ?)""",
                (
                    datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    tipo,
                    titulo,
                    (descricao or None),
                    (autor or None),
                    (pagina_origem or None),
                    (prioridade or None),
                ),
            )
        return True, "Feedback registrado. Obrigado pela contribuição!"
    except Exception as e:
        return False, str(e)


def listar_feedbacks(tipo=None, status=None, limit=500):
    clausulas, params = [], []
    if tipo and tipo != "Todos":
        clausulas.append("tipo=?")
        params.append(tipo)
    if status and status != "Todos":
        clausulas.append("status=?")
        params.append(status)
    where = ("WHERE " + " AND ".join(clausulas)) if clausulas else ""
    params.append(limit)
    with transaction() as conn:
        rows = conn.execute(
            f"SELECT * FROM feedbacks {where} ORDER BY data_hora DESC LIMIT ?", params
        ).fetchall()
    return [dict(r) for r in rows]


def atualizar_feedback(feedback_id, status=None, prioridade=None, resposta=None):
    campos, vals = [], []
    if status is not None:
        campos.append("status=?")
        vals.append(status)
    if prioridade is not None:
        campos.append("prioridade=?")
        vals.append(prioridade)
    if resposta is not None:
        campos.append("resposta=?")
        vals.append(resposta)
    if not campos:
        return False, "Nada para atualizar."
    vals.append(feedback_id)
    try:
        with transaction() as conn:
            conn.execute(f"UPDATE feedbacks SET {', '.join(campos)} WHERE id=?", vals)
        return True, "Feedback atualizado."
    except Exception as e:
        return False, str(e)


def obter_analitico_movimentacoes(periodo="mensal"):
    """
    Retorna dados agregados para o analytics de movimentações.
    periodo: 'diario', 'semanal', 'mensal'
    """
    if periodo == "diario":
        fmt = "%Y-%m-%d"
        days = 30
    elif periodo == "semanal":
        fmt = "%Y-%W"
        days = 90
    else:
        fmt = "%Y-%m"
        days = 365

    with transaction() as conn:
        rows = conn.execute(
            f"""
            SELECT
                strftime('{fmt}', data_hora) as periodo,
                tipo,
                COUNT(*) as qtd_mov,
                SUM(quantidade) as vol_unidades
            FROM movimentacoes
            WHERE data_hora >= datetime('now', '-' || ? || ' days')
            GROUP BY periodo, tipo
            ORDER BY periodo DESC
        """,
            (days,),
        ).fetchall()

    # Organizar em DataFrame-friendly structure
    data = []
    for r in rows:
        data.append(
            {
                "periodo": r["periodo"],
                "tipo": r["tipo"],
                "qtd_mov": r["qtd_mov"],
                "vol_unidades": r["vol_unidades"],
            }
        )

    return (
        pd.DataFrame(data) if data else pd.DataFrame(columns=["periodo", "tipo", "qtd_mov", "vol_unidades"])
    )


def obter_analitico_divergencias(days=90):
    """
    Identifica itens com maior volume de ajustes manuais (entradas/saídas sem req/sc).
    Retorna DataFrame com PN, Nome, Qtd Ajustada e Nº de Ajustes.
    """
    with transaction() as conn:
        rows = conn.execute(
            """
            SELECT
                i.part_number,
                i.nome_item,
                COUNT(m.id) as qtd_ajustes,
                SUM(m.quantidade) as vol_ajustado_unidades
            FROM movimentacoes m
            JOIN inventario i ON i.id = m.item_id
            WHERE m.data_hora >= datetime('now', '-' || ? || ' days')
            AND (m.requisicao_id IS NULL AND m.sc_item_id IS NULL)
            GROUP BY m.item_id
            HAVING qtd_ajustes > 0
            ORDER BY qtd_ajustes DESC
            LIMIT 10
        """,
            (days,),
        ).fetchall()

    data = []
    for r in rows:
        data.append(
            {
                "part_number": r["part_number"],
                "nome_item": r["nome_item"],
                "qtd_ajustes": r["qtd_ajustes"],
                "vol_ajustado": r["vol_ajustado_unidades"],
            }
        )

    return (
        pd.DataFrame(data)
        if data
        else pd.DataFrame(columns=["part_number", "nome_item", "qtd_ajustes", "vol_ajustado"])
    )


def obter_analitico_rupturas(days=90):
    """
    Identifica itens com histórico de ruptura (estoque zerado durante requisição).
    Retorna DataFrame com PN, Nome, Qtd de Rupturas e Última Ocorrência.
    """
    with transaction() as conn:
        rows = conn.execute(
            """
            SELECT
                i.part_number,
                i.nome_item,
                COUNT(m.id) as qtd_rupturas,
                MAX(m.data_hora) as ultima_ocorrencia
            FROM movimentacoes m
            JOIN inventario i ON i.id = m.item_id
            WHERE m.tipo = 'saida'
            AND m.requisicao_id IS NOT NULL
            AND m.saldo_apos <= 0
            AND m.data_hora >= datetime('now', '-' || ? || ' days')
            GROUP BY m.item_id
            HAVING qtd_rupturas > 0
            ORDER BY qtd_rupturas DESC
            LIMIT 10
        """,
            (days,),
        ).fetchall()

    data = []
    for r in rows:
        data.append(
            {
                "part_number": r["part_number"],
                "nome_item": r["nome_item"],
                "qtd_rupturas": r["qtd_rupturas"],
                "ultima_ocorrencia": r["ultima_ocorrencia"],
            }
        )

    return (
        pd.DataFrame(data)
        if data
        else pd.DataFrame(columns=["part_number", "nome_item", "qtd_rupturas", "ultima_ocorrencia"])
    )


# ══════════════════════════════════════════════════════════════════════════════
# v2.2.0 — GUARDA-CHUVA & SNAPSHOTS DE ESTOQUE
# ══════════════════════════════════════════════════════════════════════════════


def calcular_guarda_chuva(item_id, conn=None):
    """Guarda-Chuva (termo do comprador Miguel): quantidade já negociada que ainda
    falta ser entregue = Σ saldo_residual dos itens em SCs ABERTAS do material.

    v2.2.0: soma TODAS as SCs abertas do item (a versão anterior considerava só a
    última SC via ultima_sc_id, subestimando o valor)."""
    with transaction(conn) as c:
        r = c.execute(
            """
            SELECT COALESCE(SUM(COALESCE(isc.saldo_residual, 0)), 0) AS gc
            FROM itens_sc isc
            JOIN solicitacoes_compra s ON s.id = isc.sc_id
            WHERE isc.item_id = ?
              AND s.status NOT IN ('Recebido', 'Cancelado')
        """,
            (item_id,),
        ).fetchone()
    return float(r["gc"] or 0)


def tirar_snapshot_estoque(conn=None, data=None):
    """Grava uma 'foto' diária do saldo de cada item (idempotente por dia).

    valor_estoque = estoque_atual × preco_referencia. Base para estoque médio,
    giro, tempo em estoque e evolução do valor imobilizado (v2.2.1+). Sem
    scheduler: chamado na 1ª abertura do app no dia e ao fim do import.
    Retorna o nº de fotos criadas (0 se já havia foto de hoje)."""
    dia = data or datetime.now().strftime("%Y-%m-%d")
    criados = 0
    with transaction(conn) as c:
        ja = c.execute("SELECT 1 FROM estoque_snapshots WHERE data=? LIMIT 1", (dia,)).fetchone()
        if ja:
            return 0
        rows = c.execute("SELECT id, estoque_atual, preco_referencia FROM inventario").fetchall()
        for r in rows:
            est = float(r["estoque_atual"] or 0)
            preco = float(r["preco_referencia"] or 0)
            c.execute(
                """
                INSERT OR IGNORE INTO estoque_snapshots
                    (item_id, data, estoque_atual, valor_estoque)
                VALUES (?,?,?,?)
            """,
                (r["id"], dia, est, est * preco),
            )
            criados += 1
        # Retenção: descarta fotos além da janela configurada.
        c.execute(
            "DELETE FROM estoque_snapshots WHERE data < date('now', ?)",
            (f"-{SNAPSHOT_RETENCAO_DIAS} days",),
        )
    return criados


def calcular_giro(item_id, dias=GIRO_JANELA_DIAS, conn=None):
    """Giro de estoque e tempo médio em estoque de um item.

    estoque_medio = média das fotos diárias (estoque_snapshots) na janela; fallback
    para o estoque atual se houver menos de 2 fotos. giro_anual = (saídas no período /
    estoque_medio) × (365/dias). tempo_medio_dias = 365/giro. Retorna também
    n_snapshots (maturidade). v2.2.1."""
    with transaction(conn) as c:
        snap = c.execute(
            """SELECT AVG(estoque_atual) AS media, COUNT(*) AS n
               FROM estoque_snapshots
               WHERE item_id=? AND data >= date('now', ?)""",
            (item_id, f"-{dias} days"),
        ).fetchone()
        n_snap = snap["n"] or 0
        if n_snap >= 2 and snap["media"] and snap["media"] > 0:
            estoque_medio = float(snap["media"])
        else:
            r = c.execute("SELECT estoque_atual FROM inventario WHERE id=?", (item_id,)).fetchone()
            estoque_medio = float(r["estoque_atual"] or 0) if r else 0.0

        saida = c.execute(
            """SELECT COALESCE(SUM(quantidade),0) AS total FROM movimentacoes
               WHERE item_id=? AND tipo='saida' AND data_hora >= datetime('now', ?)""",
            (item_id, f"-{dias} days"),
        ).fetchone()
        consumo_periodo = float(saida["total"] or 0)

    if estoque_medio > 0 and consumo_periodo > 0:
        giro_anual = (consumo_periodo / estoque_medio) * (365.0 / dias)
        tempo_medio = 365.0 / giro_anual if giro_anual > 0 else None
    else:
        giro_anual = 0.0
        tempo_medio = None

    return {
        "giro_anual": round(giro_anual, 2),
        "tempo_medio_dias": round(tempo_medio, 1) if tempo_medio is not None else None,
        "estoque_medio": round(estoque_medio, 2),
        "consumo_periodo": round(consumo_periodo, 2),
        "n_snapshots": n_snap,
        "janela_dias": dias,
    }


def obter_maturidade_dados(conn=None):
    """Maturidade do histórico para rotular indicadores de série.

    Retorna dias de histórico (desde a 1ª movimentação), a data de início e a
    contagem de fotos de estoque. v2.2.1 (transparência)."""
    with transaction(conn) as c:
        r = c.execute("SELECT MIN(data_hora) AS ini FROM movimentacoes").fetchone()
        n_snap = c.execute("SELECT COUNT(*) AS n FROM estoque_snapshots").fetchone()["n"]
    ini = r["ini"] if r else None
    dias = 0
    data_inicio = None
    if ini:
        dt = pd.to_datetime(ini, errors="coerce")
        if not pd.isna(dt):
            dias = max((datetime.now() - dt.to_pydatetime()).days, 0)
            data_inicio = dt.strftime("%Y-%m-%d")
    return {"dias": dias, "data_inicio": data_inicio, "n_snapshots": n_snap or 0}


# ══════════════════════════════════════════════════════════════════════════════
# v2.3.0 — PILAR FINANCEIRO / VALORAÇÃO
# Tudo derivado na leitura (sem coluna nova). Valoração é ESTIMATIVA rotulada;
# não é a base do Sr. Neidson (Mín/Máx/Lead Time/Categoria).
# ══════════════════════════════════════════════════════════════════════════════


def _preco_valoracao(c, item_id):
    """Preço unitário de valoração + origem + moeda (transparência). Usa
    preco_referencia (último preço SCM) se > 0; senão o preço mais recente de
    precos_historico (tipicamente SC7); senão (0.0, None, 'BRL'). v2.3.0.

    Recebe uma conexão/transação JÁ ABERTA (c) — reuso em varreduras por item."""
    r = c.execute("SELECT preco_referencia FROM inventario WHERE id=?", (item_id,)).fetchone()
    preco = float(r["preco_referencia"] or 0) if r else 0.0
    if preco > 0:
        return preco, "SCM", "BRL"  # preco_referencia é cache SCM (assumido BRL)
    ph = c.execute(
        """SELECT preco_unitario, origem, moeda FROM precos_historico
           WHERE item_id=? AND COALESCE(preco_unitario,0) > 0
           ORDER BY COALESCE(data, data_registro) DESC, id DESC LIMIT 1""",
        (item_id,),
    ).fetchone()
    if ph and ph["preco_unitario"]:
        return float(ph["preco_unitario"]), (ph["origem"] or "Histórico"), (ph["moeda"] or "BRL")
    return 0.0, None, "BRL"


def obter_valor_imobilizado(conn=None):
    """Valor total imobilizado = Σ(estoque_atual × preço de valoração), em BRL.

    Transparência: conta itens valorados, itens com estoque mas SEM preço
    (subestimam o total) e itens com moeda≠BRL (somados à parte, sem câmbio).
    v2.3.0."""
    total = 0.0
    valorados = sem_preco = nao_brl = 0
    total_nao_brl = 0.0
    with transaction(conn) as c:
        itens = c.execute("SELECT id, estoque_atual FROM inventario").fetchall()
        for r in itens:
            est = float(r["estoque_atual"] or 0)
            preco, _origem, moeda = _preco_valoracao(c, r["id"])
            if preco > 0:
                valorados += 1
                if moeda and moeda != "BRL":
                    nao_brl += 1
                    total_nao_brl += est * preco
                else:
                    total += est * preco
            elif est > 0:
                sem_preco += 1
    return {
        "total_brl": round(total, 2),
        "itens_valorados": valorados,
        "itens_sem_preco": sem_preco,
        "itens_nao_brl": nao_brl,
        "total_nao_brl": round(total_nao_brl, 2),
    }


def obter_evolucao_valor_imobilizado(dias=180, conn=None):
    """Série do valor imobilizado ao longo do tempo (Σ valor_estoque por dia das
    fotos diárias). Base p/ o gráfico de evolução (Diretoria). Retorna também
    n_snapshots (maturidade). v2.3.0."""
    with transaction(conn) as c:
        rows = c.execute(
            """SELECT data, SUM(COALESCE(valor_estoque,0)) AS valor
               FROM estoque_snapshots WHERE data >= date('now', ?)
               GROUP BY data ORDER BY data""",
            (f"-{dias} days",),
        ).fetchall()
        n = c.execute("SELECT COUNT(DISTINCT data) AS n FROM estoque_snapshots").fetchone()["n"]
    serie = [{"data": r["data"], "valor": round(float(r["valor"] or 0), 2)} for r in rows]
    return {"serie": serie, "n_snapshots": n or 0}


def obter_evolucao_preco(item_id, conn=None):
    """Série de preços de um item (precos_historico, SCM+SC7) ordenada por data —
    base do gráfico 'evolução de preço'. v2.3.0."""
    with transaction(conn) as c:
        rows = c.execute(
            """SELECT data, preco_unitario, moeda, origem, fornecedor, numero_po, numero_sc
               FROM precos_historico
               WHERE item_id=? AND COALESCE(preco_unitario,0) > 0
               ORDER BY COALESCE(data, data_registro), id""",
            (item_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def _fornecedores_master_norm(c):
    """Índice {nome_normalizado: dict do cadastro} de `fornecedores` (SA1), p/ casar
    o nome livre ("Nome Fantasia") gravado em precos_historico/itens_sc com o
    cadastro mestre e recuperar e-mail/telefone/contato para cotação. v2.4.0.

    Chaveia por nome_fantasia e, como fallback, por razao_social. Em colisão,
    prioriza a linha que TEM e-mail (o dado que interessa à cotação)."""
    idx = {}
    rows = c.execute(
        """SELECT codigo, loja, razao_social, nome_fantasia, cnpj, email,
                  telefone, contato, cond_pagto
           FROM fornecedores WHERE COALESCE(ativo, 1) = 1"""
    ).fetchall()
    for r in rows:
        d = dict(r)
        tem_email = "@" in (d.get("email") or "")
        for campo in (d.get("nome_fantasia"), d.get("razao_social")):
            chave = _normalizar_txt(campo)
            if not chave:
                continue
            atual = idx.get(chave)
            if atual is None or (tem_email and "@" not in (atual.get("email") or "")):
                idx[chave] = d
    return idx


def _nome_fornecedor_valido(nome):
    """True se `nome` parece um Nome Fantasia de verdade (tem ao menos uma letra).
    Descarta o lixo que a ingestão do SCM às vezes grava no lugar do fornecedor
    (ex.: '1.0'/'2.0' = nº da loja, 'None'), verificado nos dados reais. v2.4.0."""
    return bool(nome) and bool(re.search(r"[A-Za-zÀ-ÿ]", str(nome)))


def sincronizar_fornecedores_lista():
    """Semeia a lista 'fornecedor' (Configurações) com os fornecedores que realmente
    atenderam material MRO — os Nomes Fantasia que aparecem nas SCs importadas (no
    cabeçalho da SC e por item), e NÃO o cadastro SA1 inteiro (que traz milhares de
    fornecedores de toda a empresa). Idempotente: só adiciona os que faltam. Devolve
    (adicionados:int, total_mro:int). v3.3.0."""
    with transaction() as c:
        rows = c.execute("""
            SELECT DISTINCT nome FROM (
                SELECT fornecedor_item AS nome FROM itens_sc
                UNION
                SELECT fornecedor AS nome FROM solicitacoes_compra
            ) WHERE TRIM(COALESCE(nome, '')) <> ''
        """).fetchall()
    existentes = {_normalizar_txt(v) for v in (listar_valores("fornecedor") or [])}
    adicionados = 0
    total = 0
    for r in rows:
        nome = (r["nome"] or "").strip()
        if not _nome_fornecedor_valido(nome):
            continue
        total += 1
        chave = _normalizar_txt(nome)
        if chave in existentes:
            continue
        ok, _msg = adicionar_valor_lista("fornecedor", nome)
        if ok:
            adicionados += 1
            existentes.add(chave)
    return adicionados, total


def obter_fornecedores_por_item(item_id, conn=None):
    """Fornecedores de um item, "mastigados" para cotação (v2.4.0).

    Deriva na leitura (sem tabela materializada). O elo confiável nos dados reais
    é o Nº DO PEDIDO (numero_po):
      • `itens_sc.fornecedor_item` dá PO → fornecedor (Nome Fantasia real);
      • `precos_historico` dá PO → preço (SCM/SC7) e lead time (SC7);
      • o join por numero_po reconstrói preço + lead time por fornecedor.
    Nomes inválidos ('1.0', 'None' etc.) são descartados (_nome_fornecedor_valido).
    Enriquece com e-mail/telefone/contato do cadastro (SA1).

    Ordena por MENOR último preço (fornecedores sem preço vão ao fim) e marca
    `melhor=True` no primeiro com preço — sugestão explicável em 1 frase
    (`melhor_motivo`). Assistente, não piloto: o comprador decide. Retorna []
    quando não há fornecedor nomeado para o item."""

    def _br(dstr):
        try:
            return datetime.strptime(dstr, "%Y-%m-%d").strftime("%d/%m/%Y")
        except Exception:
            return dstr or ""

    with transaction(conn) as c:
        # 1) PO -> fornecedor + fornecedores nomeados vistos (itens_sc).
        po_forn = {}  # numero_po -> nome de exibição
        fornecedores_vistos = {}  # nome_norm -> nome de exibição
        pos_por_forn = {}  # nome_norm -> set(numero_po)
        for r in c.execute(
            """SELECT numero_po, fornecedor_item FROM itens_sc
               WHERE item_id=? AND fornecedor_item IS NOT NULL
                     AND TRIM(fornecedor_item) <> ''""",
            (item_id,),
        ).fetchall():
            nome = str(r["fornecedor_item"]).strip()
            if not _nome_fornecedor_valido(nome):
                continue
            chave = _normalizar_txt(nome)
            fornecedores_vistos.setdefault(chave, nome)
            po = str(r["numero_po"]).strip() if r["numero_po"] else ""
            if po:
                po_forn.setdefault(po, nome)
                pos_por_forn.setdefault(chave, set()).add(po)

        # 2) Preços por PO (SCM+SC7), mais recente primeiro — atribuídos pelo PO.
        precos = c.execute(
            """SELECT numero_po, preco_unitario, moeda, data
               FROM precos_historico
               WHERE item_id=? AND numero_po IS NOT NULL
                     AND COALESCE(preco_unitario,0) > 0
               ORDER BY COALESCE(data, data_registro) DESC, id DESC""",
            (item_id,),
        ).fetchall()

        # 3) Lead times observados (SC7) atribuídos ao fornecedor via numero_po.
        leads = c.execute(
            """SELECT numero_po, lead_time_dias FROM precos_historico
               WHERE item_id=? AND origem='SC7' AND lead_time_dias IS NOT NULL
                     AND numero_po IS NOT NULL""",
            (item_id,),
        ).fetchall()

        master = _fornecedores_master_norm(c)

    # Agregação por fornecedor (fora da transação — matemática pura).
    agg = {}  # nome_norm -> acumulador
    for chave, nome in fornecedores_vistos.items():
        agg[chave] = {
            "fornecedor": nome,
            "ultimo_preco": None,
            "ultima_data": None,
            "moeda": None,
            "preco_min": None,
            "preco_max": None,
            "_soma": 0.0,
            "_np": 0,
            "n_compras": len(pos_por_forn.get(chave, ())),
            "_leads": [],
        }

    for r in precos:
        nome = po_forn.get(str(r["numero_po"]).strip())
        if not nome:
            continue
        a = agg[_normalizar_txt(nome)]
        preco = float(r["preco_unitario"] or 0)
        if a["ultimo_preco"] is None:  # 1ª (mais recente, pois ordenado desc)
            a["ultimo_preco"] = preco
            a["ultima_data"] = r["data"]
            a["moeda"] = r["moeda"] or MOEDA_PADRAO
            a["preco_min"] = a["preco_max"] = preco
        else:
            a["preco_min"] = min(a["preco_min"], preco)
            a["preco_max"] = max(a["preco_max"], preco)
        a["_soma"] += preco
        a["_np"] += 1

    for r in leads:
        nome = po_forn.get(str(r["numero_po"]).strip())
        if nome:
            agg[_normalizar_txt(nome)]["_leads"].append(int(r["lead_time_dias"]))

    resultado = []
    for chave, a in agg.items():
        cad = master.get(chave)
        lt = _mediana(a["_leads"])
        tem_preco = a["ultimo_preco"] is not None
        resultado.append(
            {
                "fornecedor": a["fornecedor"],
                "ultimo_preco": round(a["ultimo_preco"], 2) if tem_preco else None,
                "moeda": a["moeda"] or MOEDA_PADRAO,
                "ultima_data": a["ultima_data"],
                "preco_min": round(a["preco_min"], 2) if tem_preco else None,
                "preco_max": round(a["preco_max"], 2) if tem_preco else None,
                "preco_medio": round(a["_soma"] / a["_np"], 2) if a["_np"] else None,
                "n_compras": a["n_compras"],
                "lead_time_fornecedor": int(round(lt)) if lt is not None else None,
                "lead_time_amostras": len(a["_leads"]),
                "codigo": cad["codigo"] if cad else None,
                "loja": cad["loja"] if cad else None,
                "email": ((cad["email"] or "").strip() or None) if cad else None,
                "telefone": ((cad["telefone"] or "").strip() or None) if cad else None,
                "contato": ((cad["contato"] or "").strip() or None) if cad else None,
                "cnpj": cad["cnpj"] if cad else None,
                "cond_pagto": cad["cond_pagto"] if cad else None,
                "no_cadastro": cad is not None,
                "melhor": False,
                "melhor_motivo": None,
            }
        )

    # Menor último preço primeiro; sem preço vai ao fim (ordenado por nome).
    resultado.sort(key=lambda x: (x["ultimo_preco"] is None, x["ultimo_preco"] or 0.0, x["fornecedor"]))
    if resultado and resultado[0]["ultimo_preco"] is not None:
        m = resultado[0]
        m["melhor"] = True
        data_fmt = _br(m["ultima_data"])
        m["melhor_motivo"] = (
            f"Menor último preço ({m['moeda']} {m['ultimo_preco']:.2f}"
            + (f" em {data_fmt}" if data_fmt else "")
            + ")"
        )
    return resultado


def dias_ytd(hoje=None):
    """Nº de dias decorridos no ano corrente até `hoje` (inclusive) — usado para
    calcular o Valor Consumido em janela YTD (Year to Date, v3.1.0: substituiu a
    janela fixa de 90 dias, a pedido do PO). Ex.: 08/01 → 8; 31/12 → 365 (ou 366
    em ano bissexto)."""
    hoje = hoje or date.today()
    return (hoje - date(hoje.year, 1, 1)).days + 1


def calcular_valor_consumido(item_id, dias=VALOR_CONSUMIDO_JANELA_DIAS, conn=None):
    """Valor consumido (ESTIMATIVA) = Σ(saídas na janela) × preço de valoração.

    Estimativa: usa o último preço (não o preço vigente em cada saída — as
    movimentações não guardam preço). Rótulo de origem acompanha. v2.3.0."""
    with transaction(conn) as c:
        preco, origem, moeda = _preco_valoracao(c, item_id)
        r = c.execute(
            """SELECT COALESCE(SUM(quantidade),0) AS qtd FROM movimentacoes
               WHERE item_id=? AND tipo='saida' AND data_hora >= datetime('now', ?)""",
            (item_id, f"-{dias} days"),
        ).fetchone()
    qtd = float(r["qtd"] or 0)
    return {
        "valor": round(qtd * preco, 2),
        "qtd": round(qtd, 2),
        "preco": preco,
        "origem": origem,
        "moeda": moeda,
        "janela_dias": dias,
    }


def obter_abc_valor(dias=VALOR_CONSUMIDO_JANELA_DIAS, limit=None, conn=None):
    """Curva ABC por VALOR consumido (qtd_saída × preço) na janela. Ordena
    decrescente, calcula % acumulada e classe A/B/C (limiares 80/95).

    v3.2.0: passou a usar CONSUMO REAL (`SAIDA_REAL_WHERE` = saída por requisição),
    coerente com consumo/giro/classificação/"quem consome". Antes usava `tipo='saida'`
    cru, que incluía AJUSTES FÍSICOS de inventário (contagens) como se fossem consumo —
    isso inflava a curva com valores absurdos (ex.: um ajuste de 99.999 un num alicate
    virava R$ 2,1 mi). v2.3.0."""
    with transaction(conn) as c:
        rows = c.execute(
            f"""SELECT i.id, i.part_number, i.nome_item,
                      COALESCE(SUM(m.quantidade),0) AS qtd
               FROM movimentacoes m JOIN inventario i ON i.id = m.item_id
               WHERE {SAIDA_REAL_WHERE} AND m.data_hora >= datetime('now', ?)
               GROUP BY i.id HAVING qtd > 0""",
            (f"-{dias} days",),
        ).fetchall()
        itens = []
        for r in rows:
            preco, origem, moeda = _preco_valoracao(c, r["id"])
            valor = float(r["qtd"]) * preco
            if valor <= 0:
                continue
            itens.append(
                {
                    "item_id": r["id"],
                    "part_number": r["part_number"],
                    "nome_item": r["nome_item"],
                    "qtd": round(float(r["qtd"]), 2),
                    "preco": preco,
                    "origem": origem,
                    "moeda": moeda,
                    "valor": round(valor, 2),
                }
            )
    itens.sort(key=lambda x: x["valor"], reverse=True)
    total = sum(x["valor"] for x in itens)
    acc = 0.0
    for x in itens:
        # Classe pela % acumulada ANTES do item (convenção padrão): o item que
        # cruza 80% ainda é A; o que cruza 95% ainda é B. Evita que o 2º maior
        # item caia em C quando um item domina e o acumulado "pula" a faixa.
        prev_pct = (acc / total * 100.0) if total > 0 else 0.0
        acc += x["valor"]
        x["pct_acumulado"] = round((acc / total * 100.0) if total > 0 else 0.0, 1)
        x["classe"] = "A" if prev_pct < ABC_LIMIAR_A else ("B" if prev_pct < ABC_LIMIAR_B else "C")
    if limit:
        itens = itens[:limit]
    return itens


# ══════════════════════════════════════════════════════════════════════════════
# v2.2.0 — INGESTÃO DO "RELATÓRIO DE SCs" (multi-aba)
# ══════════════════════════════════════════════════════════════════════════════


def _codigo_txt(valor):
    """Normaliza códigos numéricos vindos do Excel (ex.: 1.0 -> '1', '14901.0' ->
    '14901'); mantém textos como estão. Retorna '' para vazio/NaN."""
    if valor is None:
        return ""
    try:
        if pd.isna(valor):
            return ""
    except Exception:
        pass
    if isinstance(valor, float) and valor.is_integer():
        return str(int(valor))
    s = str(valor).strip()
    if s.endswith(".0") and s[:-2].isdigit():
        s = s[:-2]
    return s


def _log_importacao(conn, tipo, arquivo, total, atualizados, ignorados, detalhe):
    conn.execute(
        """
        INSERT INTO log_importacoes
            (tipo, arquivo, total_planilha, atualizados, ignorados, detalhe_json)
        VALUES (?,?,?,?,?,?)
    """,
        (
            tipo,
            arquivo,
            int(total),
            int(atualizados),
            int(ignorados),
            json.dumps(detalhe, ensure_ascii=False),
        ),
    )


def _sheet_df(xls, nome, header):
    try:
        return xls.parse(nome, header=header)
    except Exception as e:
        logger.warning("Falha ao ler aba %s: %s", nome, e)
        return None


def _upsert_item_sc_externo(
    conn,
    sc_id,
    part_number,
    descricao,
    quantidade,
    unidade,
    preco_unitario,
    valor_total,
    numero_po,
    data_necessidade,
    origem,
):
    """v5.1.0 (F2) — upsert idempotente em `itens_sc_externos` (item de SC cujo PN NÃO está
    no inventário MRO). Reusado pela ingestão do Excel (`origem='excel'`) e pelo sync da API
    (`origem='api_scm'`) — a fonte única evita duplicar o SQL. Chave: (sc_id, part_number)."""
    ex = conn.execute(
        "SELECT id FROM itens_sc_externos WHERE sc_id=? AND part_number=?", (sc_id, part_number)
    ).fetchone()
    if ex:
        conn.execute(
            """
            UPDATE itens_sc_externos SET
                descricao=COALESCE(?, descricao), quantidade=?, unidade=COALESCE(?, unidade),
                preco_unitario=CASE WHEN ?>0 THEN ? ELSE preco_unitario END,
                valor_total=CASE WHEN ?>0 THEN ? ELSE valor_total END,
                numero_po=COALESCE(?, numero_po),
                data_necessidade=COALESCE(?, data_necessidade), origem=?
            WHERE id=?
        """,
            (
                descricao or None,
                quantidade,
                unidade or None,
                preco_unitario,
                preco_unitario,
                valor_total,
                valor_total,
                numero_po or None,
                data_necessidade,
                origem,
                ex["id"],
            ),
        )
    else:
        conn.execute(
            """
            INSERT INTO itens_sc_externos
                (sc_id, part_number, descricao, quantidade, unidade, preco_unitario,
                 valor_total, numero_po, data_necessidade, origem)
            VALUES (?,?,?,?,?,?,?,?,?,?)
        """,
            (
                sc_id,
                part_number,
                descricao or None,
                quantidade,
                unidade or None,
                preco_unitario,
                valor_total,
                numero_po or None,
                data_necessidade,
                origem,
            ),
        )


def importar_relatorio_scs(arquivo_excel, nome_arquivo="Relatorio de SCs.xlsx"):
    """Roteador de ingestão do 'Relatório de SCs' (planilha diária dos compradores).

    Lê cada aba conhecida (SCM/SC7/FORNECEDORES/SCM USERS) com o cabeçalho correto
    e chama o ingestor dedicado. Upsert + histórico preservado (a planilha é
    cumulativa, então nada é apagado). Faz backup automático antes e tira o
    snapshot diário ao final. Retorna (ok, {aba: stats, ...})."""
    try:
        xls = pd.ExcelFile(arquivo_excel)
    except Exception as e:
        return False, {"erro": f"Não foi possível abrir a planilha: {e}"}

    try:
        from database import _backup_db

        _backup_db("relatorio-scs")
    except Exception:
        pass

    disponiveis = set(xls.sheet_names)
    resultados = {}
    ingestores = {
        "SCM": ingerir_scm,
        "SC7": ingerir_sc7_precos,
        "FORNECEDORES": ingerir_fornecedores,
        "SCM USERS": ingerir_scm_users,
    }
    df_sc7 = None
    for aba, func in ingestores.items():
        if aba in disponiveis:
            df = _sheet_df(xls, aba, RELATORIO_SCS_ABAS.get(aba, 0))
            if aba == "SC7":
                df_sc7 = df
            resultados[aba] = func(df, nome_arquivo)
        else:
            resultados[aba] = {"erro": "Aba ausente na planilha."}

    # v6.5.0 — a MESMA aba SC7 alimenta duas coisas diferentes: `ingerir_sc7_precos` tira
    # dela preço e lead time (só de PN cadastrado, só com preço), e `ingerir_sc7_consumo`
    # guarda a linha inteira (Entregue/Saldo) para o consumo por pedido. Reler a aba seria
    # desperdício; o `df` já está em memória.
    if df_sc7 is not None:
        resultados["SC7_CONSUMO"] = ingerir_sc7_consumo(df_sc7, nome_arquivo)

    try:
        resultados["_snapshot_criados"] = tirar_snapshot_estoque()
    except Exception as e:
        logger.warning("Falha ao tirar snapshot pós-import: %s", e)

    ok = any(isinstance(v, dict) and not v.get("erro") for v in resultados.values())
    return ok, resultados


def ingerir_scm(df, nome_arquivo="Relatorio de SCs.xlsx"):
    """Ingestor da aba SCM: upsert de SCs/itens_sc + captura de preço.
    Reusa o filtro de solicitantes (dinâmico) e a semântica do importador Protheus,
    mas com o mapeamento de colunas da aba SCM e as colunas de preço."""
    if df is None or df.empty:
        return {"erro": "Aba SCM vazia ou ausente."}
    colunas = {
        "numero_sc": _coluna(df, ["SC", "Numero da Solicitacao", "Número da Solicitação"]),
        "descricao_sc": _coluna(df, ["Descrição da Solicitação", "Descricao da Solicitacao"]),
        "status": _coluna(df, ["Status"]),
        "justificativa": _coluna(df, ["Justificativa/Projeto", "Justificativa", "Projeto"]),
        "solicitante": _coluna(df, ["Solicitante"]),
        "produto": _coluna(df, ["Produto", "Partnumber", "Part Number"]),
        "descricao_item": _coluna(df, ["Descrição", "Descricao", "Descricao Detalhada", "Nome do item"]),
        "quantidade": _coluna(df, ["Qty", "Quantidade"]),  # Qty = qtd da SC (aba SCM)
        "data_necessidade": _coluna(df, ["Data Necessidade"]),
        "emissao": _coluna(df, ["Emissão", "Emissao"]),
        "aprovacao": _coluna(df, ["Aprovação", "Aprovacao", "Data de aprovação"]),
        "pedido": _coluna(df, ["Pedido", "Numero PC", "Número PC"]),
        "qtd_pedido": _coluna(df, ["Quantidade"]),  # Quantidade = qtd do PO (aba SCM)
        "qtd_entregue": _coluna(df, ["Qtd.Entregue", "Qtd Entregue"]),
        # v3.5.0 — "Nome Fantasia" vinha com lixo ("1.0"/"2.0") neste export; o nome real
        # do fornecedor está em "Razão Social" / "Fornecedor". Prioriza os limpos.
        "fornecedor": _coluna(df, ["Razão Social", "Razao Social", "Fornecedor", "Nome Fantasia"]),
        "previsao_nfe": _coluna(df, ["Previsão NFe", "Previsao NFe"]),
        "documento": _coluna(df, ["Documento"]),
        # v3.5.0 — Dashboard de Comprador: comprador real, data do PO, saving, departamento.
        "comprador": _coluna(df, ["Comprador"]),
        "dt_emissao_po": _coluna(df, ["DT Emissão", "DT Emissao", "Dt Emissão", "Dt Emissao"]),
        "saving": _coluna(df, ["Saving"]),
        "departamento": _coluna(df, ["Departamento"]),
        "preco_unitario": _coluna(df, ["Prc Unitario", "Preco Unitario", "Preço Unitário"]),
        "valor_total": _coluna(df, ["Vlr.Total", "Valor Total", "Vlr Total"]),
        "moeda": _coluna(df, ["Moeda"]),
        "unidade": _coluna(df, ["Unidade", "UM", "U.M.", "Um"]),  # v2.9.0: UM de compra
        # v5.6.0 — a planilha sempre trouxe "Centro Custo", mas a coluna não era mapeada:
        # o dado era lido e descartado, e o campo chegava vazio no SCM Integrado.
        "centro_custo": _coluna(df, ["Centro Custo", "Centro de Custo", "CC", "C.Custo"]),
    }
    faltantes = [n for n in ("numero_sc", "solicitante", "produto", "quantidade") if not colunas[n]]
    if faltantes:
        return {"erro": f"Colunas obrigatórias ausentes na aba SCM: {', '.join(faltantes)}"}

    agora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    hoje = datetime.now().date()
    stats = {
        "linhas_lidas": int(len(df)),
        "linhas_importadas": 0,
        "linhas_ignoradas": 0,
        "scs_criadas": 0,
        "scs_atualizadas": 0,
        "precos_capturados": 0,
        "rupturas": 0,
        "divergencias": 0,
        "criticos": 0,
        "externos": 0,
    }
    ignorados = []
    try:
        with transaction() as conn:
            solic_mro = _solicitantes_mro_norm(conn)
            for idx, row in df.iterrows():
                solicitante = str(_valor(row, colunas["solicitante"], "") or "").strip()
                if _normalizar_txt(solicitante) not in solic_mro:
                    stats["linhas_ignoradas"] += 1
                    if len(ignorados) < 10:
                        ignorados.append(
                            {
                                "linha": int(idx) + 2,
                                "motivo": "Solicitante fora do escopo",
                                "solicitante": solicitante,
                            }
                        )
                    continue

                numero_sc = _codigo_txt(_valor(row, colunas["numero_sc"], ""))
                part_number = str(_valor(row, colunas["produto"], "") or "").strip()
                status_protheus = str(_valor(row, colunas["status"], "") or "").strip()

                if _normalizar_txt(status_protheus) in ("rascunho", "rejeitado"):
                    stats["linhas_ignoradas"] += 1
                    continue
                if _normalizar_txt(part_number) == "generico":
                    stats["linhas_ignoradas"] += 1
                    continue
                if not numero_sc or not part_number:
                    stats["linhas_ignoradas"] += 1
                    continue

                item = conn.execute(
                    "SELECT id, importancia FROM inventario WHERE part_number=?", (part_number,)
                ).fetchone()
                # v5.1.0 (F2): PN fora do inventário não é mais descartado — a SC é criada e o
                # item vai para itens_sc_externos (visibilidade do ciclo SC→PO; "promover" depois).
                externo = item is None
                item_id = None if externo else item["id"]

                descricao_item = str(_valor(row, colunas["descricao_item"], part_number) or "").strip()
                justificativa = str(_valor(row, colunas["justificativa"], "") or "").strip()
                qtd_sc = _to_float(_valor(row, colunas["quantidade"], 0))
                qtd_entregue = _to_float(_valor(row, colunas["qtd_entregue"], 0))
                qtd_pedido = _to_float(_valor(row, colunas["qtd_pedido"], 0))
                qtd_negociada = qtd_pedido or qtd_sc
                prioridade_critica = _tem_prioridade_critica(justificativa)
                data_necessidade = _to_date_str(_valor(row, colunas["data_necessidade"], None))
                divergencia = bool(qtd_pedido and abs(qtd_sc - qtd_pedido) > 0.0001)
                # v5.7.0 — mesma regra do importador do Relatório de SCs: `qtd_entregue` é a
                # leitura do Protheus e vai para a coluna espelho; saldo, status e ruptura saem
                # do recebimento do MRO quando a linha já existe. Item externo (sem `item_id`)
                # não tem linha em `itens_sc`, então cai no valor do Protheus.
                recebida_mro = _recebimento_mro_item_sc(conn, numero_sc, item_id)
                if recebida_mro is None:
                    recebida_mro = qtd_entregue
                saldo_residual, status_item = _saldo_status_item_sc(qtd_negociada, recebida_mro)
                ruptura = bool(
                    data_necessidade
                    and saldo_residual > 0
                    and datetime.strptime(data_necessidade, "%Y-%m-%d").date() < hoje
                )
                status = _status_sc_importado(status_protheus, saldo_residual)
                numero_po = str(_valor(row, colunas["pedido"], "") or "").strip()
                fornecedor = str(_valor(row, colunas["fornecedor"], "") or "").strip()
                data_prev = _to_date_str(_valor(row, colunas["previsao_nfe"], None))
                data_abertura = _to_date_str(_valor(row, colunas["emissao"], None)) or hoje.strftime(
                    "%Y-%m-%d"
                )
                data_aprovacao = _to_date_str(_valor(row, colunas["aprovacao"], None))
                # v3.5.0 — comprador real, data de emissão do PO (DT Emissão) e saving (R$; '-' → 0).
                comprador = str(_valor(row, colunas["comprador"], "") or "").strip()
                comprador = comprador if comprador and comprador != "-" else None
                data_po = _to_date_str(_valor(row, colunas["dt_emissao_po"], None))
                saving_val = _to_float(_valor(row, colunas["saving"], 0))
                departamento = str(_valor(row, colunas["departamento"], "") or "").strip()
                departamento = departamento if departamento and departamento != "-" else None
                # v5.6.0 — centro de custo da SC (mesmo tratamento de comprador/departamento:
                # vazio ou '-' vira None para não sobrescrever com lixo no COALESCE do UPDATE).
                centro_custo = str(_valor(row, colunas["centro_custo"], "") or "").strip()
                centro_custo = centro_custo if centro_custo and centro_custo != "-" else None
                descricao_sc = str(_valor(row, colunas["descricao_sc"], "") or "").strip()
                documento = str(_valor(row, colunas["documento"], "") or "").strip() or None
                preco_unit = _to_float(_valor(row, colunas["preco_unitario"], 0))
                valor_total = _to_float(_valor(row, colunas["valor_total"], 0))
                moeda_str = decodificar_moeda(_valor(row, colunas["moeda"], None))
                # v2.9.0: UM de compra observada nesta linha de PO (fonte da sugestão
                # de `inventario.unidade_compra`). Capturada, não descartada.
                unidade_obs = str(_valor(row, colunas["unidade"], "") or "").strip() or None

                if not externo and prioridade_critica and item["importancia"] != "Parada de Linha":
                    conn.execute(
                        "UPDATE inventario SET importancia=?, data_atualizacao=? WHERE id=?",
                        ("Parada de Linha", agora, item_id),
                    )

                sc = conn.execute(
                    "SELECT id FROM solicitacoes_compra WHERE numero_sc=?", (numero_sc,)
                ).fetchone()
                if sc:
                    sc_id = sc["id"]
                    conn.execute(
                        """
                        UPDATE solicitacoes_compra SET
                            data_abertura=?, data_aprovacao=?, numero_po=?, fornecedor=?,
                            data_prev_entrega=?, status=?, observacoes=?, solicitante=?,
                            descricao_solicitacao=?, status_protheus=?, prioridade_critica=?,
                            origem_importacao=?, data_importacao=?,
                            comprador=COALESCE(?, comprador), data_po=COALESCE(?, data_po),
                            saving=MAX(COALESCE(saving, 0), ?),
                            departamento=COALESCE(?, departamento),
                            centro_custo=COALESCE(?, centro_custo)
                        WHERE id=?
                    """,
                        (
                            data_abertura,
                            data_aprovacao,
                            numero_po or None,
                            fornecedor or None,
                            data_prev,
                            status,
                            justificativa,
                            solicitante,
                            descricao_sc,
                            status_protheus,
                            1 if prioridade_critica else 0,
                            nome_arquivo,
                            agora,
                            comprador,
                            data_po,
                            saving_val,
                            departamento,
                            centro_custo,
                            sc_id,
                        ),
                    )
                    stats["scs_atualizadas"] += 1
                else:
                    cur = conn.execute(
                        """
                        INSERT INTO solicitacoes_compra
                            (numero_sc,data_abertura,data_aprovacao,numero_po,fornecedor,
                             data_prev_entrega,status,observacoes,solicitante,
                             descricao_solicitacao,status_protheus,prioridade_critica,
                             origem_importacao,data_importacao,comprador,data_po,saving,departamento,
                             centro_custo)
                        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    """,
                        (
                            numero_sc,
                            data_abertura,
                            data_aprovacao,
                            numero_po or None,
                            fornecedor or None,
                            data_prev,
                            status,
                            justificativa,
                            solicitante,
                            descricao_sc,
                            status_protheus,
                            1 if prioridade_critica else 0,
                            nome_arquivo,
                            agora,
                            comprador,
                            data_po,
                            saving_val,
                            departamento,
                            centro_custo,
                        ),
                    )
                    sc_id = cur.lastrowid
                    stats["scs_criadas"] += 1

                # v5.1.0 (F2): item com PN fora do inventário → itens_sc_externos (não polui
                # itens_sc/inventario/precos). A SC acima é criada/atualizada normalmente.
                if externo:
                    _upsert_item_sc_externo(
                        conn,
                        sc_id,
                        part_number,
                        descricao_item,
                        qtd_sc,
                        unidade_obs,
                        preco_unit,
                        valor_total,
                        numero_po or None,
                        data_necessidade,
                        "excel",
                    )
                    stats["externos"] += 1
                    continue

                dados_item = (
                    numero_po or None,
                    qtd_sc,
                    qtd_entregue,
                    data_necessidade,
                    justificativa,
                    descricao_item,
                    qtd_negociada,
                    fornecedor or None,
                    data_prev,
                    documento,
                    0,
                    saldo_residual,
                    status_item,
                    1 if ruptura else 0,
                    1 if divergencia else 0,
                    agora,
                    preco_unit,
                    valor_total,
                    moeda_str,
                    # v5.6.0 — a `origem` do item só era gravada pelo sync da API; vinda do
                    # Excel a coluna ficava NULL e a tela mostrava o campo sempre vazio.
                    "excel",
                )
                item_sc = conn.execute(
                    "SELECT id FROM itens_sc WHERE sc_id=? AND item_id=?", (sc_id, item_id)
                ).fetchone()
                if item_sc:
                    conn.execute(
                        """
                        UPDATE itens_sc SET
                            numero_po=?, quantidade_solicitada=?, quantidade_recebida_protheus=?,
                            data_necessidade=?, observacao_item=?, descricao_detalhada=?,
                            quantidade_pedido=?, fornecedor_item=?, data_prev_nfe=?, documento_nf=?,
                            quantidade_nfe=?, saldo_residual=?, status_item=?, ruptura=?,
                            divergencia_compra=?, ultima_importacao=?, preco_unitario=?,
                            valor_total=?, moeda=?, origem=?
                        WHERE id=?
                    """,
                        (*dados_item, item_sc["id"]),
                    )
                else:
                    conn.execute(
                        """
                        INSERT INTO itens_sc
                            (sc_id,item_id,numero_po,quantidade_solicitada,quantidade_recebida_protheus,
                             data_necessidade,observacao_item,descricao_detalhada,quantidade_pedido,
                             fornecedor_item,data_prev_nfe,documento_nf,quantidade_nfe,saldo_residual,
                             status_item,ruptura,divergencia_compra,ultima_importacao,preco_unitario,
                             valor_total,moeda,origem,quantidade_recebida)
                        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    """,
                        (sc_id, item_id, *dados_item, qtd_entregue),
                    )

                conn.execute("UPDATE inventario SET ultima_sc_id=? WHERE id=?", (sc_id, item_id))

                if preco_unit > 0:
                    conn.execute(
                        "UPDATE inventario SET preco_referencia=?, data_preco_ref=? WHERE id=?",
                        (preco_unit, data_abertura or agora, item_id),
                    )
                    if numero_po:
                        existe = conn.execute(
                            "SELECT id FROM precos_historico WHERE item_id=? AND numero_po=? AND origem='SCM'",
                            (item_id, numero_po),
                        ).fetchone()
                        if not existe:
                            conn.execute(
                                """
                                INSERT INTO precos_historico
                                    (item_id,data,preco_unitario,moeda,fornecedor,numero_sc,numero_po,origem,unidade)
                                VALUES (?,?,?,?,?,?,?,?,?)
                            """,
                                (
                                    item_id,
                                    data_abertura,
                                    preco_unit,
                                    moeda_str,
                                    fornecedor or None,
                                    numero_sc,
                                    numero_po,
                                    "SCM",
                                    unidade_obs,
                                ),
                            )
                            stats["precos_capturados"] += 1
                        elif unidade_obs:
                            # v2.9.0: backfill idempotente da UM em linhas gravadas antes
                            # desta versão (mesmo padrão do lead_time da v2.4.0).
                            conn.execute(
                                "UPDATE precos_historico SET unidade=? WHERE id=? AND unidade IS NULL",
                                (unidade_obs, existe["id"]),
                            )

                stats["linhas_importadas"] += 1
                stats["rupturas"] += 1 if ruptura else 0
                stats["divergencias"] += 1 if divergencia else 0
                stats["criticos"] += 1 if prioridade_critica else 0

            _log_importacao(
                conn,
                "relatorio_scm",
                nome_arquivo,
                stats["linhas_lidas"],
                stats["linhas_importadas"],
                stats["linhas_ignoradas"],
                {"ignorados_amostra": ignorados},
            )
        stats["ignorados_amostra"] = ignorados
        return stats
    except Exception as e:
        return {"erro": str(e)}


def ingerir_sc7_precos(df, nome_arquivo="Relatorio de SCs.xlsx"):
    """Ingestor da aba SC7 (Pedidos de Compra / Protheus SC7): alimenta o histórico
    de preços por item. Fonte limpa (dados crus do ERP). Só grava PNs já cadastrados."""
    if df is None or df.empty:
        return {"erro": "Aba SC7 vazia ou ausente."}
    col = {
        "produto": _coluna(df, ["Produto"]),
        "pedido": _coluna(df, ["Pedido"]),
        "dt_emissao": _coluna(df, ["DT Emissao", "DT Emissão", "Emissao", "Emissão"]),
        "dt_entrega": _coluna(df, ["Dt. Entrega", "Dt Entrega", "Data Entrega", "Entrega"]),
        "qtd_entregue": _coluna(df, ["Qtd.Entregue", "Qtd Entregue"]),
        "preco": _coluna(df, ["Prc Unitario", "Preco Unitario", "Preço Unitário"]),
        "moeda": _coluna(df, ["Moeda"]),
        "obs": _coluna(df, ["Observacoes", "Observações"]),
        "unidade": _coluna(df, ["Unidade", "UM", "U.M.", "Um"]),  # v2.9.0: UM de compra
    }
    if not col["produto"] or not col["preco"]:
        return {"erro": "Colunas essenciais ausentes na aba SC7 (Produto/Prc Unitario)."}
    stats = {"linhas_lidas": int(len(df)), "precos_inseridos": 0, "ignorados": 0, "lead_times_calculados": 0}
    lead_deltas = {}  # item_id -> [delta_dias, ...] (backfill de Lead Time via SC7)
    try:
        with transaction() as conn:
            pn_map = {
                r["part_number"]: r["id"]
                for r in conn.execute("SELECT id, part_number FROM inventario").fetchall()
            }
            for idx, row in df.iterrows():
                pn = str(_valor(row, col["produto"], "") or "").strip()
                if not pn or pn not in pn_map:
                    stats["ignorados"] += 1
                    continue
                item_id = pn_map[pn]

                # Backfill de Lead Time (independe de preço): Dt.Entrega − DT Emissao,
                # quando houve entrega. Filtro de outlier em _gravar_lead_time_calculado.
                # lead_row = delta desta linha (dentro da faixa válida), persistido em
                # precos_historico.lead_time_dias p/ atribuir lead time ao fornecedor
                # via numero_po (v2.4.0). Fora da faixa → None (não polui o dado).
                lead_row = None
                qtd_entregue = _to_float(_valor(row, col["qtd_entregue"], 0))
                if col["dt_entrega"] and qtd_entregue > 0:
                    # Datas do SC7 vêm como datetime do Excel ou ISO (YYYY-MM-DD);
                    # não usar dayfirst (quebraria o parse ISO).
                    emi = pd.to_datetime(_valor(row, col["dt_emissao"], None), errors="coerce")
                    ent = pd.to_datetime(_valor(row, col["dt_entrega"], None), errors="coerce")
                    if not pd.isna(emi) and not pd.isna(ent):
                        delta = (ent - emi).days
                        lead_deltas.setdefault(item_id, []).append(delta)
                        if 1 <= delta <= LEAD_TIME_MAX_DIAS:
                            lead_row = delta

                preco = _to_float(_valor(row, col["preco"], 0))
                if preco <= 0:
                    stats["ignorados"] += 1
                    continue
                pedido = str(_valor(row, col["pedido"], "") or "").strip()
                data = _to_date_str(_valor(row, col["dt_emissao"], None))
                moeda_str = decodificar_moeda(_valor(row, col["moeda"], None))
                unidade_obs = str(_valor(row, col["unidade"], "") or "").strip() or None  # v2.9.0
                obs = str(_valor(row, col["obs"], "") or "")
                m = re.search(r"SC:\s*(\d+)", obs)
                numero_sc = m.group(1) if m else None

                existe = conn.execute(
                    "SELECT id FROM precos_historico WHERE item_id=? AND COALESCE(numero_po,'')=? AND origem='SC7' AND preco_unitario=?",
                    (item_id, pedido, preco),
                ).fetchone()
                if existe:
                    # Backfill idempotente: reimportações preenchem o lead time em
                    # linhas SC7 antigas (gravadas antes da v2.4.0) sem duplicar.
                    if lead_row is not None:
                        conn.execute(
                            "UPDATE precos_historico SET lead_time_dias=? WHERE id=? AND lead_time_dias IS NULL",
                            (lead_row, existe["id"]),
                        )
                    # v2.9.0: idem para a UM de compra (linhas gravadas antes desta versão).
                    if unidade_obs:
                        conn.execute(
                            "UPDATE precos_historico SET unidade=? WHERE id=? AND unidade IS NULL",
                            (unidade_obs, existe["id"]),
                        )
                    continue
                conn.execute(
                    """
                    INSERT INTO precos_historico
                        (item_id,data,preco_unitario,moeda,fornecedor,numero_sc,numero_po,origem,lead_time_dias,unidade)
                    VALUES (?,?,?,?,?,?,?,?,?,?)
                """,
                    (
                        item_id,
                        data,
                        preco,
                        moeda_str,
                        None,
                        numero_sc,
                        pedido or None,
                        "SC7",
                        lead_row,
                        unidade_obs,
                    ),
                )
                stats["precos_inseridos"] += 1

            # Grava o Lead Time calculado (mediana) por item a partir do backfill SC7.
            for item_id, deltas in lead_deltas.items():
                validos = [d for d in deltas if 1 <= d <= LEAD_TIME_MAX_DIAS]
                if not validos:
                    continue
                _gravar_lead_time_calculado(conn, item_id, validos, "SC7")
                stats["lead_times_calculados"] += 1

            _log_importacao(
                conn,
                "relatorio_sc7",
                nome_arquivo,
                stats["linhas_lidas"],
                stats["precos_inseridos"],
                stats["ignorados"],
                {"lead_times_calculados": stats["lead_times_calculados"]},
            )
        return stats
    except Exception as e:
        return {"erro": str(e)}


def _upsert_consumo_sc7(conn, linha):
    """v6.5.0 — upsert idempotente em `consumo_sc7`, chave `(numero_pc, produto)`.

    Formato `SELECT id → UPDATE/INSERT` (e não `INSERT … ON CONFLICT`) para manter o
    idioma de `_upsert_item_sc_externo`. Reimportar a mesma planilha atualiza
    Entregue/Saldo/Dt.Entrega e **não duplica linha**: um PO que era parcial e virou
    atendido muda de saldo no lugar, que é o que faz o consumo do mês mudar sozinho.
    Devolve `True` quando a linha é nova (para a estatística "inseridos")."""
    ex = conn.execute(
        "SELECT id FROM consumo_sc7 WHERE numero_pc=? AND produto=?",
        (linha["numero_pc"], linha["produto"]),
    ).fetchone()
    valores = (
        linha["dt_emissao"],
        linha["descricao"] or None,
        linha["unidade"] or None,
        linha["quantidade"],
        linha["qtd_entregue"],
        linha["saldo"],
        linha["dt_entrega"],
        linha["origem"],
    )
    if ex:
        conn.execute(
            """UPDATE consumo_sc7 SET
                 dt_emissao=COALESCE(?, dt_emissao), descricao=COALESCE(?, descricao),
                 unidade=COALESCE(?, unidade), quantidade=?, qtd_entregue=?, saldo=?,
                 dt_entrega=COALESCE(?, dt_entrega), origem=?,
                 data_importacao=CURRENT_TIMESTAMP
               WHERE id=?""",
            (*valores, ex["id"]),
        )
        return False
    conn.execute(
        """INSERT INTO consumo_sc7
             (numero_pc, produto, dt_emissao, descricao, unidade, quantidade,
              qtd_entregue, saldo, dt_entrega, origem)
           VALUES (?,?,?,?,?,?,?,?,?,?)""",
        (linha["numero_pc"], linha["produto"], *valores),
    )
    return True


def ingerir_sc7_consumo(df, nome_arquivo="Relatorio de Compras.xlsx"):
    """Ingestor da aba SC7 para o CONSUMO por pedido de compra (v6.5.0).

    Irmão de `ingerir_sc7_precos` e deliberadamente mais permissivo que ele em dois
    pontos, porque as perguntas são diferentes:

    - **Grava PN fora do inventário.** `ingerir_sc7_precos` descarta a linha quando
      `pn not in pn_map` (preço só faz sentido para item cadastrado); aqui o descarte
      apagaria justamente o histórico do item que ainda vai entrar no MRO — mesma lição
      de `itens_sc_externos`. A tabela não tem FK para `inventario`; o casamento é por
      texto, na leitura.
    - **Grava linha sem preço.** O consumo vem de `Qtd.Entregue`/`Saldo`, não de
      `Prc Unitario`.

    Agrega por `(Numero PC, Produto)` antes de gravar — o mesmo par pode aparecer em mais
    de uma linha do SC7 (itens diferentes do mesmo PO), e sem a agregação a segunda linha
    sobrescreveria a primeira em vez de somar. Molde: `_agregar_sc7` do cruzamento.

    ⚠️ **O corte das linhas vazias é feito em pandas, antes do laço.** Medido no arquivo
    real de 10/08/2026: o "Relatório de Compras" cru vem com **1.048.569 linhas** (o limite
    do Excel) e só **34 mil** têm conteúdo — o resto é preenchimento da planilha. Iterar o
    milhão em Python deixaria a tela travada por minutos para gravar 34 mil linhas.
    """
    if df is None or df.empty:
        return {"erro": "Aba SC7 vazia ou ausente."}
    col = {
        "pedido": _coluna(df, ["Numero PC", "Pedido", "Número PC"]),
        "produto": _coluna(df, ["Produto"]),
        "descricao": _coluna(df, ["Descricao", "Descrição"]),
        "unidade": _coluna(df, ["Unidade", "UM", "U.M.", "Um"]),
        "quantidade": _coluna(df, ["Quantidade", "Qty"]),
        "qtd_entregue": _coluna(df, ["Qtd.Entregue", "Qtd Entregue"]),
        "saldo": _coluna(df, ["Saldo"]),
        "dt_emissao": _coluna(
            df, ["DT Emissao", "DT Emissão", "Dt Emissao", "Dt Emissão", "Emissao", "Emissão"]
        ),
        "dt_entrega": _coluna(df, ["Dt. Entrega", "Dt Entrega", "Data Entrega", "Entrega"]),
    }
    faltantes = [n for n in ("pedido", "produto", "saldo") if not col[n]]
    if faltantes:
        return {"erro": f"Colunas obrigatórias ausentes na aba SC7: {', '.join(faltantes)}"}

    total_planilha = int(len(df))
    # Corte vetorizado das linhas de preenchimento (ver o ⚠️ da docstring). Elas NÃO contam
    # como "ignoradas": nunca foram dado, e reportar "1.014.000 ignoradas" esconderia as
    # poucas linhas que de fato têm conteúdo e foram descartadas por falta de PC/Produto.
    df = df.dropna(subset=[col["pedido"], col["produto"]])
    stats = {
        "linhas_lidas": total_planilha,
        "linhas_vazias": total_planilha - int(len(df)),
        "pedidos_gravados": 0,
        "inseridos": 0,
        "atualizados": 0,
        "ignorados": 0,
    }
    agregado = {}
    for _, row in df.iterrows():
        numero_pc = str(_valor(row, col["pedido"], "") or "").strip()
        produto = str(_valor(row, col["produto"], "") or "").strip()
        if not numero_pc or not produto:
            stats["ignorados"] += 1
            continue
        chave = (numero_pc.upper(), produto.upper())
        linha = agregado.get(chave)
        if linha is None:
            linha = {
                "numero_pc": numero_pc,
                "produto": produto,
                "dt_emissao": None,
                "descricao": "",
                "unidade": "",
                "quantidade": 0.0,
                "qtd_entregue": 0.0,
                "saldo": 0.0,
                "dt_entrega": None,
                "origem": "planilha",
            }
            agregado[chave] = linha
        linha["quantidade"] += _to_float(_valor(row, col["quantidade"], 0))
        linha["qtd_entregue"] += _to_float(_valor(row, col["qtd_entregue"], 0))
        linha["saldo"] += _to_float(_valor(row, col["saldo"], 0))
        emissao = _to_date_str(_valor(row, col["dt_emissao"], None))
        # Emissão: a MAIS ANTIGA do par (é o mês em que a compra foi decidida);
        # entrega: a MAIS RECENTE (é quando o PO terminou de chegar).
        if emissao and (linha["dt_emissao"] is None or emissao < linha["dt_emissao"]):
            linha["dt_emissao"] = emissao
        entrega = _to_date_str(_valor(row, col["dt_entrega"], None))
        if entrega and (linha["dt_entrega"] is None or entrega > linha["dt_entrega"]):
            linha["dt_entrega"] = entrega
        if not linha["descricao"]:
            linha["descricao"] = str(_valor(row, col["descricao"], "") or "").strip()
        if not linha["unidade"]:
            linha["unidade"] = str(_valor(row, col["unidade"], "") or "").strip()

    try:
        with transaction() as conn:
            for linha in agregado.values():
                if _upsert_consumo_sc7(conn, linha):
                    stats["inseridos"] += 1
                else:
                    stats["atualizados"] += 1
            stats["pedidos_gravados"] = stats["inseridos"] + stats["atualizados"]
            _log_importacao(
                conn,
                "sc7_consumo",
                nome_arquivo,
                stats["linhas_lidas"],
                stats["pedidos_gravados"],
                stats["ignorados"],
                {"inseridos": stats["inseridos"], "atualizados": stats["atualizados"]},
            )
        return stats
    except Exception as e:
        return {"erro": str(e)}


def ingerir_fornecedores(df, nome_arquivo="Relatorio de SCs.xlsx"):
    """Ingestor da aba FORNECEDORES (Protheus SA1): upsert do cadastro mestre
    (chave Codigo+Loja), incluindo e-mail para cotação."""
    if df is None or df.empty:
        return {"erro": "Aba FORNECEDORES vazia ou ausente."}
    col = {
        "codigo": _coluna(df, ["Codigo", "Código"]),
        "loja": _coluna(df, ["Loja"]),
        "razao": _coluna(df, ["Razao Social", "Razão Social"]),
        "fantasia": _coluna(df, ["N Fantasia", "Nome Fantasia"]),
        "cnpj": _coluna(df, ["CNPJ/CPF", "CNPJ"]),
        "email": _coluna(df, ["E-Mail", "Email", "E-mail"]),
        "telefone": _coluna(df, ["Telefone"]),
        "contato": _coluna(df, ["Contato"]),
        "cond": _coluna(df, ["Cond. Pagto", "Cond Pagto"]),
    }
    if not col["codigo"]:
        return {"erro": "Coluna 'Codigo' ausente na aba FORNECEDORES."}
    agora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    stats = {"linhas_lidas": int(len(df)), "upserted": 0, "com_email": 0, "ignorados": 0}
    try:
        with transaction() as conn:
            for _, row in df.iterrows():
                codigo = _codigo_txt(_valor(row, col["codigo"], ""))
                if not codigo or codigo == "0":
                    stats["ignorados"] += 1
                    continue
                loja = _codigo_txt(_valor(row, col["loja"], "")) or "1"
                razao = str(_valor(row, col["razao"], "") or "").strip()
                fantasia = str(_valor(row, col["fantasia"], "") or "").strip()
                cnpj = str(_valor(row, col["cnpj"], "") or "").strip()
                email = str(_valor(row, col["email"], "") or "").strip()
                telefone = str(_valor(row, col["telefone"], "") or "").strip()
                contato = str(_valor(row, col["contato"], "") or "").strip()
                cond = str(_valor(row, col["cond"], "") or "").strip()
                conn.execute(
                    """
                    INSERT INTO fornecedores
                        (codigo,loja,razao_social,nome_fantasia,cnpj,email,telefone,contato,cond_pagto,ativo,ultima_importacao)
                    VALUES (?,?,?,?,?,?,?,?,?,1,?)
                    ON CONFLICT(codigo,loja) DO UPDATE SET
                        razao_social=excluded.razao_social, nome_fantasia=excluded.nome_fantasia,
                        cnpj=excluded.cnpj, email=excluded.email, telefone=excluded.telefone,
                        contato=excluded.contato, cond_pagto=excluded.cond_pagto,
                        ultima_importacao=excluded.ultima_importacao
                """,
                    (codigo, loja, razao, fantasia, cnpj, email, telefone, contato, cond, agora),
                )
                stats["upserted"] += 1
                if email and "@" in email:
                    stats["com_email"] += 1
            _log_importacao(
                conn,
                "relatorio_fornecedores",
                nome_arquivo,
                stats["linhas_lidas"],
                stats["upserted"],
                stats["ignorados"],
                {"com_email": stats["com_email"]},
            )
        return stats
    except Exception as e:
        return {"erro": str(e)}


def ingerir_scm_users(df, nome_arquivo="Relatorio de SCs.xlsx"):
    """Ingestor da aba SCM USERS: upsert de solicitantes (departamento/gerente/
    aprovador/status). NÃO marca incluir_mro automaticamente — o escopo MRO
    permanece controlado (preserva os já marcados, ex.: os 3 do seed)."""
    if df is None or df.empty:
        return {"erro": "Aba SCM USERS vazia ou ausente."}
    col = {
        "solicitante": _coluna(df, ["SOLICITANTE", "Solicitante"]),
        "departamento": _coluna(df, ["DEPARTAMENTO", "Departamento"]),
        "gerente": _coluna(df, ["GERENTE IME", "Gerente"]),
        "aprovador": _coluna(df, ["APROVADOR SCM", "Aprovador"]),
        "status": _coluna(df, ["STATUS", "Status"]),
    }
    if not col["solicitante"]:
        return {"erro": "Coluna 'SOLICITANTE' ausente na aba SCM USERS."}
    stats = {"linhas_lidas": int(len(df)), "upserted": 0, "ignorados": 0}
    try:
        with transaction() as conn:
            for _, row in df.iterrows():
                nome = str(_valor(row, col["solicitante"], "") or "").strip()
                norm = _normalizar_txt(nome)
                if not norm:
                    stats["ignorados"] += 1
                    continue
                dep = str(_valor(row, col["departamento"], "") or "").strip()
                ger = str(_valor(row, col["gerente"], "") or "").strip()
                apr = str(_valor(row, col["aprovador"], "") or "").strip()
                stt = str(_valor(row, col["status"], "") or "").strip()
                conn.execute(
                    """
                    INSERT INTO solicitantes_mro
                        (nome,nome_norm,departamento,gerente,aprovador,status,incluir_mro)
                    VALUES (?,?,?,?,?,?,0)
                    ON CONFLICT(nome_norm) DO UPDATE SET
                        nome=excluded.nome, departamento=excluded.departamento,
                        gerente=excluded.gerente, aprovador=excluded.aprovador,
                        status=excluded.status
                """,
                    (nome, norm, dep, ger, apr, stt),
                )
                stats["upserted"] += 1
            _log_importacao(
                conn,
                "relatorio_scm_users",
                nome_arquivo,
                stats["linhas_lidas"],
                stats["upserted"],
                stats["ignorados"],
                {},
            )
        return stats
    except Exception as e:
        return {"erro": str(e)}
