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

import os
import re
import time
import ctypes
import logging
import logging.handlers
from datetime import datetime, timedelta

import requests
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager

# ─────────────────────────────────────────────
# CONFIGURAÇÕES DO USUÁRIO — edite aqui
# ─────────────────────────────────────────────

# TODO: adicione os nomes que deseja monitorar (em MAIÚSCULAS para facilitar a busca)
NOMES_MONITORADOS = [
    "JOSÉ LEOPOLDO DANTAS COUTO",
    "JOSE LEOPOLDO DANTAS COUTO",
    "CARLA VANNESSA DA ROCHA",
    "MARIA LUCINEIDE VIDAL RODRIGUES",
    "DEIVISON TAEMY DIAS DA SILVA",
    "ALAERDSON NASCIMENTO DE LIMA",
    "GEORGIANY PAULA BESSA CAMPELO", #APAGAR DEPOIS
]

# TODO: coloque o nome exato do grupo do WhatsApp onde a mensagem será enviada
WHATSAPP_GRUPO = "Saúde | Educação PMM 💉🎓 - TESTES"

# Tempo máximo (em segundos) para escanear o QR code na primeira execução.
# Aumente este valor se precisar de mais tempo para abrir o celular e escanear.
TIMEOUT_QR_CODE = 120  # 5 minutos

# URL base do Diário Oficial de Mossoró
BASE_URL = "https://dom.mossoro.rn.gov.br"

# Perfil Chrome dedicado exclusivamente ao WhatsApp Web (separado do Chrome pessoal).
# Criado automaticamente na primeira execução. Não apague esta pasta após autenticar.
WHATSAPP_PROFILE_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), ".whatsapp_profile"
)


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
    log_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "monitor_dom.log")
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

def _colar_no_elemento(driver, elemento, texto: str) -> None:
    """
    Cola texto em um elemento do Selenium via clipboard do Windows.

    Evita o erro "ChromeDriver only supports characters in the BMP" que ocorre
    ao usar send_keys com emojis (código Unicode > U+FFFF, como 📂 🔔 📅).
    Funciona em qualquer elemento: <input>, <div contenteditable>, etc.
    """
    # Copia para o clipboard do Windows via ctypes (sem dependências externas).
    # No Windows 64-bit é obrigatório declarar restype/argtypes para funções que
    # retornam ou recebem handles/ponteiros — sem isso ctypes usa c_int (32 bits)
    # e trunca endereços de 64 bits, causando access violation ou OverflowError.
    CF_UNICODETEXT = 13
    GMEM_MOVEABLE = 0x0002
    encoded = texto.encode("utf-16-le") + b"\x00\x00"
    k32 = ctypes.windll.kernel32
    u32 = ctypes.windll.user32

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

    # O site exibe o conteúdo do diário em blocos de texto sequenciais
    # Identifica seções pelo cabeçalho de cada órgão/seção
    portarias = []
    conteudo_principal = soup.select_one("#main-content") or soup.body

    if not conteudo_principal:
        log.warning("Não foi possível identificar o conteúdo principal da página.")
        return []

    texto_completo = conteudo_principal.get_text("\n", strip=True)

    # Divide o texto em blocos de portaria usando "PORTARIA" como separador
    # Também captura outros atos: DECRETO, LEI, RESOLUÇÃO, ATO, TERMO
    padroes_ato = re.compile(
        r"((?:PORTARIA|DECRETO|LEI|RESOLUÇÃO|RESOLUCAO|ATO|TERMO|EXTRATO|AVISO|EDITAL)"
        r"[^\n]{0,200})",
        re.IGNORECASE,
    )

    linhas = texto_completo.split("\n")
    portaria_atual = None

    for linha in linhas:
        linha = linha.strip()
        if not linha:
            continue

        if padroes_ato.match(linha):
            if portaria_atual:
                portarias.append(portaria_atual)
            portaria_atual = {
                "titulo": linha,
                "ementa": "",
                "conteudo": linha,
            }
        elif portaria_atual:
            if not portaria_atual["ementa"]:
                portaria_atual["ementa"] = linha
            portaria_atual["conteudo"] += "\n" + linha

    if portaria_atual:
        portarias.append(portaria_atual)
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


def formatar_mensagem(ocorrencias: list[dict], data_str: str) -> str:
    """
    Formata a mensagem de WhatsApp com as ocorrências encontradas.
    """
    linhas = [
        f"🔔 *ALERTA — Diário Oficial de Mossoró*",
        f"📅 Edição: {data_str}",
        f"🔍 {len(ocorrencias)} ocorrência(s) encontrada(s)\n",
    ]

    for i, ocorrencia in enumerate(ocorrencias, start=1):
        nome = ocorrencia["nome"]
        portaria = ocorrencia["portaria"]
        titulo = portaria["titulo"]
        ementa = portaria["ementa"]

        # Limita o conteúdo para não tornar a mensagem muito longa
        conteudo_resumido = portaria["conteudo"][:500].strip()
        if len(portaria["conteudo"]) > 500:
            conteudo_resumido += "..."

        linhas += [
            f"━━━━━━━━━━━━━━━━━━",
            f"*{i}. Nome:* {nome}",
            f"*Ato:* {titulo}",
            f"*Ementa:* {ementa}" if ementa else None,
            f"\n{conteudo_resumido}",
            "",
        ]

    return "\n".join(l for l in linhas if l is not None)


def enviar_whatsapp(mensagem: str, grupo: str) -> bool:
    """
    Envia a mensagem para o grupo do WhatsApp via Selenium + WhatsApp Web.

    Usa um perfil Chrome dedicado (WHATSAPP_PROFILE_DIR), separado do Chrome
    pessoal do usuário, evitando conflitos de perfil bloqueado.

    Na primeira execução o Chrome abre visivelmente para o usuário escanear o
    QR code. Após autenticar, a sessão fica salva no perfil dedicado e as
    execuções seguintes carregam sem precisar escanear novamente.
    """
    log.info(f"Enviando mensagem para o grupo WhatsApp: '{grupo}'")

    # Sessão válida = IndexedDB do WhatsApp presente (criado só após autenticação real)
    # Verificar apenas a pasta "Default" é insuficiente — Chrome a cria mesmo sem login
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
            "Sessão do WhatsApp não encontrada — Chrome abrirá para autenticação. "
            "Escaneie o QR code no WhatsApp do celular. "
            f"Você tem {TIMEOUT_QR_CODE} segundos."
        )

    options = webdriver.ChromeOptions()
    options.add_argument(f"--user-data-dir={WHATSAPP_PROFILE_DIR}")
    options.add_argument("--profile-directory=Default")
    options.add_argument("--remote-allow-origins=*")

    driver = None
    try:
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
        log.info("Mensagem enviada com sucesso!")
        time.sleep(2)
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

    # 1. Obtém a data do dia anterior do sistema
    data_anterior = obter_data_anterior()
    log.info(f"Data alvo (dia anterior): {data_anterior}")

    # 2. Busca a publicação do DOM para essa data
    publicacao = buscar_publicacao_por_data(data_anterior)

    if not publicacao:
        log.warning(f"Nenhuma edição do DOM encontrada para {data_anterior}. Encerrando.")
        return

    # 3. Extrai os atos (portarias, decretos, etc.) da publicação
    portarias = extrair_portarias(publicacao["url_html"])

    if not portarias:
        log.warning("Nenhum ato extraído da publicação. Verifique a estrutura do site.")
        return

    # 4. Busca os nomes monitorados nos atos extraídos
    ocorrencias = buscar_nomes_em_portarias(portarias, NOMES_MONITORADOS)

    if not ocorrencias:
        log.info("Nenhum nome monitorado encontrado na edição de hoje. Nenhuma mensagem enviada.")
        return

    log.info(f"{len(ocorrencias)} ocorrência(s) encontrada(s). Preparando envio...")

    # 5. Formata e envia a mensagem no WhatsApp
    mensagem = formatar_mensagem(ocorrencias, data_anterior)
    log.info(f"Mensagem formatada:\n{mensagem}")

    sucesso = enviar_whatsapp(mensagem, WHATSAPP_GRUPO)

    if sucesso:
        log.info("Processo concluído com sucesso!")
    else:
        log.error("Falha no envio da mensagem. Verifique os logs.")


if __name__ == "__main__":
    main()