# ============================================================
# monitor_diario_oficial.py
# Monitora o Diário Oficial de Mossoró buscando nomes
# e envia alertas via WhatsApp Web usando Selenium
#
# Dependências:
#   pip install requests beautifulsoup4 selenium webdriver-manager
#
# CONFIGURAÇÃO NECESSÁRIA (edite as seções marcadas com TODO):
#   - NOMES_MONITORADOS: lista de nomes a pesquisar
#   - WHATSAPP_GRUPO: nome exato do grupo no WhatsApp
#
# PRIMEIRA EXECUÇÃO:
#   O Chrome abrirá automaticamente. Escaneie o QR code no
#   WhatsApp do celular. A sessão fica salva em .whatsapp_profile/
#   e não precisará ser repetida nas próximas execuções.
# ============================================================

import io
import os
import re
import sys
import time
import ctypes
import logging
import logging.handlers
import platform
import unicodedata
from datetime import datetime, timedelta

import requests
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.service import Service

try:
    from webdriver_manager.chrome import ChromeDriverManager
except ImportError:
    ChromeDriverManager = None  # type: ignore

# Carrega variáveis do arquivo .env (se existir) antes de ler os os.environ.get().
# python-dotenv não sobrescreve variáveis já definidas no ambiente do SO.
try:
    from dotenv import load_dotenv
    load_dotenv(encoding="utf-8", override=False)
except ImportError:
    pass  # sem python-dotenv, usa apenas variáveis de ambiente do SO

# ─────────────────────────────────────────────
# CONFIGURAÇÕES DO USUÁRIO
# ─────────────────────────────────────────────
# Todos os valores sensíveis devem ser definidos no arquivo .env.
# Nenhum dado real (nomes, grupos, senhas) deve aparecer neste código.
#
# Variáveis de ambiente reconhecidas:
#   NOMES_MONITORADOS    — nomes separados por vírgula (MAIÚSCULAS)          [obrigatório]
#   WHATSAPP_GRUPO       — nome exato do grupo no WhatsApp                   [obrigatório]
#   NOME_SALA            — identificação da sala exibida nas mensagens        [obrigatório]
#   SECRETARIAS_MOSSORO  — secretarias monitoradas, separadas por vírgula    [opcional]
#   TIMEOUT_QR_CODE      — segundos para escanear o QR code (padrão: 120)   [opcional]
#   WHATSAPP_PROFILE_DIR — caminho do perfil Chrome para sessão WhatsApp     [opcional]
#   LOG_DIR              — pasta de logs (padrão: mesma pasta do script)     [opcional]
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

# ── Parâmetros operacionais ──────────────────────────────────────────────────
TIMEOUT_QR_CODE: int = int(os.environ.get("TIMEOUT_QR_CODE", "120"))

# URL base do Diário Oficial de Mossoró (pública — não é dado sensível)
BASE_URL = "https://dom.mossoro.rn.gov.br"

# Perfil Chrome com sessão do WhatsApp (pasta ".whatsapp_profile" ao lado do script).
_profile_padrao = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".whatsapp_profile")
WHATSAPP_PROFILE_DIR: str = os.environ.get("WHATSAPP_PROFILE_DIR", _profile_padrao)

# Pasta de logs (padrão: mesma pasta do script).
LOG_DIR: str = os.environ.get("LOG_DIR", os.path.dirname(os.path.abspath(__file__)))

# Pasta para PDFs temporários gerados durante o fatiamento do Diário Oficial.
# Configurável via PDF_TEMP_DIR no .env; padrão: "pdfs_temporarios" ao lado do script.
_pdf_temp_padrao = os.path.join(os.path.dirname(os.path.abspath(__file__)), "pdfs_temporarios")
PDF_TEMP_DIR: str = os.environ.get("PDF_TEMP_DIR", _pdf_temp_padrao)


# ─────────────────────────────────────────────
# CONFIGURAÇÃO DE LOG
# ─────────────────────────────────────────────

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
    log_path = os.path.join(LOG_DIR, "monitor_dom.log")
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


# ─────────────────────────────────────────────
# UTILITÁRIOS INTERNOS
# ─────────────────────────────────────────────

def _colar_windows(elemento, texto: str) -> None:
    """
    Cola texto via clipboard do Windows (ctypes) — somente Windows 64-bit.

    No Windows 64-bit é obrigatório declarar restype/argtypes para funções que
    retornam ou recebem handles/ponteiros; sem isso ctypes usa c_int (32 bits)
    e trunca endereços de 64 bits, causando access violation ou OverflowError.
    """
    CF_UNICODETEXT = 13
    GMEM_MOVEABLE = 0x0002
    encoded = texto.encode("utf-16-le") + b"\x00\x00"
    k32 = ctypes.windll.kernel32   # type: ignore[attr-defined]
    u32 = ctypes.windll.user32     # type: ignore[attr-defined]

    k32.GlobalAlloc.restype = ctypes.c_void_p
    k32.GlobalAlloc.argtypes = [ctypes.c_uint, ctypes.c_size_t]
    k32.GlobalLock.restype = ctypes.c_void_p
    k32.GlobalLock.argtypes = [ctypes.c_void_p]
    k32.GlobalUnlock.argtypes = [ctypes.c_void_p]
    u32.OpenClipboard.argtypes = [ctypes.c_void_p]
    u32.SetClipboardData.restype = ctypes.c_void_p
    u32.SetClipboardData.argtypes = [ctypes.c_uint, ctypes.c_void_p]

    u32.OpenClipboard(None)
    u32.EmptyClipboard()
    handle = k32.GlobalAlloc(GMEM_MOVEABLE, len(encoded))
    ptr = k32.GlobalLock(handle)
    ctypes.memmove(ptr, encoded, len(encoded))
    k32.GlobalUnlock(handle)
    u32.SetClipboardData(CF_UNICODETEXT, handle)
    u32.CloseClipboard()

    elemento.click()
    elemento.send_keys(Keys.CONTROL, "v")


def _colar_no_elemento(driver, elemento, texto: str) -> None:
    """
    Insere texto em um elemento do Selenium de forma cross-platform.

    Suporta qualquer Unicode — incluindo emoji (📂 🔔 📅, código > U+FFFF) —
    sem depender do clipboard do sistema operacional.
    Funciona com ChromeDriver local.

    Estratégia em cascata:
      1. CDP Input.insertText   — nativo do Chrome, sem clipboard, qualquer Unicode
      2. JavaScript execCommand — fallback para contenteditable (ainda suportado)
      3. Clipboard Windows      — fallback para Windows local (ctypes)
      4. send_keys              — último recurso (não suporta emoji > U+FFFF)
    """
    elemento.click()
    time.sleep(0.15)

    # Seleciona todo conteúdo existente para que a inserção substitua o texto atual
    elemento.send_keys(Keys.CONTROL, "a")
    time.sleep(0.05)

    # ── Estratégia 1: CDP Input.insertText ──────────────────────────────────
    # Funciona em Chrome local.
    # Insere texto no ponto de foco atual (substitui seleção), sem restrição BMP.
    try:
        driver.execute_cdp_cmd("Input.insertText", {"text": texto})
        log.debug("_colar_no_elemento: texto inserido via CDP Input.insertText")
        return
    except Exception as e:
        log.debug(f"CDP Input.insertText indisponível: {e}")

    # ── Estratégia 2: JavaScript execCommand + native value setter ───────────
    # execCommand('insertText') funciona em contenteditable.
    # Para <input>/<textarea>, usa o native setter do React/Vue para disparar
    # os eventos de mudança corretamente.
    try:
        inserido = driver.execute_script(
            """
            var el = arguments[0], txt = arguments[1];
            el.focus();
            if (el.isContentEditable) {
                document.execCommand('selectAll', false, null);
                return document.execCommand('insertText', false, txt);
            }
            var proto = el.tagName === 'TEXTAREA'
                ? window.HTMLTextAreaElement.prototype
                : window.HTMLInputElement.prototype;
            var setter = Object.getOwnPropertyDescriptor(proto, 'value');
            if (setter && setter.set) {
                setter.set.call(el, txt);
                el.dispatchEvent(new Event('input',  { bubbles: true }));
                el.dispatchEvent(new Event('change', { bubbles: true }));
                return true;
            }
            return false;
            """,
            elemento,
            texto,
        )
        if inserido:
            log.debug("_colar_no_elemento: texto inserido via JavaScript execCommand")
            return
    except Exception as e:
        log.debug(f"JavaScript execCommand falhou: {e}")

    # ── Estratégia 3: clipboard do Windows (somente Windows local) ───────────
    if platform.system() == "Windows":
        try:
            _colar_windows(elemento, texto)
            log.debug("_colar_no_elemento: texto inserido via clipboard Windows")
            return
        except Exception as e:
            log.debug(f"Clipboard Windows falhou: {e}")

    # ── Estratégia 4: send_keys (último recurso) ─────────────────────────────
    # Não suporta emoji > U+FFFF — pode lançar erro do ChromeDriver.
    log.warning("_colar_no_elemento: usando send_keys (não suporta emoji > U+FFFF)")
    elemento.send_keys(texto)


def _atualizar_env(chave: str, valor: str) -> None:
    """
    Atualiza ou insere uma chave no arquivo .env ao lado do script.

    - Se a chave já existe (linha não comentada), substitui o valor.
    - Se não existe, acrescenta ao final do arquivo.
    """
    env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
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


# ─────────────────────────────────────────────
# FUNÇÕES PRINCIPAIS
# ─────────────────────────────────────────────

def obter_data_anterior() -> str:
    """
    Retorna a data do dia anterior ao sistema (Windows/Linux),
    no formato DD/MM/AAAA.
    """
    ontem = datetime.now() - timedelta(days=1)
    return ontem.strftime("%d/%m/%Y")


def buscar_publicacao_por_data(data_str: str) -> dict | None:
    """
    Acessa a página de edições do DOM e procura a publicação
    correspondente à data informada (formato DD/MM/AAAA).

    Retorna um dicionário com:
        id        - ID numérico da publicação
        numero    - número da edição (ex: 813)
        data      - data formatada
        url_html  - URL da página com o conteúdo
        url_pdf   - URL do PDF (se disponível na página inicial)
    Retorna None se não encontrar edição para a data.
    """
    log.info(f"Buscando edição do DOM para a data: {data_str}")

    # Converte DD/MM/AAAA → objeto date para comparação
    try:
        data_alvo = datetime.strptime(data_str, "%d/%m/%Y").date()
    except ValueError:
        log.error(f"Formato de data inválido: {data_str}")
        return None

    headers = {"User-Agent": "Mozilla/5.0 (compatible; DOM-Monitor/1.0)"}

    # Itera páginas de edições (o site lista ~8 por página)
    pagina = 1
    while True:
        url = f"{BASE_URL}/dom/edicoes?page={pagina}"
        try:
            resp = requests.get(url, headers=headers, timeout=30)
            resp.raise_for_status()
        except requests.RequestException as e:
            log.error(f"Erro ao acessar lista de edições: {e}")
            return None

        soup = BeautifulSoup(resp.text, "html.parser")

        # Cada card de edição tem uma tag de data e um link para a publicação
        cards = soup.select("a[href^='/dom/publicacao/']")

        if not cards:
            log.warning("Nenhuma edição encontrada na página — encerrando busca.")
            return None

        for card in cards:
            href = card.get("href", "")
            # Extrai o ID da publicação da URL
            match = re.search(r"/dom/publicacao/(\d+)", href)
            if not match:
                continue
            pub_id = match.group(1)

            # Busca a data associada ao card (elemento próximo com formato de data)
            parent = card.find_parent()
            texto = parent.get_text(" ", strip=True) if parent else ""
            date_match = re.search(r"(\d{2}/\d{2}/\d{4})", texto)
            if not date_match:
                continue

            data_card = datetime.strptime(date_match.group(1), "%d/%m/%Y").date()

            if data_card == data_alvo:
                # Monta URL do PDF (padrão observado no site)
                url_html = f"{BASE_URL}/dom/publicacao/{pub_id}"
                log.info(f"Edição encontrada: publicação ID {pub_id} — {url_html}")
                return {
                    "id": pub_id,
                    "data": data_str,
                    "url_html": url_html,
                }

            # Se a data do card já é mais antiga que o alvo, para a busca
            if data_card < data_alvo:
                log.info(f"Data {data_str} não encontrada no DOM (sem publicação nesse dia).")
                return None

        pagina += 1
        if pagina > 20:  # Proteção contra loop infinito
            log.warning("Limite de páginas atingido sem encontrar a data.")
            return None


def buscar_ultima_publicacao() -> dict | None:
    """
    Retorna a publicação mais recente do Diário Oficial de Mossoró —
    o primeiro card exibido na página de edições (item em destaque).

    Não filtra por data; sempre pega o topo da listagem.

    Retorna dicionário com:
        id       - ID numérico da publicação
        data     - data formatada (DD/MM/AAAA) extraída do card
        url_html - URL da página com o conteúdo
    """
    log.info("Buscando última edição do DOM (primeiro card do site)...")
    headers = {"User-Agent": "Mozilla/5.0 (compatible; DOM-Monitor/1.0)"}
    url = f"{BASE_URL}/dom/edicoes"
    try:
        resp = requests.get(url, headers=headers, timeout=30)
        resp.raise_for_status()
    except requests.RequestException as e:
        log.error(f"Erro ao acessar página de edições: {e}")
        return None

    soup = BeautifulSoup(resp.text, "html.parser")
    cards = soup.select("a[href^='/dom/publicacao/']")

    if not cards:
        log.warning("Nenhuma edição encontrada na página de edições.")
        return None

    # Primeiro card = edição mais recente / em destaque
    card = cards[0]
    href = card.get("href", "")
    match = re.search(r"/dom/publicacao/(\d+)", href)
    if not match:
        log.error(f"Não foi possível extrair ID da publicação de: {href}")
        return None

    pub_id = match.group(1)
    parent = card.find_parent()
    texto = parent.get_text(" ", strip=True) if parent else ""
    date_match = re.search(r"(\d{2}/\d{2}/\d{4})", texto)
    data_str = date_match.group(1) if date_match else "data desconhecida"

    # Extrai o número da edição do DOM (ex: "DOM Nº 820" → 820)
    num_match = re.search(r"DOM\s+N[ºo°]?\s*(\d+)", texto, re.IGNORECASE)
    numero = int(num_match.group(1)) if num_match else None

    url_html = f"{BASE_URL}/dom/publicacao/{pub_id}"
    log.info(f"Última edição: ID {pub_id} — Nº {numero} — {data_str} — {url_html}")
    return {"id": pub_id, "numero": numero, "data": data_str, "url_html": url_html}


def extrair_portarias(url_html: str) -> list[dict]:
    """
    Acessa a página HTML da publicação e extrai todas as portarias.

    Cada portaria é representada como um dicionário:
        titulo    - linha do título (ex: "PORTARIA Nº 072/2026 - GP/CMM")
        ementa    - primeira linha descritiva
        conteudo  - texto completo do bloco da portaria
    """
    log.info(f"Extraindo portarias de: {url_html}")
    headers = {"User-Agent": "Mozilla/5.0 (compatible; DOM-Monitor/1.0)"}

    try:
        resp = requests.get(url_html, headers=headers, timeout=30)
        resp.raise_for_status()
    except requests.RequestException as e:
        log.error(f"Erro ao acessar página da publicação: {e}")
        return []

    soup = BeautifulSoup(resp.text, "html.parser")

    portarias = []
    conteudo_principal = soup.select_one("#main-content") or soup.body

    if not conteudo_principal:
        log.warning("Não foi possível identificar o conteúdo principal da página.")
        return []

    # Substitui cada <div class="ato_separator"> por um marcador de texto único
    # antes de extrair o texto plano — isso delimita exatamente cada ato.
    MARCADOR = "\x00ATO_SEP\x00"
    conteudo_copia = BeautifulSoup(str(conteudo_principal), "html.parser")
    for sep in conteudo_copia.find_all("div", class_="ato_separator"):
        sep.replace_with(MARCADOR)

    texto_completo = conteudo_copia.get_text("\n", strip=False)
    blocos = [b.strip() for b in texto_completo.split(MARCADOR) if b.strip()]

    log.info(f"Blocos de ato encontrados (separados por ato_separator): {len(blocos)}")

    # Padrões de início de ato para identificar o título dentro de cada bloco
    padroes_ato = re.compile(
        r"(?:PORTARIA|DECRETO|LEI|RESOLUÇÃO|RESOLUCAO|ATO|TERMO|EXTRATO|AVISO|EDITAL)"
        r"[^\n]{0,200}",
        re.IGNORECASE,
    )

    for bloco in blocos:
        linhas = bloco.split("\n")
        titulo = None
        ementa = ""
        conteudo_linhas = []
        ultima_vazia = False

        for linha in linhas:
            stripped = linha.strip()

            if not stripped:
                # Linha em branco — preserva parágrafo dentro do ato (sem duplicar)
                if titulo is not None and not ultima_vazia:
                    conteudo_linhas.append("")
                ultima_vazia = True
                continue

            ultima_vazia = False

            if titulo is None and padroes_ato.match(stripped):
                titulo = stripped

            if titulo is not None:
                if not ementa and stripped != titulo:
                    ementa = stripped
                conteudo_linhas.append(stripped)

        if titulo:
            # Remove linhas em branco no final do conteúdo
            while conteudo_linhas and not conteudo_linhas[-1]:
                conteudo_linhas.pop()
            portarias.append({
                "titulo": titulo,
                "ementa": ementa,
                "conteudo": "\n".join(conteudo_linhas),
            })

    log.info(f"Total de atos extraídos: {len(portarias)}")
    return portarias


def buscar_nomes_em_portarias(portarias: list[dict], nomes: list[str]) -> list[dict]:
    """
    Varre todas as portarias buscando os nomes da lista monitorada.

    Retorna uma lista de ocorrências, cada uma com:
        nome      - nome encontrado
        portaria  - dicionário com dados da portaria onde foi achado
    """
    encontrados = []
    nomes_upper = [n.upper() for n in nomes]
    for portaria in portarias:
        texto_busca = " ".join(portaria["conteudo"].upper().split())
        for nome in nomes_upper:
            if nome in texto_busca:
                log.info(f"Nome encontrado: '{nome}' na portaria: {portaria['titulo']}")
                encontrados.append({
                    "nome": nome,
                    "portaria": portaria,
                })

    return encontrados


def _extrair_dados_fofoca(paragrafo: str, secretaria: str) -> dict | None:
    """
    Extrai nome, ação, cargo e símbolo CC de um parágrafo de portaria.
    Retorna None se não conseguir extrair ação + pessoa mínimos.

    O parágrafo pode chegar em NFKD (vindo de detectar_fofocas) — é normalizado
    para NFC internamente para que as regexes com acentos compostos funcionem.

    Padrões suportados:
      NOMEAR: "NOMEAR <NOME> PARA EXERCER O CARGO EM COMISSÃO DE <CARGO>, SÍMBOLO <CC>"
      EXONERAR: "EXONERAR [A SERVIDORA|O SERVIDOR] <NOME> DO CARGO EM COMISSÃO DE <CARGO>"
    """
    # Normaliza para NFC: detectar_fofocas usa NFKD para comparar secretarias,
    # mas as regexes esperam chars acentuados compostos (ex: "Ã" e não "A"+combining).
    paragrafo = unicodedata.normalize("NFC", paragrafo)
    secretaria = unicodedata.normalize("NFC", secretaria)

    MAPA_ACAO = {
        "NOMEAR":    "NOMEADO(A)",
        "NOMEIA":    "NOMEADO(A)",
        "NOMEADO":   "NOMEADO(A)",
        "NOMEADA":   "NOMEADO(A)",
        "EXONERAR":  "EXONERADO(A)",
        "EXONERA":   "EXONERADO(A)",
        "EXONERADO": "EXONERADO(A)",
        "EXONERADA": "EXONERADO(A)",
    }

    # Ação
    m_acao = re.search(
        r'\b(NOMEAR|NOMEIA|NOMEADO[A]?|EXONERAR|EXONERA|EXONERADO[A]?)\b',
        paragrafo,
    )
    if not m_acao:
        return None
    acao = MAPA_ACAO.get(m_acao.group(1), "NOMEADO(A)")

    # Nome da pessoa — estratégia diferente por tipo de ação:
    #
    # NOMEAR: "NOMEAR <NOME> PARA EXERCER..."
    #   → nome termina antes de "PARA"
    #
    # EXONERAR: "EXONERAR [A SERVIDORA|O SERVIDOR] <NOME> DO CARGO..."
    #   → skipa artigo + "servidor(a)" opcionais; nome termina antes de "DO/DA CARGO"
    #
    # Usamos regex gananciosa com backtracking: o grupo captura o máximo possível
    # de palavras e recua até o lookahead de parada ser satisfeito — isso permite
    # nomes com preposições internas como "GURGEL DA NOBREGA".
    _LETRAS = r'[A-ZÁÉÍÓÚÂÊÎÔÛÃÕÀÈÌÒÙÇ]'
    _PALAVRA = rf'{_LETRAS}+'
    _NOME_GREED = rf'(?:{_PALAVRA}\s+)*{_PALAVRA}'  # sequência greedy de palavras

    acao_str = m_acao.group(1)
    m_nome = None

    if acao_str.startswith("NOME"):
        # NOMEAR / NOMEIA / NOMEADO(A): nome termina antes de "PARA"
        m_nome = re.search(
            rf'\b(?:NOMEAR|NOMEIA|NOMEADO[A]?)\s+({_NOME_GREED})(?=\s+PARA\b)',
            paragrafo,
        )
        if not m_nome:
            # Fallback: captura até 7 palavras maiúsculas (padrão anterior)
            m_nome = re.search(
                rf'\b(?:NOMEAR|NOMEIA|NOMEADO[A]?)\s+'
                rf'((?:{_LETRAS}{{2,}}\s+){{0,6}}{_LETRAS}{{2,}})',
                paragrafo,
            )
    else:
        # EXONERAR / EXONERA / EXONERADO(A): pula "a servidora" / "o servidor"
        m_nome = re.search(
            rf'\b(?:EXONERAR|EXONERA|EXONERADO[A]?)\s+'
            rf'(?:(?:A|O)\s+)?(?:SERVIDORA?\s+)?'
            rf'({_NOME_GREED})(?=\s+(?:DO|DA|AO|NO|EM)\s+CARGO\b)',
            paragrafo,
        )
        if not m_nome:
            # Fallback: pula artigo/servidor mas sem lookahead de parada
            m_nome = re.search(
                rf'\b(?:EXONERAR|EXONERA|EXONERADO[A]?)\s+'
                rf'(?:(?:A|O)\s+)?(?:SERVIDORA?\s+)?'
                rf'((?:{_LETRAS}{{2,}}\s+){{0,6}}{_LETRAS}{{2,}})',
                paragrafo,
            )

    pessoa = m_nome.group(1).strip() if m_nome else "PESSOA NÃO IDENTIFICADA"

    # Cargo — texto após "CARGO EM COMISSÃO DE", "CARGO DE", "FUNÇÃO DE" ou "EMPREGO DE"
    m_cargo = re.search(
        r'(?:CARGO\s+(?:EM\s+COMISS[AÃ]O\s+DE|DE)|FUN[CÇ][AÃ]O\s+DE|EMPREGO\s+DE)\s+'
        r'(.+?)(?:,|\.|S[IÍ]MBOLO\b|(?=\bCC\d))',
        paragrafo,
    )
    cargo = m_cargo.group(1).strip().rstrip(",").strip() if m_cargo else "cargo não identificado"

    # Símbolo CC
    m_cc = re.search(r'\bCC\s*(\d+)\b', paragrafo)
    simbolo_cc = f"CC{m_cc.group(1)}" if m_cc else None

    # Converte secretaria de volta para Title Case legível
    secretaria_fmt = secretaria.title()

    return {
        "acao": acao,
        "pessoa": pessoa,
        "cargo": cargo,
        "simbolo_cc": simbolo_cc,
        "secretaria": secretaria_fmt,
    }


def detectar_fofocas(portarias: list[dict], secretarias: list[str]) -> list[dict]:
    """
    Varre as portarias extraídas buscando nomeações e exonerações
    vinculadas a secretarias municipais de Mossoró.

    Um parágrafo dispara a detecção quando contém simultaneamente:
      - Palavra-chave de movimentação: NOMEAR ou EXONERAR (e variantes)
      - Nome de uma secretaria da lista

    Retorna lista de dicionários com: acao, pessoa, cargo, simbolo_cc,
    secretaria, portaria.
    """
    fofocas = []
    secretarias_upper = [unicodedata.normalize("NFKD", s.upper()) for s in secretarias]
    RE_ACAO = re.compile(
        r'\b(NOMEAR|NOMEIA|NOMEADO[A]?|EXONERAR|EXONERA|EXONERADO[A]?)\b'
    )

    for portaria in portarias:
        conteudo_norm = unicodedata.normalize("NFKD", portaria["conteudo"].upper())
        paragrafos = [p.strip() for p in conteudo_norm.split("\n") if p.strip()]

        for paragrafo in paragrafos:
            if not RE_ACAO.search(paragrafo):
                continue

            secretaria_encontrada = None
            for sec in secretarias_upper:
                if sec in paragrafo:
                    secretaria_encontrada = sec
                    break

            if not secretaria_encontrada:
                continue

            dados = _extrair_dados_fofoca(paragrafo, secretaria_encontrada)
            if dados:
                dados["portaria"] = portaria
                fofocas.append(dados)
                log.info(
                    f"Fofoca detectada: {dados['acao']} — "
                    f"{dados['pessoa']} — {dados['secretaria']}"
                )

    log.info(f"Total de fofocas detectadas: {len(fofocas)}")
    return fofocas


def promovido_remanejado(fofocas: list[dict]) -> list[dict]:
    """
    Consolida pares exoneração + nomeação da mesma pessoa em um único evento.

    Quando alguém é exonerado de um cargo e nomeado em outro na mesma edição,
    os dois registros separados são substituídos por um único registro com ação:
      PROMOVIDO(A)  — novo símbolo CC tem número MENOR  (cargo mais alto na hierarquia)
      REMANEJADO(A) — novo símbolo CC tem número IGUAL ou MAIOR (mesmo nível ou abaixo)

    Registros sem par (só exoneração ou só nomeação) permanecem inalterados.

    Exemplo:
      CC15 → CC11 : n_novo (11) < n_antigo (15) → PROMOVIDO(A)
      CC11 → CC11 : n_novo (11) = n_antigo (11) → REMANEJADO(A)
      CC11 → CC15 : n_novo (15) > n_antigo (11) → REMANEJADO(A)
    """
    exoneracoes = {f["pessoa"]: f for f in fofocas if "EXONERADO" in f.get("acao", "")}
    nomeacoes   = {f["pessoa"]: f for f in fofocas if "NOMEADO"   in f.get("acao", "")}

    pessoas_consolidadas: set[str] = set()
    consolidados: list[dict] = []

    for pessoa, exon in exoneracoes.items():
        if pessoa not in nomeacoes:
            continue

        nom = nomeacoes[pessoa]
        pessoas_consolidadas.add(pessoa)

        cc_ant_str = exon.get("simbolo_cc") or ""
        cc_nov_str = nom.get("simbolo_cc")  or ""

        # Extrai o número do símbolo CC para comparação (ex: "CC11" → 11)
        m_ant = re.search(r'\d+', cc_ant_str)
        m_nov = re.search(r'\d+', cc_nov_str)

        if m_ant and m_nov and int(m_nov.group()) < int(m_ant.group()):
            acao = "PROMOVIDO(A)"
        else:
            acao = "REMANEJADO(A)"

        consolidados.append({
            "acao":               acao,
            "pessoa":             pessoa,
            "cargo_anterior":     exon.get("cargo", "cargo não identificado"),
            "secretaria_anterior":exon.get("secretaria", "secretaria não identificada"),
            "cc_anterior":        exon.get("simbolo_cc"),
            "cargo_novo":         nom.get("cargo", "cargo não identificado"),
            "secretaria_nova":    nom.get("secretaria", "secretaria não identificada"),
            "cc_novo":            nom.get("simbolo_cc"),
            "portaria_exon":      exon.get("portaria"),
            "portaria_nom":       nom.get("portaria"),
        })
        log.info(
            f"{acao}: {pessoa} | "
            f"{exon.get('secretaria')} → {nom.get('secretaria')}"
        )

    # Mantém registros sem par (exoneração ou nomeação sem correspondente)
    restantes = [f for f in fofocas if f["pessoa"] not in pessoas_consolidadas]

    return consolidados + restantes


def formatar_fofocas(fofocas: list[dict]) -> str:
    """
    Gera a seção "Fofoca da Secretaria" em formato informal/divertido
    para ser anexada à mensagem principal do WhatsApp.
    Sempre exibe o cabeçalho da seção — quando vazia, informa que não houve movimentações.
    """
    linhas = [
        "",
        "🗣️ *FOFOCA DA SECRETARIA*",
    ]

    if not fofocas:
        linhas += [
            "💤 Silêncio absoluto nos bastidores...\nNenhuma movimentação de pessoal detectada nesta edição.",
            "",
        ]
        return "\n".join(linhas)

    linhas += [
        f"_{len(fofocas)} movimentação(ões) de pessoal detectada(s)_",
        "",
    ]

    for fofoca in fofocas:
        pessoa = fofoca.get("pessoa", "???")
        acao   = fofoca.get("acao", "???")

        if acao in ("PROMOVIDO(A)", "REMANEJADO(A)"):
            c_ant  = fofoca.get("cargo_anterior", "cargo não identificado")
            cc_ant = fofoca.get("cc_anterior")
            s_ant  = fofoca.get("secretaria_anterior", "secretaria não identificada")
            c_nov  = fofoca.get("cargo_novo", "cargo não identificado")
            cc_nov = fofoca.get("cc_novo")
            s_nov  = fofoca.get("secretaria_nova", "secretaria não identificada")
            cc_ant_str = f" ({cc_ant})" if cc_ant else ""
            cc_nov_str = f" ({cc_nov})" if cc_nov else ""

            if acao == "PROMOVIDO(A)":
                texto = (
                    f"🔝 *{pessoa}* foi *PROMOVIDO(A)*!\n"
                    f"   De: _{c_ant}{cc_ant_str}_ na _{s_ant}_\n"
                    f"   Para: _{c_nov}{cc_nov_str}_ na _{s_nov}_"
                )
            else:
                texto = (
                    f"🔄 *{pessoa}* foi *REMANEJADO(A)*.\n"
                    f"   De: _{c_ant}{cc_ant_str}_ na _{s_ant}_\n"
                    f"   Para: _{c_nov}{cc_nov_str}_ na _{s_nov}_"
                )

        elif "NOMEADO" in acao:
            cargo      = fofoca.get("cargo", "cargo não identificado")
            cc         = fofoca.get("simbolo_cc")
            secretaria = fofoca.get("secretaria", "secretaria não identificada")
            cc_str     = f" ({cc})" if cc else ""
            texto = (
                f"🔥 *{pessoa}* foi *NOMEADO(A)* no cargo de "
                f"_{cargo}{cc_str}_ na _{secretaria}_!"
            )
        else:
            cargo      = fofoca.get("cargo", "cargo não identificado")
            cc         = fofoca.get("simbolo_cc")
            secretaria = fofoca.get("secretaria", "secretaria não identificada")
            cc_str     = f" ({cc})" if cc else ""
            texto = (
                f"🚪 *{pessoa}* deixou a casa! Foi *EXONERADO(A)* "
                f"do cargo de _{cargo}{cc_str}_ na _{secretaria}_."
            )

        linhas.append(texto)
        linhas.append("")

    return "\n".join(linhas)


def formatar_mensagem(ocorrencias: list[dict], data_str: str, numero: int | None = None) -> str:
    """
    Formata a mensagem principal de WhatsApp com as ocorrências encontradas.
    A seção de fofocas é enviada separadamente após os PDFs.
    """
    edicao_str = f"📅 EDIÇÃO Nº {numero}: {data_str}" if numero else f"📅 EDIÇÃO: {data_str}"
    linhas = [
        f"📢 *MONITORAMENTO — DIÁRIO OFICIAL DE MOSSORÓ*\n",
        f"👥 *{NOME_SALA}*\n",
        edicao_str,
        f"🔍 {len(ocorrencias)} ocorrência(s) encontrada(s)\n",
    ]

    for i, ocorrencia in enumerate(ocorrencias, start=1):
        nome = ocorrencia["nome"]
        portaria = ocorrencia["portaria"]
        titulo = portaria["titulo"]

        # Corpo = conteúdo completo sem a primeira linha (título já exibido em *Ato:*)
        linhas_conteudo = portaria["conteudo"].split("\n")
        corpo = "\n".join(linhas_conteudo[1:]).strip()

        linhas += [
            f"━━━━━━━━━━━━━━━━━━",
            f"*{i}. Nome:* {nome}",
            f"*Ato:* {titulo}",
            f"\n{corpo}",
            "",
        ]

    return "\n".join(l for l in linhas if l is not None)


def buscar_url_pdf(url_publicacao: str) -> str | None:
    """
    Acessa a página HTML da publicação e extrai o link direto para o PDF oficial.
    O link segue o padrão /pmm/uploads/publicacao/pdf/{id}/{nome}.pdf
    """
    headers = {"User-Agent": "Mozilla/5.0 (compatible; DOM-Monitor/1.0)"}
    try:
        resp = requests.get(url_publicacao, headers=headers, timeout=30)
        resp.raise_for_status()
    except requests.RequestException as e:
        log.error(f"Erro ao buscar página para localizar PDF: {e}")
        return None

    soup = BeautifulSoup(resp.text, "html.parser")
    link = soup.find("a", href=re.compile(r"/pmm/uploads/publicacao/pdf/"))
    if not link:
        log.warning("Link do PDF não encontrado na página da publicação.")
        return None

    href = link.get("href", "")
    url_pdf = (BASE_URL + href) if href.startswith("/") else href
    log.info(f"URL do PDF encontrada: {url_pdf}")
    return url_pdf


def _sanitizar_nome_arquivo(nome: str) -> str:
    """Remove caracteres inválidos para nomes de arquivo no Windows/Linux."""
    return re.sub(r'[\\/:*?"<>|]', '-', nome).strip(" .")


def extrair_pdfs_por_ocorrencia(url_pdf: str, ocorrencias: list[dict]) -> list[str]:
    """
    Baixa o PDF da publicação e gera um arquivo PDF separado para cada
    ocorrência encontrada, contendo apenas as páginas da portaria associada.

    Nome do arquivo: "{titulo_portaria} - {nome_pessoa}.pdf"
    Exemplo: "PORTARIA Nº 262, DE 08 DE MAIO DE 2026 - MARINA COSTA.pdf"

    Retorna lista de caminhos dos PDFs gerados (vazia se falhar).
    """
    try:
        from pypdf import PdfReader, PdfWriter
    except ImportError:
        log.error("Biblioteca 'pypdf' não instalada. Execute: pip install pypdf")
        return []

    def _normalizar(texto: str) -> str:
        sem_acento = unicodedata.normalize("NFKD", texto)
        sem_acento = "".join(c for c in sem_acento if not unicodedata.combining(c))
        return sem_acento.upper()

    log.info(f"Baixando PDF: {url_pdf}")
    headers = {"User-Agent": "Mozilla/5.0 (compatible; DOM-Monitor/1.0)"}
    try:
        resp = requests.get(url_pdf, headers=headers, timeout=120)
        resp.raise_for_status()
    except requests.RequestException as e:
        log.error(f"Erro ao baixar PDF: {e}")
        return []

    reader = PdfReader(io.BytesIO(resp.content))
    pasta = PDF_TEMP_DIR  # PDFs temporários salvos em subpasta dedicada
    os.makedirs(pasta, exist_ok=True)
    caminhos_gerados = []

    # Monta texto combinado de todas as páginas para localizar spans de portarias.
    # Cada página ocupa o intervalo [page_offsets[i], page_offsets[i+1]) na string.
    # Assim podemos mapear qualquer posição de caractere → número da página.
    page_texts_norm: list[str] = [
        _normalizar(p.extract_text() or "") for p in reader.pages
    ]
    page_offsets: list[int] = []
    _pos = 0
    for _t in page_texts_norm:
        page_offsets.append(_pos)
        _pos += len(_t) + 1          # +1 pelo "\n" separador
    page_offsets.append(_pos)        # sentinela: posição após o último char
    combined = "\n".join(page_texts_norm)

    # Detecta posições de todos os CABEÇALHOS formais de portaria no texto do PDF
    # (não apenas os monitorados) para usar como fronteiras precisas.
    # Cabeçalhos formais têm vírgula após o número: "PORTARIA Nº 37,"
    # Referências de corpo NÃO têm: "...nomeado através da Portaria nº 33 de..."
    # Após _normalizar, "Nº" → "NO"; aceitamos variantes Oº° por segurança.
    _portaria_title_re = re.compile(r'PORTARIA\s+N[Oº°]\s+\d+\s*,')
    all_portaria_positions: list[int] = [
        m.start() for m in _portaria_title_re.finditer(combined)
    ]

    # Agrupa ocorrências por portaria para evitar PDFs duplicados quando
    # múltiplos nomes monitorados aparecem na mesma portaria.
    # Mantém ordem de inserção (Python 3.7+) para preservar sequência original.
    portaria_nomes: dict[str, list[str]] = {}
    portaria_obj:   dict[str, dict]      = {}
    for oc in ocorrencias:
        titulo = oc["portaria"]["titulo"]
        if titulo not in portaria_nomes:
            portaria_nomes[titulo] = []
            portaria_obj[titulo]   = oc["portaria"]
        if oc["nome"] not in portaria_nomes[titulo]:
            portaria_nomes[titulo].append(oc["nome"])

    for titulo, nomes in portaria_nomes.items():
        portaria    = portaria_obj[titulo]
        titulo_norm = _normalizar(titulo)

        writer = PdfWriter()
        paginas_incluidas: list[int] = []

        # Localiza o início do texto desta portaria no combined.
        start_pos = combined.find(titulo_norm)
        if start_pos == -1:
            log.warning(f"Título '{titulo}' não localizado no PDF — ocorrência pulada.")
            continue

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

        if not paginas_incluidas:
            log.warning(f"Nenhuma página encontrada para '{titulo}' — ocorrência pulada.")
            continue

        paginas_incluidas = sorted(set(paginas_incluidas))
        nomes_log = ", ".join(nomes)
        log.info(f"Páginas {paginas_incluidas} extraídas para [{nomes_log}].")

        # Quando o título termina em vírgula e a ementa é a continuação da data
        # ("DE 08 DE MAIO DE 2026"), o DOM separou em duas linhas — junta para o nome.
        ementa = portaria.get("ementa", "")
        if titulo.rstrip().endswith(",") and re.match(r"DE\s+\d", ementa.strip(), re.IGNORECASE):
            titulo_arquivo = f"{titulo.rstrip()} {ementa.strip()}"
        else:
            titulo_arquivo = titulo

        # Nome do arquivo inclui todos os nomes encontrados na portaria
        nomes_arquivo = " + ".join(nomes)
        nome_arquivo = _sanitizar_nome_arquivo(f"{titulo_arquivo} - {nomes_arquivo}") + ".pdf"
        caminho_saida = os.path.join(pasta, nome_arquivo)
        with open(caminho_saida, "wb") as f:
            writer.write(f)

        log.info(f"PDF gerado: {caminho_saida}")
        caminhos_gerados.append(caminho_saida)

    return caminhos_gerados


def _enviar_arquivos_no_grupo(driver, caminhos_pdf: list) -> None:
    """
    Envia um ou mais arquivos PDF para o grupo já aberto no WhatsApp Web,
    em uma única operação de anexo (clip → Documentos → send_keys com todos
    os caminhos separados por '\\n' → botão Enviar).

    Deve ser chamado após o grupo estar visível na janela do driver.
    """
    caminhos_abs = [os.path.abspath(p) for p in caminhos_pdf if os.path.isfile(p)]
    ignorados = [p for p in caminhos_pdf if not os.path.isfile(p)]
    for p in ignorados:
        log.warning(f"Arquivo PDF não encontrado (ignorado): {p}")
    if not caminhos_abs:
        log.warning("Nenhum arquivo PDF válido para enviar.")
        return
    log.info(f"Enviando {len(caminhos_abs)} PDF(s) de uma vez: {[os.path.basename(p) for p in caminhos_abs]}")

    # Localiza o botão de anexar (ícone de clipe)
    xpaths_clipe = [
        '//span[@data-testid="clip"]',
        '//div[@title="Attach"]',
        '//div[@title="Anexar"]',
        '//button[contains(@aria-label,"Attach")]',
        '//button[contains(@aria-label,"nexar")]',
        '//div[contains(@aria-label,"nexar")]',
    ]
    btn_clipe = None
    for xpath in xpaths_clipe:
        try:
            btn_clipe = WebDriverWait(driver, 5).until(
                EC.element_to_be_clickable((By.XPATH, xpath))
            )
            log.info(f"Botão de anexar encontrado: {xpath}")
            break
        except Exception:
            pass

    if btn_clipe is None:
        raise Exception("Botão de anexar (clipe) não encontrado.")

    # Clica em "Documentos" no submenu de anexos com retry.
    # O WhatsApp Web pode demorar para renderizar o submenu; se não encontrar,
    # fecha com Escape, aguarda e tenta novamente.
    xpaths_documentos = [
        '//span[contains(text(),"Documento")]',
        '//span[contains(text(),"Document")]',
        '//div[contains(@aria-label,"ocumento")]',
        '//li[.//span[contains(text(),"ocumento")]]',
        '//label[.//input[@type="file"][not(contains(@accept,"image"))]]',
    ]
    clicou_documentos = False
    _MAX_TENTATIVAS_DOCS = 3
    for tentativa in range(1, _MAX_TENTATIVAS_DOCS + 1):
        btn_clipe.click()
        time.sleep(2)  # Aguarda o submenu renderizar
        for xpath in xpaths_documentos:
            try:
                btn_docs = WebDriverWait(driver, 4).until(
                    EC.element_to_be_clickable((By.XPATH, xpath))
                )
                btn_docs.click()
                log.info(f"Opção 'Documentos' clicada (tentativa {tentativa}): {xpath}")
                time.sleep(1)
                clicou_documentos = True
                break
            except Exception:
                pass
        if clicou_documentos:
            break
        # Fecha o submenu antes de tentar novamente
        log.warning(f"Opção 'Documentos' não encontrada (tentativa {tentativa}/{_MAX_TENTATIVAS_DOCS}) — fechando submenu e tentando novamente.")
        try:
            driver.find_element(By.TAG_NAME, "body").send_keys(Keys.ESCAPE)
        except Exception:
            pass
        time.sleep(2)

    if not clicou_documentos:
        log.warning(
            "Opção 'Documentos' não encontrada após todas as tentativas — "
            "tentando enviar diretamente ao input de arquivo (pode rejeitar PDF)."
        )

    # Localiza o input[type="file"] para documentos.
    # Após clicar em "Documentos", o input correto fica acessível no DOM.
    input_arquivo = None
    try:
        inputs = driver.find_elements(By.CSS_SELECTOR, 'input[type="file"]')
        log.info(f"Input(s) de arquivo encontrado(s): {len(inputs)} disponível/eis.")
        for inp in inputs:
            accept = (inp.get_attribute("accept") or "").lower()
            log.debug(f"  input accept='{accept}'")
            if "image" not in accept:
                input_arquivo = inp
                log.info(f"Input para documentos selecionado (accept='{accept}').")
                break
        if input_arquivo is None:
            raise Exception(
                "Nenhum input de arquivo sem 'image' no accept foi encontrado. "
                "A opção 'Documentos' pode não ter sido clicada corretamente."
            )
    except Exception as e:
        log.error(f"Erro ao localizar input de arquivo: {e}")
        raise

    if input_arquivo is None:
        raise Exception("Input de arquivo não encontrado após abrir menu de anexos.")

    # Garante que o input esteja interagível e envia todos os caminhos de uma vez.
    # O ChromeDriver aceita múltiplos caminhos separados por '\n' em input[type="file"]
    # quando multiple está presente (ou mesmo sem ele, dependendo da versão).
    # IMPORTANTE: nunca use send_keys(Keys.ENTER) em input[type="file"] — o ChromeDriver
    # interpreta qualquer string enviada como caminho de arquivo e lança "File not found".
    driver.execute_script(
        "arguments[0].style.display='block';"
        "arguments[0].style.visibility='visible';"
        "arguments[0].removeAttribute('hidden');",
        input_arquivo,
    )
    input_arquivo.send_keys("\n".join(caminhos_abs))
    log.info(f"{len(caminhos_abs)} caminho(s) enviado(s) ao input.")
    espera_preview = 8 + max(0, (len(caminhos_abs) - 1) * 2)  # +2s por arquivo extra
    log.info(f"Aguardando pré-visualização ({espera_preview}s)...")
    time.sleep(espera_preview)

    # Clica no botão de enviar da pré-visualização do anexo.
    # Seletor confirmado via inspeção do DOM real do WhatsApp Web (2025):
    #   div[role="button"] com aria-label contendo "Send" ou "Enviar"
    #   e ícone interno span[data-testid="wds-ic-send-filled"]
    xpaths_enviar = [
        # Versão atual confirmada (2025): ícone wds-ic-send-filled dentro de div[role="button"]
        '//div[@role="button"][.//span[@data-testid="wds-ic-send-filled"]]',
        # Por aria-label (varia conforme qtd de arquivos: "Send 1 selected", "Enviar 1 selecionado")
        '//div[@role="button"][contains(@aria-label,"Send")]',
        '//div[@role="button"][contains(@aria-label,"Enviar")]',
        # Fallbacks para versões anteriores
        '//div[@role="button"][.//span[@data-icon="send"]]',
        '//button[.//span[@data-testid="wds-ic-send-filled"]]',
        '//div[@data-testid="compose-btn-send"]',
        '//button[@aria-label="Enviar"]',
        '//button[@aria-label="Send"]',
    ]
    for xpath in xpaths_enviar:
        try:
            btn_enviar = WebDriverWait(driver, 10).until(
                EC.element_to_be_clickable((By.XPATH, xpath))
            )
            btn_enviar.click()
            log.info(f"{len(caminhos_abs)} PDF(s) enviado(s) com sucesso! (via {xpath})")
            time.sleep(3)
            return
        except Exception:
            pass

    # Fallback JavaScript: busca pelo ícone wds-ic-send-filled e sobe até o div[role="button"]
    try:
        enviado = driver.execute_script("""
            var seletores = [
                '[data-testid="wds-ic-send-filled"]',
                '[data-icon="wds-ic-send-filled"]',
                '[data-icon="send"]',
                '[data-testid="compose-btn-send"]'
            ];
            for (var sel of seletores) {
                var elems = document.querySelectorAll(sel);
                for (var el of elems) {
                    if (el.offsetParent === null) continue;
                    var alvo = el;
                    for (var i = 0; i < 8; i++) {
                        if (!alvo.parentElement) break;
                        alvo = alvo.parentElement;
                        if (alvo.getAttribute('role') === 'button' || alvo.tagName === 'BUTTON') break;
                    }
                    alvo.click();
                    return sel;
                }
            }
            return null;
        """)
        if enviado:
            log.info(f"{len(caminhos_abs)} PDF(s) enviado(s) com sucesso via JavaScript fallback (seletor: {enviado}).")
            time.sleep(3)
            return
    except Exception as e:
        log.warning(f"Fallback JavaScript falhou: {e}")

    # Diagnóstico: despeja HTML do footer da pré-visualização no log para
    # identificar os seletores corretos na versão atual do WhatsApp Web.
    try:
        html_preview = driver.execute_script("""
            var footer = document.querySelector(
                '[data-testid="media-caption-input-container"], ' +
                '.x1n2onr6[class*="footer"], ' +
                'footer'
            );
            return footer ? footer.outerHTML.substring(0, 3000) : document.body.innerHTML.substring(0, 3000);
        """)
        log.debug(f"HTML da área de pré-visualização:\n{html_preview}")
    except Exception:
        pass

    raise Exception(
        f"Botão de enviar não encontrado após upload de {len(caminhos_abs)} PDF(s). "
        "Verifique os logs (nível DEBUG) para ver o HTML da pré-visualização "
        "e identificar o seletor correto."
    )


def enviar_whatsapp(
    mensagem: str,
    grupo: str,
    caminhos_pdf: list[str] = None,
    mensagem_apos_pdf: str = "",
) -> bool:
    """
    Envia a mensagem para o grupo do WhatsApp via Selenium + WhatsApp Web.

    Fluxo de envio (dentro de uma única sessão do Chrome):
      1. Mensagem de texto principal
      2. Todos os PDFs de uma vez (única operação de anexo)
      3. mensagem_apos_pdf, se não vazia (ex.: Fofoca da Secretaria)

    Inicia o Chrome localmente via ChromeDriver.
    O perfil Chrome (sessão WhatsApp) é salvo em WHATSAPP_PROFILE_DIR.
    """
    log.info(f"Enviando mensagem para o grupo WhatsApp: '{grupo}'")

    # ── Detecção de sessão e timeout de autenticação ─────────────────────────
    sessao_valida = os.path.isdir(
        os.path.join(
            WHATSAPP_PROFILE_DIR,
            "Default", "IndexedDB",
            "https_web.whatsapp.com_0.indexeddb.leveldb",
        )
    )
    timeout_auth = 30 if sessao_valida else TIMEOUT_QR_CODE
    if not sessao_valida:
        log.info(
            "Sessão do WhatsApp não encontrada — Chrome abrirá para autenticação.\n"
            f"Escaneie o QR code no WhatsApp do celular. "
            f"Você tem {TIMEOUT_QR_CODE} segundos."
        )

    # ── Opções do Chrome ─────────────────────────────────────────────────────
    options = webdriver.ChromeOptions()
    options.add_argument(f"--user-data-dir={WHATSAPP_PROFILE_DIR}")
    options.add_argument("--profile-directory=Default")
    options.add_argument("--remote-allow-origins=*")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")

    driver = None
    try:
        if ChromeDriverManager is None:
            raise ImportError(
                "webdriver-manager não instalado. "
                "Execute: pip install webdriver-manager"
            )
        service = Service(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=options)

        wait = WebDriverWait(driver, timeout_auth)
        wait_curto = WebDriverWait(driver, 30)

        driver.get("https://web.whatsapp.com")
        time.sleep(3)
        log.info("Aguardando interface do WhatsApp Web...")

        # Detecta se o QR code está visível e avisa o usuário no log
        try:
            WebDriverWait(driver, 5).until(
                EC.presence_of_element_located((By.XPATH, '//*[@data-ref]'))
            )
            log.info(
                "=" * 50 + "\n"
                "QR CODE VISÍVEL — ESCANEIE AGORA com o WhatsApp\n"
                f"Aguardando até {timeout_auth} segundos...\n"
                + "=" * 50
            )
        except Exception:
            log.info("Sessão ativa detectada — sem necessidade de QR code.")

        # Detecta e dispensa o diálogo "WhatsApp aberto em outra janela"
        # (aparece quando o mesmo número já está ativo em outra aba/perfil)
        try:
            btn_usar = WebDriverWait(driver, 8).until(
                EC.element_to_be_clickable(
                    (By.XPATH, '//button[contains(normalize-space(),"Usar nesta janela")]')
                )
            )
            log.info("Diálogo 'aberto em outra janela' detectado — clicando em 'Usar nesta janela'.")
            btn_usar.click()
            time.sleep(3)
        except Exception:
            log.info("Sem diálogo de conflito de sessão.")

        # Aguarda a caixa de pesquisa estar disponível
        # NOTA: no WhatsApp Web atual a caixa é <input data-tab="3">, não div[contenteditable]
        xpaths_pesquisa = [
            '//input[@data-tab="3"]',                                     # versão atual (INPUT)
            '//input[contains(@aria-label,"esquisar")]',                  # por aria-label PT
            '//input[contains(@aria-label,"Search")]',                    # por aria-label EN
            '//input[@role="textbox"]',                                   # por role
            '//div[@contenteditable="true"][@data-tab="3"]',              # versão legada (DIV)
            '//div[@contenteditable="true"][contains(@aria-label,"esquisar")]',
            '//div[@role="searchbox"]',
            '//div[@id="side"]//div[@contenteditable="true"]',
        ]
        caixa_pesquisa = None
        for i, xpath in enumerate(xpaths_pesquisa):
            timeout = timeout_auth if i == 0 else 5
            try:
                log.info(f"[{i+1}/{len(xpaths_pesquisa)}] Buscando caixa de pesquisa: {xpath}")
                caixa_pesquisa = WebDriverWait(driver, timeout).until(
                    EC.element_to_be_clickable((By.XPATH, xpath))
                )
                log.info(f"Caixa de pesquisa encontrada via XPath #{i+1}.")
                break
            except Exception:
                log.warning(f"XPath não encontrou elemento: {xpath}")

        if caixa_pesquisa is None:
            raise Exception(
                "Nenhum XPath funcionou para a caixa de pesquisa. "
                "O WhatsApp Web pode ter atualizado sua interface."
            )

        log.info("WhatsApp Web autenticado e pronto.")

        # Pesquisa o grupo pelo nome (via clipboard — evita erro de emoji no send_keys)
        log.info(f"Pesquisando grupo: '{grupo}'")
        _colar_no_elemento(driver, caixa_pesquisa, grupo)
        time.sleep(2)

        # Clica no resultado que corresponde exatamente ao nome do grupo
        log.info("Aguardando resultado da pesquisa...")
        resultado = wait_curto.until(
            EC.element_to_be_clickable(
                (By.XPATH, f'//span[@title="{grupo}"]')
            )
        )
        resultado.click()
        log.info(f"Grupo '{grupo}' selecionado.")
        time.sleep(1)

        # Tenta encontrar a caixa de mensagem com múltiplos XPaths
        xpaths_mensagem = [
            '//div[@contenteditable="true"][@data-tab="10"]',
            '//div[@role="textbox"][@data-tab="10"]',
            '//div[@data-lexical-editor="true"][@data-tab="10"]',
            '//div[@contenteditable="true"][contains(@aria-label,"ensagem")]',
        ]
        caixa_msg = None
        for i, xpath in enumerate(xpaths_mensagem):
            try:
                log.info(f"[{i+1}/{len(xpaths_mensagem)}] Buscando caixa de mensagem: {xpath}")
                caixa_msg = WebDriverWait(driver, 15 if i == 0 else 3).until(
                    EC.element_to_be_clickable((By.XPATH, xpath))
                )
                log.info("Caixa de mensagem encontrada.")
                break
            except Exception:
                log.warning(f"XPath não encontrou elemento: {xpath}")

        if caixa_msg is None:
            raise Exception(
                "Nenhum XPath funcionou para a caixa de mensagem. "
                "O WhatsApp Web pode ter atualizado sua interface."
            )

        # Cola a mensagem via clipboard (evita erro de emoji no send_keys)
        # O WhatsApp Web preserva as quebras de linha ao colar texto
        _colar_no_elemento(driver, caixa_msg, mensagem)
        time.sleep(0.5)
        caixa_msg.send_keys(Keys.ENTER)
        log.info("Mensagem de texto enviada com sucesso!")
        time.sleep(2)

        # Envia todos os PDFs de uma vez (uma única operação de anexo)
        if caminhos_pdf:
            _enviar_arquivos_no_grupo(driver, caminhos_pdf)
            time.sleep(2)

        # Envia mensagem de fofoca após todos os PDFs (mesma sessão Chrome)
        if mensagem_apos_pdf:
            log.info("Enviando mensagem pós-PDF (Fofoca da Secretaria)...")
            xpaths_msg_pos = [
                '//div[@contenteditable="true"][@data-tab="10"]',
                '//div[@role="textbox"][@data-tab="10"]',
                '//div[@contenteditable="true"][contains(@aria-label,"ensagem")]',
            ]
            caixa_pos = None
            for xpath in xpaths_msg_pos:
                try:
                    caixa_pos = WebDriverWait(driver, 5).until(
                        EC.element_to_be_clickable((By.XPATH, xpath))
                    )
                    break
                except Exception:
                    pass
            if caixa_pos:
                _colar_no_elemento(driver, caixa_pos, mensagem_apos_pdf.strip())
                time.sleep(0.5)
                caixa_pos.send_keys(Keys.ENTER)
                log.info("Mensagem pós-PDF enviada com sucesso!")
                time.sleep(2)
            else:
                log.warning("Caixa de mensagem não encontrada para envio pós-PDF.")

        return True

    except Exception as e:
        log.error(f"Erro ao enviar mensagem no WhatsApp: {e}")
        return False

    finally:
        if driver:
            driver.quit()


# ─────────────────────────────────────────────
# EXECUÇÃO PRINCIPAL
# ─────────────────────────────────────────────

def main():
    log.info("=" * 60)
    log.info("Iniciando monitoramento do Diário Oficial de Mossoró")
    log.info("=" * 60)

    # 1. Busca a publicação mais recente (primeiro card do site)
    publicacao = buscar_ultima_publicacao()

    if not publicacao:
        log.warning("Não foi possível obter a última edição do DOM. Encerrando.")
        return

    # 2. Verifica se a edição já foi monitorada (evita reprocessar a mesma edição)
    numero_atual = publicacao.get("numero")
    ultimo_salvo = int(os.environ.get("ULTIMO_DOM_NUMERO", "0"))
    if numero_atual is not None and numero_atual <= ultimo_salvo:
        log.info(
            f"Edição Nº {numero_atual} já foi monitorada "
            f"(último número salvo: {ultimo_salvo}). Encerrando."
        )
        return

    # 2a. Persiste o número da edição atual no .env para evitar reprocessamento futuro
    if numero_atual is not None:
        _atualizar_env("ULTIMO_DOM_NUMERO", str(numero_atual))

    # 3. Extrai os atos (portarias, decretos, etc.) da publicação
    portarias = extrair_portarias(publicacao["url_html"])

    if not portarias:
        log.warning("Nenhum ato extraído da publicação. Verifique a estrutura do site.")
        return

    # 4. Busca os nomes monitorados nos atos extraídos
    ocorrencias = buscar_nomes_em_portarias(portarias, NOMES_MONITORADOS)

    # 4a. Detecta movimentações de pessoal nas secretarias (Fofoca da Secretaria)
    fofocas = detectar_fofocas(portarias, SECRETARIAS_MOSSORO)

    # 4a1. Consolida pares exoneração+nomeação da mesma pessoa em promovido/remanejado
    fofocas = promovido_remanejado(fofocas)

    # 4b. Formata a seção de fofocas (sempre exibe o bloco, mesmo sem movimentações)
    secao_fofoca = formatar_fofocas(fofocas)
    log.info(f"{len(fofocas)} fofoca(s) incluída(s) na mensagem.")

    if not ocorrencias:
        log.info("Nenhum nome monitorado encontrado — enviando aviso ao WhatsApp.")
        edicao_vazia = (
            f"📅 Edição Nº {numero_atual}: {publicacao['data']}"
            if numero_atual else f"📅 Edição: {publicacao['data']}"
        )
        mensagem_vazia = (
            f"📢 *MONITORAMENTO — DIÁRIO OFICIAL DE MOSSORÓ*\n"
            f"👥 *{NOME_SALA}*\n"
            f"{edicao_vazia}\n\n"
            f"❌ Nenhuma ocorrência encontrada para os nomes monitorados nesta edição."
        )
        # Fofoca enviada como segunda mensagem, mesmo sem PDFs
        enviar_whatsapp(mensagem_vazia, WHATSAPP_GRUPO, mensagem_apos_pdf=secao_fofoca)
        return

    log.info(f"{len(ocorrencias)} ocorrência(s) encontrada(s). Preparando envio...")

    # 5. Formata a mensagem de texto principal (sem fofoca — enviada separadamente)
    mensagem = formatar_mensagem(ocorrencias, publicacao["data"], numero_atual)

    # 6. Baixa o PDF e gera um arquivo separado por ocorrência
    url_pdf = buscar_url_pdf(publicacao["url_html"])
    caminhos_pdf = []
    if url_pdf:
        caminhos_pdf = extrair_pdfs_por_ocorrencia(url_pdf, ocorrencias)
        if not caminhos_pdf:
            log.warning("Nenhum PDF gerado — apenas a mensagem de texto será enviada.")
    else:
        log.warning("PDF não encontrado — apenas a mensagem de texto será enviada.")

    # 7. Envia: (1) mensagem principal, (2) PDFs, (3) fofoca — tudo na mesma sessão
    sucesso = enviar_whatsapp(mensagem, WHATSAPP_GRUPO, caminhos_pdf, mensagem_apos_pdf=secao_fofoca)

    # 8. Remove os PDFs temporários após envio
    for caminho in caminhos_pdf:
        if os.path.isfile(caminho):
            os.remove(caminho)
            log.info(f"PDF temporário removido: {os.path.basename(caminho)}")

    if sucesso:
        log.info("Processo concluído com sucesso!")
    else:
        log.error("Falha no envio da mensagem. Verifique os logs.")


def _agendar_execucao(horario: str) -> None:
    """
    Executa main() todos os dias no horário especificado (loop infinito).

    O fuso horário utilizado é o local do sistema.

    Args:
        horario: Horário de execução no formato "HH:MM" (ex: "07:30").
    """
    try:
        hora, minuto = map(int, horario.split(":"))
    except ValueError:
        log.error(f"Formato de horário inválido: '{horario}' — use HH:MM (ex: 07:30)")
        sys.exit(1)

    log.info(f"Modo agendado ativo — execução diária às {horario}.")

    # Executa imediatamente se o horário configurado já passou hoje,
    # evitando esperar quase 24 h na primeira execução do dia.
    agora = datetime.now()
    horario_hoje = agora.replace(hour=hora, minute=minuto, second=0, microsecond=0)
    if agora >= horario_hoje:
        log.info("Horário de hoje já passou — executando imediatamente.")
        main()

    while True:
        agora = datetime.now()
        proximo = agora.replace(hour=hora, minute=minuto, second=0, microsecond=0)
        if proximo <= agora:
            proximo += timedelta(days=1)

        delta_s = (proximo - agora).total_seconds()
        horas   = int(delta_s // 3600)
        minutos = int((delta_s % 3600) // 60)
        log.info(
            f"Próxima execução: {proximo.strftime('%d/%m/%Y %H:%M')} "
            f"(em {horas}h {minutos}min)"
        )
        time.sleep(delta_s)
        main()


if __name__ == "__main__":
    # ── Modo agendado (execução contínua) ────────────────────────────────────
    # Acionado APENAS por: python monitor_diario_oficial.py --agendar
    # HORARIO_EXECUCAO define o horário, mas NÃO ativa o modo sozinho.
    # Agendamento externo (Claude Routines, Task Scheduler, cron):
    #   → execute sem --agendar; o script roda uma vez e encerra.
    if "--agendar" in sys.argv:
        horario = os.environ.get("HORARIO_EXECUCAO", "05:00").strip()
        _agendar_execucao(horario)
    else:
        # ── Execução pontual (padrão) ────────────────────────────────────────
        # Roda uma única vez e encerra — modo correto para agendamento externo.
        main()