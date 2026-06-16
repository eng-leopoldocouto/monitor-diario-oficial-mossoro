# Correção da detecção de páginas por portaria no PDF

**Data:** 2026-06-16
**Arquivo afetado (principal):** `src/pdf.py` — `extrair_pdfs_por_ocorrencia`

## Problema

Ao fatiar o PDF do Diário Oficial por portaria, algumas portarias saem com uma
página a mais do que deveriam. Caso observado: a **PORTARIA Nº 47** (edição 841 /
publicação 1876) ocupa apenas 1 página, mas o PDF gerado saiu com 2 páginas.

## Causa raiz

A função define o fim de uma portaria como **a posição do próximo cabeçalho
`PORTARIA Nº <n>,`** no texto do PDF (`src/pdf.py:144-149`) e inclui toda página
cujo intervalo de texto se sobrepõe a `[start_pos, end_pos)` (`src/pdf.py:154-159`).

O texto do PDF não tem noção de colunas — opera só por página e por posição de
caractere. Quando, **depois** da portaria e **antes** da próxima portaria, vêm
atos de outro tipo (EXTRATO, TERMO, AVISO, ADITIVO…), o detector não encontra
fronteira ali. Na edição 1876, depois da PORTARIA Nº 47 vêm EXTRATO DE CONTRATO,
TERMO DE ADESÃO, EXTRATO DE ADITIVO e TERMO DE RATIFICAÇÃO — nenhum casa com
`PORTARIA Nº ...,`. O próximo `PORTARIA Nº` é a **Nº 25**, já na página seguinte.
Resultado: `end_pos` cai na página seguinte e ela é incluída por engano.

A PORTARIA Nº 47 está, na verdade, completa numa página só (termina com o bloco de
assinatura "JOSENILDO GOMES DA FONSECA / SECRETARIO MUNICIPAL DE INFRAESTRUTURA").

## Decisão de projeto

Quando a fronteira for ambígua, priorizar **precisão usando a segmentação que o
HTML já fornece**, com uma cadeia de segurança para não regredir o comportamento
atual em caso de falha de localização (escolha "equilíbrio").

## Abordagem escolhida

Trocar a fronteira de "próximo `PORTARIA Nº ...,`" por **"início do ato seguinte
na ordem real do Diário"**. Essa ordem já existe: `extrair_portarias` (em
`src/scraping.py`) separa todos os atos via `ato_separator` e devolve a lista
`portarias` ordenada — disponível no ponto de chamada
(`monitor_diario_oficial.py:157`, lista criada na linha 105).

Mecânica:

1. `extrair_pdfs_por_ocorrencia(url_pdf, ocorrencias, portarias=None)` — novo
   parâmetro **opcional** (default `None`); com `None` mantém o comportamento
   atual (nenhuma chamada/teste existente quebra).
2. Atualizar a chamada em `monitor_diario_oficial.py:157` para passar `portarias`.
3. Para a portaria atual, achar seu índice na lista ordenada e pegar o **título
   do ato imediatamente seguinte** (portaria, extrato, termo, etc.).
4. `start_pos` = posição do título da portaria no texto do PDF (inalterado).
5. `end_pos` = posição do **título do próximo ato** no texto do PDF, procurada a
   partir de `start_pos` (texto normalizado: NFKD sem acento + maiúsculas, igual
   ao restante da função).
6. Seleção de páginas por sobreposição de intervalo — **inalterada**
   (`src/pdf.py:154-159`).

### Cadeia de segurança (o "equilíbrio")

Se o título do próximo ato **não for localizável** no texto do PDF:
- (a) cai para o próximo `PORTARIA Nº ...,` (lógica atual); se também não houver,
- (b) cai para o fim do documento.

Na dúvida, mantém o comportamento atual — que erra incluindo páginas a mais, nunca
a menos. Portarias que realmente viram a página continuam corretas: o título do
próximo ato simplesmente estará na página seguinte.

## Melhoria de testabilidade

Extrair o cálculo de páginas para uma função pura, ex.:

```
_paginas_da_portaria(combined, page_offsets, titulo_norm, titulos_ordenados_norm) -> list[int]
```

Isso permite testar a lógica de fronteira com strings sintéticas, sem montar PDFs
reais (os testes atuais usam páginas em branco e não cobrem este cenário).

## Validação contra dados reais

Edição: `https://dom.mossoro.rn.gov.br/dom/publicacao/1876` (DOM nº 841, PDF de 10
páginas). Simulação das duas lógicas:

| Portaria | Lógica atual | Proposta | Esperado |
|----------|--------------|----------|----------|
| Nº 45    | `[8, 9]`     | `[8, 9]` | 2 páginas ✅ |
| Nº 47    | `[9, 10]` ❌ | `[9]`    | 1 página ✅ |

Em ambos a proposta usou o método "próximo-ato" (sem precisar do fallback):
- Nº 45 → próximo ato = PORTARIA Nº 46 (página 9) → mantém `[8, 9]`.
- Nº 47 → próximo ato = EXTRATO DE CONTRATO (página 9) → reduz para `[9]`.

## Plano de testes

1. **Regressão (cenário 47):** dado `combined`/`page_offsets` sintéticos onde uma
   portaria é seguida por atos não-portaria na mesma página e por outra portaria
   na página seguinte, a função pura deve retornar só a primeira página.
2. **Multi-página (cenário 45):** quando o próximo ato está na página seguinte, as
   duas páginas devem ser retornadas.
3. **Fallback:** quando o título do próximo ato não é localizável, deve recair em
   "próximo PORTARIA Nº" e depois no fim do documento.
4. **Compatibilidade:** com `portarias=None`, comportamento idêntico ao atual.

## Fora de escopo

- Detecção real de colunas no PDF.
- Reescrita da extração de texto do PDF (pypdf) ou da segmentação do HTML.
- Qualquer refatoração não relacionada à detecção de páginas por portaria.
