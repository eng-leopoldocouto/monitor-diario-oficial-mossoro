"""Configuração: variáveis de ambiente, constantes e logging.

Centraliza a leitura do .env, as constantes da aplicação e o logger
compartilhado (`log`), importado pelos demais módulos.
"""
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
TIMEOUT_QR_CODE: int = int(os.environ.get("TIMEOUT_QR_CODE", "120"))

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

    with open(env_path, "r", encoding="utf-8") as f:
        linhas = f.readlines()

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

    with open(env_path, "w", encoding="utf-8") as f:
        f.writelines(linhas)

    log.info(f".env atualizado: {chave}={valor}")
