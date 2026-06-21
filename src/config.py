"""Configuração: variáveis de ambiente, constantes e logging.

Centraliza a leitura do .env, as constantes da aplicação e o logger
compartilhado (`log`), importado pelos demais módulos.
"""
import contextlib
import json
import os
import re
import sys
import logging
import logging.handlers

# Carrega variáveis do .env (se existir) antes de ler os os.environ.get().
# python-dotenv não sobrescreve variáveis já definidas no ambiente do SO.
try:
    from dotenv import load_dotenv
    load_dotenv(encoding="utf-8", override=False)
except ImportError:
    pass  # sem python-dotenv, usa apenas variáveis de ambiente do SO

# Raiz do projeto = diretório-pai deste pacote src/. Mantém as pastas padrão
# (.whatsapp_profile, logs, pdfs_temporarios) na raiz, não dentro de src/.
_BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# ─────────────────────────────────────────────
# CONFIGURAÇÕES DO USUÁRIO
# ─────────────────────────────────────────────
# Todos os valores sensíveis devem ser definidos no arquivo .env.
# Nenhum dado real (nomes, grupos, senhas) deve aparecer neste código.
#
# Variáveis de ambiente reconhecidas:
#   NOMES_MONITORADOS    — nomes separados por vírgula (MAIÚSCULAS)          [obrigatório]
#   WHATSAPP_GRUPO       — nome exato do grupo no WhatsApp                   [obrigatório]
#   WHATSAPP_GRUPO_TESTE — grupo de testes usado com a flag --test (padrão: "TESTES SCRIPTs") [opcional]
#   NOME_SALA            — identificação da sala exibida nas mensagens        [obrigatório]
#   SECRETARIAS_MOSSORO  — secretarias monitoradas, separadas por vírgula    [opcional]
#   TIMEOUT_QR_CODE      — segundos para escanear o QR code (padrão: 120)   [opcional]
#   WHATSAPP_PROFILE_DIR — caminho do perfil Chrome para sessão WhatsApp     [opcional]
#   LOG_DIR              — pasta de logs (padrão: subpasta logs/)            [opcional]
#   HORARIO_EXECUCAO     — horário HH:MM para --agendar (padrão: 05:00)     [opcional]
# ─────────────────────────────────────────────

def _ler_lista_env(chave: str, padrao: list[str]) -> list[str]:
    """Lê lista separada por vírgula de variável de ambiente; usa padrão se vazia."""
    valor = os.environ.get(chave, "").strip()
    if valor:
        return [item.strip().upper() for item in valor.split(",") if item.strip()]
    return padrao


def _ler_env_obrigatorio(chave: str) -> str:
    """Lê variável de ambiente obrigatória; encerra com erro claro se ausente."""
    valor = os.environ.get(chave, "").strip()
    if not valor:
        print(
            f"\n[ERRO] Variável de ambiente obrigatória não definida: {chave}\n"
            f"       Defina-a no arquivo .env antes de executar o script.\n",
            file=sys.stderr,
        )
        sys.exit(1)
    return valor


def _ler_int_env(chave: str, padrao: int) -> int:
    """Lê variável de ambiente inteira; usa o padrão se ausente ou inválida.

    Avisa (stderr) em vez de propagar ValueError, pois um valor mal digitado
    no .env (vazio, com espaços ou não numérico) não deve travar o import do
    módulo — e o logger ainda não existe neste ponto da inicialização.
    """
    valor = os.environ.get(chave, "").strip()
    if not valor:
        return padrao
    try:
        return int(valor)
    except ValueError:
        print(
            f"\n[AVISO] Variável de ambiente {chave}='{valor}' não é um inteiro "
            f"válido — usando o padrão {padrao}.\n",
            file=sys.stderr,
        )
        return padrao


# ── Nomes monitorados ────────────────────────────────────────────────────────
# Obrigatório via .env. Nenhum nome real fica hardcoded no código.
NOMES_MONITORADOS: list[str] = _ler_lista_env("NOMES_MONITORADOS", [])
if not NOMES_MONITORADOS:
    _ler_env_obrigatorio("NOMES_MONITORADOS")   # dispara mensagem de erro

# ── Secretarias monitoradas (Fofoca da Secretaria) ───────────────────────────
# Pode ser sobrescrita via SECRETARIAS_MOSSORO no .env.
# Para ativar outras secretarias, remova o '#' da linha correspondente.
_SECRETARIAS_PADRAO = [
    "SECRETARIA MUNICIPAL DE INFRAESTRUTURA",
    # "SECRETARIA MUNICIPAL DE SAÚDE",
    # "SECRETARIA MUNICIPAL DE EDUCAÇÃO",
    # "SECRETARIA MUNICIPAL DE FINANÇAS",
    # "SECRETARIA MUNICIPAL DE ADMINISTRAÇÃO",
    # "SECRETARIA MUNICIPAL DE ASSISTÊNCIA SOCIAL",
    # "SECRETARIA MUNICIPAL DE PLANEJAMENTO",
    # "SECRETARIA MUNICIPAL DE MEIO AMBIENTE",
    # "SECRETARIA MUNICIPAL DE AGRICULTURA",
    # "SECRETARIA MUNICIPAL DE HABITAÇÃO",
    # "SECRETARIA MUNICIPAL DE TURISMO",
    # "SECRETARIA MUNICIPAL DE CULTURA",
    # "SECRETARIA MUNICIPAL DE ESPORTES",
    # "SECRETARIA MUNICIPAL DE SEGURANÇA",
    # "SECRETARIA MUNICIPAL DE TRANSPORTES",
    # "SECRETARIA MUNICIPAL DE COMUNICAÇÃO",
    # "SECRETARIA MUNICIPAL DE DESENVOLVIMENTO ECONÔMICO",
    # "SECRETARIA MUNICIPAL DE OBRAS",
    # "SECRETARIA MUNICIPAL DE SERVIÇOS URBANOS",
    # "SECRETARIA MUNICIPAL DE DEFESA CIVIL",
    # "GABINETE DO PREFEITO",
    # "PROCURADORIA GERAL DO MUNICÍPIO",
    # "CONTROLADORIA GERAL DO MUNICÍPIO",
]
SECRETARIAS_MOSSORO: list[str] = _ler_lista_env("SECRETARIAS_MOSSORO", _SECRETARIAS_PADRAO)

# ── Grupo e identificação da sala ────────────────────────────────────────────
# Obrigatórios via .env — não há padrão hardcoded para evitar envio acidental.
WHATSAPP_GRUPO: str = _ler_env_obrigatorio("WHATSAPP_GRUPO")
NOME_SALA: str       = _ler_env_obrigatorio("NOME_SALA")

# Grupo de testes — destino das mensagens quando o script roda com a flag --test.
# Opcional; padrão "TESTES SCRIPTs". Evita enviar testes ao grupo real.
WHATSAPP_GRUPO_TESTE: str = os.environ.get("WHATSAPP_GRUPO_TESTE", "TESTES SCRIPTs").strip()

# ── Parâmetros operacionais ──────────────────────────────────────────────────
TIMEOUT_QR_CODE: int = _ler_int_env("TIMEOUT_QR_CODE", 120)

# URL base do Diário Oficial de Mossoró (pública — não é dado sensível)
BASE_URL = "https://dom.mossoro.rn.gov.br"

# Perfil Chrome com sessão do WhatsApp (pasta ".whatsapp_profile" ao lado do script).
_profile_padrao = os.path.join(_BASE_DIR, ".whatsapp_profile")
WHATSAPP_PROFILE_DIR: str = os.environ.get("WHATSAPP_PROFILE_DIR", _profile_padrao)

# Pasta de logs (padrão: subpasta "logs" ao lado do script).
# Os nomes dos arquivos (producao.log / testes.log) são escolhidos em _nome_arquivo_log.
LOG_DIR: str = os.environ.get("LOG_DIR", os.path.join(_BASE_DIR, "logs"))

# Pasta para PDFs temporários gerados durante o fatiamento do Diário Oficial.
# Configurável via PDF_TEMP_DIR no .env; padrão: "pdfs_temporarios" ao lado do script.
_pdf_temp_padrao = os.path.join(_BASE_DIR, "pdfs_temporarios")
PDF_TEMP_DIR: str = os.environ.get("PDF_TEMP_DIR", _pdf_temp_padrao)


# ─────────────────────────────────────────────
# CONFIGURAÇÃO DE LOG
# ─────────────────────────────────────────────

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


def configurar_logging() -> logging.Logger:
    """
    Configura e retorna o logger principal da aplicação.

    - Console: nível INFO, formato simples (timestamp + nível + mensagem)
    - Arquivo:  nível DEBUG, formato detalhado (função + linha), rotativo
                (máx. 5 MB por arquivo, 3 backups mantidos)
    - Loggers de terceiros ruidosos (selenium, urllib3, WDM) são silenciados
      para WARNING, mantendo o log limpo.
    """
    logger = logging.getLogger("monitor_dom")
    logger.setLevel(logging.DEBUG)  # captura tudo; handlers filtram por nível

    if logger.handlers:
        # Evita duplicação de handlers se a função for chamada mais de uma vez
        return logger

    # ── Formato simples para o console ──────────────────────────────────────
    fmt_console = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(fmt_console)

    # ── Formato detalhado para o arquivo (inclui função e linha) ────────────
    fmt_arquivo = logging.Formatter(
        "%(asctime)s [%(levelname)-8s] %(funcName)s:%(lineno)d — %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    os.makedirs(LOG_DIR, exist_ok=True)
    os.makedirs(PDF_TEMP_DIR, exist_ok=True)
    log_path = os.path.join(LOG_DIR, _nome_arquivo_log())
    arquivo_handler = logging.handlers.RotatingFileHandler(
        log_path,
        maxBytes=5 * 1024 * 1024,  # 5 MB
        backupCount=3,
        encoding="utf-8",
    )
    arquivo_handler.setLevel(logging.DEBUG)
    arquivo_handler.setFormatter(fmt_arquivo)

    logger.addHandler(console_handler)
    logger.addHandler(arquivo_handler)

    # ── Silencia loggers ruidosos de bibliotecas terceiras ──────────────────
    for nome_lib in ("selenium", "urllib3", "WDM", "webdriver_manager"):
        logging.getLogger(nome_lib).setLevel(logging.WARNING)

    return logger


log = configurar_logging()


def _atualizar_env(chave: str, valor: str) -> None:
    """
    Atualiza ou insere uma chave no arquivo .env da raiz do projeto.

    - Se a chave já existe (linha não comentada), substitui o valor.
    - Se não existe, acrescenta ao final do arquivo.
    """
    env_path = os.path.join(_BASE_DIR, ".env")
    if not os.path.isfile(env_path):
        log.warning(f"Arquivo .env não encontrado em: {env_path} — valor não salvo.")
        return

    try:
        with open(env_path, encoding="utf-8") as f:
            linhas = f.readlines()
    except OSError as e:
        log.error(f"Falha ao ler {env_path}: {e} — valor não salvo.")
        return

    padrao = re.compile(rf"^{re.escape(chave)}\s*=")
    nova_linha = f"{chave}={valor}\n"
    encontrou = False
    for i, linha in enumerate(linhas):
        if padrao.match(linha):
            linhas[i] = nova_linha
            encontrou = True
            break

    if not encontrou:
        # Garante quebra de linha antes da nova entrada
        if linhas and not linhas[-1].endswith("\n"):
            linhas.append("\n")
        linhas.append(nova_linha)

    # Escrita atômica: grava num temporário no MESMO diretório e troca via
    # os.replace (rename atômico no mesmo filesystem). Evita corromper/truncar
    # o .env se o processo morrer no meio da escrita — o arquivo é o dado de
    # configuração do usuário, não versionado.
    tmp_path = env_path + ".tmp"
    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            f.writelines(linhas)
        os.replace(tmp_path, env_path)
    except OSError as e:
        log.error(f"Falha ao gravar {env_path}: {e} — valor não salvo.")
        if os.path.isfile(tmp_path):
            with contextlib.suppress(OSError):
                os.remove(tmp_path)
        return

    log.info(f".env atualizado: {chave}={valor}")


# ─────────────────────────────────────────────
# ESTADO DE ENVIO — idempotência por etapa
# ─────────────────────────────────────────────
# Registra, por número de edição, quais etapas de envio (texto/pdfs/fofoca) já
# foram confirmadas. Permite que um retry da MESMA edição pule o que já foi
# enviado — em vez de reenviar o texto quando, p.ex., só o anexo PDF falhou.
# É um arquivo de estado descartável (regenerável); não é a config do usuário.

_ESTADO_ENVIO_PATH = os.path.join(_BASE_DIR, ".envio_estado.json")
_MAX_EDICOES_ESTADO = 20  # mantém só as N edições mais recentes (cap de tamanho)


def _ler_estado_envio() -> dict:
    """Lê o estado de envio do disco; trata ausência/corrupção como vazio."""
    try:
        with open(_ESTADO_ENVIO_PATH, encoding="utf-8") as f:
            dados = json.load(f)
        return dados if isinstance(dados, dict) else {}
    except (OSError, ValueError):
        return {}


def _gravar_estado_envio(estado: dict) -> None:
    """Grava o estado de envio de forma atômica (temporário + os.replace)."""
    tmp_path = _ESTADO_ENVIO_PATH + ".tmp"
    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(estado, f, ensure_ascii=False)
        os.replace(tmp_path, _ESTADO_ENVIO_PATH)
    except OSError as e:
        log.warning(f"Falha ao gravar estado de envio: {e}")
        if os.path.isfile(tmp_path):
            with contextlib.suppress(OSError):
                os.remove(tmp_path)


def _prune_estado(estado: dict) -> None:
    """Mantém só as _MAX_EDICOES_ESTADO edições de maior número (mais recentes)."""
    if len(estado) <= _MAX_EDICOES_ESTADO:
        return

    def _num(chave: str) -> int:
        try:
            return int(chave)
        except ValueError:
            return -1

    for chave in sorted(estado, key=_num)[:-_MAX_EDICOES_ESTADO]:
        estado.pop(chave, None)


def etapas_enviadas(id_edicao) -> set[str]:
    """Conjunto de etapas já confirmadas para a edição (vazio se nenhuma/sem id)."""
    if id_edicao is None:
        return set()
    return set(_ler_estado_envio().get(str(id_edicao), []))


def marcar_etapa_enviada(id_edicao, etapa: str) -> None:
    """Persiste em disco que uma etapa de envio foi concluída para a edição.

    No-op quando id_edicao é None (modo teste ou edição sem número), preservando
    o comportamento de sempre reenviar nesses casos.
    """
    if id_edicao is None:
        return
    estado = _ler_estado_envio()
    chave = str(id_edicao)
    etapas = set(estado.get(chave, []))
    etapas.add(etapa)
    estado[chave] = sorted(etapas)
    _prune_estado(estado)
    _gravar_estado_envio(estado)
