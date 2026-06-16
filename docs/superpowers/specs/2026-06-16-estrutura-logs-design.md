# Design — Estrutura de logs (pasta `logs/`, produção × testes)

**Data:** 2026-06-16
**Status:** Aprovado para implementação

## Problema

Hoje toda a aplicação grava em **um único** arquivo `monitor_dom.log` na **raiz** do
projeto ([src/config.py](../../../src/config.py) — `configurar_logging`). Consequências:

- A raiz do repositório fica poluída com o `.log` e seus backups rotacionados.
- Execuções de teste (flag `--test`) e da suíte `pytest` misturam ruído no mesmo
  arquivo das execuções reais de produção, dificultando a leitura do histórico real.

## Objetivo

1. Concentrar os logs em uma pasta `logs/` (já ignorada pelo `.gitignore`).
2. Separar o destino conforme o modo de execução:
   - Execução normal (produção) → `logs/producao.log`
   - Execução com `--test` **ou** rodada da suíte `pytest` → `logs/testes.log`
3. Manter a rotação atual (5 MB por arquivo, 3 backups) e o log de console inalterado.

Não-objetivos (YAGNI):
- Mudar níveis de log, formato das mensagens ou o handler de console.
- Refatorar a inicialização do logging para fora do tempo de import.
- Migrar/mover automaticamente o `monitor_dom.log` antigo (limpeza manual, ver abaixo).

## Restrição arquitetural que orienta a solução

O logger é configurado **no momento do import**: `log = configurar_logging()` roda em
nível de módulo em `src/config.py`. Isso acontece **antes** de o `--test` ser lido no
bloco `__main__` de `monitor_diario_oficial.py`. Portanto a escolha do arquivo precisa
ser feita já no import — não dá para decidir no `main()`, pois o handler de arquivo já
estaria aberto. A solução detecta o modo a partir de `sys.argv` / `sys.modules`, ambos
disponíveis no import.

## Abordagem escolhida

Detectar o modo dentro de `configurar_logging`, via um helper **puro e testável**
que recebe `argv` e `modulos` por injeção (com defaults para os globais reais):

```python
def _nome_arquivo_log(argv=None, modulos=None) -> str:
    argv = sys.argv if argv is None else argv
    modulos = sys.modules if modulos is None else modulos
    em_teste = ("--test" in argv) or ("pytest" in modulos)
    return "testes.log" if em_teste else "producao.log"
```

Descartada a alternativa de adiar o handler de arquivo para depois do parse de
argumentos: vários módulos importam `log` no import e logs emitidos durante o import se
perderiam — refator grande e arriscado sem ganho proporcional.

## Componentes e mudanças

### `src/config.py`

1. **Pasta de logs padrão:** `LOG_DIR` passa de `_BASE_DIR` para
   `os.path.join(_BASE_DIR, "logs")`. O override por variável de ambiente `LOG_DIR`
   continua válido e agora aponta para a *pasta* onde os arquivos são gravados.
2. **Novo helper `_nome_arquivo_log(argv=None, modulos=None)`** (acima): retorna
   `"testes.log"` se `--test` estiver no argv **ou** `pytest` estiver carregado em
   `sys.modules`; caso contrário `"producao.log"`. Importa `sys` (já importado no módulo).
3. **`configurar_logging`:** trocar
   `log_path = os.path.join(LOG_DIR, "monitor_dom.log")` por
   `log_path = os.path.join(LOG_DIR, _nome_arquivo_log())`.
   Mantém `os.makedirs(LOG_DIR, exist_ok=True)`, o `RotatingFileHandler`
   (`maxBytes=5*1024*1024`, `backupCount=3`, `encoding="utf-8"`) e o handler de console
   sem alterações. Atualizar o docstring/comentário da função para refletir os dois
   arquivos.

### Documentação

- `README.md`:
  - Atualizar a descrição de `LOG_DIR` (default agora `logs/`).
  - Atualizar o diagrama de estrutura de pastas que cita `monitor_dom.log` para refletir
    a pasta `logs/` com `producao.log` / `testes.log`.
  - Atualizar as menções a `monitor_dom.log` no texto (seção de logs e troubleshooting)
    para os novos nomes/local.
- `.env.example`: ajustar o comentário de `LOG_DIR` para indicar que é a pasta de logs.

### Limpeza manual (fora do código)

O antigo `monitor_dom.log` e seus backups (`monitor_dom.log.1`, etc.) na raiz ficam
órfãos após a mudança. São arquivos locais e gitignored; recomenda-se removê-los
manualmente numa limpeza única. Não faz parte das alterações de código.

## Comportamento resultante

| Execução | Arquivo |
|----------|---------|
| `python monitor_diario_oficial.py` (normal/produção) | `logs/producao.log` |
| `python monitor_diario_oficial.py --test [N]` | `logs/testes.log` |
| `pytest` (suíte de testes) | `logs/testes.log` |

Console permanece em nível INFO em todos os casos; arquivo em DEBUG, como hoje.

## Tratamento de erros

- `os.makedirs(LOG_DIR, exist_ok=True)` cria a pasta `logs/` se não existir (já presente).
- O helper `_nome_arquivo_log` é total (sempre retorna um dos dois nomes) e não lança;
  com `argv`/`modulos` ausentes usa os globais reais.

## Testes

Adicionar testes unitários para o helper puro `_nome_arquivo_log` (sem tocar no
filesystem), exercitando os três caminhos via injeção de `argv`/`modulos`:

1. `_nome_arquivo_log(argv=["prog"], modulos={})` → `"producao.log"`.
2. `_nome_arquivo_log(argv=["prog", "--test"], modulos={})` → `"testes.log"`.
3. `_nome_arquivo_log(argv=["prog"], modulos={"pytest": object()})` → `"testes.log"`.

> Observação: a suíte é executada sob `pytest`, então qualquer chamada **sem** injeção
> (`_nome_arquivo_log()`) sempre cai em `"testes.log"` durante os testes — por isso os
> testes injetam `modulos={}` explicitamente para conseguir exercitar o caminho de
> produção. Isso também valida que a configuração de logging da própria suíte passa a
> escrever em `logs/testes.log` (efeito desejado: produção não é poluída pelos testes).

O acesso ao helper nos testes segue o padrão existente do repositório
(`import monitor_diario_oficial as monitor`); o helper deve ser acessível como
`monitor.config._nome_arquivo_log` (ou reexportado conforme o padrão do projeto).

## Critérios de sucesso

- Execução normal grava em `logs/producao.log`; `--test` e `pytest` gravam em
  `logs/testes.log`.
- Nenhum `.log` novo é criado na raiz do projeto.
- Rotação e formato de log inalterados; console inalterado.
- Os 3 testes do helper passam e a suíte completa continua verde.
- README e `.env.example` refletem a nova estrutura.
