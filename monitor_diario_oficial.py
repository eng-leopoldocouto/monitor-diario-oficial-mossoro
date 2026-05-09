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

# webdriver_manager só é necessário no modo local (não-Docker).
# A importação é opcional para não exigir a dependência dentro do container.
try:
    from webdriver_manager.chrome import ChromeDriverManager
except ImportError:
    ChromeDriverManager = None  # type: ignore

# ─────────────────────────────────────────────
# CONFIGURAÇÕES DO USUÁRIO
# ─────────────────────────────────────────────
# Cada valor pode ser sobrescrito por variável de ambiente, permitindo uso
# sem editar código — ideal para Docker / Docker Compose (.env file).
#
# Variáveis de ambiente reconhecidas:
#   NOMES_MONITORADOS   — nomes separados por vírgula (MAIÚSCULAS)
#   WHATSAPP_GRUPO      — nome exato do grupo no WhatsApp
#   TIMEOUT_QR_CODE     — segundos para escanear o QR code (padrão: 120)
#   SELENIUM_URL        — URL do WebDriver remoto (ex.: http://selenium:4444/wd/hub)
#                         Se vazio, usa ChromeDriver local (modo Windows/instalação direta)
#   WHATSAPP_PROFILE_DIR— caminho do perfil Chrome para sessão WhatsApp
#   LOG_DIR             — pasta de logs (padrão: mesma pasta do script)
#   HORARIO_EXECUCAO    — horário de execução diária HH:MM (ex.: 07:30)
#                         Necessário apenas quando iniciado com --agendar
# ─────────────────────────────────────────────

def _ler_lista_env(chave: str, padrao: list[str]) -> list[str]:
    """Lê lista separada por vírgula de variável de ambiente; usa padrão se vazia."""
    valor = os.environ.get(chave, "").strip()
    if valor:
        return [item.strip().upper() for item in valor.split(",") if item.strip()]
    return padrao


# Nomes monitorados pela Sala Saúde | Educação PMM
# (edite abaixo ou defina NOMES_MONITORADOS no .env)
_NOMES_SALA_SAUDE_EDUCACAO = [
    "JOSÉ LEOPOLDO DANTAS COUTO",
    "JOSE LEOPOLDO DANTAS COUTO",
    "CARLA VANNESSA DA ROCHA",
    "MARIA LUCINEIDE VIDAL RODRIGUES",
    "DEIVISON TAEMY DIAS DA SILVA",
    "ALAERDSON NASCIMENTO DE LIMA",
    "LUCAS PAULO RIBEIRO DE OLIVEIRA",  # TODO: remover após validação

]
NOMES_MONITORADOS: list[str] = _ler_lista_env("NOMES_MONITORADOS", _NOMES_SALA_SAUDE_EDUCACAO)

# Secretarias municipais de Mossoró monitoradas para "Fofoca da Secretaria"
# Pode ser sobrescrita via variável de ambiente SECRETARIAS_MOSSORO (separadas por vírgula)
_SECRETARIAS_PADRAO = [
    "SECRETARIA MUNICIPAL DE INFRAESTRUTURA",
    "SECRETARIA MUNICIPAL DE SAÚDE",
    "SECRETARIA MUNICIPAL DE EDUCAÇÃO",
    "SECRETARIA MUNICIPAL DE FINANÇAS",
    "SECRETARIA MUNICIPAL DE ADMINISTRAÇÃO",
    "SECRETARIA MUNICIPAL DE ASSISTÊNCIA SOCIAL",
    "SECRETARIA MUNICIPAL DE PLANEJAMENTO",
    "SECRETARIA MUNICIPAL DE MEIO AMBIENTE",
    "SECRETARIA MUNICIPAL DE AGRICULTURA",
    "SECRETARIA MUNICIPAL DE HABITAÇÃO",
    "SECRETARIA MUNICIPAL DE TURISMO",
    "SECRETARIA MUNICIPAL DE CULTURA",
    "SECRETARIA MUNICIPAL DE ESPORTES",
    "SECRETARIA MUNICIPAL DE SEGURANÇA",
    "SECRETARIA MUNICIPAL DE TRANSPORTES",
    "SECRETARIA MUNICIPAL DE COMUNICAÇÃO",
    "SECRETARIA MUNICIPAL DE DESENVOLVIMENTO ECONÔMICO",
    "SECRETARIA MUNICIPAL DE OBRAS",
    "SECRETARIA MUNICIPAL DE SERVIÇOS URBANOS",
    "SECRETARIA MUNICIPAL DE DEFESA CIVIL",
    "GABINETE DO PREFEITO",
    "PROCURADORIA GERAL DO MUNICÍPIO",
    "CONTROLADORIA GERAL DO MUNICÍPIO",
]
SECRETARIAS_MOSSORO: list[str] = _ler_lista_env("SECRETARIAS_MOSSORO", _SECRETARIAS_PADRAO)

# Nome exato do grupo do WhatsApp (TODO: edite aqui ou defina WHATSAPP_GRUPO no .env)
WHATSAPP_GRUPO: str = os.environ.get(
    "WHATSAPP_GRUPO", "Saúde | Educação PMM 💉🎓 - TESTES"
)

# Tempo máximo (segundos) para escanear o QR code na primeira execução
TIMEOUT_QR_CODE: int = int(os.environ.get("TIMEOUT_QR_CODE", "120"))

# URL base do Diário Oficial de Mossoró
BASE_URL = "https://dom.mossoro.rn.gov.br"

# ── Modo de operação ────────────────────────────────────────────────────────
# SELENIUM_URL vazio  → ChromeDriver local (Windows/Linux com Chrome instalado)
# SELENIUM_URL preench→ Selenium Grid remoto (Docker)
SELENIUM_URL: str = os.environ.get("SELENIUM_URL", "").strip()

# Perfil Chrome com sessão do WhatsApp.
# Modo local : pasta ".whatsapp_profile" ao lado do script
# Modo Docker: caminho dentro do container Selenium (configurável via env)
_profile_padrao = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".whatsapp_profile")
WHATSAPP_PROFILE_DIR: str = os.environ.get("WHATSAPP_PROFILE_DIR", _profile_padrao)

# Pasta de logs (padrão: mesma pasta do script; em Docker use /app/logs montado)
LOG_DIR: str = os.environ.get("LOG_DIR", os.path.dirname(os.path.abspath(__file__)))


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
    Funciona tanto com ChromeDriver local quanto com Selenium Grid remoto (Docker).

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
    # Funciona em Chrome local E em Selenium 4 Grid remoto (Docker).
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
    if platform.system() == "Windows" and not SELENIUM_URL:
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

    url_html = f"{BASE_URL}/dom/publicacao/{pub_id}"
    log.info(f"Última edição: ID {pub_id} — {data_str} — {url_html}")
    return {"id": pub_id, "data": data_str, "url_html": url_html}


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
        "━━━━━━━━━━━━━━━━━━",
        "🗣️ *FOFOCA DA SECRETARIA*",
    ]

    if not fofocas:
        linhas += [
            "_Silêncio💤 absoluto nos bastidores...\nNenhuma movimentação de pessoal detectada nesta edição._",
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
                    f"   Antes: _{c_ant}{cc_ant_str}_ na _{s_ant}_\n"
                    f"   Agora: _{c_nov}{cc_nov_str}_ na _{s_nov}_"
                )
            else:
                texto = (
                    f"🔄 *{pessoa}* foi *REMANEJADO(A)*.\n"
                    f"   Antes: _{c_ant}{cc_ant_str}_ na _{s_ant}_\n"
                    f"   Agora: _{c_nov}{cc_nov_str}_ na _{s_nov}_"
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


def formatar_mensagem(ocorrencias: list[dict], data_str: str, secao_fofoca: str = "") -> str:
    """
    Formata a mensagem de WhatsApp com as ocorrências encontradas.
    """
    linhas = [
        f"📢 *MONITORAMENTO — Diário Oficial de Mossoró*\n",
        f"👥 *Sala: SAÚDE | EDUCAÇÃO SEINFRA 💉🎓*\n",
        f"📅 Edição: {data_str}",
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

    mensagem_base = "\n".join(l for l in linhas if l is not None)
    if secao_fofoca:
        return mensagem_base + secao_fofoca
    return mensagem_base


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
    todos_titulos_norm = [
        _normalizar(oc["portaria"]["titulo"]) for oc in ocorrencias
    ]
    pasta = os.path.dirname(os.path.abspath(__file__))
    caminhos_gerados = []

    for oc in ocorrencias:
        titulo = oc["portaria"]["titulo"]
        nome   = oc["nome"]
        titulo_norm = _normalizar(titulo)

        writer = PdfWriter()
        paginas_incluidas: list[int] = []

        # Localiza a página inicial onde o título da portaria aparece
        pagina_inicio: int | None = None
        for num, page in enumerate(reader.pages):
            texto_pag = _normalizar(page.extract_text() or "")
            if titulo_norm in texto_pag:
                pagina_inicio = num
                break

        if pagina_inicio is not None:
            # A partir da página inicial, avança até encontrar outro título ou EOF
            outros_titulos = [t for t in todos_titulos_norm if t != titulo_norm]
            for num in range(pagina_inicio, len(reader.pages)):
                page = reader.pages[num]
                texto_pag = _normalizar(page.extract_text() or "")
                # Para quando uma página posterior contém outro título de portaria
                if num > pagina_inicio and any(t in texto_pag for t in outros_titulos):
                    break
                writer.add_page(page)
                paginas_incluidas.append(num + 1)

        if not paginas_incluidas:
            log.warning(f"Nenhuma página encontrada para '{titulo}' — ocorrência pulada.")
            continue

        paginas_incluidas = sorted(set(paginas_incluidas))
        log.info(f"Páginas {paginas_incluidas} extraídas para '{nome}'.")

        # Quando o título termina em vírgula e a ementa é a continuação da data
        # ("DE 08 DE MAIO DE 2026"), o DOM separou em duas linhas — junta para o nome.
        ementa = oc["portaria"].get("ementa", "")
        if titulo.rstrip().endswith(",") and re.match(r"DE\s+\d", ementa.strip(), re.IGNORECASE):
            titulo_arquivo = f"{titulo.rstrip()} {ementa.strip()}"
        else:
            titulo_arquivo = titulo
        nome_arquivo = _sanitizar_nome_arquivo(f"{titulo_arquivo} - {nome}") + ".pdf"
        caminho_saida = os.path.join(pasta, nome_arquivo)
        with open(caminho_saida, "wb") as f:
            writer.write(f)

        log.info(f"PDF gerado: {caminho_saida}")
        caminhos_gerados.append(caminho_saida)

    return caminhos_gerados


def _enviar_arquivo_no_grupo(driver, caminho_pdf: str) -> None:
    """
    Envia um arquivo PDF para o grupo já aberto no WhatsApp Web.
    Deve ser chamado após o grupo estar visível na janela do driver.
    """
    caminho_abs = os.path.abspath(caminho_pdf)
    log.info(f"Enviando arquivo: {caminho_abs}")

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

    # Garante que o input esteja interagível e envia o caminho absoluto do arquivo.
    # IMPORTANTE: nunca use send_keys(Keys.ENTER) em input[type="file"] — o ChromeDriver
    # interpreta qualquer string enviada como caminho de arquivo e lança "File not found".
    driver.execute_script(
        "arguments[0].style.display='block';"
        "arguments[0].style.visibility='visible';"
        "arguments[0].removeAttribute('hidden');",
        input_arquivo,
    )
    input_arquivo.send_keys(caminho_abs)
    log.info("Caminho do arquivo enviado ao input.")
    time.sleep(8)  # Aguarda pré-visualização do arquivo carregar

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
            log.info(f"PDF enviado com sucesso! (via {xpath})")
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
            log.info(f"PDF enviado com sucesso via JavaScript fallback (seletor: {enviado}).")
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
        "Botão de enviar não encontrado após upload do PDF. "
        "Verifique os logs (nível DEBUG) para ver o HTML da pré-visualização "
        "e identificar o seletor correto."
    )


def enviar_whatsapp(mensagem: str, grupo: str, caminhos_pdf: list[str] = None) -> bool:
    """
    Envia a mensagem para o grupo do WhatsApp via Selenium + WhatsApp Web.

    Suporta dois modos de operação:

    Modo local (SELENIUM_URL vazio — padrão Windows/instalação direta):
      • Inicia o Chrome localmente via ChromeDriver.
      • Verifica no filesystem se há sessão WhatsApp salva.
      • Perfil Chrome salvo em WHATSAPP_PROFILE_DIR (pasta local).

    Modo Docker (SELENIUM_URL definido — ex.: http://selenium:4444/wd/hub):
      • Conecta ao Selenium Grid remoto (container selenium/standalone-chrome).
      • A sessão WhatsApp é persistida no volume Docker montado no container Selenium.
      • O noVNC do container permite escanear o QR code via browser (porta 7900).
      • LocalFileDetector transfere automaticamente arquivos PDF para o container remoto.
    """
    log.info(f"Enviando mensagem para o grupo WhatsApp: '{grupo}'")
    modo_docker = bool(SELENIUM_URL)

    # ── Detecção de sessão e timeout de autenticação ─────────────────────────
    if modo_docker:
        # Em modo Docker, o perfil fica no container Selenium — não é possível
        # inspecionar o filesystem remotamente. Usa timeout completo e deixa
        # o Chrome decidir: se a sessão existe no volume, carrega em < 10 s.
        timeout_auth = TIMEOUT_QR_CODE
        log.info(
            f"Modo Docker: conectando ao Selenium em {SELENIUM_URL}\n"
            f"Para escanear o QR code (1ª execução), acesse: "
            f"http://localhost:7900  (senha: veja VNC_PASSWORD no .env)"
        )
    else:
        # Modo local: verifica IndexedDB do WhatsApp no filesystem
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
    # Flags necessárias em ambientes sem GPU (Docker/CI)
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")

    driver = None
    try:
        if modo_docker:
            # ── Modo Docker: RemoteWebDriver ─────────────────────────────────
            driver = webdriver.Remote(
                command_executor=SELENIUM_URL,
                options=options,
            )
            # LocalFileDetector faz o Selenium transferir automaticamente
            # arquivos locais (PDF) para o container remoto ao usar send_keys
            # em <input type="file"> — sem ele o ChromeDriver não encontraria o arquivo.
            from selenium.webdriver.remote.file_detector import LocalFileDetector
            driver.file_detector = LocalFileDetector()
        else:
            # ── Modo local: ChromeDriver gerenciado automaticamente ───────────
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

        # Envia cada PDF individualmente (um por ocorrência)
        if caminhos_pdf:
            for i, caminho in enumerate(caminhos_pdf, start=1):
                if os.path.isfile(caminho):
                    log.info(f"Enviando PDF {i}/{len(caminhos_pdf)}: {os.path.basename(caminho)}")
                    _enviar_arquivo_no_grupo(driver, caminho)
                    time.sleep(2)
                else:
                    log.warning(f"Arquivo PDF não encontrado: {caminho}")

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
        mensagem_vazia = (
            f"📢 *MONITORAMENTO — Diário Oficial de Mossoró*\n"
            f"👥 *Sala: SAÚDE | EDUCAÇÃO SEINFRA 💉🎓*\n"
            f"📅 Edição: {publicacao['data']}\n\n"
            f"❌ Nenhuma ocorrência encontrada para os nomes monitorados nesta edição."
        )
        if secao_fofoca:
            mensagem_vazia += secao_fofoca
        enviar_whatsapp(mensagem_vazia, WHATSAPP_GRUPO)
        return

    log.info(f"{len(ocorrencias)} ocorrência(s) encontrada(s). Preparando envio...")

    # 5. Formata a mensagem de texto (com fofocas integradas se houver)
    mensagem = formatar_mensagem(ocorrencias, publicacao["data"], secao_fofoca)

    # 6. Baixa o PDF e gera um arquivo separado por ocorrência
    url_pdf = buscar_url_pdf(publicacao["url_html"])
    caminhos_pdf = []
    if url_pdf:
        caminhos_pdf = extrair_pdfs_por_ocorrencia(url_pdf, ocorrencias)
        if not caminhos_pdf:
            log.warning("Nenhum PDF gerado — apenas a mensagem de texto será enviada.")
    else:
        log.warning("PDF não encontrado — apenas a mensagem de texto será enviada.")

    # 7. Envia mensagem de texto e PDFs (um por ocorrência) no WhatsApp
    sucesso = enviar_whatsapp(mensagem, WHATSAPP_GRUPO, caminhos_pdf)

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

    Utilizado pelo container Docker para substituir o cron do SO.
    O fuso horário respeitado é o da variável de ambiente TZ do container.

    Args:
        horario: Horário de execução no formato "HH:MM" (ex: "07:30").
    """
    try:
        hora, minuto = map(int, horario.split(":"))
    except ValueError:
        log.error(f"Formato de horário inválido: '{horario}' — use HH:MM (ex: 07:30)")
        sys.exit(1)

    log.info(
        f"Modo agendado ativo — execução diária às {horario} "
        f"(TZ={os.environ.get('TZ', 'local do sistema')})"
    )

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
    # ── Modo agendado (Docker / execução contínua) ───────────────────────────
    # Acionado por: python monitor_diario_oficial.py --agendar
    # Ou automaticamente quando HORARIO_EXECUCAO estiver definido no ambiente.
    horario_env = os.environ.get("HORARIO_EXECUCAO", "").strip()
    if "--agendar" in sys.argv or horario_env:
        horario = horario_env or "07:30"
        _agendar_execucao(horario)
    else:
        # ── Execução pontual (padrão local) ─────────────────────────────────
        # Roda uma única vez e encerra — útil para teste manual ou cron externo.
        main()