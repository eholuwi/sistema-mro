# Prompt — Migrar fotos da planilha "Material MRO 2026.xlsx" para o Sistema MRO

> **Como usar:** cole este prompt numa sessão nova do Claude/opencode dentro da pasta
> `C:\Users\luis.oliveira\Desktop\Tarefas Diárias\04_MRO System\sistema-mro`.
> Ele orienta a extração das fotos embutidas na planilha e a gravação no sistema em execução.
> Edite à vontade — versão 1, criada em 05/08/2026.

---

## Objetivo

Ler a planilha `Material MRO 2026.xlsx` (controle de estoque usado antes do Sistema MRO),
extrair **todas as imagens** de itens e **inputá-las no sistema MRO em execução** (campo
`inventario.imagem_path` + arquivos em `docs/itens/`), casando pelo Part Number.

NÃO criar itens novos sem autorização explícita. NÃO alterar nada do banco sem backup.

## Contexto técnico já levantado (05/08/2026)

- **Arquivo:** `sistema-mro\Material MRO 2026.xlsx` (118 MB).
- **Abas úteis:** `GERAL` (1402 linhas × 137 colunas — ITEM, PN, DESCRIÇÃO, UN, IMAGEM,
  TIPO, SETOR, MÍNIMO, ESTOQUE ATUAL + colunas diárias de saldo 2026-01-01→04-30) e
  `ENTRADA` (ITEM, PN, DESCRIÇÃO, IMAGEM, MÍNIMO, TOTAL, Saldo 2025 + colunas de
  recebimento por data). Demais abas (`GERAL TESTE`, `LISTA DE SOLICITAÇÃO POR PN`,
  `ETIQUETA IDENTIFICAÇÃO`, `DESCRIÇÃO DE MATERIAIS`, `MATERIAIS NA TENDA`) são
  auxiliares — só usar se o match de PN falhar e precisar cruzar descrição.
- **Imagens:** o `.xlsx` contém **403 PNGs** em `xl/media/` (402 são fotos de itens
  embutidas **em célula**, recurso "rich data" do Excel 365; 1 é o logo, em
  `xl/drawings/drawing6.xml` → `image403.png`, que deve ser **ignorado**).
  - O mapeamento foto→célula NÃO está nos drawings: as 402 fotos estão referenciadas em
    `xl/richData/richValueRel.xml` + `xl/richData/_rels/richValueRel.xml.rels`.
    Parseie o `richValueRel.xml` (ordem dos blocos `rel r:id="rIdN"`) e o `.rels`
    (rIdN → `imageNNN.png`) para descobrir a **ordem** das imagens; depois case essa
    ordem com a coluna IMAGEM das abas GERAL/ENTRADA (as fotos aparecem na ordem dos
    itens). Confirme a correspondência visual antes de gravar (amostra de 5).
  - Se o mapeamento por rich data se mostrar impraticável, plano B: extrair os 402
    PNGs em ordem e associar à sequência de linhas com PN na aba GERAL, validando por
    amostragem visual.
- **Casamento por PN:** 961 PNs únicos na aba GERAL; apenas **330** existem no
  `inventario` atual (362 itens). Normalizar SEMPRE com `UPPER(TRIM())` (e, se ainda
  faltar, descartar não-alfanuméricos). Os ~630 PNs sem correspondência devem ser
  **listados e reportados**, nunca inseridos sem autorização.

## Passos

1. **Leia antes de tocar:** `sistema-mro/CLAUDE.md`, `docs/HANDOFF.md` (seção STATUS
   ATUAL) e `services/ficha.py` (`salvar_imagem_item`, `caminho_absoluto_imagem`,
   `remover_imagem_item`). Regra de ouro: o `imagem_path` é relativo, do tipo
   `docs/itens/item_<id>.png`, e o arquivo vive ao lado do banco em `docs/itens/`.
2. **Backup obrigatório do banco** antes de qualquer gravação: use o mecanismo de
   backup do sistema (conferir `database._backup_db` / `services/backup.py`) e anote o
   caminho do `.bak` criado.
3. **Extraia as imagens** conforme o contexto acima, preservando a ordem e o mapeamento
   para a linha/PN. Salve num diretório temporário de trabalho (ex.: `build/planilha_imgs/`,
   FORA de `docs/itens/`).
4. **Casse por PN** normalizado contra `inventario` (`SELECT id, part_number FROM inventario`).
   Para cada item da planilha com foto e correspondência no banco, grave a foto:
   - ideal: reutilize `services/ficha.salvar_imagem_item(item_id, nome, bytes)` — ela
     valida formato/tamanho (≤5 MB, png/jpg/webp/gif), grava o arquivo e o
     `imagem_path` na mesma transação;
   - se alguma foto ultrapassar 5 MB, reencoda (Pillow) reduzindo para caber e registre.
5. **Não sobrescreva cegamente:** se o item JÁ tem `imagem_path` preenchido, compare as
   imagens e, se forem diferentes, **pare e pergunte** antes de trocar (não substituir
   sem OK explícito).
6. **Reporte ao final:** quantas fotos extraídas, quantas gravadas, quantos itens já
   tinham foto (pulados/em conflito), quantos PNs sem correspondência no inventário
   (listar). Não crie itens novos sem autorização.
7. **Validação:** abra o app (`streamlit run app.py`), confira 5 itens na Ficha 360 com
   foto e 2 sem. Depois rode `.\verify.ps1` (gate) e `graphify update .`.

## Regras

- Só o que a planilha tem que o sistema **não tem** é notícia: PNs sem foto, fotos sem
  PN, itens duplicados na planilha — tudo vai para o relatório final.
- Nada de adivinhar descrição/unidade/estoque da planilha: esta tarefa é **somente**
  sobre imagens. Estoque, mínimo, categoria etc. ficam fora.
- Preservar compatibilidade com `mro.db` (regra 1 do CLAUDE.md). Nenhuma alteração de
  schema.
