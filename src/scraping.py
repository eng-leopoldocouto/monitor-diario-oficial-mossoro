"""Scraping do Diário Oficial de Mossoró (busca de edições e atos)."""
import re
from datetime import datetime, timedelta

import requests
from bs4 import BeautifulSoup

from .config import log, BASE_URL


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


def buscar_publicacao_por_numero(numero: int) -> dict | None:
    """
    Procura na listagem de edições a publicação cujo número da edição
    (ex.: "DOM Nº 839") seja igual a `numero` e retorna seus dados.

    Pagina /dom/edicoes (listagem decrescente por número) lendo, em cada card,
    o número da edição, o id da publicação e a data. Retorna o mesmo formato
    de buscar_ultima_publicacao:
        {id, numero, data, url_html}

    Retorna None se: o número não existir (a listagem decrescente passou do
    alvo — caso de lacuna), a página vier vazia, ou ocorrer erro de rede.
    """
    log.info(f"Buscando edição do DOM número: {numero}")
    headers = {"User-Agent": "Mozilla/5.0 (compatible; DOM-Monitor/1.0)"}

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
        cards = soup.select("a[href^='/dom/publicacao/']")

        if not cards:
            log.warning("Nenhuma edição encontrada na página — encerrando busca.")
            return None

        for card in cards:
            href = card.get("href", "")
            match = re.search(r"/dom/publicacao/(\d+)", href)
            if not match:
                continue
            pub_id = match.group(1)

            parent = card.find_parent()
            texto = parent.get_text(" ", strip=True) if parent else ""
            num_match = re.search(r"DOM\s+N[ºo°]?\s*(\d+)", texto, re.IGNORECASE)
            if not num_match:
                continue
            num_card = int(num_match.group(1))

            if num_card == numero:
                date_match = re.search(r"(\d{2}/\d{2}/\d{4})", texto)
                data_str = date_match.group(1) if date_match else "data desconhecida"
                url_html = f"{BASE_URL}/dom/publicacao/{pub_id}"
                log.info(f"Edição Nº {numero} encontrada: ID {pub_id} — {url_html}")
                return {"id": pub_id, "numero": num_card, "data": data_str, "url_html": url_html}

            # Listagem é decrescente: se já passou do alvo, a edição não existe.
            if num_card < numero:
                log.info(
                    f"Edição Nº {numero} não encontrada "
                    f"(listagem já passou para Nº {num_card})."
                )
                return None

        pagina += 1
        if pagina > 20:  # Proteção contra loop infinito
            log.warning("Limite de páginas atingido sem encontrar o número.")
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
        r"(?:PORTARIA|DECRETO|LEI|RESOLUÇÃO|RESOLUCAO|ATO|TERMO|EXTRATO|AVISO|EDITAL"
        r"|LICITAÇÃO|LICITACAO|RETIFICAÇÃO|RETIFICACAO|RESULTADO"
        r"|PROGRAMAÇÃO|PROGRAMACAO|TRIBUNAL|NOTIFICAÇÃO|NOTIFICACAO"
        r"|ACÓRDÃO|ACORDAO|REGULAMENTO|JUSTIFICATIVA)"
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
