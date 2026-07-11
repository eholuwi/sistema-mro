import sqlite3, json, re, math, unicodedata
import logging
from datetime import datetime, date, timedelta
from database import transaction
from services.constants import (
    MARGEM_ATENCAO, FATOR_ESTOQUE_MAXIMO, FATOR_ESTOQUE_SEGURANCA,
    JANELA_CONSUMO_DIAS, PREVISAO_RUPTURA_SEM_RISCO,
    SNAPSHOT_RETENCAO_DIAS, RELATORIO_SCS_ABAS, decodificar_moeda,
    JANELAS_CONSUMO, TENDENCIA_LIMIAR_PCT, GIRO_JANELA_DIAS, LEAD_TIME_MAX_DIAS,
    LEAD_TIME_DEFAULT_DIAS,
    ABC_LIMIAR_A, ABC_LIMIAR_B, VALOR_CONSUMIDO_JANELA_DIAS, MOEDA_PADRAO,
    SAIDA_REAL_WHERE, STATUS_SEM_MOVIMENTACAO,
    FATOR_CONVERSAO_PADRAO, extrair_fator_embalagem,
)
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
        rows = conn.execute(
            "SELECT nome_norm FROM solicitantes_mro WHERE incluir_mro=1"
        ).fetchall()
        nomes = {r[0] for r in rows if r[0]}
        if nomes:
            return nomes
    except Exception:
        pass
    return set(SOLICITANTES_MRO)


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
    return [i for i in itens
            if b in (i.get("part_number") or "").lower()
            or b in (i.get("nome_item") or "").lower()
            or b in (i.get("descricao") or "").lower()]


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
            "SELECT valor FROM listas WHERE tipo=? AND ativo=1 ORDER BY valor",(tipo,)
        ).fetchall()
    return [r["valor"] for r in rows]

def adicionar_valor_lista(tipo, valor):
    try:
        with transaction() as conn:
            conn.execute("INSERT INTO listas (tipo,valor) VALUES (?,?)",(tipo,valor.strip().upper()))
        return True, f"'{valor.upper()}' adicionado."
    except sqlite3.IntegrityError:
        return False, f"'{valor}' já existe."
    except Exception as e:
        return False, str(e)

def remover_valor_lista(tipo, valor):
    try:
        with transaction() as conn:
            conn.execute("UPDATE listas SET ativo=0 WHERE tipo=? AND valor=?",(tipo,valor))
        return True, f"'{valor}' removido."
    except Exception as e:
        return False, str(e)


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
        v = (str(v).strip() if v is not None else "")
        if v:
            vistos.setdefault(v.upper(), v)
    for v in listar_valores("setor"):   # Configurações primeiro (forma cadastrada vence)
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
        rows = conn.execute("""
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
            WHERE m.item_id = i.id AND """ + SAIDA_REAL_WHERE + """) AS qtd_requisicoes,
        (SELECT MAX(m.data_hora) FROM movimentacoes m
            WHERE m.item_id = i.id AND """ + SAIDA_REAL_WHERE + """) AS ultima_requisicao_data
        FROM inventario i
        LEFT JOIN solicitacoes_compra sc ON sc.id = i.ultima_sc_id
        ORDER BY
        CASE i.importancia
            WHEN 'Parada de Linha' THEN 1
            WHEN 'Importante'      THEN 2
            WHEN 'Admin'           THEN 3 ELSE 4 END,
        i.part_number
        """).fetchall()

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
            item.get("estoque_em_transito", 0) or 0
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
            STATUS_SEM_MOVIMENTACAO if item["sem_movimentacao"]
            else item["status_estoque_fisico"]
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
                item["sc_aprovacao"],
                item["sc_po"],
                item["sc_fornecedor"],
                True
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
            maximo_armazenado if maximo_armazenado > 0
            else (item.get("estoque_minimo") or 0) * FATOR_ESTOQUE_MAXIMO
        )
        resultado.append(item)

    return resultado

def buscar_item_por_id(item_id):
    with transaction() as conn:
        r = conn.execute("SELECT * FROM inventario WHERE id=?",(item_id,)).fetchone()
    return dict(r) if r else None

def _mov_inline(conn, item_id, tipo, quantidade, saldo_apos, observacao, agora,
                centro_custo="EDIÇÃO", responsavel="Sistema"):
    """Insere uma movimentação usando a conexão/transação CORRENTE (sem abrir
    outra). v2.2.0: mantém o ledger contínuo (saldo_apos) quando o saldo muda
    fora de registrar_movimentacao — ex.: saldo inicial no cadastro. Evita as
    'quebras' de continuidade observadas no histórico."""
    conn.execute("""
        INSERT INTO movimentacoes
            (item_id,tipo,quantidade,saldo_apos,data_hora,
             centro_custo,setor,solicitante,emitente,observacao)
        VALUES (?,?,?,?,?,?,?,?,?,?)
    """,(item_id,tipo,quantidade,saldo_apos,agora,
         centro_custo,"",responsavel,responsavel,observacao))


def salvar_item(part_number, nome_item, descricao, unidade, importancia,
                tipo_material, setor, local, caixa,
                estoque_atual, estoque_minimo, lead_time, item_id=None,
                unidade_compra=None, fator_conversao=None):
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
                conn.execute("""
                    UPDATE inventario SET
                        part_number=?,nome_item=?,descricao=?,unidade=?,
                        importancia=?,tipo_material=?,setor_responsavel=?,
                        local_armazenagem=?,caixa_identificacao=?,
                        estoque_atual=?,estoque_minimo=?,lead_time_dias=?,
                        unidade_compra=COALESCE(?, unidade_compra),
                        fator_conversao=COALESCE(?, fator_conversao),
                        data_atualizacao=?
                    WHERE id=?
                """,(part_number,nome_item,descricao,unidade,importancia,
                     tipo_material,setor,local,caixa,
                     estoque_atual,estoque_minimo,lead_time,
                     unidade_compra, fator_conversao, agora, item_id))
                # Integridade do ledger: se o saldo mudou pela edição, registra o
                # delta como movimentação (evita alterar o saldo de forma "silenciosa").
                delta = estoque_atual - estoque_antigo
                if abs(delta) > 1e-9:
                    _mov_inline(conn, item_id, "entrada" if delta > 0 else "saida",
                                abs(delta), estoque_atual, "Ajuste via edição de item", agora)
            else:
                cur = conn.execute("""
                    INSERT INTO inventario
                        (part_number,nome_item,descricao,unidade,importancia,
                         tipo_material,setor_responsavel,local_armazenagem,
                         caixa_identificacao,estoque_atual,estoque_minimo,lead_time_dias,
                         unidade_compra,fator_conversao)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,(part_number,nome_item,descricao,unidade,importancia,
                     tipo_material,setor,local,caixa,estoque_atual,estoque_minimo,lead_time,
                     unidade_compra,
                     fator_conversao if fator_conversao is not None else FATOR_CONVERSAO_PADRAO))
                novo_id = cur.lastrowid
                # Saldo inicial vira "entrada" → origem do ledger para snapshots/giro.
                if estoque_atual > 0:
                    _mov_inline(conn, novo_id, "entrada", estoque_atual, estoque_atual,
                                "Saldo inicial (cadastro)", agora)
            _recalcular_ruptura_by_pn(conn, part_number)
        return True,"Item salvo com sucesso."
    except sqlite3.IntegrityError:
        return False,f"Part Number '{part_number}' já existe."
    except Exception as e:
        return False, str(e)

def desmarcar_inventariado(item_id):
    agora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        with transaction() as conn:
            conn.execute(
                "UPDATE inventario SET data_inventario=NULL,data_atualizacao=? WHERE id=?",
                (agora, item_id)
            )
        return True, "Inventário removido."
    except Exception as e:
        return False, str(e)

def _recalcular_ruptura_by_pn(conn, part_number):
    # conn=None -> transaction() abre, comita e fecha; conn externo -> yield puro.
    with transaction(conn) as c:
        r = c.execute(
            "SELECT id,estoque_atual,consumo_medio_diario,lead_time_dias FROM inventario WHERE part_number=?",
            (part_number,)
        ).fetchone()
        if not r:
            return
        consumo = r["consumo_medio_diario"] or 0
        ruptura = (r["estoque_atual"]/consumo) if consumo > 0 else PREVISAO_RUPTURA_SEM_RISCO
        # v3.7.0: o Estoque de Segurança foi desativado (o buffer virou o próprio Mínimo
        # do Neidson). Não recalculamos mais `estoque_seguranca_calculado` — só a
        # previsão de ruptura (usada pelo Monitor de SC). As colunas de segurança
        # permanecem no schema (não-destrutivo), mas ficam órfãs.
        c.execute("""
            UPDATE inventario SET previsao_ruptura_dias=?,data_atualizacao=? WHERE id=?
        """,(ruptura,datetime.now().strftime("%Y-%m-%d %H:%M:%S"),r["id"]))

def _recalcular_ruptura_by_id(conn, item_id):
    with transaction(conn) as c:
        r = c.execute(
            "SELECT part_number FROM inventario WHERE id=?", (item_id,)
        ).fetchone()
        if r:
            _recalcular_ruptura_by_pn(c, r["part_number"])


def setor_dominante_por_item(item_ids=None, conn=None):
    """{item_id: setor dominante} derivado do CONSUMO REAL (saídas por requisição).

    v3.7.0 — Para cada item, o setor mais frequente entre suas saídas reais
    (`SAIDA_REAL_WHERE`), ignorando setores vazios. Itens sem consumo real não entram
    no mapa (o chamador aplica o fallback, ex.: '—'). UMA única query — evita N
    consultas por render. Substitui o `inventario.setor_responsavel` (98% 'Improdutivo',
    inútil) como base do "Setor" no Dashboard de Comprador (Setores em aberto) e no
    Assistente de Reposição (coluna/filtro Setor)."""
    with transaction(conn) as c:
        rows = c.execute(f"""
            SELECT item_id, setor, COUNT(*) AS n
            FROM movimentacoes
            WHERE {SAIDA_REAL_WHERE}
              AND setor IS NOT NULL AND TRIM(setor) <> ''
            GROUP BY item_id, setor
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
MONITOR_COLS_MANUAIS = ("status_po", "fornecedor", "comentario", "responsavel")
MONITOR_COLS_TECNICAS = ("numero_sc", "part_number", "nome_item", "status_calc", "unidade",
                         "tam_po", "saldo_po", "esgotado_em", "faltando_dias", "po")


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
            "WHERE revisado=1 AND (revisado_data IS NULL OR revisado_data < ?)", (hoje_iso,))

        # 2) Desativa todas as linhas de sistema; as pendentes serão reativadas no upsert.
        c.execute("UPDATE monitor_sc SET ativo=0 WHERE origem='sistema'")

        rows = c.execute(f"""
            SELECT isc.id AS item_sc_id, sc.numero_sc,
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
            po = (r["po_item"] or r["po_sc"] or "")
            c.execute("""
                INSERT INTO monitor_sc
                    (linha_id, numero_sc, part_number, nome_item, status_calc, unidade,
                     tam_po, saldo_po, esgotado_em, faltando_dias, po, origem, ativo, data_atualizacao)
                VALUES (?,?,?,?,?,?,?,?,?,?,?, 'sistema', 1, ?)
                ON CONFLICT(linha_id) DO UPDATE SET
                    numero_sc=excluded.numero_sc, part_number=excluded.part_number,
                    nome_item=excluded.nome_item, status_calc=excluded.status_calc,
                    unidade=excluded.unidade, tam_po=excluded.tam_po, saldo_po=excluded.saldo_po,
                    esgotado_em=excluded.esgotado_em, faltando_dias=excluded.faltando_dias,
                    po=excluded.po, ativo=1, data_atualizacao=excluded.data_atualizacao
            """, (linha_id, r["numero_sc"], r["part_number"], r["nome_item"], status_calc,
                  r["unidade"], r["tam_po"], r["saldo_po"], esgotado_em, faltando, po, agora))
            ativos += 1

        c.execute(
            "INSERT INTO monitor_sc_sync (id, ultima_sync) VALUES (1, ?) "
            "ON CONFLICT(id) DO UPDATE SET ultima_sync=excluded.ultima_sync", (hoje_iso,))
    return ativos


def listar_monitor_sc(conn=None):
    """Linhas VISÍVEIS do Monitor: itens de sistema ainda pendentes (ativo=1) + linhas
    manuais, exceto tombstones (removido=1). Mais urgente primeiro (menor 'faltando')."""
    with transaction(conn) as c:
        rows = c.execute("""
            SELECT * FROM monitor_sc
            WHERE removido=0 AND (origem='manual' OR ativo=1)
            ORDER BY (faltando_dias IS NULL), faltando_dias ASC, numero_sc
        """).fetchall()
    return [dict(r) for r in rows]


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
                c.execute(f"UPDATE monitor_sc SET {sets}, data_atualizacao=? WHERE linha_id=?",
                          (*dados.values(), agora, lid))
                upd += 1
            else:
                new_lid = f"man:{_uuid.uuid4().hex[:12]}"
                cols = list(dados.keys()) + ["linha_id", "origem", "ativo", "removido", "data_atualizacao"]
                vals = list(dados.values()) + [new_lid, "manual", 1, 0, agora]
                c.execute(f"INSERT INTO monitor_sc ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})", vals)
                ins += 1
        rem = 0
        for lid in orig - vistos:
            r = c.execute("SELECT origem FROM monitor_sc WHERE linha_id=?", (lid,)).fetchone()
            if not r:
                continue
            if r["origem"] == "sistema":
                c.execute("UPDATE monitor_sc SET removido=1, data_atualizacao=? WHERE linha_id=?",
                          (agora, lid))
            else:
                c.execute("DELETE FROM monitor_sc WHERE linha_id=?", (lid,))
            rem += 1
    return upd, ins, rem


# ══════════════════════════════════════════════════════════════════════════════
# MOVIMENTAÇÕES
# ══════════════════════════════════════════════════════════════════════════════

def registrar_movimentacao(item_id, tipo, quantidade, centro_custo,
solicitante, emitente, setor="", observacao="",
sc_item_id=None, requisicao_id=None, data_hora=None):
    try:
        with transaction() as conn:
            r = conn.execute(
                "SELECT estoque_atual,part_number FROM inventario WHERE id=?",(item_id,)
            ).fetchone()
            if not r:
                return False,"Item não encontrado."

            estoque = r["estoque_atual"]
            if tipo == "saida" and quantidade > 0 and quantidade > estoque:
                return False,f"Estoque insuficiente. Disponível: {estoque}"

            if quantidade == 0:
                novo_saldo = estoque
            else:
                novo_saldo = estoque + quantidade if tipo in ("entrada", "devolucao") else estoque - quantidade

            agora = data_hora or datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            conn.execute("""
                INSERT INTO movimentacoes
                    (item_id,tipo,quantidade,saldo_apos,data_hora,
                     centro_custo,setor,solicitante,emitente,observacao,sc_item_id,requisicao_id)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
            """,(item_id,tipo,quantidade,novo_saldo,agora,
                centro_custo,setor,solicitante,emitente,observacao,sc_item_id,requisicao_id))

            if quantidade != 0:
                conn.execute(
                    "UPDATE inventario SET estoque_atual=?,data_atualizacao=? WHERE id=?",
                    (novo_saldo,agora,item_id)
                )
                if tipo in ("saida", "devolucao"):
                    _recalcular_consumo(conn,item_id)
                _recalcular_ruptura_by_id(conn,item_id)

        return True,f"Novo saldo: {novo_saldo}"
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
            tendencia_pct = 100.0   # sem base anterior, mas passou a consumir
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
            (consumo_30, janelas.get(30, consumo_30), janelas.get(60, 0.0),
             janelas.get(90, 0.0), round(tendencia_pct, 1), tendencia_label, item_id),
        )

def listar_movimentacoes(item_id=None, limit=200):
    with transaction() as conn:
        if item_id:
            rows = conn.execute("""
                SELECT m.*,i.part_number,i.nome_item FROM movimentacoes m
                JOIN inventario i ON i.id=m.item_id
                WHERE m.item_id=? ORDER BY m.data_hora DESC LIMIT ?
            """,(item_id,limit)).fetchall()
        else:
            rows = conn.execute("""
                SELECT m.*,i.part_number,i.nome_item FROM movimentacoes m
                JOIN inventario i ON i.id=m.item_id
                ORDER BY m.data_hora DESC LIMIT ?
            """,(limit,)).fetchall()
    return [dict(r) for r in rows]

# ══════════════════════════════════════════════════════════════════════════════
# REQUISIÇÕES
# ══════════════════════════════════════════════════════════════════════════════

def _gerar_numero_requisicao(conn):
    hoje = datetime.now().strftime("%Y%m%d")
    r = conn.execute("""
        SELECT COUNT(*) AS n FROM requisicoes
        WHERE data_hora LIKE ?
    """,(f"{datetime.now().strftime('%Y-%m-%d')}%",)).fetchone()
    seq = (r["n"] if r else 0) + 1
    return f"REQ-{hoje}-{seq:03d}"

def criar_requisicao(setor, emitente, centro_custo, autorizador_tipo, autorizador_nome,
                     entrega_individual, destinatarios, sesmt, sesmt_responsavel,
                     itens, observacoes=""):
    if not itens: return False, "Adicione ao menos um item."
    agora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        with transaction() as conn:
            num = _gerar_numero_requisicao(conn)
            cur = conn.execute("""INSERT INTO requisicoes
                (numero_requisicao,data_hora,setor,emitente,centro_custo,autorizador_tipo,
                 autorizador_nome,entrega_individual,destinatarios,sesmt,sesmt_responsavel,observacoes)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                (num, agora, setor, emitente, centro_custo, autorizador_tipo, autorizador_nome,
                 1 if entrega_individual else 0, json.dumps(destinatarios or [], ensure_ascii=False),
                 1 if sesmt else 0, sesmt_responsavel, observacoes))
            req_id = cur.lastrowid
            for it in itens:
                qtd_sol = float(it.get("quantidade_solicitada", 0))
                qtd_ate = float(it.get("quantidade_atendida", qtd_sol))
                if qtd_sol <= 0: continue
                conn.execute("INSERT INTO itens_requisicao (requisicao_id,item_id,quantidade_solicitada,quantidade_atendida) VALUES (?,?,?,?)",
                             (req_id, it["item_id"], qtd_sol, qtd_ate))
                r_est = conn.execute("SELECT estoque_atual FROM inventario WHERE id=?", (it["item_id"],)).fetchone()
                if not r_est or r_est["estoque_atual"] < qtd_ate:
                    raise Exception(f"Estoque insuficiente para {it.get('part_number', 'Item')}.")
                novo_saldo = r_est["estoque_atual"] - qtd_ate
                conn.execute("INSERT INTO movimentacoes (item_id,tipo,quantidade,saldo_apos,data_hora,centro_custo,setor,solicitante,emitente,observacao,requisicao_id) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                             (it["item_id"], "saida", qtd_ate, novo_saldo, agora, centro_custo, setor, emitente, emitente, f"Req {num}", req_id))
                conn.execute("UPDATE inventario SET estoque_atual=?, data_atualizacao=? WHERE id=?", (novo_saldo, agora, it["item_id"]))
                _recalcular_consumo(conn, it["item_id"])
                _recalcular_ruptura_by_id(conn, it["item_id"])
        return True, num
    except Exception as e:
        return False, str(e)

def listar_requisicoes(limit=100):
    with transaction() as conn:
        rows = conn.execute("""
            SELECT r.*,
                   COUNT(ir.id) AS total_itens,
                   SUM(ir.quantidade_atendida) AS total_atendido
            FROM requisicoes r
            LEFT JOIN itens_requisicao ir ON ir.requisicao_id=r.id
            GROUP BY r.id
            ORDER BY r.data_hora DESC LIMIT ?
        """,(limit,)).fetchall()
    return [dict(r) for r in rows]

def listar_itens_requisicao(req_id):
    with transaction() as conn:
        rows = conn.execute("""
            SELECT ir.*,i.part_number,i.nome_item,i.unidade
            FROM itens_requisicao ir
            JOIN inventario i ON i.id=ir.item_id
            WHERE ir.requisicao_id=?
        """,(req_id,)).fetchall()
    return [dict(r) for r in rows]

# ══════════════════════════════════════════════════════════════════════════════
# COMPRAS (SC)
# ══════════════════════════════════════════════════════════════════════════════

def criar_sc(numero_sc, data_abertura, itens, observacoes=""):
    if not itens:
        return False,"Adicione ao menos um item."
    try:
        with transaction() as conn:
            sc = conn.execute("SELECT id FROM solicitacoes_compra WHERE numero_sc=?", (numero_sc,)).fetchone()
            if sc:
                sc_id = sc["id"]
                conn.execute("""
                    UPDATE solicitacoes_compra SET data_abertura=?, observacoes=?
                    WHERE id=?
                """, (data_abertura, observacoes, sc_id))
            else:
                cur = conn.execute("""
                    INSERT INTO solicitacoes_compra (numero_sc,data_abertura,observacoes)
                    VALUES (?,?,?)
                """,(numero_sc,data_abertura,observacoes))
                sc_id = cur.lastrowid

            criados, atualizados = 0, 0
            for it in itens:
                qtd_solicitada = _to_float(it.get("quantidade_solicitada", 0))
                qtd_negociada = _to_float(it.get("quantidade_pedido", qtd_solicitada)) or qtd_solicitada
                qtd_recebida = _to_float(it.get("quantidade_recebida", 0))
                saldo = max(qtd_negociada - qtd_recebida, 0)
                status_item = "Recebido" if saldo <= 0 else ("Parcial" if qtd_recebida > 0 else "Aberto")
                divergencia = 1 if abs(qtd_solicitada - qtd_negociada) > 0.0001 else 0
                existente = conn.execute(
                    "SELECT id FROM itens_sc WHERE sc_id=? AND item_id=?",
                    (sc_id, it["item_id"])
                ).fetchone()
                dados = (
                    it.get("numero_po") or None, qtd_solicitada, qtd_recebida,
                    it.get("data_necessidade"), it.get("observacao_item",""),
                    qtd_negociada, it.get("fornecedor_item") or None,
                    it.get("data_prev_nfe") or None, saldo, status_item, divergencia
                )
                if existente:
                    conn.execute("""
                        UPDATE itens_sc SET
                            numero_po=?, quantidade_solicitada=?, quantidade_recebida=?,
                            data_necessidade=?, observacao_item=?, quantidade_pedido=?,
                            fornecedor_item=?, data_prev_nfe=?, saldo_residual=?,
                            status_item=?, divergencia_compra=?
                        WHERE id=?
                    """, (*dados, existente["id"]))
                    atualizados += 1
                else:
                    conn.execute("""
                        INSERT INTO itens_sc
                            (sc_id,item_id,numero_po,quantidade_solicitada,quantidade_recebida,
                             data_necessidade,observacao_item,quantidade_pedido,fornecedor_item,
                             data_prev_nfe,saldo_residual,status_item,divergencia_compra)
                        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
                    """,(sc_id,it["item_id"],*dados))
                    criados += 1
                conn.execute(
                    "UPDATE inventario SET ultima_sc_id=? WHERE id=?",(sc_id,it["item_id"])
                )
        return True,f"SC {numero_sc} salva. Itens criados: {criados}. Atualizados: {atualizados}."
    except sqlite3.IntegrityError:
        return False,f"SC '{numero_sc}' já existe."
    except Exception as e:
        return False, str(e)

def atualizar_sc(sc_id, data_aprovacao=None, numero_po=None,
                 fornecedor=None, data_prev_entrega=None, status=None, observacoes=None,
                 itens=None):
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
                sc_atual = conn.execute("SELECT status FROM solicitacoes_compra WHERE id=?", (sc_id,)).fetchone()
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

            if data_aprovacao    is not None: campos.append("data_aprovacao=?");    vals.append(data_aprovacao)
            if numero_po         is not None: campos.append("numero_po=?");          vals.append(numero_po)
            if fornecedor        is not None: campos.append("fornecedor=?");         vals.append(fornecedor)
            if data_prev_entrega is not None: campos.append("data_prev_entrega=?");  vals.append(data_prev_entrega)
            if status            is not None: campos.append("status=?");             vals.append(status)
            if observacoes       is not None: campos.append("observacoes=?");        vals.append(observacoes)

            if campos:
                vals.append(sc_id)
                conn.execute(f"UPDATE solicitacoes_compra SET {','.join(campos)} WHERE id=?", vals)

            if itens:
                for it in itens:
                    item_sc_id = it.get("item_sc_id") or it.get("id")
                    if not item_sc_id: continue
                    qtd_solicitada = _to_float(it.get("quantidade_solicitada", 0))
                    qtd_negociada = _to_float(it.get("quantidade_pedido", qtd_solicitada)) or qtd_solicitada
                    qtd_recebida = _to_float(it.get("quantidade_recebida", 0))
                    saldo = max(qtd_negociada - qtd_recebida, 0)
                    status_item = "Recebido" if saldo <= 0 else ("Parcial" if qtd_recebida > 0 else "Aberto")
                    divergencia = 1 if abs(qtd_solicitada - qtd_negociada) > 0.0001 else 0
                    conn.execute("""
                        UPDATE itens_sc SET
                            numero_po=?, quantidade_solicitada=?, quantidade_pedido=?,
                            fornecedor_item=?, data_prev_nfe=?, data_necessidade=?,
                            observacao_item=?, saldo_residual=?, status_item=?,
                            divergencia_compra=?
                        WHERE id=? AND sc_id=?
                    """, (
                        it.get("numero_po") or None, qtd_solicitada, qtd_negociada,
                        it.get("fornecedor_item") or None, it.get("data_prev_nfe") or None,
                        it.get("data_necessidade") or None, it.get("observacao_item") or "",
                        saldo, status_item, divergencia, item_sc_id, sc_id
                    ))

            pend = conn.execute("""
                SELECT COUNT(*) AS n FROM itens_sc
                WHERE sc_id=? AND COALESCE(saldo_residual, quantidade_solicitada-quantidade_recebida) > 0
            """, (sc_id,)).fetchone()["n"]
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
        "SELECT id, importancia FROM inventario WHERE part_number=?",
        (part_number,)
    ).fetchone()
    importancia = "Parada de Linha" if prioridade_critica else "Importante"
    if item:
        if prioridade_critica and item["importancia"] != "Parada de Linha":
            conn.execute(
                "UPDATE inventario SET importancia=?, data_atualizacao=? WHERE id=?",
                (importancia, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), item["id"])
            )
        return item["id"]

    cur = conn.execute("""
        INSERT INTO inventario
            (part_number,nome_item,descricao,unidade,importancia,tipo_material,
             setor_responsavel,estoque_atual,estoque_minimo)
        VALUES (?,?,?,?,?,?,?,?,?)
    """, (
        part_number,
        nome_item or part_number,
        descricao or nome_item or "",
        "UN",
        importancia,
        "Spare Parts",
        "Improdutivo",
        0,
        0,
    ))
    return cur.lastrowid

def importar_solicitacoes_protheus(arquivo_excel, nome_arquivo="Solicitacoes.xlsx"):
    df = pd.read_excel(arquivo_excel)
    if df.empty:
        return False, {"erro": "A planilha esta vazia."}

    colunas = {
        "numero_sc": _coluna(df, ["Numero da Solicitacao", "N\u00famero da Solicita\u00e7\u00e3o"]),
        "descricao_sc": _coluna(df, ["Descricao da Solicitacao", "Descri\u00e7\u00e3o da Solicita\u00e7\u00e3o"]),
        "status": _coluna(df, ["Status"]),
        "justificativa": _coluna(df, ["Justificativa/Projeto", "Justificativa", "Projeto"]),
        "solicitante": _coluna(df, ["Solicitante"]),
        "produto": _coluna(df, ["Produto", "Partnumber", "Part Number"]),
        "descricao_item": _coluna(df, ["Descricao Detalhada", "Descri\u00e7\u00e3o Detalhada", "Nome do item"]),
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
                        ignorados.append({"linha": int(idx) + 2, "motivo": "Solicitante fora do escopo", "solicitante": solicitante})
                    continue

                numero_sc = str(_valor(row, colunas["numero_sc"], "")).strip()
                part_number = str(_valor(row, colunas["produto"], "")).strip()
                status_protheus = str(_valor(row, colunas["status"], "") or "").strip()

                # 🚫 Filtro 1: Ignorar Status "Rascunho" ou "Rejeitado"
                if _normalizar_txt(status_protheus) in ("rascunho", "rejeitado"):
                    stats["linhas_ignoradas"] += 1
                    if len(ignorados) < 10:
                        ignorados.append({"linha": int(idx) + 2, "motivo": "Status ignorado (Rascunho/Rejeitado)", "status": status_protheus})
                    continue

                # 🚫 Filtro 2: Ignorar Produto "Generico"
                if _normalizar_txt(part_number) == "generico":
                    stats["linhas_ignoradas"] += 1
                    if len(ignorados) < 10:
                        ignorados.append({"linha": int(idx) + 2, "motivo": "Produto Genérico", "produto": part_number})
                    continue

                if not numero_sc or not part_number:
                    stats["linhas_ignoradas"] += 1
                    if len(ignorados) < 10:
                        ignorados.append({"linha": int(idx) + 2, "motivo": "SC ou produto vazio"})
                    continue

                descricao_item = str(_valor(row, colunas["descricao_item"], part_number)).strip()
                justificativa = str(_valor(row, colunas["justificativa"], "") or "").strip()
                qtd_sc = _to_float(_valor(row, colunas["quantidade"], 0))
                qtd_entregue = _to_float(_valor(row, colunas["qtd_entregue"], 0))
                qtd_pedido = _to_float(_valor(row, colunas["quantidade_pedido"], 0))
                qtd_nfe = _to_float(_valor(row, colunas["quantidade_nfe"], 0))
                qtd_negociada = qtd_pedido or qtd_sc
                saldo_residual = max(qtd_negociada - qtd_entregue, 0)
                prioridade_critica = _tem_prioridade_critica(justificativa)
                data_necessidade = _to_date_str(_valor(row, colunas["data_necessidade"], None))
                ruptura = bool(data_necessidade and saldo_residual > 0 and datetime.strptime(data_necessidade, "%Y-%m-%d").date() < hoje)
                divergencia = bool(qtd_pedido and abs(qtd_sc - qtd_pedido) > 0.0001)
                status_item = "Recebido" if saldo_residual <= 0 else ("Parcial" if qtd_entregue > 0 else "Aberto")
                # status_protheus já foi extraído acima

                # 🚫 Filtro 3: Verificar se o Item (PN) já existe no Banco MRO
                item_existente = conn.execute(
                    "SELECT id, importancia FROM inventario WHERE part_number=?", 
                    (part_number,)
                ).fetchone()

                if not item_existente:
                    stats["linhas_ignoradas"] += 1
                    if len(ignorados) < 10:
                        ignorados.append({
                            "linha": int(idx) + 2, 
                            "motivo": "Item não cadastrado no MRO DB", 
                            "produto": part_number,
                            "descricao": descricao_item
                        })
                    continue # Pula para a próxima linha do Excel

                item_id = item_existente["id"]
                
                # Opcional: Atualizar a importância se o Protheus indicar criticidade e o banco não tiver
                if prioridade_critica and item_existente["importancia"] != "Parada de Linha":
                    conn.execute(
                        "UPDATE inventario SET importancia=?, data_atualizacao=? WHERE id=?",
                        ("Parada de Linha", agora, item_id)
                    )
                
                status = _status_sc_importado(status_protheus, saldo_residual)
                numero_po = str(_valor(row, colunas["pedido"], "") or "").strip()
                fornecedor = str(_valor(row, colunas["fornecedor"], "") or "").strip()
                data_prev = _to_date_str(_valor(row, colunas["previsao_nfe"], None))
                data_abertura = _to_date_str(_valor(row, colunas["emissao"], None)) or hoje.strftime("%Y-%m-%d")
                data_aprovacao = _to_date_str(_valor(row, colunas["aprovacao"], None))
                descricao_sc = str(_valor(row, colunas["descricao_sc"], "") or "").strip()

                antes_item = conn.execute("SELECT id FROM inventario WHERE part_number=?", (part_number,)).fetchone()
                if antes_item:
                    stats["itens_atualizados"] += 1
                else:
                    stats["itens_criados"] += 1

                sc = conn.execute("SELECT id FROM solicitacoes_compra WHERE numero_sc=?", (numero_sc,)).fetchone()
                if sc:
                    sc_id = sc["id"]
                    conn.execute("""
                        UPDATE solicitacoes_compra SET
                            data_abertura=?, data_aprovacao=?, numero_po=?, fornecedor=?,
                            data_prev_entrega=?, status=?, observacoes=?, solicitante=?,
                            descricao_solicitacao=?, status_protheus=?, prioridade_critica=?,
                            origem_importacao=?, data_importacao=?
                        WHERE id=?
                    """, (
                        data_abertura, data_aprovacao, numero_po or None, fornecedor or None,
                        data_prev, status, justificativa, solicitante, descricao_sc,
                        status_protheus, 1 if prioridade_critica else 0, nome_arquivo, agora, sc_id
                    ))
                    stats["scs_atualizadas"] += 1
                else:
                    cur = conn.execute("""
                        INSERT INTO solicitacoes_compra
                            (numero_sc,data_abertura,data_aprovacao,numero_po,fornecedor,
                             data_prev_entrega,status,observacoes,solicitante,
                             descricao_solicitacao,status_protheus,prioridade_critica,
                             origem_importacao,data_importacao)
                        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    """, (
                        numero_sc, data_abertura, data_aprovacao, numero_po or None, fornecedor or None,
                        data_prev, status, justificativa, solicitante, descricao_sc,
                        status_protheus, 1 if prioridade_critica else 0, nome_arquivo, agora
                    ))
                    sc_id = cur.lastrowid
                    stats["scs_criadas"] += 1

                item_sc = conn.execute("""
                    SELECT id FROM itens_sc
                    WHERE sc_id=? AND item_id=?
                """, (sc_id, item_id)).fetchone()
                dados_item = (
                    numero_po or None, qtd_sc, qtd_entregue, data_necessidade,
                    justificativa, descricao_item, qtd_negociada, fornecedor or None,
                    data_prev, str(_valor(row, colunas["documento"], "") or "").strip() or None,
                    qtd_nfe, saldo_residual, status_item, 1 if ruptura else 0,
                    1 if divergencia else 0, agora
                )
                if item_sc:
                    conn.execute("""
                        UPDATE itens_sc SET
                            numero_po=?, quantidade_solicitada=?, quantidade_recebida=?,
                            data_necessidade=?, observacao_item=?, descricao_detalhada=?,
                            quantidade_pedido=?, fornecedor_item=?, data_prev_nfe=?,
                            documento_nf=?, quantidade_nfe=?, saldo_residual=?,
                            status_item=?, ruptura=?, divergencia_compra=?, ultima_importacao=?
                        WHERE id=?
                    """, (*dados_item, item_sc["id"]))
                else:
                    conn.execute("""
                        INSERT INTO itens_sc
                            (sc_id,item_id,numero_po,quantidade_solicitada,quantidade_recebida,
                             data_necessidade,observacao_item,descricao_detalhada,
                             quantidade_pedido,fornecedor_item,data_prev_nfe,documento_nf,
                             quantidade_nfe,saldo_residual,status_item,ruptura,divergencia_compra,
                             ultima_importacao)
                        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    """, (sc_id, item_id, *dados_item))

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
    df = bruto.iloc[header_idx + 1:].copy()
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
        "maximo": _coluna(df, ["Máximo ( 60 dias)", "Máximo (60 dias)", "Maximo (60 dias)", "Máximo", "Maximo"]),
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

                item = conn.execute(
                    "SELECT id FROM inventario WHERE part_number=?", (pn,)
                ).fetchone()
                if not item:
                    stats["ignorados"] += 1
                    stats["pns_nao_encontrados"].append(pn)
                    continue

                sets, vals = [], []
                if colunas["categoria"]:
                    cat = _valor(row, colunas["categoria"], None)
                    cat = str(cat).strip() if cat is not None and str(cat).strip() else None
                    if cat:
                        sets.append("tipo_material=?"); vals.append(cat)
                if colunas["minimo"]:
                    sets.append("estoque_minimo=?"); vals.append(_to_float(_valor(row, colunas["minimo"], None)))
                if colunas["maximo"]:
                    sets.append("estoque_maximo=?"); vals.append(_to_float(_valor(row, colunas["maximo"], None)))
                if colunas["lead_time"]:
                    lt = _parse_lead_time_dias(_valor(row, colunas["lead_time"], None))
                    if lt is not None:
                        sets.append("lead_time_dias=?"); vals.append(lt)

                if not sets:
                    stats["ignorados"] += 1
                    continue

                if not dry_run:
                    sets.append("data_atualizacao=?"); vals.append(agora)
                    vals.append(item["id"])
                    conn.execute(f"UPDATE inventario SET {', '.join(sets)} WHERE id=?", vals)
                    _recalcular_ruptura_by_id(conn, item["id"])
                stats["atualizados"] += 1

            if not dry_run:
                detalhe = json.dumps({
                    "pns_nao_encontrados": stats["pns_nao_encontrados"],
                    "pns_duplicados_planilha": sorted(set(stats["pns_duplicados_planilha"])),
                }, ensure_ascii=False)
                conn.execute(
                    """INSERT INTO log_importacoes
                        (tipo, arquivo, data_hora, total_planilha, atualizados, ignorados, detalhe_json)
                       VALUES (?,?,?,?,?,?,?)""",
                    ("inventario_neidson", nome_arquivo, agora, stats["linhas_lidas"],
                     stats["atualizados"], stats["ignorados"], detalhe),
                )
        stats["pns_duplicados_planilha"] = sorted(set(stats["pns_duplicados_planilha"]))
        return True, stats
    except Exception as e:
        return False, {"erro": str(e)}


def listar_itens_sc(sc_id):
    with transaction() as conn:
        rows = conn.execute("""
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
        """, (sc_id,)).fetchall()

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

def registrar_recebimento_sc(sc_id, item_sc_id, qtd_recebida,
centro_custo, solicitante, emitente,
fornecedor, data_recebimento, obs_nf=""):
    # DT-2: recebimento atomico via transaction(). Qualquer falha faz rollback total.
    try:
        with transaction() as conn:
            # (1) Validacao (somente leitura; retornos antecipados nao persistem nada)
            sc_item = conn.execute("SELECT * FROM itens_sc WHERE id=?",(item_sc_id,)).fetchone()
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
            data_mov = f"{data_recebimento} {datetime.now().strftime('%H:%M:%S')}" if data_recebimento and len(str(data_recebimento)) == 10 else (data_recebimento or agora)
            nf = (obs_nf or "").strip()

            # (2) Atualiza itens_sc
            conn.execute("""
                UPDATE itens_sc SET
                    quantidade_recebida=?, saldo_residual=?, status_item=?,
                    documento_nf=COALESCE(NULLIF(?, ''), documento_nf),
                    quantidade_nfe=?, fornecedor_item=COALESCE(NULLIF(?, ''), fornecedor_item),
                    ultima_importacao=?
                WHERE id=?
            """,(nova_rec, novo_saldo, status_item, nf, qtd_recebida, fornecedor or "", agora, item_sc_id))

            # (3) Atualiza fornecedor da solicitacao
            conn.execute("""
                UPDATE solicitacoes_compra
                SET fornecedor=COALESCE(NULLIF(?, ''), fornecedor)
                WHERE id=?
            """,(fornecedor or "", sc_id))

            # (4)+(5) Entrada de estoque INLINE na mesma transacao.
            # v2.9.0 — CONVERSÃO: `qtd_recebida` chega na UNIDADE DE COMPRA (consistente
            # com itens_sc.quantidade_pedido, gravada pela ingestão na UM do PO). O
            # ledger/estoque vive na UNIDADE DE ESTOQUE, então converte:
            #   incremento_estoque = qtd_recebida / fator_conversao.
            # itens_sc.quantidade_recebida (nova_rec) segue na UM de compra (item 2 acima).
            # fator=1 (os ~318 itens de UM única) → incremento == qtd_recebida (no-op).
            r_est = conn.execute(
                "SELECT estoque_atual, unidade, unidade_compra, fator_conversao "
                "FROM inventario WHERE id=?", (item_id,)
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
                obs_mov += (f" · convertido: {qtd_recebida:g} {_uc} ÷ {fator:g}"
                            f" = {incremento_estoque:g} {_ue}")
            conn.execute("""
                INSERT INTO movimentacoes
                    (item_id,tipo,quantidade,saldo_apos,data_hora,
                     centro_custo,setor,solicitante,emitente,observacao,sc_item_id,requisicao_id)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
            """,(item_id,"entrada",incremento_estoque,novo_estoque,data_mov,
                centro_custo,"",solicitante,emitente,obs_mov,item_sc_id,None))
            conn.execute(
                "UPDATE inventario SET estoque_atual=?,data_atualizacao=? WHERE id=?",
                (novo_estoque, agora, item_id)
            )

            # (6) Recalcula ruptura + segurança (SUGESTÃO) reusando a função canônica.
            #     v3.3.0: NÃO sobrescreve mais o estoque_seguranca MANUAL do gestor — o
            #     bug antigo gravava aqui consumo×lead×1,5 (fracionário) na coluna manual,
            #     contaminando o parâmetro do gestor com "números quebrados".
            _recalcular_ruptura_by_id(conn, item_id)

            # (7) Atualiza status da SC
            pend = conn.execute("""
                SELECT COUNT(*) AS n FROM itens_sc
                WHERE sc_id=? AND COALESCE(saldo_residual, quantidade_solicitada-quantidade_recebida) > 0
            """,(sc_id,)).fetchone()["n"]
            status_novo = "Recebido" if pend == 0 else "Parcial"
            conn.execute("UPDATE solicitacoes_compra SET status=? WHERE id=?",(status_novo, sc_id))

            # (8) Recalcula o Lead Time CALCULADO como sugestão (não sobrescreve o
            #     cadastrado / base do Neidson). v2.2.1.
            _recalcular_lead_time_calculado(conn, item_id)

        return True, f"Recebimento registrado. SC {'fechada' if pend == 0 else 'parcial'}."
    except Exception as e:
        return False, f"Erro ao registrar recebimento: {e}"

def listar_scs(apenas_abertas=True):
    filtro = "WHERE COALESCE(isc.saldo_residual, isc.quantidade_solicitada-isc.quantidade_recebida) > 0 AND sc.status NOT IN ('Cancelado') " if apenas_abertas else " "
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
        importancias = sc.get('importancias_itens') or ""
        if 'Parada de Linha' in importancias: return 1
        if 'Importante' in importancias: return 2
        if 'Admin' in importancias: return 3
        return 4

    try:
        resultado.sort(key=lambda x: (peso_criticidade(x), x.get('data_abertura') or ""))
    except Exception:
        pass
    return resultado

def buscar_scs_por_item(item_id, apenas_abertas=True):
    filtro = "AND COALESCE(isc.saldo_residual, COALESCE(isc.quantidade_pedido, isc.quantidade_solicitada)-isc.quantidade_recebida) > 0 AND sc.status NOT IN ('Cancelado')" if apenas_abertas else ""
    with transaction() as conn:
        rows = conn.execute(f"""
            SELECT sc.id, sc.numero_sc, sc.numero_po, sc.fornecedor, sc.status, sc.data_abertura,
                   isc.id AS item_sc_id, isc.numero_po AS po_item,
                   COALESCE(isc.fornecedor_item, sc.fornecedor) AS fornecedor_item,
                   isc.quantidade_solicitada,
                   COALESCE(isc.quantidade_pedido, isc.quantidade_solicitada) AS quantidade_negociada,
                   isc.quantidade_recebida,
                   COALESCE(isc.saldo_residual, COALESCE(isc.quantidade_pedido, isc.quantidade_solicitada)-isc.quantidade_recebida) AS pendente,
                   isc.data_necessidade, isc.data_prev_nfe, isc.documento_nf, isc.status_item,
                   isc.preco_unitario, isc.valor_total, isc.moeda
            FROM itens_sc isc JOIN solicitacoes_compra sc ON sc.id=isc.sc_id
            WHERE isc.item_id=? {filtro}
            ORDER BY sc.data_abertura DESC
        """,(item_id,)).fetchall()
    return [dict(r) for r in rows]


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
    with transaction() as conn:
        rows = conn.execute("""
            SELECT m.data_hora, sc.numero_sc, i.part_number, i.nome_item,
                   m.quantidade, isc.documento_nf, m.emitente, m.observacao
            FROM movimentacoes m
            JOIN itens_sc isc ON isc.id=m.sc_item_id
            JOIN solicitacoes_compra sc ON sc.id=isc.sc_id
            JOIN inventario i ON i.id=m.item_id
            WHERE m.tipo='entrada' AND m.sc_item_id IS NOT NULL
            ORDER BY m.data_hora DESC LIMIT ?
        """,(limit,)).fetchall()
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
        mn  = r["estoque_minimo"] or 0
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
            "periodo_abc": f"{periodo_inicio} a {periodo_fim}"
        }
    }

def atualizar_localizacao_e_inventariar(item_id, novo_local, nova_caixa, novo_local_2=None):
    """
    Atualiza a localização primária, a 2ª locação e a caixa/observação do item.
    Aceita valores vazios. v3.4.0: 2ª locação (`local_armazenagem_2`) — um 2º ponto de
    armazenagem do mesmo item, distinto do Ajuste Rápido de Movimentações.
    """
    agora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    nova_caixa = nova_caixa or ""
    novo_local  = novo_local  or ""
    novo_local_2 = novo_local_2 or ""
    try:
        with transaction() as conn:
            conn.execute(
                "UPDATE inventario SET local_armazenagem=?, local_armazenagem_2=?, caixa_identificacao=?, data_inventario=?, data_atualizacao=? WHERE id=?",
                (novo_local, novo_local_2, nova_caixa, agora, agora, item_id)
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
        "part_number", "nome_item", "descricao", "unidade", "importancia",
        "tipo_material", "local_armazenagem",
        "estoque_atual", "estoque_minimo", "estoque_maximo", "estoque_seguranca",
        "estoque_em_transito", "dias_cobertura",
        "consumo_medio_diario", "consumo_30d", "consumo_60d", "consumo_90d",
        "tendencia_label", "tendencia_pct", "movimentacao",
        "lead_time_dias", "lead_time_calculado", "lead_time_calculado_origem",
        "giro_anual", "tempo_medio_dias", "previsao_ruptura_dias",
        "preco_ref", "preco_origem", "valor_estoque", "valor_consumido_ytd",
        "classe_abc_valor", "padrao_demanda", "classe_xyz",
        "sc_numero", "status_material", "status_sc",
        "data_inventario",
        "caixa_identificacao" # Campo reutilizado para Obs Operacional
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
        "caixa_identificacao": "Obs. Inventário" # NOVO NOME NA EXPORTAÇÃO
    }

    # Filtra apenas colunas que existem no DF antes de renomear
    cols_presentes = [c for c in colunas if c in df.columns]
    df = df[cols_presentes]
    
    # Aplica rename apenas nas colunas presentes
    df.rename(columns={k: v for k, v in rename_map.items() if k in df.columns}, inplace=True)

    return df

def exportar_movimentacoes_df(item_id=None, tipos_selecionados=None):
    # Busca todas as movimentações (sem o limite da tela para o relatório ser completo)
    movs = listar_movimentacoes(item_id=item_id, limit=5000)
    
    if not movs:
        return pd.DataFrame()
    
    # Filtro de tipo em memória (mesma lógica que você usa no app.py)
    if tipos_selecionados:
        movs = [m for m in movs if m['tipo'] in tipos_selecionados]
        
    # B-01: se o filtro de tipo zerou o resultado, retorna DataFrame vazio
    # (evita ValueError ao reatribuir colunas a um DataFrame sem linhas).
    if not movs:
        return pd.DataFrame()

    df = pd.DataFrame(movs)

    # Colunas desejadas para o Excel
    colunas = ["data_hora", "part_number", "nome_item", "tipo", "quantidade", "saldo_apos", "emitente", "observacao"]
    
    df = df[[c for c in colunas if c in df.columns]]
    
    # Renomear para o cabeçalho do Excel
    df.columns = ["Data/Hora", "PN", "Item", "Tipo", "Qtd", "Saldo Pós", "Responsável", "Observação"]
    
    return df

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
        rows = conn.execute("""
            SELECT sc.data_abertura AS abertura,
                   MIN(m.data_hora) AS chegada
            FROM itens_sc isc
            JOIN solicitacoes_compra sc ON sc.id = isc.sc_id
            JOIN movimentacoes m ON m.sc_item_id = isc.id AND m.tipo = 'entrada'
            WHERE isc.item_id = ? AND sc.data_abertura IS NOT NULL
            GROUP BY isc.id
        """, (item_id,)).fetchall()

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
                "nome_item", "descricao", "unidade", "tipo_material", "importancia",
                "estoque_minimo", "estoque_maximo", "lead_time_dias", "local_armazenagem",
                "caixa_identificacao", "consumo_medio_diario", "setor_responsavel",
                # v2.2.0 — estoque de segurança agora é MANUAL (parâmetro do gestor)
                "estoque_seguranca",
                # v2.9.0 — curadoria da conversão de unidades (só grava o que o gestor
                # confirmar; não sobrescreve automaticamente).
                "unidade_compra", "fator_conversao",
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
        "fator_sugerido": fator_desc,   # None quando não há padrão claro
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
            atual = conn.execute(
                "SELECT part_number FROM inventario WHERE id=?", (item_id,)
            ).fetchone()
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
                (novo_pn, agora, item_id)
            )
            conn.execute(
                """INSERT INTO part_numbers_historico
                       (item_id, pn_antigo, pn_novo, data_hora, usuario, motivo)
                   VALUES (?,?,?,?,?,?)""",
                (item_id, pn_antigo, novo_pn, agora, (usuario or None), (motivo or None))
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
                "SELECT * FROM part_numbers_historico WHERE item_id=? ORDER BY data_hora DESC",
                (item_id,)
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
            (termo,)
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
                (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), tipo, titulo,
                 (descricao or None), (autor or None), (pagina_origem or None), (prioridade or None))
            )
        return True, "Feedback registrado. Obrigado pela contribuição!"
    except Exception as e:
        return False, str(e)


def listar_feedbacks(tipo=None, status=None, limit=500):
    clausulas, params = [], []
    if tipo and tipo != "Todos":
        clausulas.append("tipo=?"); params.append(tipo)
    if status and status != "Todos":
        clausulas.append("status=?"); params.append(status)
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
        campos.append("status=?"); vals.append(status)
    if prioridade is not None:
        campos.append("prioridade=?"); vals.append(prioridade)
    if resposta is not None:
        campos.append("resposta=?"); vals.append(resposta)
    if not campos:
        return False, "Nada para atualizar."
    vals.append(feedback_id)
    try:
        with transaction() as conn:
            conn.execute(f"UPDATE feedbacks SET {', '.join(campos)} WHERE id=?", vals)
        return True, "Feedback atualizado."
    except Exception as e:
        return False, str(e)


def obter_analitico_movimentacoes(periodo='mensal'):
    """
    Retorna dados agregados para o analytics de movimentações.
    periodo: 'diario', 'semanal', 'mensal'
    """
    if periodo == 'diario':
        fmt = "%Y-%m-%d"
        days = 30
    elif periodo == 'semanal':
        fmt = "%Y-%W"
        days = 90
    else:
        fmt = "%Y-%m"
        days = 365

    with transaction() as conn:
        rows = conn.execute(f"""
            SELECT
                strftime('{fmt}', data_hora) as periodo,
                tipo,
                COUNT(*) as qtd_mov,
                SUM(quantidade) as vol_unidades
            FROM movimentacoes
            WHERE data_hora >= datetime('now', '-' || ? || ' days')
            GROUP BY periodo, tipo
            ORDER BY periodo DESC
        """, (days,)).fetchall()
    
    # Organizar em DataFrame-friendly structure
    data = []
    for r in rows:
        data.append({
            "periodo": r["periodo"],
            "tipo": r["tipo"],
            "qtd_mov": r["qtd_mov"],
            "vol_unidades": r["vol_unidades"]
        })
        
    return pd.DataFrame(data) if data else pd.DataFrame(columns=["periodo", "tipo", "qtd_mov", "vol_unidades"])

def obter_analitico_divergencias(days=90):
    """
    Identifica itens com maior volume de ajustes manuais (entradas/saídas sem req/sc).
    Retorna DataFrame com PN, Nome, Qtd Ajustada e Nº de Ajustes.
    """
    with transaction() as conn:
        rows = conn.execute(f"""
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
        """, (days,)).fetchall()
    
    data = []
    for r in rows:
        data.append({
            "part_number": r["part_number"],
            "nome_item": r["nome_item"],
            "qtd_ajustes": r["qtd_ajustes"],
            "vol_ajustado": r["vol_ajustado_unidades"]
        })
        
    return pd.DataFrame(data) if data else pd.DataFrame(columns=["part_number", "nome_item", "qtd_ajustes", "vol_ajustado"])

def obter_analitico_rupturas(days=90):
    """
    Identifica itens com histórico de ruptura (estoque zerado durante requisição).
    Retorna DataFrame com PN, Nome, Qtd de Rupturas e Última Ocorrência.
    """
    with transaction() as conn:
        rows = conn.execute(f"""
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
        """, (days,)).fetchall()
    
    data = []
    for r in rows:
        data.append({
            "part_number": r["part_number"],
            "nome_item": r["nome_item"],
            "qtd_rupturas": r["qtd_rupturas"],
            "ultima_ocorrencia": r["ultima_ocorrencia"]
        })
        
    return pd.DataFrame(data) if data else pd.DataFrame(columns=["part_number", "nome_item", "qtd_rupturas", "ultima_ocorrencia"])


# ══════════════════════════════════════════════════════════════════════════════
# v2.2.0 — GUARDA-CHUVA & SNAPSHOTS DE ESTOQUE
# ══════════════════════════════════════════════════════════════════════════════

def calcular_guarda_chuva(item_id, conn=None):
    """Guarda-Chuva (termo do comprador Miguel): quantidade já negociada que ainda
    falta ser entregue = Σ saldo_residual dos itens em SCs ABERTAS do material.

    v2.2.0: soma TODAS as SCs abertas do item (a versão anterior considerava só a
    última SC via ultima_sc_id, subestimando o valor)."""
    with transaction(conn) as c:
        r = c.execute("""
            SELECT COALESCE(SUM(COALESCE(isc.saldo_residual, 0)), 0) AS gc
            FROM itens_sc isc
            JOIN solicitacoes_compra s ON s.id = isc.sc_id
            WHERE isc.item_id = ?
              AND s.status NOT IN ('Recebido', 'Cancelado')
        """, (item_id,)).fetchone()
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
        ja = c.execute(
            "SELECT 1 FROM estoque_snapshots WHERE data=? LIMIT 1", (dia,)
        ).fetchone()
        if ja:
            return 0
        rows = c.execute(
            "SELECT id, estoque_atual, preco_referencia FROM inventario"
        ).fetchall()
        for r in rows:
            est = float(r["estoque_atual"] or 0)
            preco = float(r["preco_referencia"] or 0)
            c.execute("""
                INSERT OR IGNORE INTO estoque_snapshots
                    (item_id, data, estoque_atual, valor_estoque)
                VALUES (?,?,?,?)
            """, (r["id"], dia, est, est * preco))
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
        po_forn = {}                 # numero_po -> nome de exibição
        fornecedores_vistos = {}     # nome_norm -> nome de exibição
        pos_por_forn = {}            # nome_norm -> set(numero_po)
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
            "fornecedor": nome, "ultimo_preco": None, "ultima_data": None,
            "moeda": None, "preco_min": None, "preco_max": None,
            "_soma": 0.0, "_np": 0,
            "n_compras": len(pos_por_forn.get(chave, ())), "_leads": [],
        }

    for r in precos:
        nome = po_forn.get(str(r["numero_po"]).strip())
        if not nome:
            continue
        a = agg[_normalizar_txt(nome)]
        preco = float(r["preco_unitario"] or 0)
        if a["ultimo_preco"] is None:        # 1ª (mais recente, pois ordenado desc)
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
        resultado.append({
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
        })

    # Menor último preço primeiro; sem preço vai ao fim (ordenado por nome).
    resultado.sort(key=lambda x: (
        x["ultimo_preco"] is None, x["ultimo_preco"] or 0.0, x["fornecedor"]))
    if resultado and resultado[0]["ultimo_preco"] is not None:
        m = resultado[0]
        m["melhor"] = True
        data_fmt = _br(m["ultima_data"])
        m["melhor_motivo"] = (
            f"Menor último preço ({m['moeda']} {m['ultimo_preco']:.2f}"
            + (f" em {data_fmt}" if data_fmt else "") + ")"
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
            itens.append({
                "item_id": r["id"], "part_number": r["part_number"],
                "nome_item": r["nome_item"], "qtd": round(float(r["qtd"]), 2),
                "preco": preco, "origem": origem, "moeda": moeda,
                "valor": round(valor, 2),
            })
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
    conn.execute("""
        INSERT INTO log_importacoes
            (tipo, arquivo, total_planilha, atualizados, ignorados, detalhe_json)
        VALUES (?,?,?,?,?,?)
    """, (tipo, arquivo, int(total), int(atualizados), int(ignorados),
          json.dumps(detalhe, ensure_ascii=False)))


def _sheet_df(xls, nome, header):
    try:
        return xls.parse(nome, header=header)
    except Exception as e:
        logger.warning("Falha ao ler aba %s: %s", nome, e)
        return None


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
    for aba, func in ingestores.items():
        if aba in disponiveis:
            df = _sheet_df(xls, aba, RELATORIO_SCS_ABAS.get(aba, 0))
            resultados[aba] = func(df, nome_arquivo)
        else:
            resultados[aba] = {"erro": "Aba ausente na planilha."}

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
        "numero_sc":        _coluna(df, ["SC", "Numero da Solicitacao", "Número da Solicitação"]),
        "descricao_sc":     _coluna(df, ["Descrição da Solicitação", "Descricao da Solicitacao"]),
        "status":           _coluna(df, ["Status"]),
        "justificativa":    _coluna(df, ["Justificativa/Projeto", "Justificativa", "Projeto"]),
        "solicitante":      _coluna(df, ["Solicitante"]),
        "produto":          _coluna(df, ["Produto", "Partnumber", "Part Number"]),
        "descricao_item":   _coluna(df, ["Descrição", "Descricao", "Descricao Detalhada", "Nome do item"]),
        "quantidade":       _coluna(df, ["Qty", "Quantidade"]),          # Qty = qtd da SC (aba SCM)
        "data_necessidade": _coluna(df, ["Data Necessidade"]),
        "emissao":          _coluna(df, ["Emissão", "Emissao"]),
        "aprovacao":        _coluna(df, ["Aprovação", "Aprovacao", "Data de aprovação"]),
        "pedido":           _coluna(df, ["Pedido", "Numero PC", "Número PC"]),
        "qtd_pedido":       _coluna(df, ["Quantidade"]),                 # Quantidade = qtd do PO (aba SCM)
        "qtd_entregue":     _coluna(df, ["Qtd.Entregue", "Qtd Entregue"]),
        # v3.5.0 — "Nome Fantasia" vinha com lixo ("1.0"/"2.0") neste export; o nome real
        # do fornecedor está em "Razão Social" / "Fornecedor". Prioriza os limpos.
        "fornecedor":       _coluna(df, ["Razão Social", "Razao Social", "Fornecedor", "Nome Fantasia"]),
        "previsao_nfe":     _coluna(df, ["Previsão NFe", "Previsao NFe"]),
        "documento":        _coluna(df, ["Documento"]),
        # v3.5.0 — Dashboard de Comprador: comprador real, data do PO, saving, departamento.
        "comprador":        _coluna(df, ["Comprador"]),
        "dt_emissao_po":    _coluna(df, ["DT Emissão", "DT Emissao", "Dt Emissão", "Dt Emissao"]),
        "saving":           _coluna(df, ["Saving"]),
        "departamento":     _coluna(df, ["Departamento"]),
        "preco_unitario":   _coluna(df, ["Prc Unitario", "Preco Unitario", "Preço Unitário"]),
        "valor_total":      _coluna(df, ["Vlr.Total", "Valor Total", "Vlr Total"]),
        "moeda":            _coluna(df, ["Moeda"]),
        "unidade":          _coluna(df, ["Unidade", "UM", "U.M.", "Um"]),  # v2.9.0: UM de compra
    }
    faltantes = [n for n in ("numero_sc", "solicitante", "produto", "quantidade") if not colunas[n]]
    if faltantes:
        return {"erro": f"Colunas obrigatórias ausentes na aba SCM: {', '.join(faltantes)}"}

    agora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    hoje = datetime.now().date()
    stats = {"linhas_lidas": int(len(df)), "linhas_importadas": 0, "linhas_ignoradas": 0,
             "scs_criadas": 0, "scs_atualizadas": 0, "precos_capturados": 0,
             "rupturas": 0, "divergencias": 0, "criticos": 0}
    ignorados = []
    try:
        with transaction() as conn:
            solic_mro = _solicitantes_mro_norm(conn)
            for idx, row in df.iterrows():
                solicitante = str(_valor(row, colunas["solicitante"], "") or "").strip()
                if _normalizar_txt(solicitante) not in solic_mro:
                    stats["linhas_ignoradas"] += 1
                    if len(ignorados) < 10:
                        ignorados.append({"linha": int(idx) + 2, "motivo": "Solicitante fora do escopo", "solicitante": solicitante})
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
                if not item:
                    stats["linhas_ignoradas"] += 1
                    if len(ignorados) < 10:
                        ignorados.append({"linha": int(idx) + 2, "motivo": "Item não cadastrado no MRO DB", "produto": part_number})
                    continue
                item_id = item["id"]

                descricao_item = str(_valor(row, colunas["descricao_item"], part_number) or "").strip()
                justificativa = str(_valor(row, colunas["justificativa"], "") or "").strip()
                qtd_sc = _to_float(_valor(row, colunas["quantidade"], 0))
                qtd_entregue = _to_float(_valor(row, colunas["qtd_entregue"], 0))
                qtd_pedido = _to_float(_valor(row, colunas["qtd_pedido"], 0))
                qtd_negociada = qtd_pedido or qtd_sc
                saldo_residual = max(qtd_negociada - qtd_entregue, 0)
                prioridade_critica = _tem_prioridade_critica(justificativa)
                data_necessidade = _to_date_str(_valor(row, colunas["data_necessidade"], None))
                ruptura = bool(data_necessidade and saldo_residual > 0 and datetime.strptime(data_necessidade, "%Y-%m-%d").date() < hoje)
                divergencia = bool(qtd_pedido and abs(qtd_sc - qtd_pedido) > 0.0001)
                status_item = "Recebido" if saldo_residual <= 0 else ("Parcial" if qtd_entregue > 0 else "Aberto")
                status = _status_sc_importado(status_protheus, saldo_residual)
                numero_po = str(_valor(row, colunas["pedido"], "") or "").strip()
                fornecedor = str(_valor(row, colunas["fornecedor"], "") or "").strip()
                data_prev = _to_date_str(_valor(row, colunas["previsao_nfe"], None))
                data_abertura = _to_date_str(_valor(row, colunas["emissao"], None)) or hoje.strftime("%Y-%m-%d")
                data_aprovacao = _to_date_str(_valor(row, colunas["aprovacao"], None))
                # v3.5.0 — comprador real, data de emissão do PO (DT Emissão) e saving (R$; '-' → 0).
                comprador = str(_valor(row, colunas["comprador"], "") or "").strip()
                comprador = comprador if comprador and comprador != "-" else None
                data_po = _to_date_str(_valor(row, colunas["dt_emissao_po"], None))
                saving_val = _to_float(_valor(row, colunas["saving"], 0))
                departamento = str(_valor(row, colunas["departamento"], "") or "").strip()
                departamento = departamento if departamento and departamento != "-" else None
                descricao_sc = str(_valor(row, colunas["descricao_sc"], "") or "").strip()
                documento = str(_valor(row, colunas["documento"], "") or "").strip() or None
                preco_unit = _to_float(_valor(row, colunas["preco_unitario"], 0))
                valor_total = _to_float(_valor(row, colunas["valor_total"], 0))
                moeda_str = decodificar_moeda(_valor(row, colunas["moeda"], None))
                # v2.9.0: UM de compra observada nesta linha de PO (fonte da sugestão
                # de `inventario.unidade_compra`). Capturada, não descartada.
                unidade_obs = (str(_valor(row, colunas["unidade"], "") or "").strip() or None)

                if prioridade_critica and item["importancia"] != "Parada de Linha":
                    conn.execute("UPDATE inventario SET importancia=?, data_atualizacao=? WHERE id=?",
                                 ("Parada de Linha", agora, item_id))

                sc = conn.execute("SELECT id FROM solicitacoes_compra WHERE numero_sc=?", (numero_sc,)).fetchone()
                if sc:
                    sc_id = sc["id"]
                    conn.execute("""
                        UPDATE solicitacoes_compra SET
                            data_abertura=?, data_aprovacao=?, numero_po=?, fornecedor=?,
                            data_prev_entrega=?, status=?, observacoes=?, solicitante=?,
                            descricao_solicitacao=?, status_protheus=?, prioridade_critica=?,
                            origem_importacao=?, data_importacao=?,
                            comprador=COALESCE(?, comprador), data_po=COALESCE(?, data_po),
                            saving=MAX(COALESCE(saving, 0), ?),
                            departamento=COALESCE(?, departamento)
                        WHERE id=?
                    """, (data_abertura, data_aprovacao, numero_po or None, fornecedor or None,
                          data_prev, status, justificativa, solicitante, descricao_sc,
                          status_protheus, 1 if prioridade_critica else 0, nome_arquivo, agora,
                          comprador, data_po, saving_val, departamento, sc_id))
                    stats["scs_atualizadas"] += 1
                else:
                    cur = conn.execute("""
                        INSERT INTO solicitacoes_compra
                            (numero_sc,data_abertura,data_aprovacao,numero_po,fornecedor,
                             data_prev_entrega,status,observacoes,solicitante,
                             descricao_solicitacao,status_protheus,prioridade_critica,
                             origem_importacao,data_importacao,comprador,data_po,saving,departamento)
                        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    """, (numero_sc, data_abertura, data_aprovacao, numero_po or None, fornecedor or None,
                          data_prev, status, justificativa, solicitante, descricao_sc,
                          status_protheus, 1 if prioridade_critica else 0, nome_arquivo, agora,
                          comprador, data_po, saving_val, departamento))
                    sc_id = cur.lastrowid
                    stats["scs_criadas"] += 1

                dados_item = (
                    numero_po or None, qtd_sc, qtd_entregue, data_necessidade, justificativa,
                    descricao_item, qtd_negociada, fornecedor or None, data_prev, documento,
                    0, saldo_residual, status_item, 1 if ruptura else 0, 1 if divergencia else 0,
                    agora, preco_unit, valor_total, moeda_str,
                )
                item_sc = conn.execute("SELECT id FROM itens_sc WHERE sc_id=? AND item_id=?", (sc_id, item_id)).fetchone()
                if item_sc:
                    conn.execute("""
                        UPDATE itens_sc SET
                            numero_po=?, quantidade_solicitada=?, quantidade_recebida=?,
                            data_necessidade=?, observacao_item=?, descricao_detalhada=?,
                            quantidade_pedido=?, fornecedor_item=?, data_prev_nfe=?, documento_nf=?,
                            quantidade_nfe=?, saldo_residual=?, status_item=?, ruptura=?,
                            divergencia_compra=?, ultima_importacao=?, preco_unitario=?,
                            valor_total=?, moeda=?
                        WHERE id=?
                    """, (*dados_item, item_sc["id"]))
                else:
                    conn.execute("""
                        INSERT INTO itens_sc
                            (sc_id,item_id,numero_po,quantidade_solicitada,quantidade_recebida,
                             data_necessidade,observacao_item,descricao_detalhada,quantidade_pedido,
                             fornecedor_item,data_prev_nfe,documento_nf,quantidade_nfe,saldo_residual,
                             status_item,ruptura,divergencia_compra,ultima_importacao,preco_unitario,
                             valor_total,moeda)
                        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    """, (sc_id, item_id, *dados_item))

                conn.execute("UPDATE inventario SET ultima_sc_id=? WHERE id=?", (sc_id, item_id))

                if preco_unit > 0:
                    conn.execute("UPDATE inventario SET preco_referencia=?, data_preco_ref=? WHERE id=?",
                                 (preco_unit, data_abertura or agora, item_id))
                    if numero_po:
                        existe = conn.execute(
                            "SELECT id FROM precos_historico WHERE item_id=? AND numero_po=? AND origem='SCM'",
                            (item_id, numero_po)
                        ).fetchone()
                        if not existe:
                            conn.execute("""
                                INSERT INTO precos_historico
                                    (item_id,data,preco_unitario,moeda,fornecedor,numero_sc,numero_po,origem,unidade)
                                VALUES (?,?,?,?,?,?,?,?,?)
                            """, (item_id, data_abertura, preco_unit, moeda_str, fornecedor or None, numero_sc, numero_po, "SCM", unidade_obs))
                            stats["precos_capturados"] += 1
                        elif unidade_obs:
                            # v2.9.0: backfill idempotente da UM em linhas gravadas antes
                            # desta versão (mesmo padrão do lead_time da v2.4.0).
                            conn.execute(
                                "UPDATE precos_historico SET unidade=? WHERE id=? AND unidade IS NULL",
                                (unidade_obs, existe["id"]))

                stats["linhas_importadas"] += 1
                stats["rupturas"] += 1 if ruptura else 0
                stats["divergencias"] += 1 if divergencia else 0
                stats["criticos"] += 1 if prioridade_critica else 0

            _log_importacao(conn, "relatorio_scm", nome_arquivo, stats["linhas_lidas"],
                            stats["linhas_importadas"], stats["linhas_ignoradas"],
                            {"ignorados_amostra": ignorados})
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
        "produto":    _coluna(df, ["Produto"]),
        "pedido":     _coluna(df, ["Pedido"]),
        "dt_emissao": _coluna(df, ["DT Emissao", "DT Emissão", "Emissao", "Emissão"]),
        "dt_entrega": _coluna(df, ["Dt. Entrega", "Dt Entrega", "Data Entrega", "Entrega"]),
        "qtd_entregue": _coluna(df, ["Qtd.Entregue", "Qtd Entregue"]),
        "preco":      _coluna(df, ["Prc Unitario", "Preco Unitario", "Preço Unitário"]),
        "moeda":      _coluna(df, ["Moeda"]),
        "obs":        _coluna(df, ["Observacoes", "Observações"]),
        "unidade":    _coluna(df, ["Unidade", "UM", "U.M.", "Um"]),  # v2.9.0: UM de compra
    }
    if not col["produto"] or not col["preco"]:
        return {"erro": "Colunas essenciais ausentes na aba SC7 (Produto/Prc Unitario)."}
    stats = {"linhas_lidas": int(len(df)), "precos_inseridos": 0, "ignorados": 0,
             "lead_times_calculados": 0}
    lead_deltas = {}  # item_id -> [delta_dias, ...] (backfill de Lead Time via SC7)
    try:
        with transaction() as conn:
            pn_map = {r["part_number"]: r["id"] for r in
                      conn.execute("SELECT id, part_number FROM inventario").fetchall()}
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
                unidade_obs = (str(_valor(row, col["unidade"], "") or "").strip() or None)  # v2.9.0
                obs = str(_valor(row, col["obs"], "") or "")
                m = re.search(r"SC:\s*(\d+)", obs)
                numero_sc = m.group(1) if m else None

                existe = conn.execute(
                    "SELECT id FROM precos_historico WHERE item_id=? AND COALESCE(numero_po,'')=? AND origem='SC7' AND preco_unitario=?",
                    (item_id, pedido, preco)
                ).fetchone()
                if existe:
                    # Backfill idempotente: reimportações preenchem o lead time em
                    # linhas SC7 antigas (gravadas antes da v2.4.0) sem duplicar.
                    if lead_row is not None:
                        conn.execute(
                            "UPDATE precos_historico SET lead_time_dias=? WHERE id=? AND lead_time_dias IS NULL",
                            (lead_row, existe["id"]))
                    # v2.9.0: idem para a UM de compra (linhas gravadas antes desta versão).
                    if unidade_obs:
                        conn.execute(
                            "UPDATE precos_historico SET unidade=? WHERE id=? AND unidade IS NULL",
                            (unidade_obs, existe["id"]))
                    continue
                conn.execute("""
                    INSERT INTO precos_historico
                        (item_id,data,preco_unitario,moeda,fornecedor,numero_sc,numero_po,origem,lead_time_dias,unidade)
                    VALUES (?,?,?,?,?,?,?,?,?,?)
                """, (item_id, data, preco, moeda_str, None, numero_sc, pedido or None, "SC7", lead_row, unidade_obs))
                stats["precos_inseridos"] += 1

            # Grava o Lead Time calculado (mediana) por item a partir do backfill SC7.
            for item_id, deltas in lead_deltas.items():
                validos = [d for d in deltas if 1 <= d <= LEAD_TIME_MAX_DIAS]
                if not validos:
                    continue
                _gravar_lead_time_calculado(conn, item_id, validos, "SC7")
                stats["lead_times_calculados"] += 1

            _log_importacao(conn, "relatorio_sc7", nome_arquivo, stats["linhas_lidas"],
                            stats["precos_inseridos"], stats["ignorados"],
                            {"lead_times_calculados": stats["lead_times_calculados"]})
        return stats
    except Exception as e:
        return {"erro": str(e)}


def ingerir_fornecedores(df, nome_arquivo="Relatorio de SCs.xlsx"):
    """Ingestor da aba FORNECEDORES (Protheus SA1): upsert do cadastro mestre
    (chave Codigo+Loja), incluindo e-mail para cotação."""
    if df is None or df.empty:
        return {"erro": "Aba FORNECEDORES vazia ou ausente."}
    col = {
        "codigo":   _coluna(df, ["Codigo", "Código"]),
        "loja":     _coluna(df, ["Loja"]),
        "razao":    _coluna(df, ["Razao Social", "Razão Social"]),
        "fantasia": _coluna(df, ["N Fantasia", "Nome Fantasia"]),
        "cnpj":     _coluna(df, ["CNPJ/CPF", "CNPJ"]),
        "email":    _coluna(df, ["E-Mail", "Email", "E-mail"]),
        "telefone": _coluna(df, ["Telefone"]),
        "contato":  _coluna(df, ["Contato"]),
        "cond":     _coluna(df, ["Cond. Pagto", "Cond Pagto"]),
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
                conn.execute("""
                    INSERT INTO fornecedores
                        (codigo,loja,razao_social,nome_fantasia,cnpj,email,telefone,contato,cond_pagto,ativo,ultima_importacao)
                    VALUES (?,?,?,?,?,?,?,?,?,1,?)
                    ON CONFLICT(codigo,loja) DO UPDATE SET
                        razao_social=excluded.razao_social, nome_fantasia=excluded.nome_fantasia,
                        cnpj=excluded.cnpj, email=excluded.email, telefone=excluded.telefone,
                        contato=excluded.contato, cond_pagto=excluded.cond_pagto,
                        ultima_importacao=excluded.ultima_importacao
                """, (codigo, loja, razao, fantasia, cnpj, email, telefone, contato, cond, agora))
                stats["upserted"] += 1
                if email and "@" in email:
                    stats["com_email"] += 1
            _log_importacao(conn, "relatorio_fornecedores", nome_arquivo, stats["linhas_lidas"],
                            stats["upserted"], stats["ignorados"], {"com_email": stats["com_email"]})
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
        "solicitante":  _coluna(df, ["SOLICITANTE", "Solicitante"]),
        "departamento": _coluna(df, ["DEPARTAMENTO", "Departamento"]),
        "gerente":      _coluna(df, ["GERENTE IME", "Gerente"]),
        "aprovador":    _coluna(df, ["APROVADOR SCM", "Aprovador"]),
        "status":       _coluna(df, ["STATUS", "Status"]),
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
                conn.execute("""
                    INSERT INTO solicitantes_mro
                        (nome,nome_norm,departamento,gerente,aprovador,status,incluir_mro)
                    VALUES (?,?,?,?,?,?,0)
                    ON CONFLICT(nome_norm) DO UPDATE SET
                        nome=excluded.nome, departamento=excluded.departamento,
                        gerente=excluded.gerente, aprovador=excluded.aprovador,
                        status=excluded.status
                """, (nome, norm, dep, ger, apr, stt))
                stats["upserted"] += 1
            _log_importacao(conn, "relatorio_scm_users", nome_arquivo, stats["linhas_lidas"],
                            stats["upserted"], stats["ignorados"], {})
        return stats
    except Exception as e:
        return {"erro": str(e)}

