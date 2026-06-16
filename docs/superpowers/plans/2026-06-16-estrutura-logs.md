# Estrutura de logs (pasta `logs/`, produção × testes) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Gravar os logs em uma pasta `logs/`, separando execuções de produção (`logs/producao.log`) das execuções de teste — flag `--test` ou suíte `pytest` — (`logs/testes.log`), sem mexer em níveis, formato ou rotação.

**Architecture:** Um helper puro `_nome_arquivo_log(argv, modulos)` em `src/config.py` decide o nome do arquivo no momento do import (quando o logging é configurado), a partir de `sys.argv`/`sys.modules`. `LOG_DIR` passa a apontar para a subpasta `logs/`. `configurar_logging` usa o helper para montar o caminho do arquivo.

**Tech Stack:** Python 3.11+, `logging` (RotatingFileHandler), pytest.

---

## File Structure

- **Modify:** `src/config.py` — novo helper `_nome_arquivo_log`; default de `LOG_DIR` → `logs/`; `configurar_logging` usa o helper.
- **Modify:** `test_monitor_diario_oficial.py` — nova classe de teste para o helper.
- **Modify:** `README.md` — descrição de `LOG_DIR`, diagrama de estrutura, menções a `monitor_dom.log`.
- **Modify:** `.env.example` — comentário de `LOG_DIR`.

Referência de design: `docs/superpowers/specs/2026-06-16-estrutura-logs-design.md`.

---

## Task 1: Helper `_nome_arquivo_log` + pasta `logs/` no `configurar_logging`

**Files:**
- Modify: `src/config.py` (LOG_DIR linha 118-119; novo helper antes de `configurar_logging`; `log_path` linha ~164)
- Test: `test_monitor_diario_oficial.py` (nova classe `TestNomeArquivoLog`)

### Contexto para os testes

Os testes importam o módulo como `import monitor_diario_oficial as monitor`. O submódulo
de config é acessível como `monitor.config` (`monitor_diario_oficial` faz
`from src import config`). Logo o helper é acessível como
`monitor.config._nome_arquivo_log`. O helper é **puro** e recebe `argv`/`modulos` por
injeção, então os testes não tocam no filesystem e conseguem exercitar o caminho de
produção mesmo rodando sob pytest (basta passar `modulos={}`).

- [ ] **Step 1: Escrever os testes que falham**

Adicione esta nova classe ao `test_monitor_diario_oficial.py`, logo após a classe
`TestExtrairNumeroTeste` (final do arquivo):

```python
# ══════════════════════════════════════════════════════════════
# 12. _nome_arquivo_log — escolhe producao.log vs testes.log
# ══════════════════════════════════════════════════════════════

class TestNomeArquivoLog:

    def test_execucao_normal_usa_producao(self):
        """Sem --test e sem pytest carregado → producao.log."""
        assert monitor.config._nome_arquivo_log(argv=["prog"], modulos={}) == "producao.log"

    def test_flag_test_usa_testes(self):
        """Com --test no argv → testes.log."""
        assert monitor.config._nome_arquivo_log(argv=["prog", "--test"], modulos={}) == "testes.log"

    def test_pytest_carregado_usa_testes(self):
        """Com pytest em sys.modules → testes.log (suíte não polui produção)."""
        assert monitor.config._nome_arquivo_log(argv=["prog"], modulos={"pytest": object()}) == "testes.log"
```

- [ ] **Step 2: Rodar os testes e ver que falham**

Run: `python -m pytest test_monitor_diario_oficial.py::TestNomeArquivoLog -v`
Expected: FAIL — `_nome_arquivo_log` não existe (AttributeError em `monitor.config._nome_arquivo_log`).

- [ ] **Step 3: Mudar o default de `LOG_DIR` para a pasta `logs/`**

Em `src/config.py`, substitua o comentário e a linha (linhas 118-119):

```python
# Pasta de logs (padrão: mesma pasta do script).
LOG_DIR: str = os.environ.get("LOG_DIR", _BASE_DIR)
```

por:

```python
# Pasta de logs (padrão: subpasta "logs" ao lado do script).
# Os nomes dos arquivos (producao.log / testes.log) são escolhidos em _nome_arquivo_log.
LOG_DIR: str = os.environ.get("LOG_DIR", os.path.join(_BASE_DIR, "logs"))
```

- [ ] **Step 4: Adicionar o helper `_nome_arquivo_log`**

Em `src/config.py`, na seção `# CONFIGURAÇÃO DE LOG` (logo antes de
`def configurar_logging() -> logging.Logger:`, linha ~131), insira:

```python
def _nome_arquivo_log(argv=None, modulos=None) -> str:
    """
    Escolhe o arquivo de log conforme o modo de execução.

    - Execução com a flag --test OU sob a suíte pytest → "testes.log"
      (evita poluir o log de produção com ruído de teste).
    - Caso contrário → "producao.log".

    argv/modulos são injetáveis para permitir teste puro (sem tocar no
    filesystem); por padrão usam os globais reais sys.argv / sys.modules.
    """
    argv = sys.argv if argv is None else argv
    modulos = sys.modules if modulos is None else modulos
    em_teste = ("--test" in argv) or ("pytest" in modulos)
    return "testes.log" if em_teste else "producao.log"
```

(`sys` já está importado no topo de `src/config.py`.)

- [ ] **Step 5: Usar o helper em `configurar_logging`**

Em `src/config.py`, dentro de `configurar_logging`, substitua a linha (~164):

```python
    log_path = os.path.join(LOG_DIR, "monitor_dom.log")
```

por:

```python
    log_path = os.path.join(LOG_DIR, _nome_arquivo_log())
```

Não altere mais nada na função: `os.makedirs(LOG_DIR, exist_ok=True)`, o
`RotatingFileHandler(maxBytes=5*1024*1024, backupCount=3, encoding="utf-8")` e o handler
de console permanecem como estão.

- [ ] **Step 6: Rodar os testes do helper e ver que passam**

Run: `python -m pytest test_monitor_diario_oficial.py::TestNomeArquivoLog -v`
Expected: PASS (3 testes).

- [ ] **Step 7: Rodar a suíte completa (regressão) e confirmar o destino do log**

Run: `python -m pytest test_monitor_diario_oficial.py -q`
Expected: todos os testes passam.

Depois, confirme que a suíte gravou em `logs/testes.log` (e não na raiz):
Run: `python -c "import os; print('logs/testes.log existe:', os.path.isfile('logs/testes.log'))"`
Expected: imprime `logs/testes.log existe: True`. (Confirma que o pytest caiu no bucket de testes e a pasta `logs/` foi criada.)

- [ ] **Step 8: Commit**

```bash
git add src/config.py test_monitor_diario_oficial.py
git commit -m "feat(logs): separa logs em logs/producao.log e logs/testes.log

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: Atualizar documentação (README + .env.example)

**Files:**
- Modify: `README.md` (linhas 272, 294, 330, 379)
- Modify: `.env.example` (linhas 57-58)

> Sem teste unitário: mudança apenas de documentação. Verificação por inspeção.

- [ ] **Step 1: Atualizar a linha de `LOG_DIR` na tabela de variáveis**

Em `README.md` (linha 272), substitua:

```
| `LOG_DIR` | Pasta onde o arquivo de log é gravado | Mesma pasta do script |
```

por:

```
| `LOG_DIR` | Pasta onde os arquivos de log são gravados (`producao.log`, `testes.log`) | Subpasta `logs/` ao lado do script |
```

- [ ] **Step 2: Atualizar a menção a `monitor_dom.log` na seção LGPD**

Em `README.md` (linhas 293-295), substitua o trecho:

```
  artefatos **locais e temporários**: PDFs em `pdfs_temporarios/` (removidos após
  o envio) e logs em `monitor_dom.log`. Recomenda-se **expurgar os logs
  periodicamente** (ex.: a cada 30 dias), pois podem conter nomes.
```

por:

```
  artefatos **locais e temporários**: PDFs em `pdfs_temporarios/` (removidos após
  o envio) e logs na pasta `logs/` (`producao.log` e `testes.log`). Recomenda-se
  **expurgar os logs periodicamente** (ex.: a cada 30 dias), pois podem conter nomes.
```

- [ ] **Step 3: Atualizar o diagrama de estrutura de pastas**

Em `README.md` (linhas 327-331), substitua:

```
├── .whatsapp_profile/          # Sessão do Chrome/WhatsApp (não versionada)
├── pdfs_temporarios/           # PDFs gerados antes do envio (apagados após envio)
└── monitor_dom.log             # Log de execução (rotativo, máx. 5 MB)
```

por:

```
├── .whatsapp_profile/          # Sessão do Chrome/WhatsApp (não versionada)
├── pdfs_temporarios/           # PDFs gerados antes do envio (apagados após envio)
└── logs/                       # Logs de execução (rotativos, máx. 5 MB cada)
    ├── producao.log            # Execução normal
    └── testes.log              # Execução com --test ou suíte pytest
```

- [ ] **Step 4: Atualizar a referência no troubleshooting**

Em `README.md` (linha 379), substitua:

```
- Verifique o arquivo `monitor_dom.log` — ele contém o detalhe completo de cada etapa.
```

por:

```
- Verifique o arquivo `logs/producao.log` (ou `logs/testes.log`, se rodou com `--test`) — ele contém o detalhe completo de cada etapa.
```

- [ ] **Step 5: Atualizar o comentário de `LOG_DIR` no `.env.example`**

Em `.env.example` (linhas 57-58), substitua:

```
# Pasta onde os arquivos de log são salvos.
# Se omitido, usa a mesma pasta do script.
```

por:

```
# Pasta onde os arquivos de log são salvos (producao.log e testes.log).
# Se omitido, usa a subpasta "logs" ao lado do script.
```

- [ ] **Step 6: Verificar que nenhuma menção a `monitor_dom.log` permaneceu**

Run: `python -c "import pathlib,sys; t=pathlib.Path('README.md').read_text(encoding='utf-8')+pathlib.Path('.env.example').read_text(encoding='utf-8'); sys.exit(1 if 'monitor_dom.log' in t else 0)"`
Expected: sai com código 0 (nenhuma ocorrência restante). Se sair 1, localize e atualize a menção remanescente.

- [ ] **Step 7: Commit**

```bash
git add README.md .env.example
git commit -m "docs: atualiza referencias de log para logs/producao.log e logs/testes.log

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Self-Review (preenchido)

**Spec coverage:**
- Pasta `logs/` (default de `LOG_DIR`) → Task 1 Step 3. ✓
- Helper `_nome_arquivo_log(argv, modulos)` com `--test`/`pytest` → Task 1 Step 4. ✓
- `configurar_logging` usa o helper; rotação/console intactos → Task 1 Step 5. ✓
- Comportamento: produção→producao.log, `--test`/pytest→testes.log → Task 1 (Steps 4-5, testes Step 1, verificação Step 7). ✓
- Testes do helper (3 caminhos via injeção) → Task 1 Step 1. ✓
- Nenhum `.log` novo na raiz → garantido pelo default `logs/` + verificação Step 7. ✓
- README (LOG_DIR, diagrama, menções) e `.env.example` → Task 2. ✓
- Limpeza manual do `monitor_dom.log` antigo → fora do escopo de código (documentado no spec). ✓

**Placeholder scan:** nenhum TBD/TODO; todo passo de código mostra o código exato. ✓

**Type/nome consistency:** `_nome_arquivo_log(argv=None, modulos=None) -> str` usado de
forma idêntica nos testes (Task 1 Step 1) e na definição/chamada (Steps 4-5);
nomes de arquivo `producao.log`/`testes.log` consistentes em todo o plano. ✓
