# Design — Flag `--nova-sessao` (sessão descartável do WhatsApp)

**Data:** 2026-06-16
**Status:** Aprovado para implementação

## Problema

Hoje o envio via WhatsApp (`src/whatsapp.py::enviar_whatsapp`) sempre reusa o perfil
persistente do Chrome em `WHATSAPP_PROFILE_DIR` (`.whatsapp_profile/`). Se a sessão
salva existe, o script entra direto sem pedir QR. Não há forma de forçar uma
autenticação limpa (QR novo) sem apagar manualmente a pasta do perfil — útil para
logar com **outro número** ou validar o fluxo de QR sem afetar a sessão de produção.

## Objetivo

Adicionar uma flag de linha de comando `--nova-sessao` que abre uma **sessão
descartável** ("aba anônima"): perfil limpo, QR exigido toda vez, e **nada
persistido** — o perfil de produção em `.whatsapp_profile/` permanece intacto.

Não-objetivos (YAGNI):
- Trocar/re-vincular a sessão **persistente** de produção (isso continua sendo
  feito apagando/recriando o perfil manualmente).
- Suportar `--nova-sessao` no modo `--agendar` (execuções agendadas sempre usam o
  perfil persistente — pedir QR a cada execução diária não faz sentido).

## Abordagem escolhida

**Perfil temporário descartável.** Em vez de `--user-data-dir={WHATSAPP_PROFILE_DIR}`,
quando a flag está ativa cria-se uma pasta nova com `tempfile.mkdtemp(prefix="wa_qr_")`,
usada como `--user-data-dir`. Como nasce vazia, o WhatsApp Web sempre mostra o QR.
A pasta é removida no `finally` após `driver.quit()`.

Descartada a alternativa Chrome `--incognito`: conflita com `--user-data-dir` e o
WhatsApp Web é instável em modo incógnito em várias versões do Chrome. O perfil
temporário entrega o mesmo efeito ("nada salvo, QR sempre") de forma confiável com
Selenium.

## Componentes e mudanças

### 1. `src/whatsapp.py` — `enviar_whatsapp`

- Novos imports no topo: `tempfile`, `shutil`.
- Novo parâmetro: `sessao_descartavel: bool = False` (último, com default — não quebra
  chamadas existentes nem os testes).
- Seleção do perfil, no início da função:
  - Se `sessao_descartavel`:
    - `perfil_temp = tempfile.mkdtemp(prefix="wa_qr_")`; `perfil_dir = perfil_temp`;
    - `sessao_valida = False` (força QR e `timeout_auth = TIMEOUT_QR_CODE`);
    - log informando o modo descartável e o caminho temporário.
  - Caso contrário (comportamento atual):
    - `perfil_temp = None`; `perfil_dir = WHATSAPP_PROFILE_DIR`;
    - `sessao_valida` calculado como hoje (existência do IndexedDB).
- `options.add_argument(f"--user-data-dir={perfil_dir}")` (usa `perfil_dir`, não mais a
  constante diretamente).
- No `finally`, após o `driver.quit()` existente:
  `if perfil_temp: shutil.rmtree(perfil_temp, ignore_errors=True)` (com log).

### 2. `monitor_diario_oficial.py` — `main` e bloco `__main__`

- `main(modo_teste=False, numero_diario=None, sessao_descartavel=False)`:
  - repassa `sessao_descartavel=sessao_descartavel` para **ambas** as chamadas de
    `enviar_whatsapp` (edição vazia e fluxo normal).
- Bloco `__main__`:
  - `sessao_descartavel = "--nova-sessao" in sys.argv` (calculado uma vez).
  - Ramo `--test`: `main(modo_teste=True, numero_diario=..., sessao_descartavel=sessao_descartavel)`.
  - Ramo `else` (execução pontual padrão): `main(sessao_descartavel=sessao_descartavel)`.
  - Ramo `--agendar`: **não** propaga a flag (comportamento persistente preservado).

A flag é **ortogonal** às demais:
- `--nova-sessao` sozinha → sessão descartável, envia ao **grupo real**.
- `--nova-sessao --test` → sessão descartável + **grupo de testes** (uso mais provável:
  logar com outro número sem tocar no perfil nem no grupo real).

### 3. Documentação

- `README.md`: documentar a flag `--nova-sessao` na seção de execução/flags, incluindo
  a combinação com `--test` e a observação de que não tem efeito com `--agendar`.
- Comentário do bloco `__main__` em `monitor_diario_oficial.py`: descrever a flag junto
  das demais (`--test`, `--agendar`).

## Fluxo de dados

```
CLI (--nova-sessao) → __main__ detecta → main(sessao_descartavel=True)
   → enviar_whatsapp(..., sessao_descartavel=True)
      → tempfile.mkdtemp → --user-data-dir=<temp> → QR → envio
      → finally: driver.quit() + shutil.rmtree(<temp>)
```

## Tratamento de erros

- A remoção da pasta temporária usa `ignore_errors=True` para nunca mascarar o
  resultado real do envio nem lançar em cima de uma exceção anterior.
- Se `mkdtemp` falhar (caso raro de disco/permissão), a exceção sobe e é capturada pelo
  `try/except` existente de `enviar_whatsapp`, que loga o erro e retorna `False` —
  consistente com o tratamento atual.

## Testes (seguindo o harness existente em `test_monitor_diario_oficial.py`)

Reusar `_PATCHES_SELENIUM` / `_setup_selenium_mocks` da classe `TestEnviarWhatsapp`.

1. **Perfil temporário quando `sessao_descartavel=True`:** com `tempfile.mkdtemp`
   (via `monitor_diario_oficial.whatsapp.tempfile`) patchado para retornar um caminho
   conhecido, chamar `enviar_whatsapp(..., sessao_descartavel=True)` e asseverar que as
   `ChromeOptions` passadas a `webdriver.Chrome` contêm `--user-data-dir=<caminho temp>`
   e **não** `WHATSAPP_PROFILE_DIR`.
2. **Limpeza:** asseverar que `shutil.rmtree` (patchado) é chamado com o caminho
   temporário no `finally`.
3. **Sem a flag (regressão):** `enviar_whatsapp(...)` continua usando
   `WHATSAPP_PROFILE_DIR` e **não** chama `mkdtemp`/`rmtree`.
4. **QR forçado:** com `sessao_descartavel=True`, o primeiro `WebDriverWait` usa
   `TIMEOUT_QR_CODE` mesmo que `os.path.isdir` retorne `True` (espelha o teste
   `test_timeout_auth_qr_code_sem_sessao_valida`).
5. **Propagação em `main`:** com `enviar_whatsapp` patchado, `main(sessao_descartavel=True)`
   chama `enviar_whatsapp` com `sessao_descartavel=True` (verificar via `kwargs`).

## Critérios de sucesso

- `python monitor_diario_oficial.py --nova-sessao` abre o Chrome com perfil limpo,
  exige QR, envia ao grupo real e não deixa resíduo no perfil de produção.
- `--nova-sessao --test` faz o mesmo mas envia ao grupo de testes.
- Execuções sem a flag permanecem idênticas ao comportamento atual.
- Todos os testes (novos e existentes) passam.
