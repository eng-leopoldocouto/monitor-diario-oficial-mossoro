# Correção da detecção de páginas por portaria — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fazer o PDF de cada portaria conter exatamente as páginas que ela ocupa, usando o início do PRÓXIMO ato (na ordem real do Diário) como fronteira, com fallback para o comportamento atual.

**Architecture:** Duas funções puras novas em `src/pdf.py` — `_prox_ato_titulo` (próximo ato na lista ordenada do HTML) e `_paginas_da_portaria` (cálculo das páginas com cadeia de fronteira: próximo ato → próximo `PORTARIA Nº` → fim do doc). `extrair_pdfs_por_ocorrencia` ganha o parâmetro opcional `portarias` e passa a delegar a essas funções. O ponto de chamada repassa a lista ordenada que já existe.

**Tech Stack:** Python 3.10+, pypdf, pytest. Testes em `test_monitor_diario_oficial.py` (importam `import monitor_diario_oficial as monitor`).

**Spec:** `docs/superpowers/specs/2026-06-16-deteccao-paginas-portaria-design.md`

> **Branch:** o repositório está em `master`. Antes da Task 1, crie um branch de trabalho:
> `git checkout -b fix/deteccao-paginas-portaria`

---

## File Structure

- **Modify** `src/pdf.py`
  - Novas funções módulo-level: `_prox_ato_titulo`, `_paginas_da_portaria`.
  - `extrair_pdfs_por_ocorrencia`: novo parâmetro `portarias=None`; substitui o cálculo inline de `end_pos`/páginas por chamadas às novas funções.
- **Modify** `monitor_diario_oficial.py`
  - Reexporta `_prox_ato_titulo` e `_paginas_da_portaria` no bloco `from src.pdf import (...)`.
  - Passa `portarias` na chamada de `extrair_pdfs_por_ocorrencia` (linha ~157).
- **Modify** `test_monitor_diario_oficial.py`
  - Novas classes de teste: `TestProxAtoTitulo`, `TestPaginasDaPortaria`, com um helper `_montar_combined`.

---

## Task 1: Função pura `_prox_ato_titulo`

**Files:**
- Modify: `src/pdf.py` (nova função módulo-level)
- Modify: `monitor_diario_oficial.py:54-56` (reexport)
- Test: `test_monitor_diario_oficial.py` (nova classe `TestProxAtoTitulo`)

- [ ] **Step 1: Escrever os testes que falham**

Adicione ao final de `test_monitor_diario_oficial.py`:

```python
# ══════════════════════════════════════════════════════════════
# 2c. _prox_ato_titulo e _paginas_da_portaria (detecção de páginas)
# ══════════════════════════════════════════════════════════════

class TestProxAtoTitulo:

    def test_retorna_titulo_do_ato_seguinte(self):
        p1 = {"titulo": "PORTARIA Nº 47,"}
        p2 = {"titulo": "EXTRATO DE CONTRATO"}
        portarias = [p1, p2]
        assert monitor._prox_ato_titulo(p1, portarias) == "EXTRATO DE CONTRATO"

    def test_ultimo_ato_retorna_none(self):
        p1 = {"titulo": "PORTARIA Nº 47,"}
        assert monitor._prox_ato_titulo(p1, [p1]) is None

    def test_sem_lista_retorna_none(self):
        assert monitor._prox_ato_titulo({"titulo": "X"}, None) is None

    def test_objeto_ausente_na_lista_retorna_none(self):
        p1 = {"titulo": "A"}
        outros = [{"titulo": "B"}, {"titulo": "C"}]
        assert monitor._prox_ato_titulo(p1, outros) is None
```

- [ ] **Step 2: Rodar os testes para confirmar que falham**

Run: `python -m pytest test_monitor_diario_oficial.py::TestProxAtoTitulo -v`
Expected: FAIL — `AttributeError: module 'monitor_diario_oficial' has no attribute '_prox_ato_titulo'`

- [ ] **Step 3: Implementar `_prox_ato_titulo` em `src/pdf.py`**

Adicione esta função em `src/pdf.py` logo **antes** de `def extrair_pdfs_por_ocorrencia(`:

```python
def _prox_ato_titulo(portaria: dict, portarias: list[dict] | None) -> str | None:
    """
    Título do ato imediatamente seguinte a `portaria` na lista ORDENADA de atos
    (a mesma que `extrair_portarias` produz, já segmentada via ato_separator).

    Retorna None quando: a lista não foi fornecida, `portaria` é o último ato, ou
    o objeto não está na lista. A comparação é por IDENTIDADE (`is`) — o dict da
    ocorrência é o mesmo objeto inserido na lista por buscar_nomes_em_portarias.
    """
    if not portarias:
        return None
    for i, ato in enumerate(portarias):
        if ato is portaria:
            return portarias[i + 1]["titulo"] if i + 1 < len(portarias) else None
    return None
```

Em `monitor_diario_oficial.py`, atualize o import (linhas 54-56) de:

```python
from src.pdf import (  # noqa: F401
    buscar_url_pdf, _sanitizar_nome_arquivo, extrair_pdfs_por_ocorrencia,
)
```

para:

```python
from src.pdf import (  # noqa: F401
    buscar_url_pdf, _sanitizar_nome_arquivo, extrair_pdfs_por_ocorrencia,
    _prox_ato_titulo,
)
```

> Importe **apenas** `_prox_ato_titulo` agora. `_paginas_da_portaria` será criada
> e adicionada ao import na Task 2 — adicioná-la aqui quebraria
> `import monitor_diario_oficial` (ImportError), pois ela ainda não existe.

- [ ] **Step 4: Rodar os testes para confirmar que passam**

Run: `python -m pytest test_monitor_diario_oficial.py::TestProxAtoTitulo -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add src/pdf.py monitor_diario_oficial.py test_monitor_diario_oficial.py
git commit -m "$(cat <<'EOF'
feat(pdf): adiciona _prox_ato_titulo para fronteira por ato seguinte

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: Função pura `_paginas_da_portaria`

**Files:**
- Modify: `src/pdf.py` (nova função módulo-level)
- Test: `test_monitor_diario_oficial.py` (nova classe `TestPaginasDaPortaria` + helper)

- [ ] **Step 1: Escrever os testes que falham**

Adicione ao final de `test_monitor_diario_oficial.py`:

```python
def _montar_combined(paginas_norm):
    """Replica o combined/page_offsets de extrair_pdfs_por_ocorrencia.

    Retorna (combined, page_offsets). page_offsets tem len == nº de páginas + 1
    (sentinela), com cada página separada por '\\n' (somando +1 ao offset)."""
    offsets = []
    pos = 0
    for t in paginas_norm:
        offsets.append(pos)
        pos += len(t) + 1
    offsets.append(pos)
    return "\n".join(paginas_norm), offsets


_RX_PORTARIA = re.compile(r'PORTARIA\s+N[Oº°]\s+\d+\s*,')


class TestPaginasDaPortaria:

    def test_portaria_seguida_de_outro_ato_fica_em_uma_pagina(self):
        # Cenário PORTARIA 47: termina na pág. 1; depois vêm extratos/termos;
        # o próximo PORTARIA só aparece na pág. 2.
        pg1 = ("PORTARIA NO 47, DE 12 DE JUNHO DE 2026\n"
               "ART 1 CONCEDER DIARIA AO SR FULANO\n"
               "MOSSORO-RN 12 DE JUNHO DE 2026\n"
               "EXTRATO DE CONTRATO\nCONTRATO NO 06/2026")
        pg2 = ("EXPEDIENTE\nPORTARIA NO 25, DE 15 DE JUNHO DE 2026\nART 1 ...")
        combined, offs = _montar_combined([pg1, pg2])
        all_port = [m.start() for m in _RX_PORTARIA.finditer(combined)]
        start = combined.find("PORTARIA NO 47,")

        pgs = monitor._paginas_da_portaria(
            combined, offs, start, "PORTARIA NO 47,",
            "EXTRATO DE CONTRATO", all_port,
        )
        assert pgs == [1]

    def test_sem_proximo_ato_recai_em_proxima_portaria(self):
        # Mesma montagem, mas prox_titulo_norm=None (lista não fornecida):
        # comportamento ANTIGO — inclui a pág. 2 indevidamente.
        pg1 = ("PORTARIA NO 47, DE 12 DE JUNHO DE 2026\nART 1 ...\n"
               "EXTRATO DE CONTRATO\nCONTRATO NO 06/2026")
        pg2 = ("EXPEDIENTE\nPORTARIA NO 25, DE 15 DE JUNHO DE 2026\n...")
        combined, offs = _montar_combined([pg1, pg2])
        all_port = [m.start() for m in _RX_PORTARIA.finditer(combined)]
        start = combined.find("PORTARIA NO 47,")

        pgs = monitor._paginas_da_portaria(
            combined, offs, start, "PORTARIA NO 47,", None, all_port,
        )
        assert pgs == [1, 2]

    def test_portaria_que_continua_inclui_duas_paginas(self):
        # Cenário PORTARIA 45: corpo continua na pág. 2; próximo ato (PORTARIA 46)
        # está na pág. 2 → as duas páginas entram.
        pg1 = ("PORTARIA NO 45, DE 12 DE JUNHO DE 2026\n"
               "ART 1 TEXTO LONGO QUE CONTINUA NA PROXIMA PAGINA")
        pg2 = ("CONTINUACAO DO ARTIGO\nMOSSORO-RN 12 DE JUNHO\n"
               "PORTARIA NO 46, DE 12 DE JUNHO DE 2026\nART 1 ...")
        combined, offs = _montar_combined([pg1, pg2])
        all_port = [m.start() for m in _RX_PORTARIA.finditer(combined)]
        start = combined.find("PORTARIA NO 45,")

        pgs = monitor._paginas_da_portaria(
            combined, offs, start, "PORTARIA NO 45,",
            "PORTARIA NO 46,", all_port,
        )
        assert pgs == [1, 2]

    def test_proximo_ato_nao_localizado_e_sem_proxima_portaria_vai_ate_fim(self):
        # prox_titulo existe na lista do HTML mas não é localizável no PDF, e não
        # há próximo PORTARIA → fallback final: fim do documento.
        pg1 = ("PORTARIA NO 99, DE 12 DE JUNHO DE 2026\nART 1 ...")
        pg2 = ("CONTINUACAO SEM CABECALHO DE PORTARIA")
        combined, offs = _montar_combined([pg1, pg2])
        all_port = [m.start() for m in _RX_PORTARIA.finditer(combined)]
        start = combined.find("PORTARIA NO 99,")

        pgs = monitor._paginas_da_portaria(
            combined, offs, start, "PORTARIA NO 99,",
            "PORTARIA NO 100,", all_port,  # 100 não aparece no texto
        )
        assert pgs == [1, 2]
```

- [ ] **Step 2: Rodar os testes para confirmar que falham**

Run: `python -m pytest test_monitor_diario_oficial.py::TestPaginasDaPortaria -v`
Expected: FAIL — `AttributeError: module 'monitor_diario_oficial' has no attribute '_paginas_da_portaria'`

- [ ] **Step 3: Implementar `_paginas_da_portaria` em `src/pdf.py`**

Adicione em `src/pdf.py` logo **antes** de `def extrair_pdfs_por_ocorrencia(` (junto de `_prox_ato_titulo`):

```python
def _paginas_da_portaria(
    combined: str,
    page_offsets: list[int],
    start_pos: int,
    titulo_norm: str,
    prox_titulo_norm: str | None,
    all_portaria_positions: list[int],
) -> list[int]:
    """
    Páginas (1-based) do PDF que contêm a portaria iniciada em `start_pos`.

    A fronteira final (`end_pos`) é, em ordem de preferência:
      1. início do PRÓXIMO ato (`prox_titulo_norm`), localizado após a portaria;
      2. próximo cabeçalho `PORTARIA Nº ...,` (`all_portaria_positions`);
      3. fim do documento.

    Inclui toda página cujo intervalo de texto [pg_start, pg_end) se sobrepõe a
    [start_pos, end_pos). `page_offsets` tem len == nº de páginas + 1 (sentinela).
    """
    search_from = start_pos + len(titulo_norm)

    end_pos = -1
    if prox_titulo_norm:
        achado = combined.find(prox_titulo_norm, search_from)
        if achado != -1:
            end_pos = achado
    if end_pos == -1:
        for pos in all_portaria_positions:
            if pos >= search_from:
                end_pos = pos
                break  # lista já ordenada por posição
    if end_pos == -1:
        end_pos = len(combined)

    paginas: list[int] = []
    for page_idx in range(len(page_offsets) - 1):
        pg_start = page_offsets[page_idx]
        pg_end = page_offsets[page_idx + 1]
        if pg_start < end_pos and pg_end > start_pos:
            paginas.append(page_idx + 1)
    return paginas
```

Agora adicione `_paginas_da_portaria` ao import em `monitor_diario_oficial.py`
(linhas 54-56), de:

```python
from src.pdf import (  # noqa: F401
    buscar_url_pdf, _sanitizar_nome_arquivo, extrair_pdfs_por_ocorrencia,
    _prox_ato_titulo,
)
```

para:

```python
from src.pdf import (  # noqa: F401
    buscar_url_pdf, _sanitizar_nome_arquivo, extrair_pdfs_por_ocorrencia,
    _prox_ato_titulo, _paginas_da_portaria,
)
```

- [ ] **Step 4: Rodar os testes para confirmar que passam**

Run: `python -m pytest test_monitor_diario_oficial.py::TestPaginasDaPortaria -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add src/pdf.py monitor_diario_oficial.py test_monitor_diario_oficial.py
git commit -m "$(cat <<'EOF'
feat(pdf): adiciona _paginas_da_portaria com fronteira por proximo ato

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: Integrar helpers em `extrair_pdfs_por_ocorrencia`

**Files:**
- Modify: `src/pdf.py:56` (assinatura) e `src/pdf.py:140-159` (corpo do loop)

- [ ] **Step 1: Confirmar baseline verde**

Run: `python -m pytest test_monitor_diario_oficial.py -v`
Expected: PASS (todos os testes existentes + os das Tasks 1 e 2)

- [ ] **Step 2: Alterar a assinatura e a docstring**

Em `src/pdf.py`, troque:

```python
def extrair_pdfs_por_ocorrencia(url_pdf: str, ocorrencias: list[dict]) -> list[str]:
```

por:

```python
def extrair_pdfs_por_ocorrencia(
    url_pdf: str,
    ocorrencias: list[dict],
    portarias: list[dict] | None = None,
) -> list[str]:
```

E acrescente ao final da docstring desta função (antes do `"""` de fechamento):

```
    Quando `portarias` (lista ORDENADA de atos da edição, vinda de
    extrair_portarias) é fornecida, o fim de cada portaria é o início do ato
    seguinte — evitando arrastar páginas quando a portaria é seguida por atos de
    outro tipo (extrato, termo…). Sem `portarias`, mantém o comportamento antigo.
```

- [ ] **Step 3: Substituir o cálculo inline de `end_pos`/páginas**

Em `src/pdf.py`, dentro do `for titulo, nomes in portaria_nomes.items():`, localize o bloco que vai de:

```python
        # Determina onde a portaria termina: próximo título de portaria (qualquer
        # uma, não só as monitoradas) que apareça APÓS o início desta portaria.
        # Isso evita incluir páginas de portarias não monitoradas ao fim do PDF.
        search_from = start_pos + len(titulo_norm)
        end_pos = len(combined)
        for pos in all_portaria_positions:
            if pos >= search_from and pos < end_pos:
                end_pos = pos
                break  # lista já está ordenada por posição

        # Inclui todas as páginas cujo intervalo de texto se sobrepõe ao span
        # [start_pos, end_pos) da portaria — captura corretamente portarias que
        # ocupam 2 ou mais páginas, mesmo quando uma página tem início de outra.
        for page_idx in range(len(reader.pages)):
            pg_start = page_offsets[page_idx]
            pg_end   = page_offsets[page_idx + 1]
            if pg_start < end_pos and pg_end > start_pos:
                writer.add_page(reader.pages[page_idx])
                paginas_incluidas.append(page_idx + 1)
```

e substitua TODO esse bloco por:

```python
        # Fronteira final da portaria: início do PRÓXIMO ato na ordem real do
        # Diário (lista `portarias`, segmentada via ato_separator). Sem a lista,
        # ou se o próximo ato não for localizável no PDF, recai no comportamento
        # antigo (próximo PORTARIA Nº; depois fim do documento).
        prox_ato = _prox_ato_titulo(portaria, portarias)
        prox_titulo_norm = _normalizar(prox_ato) if prox_ato else None

        paginas_incluidas = _paginas_da_portaria(
            combined, page_offsets, start_pos, titulo_norm,
            prox_titulo_norm, all_portaria_positions,
        )
        for pg in paginas_incluidas:
            writer.add_page(reader.pages[pg - 1])
```

> Mantém-se intactos: a inicialização `writer = PdfWriter()` / `paginas_incluidas = []`,
> o `start_pos = combined.find(titulo_norm)` com seu `if start_pos == -1`, e o
> `if not paginas_incluidas:` logo abaixo. `_normalizar` continua sendo a função
> aninhada já existente.

- [ ] **Step 4: Rodar a suíte completa**

Run: `python -m pytest test_monitor_diario_oficial.py -v`
Expected: PASS (todos). Os testes existentes de `extrair_pdfs_por_ocorrencia` (que chamam sem `portarias`) continuam verdes — `portarias=None` ⇒ comportamento antigo.

- [ ] **Step 5: Commit**

```bash
git add src/pdf.py
git commit -m "$(cat <<'EOF'
refactor(pdf): extrair_pdfs_por_ocorrencia usa fronteira por proximo ato

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: Passar `portarias` no ponto de chamada

**Files:**
- Modify: `monitor_diario_oficial.py:157`

- [ ] **Step 1: Atualizar a chamada**

Em `monitor_diario_oficial.py`, troque:

```python
        caminhos_pdf = extrair_pdfs_por_ocorrencia(url_pdf, ocorrencias)
```

por:

```python
        caminhos_pdf = extrair_pdfs_por_ocorrencia(url_pdf, ocorrencias, portarias)
```

(`portarias` é a lista criada na linha ~105 e está em escopo.)

- [ ] **Step 2: Rodar a suíte completa**

Run: `python -m pytest test_monitor_diario_oficial.py -v`
Expected: PASS (todos)

- [ ] **Step 3: Commit**

```bash
git add monitor_diario_oficial.py
git commit -m "$(cat <<'EOF'
feat: passa lista ordenada de atos para fatiar PDF por portaria

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: Verificação end-to-end contra a edição 1876 (manual, requer rede)

**Files:** nenhum (verificação de aceitação; não commitar).

- [ ] **Step 1: Rodar o script de verificação**

Run:

```bash
python -c "
from src.scraping import extrair_portarias
from src.pdf import buscar_url_pdf, extrair_pdfs_por_ocorrencia
from pypdf import PdfReader

URL='https://dom.mossoro.rn.gov.br/dom/publicacao/1876'
portarias = extrair_portarias(URL)
url_pdf = buscar_url_pdf(URL)

def oc_para(num):
    alvo = next(p for p in portarias if p['titulo'].startswith('PORTARIA') and f'{num},' in p['titulo'])
    return {'nome': 'VERIFICACAO', 'portaria': alvo}

ocs = [oc_para(45), oc_para(47)]
caminhos = extrair_pdfs_por_ocorrencia(url_pdf, ocs, portarias)
for c in caminhos:
    print(len(PdfReader(c).pages), 'pag ->', c)
"
```

Expected: o PDF cujo nome contém `45` tem **2** páginas; o que contém `47` tem **1** página.

- [ ] **Step 2: Limpeza**

Apague os PDFs de verificação gerados em `PDF_TEMP_DIR` (definido em `src/config.py`).

---

## Notas de execução

- Não há `pytest.ini`/`conftest.py`; rode sempre da raiz do projeto.
- `requirements.txt` já inclui `pypdf` e `pytest`; instale com `pip install -r requirements.txt` se necessário.
- A contagem total de testes do projeto aumenta em 8 (4 em `TestProxAtoTitulo` + 4 em `TestPaginasDaPortaria`) — se houver doc que cite o número de testes, atualizar fora do escopo deste plano.
