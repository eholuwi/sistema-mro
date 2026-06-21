import sqlite3, json, re, unicodedata
import logging
from datetime import datetime
from database import get_connection
from services.constants import (
    MARGEM_ATENCAO, FATOR_ESTOQUE_MAXIMO, FATOR_ESTOQUE_SEGURANCA,
    JANELA_CONSUMO_DIAS, PREVISAO_RUPTURA_SEM_RISCO,
)
import pandas as pd

logger = logging.getLogger(__name__)

# ══════════════════════════════════════════════════════════════════════════════
# CONSTANTES E HELPERS PARA IMPORTAÇÃO PROTHEUS
# ══════════════════════════════════════════════════════════════════════════════

SOLICITANTES_MRO = {
    "jasiva lopes",
    "luis gabriel arruda de oliveira",
    "sidinei correa alfon",
}

PALAVRAS_CRITICAS = ("parada", "critico", "critica", "urgente", "linha")


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

def calcular_status_sc(data_aprovacao, numero_po, fornecedor, tem_pendente):
    if not tem_pendente:
        return "✅ SC Concluída"
    if numero_po and fornecedor:
        return "🚚 Aguardando Entrega"
    if numero_po and not fornecedor:
        return "🔍 Verificar Fornecedor"
    if data_aprovacao and not numero_po:
        return "⚠️ Cotação"
    return "📢 Aprovação Gestor"

# ══════════════════════════════════════════════════════════════════════════════
# LISTAS CONFIGURÁVEIS
# ══════════════════════════════════════════════════════════════════════════════

def listar_valores(tipo):
    conn = get_connection()
    rows = conn.execute(
        "SELECT valor FROM listas WHERE tipo=? AND ativo=1 ORDER BY valor",(tipo,)
    ).fetchall()
    conn.close()
    return [r["valor"] for r in rows]

def adicionar_valor_lista(tipo, valor):
    conn = get_connection()
    try:
        conn.execute("INSERT INTO listas (tipo,valor) VALUES (?,?)",(tipo,valor.strip().upper()))
        conn.commit()
        return True, f"'{valor.upper()}' adicionado."
    except sqlite3.IntegrityError:
        return False, f"'{valor}' já existe."
    finally:
        conn.close()

def remover_valor_lista(tipo, valor):
    conn = get_connection()
    conn.execute("UPDATE listas SET ativo=0 WHERE tipo=? AND valor=?",(tipo,valor))
    conn.commit(); conn.close()
    return True, f"'{valor}' removido."

# ══════════════════════════════════════════════════════════════════════════════
# INVENTÁRIO
# ══════════════════════════════════════════════════════════════════════════════

def listar_inventario():
    conn = get_connection()
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
        WHERE isc.sc_id = i.ultima_sc_id
        AND isc.item_id = i.id
    ), 0) AS estoque_em_transito
    FROM inventario i
    LEFT JOIN solicitacoes_compra sc ON sc.id = i.ultima_sc_id
    ORDER BY
    CASE i.importancia
        WHEN 'Parada de Linha' THEN 1
        WHEN 'Importante'      THEN 2
        WHEN 'Admin'           THEN 3 ELSE 4 END,
    i.part_number
    """).fetchall()
    
    resultado = []
    for r in rows:
        item = dict(r)
        
        # 1. Status do Material (Baseado em Estoque Físico vs Mínimo)
        item["status_material"] = calcular_status_inventario(
            item.get("estoque_atual", 0) or 0,
            item.get("estoque_minimo", 0) or 0,
            item.get("estoque_em_transito", 0) or 0
        )
        
        # 2. Status da SC (Lógica Refinada v2.3)
        sc_num = item.get("sc_numero")
        sc_status_raw = item.get("sc_status_raw")
        saldo_transito = item.get("estoque_em_transito", 0)
        
        if not sc_num:
            item["status_sc"] = "Sem SC"
        elif sc_status_raw in ["Recebido", "Cancelado"]:
            item["status_sc"] = "✅ SC Concluída"
        elif saldo_transito > 0:
            # Tem saldo pendente, usa a lógica detalhada
            item["status_sc"] = calcular_status_sc(
                item["sc_aprovacao"], 
                item["sc_po"], 
                item["sc_fornecedor"], 
                True # tem_pendente
            )
        else:
            # Tem número de SC, mas saldo zerado (possível erro de sincronia ou recebimento parcial não atualizado)
            # Vamos confiar no status_raw da tabela de SCs
            if sc_status_raw:
                item["status_sc"] = f"📄 {sc_status_raw}"
            else:
                item["status_sc"] = "✅ SC Concluída" # Fallback seguro
        
        # Compatibilidade com código legado
        item["status_display"] = item["status_material"]

        item["estoque_maximo"] = (item.get("estoque_minimo") or 0) * FATOR_ESTOQUE_MAXIMO

        resultado.append(item)

    conn.close()
    return resultado

def buscar_item_por_id(item_id):
    conn = get_connection()
    r = conn.execute("SELECT * FROM inventario WHERE id=?",(item_id,)).fetchone()
    conn.close()
    return dict(r) if r else None

def salvar_item(part_number, nome_item, descricao, unidade, importancia,
                tipo_material, setor, local, caixa,
                estoque_atual, estoque_minimo, lead_time, item_id=None):
    conn = get_connection()
    agora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        if item_id:
            conn.execute("""
                UPDATE inventario SET
                    part_number=?,nome_item=?,descricao=?,unidade=?,
                    importancia=?,tipo_material=?,setor_responsavel=?,
                    local_armazenagem=?,caixa_identificacao=?,
                    estoque_atual=?,estoque_minimo=?,lead_time_dias=?,data_atualizacao=?
                WHERE id=?
            """,(part_number,nome_item,descricao,unidade,importancia,
                 tipo_material,setor,local,caixa,
                 estoque_atual,estoque_minimo,lead_time,agora,item_id))
        else:
            conn.execute("""
                INSERT INTO inventario
                    (part_number,nome_item,descricao,unidade,importancia,
                     tipo_material,setor_responsavel,local_armazenagem,
                     caixa_identificacao,estoque_atual,estoque_minimo,lead_time_dias)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
            """,(part_number,nome_item,descricao,unidade,importancia,
                 tipo_material,setor,local,caixa,estoque_atual,estoque_minimo,lead_time))
        conn.commit()
        _recalcular_ruptura_by_pn(conn, part_number)
        conn.commit()  # F4-11: persiste a ruptura (by_pn nao comita mais com conn externa)
        return True,"Item salvo com sucesso."
    except sqlite3.IntegrityError:
        return False,f"Part Number '{part_number}' já existe."
    finally:
        conn.close()

def desmarcar_inventariado(item_id):
    agora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn = get_connection()
    conn.execute(
        "UPDATE inventario SET data_inventario=NULL,data_atualizacao=? WHERE id=?",
        (agora, item_id)
    )
    conn.commit(); conn.close()
    return True, "Inventário removido."

def _recalcular_ruptura_by_pn(conn, part_number):
    # F4-11: mesmo padrao de _recalcular_ruptura_by_id/_recalcular_consumo --
    # so abre/comita/fecha se a conexao for criada aqui; respeita transacao externa.
    close_conn = False
    if conn is None:
        conn = get_connection()
        close_conn = True
    try:
        r = conn.execute(
            "SELECT id,estoque_atual,consumo_medio_diario,lead_time_dias FROM inventario WHERE part_number=?",
            (part_number,)
        ).fetchone()
        if not r:
            return
        consumo = r["consumo_medio_diario"] or 0
        ruptura = (r["estoque_atual"]/consumo) if consumo > 0 else PREVISAO_RUPTURA_SEM_RISCO
        seguranca = consumo*(r["lead_time_dias"] or 0)*FATOR_ESTOQUE_SEGURANCA
        conn.execute("""
            UPDATE inventario SET previsao_ruptura_dias=?,estoque_seguranca=?,data_atualizacao=? WHERE id=?
        """,(ruptura,seguranca,datetime.now().strftime("%Y-%m-%d %H:%M:%S"),r["id"]))
        if close_conn:
            conn.commit()
    finally:
        if close_conn:
            conn.close()

def _recalcular_ruptura_by_id(conn, item_id):
    """
    Recalcula a previsão de ruptura baseada no consumo e estoque atual.
    Aceita uma conexão 'conn' existente para evitar locks.
    """
    # Se conn for None, abre uma nova (fallback seguro)
    close_conn = False
    if conn is None:
        conn = get_connection()
        close_conn = True

    try:
        r = conn.execute(
            "SELECT part_number FROM inventario WHERE id=?", (item_id,)
        ).fetchone()
        
        if r:
            # Chama a função interna que também precisa da conexão
            _recalcular_ruptura_by_pn(conn, r["part_number"])
            
        if close_conn:
            conn.commit()
    finally:
        if close_conn:
            conn.close()

# ══════════════════════════════════════════════════════════════════════════════
# MOVIMENTAÇÕES
# ══════════════════════════════════════════════════════════════════════════════

def registrar_movimentacao(item_id, tipo, quantidade, centro_custo,
solicitante, emitente, setor="", observacao="",
sc_item_id=None, requisicao_id=None, data_hora=None):
    conn = get_connection()
    r = conn.execute(
        "SELECT estoque_atual,part_number FROM inventario WHERE id=?",(item_id,)
    ).fetchone()
    if not r:
        conn.close(); return False,"Item não encontrado."
    
    estoque = r["estoque_atual"]

    # ✅ AJUSTE: Permitir quantidade 0 para registros de auditoria/conferência
    # Só bloqueia saída se a quantidade for MAIOR que o estoque e maior que 0
    if tipo == "saida" and quantidade > 0 and quantidade > estoque:
        conn.close(); return False,f"Estoque insuficiente. Disponível: {estoque}"

    # Calcula novo saldo
    if quantidade == 0:
        novo_saldo = estoque # Saldo não muda
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

    # Atualiza o estoque APENAS se houver mudança real de quantidade
    if quantidade != 0:
        conn.execute(
            "UPDATE inventario SET estoque_atual=?,data_atualizacao=? WHERE id=?",
            (novo_saldo,agora,item_id)
        )
        # Recálculos de consumo/ruptura só fazem sentido se houve movimento físico
        if tipo in ("saida", "devolucao"):
            _recalcular_consumo(conn,item_id)
        _recalcular_ruptura_by_id(conn,item_id)
        
    conn.commit()
    conn.close()
    return True,f"Novo saldo: {novo_saldo}"

def _recalcular_consumo(conn, item_id):
    """
    Recalcula o consumo médio diário dos últimos 30 dias.
    Aceita uma conexão 'conn' existente para evitar locks.
    """
    # Se conn for None, abre uma nova (fallback seguro)
    close_conn = False
    if conn is None:
        conn = get_connection()
        close_conn = True

    try:
        r = conn.execute(f"""
            SELECT COALESCE(SUM(quantidade),0) AS total FROM movimentacoes
            WHERE item_id=? AND tipo='saida' AND data_hora >= datetime('now','-{JANELA_CONSUMO_DIAS} days')
        """, (item_id,)).fetchone()

        consumo_diario = (r["total"]/JANELA_CONSUMO_DIAS) if r else 0
        conn.execute("UPDATE inventario SET consumo_medio_diario=? WHERE id=?", (consumo_diario, item_id))
        
        if close_conn:
            conn.commit()
    finally:
        if close_conn:
            conn.close()

def listar_movimentacoes(item_id=None, limit=200):
    conn = get_connection()
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
    conn.close()
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
    
    conn = get_connection() # ÚNICA CONEXÃO
    agora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    try:
        num = _gerar_numero_requisicao(conn)
        
        # 1. Cabeçalho
        cur = conn.execute("""INSERT INTO requisicoes
            (numero_requisicao,data_hora,setor,emitente,centro_custo,autorizador_tipo,
             autorizador_nome,entrega_individual,destinatarios,sesmt,sesmt_responsavel,observacoes)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""", 
            (num, agora, setor, emitente, centro_custo, autorizador_tipo, autorizador_nome,
             1 if entrega_individual else 0, json.dumps(destinatarios or [], ensure_ascii=False),
             1 if sesmt else 0, sesmt_responsavel, observacoes))
        req_id = cur.lastrowid

        # 2. Itens e Baixa Imediata (Manual para evitar lock)
        for it in itens:
            qtd_sol = float(it.get("quantidade_solicitada", 0))
            qtd_ate = float(it.get("quantidade_atendida", qtd_sol))
            if qtd_sol <= 0: continue

            # Registra item da req (solicitada e atendida persistidas separadamente)
            conn.execute("INSERT INTO itens_requisicao (requisicao_id,item_id,quantidade_solicitada,quantidade_atendida) VALUES (?,?,?,?)",
                         (req_id, it["item_id"], qtd_sol, qtd_ate))
            
            # Baixa física manual na mesma conexão
            r_est = conn.execute("SELECT estoque_atual FROM inventario WHERE id=?", (it["item_id"],)).fetchone()
            if not r_est or r_est["estoque_atual"] < qtd_ate:
                raise Exception(f"Estoque insuficiente para {it.get('part_number', 'Item')}.")

            novo_saldo = r_est["estoque_atual"] - qtd_ate
            conn.execute("INSERT INTO movimentacoes (item_id,tipo,quantidade,saldo_apos,data_hora,centro_custo,setor,solicitante,emitente,observacao,requisicao_id) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                         (it["item_id"], "saida", qtd_ate, novo_saldo, agora, centro_custo, setor, emitente, emitente, f"Req {num}", req_id))
            conn.execute("UPDATE inventario SET estoque_atual=?, data_atualizacao=? WHERE id=?", (novo_saldo, agora, it["item_id"]))
            
            # Recalcula métricas na mesma conexão
            _recalcular_consumo(conn, it["item_id"])
            _recalcular_ruptura_by_id(conn, it["item_id"])

        conn.commit()
        return True, num
    except Exception as e:
        conn.rollback()
        return False, str(e)
    finally:
        conn.close()

def listar_requisicoes(limit=100):
    conn = get_connection()
    rows = conn.execute("""
        SELECT r.*,
               COUNT(ir.id) AS total_itens,
               SUM(ir.quantidade_atendida) AS total_atendido
        FROM requisicoes r
        LEFT JOIN itens_requisicao ir ON ir.requisicao_id=r.id
        GROUP BY r.id
        ORDER BY r.data_hora DESC LIMIT ?
    """,(limit,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def listar_itens_requisicao(req_id):
    conn = get_connection()
    rows = conn.execute("""
        SELECT ir.*,i.part_number,i.nome_item,i.unidade
        FROM itens_requisicao ir
        JOIN inventario i ON i.id=ir.item_id
        WHERE ir.requisicao_id=?
    """,(req_id,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]

# ══════════════════════════════════════════════════════════════════════════════
# COMPRAS (SC)
# ══════════════════════════════════════════════════════════════════════════════

def criar_sc(numero_sc, data_abertura, itens, observacoes=""):
    if not itens:
        return False,"Adicione ao menos um item."
    conn = get_connection()
    try:
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
        conn.commit()
        return True,f"SC {numero_sc} salva. Itens criados: {criados}. Atualizados: {atualizados}."
    except sqlite3.IntegrityError:
        return False,f"SC '{numero_sc}' já existe."
    finally:
        conn.close()

def atualizar_sc(sc_id, data_aprovacao=None, numero_po=None,
                 fornecedor=None, data_prev_entrega=None, status=None, observacoes=None,
                 itens=None):
    """
    Atualiza uma SC com lógica inteligente de status e gestão segura de conexão.
    - Se PO e Fornecedor forem preenchidos -> Sugerir 'Pedido Emitido'
    - Se todos os itens estiverem recebidos -> Forçar 'Recebido'
    - Garante que a conexão seja sempre fechada para evitar 'database is locked'.
    """
    conn = get_connection()
    try:
        campos, vals = [], []
        
        # --- 1. LÓGICA INTELIGENTE DE STATUS AUTOMÁTICO (Backend Safety Net) ---
        if status is None:
            # Busca o status atual para não regredir
            sc_atual = conn.execute("SELECT status FROM solicitacoes_compra WHERE id=?", (sc_id,)).fetchone()
            status_atual_db = sc_atual["status"] if sc_atual else "Aguardando Aprovação"
            
            # Verifica dados no Cabeçalho
            tem_forn_geral = bool(fornecedor and str(fornecedor).strip())
            tem_po_geral = bool(numero_po and str(numero_po).strip())
            
            # Verifica dados nos Itens (se enviados)
            tem_po_item = False
            tem_forn_item = False
            if itens:
                for it in itens:
                    if it.get("numero_po") and str(it.get("numero_po")).strip():
                        tem_po_item = True
                    if it.get("fornecedor_item") and str(it.get("fornecedor_item")).strip():
                        tem_forn_item = True
            
            # Regra: Se tem Fornecedor E PO (em qualquer nível) -> Força "Aguardando Entrega"
            if (tem_forn_geral or tem_forn_item) and (tem_po_geral or tem_po_item):
                if status_atual_db not in ["Recebido", "Cancelado"]:
                    status = "Aguardando Entrega"
            
            # Regra: Se tem Data Aprovação mas não tem pedido completo -> "Em Cotação"
            elif data_aprovacao and status_atual_db == "Aguardando Aprovação":
                status = "Em Cotação"
                
            else:
                status = status_atual_db
        # --- 2. PREPARAÇÃO DOS CAMPOS DE UPDATE DO CABEÇALHO ---
        if data_aprovacao   is not None: campos.append("data_aprovacao=?");   vals.append(data_aprovacao)
        if numero_po        is not None: campos.append("numero_po=?");         vals.append(numero_po)
        if fornecedor       is not None: campos.append("fornecedor=?");        vals.append(fornecedor)
        if data_prev_entrega is not None: campos.append("data_prev_entrega=?");vals.append(data_prev_entrega)
        if status           is not None: campos.append("status=?");            vals.append(status)
        if observacoes      is not None: campos.append("observacoes=?");       vals.append(observacoes)

        if campos:
            vals.append(sc_id)
            conn.execute(f"UPDATE solicitacoes_compra SET {','.join(campos)} WHERE id=?", vals)

        # --- 3. ATUALIZAÇÃO DOS ITENS ---
        if itens:
            for it in itens:
                item_sc_id = it.get("item_sc_id") or it.get("id")
                if not item_sc_id: continue

                qtd_solicitada = _to_float(it.get("quantidade_solicitada", 0))
                qtd_negociada = _to_float(it.get("quantidade_pedido", qtd_solicitada)) or qtd_solicitada
                qtd_recebida = _to_float(it.get("quantidade_recebida", 0))
                
                # Cálculo de saldo usando a coluna correta (saldo_residual ou cálculo dinâmico)
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

        # --- 4. VERIFICAÇÃO FINAL DE STATUS DA SC (FECHAMENTO AUTOMÁTICO) ---
        pend = conn.execute("""
            SELECT COUNT(*) AS n FROM itens_sc
            WHERE sc_id=? AND COALESCE(saldo_residual, quantidade_solicitada-quantidade_recebida) > 0
        """, (sc_id,)).fetchone()["n"]
        
        # Se não há pendências, força status Recebido (mesmo que seja manual)
        if pend == 0 and status != "Cancelado":
            conn.execute("UPDATE solicitacoes_compra SET status='Recebido' WHERE id=?", (sc_id,))
        # Se há pendências, mas o status estava como Recebido (erro de sincronia), volta para Parcial
        elif pend > 0 and status == "Recebido":
            conn.execute("UPDATE solicitacoes_compra SET status='Parcial' WHERE id=?", (sc_id,))

        conn.commit()
        return True, "SC atualizada."

    except Exception as e:
        conn.rollback()
        return False, str(e)
    
    finally:
        # GARANTIA DE FECHAMENTO DA CONEXÃO PARA EVITAR LOCKS
        conn.close()

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

    conn = get_connection()
    try:
        for idx, row in df.iterrows():
            solicitante = str(_valor(row, colunas["solicitante"], "")).strip()
            if _normalizar_txt(solicitante) not in SOLICITANTES_MRO:
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

        conn.commit()
        stats["ignorados_amostra"] = ignorados
        return True, stats
    except Exception as e:
        conn.rollback()
        return False, {"erro": str(e)}
    finally:
        conn.close()

def listar_itens_sc(sc_id):
    conn = get_connection()
    # Busca os itens da SC junto com as datas de Abertura E Aprovação da SC
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
        
        # Parsing seguro das datas
        data_aprovacao_str = item.get("data_aprovacao")
        data_abertura_str = item.get("data_abertura")
        
        dias_atendimento = 0
        
        # LÓGICA DE AGING v2.0.1: Prioriza Data de Aprovação. Se não tiver, usa Abertura.
        data_referencia = None
        
        if data_aprovacao_str:
            data_referencia = data_aprovacao_str
        elif data_abertura_str:
            data_referencia = data_abertura_str
            
        if data_referencia:
            try:
                # Tenta formatos comuns de data do SQLite
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
        
    conn.close()
    return resultado

def registrar_recebimento_sc(sc_id, item_sc_id, qtd_recebida,
centro_custo, solicitante, emitente,
fornecedor, data_recebimento, obs_nf=""):
    # DT-2: recebimento atomico. Toda a operacao roda em UMA conexao/transacao,
    # com um unico commit ao final. Qualquer falha faz rollback total (nenhum
    # efeito parcial em itens_sc, solicitacoes_compra, movimentacoes ou inventario).
    conn = get_connection()
    try:
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

        # (4)+(5) Entrada de estoque INLINE na mesma transacao. Nao usamos
        # registrar_movimentacao porque ela abre conexao propria e da commit, o
        # que fragmentaria a transacao e quebraria a atomicidade (DT-2).
        r_est = conn.execute(
            "SELECT estoque_atual FROM inventario WHERE id=?", (item_id,)
        ).fetchone()
        if not r_est:
            return False, "Item nao encontrado no inventario."
        novo_estoque = (r_est["estoque_atual"] or 0) + qtd_recebida
        obs_mov = f"NF: {nf}" if nf else "Recebimento SC"
        conn.execute("""
            INSERT INTO movimentacoes
                (item_id,tipo,quantidade,saldo_apos,data_hora,
                 centro_custo,setor,solicitante,emitente,observacao,sc_item_id,requisicao_id)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
        """,(item_id,"entrada",qtd_recebida,novo_estoque,data_mov,
            centro_custo,"",solicitante,emitente,obs_mov,item_sc_id,None))
        conn.execute(
            "UPDATE inventario SET estoque_atual=?,data_atualizacao=? WHERE id=?",
            (novo_estoque, agora, item_id)
        )

        # (6) Recalcula previsao de ruptura INLINE (mesma logica de
        # _recalcular_ruptura_by_pn, porem sem commit proprio, para nao fragmentar
        # a transacao). Entrada nao recalcula consumo medio (igual registrar_movimentacao).
        r_rup = conn.execute(
            "SELECT estoque_atual,consumo_medio_diario,lead_time_dias FROM inventario WHERE id=?",
            (item_id,)
        ).fetchone()
        consumo = r_rup["consumo_medio_diario"] or 0
        prev_ruptura = (r_rup["estoque_atual"] / consumo) if consumo > 0 else PREVISAO_RUPTURA_SEM_RISCO
        seguranca = consumo * (r_rup["lead_time_dias"] or 0) * FATOR_ESTOQUE_SEGURANCA
        conn.execute(
            "UPDATE inventario SET previsao_ruptura_dias=?,estoque_seguranca=?,data_atualizacao=? WHERE id=?",
            (prev_ruptura, seguranca, agora, item_id)
        )

        # (7) Atualiza status da SC
        pend = conn.execute("""
            SELECT COUNT(*) AS n FROM itens_sc
            WHERE sc_id=? AND COALESCE(saldo_residual, quantidade_solicitada-quantidade_recebida) > 0
        """,(sc_id,)).fetchone()["n"]
        status_novo = "Recebido" if pend == 0 else "Parcial"
        conn.execute("UPDATE solicitacoes_compra SET status=? WHERE id=?",(status_novo, sc_id))

        # (8) Recalcula lead time real (usa a MESMA conn; nao da commit/close)
        _recalcular_lead_time_real(conn, item_id)

        # (9) Commit unico: tudo ou nada
        conn.commit()
        return True, f"Recebimento registrado. SC {'fechada' if pend == 0 else 'parcial'}."
    except Exception as e:
        conn.rollback()
        return False, f"Erro ao registrar recebimento: {e}"
    finally:
        conn.close()

def listar_scs(apenas_abertas=True):
    conn = get_connection()
    filtro = "WHERE COALESCE(isc.saldo_residual, isc.quantidade_solicitada-isc.quantidade_recebida) > 0 AND sc.status NOT IN ('Cancelado') " if apenas_abertas else " "
    
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
        # ✅ CORREÇÃO: Tratar None como string vazia para evitar erro no 'in'
        importancias = sc.get('importancias_itens') or ""
        if 'Parada de Linha' in importancias: return 1
        if 'Importante' in importancias: return 2
        if 'Admin' in importancias: return 3
        return 4
        
    # Ordenação segura
    try:
        resultado.sort(key=lambda x: (peso_criticidade(x), x.get('data_abertura') or ""))
    except Exception:
        pass # Fallback se houver erro de ordenação

    conn.close()
    return resultado

def buscar_scs_por_item(item_id, apenas_abertas=True):
    conn = get_connection()
    filtro = "AND COALESCE(isc.saldo_residual, COALESCE(isc.quantidade_pedido, isc.quantidade_solicitada)-isc.quantidade_recebida) > 0 AND sc.status NOT IN ('Cancelado')" if apenas_abertas else ""
    rows = conn.execute(f"""
        SELECT sc.id, sc.numero_sc, sc.numero_po, sc.fornecedor, sc.status, sc.data_abertura,
               isc.id AS item_sc_id, isc.numero_po AS po_item,
               COALESCE(isc.fornecedor_item, sc.fornecedor) AS fornecedor_item,
               isc.quantidade_solicitada,
               COALESCE(isc.quantidade_pedido, isc.quantidade_solicitada) AS quantidade_negociada,
               isc.quantidade_recebida,
               COALESCE(isc.saldo_residual, COALESCE(isc.quantidade_pedido, isc.quantidade_solicitada)-isc.quantidade_recebida) AS pendente,
               isc.data_necessidade, isc.data_prev_nfe, isc.documento_nf, isc.status_item
        FROM itens_sc isc JOIN solicitacoes_compra sc ON sc.id=isc.sc_id
        WHERE isc.item_id=? {filtro}
        ORDER BY sc.data_abertura DESC
    """,(item_id,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def listar_recebimentos_sc(limit=300):
    conn = get_connection()
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
    conn.close()
    return [dict(r) for r in rows]

def obter_dados_dashboard(limit_abc=10):
    """
    Retorna dados para o Dashboard:
    - Curva ABC das saídas do MÊS ANTERIOR.
    - KPIs de estoque atuais (Snapshot).
    """
    from datetime import date, timedelta
    
    conn = get_connection()
    
    # --- 1. CÁLCULO DO PERÍODO (MÊS ANTERIOR) ---
    hoje = date.today()
    # Primeiro dia do mês atual
    primeiro_dia_mes_atual = hoje.replace(day=1)
    # Último dia do mês anterior
    ultimo_dia_mes_anterior = primeiro_dia_mes_atual - timedelta(days=1)
    # Primeiro dia do mês anterior
    primeiro_dia_mes_anterior = ultimo_dia_mes_anterior.replace(day=1)
    
    periodo_inicio = primeiro_dia_mes_anterior.strftime("%Y-%m-%d")
    periodo_fim = ultimo_dia_mes_anterior.strftime("%Y-%m-%d")

    # --- 2. CURVA ABC (MÊS ANTERIOR) ---
    # Filtra movimentações de saída vinculadas a requisições dentro do período
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
    
    try:
        abc_rows = conn.execute(abc_query, (periodo_inicio, periodo_fim, limit_abc)).fetchall()
    except Exception as e:
        logger.exception("Erro na query ABC: %s", e)
        abc_rows = []

    # --- 3. KPIS ATUAIS (SNAPSHOT) ---
    itens = conn.execute("SELECT estoque_atual, estoque_minimo, data_inventario FROM inventario").fetchall()
    ok = atencao = comprar = inv_ok = 0
    
    for r in itens:
        est = r["estoque_atual"] or 0
        mn  = r["estoque_minimo"] or 0
        
        # DT-4: classificacao exclusivamente via regra oficial
        status = calcular_status_inventario(est, mn, 0)
        if "COMPRAR" in status:
            comprar += 1
        elif "ATENÇÃO" in status:
            atencao += 1
        else:
            ok += 1
            
        if r["data_inventario"]: 
            inv_ok += 1
        
    conn.close()
    
    return {
        "abc": [dict(r) for r in abc_rows],
        "kpis": {
            "total": len(itens), 
            "ok": ok, 
            "atencao": atencao, 
            "comprar": comprar, 
            "inv_ok": inv_ok,
            "periodo_abc": f"{periodo_inicio} a {periodo_fim}" # Para exibir no frontend
        }
    }

def atualizar_localizacao_e_inventariar(item_id, novo_local, nova_caixa):
    """
    Atualiza a localização primária e secundária (caixa) do item.
    Aceita valores vazios para a caixa.
    """
    conn = get_connection()
    agora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    # Garante que se for None, vire string vazia para o banco
    if nova_caixa is None:
        nova_caixa = ""
    if novo_local is None:
        novo_local = ""

    try:
        conn.execute(
            "UPDATE inventario SET local_armazenagem=?, caixa_identificacao=?, data_inventario=?, data_atualizacao=? WHERE id=?",
            (novo_local, nova_caixa, agora, agora, item_id)
        )
        conn.commit()
        return True, agora
    except Exception as e:
        conn.rollback()
        return False, str(e)
    finally:
        conn.close()

# ══════════════════════════════════════════════════════════════════════════════
# EXPORTAÇÃO
# ══════════════════════════════════════════════════════════════════════════════

def exportar_inventario_df():
    itens = listar_inventario()
    if not itens:
        return pd.DataFrame()
    
    # v2.0.2: Atualização da estrutura de exportação
    colunas = [
        "part_number", "nome_item", "descricao", "unidade", "importancia",
        "tipo_material", "local_armazenagem", 
        "estoque_atual", "estoque_minimo", "estoque_maximo", "estoque_seguranca",
        "estoque_em_transito",
        "consumo_medio_diario", "lead_time_dias", "previsao_ruptura_dias",
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
        "estoque_em_transito": "Em Trânsito",
        "consumo_medio_diario": "Consumo/Dia",
        "lead_time_dias": "Lead Time(d)",
        "previsao_ruptura_dias": "Ruptura(d)",
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
        
    df = pd.DataFrame(movs)
    
    # Colunas desejadas para o Excel
    colunas = ["data_hora", "part_number", "nome_item", "tipo", "quantidade", "saldo_apos", "emitente", "observacao"]
    
    df = df[[c for c in colunas if c in df.columns]]
    
    # Renomear para o cabeçalho do Excel
    df.columns = ["Data/Hora", "PN", "Item", "Tipo", "Qtd", "Saldo Pós", "Responsável", "Observação"]
    
    return df

def _recalcular_lead_time_real(conn, item_id):
    """
    Calcula o Lead Time Médio Real baseado no histórico de SCs recebidas.
    Atualiza o campo lead_time_dias no inventario.
    """
    try:
        # Busca SCs onde o item foi recebido (Status 'Recebido' ou 'Parcial')
        rows = conn.execute("""
            SELECT sc.data_abertura, isc.quantidade_recebida
            FROM itens_sc isc
            JOIN solicitacoes_compra sc ON sc.id = isc.sc_id
            WHERE isc.item_id = ? 
            AND sc.status IN ('Recebido', 'Parcial')
            AND sc.data_abertura IS NOT NULL
        """, (item_id,)).fetchall()

        if not rows:
            return # Sem histórico de recebimento, mantém o atual

        total_dias = 0
        count = 0
        hoje = datetime.now()

        for row in rows:
            try:
                dt_abertura = datetime.strptime(row['data_abertura'], "%Y-%m-%d %H:%M:%S")
                # Para simplificar, usamos a data atual como referência de "chegada" se não tivermos a data exata da NF no banco
                # Idealmente, teríamos uma tabela de NFs, mas usando a data de atualização da SC ou data atual é um bom proxy
                # Se quiser ser mais preciso, precisaria armazenar 'data_recebimento_nf' na tabela itens_sc ou movimentacoes.
                # Vamos usar a data da última movimentação de entrada vinculada a essa SC como data de chegada real.
                
                mov = conn.execute("""
                    SELECT MAX(data_hora) as dt_chegada FROM movimentacoes 
                    WHERE sc_item_id = ? AND tipo = 'entrada'
                """, (row[0] if False else None,)).fetchone() # Simplificação: Vamos usar a data de abertura + um offset ou buscar na mov
                
                # Abordagem Robusta: Buscar a data da primeira entrada de estoque vinculada a esta SC/Item
                dt_chegada_row = conn.execute("""
                    SELECT MIN(data_hora) as dt_chegada FROM movimentacoes m
                    JOIN itens_sc isc ON isc.id = m.sc_item_id
                    WHERE isc.item_id = ? AND isc.sc_id = (
                        SELECT id FROM solicitacoes_compra WHERE data_abertura = ?
                    ) AND m.tipo = 'entrada'
                """, (item_id, row['data_abertura'])).fetchone()

                if dt_chegada_row and dt_chegada_row['dt_chegada']:
                    dt_chegada = datetime.strptime(dt_chegada_row['dt_chegada'], "%Y-%m-%d %H:%M:%S")
                    delta = (dt_chegada - dt_abertura).days
                    if delta > 0: # Ignorar dados inconsistentes
                        total_dias += delta
                        count += 1
            except Exception:
                continue

        if count > 0:
            novo_lead_time = int(round(total_dias / count))
            # Atualiza apenas se houver mudança significativa ou se for a primeira vez
            conn.execute("UPDATE inventario SET lead_time_dias = ?, data_atualizacao = ? WHERE id = ?",
                         (novo_lead_time, hoje.strftime("%Y-%m-%d %H:%M:%S"), item_id))
            
    except Exception as e:
        logger.exception("Erro ao recalcular lead time: %s", e)

def atualizar_item_inventario(item_id, dados_atualizados):
    """
    Atualiza um item no inventário.
    Nota: O status_material é calculado dinamicamente na leitura (listar_inventario),
    não sendo salvo fisicamente no banco nesta versão do schema.
    """
    conn = get_connection()
    try:
        # 1. Verificar se o item existe
        current_row = conn.execute("SELECT * FROM inventario WHERE id=?", (item_id,)).fetchone()
        if not current_row:
            return False, "Item não encontrado."
        
        # 2. Preparar campos para update
        fields = []
        values = []
        
        # Mapeamento seguro de campos permitidos (que existem no banco)
        allowed_fields = [
            "part_number", "nome_item", "descricao", "unidade", "tipo_material", "importancia",
            "estoque_minimo", "lead_time_dias", "local_armazenagem", "caixa_identificacao",
            "consumo_medio_diario", "setor_responsavel" # Adicionado setor_responsavel caso use
        ]

        for key in allowed_fields:
            if key in dados_atualizados:
                fields.append(f"{key}=?")
                values.append(dados_atualizados[key])

        if not fields:
            return False, "Nenhum dado válido para atualizar."

        # 3. Adicionar timestamp de atualização
        fields.append("data_atualizacao=?")
        values.append(datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

        values.append(item_id) # Para o WHERE

        query = f"UPDATE inventario SET {', '.join(fields)} WHERE id=?"
        conn.execute(query, values)
        conn.commit()
        return True, "Item atualizado com sucesso!"

    except Exception as e:
        conn.rollback()
        return False, str(e)
    finally:
        conn.close()

def obter_analitico_movimentacoes(periodo='mensal'):
    """
    Retorna dados agregados para o analytics de movimentações.
    periodo: 'diario', 'semanal', 'mensal'
    """
    conn = get_connection()
    
    # Definir formato de agrupamento e limite de dias
    if periodo == 'diario':
        fmt = "%Y-%m-%d"
        days = 30
    elif periodo == 'semanal':
        fmt = "%Y-%W" # Ano-Semana
        days = 90 # Últimos 3 meses
    else: # mensal
        fmt = "%Y-%m"
        days = 365 # Último ano

    # Query única para performance
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

    conn.close()
    
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
    conn = get_connection()
    
    # Query focada em ajustes manuais (exclui requisições e SCs para focar em erro/perda)
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
    
    conn.close()
    
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
    conn = get_connection()
    
    # Lógica: Busca saídas vinculadas a requisições onde o saldo pós-movimentação foi 0
    # ou onde o estoque anterior era insuficiente (simulado pela lógica de 'saida' com saldo 0)
    # Para ser preciso, olhamos o histórico de movimentações.
    
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
    
    conn.close()
    
    data = []
    for r in rows:
        data.append({
            "part_number": r["part_number"],
            "nome_item": r["nome_item"],
            "qtd_rupturas": r["qtd_rupturas"],
            "ultima_ocorrencia": r["ultima_ocorrencia"]
        })
        
    return pd.DataFrame(data) if data else pd.DataFrame(columns=["part_number", "nome_item", "qtd_rupturas", "ultima_ocorrencia"])

