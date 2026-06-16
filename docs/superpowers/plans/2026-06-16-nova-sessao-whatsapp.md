# Flag `--nova-sessao` (sessão descartável do WhatsApp) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Adicionar a flag de linha de comando `--nova-sessao`, que abre o WhatsApp Web em um perfil Chrome temporário (sessão descartável: QR sempre, nada persistido), sem tocar no perfil de produção `.whatsapp_profile/`.

**Architecture:** Quando a flag está ativa, `enviar_whatsapp` cria uma pasta temporária com `tempfile.mkdtemp` e a usa como `--user-data-dir` (em vez de `WHATSAPP_PROFILE_DIR`), força o fluxo de QR, e remove a pasta no `finally`. A flag é detectada no bloco `__main__`, propagada por `main()` até `enviar_whatsapp`. Ortogonal a `--test` (grupo) e sem efeito em `--agendar`.

**Tech Stack:** Python 3.11+, Selenium, pytest + unittest.mock.

---

## File Structure

- **Modify:** `src/whatsapp.py` — novo parâmetro `sessao_descartavel` em `enviar_whatsapp`; imports `tempfile`/`shutil`; seleção de perfil e limpeza.
- **Modify:** `monitor_diario_oficial.py` — `main()` ganha `sessao_descartavel` e repassa às duas chamadas de `enviar_whatsapp`; bloco `__main__` detecta `--nova-sessao`; comentário atualizado.
- **Modify:** `test_monitor_diario_oficial.py` — novos testes na classe `TestEnviarWhatsapp` e um teste de propagação em `TestMainRoteamento`.
- **Modify:** `README.md` — documenta a flag.

Referência de design: `docs/superpowers/specs/2026-06-16-nova-sessao-whatsapp-design.md`.

---

## Task 1: `enviar_whatsapp` — sessão descartável (perfil temporário)

**Files:**
- Modify: `src/whatsapp.py` (imports no topo; corpo de `enviar_whatsapp`, ~linhas 350-616)
- Test: `test_monitor_diario_oficial.py` (classe `TestEnviarWhatsapp`, após o último teste da classe)

### Contexto do harness de teste (leia antes de escrever os testes)

Os testes de `enviar_whatsapp` usam o decorator `@_aplicar_patches`, que injeta, **nesta ordem**, os parâmetros:
`mock_chrome, mock_wait, mock_service, mock_cdm, mock_isdir, mock_sleep, mock_colar`.
`_setup_selenium_mocks(mock_chrome, mock_wait)` configura um fluxo de envio bem-sucedido.
`webdriver.Chrome` é mockado; `webdriver.ChromeOptions()` é **real**, então
`mock_chrome.call_args.kwargs["options"].arguments` retorna a lista de argumentos
adicionados via `options.add_argument(...)`.

- [ ] **Step 1: Escrever os testes que falham**

Adicione ao final da classe `TestEnviarWhatsapp` em `test_monitor_diario_oficial.py`:

```python
    @_aplicar_patches
    def test_sessao_descartavel_usa_perfil_temporario(
        self, mock_chrome, mock_wait, mock_service, mock_cdm, mock_isdir, mock_sleep, mock_colar
    ):
        """Com sessao_descartavel, o --user-data-dir aponta para a pasta temporária."""
        _setup_selenium_mocks(mock_chrome, mock_wait)
        with patch(
            "monitor_diario_oficial.whatsapp.tempfile.mkdtemp",
            return_value="/tmp/wa_qr_fake",
        ), patch("monitor_diario_oficial.whatsapp.shutil.rmtree") as mock_rmtree:
            monitor.enviar_whatsapp("Msg", "Grupo", sessao_descartavel=True)

        args = mock_chrome.call_args.kwargs["options"].arguments
        assert "--user-data-dir=/tmp/wa_qr_fake" in args
        assert all(
            not a.startswith(f"--user-data-dir={monitor.WHATSAPP_PROFILE_DIR}")
            for a in args
        )

    @_aplicar_patches
    def test_sessao_descartavel_remove_perfil_temporario(
        self, mock_chrome, mock_wait, mock_service, mock_cdm, mock_isdir, mock_sleep, mock_colar
    ):
        """A pasta temporária deve ser removida no finally."""
        _setup_selenium_mocks(mock_chrome, mock_wait)
        with patch(
            "monitor_diario_oficial.whatsapp.tempfile.mkdtemp",
            return_value="/tmp/wa_qr_fake",
        ), patch("monitor_diario_oficial.whatsapp.shutil.rmtree") as mock_rmtree:
            monitor.enviar_whatsapp("Msg", "Grupo", sessao_descartavel=True)

        mock_rmtree.assert_called_once_with("/tmp/wa_qr_fake", ignore_errors=True)

    @_aplicar_patches
    def test_sessao_descartavel_forca_timeout_qr_code(
        self, mock_chrome, mock_wait, mock_service, mock_cdm, mock_isdir, mock_sleep, mock_colar
    ):
        """sessao_descartavel força TIMEOUT_QR_CODE mesmo se isdir indicar sessão salva."""
        mock_isdir.return_value = True  # haveria sessão salva, mas a flag deve ignorar
        _setup_selenium_mocks(mock_chrome, mock_wait)
        with patch(
            "monitor_diario_oficial.whatsapp.tempfile.mkdtemp",
            return_value="/tmp/wa_qr_fake",
        ), patch("monitor_diario_oficial.whatsapp.shutil.rmtree"):
            monitor.enviar_whatsapp("Msg", "Grupo", sessao_descartavel=True)

        timeout_primeiro_wait = mock_wait.call_args_list[0][0][1]
        assert timeout_primeiro_wait == monitor.TIMEOUT_QR_CODE

    @_aplicar_patches
    def test_sem_flag_usa_perfil_persistente(
        self, mock_chrome, mock_wait, mock_service, mock_cdm, mock_isdir, mock_sleep, mock_colar
    ):
        """Sem a flag: usa WHATSAPP_PROFILE_DIR e não cria/remove pasta temporária."""
        mock_isdir.return_value = True
        _setup_selenium_mocks(mock_chrome, mock_wait)
        with patch("monitor_diario_oficial.whatsapp.tempfile.mkdtemp") as mock_mkdtemp, \
             patch("monitor_diario_oficial.whatsapp.shutil.rmtree") as mock_rmtree:
            monitor.enviar_whatsapp("Msg", "Grupo")

        args = mock_chrome.call_args.kwargs["options"].arguments
        assert f"--user-data-dir={monitor.WHATSAPP_PROFILE_DIR}" in args
        mock_mkdtemp.assert_not_called()
        mock_rmtree.assert_not_called()
```

- [ ] **Step 2: Rodar os testes e ver que falham**

Run: `pytest test_monitor_diario_oficial.py::TestEnviarWhatsapp -k "descartavel or persistente" -v`
Expected: FAIL — `enviar_whatsapp()` ainda não aceita `sessao_descartavel` (TypeError: unexpected keyword argument).

- [ ] **Step 3: Adicionar os imports em `src/whatsapp.py`**

No topo do arquivo, junto aos imports da stdlib (logo após `import platform`, linha 5):

```python
import shutil
import tempfile
```

- [ ] **Step 4: Adicionar o parâmetro à assinatura de `enviar_whatsapp`**

Em `src/whatsapp.py`, altere a assinatura (linhas ~350-355) para:

```python
def enviar_whatsapp(
    mensagem: str,
    grupo: str,
    caminhos_pdf: list[str] = None,
    mensagem_apos_pdf: str = "",
    sessao_descartavel: bool = False,
) -> bool:
```

- [ ] **Step 5: Selecionar o perfil e forçar o QR (corpo da função)**

Substitua o bloco atual de detecção de sessão + opções do Chrome
(de `# ── Detecção de sessão...` até `driver = None`, linhas ~369-396) por:

```python
    # ── Perfil Chrome: persistente (produção) ou temporário (sessão descartável) ──
    # perfil_temp != None somente no modo --nova-sessao; é criado dentro do try
    # para que qualquer falha de criação caia no except/finally desta função.
    perfil_temp = None
    driver = None
    try:
        if sessao_descartavel:
            perfil_temp = tempfile.mkdtemp(prefix="wa_qr_")
            perfil_dir = perfil_temp
            sessao_valida = False  # perfil limpo → QR sempre exigido
            log.info(
                "Modo nova sessão (descartável): perfil temporário limpo — "
                f"o QR será exibido. Perfil: {perfil_temp}"
            )
        else:
            perfil_dir = WHATSAPP_PROFILE_DIR
            sessao_valida = os.path.isdir(
                os.path.join(
                    WHATSAPP_PROFILE_DIR,
                    "Default", "IndexedDB",
                    "https_web.whatsapp.com_0.indexeddb.leveldb",
                )
            )
            if not sessao_valida:
                log.info(
                    "Sessão do WhatsApp não encontrada — Chrome abrirá para autenticação.\n"
                    f"Escaneie o QR code no WhatsApp do celular. "
                    f"Você tem {TIMEOUT_QR_CODE} segundos."
                )

        timeout_auth = 30 if sessao_valida else TIMEOUT_QR_CODE

        # ── Opções do Chrome ─────────────────────────────────────────────────
        options = webdriver.ChromeOptions()
        options.add_argument(f"--user-data-dir={perfil_dir}")
        options.add_argument("--profile-directory=Default")
        options.add_argument("--remote-allow-origins=*")
        # NÃO usar --no-sandbox: o sandbox do Chrome é a principal camada de
        # isolamento contra exploração via conteúdo web. Em desktop comum ele é
        # desnecessário. Em container, rode como usuário não-root em vez de desligá-lo.
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--disable-gpu")

        if ChromeDriverManager is None:
```

> Atenção: o `if ChromeDriverManager is None:` acima é a primeira linha do bloco
> que **já existia** dentro do `try`. Ou seja, você está movendo a detecção de
> sessão e a criação de `options` para **dentro** do `try` existente e removendo o
> `driver = None` / `try:` antigos (já reescritos acima). O restante do corpo do
> `try` (a partir de `service = Service(...)`) permanece inalterado.

- [ ] **Step 6: Remover a pasta temporária no `finally`**

No final da função, substitua o `finally` atual (linhas ~613-615):

```python
    finally:
        if driver:
            driver.quit()
```

por:

```python
    finally:
        if driver:
            driver.quit()
        if perfil_temp:
            shutil.rmtree(perfil_temp, ignore_errors=True)
            log.info(f"Perfil temporário (sessão descartável) removido: {perfil_temp}")
```

- [ ] **Step 7: Rodar os testes e ver que passam**

Run: `pytest test_monitor_diario_oficial.py::TestEnviarWhatsapp -v`
Expected: PASS — todos os testes da classe (novos e antigos) passam.

- [ ] **Step 8: Commit**

```bash
git add src/whatsapp.py test_monitor_diario_oficial.py
git commit -m "feat(whatsapp): sessao descartavel via perfil temporario (param sessao_descartavel)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: Propagar `sessao_descartavel` por `main()`

**Files:**
- Modify: `monitor_diario_oficial.py` (`def main`, linha 62; chamadas de `enviar_whatsapp`, linhas ~140 e ~159)
- Test: `test_monitor_diario_oficial.py` (classe `TestMainRoteamento`)

- [ ] **Step 1: Escrever o teste que falha**

Adicione à classe `TestMainRoteamento` em `test_monitor_diario_oficial.py`:

```python
    def test_propaga_sessao_descartavel_para_enviar_whatsapp(self):
        """main(sessao_descartavel=True) deve repassar a flag a enviar_whatsapp."""
        publicacao = {"numero": 999, "data": "16/06/2026", "url_html": "http://x/999"}
        with patch("monitor_diario_oficial.buscar_ultima_publicacao", return_value=publicacao), \
             patch("monitor_diario_oficial.extrair_portarias", return_value=["ato"]), \
             patch("monitor_diario_oficial.buscar_nomes_em_portarias", return_value=[]), \
             patch("monitor_diario_oficial.detectar_fofocas", return_value=[]), \
             patch("monitor_diario_oficial.promovido_remanejado", return_value=[]), \
             patch("monitor_diario_oficial.detectar_ponto_facultativo", return_value=[]), \
             patch("monitor_diario_oficial.formatar_fofocas", return_value=""), \
             patch("monitor_diario_oficial.enviar_whatsapp", return_value=True) as m_env:
            monitor.main(modo_teste=True, sessao_descartavel=True)

        assert m_env.call_args.kwargs.get("sessao_descartavel") is True
```

> Nota: `modo_teste=True` evita escrita no `.env` (`_atualizar_env` só roda fora do
> modo teste) e faz `ULTIMO_DOM_NUMERO` valer 0, garantindo o processamento. Com
> `buscar_nomes_em_portarias` retornando `[]`, `main` cai no ramo "edição vazia" e
> chama `enviar_whatsapp` uma vez, então `return`.

- [ ] **Step 2: Rodar o teste e ver que falha**

Run: `pytest test_monitor_diario_oficial.py::TestMainRoteamento::test_propaga_sessao_descartavel_para_enviar_whatsapp -v`
Expected: FAIL — `main()` ainda não aceita `sessao_descartavel` (TypeError).

- [ ] **Step 3: Adicionar o parâmetro a `main` e repassá-lo**

Em `monitor_diario_oficial.py`, altere a assinatura de `main` (linha 62):

```python
def main(modo_teste: bool = False, numero_diario: int | None = None,
         sessao_descartavel: bool = False):
```

Na chamada do ramo "edição vazia" (linha ~140), passe a flag:

```python
        enviar_whatsapp(
            mensagem_vazia, grupo_destino,
            mensagem_apos_pdf=secao_fofoca,
            sessao_descartavel=sessao_descartavel,
        )
        return
```

E na chamada do fluxo normal (linha ~159):

```python
    sucesso = enviar_whatsapp(
        mensagem, grupo_destino, caminhos_pdf,
        mensagem_apos_pdf=secao_fofoca,
        sessao_descartavel=sessao_descartavel,
    )
```

- [ ] **Step 4: Rodar o teste e ver que passa**

Run: `pytest test_monitor_diario_oficial.py::TestMainRoteamento -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add monitor_diario_oficial.py test_monitor_diario_oficial.py
git commit -m "feat: main propaga sessao_descartavel ate enviar_whatsapp

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: Flag `--nova-sessao` no `__main__` + documentação

**Files:**
- Modify: `monitor_diario_oficial.py` (bloco `if __name__ == "__main__":`, linhas ~231-251)
- Modify: `README.md` (seção de execução/flags)

> Sem teste unitário: o bloco `__main__` não é uma função testável e a detecção é um
> `"--nova-sessao" in sys.argv` trivial, igual às flags `--test`/`--agendar` já
> existentes (também não testadas isoladamente). Validação é manual (Step 3).

- [ ] **Step 1: Detectar e propagar a flag no `__main__`**

Em `monitor_diario_oficial.py`, substitua o bloco `__main__` (linhas ~231-251) por:

```python
if __name__ == "__main__":
    # --nova-sessao: abre uma sessão DESCARTÁVEL (perfil Chrome temporário, QR
    # sempre exigido, nada persistido). Útil para logar com outro número sem
    # afetar o perfil de produção. Ortogonal a --test (que só troca o grupo).
    # Sem efeito em --agendar (execuções agendadas usam o perfil persistente).
    sessao_descartavel = "--nova-sessao" in sys.argv

    # ── Modo teste ────────────────────────────────────────────────────────────
    # Acionado por: python monitor_diario_oficial.py --test [NÚMERO]
    # Sem número → edição mais recente. Com número (ex.: --test 839) → busca essa
    # edição específica pelo nº do DOM. Em ambos: trata ULTIMO_DOM_NUMERO como 0
    # (sempre reprocessa) e envia ao grupo de testes (WHATSAPP_GRUPO_TESTE), sem
    # alterar o rastreamento real no .env.
    if "--test" in sys.argv:
        main(
            modo_teste=True,
            numero_diario=_extrair_numero_teste(sys.argv),
            sessao_descartavel=sessao_descartavel,
        )
    # ── Modo agendado (execução contínua) ────────────────────────────────────
    # Acionado APENAS por: python monitor_diario_oficial.py --agendar
    # HORARIO_EXECUCAO define o horário, mas NÃO ativa o modo sozinho.
    # Agendamento externo (Claude Routines, Task Scheduler, cron):
    #   → execute sem --agendar; o script roda uma vez e encerra.
    elif "--agendar" in sys.argv:
        horario = os.environ.get("HORARIO_EXECUCAO", "05:00").strip()
        _agendar_execucao(horario)
    else:
        # ── Execução pontual (padrão) ────────────────────────────────────────
        # Roda uma única vez e encerra — modo correto para agendamento externo.
        main(sessao_descartavel=sessao_descartavel)
```

- [ ] **Step 2: Documentar a flag no `README.md`**

Localize a seção que descreve as flags de execução (procure por `--test` ou `--agendar`
no `README.md`) e acrescente, no mesmo formato/idioma das demais, uma entrada para
`--nova-sessao`. Conteúdo a documentar:

- `python monitor_diario_oficial.py --nova-sessao` — abre uma **sessão descartável**:
  perfil Chrome temporário e limpo, QR exigido toda vez, nada persistido; o perfil de
  produção `.whatsapp_profile/` permanece intacto.
- Combina com `--test`: `python monitor_diario_oficial.py --nova-sessao --test` envia ao
  grupo de testes (uso típico: logar com outro número sem afetar produção).
- Sem efeito com `--agendar` (execuções agendadas usam o perfil persistente).

- [ ] **Step 3: Verificação manual da fiação da CLI**

Confirme que a flag é reconhecida e propagada sem disparar o fluxo real do Chrome,
usando um mock de `enviar_whatsapp` via `-c`:

Run:
```bash
python -c "import sys; sys.argv=['p','--nova-sessao','--test']; import monitor_diario_oficial as m; from unittest.mock import patch; \
patch('monitor_diario_oficial.buscar_ultima_publicacao', return_value=None).start(); \
print('flag detectada:', '--nova-sessao' in sys.argv)"
```
Expected: imprime `flag detectada: True` e encerra sem abrir o Chrome (publicação None → early return em `main`). Se preferir, rode `python monitor_diario_oficial.py --nova-sessao --test` de verdade: o Chrome deve abrir já exibindo o QR (não logar automaticamente).

- [ ] **Step 4: Rodar a suíte completa**

Run: `pytest test_monitor_diario_oficial.py -q`
Expected: todos os testes passam.

- [ ] **Step 5: Commit**

```bash
git add monitor_diario_oficial.py README.md
git commit -m "feat: flag --nova-sessao na CLI + documentacao no README

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Self-Review (preenchido)

**Spec coverage:**
- Param `sessao_descartavel` + perfil temporário + cleanup → Task 1. ✓
- Força QR (sessao_valida=False / TIMEOUT_QR_CODE) → Task 1 (Step 5, teste Step 1). ✓
- `--user-data-dir` usa `perfil_dir` → Task 1. ✓
- Propagação em `main` (ambas as chamadas) → Task 2. ✓
- Flag `--nova-sessao` no `__main__`, ortogonal a `--test`, sem efeito em `--agendar` → Task 3. ✓
- README + comentário `__main__` → Task 3. ✓
- Testes (perfil temp, limpeza, QR forçado, regressão sem flag, propagação) → Tasks 1 e 2. ✓
- Tratamento de erro (mkdtemp dentro do try; rmtree com ignore_errors) → Task 1 (Steps 5-6). ✓

**Placeholder scan:** nenhum TBD/TODO; todo passo de código mostra o código exato. ✓

**Type/nome consistency:** `sessao_descartavel` (bool) usado de forma consistente em
`enviar_whatsapp`, `main` e `__main__`; `perfil_temp`/`perfil_dir` consistentes dentro
de `enviar_whatsapp`. ✓
