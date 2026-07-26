# Funcionalidades do Sistema MRO

Explicação das regras e cálculos que o sistema aplica. Para **onde** cada coisa está no
código, ver [`CLAUDE.md`](../CLAUDE.md); para o **estado atual** do desenvolvimento, ver
[`HANDOFF.md`](HANDOFF.md).

> Este documento descreve comportamento, não implementação. Quando divergirem, o código é a
> verdade — e a divergência é um bug de documentação a corrigir.

---

## Dashboard

Central de decisão operacional: KPIs de cobertura e dias até ruptura, itens críticos, SCs com
ação pendente, pendências de inventário e tendência de consumo.

### Cobertura Real

Diferente da cobertura ingênua, considera o que já foi comprado e ainda não chegou:

```
(Estoque Atual + Estoque em Trânsito) / Consumo Diário
```

Cruzando com o Lead Time, classifica em:

| | Situação |
|---|---|
| 🔴 | Risco de ruptura (≤ ROP) |
| 🟡 | Atenção operacional (antecedência de 15 dias) |
| 🟢 | Estoque seguro |

---

## Assistente de Reposição

Transforma dados em ações de compra.

- **ROP (Reorder Point)** = `consumo_diário × lead_time + estoque_segurança`
- **Gatilho com antecedência** — dispara 15 dias antes da ruptura prevista, não no dia
- **Quantidade sugerida híbrida** — o maior valor entre o piso cadastrado e 60 dias de consumo
- **Priorização** — crítico → antecipar → atenção
- **Agrupamento por fornecedor** — otimiza o pedido
- **Auditoria** — registra "Criar SC", "Adiar" e "Ignorar"

### Princípio: assistente, não piloto automático

O sistema **recomenda**, o comprador **decide**. A base de referência humana (mínimo, máximo,
lead time cadastrado) **nunca** é sobrescrita por cálculo automático — a sugestão aparece ao
lado do valor cadastrado, não no lugar dele.

---

## Ficha 360 do material

Consolida a vida inteira de um item numa tela: cadastro, estoque (atual/mínimo/máximo/segurança),
cobertura, consumo por período e por centro de custo, histórico de SCs e POs com lead time real
versus cadastrado, giro e valor consumido, classe ABC e evolução de preço, fornecedores,
imagem do produto e histórico de Part Number.

---

## Controle de SC — dois status independentes

A separação existe porque **saúde do estoque** e **andamento administrativo** são perguntas
diferentes: um item pode estar 🔴 no estoque e com a compra já ✅ concluída, ou 🟢 no estoque
com uma SC travada em cotação.

### Status Material (calculado)

| | Regra |
|---|---|
| 🟢 OK | Estoque acima da faixa de atenção |
| 🟡 ATENÇÃO | Até 20% acima do mínimo |
| 🔴 COMPRAR | Estoque ≤ mínimo **e com consumo real** |
| ⚪ Sem Movimentação | Nunca teve saída por requisição |

O "**e com consumo real**" do 🔴 é o que separa candidato de compra de item fantasma: sem ele,
a lista enche de material que ninguém usa. Foi o que reduziu a lista de compra em ~66%.

### Status SC (manual)

📢 Aprovação → ⚠️ Cotação → 🚚 Aguardando Entrega → ✅ Concluída

---

## Estoque em Trânsito (Guarda-Chuva)

Desconta do cálculo o que já foi pedido e ainda não chegou. Sem isso o sistema pediria de novo
o que já está a caminho.

- **Saldo residual** — quanto falta chegar de SCs anteriores
- **Recebimentos parciais** — múltiplas entregas do mesmo item
- **Desconto na sugestão** — protege contra duplicidade

Evita compra duplicada, excesso de estoque e falso alerta de ruptura.

---

## Inventário e rastreabilidade

Cada item tem local e caixa/ID. Toda alteração de localização gera histórico automático
(`20 UN ARM-12 → MRO-20`).

**Integridade:** movimentação que só muda localização, sem alterar quantidade, **não** entra na
curva ABC nem no consumo médio. Sem essa regra, uma reorganização do almoxarifado apareceria
como consumo e distorceria toda a análise.

---

## Previsão de ruptura

```
estoque_atual / consumo_diario
```

Dias restantes até faltar, assumindo o consumo médio observado.

---

## Importação do Protheus

Normaliza texto (remove acentos, padroniza nomenclatura) e previne duplicidade de item.

**Priorização automática:** palavras como *parada*, *urgente*, *crítica* e *linha* na descrição
elevam o item para 🔴 **Parada de Linha** na importação.

---

## Integração com a API do SCM

A partir da v5.1.0 a API do SCM é fonte primária, persistida no `mro.db`; o "Relatório de SCs"
em Excel virou fallback. A sincronização enriquece sem apagar: o que só existe no Excel é
preservado.

⚠️ Os códigos de status da API (`01/03/05/09`) são **inferidos** da documentação e ainda não
foram confirmados com dado real — o código cru fica guardado em `status_protheus`, então nada
se perde se o mapeamento estiver errado.
