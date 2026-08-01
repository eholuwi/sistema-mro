# -*- coding: utf-8 -*-
"""Conteúdo da Central de Ajuda (v2.11.0) — dados PUROS, sem streamlit.

Separado da UI para (a) manter `app.py` enxuto e (b) permitir testar a COMPLETUDE do
manual (todo item tem explicação normal + versão "criança"). A UI (`app.py`) apenas
renderiza estas estruturas.

- `GUIAS_PERSONA`: guias rápidos por perfil (markdown).
- `MANUAL`: manual tela a tela. Cada item explica, para um elemento da interface
  (botão/card/gráfico/aba): **para que serve · com base em quê (fonte do dado) · como o
  sistema calcula**, mais `crianca` = a mesma ideia explicada de forma simples (ELI5),
  com foco especial em cálculos e dashboards.
"""

# ══════════════════════════════════════════════════════════════════════════════
# GUIAS RÁPIDOS POR PERFIL ("Começar aqui")
# ══════════════════════════════════════════════════════════════════════════════

GUIAS_PERSONA = {
    "assistente": """
### :material/menu_book: Assistente de Materiais (Almoxarifado)

Você cuida do **físico**: dá baixa, recebe, confere e consulta os materiais. O sistema é
seu **apoio** — a base do Compras (mínimo/máximo/categoria) fica intocada.

**1. Dar baixa — `:material/sync: Movimentação` → `:material/assignment: Requisição`**
- Preencha o cabeçalho (setor, emitente, centro de custo).
- Pesquise o item (o card mostra o **DISPONÍVEL**), informe *Qtd Solicitada/Atendida* e
  **Adicione à lista**; ao final, **registre a requisição**.
- Isso é o **consumo real** — alimenta cobertura, giro e o padrão de demanda.

**2. Receber material — `:material/sync: Movimentação` → `:material/inventory_2: Receber Material`**
- Dois modos: **Por Material** (começa pelo item) ou **Por SC / PO** (escolhe a SC e
  recebe **todos os itens pendentes** de uma vez).
- Informe a quantidade **na unidade de compra** (ex.: litros). Se houver **conversão**, o
  sistema mostra o preview (ex.: *5 L ÷ 5 = +1 GL*) e soma já convertido.
- Viu **:material/warning: revisar unidade**? Avise o comprador para cadastrar o fator.

**3. Contagem física — `:material/assignment: Saldo em Estoque` → `Realizar Contagem Física`**
- Informe a quantidade real, o **local (1ª e 2ª locação)** e observações; a diferença vira
  ajuste (não conta como consumo).

**4. Consultar — `:material/badge: Ficha 360`** — tudo do item numa tela.

**5. Status:** 🔴 Comprar · 🟡 Atenção · 🟢 OK · ⚪ Sem Movimentação (nunca consumido).
""",
    "comprador": """
### :material/shopping_cart: Comprador

Você **decide e cria as SCs**. O sistema **recomenda**, você confirma — nunca o contrário.

**1. O que repor — `:material/receipt_long: Controle de SC` → `:material/psychology: Assistente de Reposição`**
- Fila **priorizada** (🔴/🟠/🟡) com **"Comprar até DD/MM"** por item.
- **Selecione** os itens e crie **SCs sugeridas agrupadas por Tipo do material** (com
  título, justificativa de ~2 meses e centro de custo) — multi-item em 1 clique.

**2. Escolher fornecedor — `:material/badge: Ficha 360` → `:material/apartment: Fornecedores`**
- Último preço, moeda, nº de compras, lead time por fornecedor e o **⭐ melhor preço**.

**3. Curar conversão — `:material/add: Cadastro de Itens`** — quando compra em unidade diferente da de
estoque (ex.: GL × L), marque **"Este material é comprado em uma unidade diferente da
unidade de estoque"** e informe a **unidade de compra** e o **fator** (o sistema sugere).

**4. Ler a demanda — `:material/badge: Ficha 360` / `:material/assignment: Saldo em Estoque`** — **Padrão de demanda** e **XYZ**
ajudam a escolher a política de compra. É **diagnóstico**, não muda a lista sozinho.

**5. Atualizar dados — `:material/download: Importar Relatório de SCs`** — atualiza SCs, preços, fornecedores
e unidades (backup automático).

> **Princípio:** o sistema é **assistente, não piloto automático** — toda SC é sua decisão.
""",
}


# ══════════════════════════════════════════════════════════════════════════════
# MANUAL DO SISTEMA (tela a tela)
# ══════════════════════════════════════════════════════════════════════════════


def _item(nome, para_que, base, como, crianca):
    return {"nome": nome, "para_que": para_que, "base": base, "como": como, "crianca": crianca}


MANUAL = [
    {
        "tela": ":material/bar_chart: Dashboard",
        "intro": "A tela de abertura, com **abas por público** no topo (mesmo padrão de "
        "Controle de SC / Movimentação): cada perfil "
        "(:material/person: Comprador · :material/warehouse: Almoxarifado) vê só o que importa "
        "para o seu trabalho.",
        "itens": [
            _item(
                "Abas de visão (:material/person: Comprador · :material/warehouse: Almoxarifado)",
                "Trocar o painel inteiro conforme quem está olhando — sem poluir o menu lateral.",
                "A aba escolhida; o conteúdo é montado só para aquele público.",
                "Ao abrir uma aba, o sistema monta os cartões e gráficos daquela visão. "
                "**Comprador** = ação (o que comprar); **Almoxarifado** = o painel operacional "
                "completo (saúde do estoque, movimento do dia, números do ano e capital parado).",
                "É como trocar de canal na TV: o mesmo aparelho, mas cada canal mostra o programa "
                "certo para quem está assistindo.",
            ),
            _item(
                "Visão :material/person: Comprador — 'o que fazer agora'",
                "Dar ao comprador a lista de ação do dia: o que está crítico, atrasado, em ruptura, "
                "a fila de reposição e as SCs já agrupadas.",
                "A fila do Assistente de Reposição, as SCs abertas e as saídas reais.",
                "Os cartões contam **Críticos**, **Comprar até atrasados** (o prazo-limite já "
                "passou), **SCs abertas** e **Rupturas** (consumo real e estoque = 0). Abaixo, a "
                "**fila priorizada** com 'Comprar até DD/MM', as **SCs sugeridas** agrupadas por "
                "natureza e o **aging** (há quantos dias cada SC está aberta).",
                "É a lista de tarefas do comprador: 'compre isso primeiro, isso está atrasado, "
                "isso já acabou' — tudo mastigado, é só decidir.",
            ),
            _item(
                "Visão :material/warehouse: Almoxarifado — status dos itens, movimento do dia e demanda",
                "Detalhar a saúde do estoque: quantos itens em cada status, quem mais consome e "
                "como a demanda se comporta.",
                "As saídas reais (por requisição), os preços de referência e as requisições.",
                "**Status dos itens** conta OK/Atenção/Críticos/Sem Movimentação/Zerados/"
                "Inventariado (base de compra) e, na linha seguinte, o status FÍSICO de todo o "
                "material. **Entradas/Saídas** mostram hoje/semana/mês. **Top 10 Consumidores** "
                "ordena por quantidade consumida no mês anterior. **Requisições por Setor / Top "
                "Emitentes** mostram quem mais pede. **Padrões de demanda** classifica cada item "
                "por Syntetos-Boylan (Suave/Intermitente/Errático/Irregular) + resumo XYZ — é "
                "**diagnóstico**, não muda a lista de compra.",
                "É o 'raio-x' do estoque: quantos estão em cada cor, quem mais pede material e "
                "quais itens saem sempre igual ou 'do nada'.",
            ),
            _item(
                "Visão :material/warehouse: Almoxarifado — Ano corrente (Consumido · Requisições · Itens)",
                "Dar o panorama do ano em três números, no mesmo painel do dia a dia.",
                "As saídas REAIS valoradas (por requisição) — ajuste de inventário não entra.",
                "**Consumido no Ano** = Σ(quantidade saída × preço de referência) de 1º/jan até "
                "hoje. **Requisições Atendidas no Ano** = nº de requisições com consumo real. "
                "**Itens Movimentados no Ano** = quantos materiais diferentes tiveram saída. Ao "
                "lado, o **Consumo por Tipo de Material** mostra onde o dinheiro se concentra.",
                "É o resumo do ano: quanto saiu de dinheiro, quantos pedidos foram atendidos e "
                "quantos materiais diferentes se mexeram.",
            ),
            _item(
                "Visão :material/warehouse: Almoxarifado — capital parado e falhas de abastecimento",
                "Mostrar onde há dinheiro dormindo no estoque e onde o abastecimento falhou.",
                "A valoração do estoque (último preço), o giro por item e as movimentações de 90 dias.",
                "**Tendência de Consumo** compara os últimos 30 dias com os 30 anteriores (±15%). "
                "**Top Capital Parado** = maior valor em estoque COM giro 0. **Maior Valor em "
                "Estoque** = quem mais imobiliza capital hoje, com giro ou sem. **Top Itens com "
                "Divergências** = ajustes manuais frequentes (erro de processo). **Ruptura de "
                "Estoque** = itens que zeraram durante uma requisição. Valores são **estimativas** "
                "pelo último preço conhecido — não substituem o custo contábil.",
                "É a parte que mostra dinheiro parado e onde faltou material — o que dá pra "
                "melhorar sem comprar mais nada.",
            ),
        ],
    },
    {
        "tela": ":material/assignment: Saldo em Estoque",
        "intro": "A lista completa dos materiais, com filtros, status e a contagem física.",
        "itens": [
            _item(
                "Filtros (busca, importância, tipo, status, inventariado)",
                "Encontrar rapidamente um grupo de itens (ex.: só os 🔴 COMPRAR, ou de um setor).",
                "Os campos de cada item do inventário.",
                "Cada filtro afina a tabela abaixo; combinam-se entre si. O contador mostra "
                "'exibindo X de Y itens'.",
                "São peneiras: você escolhe o que quer ver e a lista encolhe só pro que importa.",
            ),
            _item(
                "Coluna 'Status Material' (🔴🟡🟢⚪)",
                "Dizer, num relance, o que fazer com o item.",
                "Estoque atual vs. mínimo do item, e se ele tem **consumo real** (requisição).",
                "**🔴 Comprar** = estoque ≤ mínimo E teve consumo real; **🟡 Atenção** = perto do "
                "mínimo; **🟢 OK** = acima do mínimo; **⚪ Sem Movimentação** = nunca teve saída "
                "por requisição (sai da lista de compra, mesmo zerado).",
                "É um semáforo: vermelho = precisa comprar, amarelo = fica de olho, verde = "
                "tranquilo, branco = esse nunca foi usado de verdade.",
            ),
            _item(
                "Colunas 'Un?', 'Demanda' e 'XYZ'",
                "Sinalizar unidade a revisar (:material/warning:) e mostrar o padrão de demanda e a variabilidade.",
                "'Un?' vem da unidade de compra observada nos pedidos vs. a de estoque; 'Demanda' "
                "e 'XYZ' vêm das saídas reais.",
                "**Un? :material/warning:** = comprado em unidade diferente da de estoque e ainda sem fator de "
                "conversão. **Demanda** e **XYZ** são diagnósticos (detalhe na Ficha 360).",
                "Um alerta ':material/warning:' que diz 'confere a unidade desse aqui', e duas etiquetas que "
                "dizem se o item é fácil ou difícil de prever.",
            ),
            _item(
                "Realizar Contagem Física",
                "Corrigir o estoque do sistema para bater com o que existe na prateleira.",
                "A quantidade real que você conta e informa.",
                "Grava a diferença como um ajuste no histórico (entrada/saída) — **não** conta "
                "como consumo real (não distorce os indicadores).",
                "Você conta de verdade na prateleira e escreve o número certo; o sistema anota a "
                "diferença sem confundir com 'gasto'.",
            ),
            _item(
                "Botão 'Exportar' (Excel)",
                "Levar a lista para fora do sistema (análise, reunião, backup).",
                "A mesma lista de itens, com indicadores calculados.",
                "Gera um .xlsx com todas as colunas (incluindo Padrão Demanda e Classe XYZ).",
                "Um botão que salva a tabela num arquivo de Excel pra você abrir onde quiser.",
            ),
        ],
    },
    {
        "tela": ":material/badge: Ficha 360",
        "intro": "Toda a vida de um material numa tela só (somente leitura, exceto a imagem).",
        "itens": [
            _item(
                "Cartões de estoque (Atual/Mínimo/Máximo/Segurança/Saldo Residual)",
                "Mostrar de uma vez a posição do item.",
                "Cadastro do item (base do Compras) + saldos de SCs abertas.",
                "**Saldo Residual (Guarda-Chuva)** = soma do que já foi negociado em SCs abertas "
                "e ainda vai chegar. Clique em 'Ver detalhes' para ver os pedidos com saldo e o "
                "saldo residual por fornecedor. Mínimo/Máximo/Segurança vêm da base do Compras "
                "(o sistema não sobrescreve).",
                "É a 'ficha de saúde' do item: quanto tem, quanto precisa ter no mínimo, e quanto "
                "já está a caminho (o 'saldo residual' que protege da falta).",
            ),
            _item(
                "Cobertura, Consumo/dia, Giro e Lead time",
                "Dizer por quantos dias o estoque dura e o ritmo de consumo.",
                "Saídas reais (por requisição) e as fotos diárias de estoque (snapshots).",
                "**Cobertura** = estoque atual ÷ consumo por dia. **Consumo/dia** = "
                "média das saídas na janela (30 dias). **Giro anual** = quantas vezes o estoque "
                "'roda' no ano (pelas fotos). **Lead time** = prazo do fornecedor.",
                "Cobertura é 'quantos dias ainda dá pra durar'. Consumo/dia é 'quanto sai por "
                "dia'. Giro é 'quantas vezes o estoque se renova no ano'.",
            ),
            _item(
                "Recomendação de reposição",
                "Dizer se precisa comprar agora e quanto.",
                "Consumo, lead time, estoque de segurança, estoque e guarda-chuva.",
                "Dispara quando (estoque + guarda-chuva) fica perto do **ponto de reposição** = "
                "consumo/dia × lead time + segurança, com 15 dias de antecedência. A quantidade "
                "mira um alvo = max(máximo do Compras, consumo × 60 dias).",
                "O sistema calcula 'quando vai faltar' e avisa com antecedência: 'compre até tal "
                "dia, mais ou menos essa quantidade' — mas quem decide é você.",
            ),
            _item(
                "Padrão de demanda & variabilidade (Demanda / XYZ / Sazonalidade)",
                "Explicar o COMPORTAMENTO da demanda para escolher a política de compra.",
                "As saídas reais por requisição (por semana para a Demanda, por mês para o XYZ).",
                "**Demanda (Syntetos-Boylan)**: olha o intervalo entre saídas (ADI) e o quanto o "
                "tamanho varia (CV²) → Suave/Intermitente/Errático/Irregular. **XYZ**: variação "
                "do consumo mensal → X (estável)/Y/Z (errático). **Sazonalidade** só com ≥12 "
                "meses de histórico. Tudo com rótulo de confiança; é diagnóstico.",
                "O sistema percebe se o material 'sai certinho toda semana' ou 'do nada, um "
                "montão'. Isso ajuda a decidir se dá pra confiar numa regra simples ou não. "
                "Como só temos poucos meses, ele avisa que a certeza ainda é baixa.",
            ),
            _item(
                "Valor, ABC, evolução de preço e 'Quem consome'",
                "Mostrar o lado financeiro e quem usa o item.",
                "Preços do Relatório de SCs e as saídas por centro de custo/setor.",
                "**Valor em estoque** = estoque × preço de referência. **ABC** = classe pelo "
                "valor consumido. **Quem consome** agrega as saídas reais por centro de custo.",
                "Mostra quanto vale o que está guardado, se é um item 'caro' (A) ou 'barato' (C) "
                "no total, e quais setores mais usam.",
            ),
        ],
    },
    {
        "tela": ":material/sync: Movimentação → Requisição",
        "intro": "Aba da Movimentação onde o almoxarifado dá baixa (entrega material para quem pediu).",
        "itens": [
            _item(
                "Cabeçalho (setor, emitente, centro de custo, autorizador)",
                "Registrar quem está pedindo e para onde vai o material.",
                "As listas mestras (setores, centros de custo) e o que você digita.",
                "Identifica a requisição; o centro de custo é usado depois no 'Quem consome'.",
                "É preencher 'quem pediu e pra qual área' antes de entregar.",
            ),
            _item(
                "Adicionar materiais + card DISPONÍVEL",
                "Escolher os itens e ver na hora se tem em estoque.",
                "O estoque atual do item selecionado.",
                "O card mostra o disponível; você informa Qtd Solicitada e Atendida e adiciona à "
                "lista da requisição.",
                "Você procura o material e o sistema já diz 'tem tantos aí'. Aí você põe quantos "
                "vai entregar.",
            ),
            _item(
                "Registrar requisição",
                "Efetivar a baixa e contar como consumo real.",
                "Os itens adicionados.",
                "Grava a saída com vínculo de requisição — é isso que o sistema entende como "
                "**consumo real** (base de cobertura, giro, demanda).",
                "É o botão que confirma a entrega. A partir daí o sistema sabe que aquilo foi "
                "'gasto de verdade'.",
            ),
        ],
    },
    {
        "tela": ":material/receipt_long: Controle de SC",
        "intro": "O centro do comprador: solicitações, reposição, consulta ao SCM e importação. "
        "(O **recebimento** mudou para a **Movimentação → Receber Material**; os "
        "**fornecedores por item** ficam na **Ficha 360**.)",
        "itens": [
            _item(
                "Aba 'Assistente de Reposição' — fila e 'Comprar até'",
                "Dizer o que repor, com que prioridade e até quando comprar.",
                "Estoque, guarda-chuva, consumo, lead time e estoque de segurança de cada item.",
                "Prioriza 🔴/🟠/🟡; **Comprar até** = hoje + cobertura − lead time − 15 dias de "
                "antecedência. Item **sem consumo nunca é 🔴** (não há relógio de ruptura).",
                "É uma lista de tarefas de compra, já em ordem de urgência, com a data limite pra "
                "pedir cada coisa sem deixar faltar.",
            ),
            _item(
                "Aba 'Assistente' — SCs sugeridas agrupadas",
                "Juntar itens numa SC pronta, por Tipo do material e centro de custo, em 1 clique.",
                "O Tipo do material cadastrado em cada item e o consumo por CC.",
                "Agrupa os itens da fila pelo **Tipo do material** (campo do cadastro) e "
                "sugere o centro de custo; você cria a SC multi-item de uma vez.",
                "Em vez de montar pedido item por item, o sistema já monta 'cestinhas' prontas "
                "por tipo de material pra você só confirmar.",
            ),
            _item(
                "Aba 'SCM Integrado'",
                "Consultar as SCs de forma unificada e sincronizar com a API do SCM.",
                "As SCs já gravadas no banco — pelo Relatório de SCs (Excel) e/ou pela API.",
                "Lista **Solicitações de Compra**, **Itens das SCs** e o **Detalhe** de cada SC "
                "(itens, itens fora do inventário e preços históricos). O botão **Atualizar "
                "agora** é o único ponto que toca a rede — abrir a aba não consulta a API.",
                "É a tela onde você procura uma SC e vê tudo dela, mesmo que ela não tenha vindo "
                "da planilha do dia.",
            ),
            _item(
                "Aba 'Importar Relatório de SCs'",
                "Atualizar o sistema com os dados mais recentes de compras.",
                "A planilha 'Relatório de SCs' (abas SCM/SC7/Fornecedores/Users).",
                "Faz **backup automático** e depois atualiza SCs, preços, fornecedores, lead "
                "times e unidades (upsert — nada é apagado).",
                "É o botão que 'sincroniza' o sistema com a planilha do dia. Ele guarda uma cópia "
                "de segurança antes, por via das dúvidas.",
            ),
        ],
    },
    {
        "tela": ":material/add: Cadastro de Itens",
        "intro": "Cadastro e edição de itens, incluindo a curadoria da conversão de unidades.",
        "itens": [
            _item(
                "Cadastro / edição do item",
                "Criar ou ajustar os dados de um material.",
                "O que você preenche + a base do Compras (na edição, preservada).",
                "Salva os campos; na edição, campos sensíveis usam COALESCE (só grava o que você "
                "confirmar, sem apagar o que já existe).",
                "É a ficha do produto: nome, unidade, categoria, local. Editar não apaga o que "
                "você não mexeu.",
            ),
            _item(
                "Conversão de unidades (checkbox → unidade de compra + fator)",
                "Ensinar o sistema a converter quando compra e estoque usam unidades diferentes.",
                "Sugestão vinda do nome do item (ex.: 'C/ 5 LT') e das unidades vistas nos pedidos.",
                "Os campos só aparecem quando você marca **'Este material é comprado em uma "
                "unidade diferente da unidade de estoque'** — no caso comum a tela não pergunta "
                "nada. Na edição o checkbox **já vem marcado** se o item tem conversão gravada. "
                "**Fator** = quantas unidades de compra cabem em 1 de estoque (ex.: 1 GL = 5 L → "
                "fator 5). O sistema **sugere**, você **confirma** — nunca sobrescreve sozinho. "
                "No recebimento, a entrada vira qtd ÷ fator.",
                "Você conta pro sistema 'nesse galão cabem 5 litros'. Aí quando chegam 5 litros, "
                "ele sabe que é 1 galão. Ele adivinha o número, mas quem confirma é você.",
            ),
        ],
    },
    {
        "tela": ":material/sync: Movimentação",
        "intro": "O centro do almoxarifado físico: **Receber Material**, **Requisição**, "
        "**Ajuste Rápido** e **Histórico Completo** — tudo que entra e sai.",
        "itens": [
            _item(
                "Histórico Completo + Relatório de Movimentações",
                "Auditar o que entrou e saiu, e exportar o rateio mensal por CC/Setor.",
                "O histórico de movimentações, com a categoria derivada (requisição, ajuste, "
                "devolução, perda, conferência).",
                "Filtra por item, categoria e limite de tela; a **exportação** recorta por "
                "período e sai inteira (sem teto silencioso), com cada informação em sua coluna. "
                "Os gráficos de tendência, divergência e ruptura ficam no **Dashboard → "
                "Almoxarifado**.",
                "É o extrato do almoxarifado: tudo que entrou e saiu, com filtro, e o botão de "
                "baixar a planilha do mês.",
            ),
            _item(
                "Aba 'Receber Material' (com conversão)",
                "Dar entrada no estoque quando o material chega (v3.8.0: veio do Controle de SC).",
                "O item da SC e o fator de conversão cadastrado.",
                "Dois modos — **Por Material** ou **Por SC / PO**. Você digita a quantidade **na "
                "unidade de compra**; o estoque sobe já convertido: **incremento = qtd ÷ fator** "
                "(ex.: 5 L ÷ 5 = +1 GL). O saldo da SC segue na unidade de compra.",
                "Chegou a mercadoria? Você diz quanto veio (em litros, por exemplo) e o sistema "
                "guarda na conta certa (galões), sem você fazer conta.",
            ),
        ],
    },
    {
        "tela": ":material/settings: Configurações",
        "intro": "Organizada em **abas**: Aparência · Backup · Importar Base · Solicitantes "
        "MRO · Listas Mestras · **Ajuda** (a Central de Ajuda passou a morar aqui).",
        "itens": [
            _item(
                ":material/palette: Aparência (tema claro/escuro)",
                "Escolher entre o visual claro (padrão) e o escuro.",
                "A sua escolha, guardada na URL (?tema=).",
                "O botão da **barra lateral** troca o tema; fundo, textos, menu e gráficos "
                "acompanham. As tabelas seguem o tema base (claro) — no escuro podem ficar claras.",
                "Um botão de 'dia e noite' pro sistema. Começa no claro; se você preferir escuro, "
                "é só clicar.",
            ),
            _item(
                "Importar Base (Tipo/Mínimo/Máximo/Lead Time)",
                "Atualizar os itens com os dados apurados pelo Compras.",
                "A planilha do Compras (casada pelo Part Number).",
                "Atualiza apenas itens **existentes** (PNs não encontrados são só relatados); faz "
                "**backup** antes. Tem prévia (simulação) antes de aplicar.",
                "Sobe a planilha do especialista e o sistema atualiza os números certos, "
                "mostrando antes o que vai mudar.",
            ),
            _item(
                "Listas Mestras (centros de custo, locais, fornecedores...)",
                "Manter as opções que aparecem nos formulários.",
                "A tabela de listas do sistema.",
                "Adiciona/remove valores usados nos selects (centro de custo, local, etc.). "
                "As 5 listas ficam em sub-abas dentro da aba **Listas Mestras**.",
                "É onde você cadastra as 'opções fixas' que aparecem nas listinhas dos formulários.",
            ),
            _item(
                "Aba :material/help: Ajuda (Central de Ajuda)",
                "Consultar os guias por perfil, o Manual do Sistema e enviar feedback.",
                "Este manual + o backlog de feedback gravado no banco.",
                "Era um item próprio do menu lateral e virou aba daqui, para encurtar a navegação. "
                "Traz **Começar aqui** (guia por perfil), **Manual do Sistema** (esta tela a tela, "
                "com modo de linguagem simples), **Enviar Feedback** e **Backlog**.",
                "É o 'manual de instruções' do sistema, junto do lugar onde você configura ele.",
            ),
        ],
    },
]


# ══════════════════════════════════════════════════════════════════════════════
# AJUDA_DADOS — Textos para drill-down de métricas (v4.2.0)
# ══════════════════════════════════════════════════════════════════════════════

AJUDA_DADOS = {
    # Dashboard Comprador
    "itens_em_aberto": "**O que é:** Itens com SC/PO aberta e quantidade ainda pendente de recebimento. "
    "**Para que serve:** Monitorar o que está a caminho. "
    "**Como é feito:** Conta SCs e POs com status ≠ 'Finalizado' e qtd_pendente > 0.",
    "fornecedores_aberto": "**O que é:** Fornecedores com pedidos em aberto, ordenados por valor. "
    "**Para que serve:** Priorizar Follow-ups e negociações. "
    "**Como é feito:** Agrupa itens em aberto por fornecedor, soma valores das POs pendentes.",
    "setores_demanda_aberta": "**O que é:** Setores com mais requisições em aberto aguardando material. "
    "**Para que serve:** Identificar qual setor está com mais demanda represada. "
    "**Como é feito:** Conta requisições com status 'Aberta' ou 'Parcial' por setor.",
    # Dashboard Almoxarifado
    "dist_ok": "**O que é:** Itens com estoque adequado para cobrir a demanda prevista. "
    "**Para que serve:** Confirmar que esses materiais podem ser usados livremente. "
    "**Como é feito:** Estoque atual ≥ mínimo E dias de cobertura ≥ dias de segurança.",
    "dist_atencao": "**O que é:** Itens com estoque acima do mínimo, mas com cobertura curta (demanda alta ou lead time longo). "
    "**Para que serve:** Sinal de atenção — pode virar crítico se não houver reposição em tempo. "
    "**Como é feito:** Estoque ≥ mínimo, mas dias de cobertura < dias de segurança.",
    "dist_critico": "**O que é:** Itens com estoque abaixo do mínimo — risco iminente de ruptura. "
    "**Para que serve:** Ação imediata — conferir a demanda e acionar compras. "
    "**Como é feito:** Estoque atual < mínimo.",
    "cobertura_dias": "**O que é:** Quantos dias o estoque atual cobre a demanda média (consumo/dia). "
    "**Para que serve:** Prever quando o material acaba e planejar reposição. "
    "**Como é feito:** Estoque atual ÷ consumo médio diário (últimos 30 dias).",
    "top_consumo": "**O que é:** Itens com maior consumo (em quantidade ou valor) no período. "
    "**Para que serve:** Entender quais materiais movem a operação — foco em reposição e acompanhamento. "
    "**Como é feito:** Soma de saídas (requisições) no período, ordenado decrescente.",
    "entradas_saidas": "**O que é:** Volume de material que entrou (recebimentos) e saiu (requisições/ajustes) em um período. "
    "**Para que serve:** Monitorar fluxo operacional — giro, rupturas e divergências. "
    "**Como é feito:** Contagem de movimentações por tipo (entrada/saída) e período (dia/semana/mês).",
}
