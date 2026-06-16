"""Envio de mensagens e arquivos via WhatsApp Web (Selenium)."""
import os
import shutil
import tempfile
import time
import ctypes
import platform

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

from .config import log, WHATSAPP_PROFILE_DIR, TIMEOUT_QR_CODE


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
    sessao_descartavel: bool = False,
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

        # Detecta e fecha o pop-up de novidades/atualizações do WhatsApp
        # (ex.: "Novidades", "Continuar", "Atualização disponível"). Aparece
        # apenas de vez em quando, sobreposto à interface, e bloqueia a busca
        # do grupo se não for dispensado. Tudo aqui é best-effort: se não houver
        # pop-up, seguimos normalmente.
        #
        # Para não atrasar a execução normal (sem pop-up), primeiro checamos
        # rapidamente se há algum diálogo na tela; só então tentamos fechá-lo.
        try:
            WebDriverWait(driver, 3).until(
                EC.presence_of_element_located((By.XPATH, '//div[@role="dialog"]'))
            )
            log.info("Diálogo sobreposto detectado — tentando fechar (pop-up de novidades).")
            botoes_fechar_popup = [
                # Botões de ação do diálogo de novidades
                '//div[@role="dialog"]//button[contains(normalize-space(),"Continuar")]',
                '//div[@role="dialog"]//button[contains(normalize-space(),"Continue")]',
                '//div[@role="dialog"]//button[contains(normalize-space(),"Entendi")]',
                '//div[@role="dialog"]//button[contains(normalize-space(),"OK")]',
                '//div[@role="dialog"]//button[contains(normalize-space(),"Ok")]',
                '//div[@role="dialog"]//button[contains(normalize-space(),"Agora não")]',
                '//div[@role="dialog"]//button[contains(normalize-space(),"Not now")]',
                # Botão "X" de fechar do diálogo
                '//div[@role="dialog"]//button[@aria-label="Fechar"]',
                '//div[@role="dialog"]//button[@aria-label="Close"]',
                '//div[@role="dialog"]//div[@aria-label="Fechar"]',
                '//div[@role="dialog"]//div[@aria-label="Close"]',
            ]
            for xpath in botoes_fechar_popup:
                try:
                    botao = WebDriverWait(driver, 2).until(
                        EC.element_to_be_clickable((By.XPATH, xpath))
                    )
                    log.info(f"Fechando pop-up via: {xpath}")
                    botao.click()
                    time.sleep(1)
                    break
                except Exception:
                    continue
            else:
                # Nenhum botão conhecido funcionou; tenta dispensar com ESC
                log.warning(
                    "Diálogo detectado mas nenhum botão de fechar conhecido funcionou — "
                    "tentando tecla ESC."
                )
                try:
                    webdriver.ActionChains(driver).send_keys(Keys.ESCAPE).perform()
                    time.sleep(1)
                except Exception:
                    log.warning("Não foi possível fechar o diálogo automaticamente.")
        except Exception:
            log.info("Sem pop-up de novidades.")

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
        if perfil_temp:
            shutil.rmtree(perfil_temp, ignore_errors=True)
            log.info(f"Perfil temporário (sessão descartável) removido: {perfil_temp}")
