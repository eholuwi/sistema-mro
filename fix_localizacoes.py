import sqlite3
import re

DB_PATH = "mro.db"

def normalizar_forcado(local_original):
    """
    Normalização forçada para padrões TIPO-NUMERO.
    Ex: "ARM 10" -> "ARM-10", "MRO.5" -> "MRO-05"
    """
    if not local_original:
        return None
    
    local = str(local_original).strip().upper()
    
    # Se já estiver perfeito (ex: ARM-01), não mexe
    if re.match(r'^[A-Z]+-\d+$', local):
        return local
        
    # Tenta capturar Padrão: LETRAS + SEPARADOR(OPCIONAL) + NUMEROS
    # Ex: ARM 10, MRO.5, GAIOLA 02
    match = re.match(r'^([A-ZÁÀÂÃÉÈÊÍÌÓÒÔÕÚÙÇ]+)[\s\.]?(\d+)$', local)
    
    if match:
        tipo = match.group(1)
        numero = match.group(2)
        # Padroniza número com 2 dígitos se for curto (opcional, mas recomendado para ordem alfabética)
        # Se quiser manter como está (ex: ARM-10), remova o zfill
        numero_formatado = numero.zfill(2) if len(numero) < 2 else numero
        return f"{tipo}-{numero_formatado}"
    
    # Se for nome composto sem número no final (ex: SALA ALMOXARIFADO), padroniza hífens
    if ' ' in local or '.' in local:
        local_padrao = local.replace(' ', '-').replace('.', '-')
        while '--' in local_padrao:
            local_padrao = local_padrao.replace('--', '-')
        return local_padrao

    return local

def main():
    print("🔧 Iniciando correção FINAL de localizações...")
    
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    # Busca TODOS os itens com localização preenchida
    cursor.execute("SELECT id, part_number, local_armazenagem FROM inventario WHERE local_armazenagem IS NOT NULL AND local_armazenagem != ''")
    itens = cursor.fetchall()
    
    atualizacoes = []
    
    for item in itens:
        local_orig = item['local_armazenagem']
        local_novo = normalizar_forcado(local_orig)
        
        # Só atualiza se mudou E se o novo formato for válido (não nulo)
        if local_novo and local_novo != local_orig:
            atualizacoes.append({
                'id': item['id'],
                'pn': item['part_number'],
                'origem': local_orig,
                'destino': local_novo
            })
            
            cursor.execute(
                "UPDATE inventario SET local_armazenagem = ? WHERE id = ?",
                (local_novo, item['id'])
            )
            
    conn.commit()
    conn.close()
    
    if not atualizacoes:
        print("✅ Nenhuma correção necessária. Todas as localizações estão padronizadas.")
    else:
        print(f"\n📊 Resumo da Correção Final: {len(atualizacoes)} itens atualizados.\n")
        print("-" * 80)
        print(f"{'PN':<15} {'Origem':<20} {'Destino':<20}")
        print("-" * 80)
        
        for u in atualizacoes:
            print(f"{u['pn']:<15} {u['origem']:<20} {u['destino']:<20}")
            
        print("-" * 80)
        print("✅ Correção concluída! Verifique o sistema agora.")

if __name__ == "__main__":
    main()