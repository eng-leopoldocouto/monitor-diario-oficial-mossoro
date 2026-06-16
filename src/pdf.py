"""Extração e fatiamento de PDFs do Diário Oficial por ocorrência."""
import io
import os
import re
import unicodedata

import requests
from bs4 import BeautifulSoup

from .config import log, BASE_URL, PDF_TEMP_DIR


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

    # Defesa contra SSRF: só seguimos URLs do próprio domínio do DOM. Se a página
    # (eventualmente adulterada) apontar para um host externo, recusamos.
    if not url_pdf.startswith(BASE_URL + "/"):
        log.warning(f"URL do PDF fora do domínio oficial ({BASE_URL}) — ignorada: {url_pdf}")
        return None

    log.info(f"URL do PDF encontrada: {url_pdf}")
    return url_pdf


def _sanitizar_nome_arquivo(nome: str) -> str:
    """Remove caracteres inválidos para nomes de arquivo no Windows/Linux.

    Também neutraliza sequências de travessia de diretório (".."), já que o nome
    deriva de conteúdo externo (título da portaria vindo do site do DOM).
    """
    limpo = re.sub(r'[\\/:*?"<>|]', '-', nome)
    limpo = limpo.replace("..", "-")  # impede travessia de diretório
    return limpo.strip(" .")


def _prox_ato_titulo(portaria: dict, portarias: list[dict] | None) -> str | None:
    """
    Título do ato imediatamente seguinte a `portaria` na lista ORDENADA de atos
    (a mesma que `extrair_portarias` produz, já segmentada via ato_separator).

    Retorna None quando: a lista não foi fornecida, `portaria` é o último ato, ou
    o objeto não está na lista. A comparação é por IDENTIDADE (`is`) — o dict da
    ocorrência é o mesmo objeto inserido na lista por buscar_nomes_em_portarias.
    """
    if not portarias:
        return None
    for i, ato in enumerate(portarias):
        if ato is portaria:
            # lista produzida por extrair_portarias: "titulo" sempre presente
            return portarias[i + 1]["titulo"] if i + 1 < len(portarias) else None
    return None


def _paginas_da_portaria(
    combined: str,
    page_offsets: list[int],
    start_pos: int,
    titulo_norm: str,
    prox_titulo_norm: str | None,
    all_portaria_positions: list[int],
) -> list[int]:
    """
    Páginas (1-based) do PDF que contêm a portaria iniciada em `start_pos`.

    A fronteira final (`end_pos`) é, em ordem de preferência:
      1. início do PRÓXIMO ato (`prox_titulo_norm`), localizado após a portaria;
      2. próximo cabeçalho `PORTARIA Nº ...,` (`all_portaria_positions`);
      3. fim do documento.

    Inclui toda página cujo intervalo de texto [pg_start, pg_end) se sobrepõe a
    [start_pos, end_pos). `page_offsets` tem len == nº de páginas + 1 (sentinela).

    Contrato: `start_pos` deve ser válido (>= 0, já localizado pelo chamador);
    a função não revalida que `titulo_norm` ocorre em `start_pos`.
    """
    search_from = start_pos + len(titulo_norm)

    end_pos = -1
    if prox_titulo_norm:
        achado = combined.find(prox_titulo_norm, search_from)
        if achado != -1:
            end_pos = achado
    if end_pos == -1:
        for pos in all_portaria_positions:
            if pos >= search_from:
                end_pos = pos
                break  # lista já ordenada por posição
    if end_pos == -1:
        end_pos = len(combined)

    paginas: list[int] = []
    for page_idx in range(len(page_offsets) - 1):
        pg_start = page_offsets[page_idx]
        pg_end = page_offsets[page_idx + 1]
        if pg_start < end_pos and pg_end > start_pos:
            paginas.append(page_idx + 1)
    return paginas


def extrair_pdfs_por_ocorrencia(
    url_pdf: str,
    ocorrencias: list[dict],
    portarias: list[dict] | None = None,
) -> list[str]:
    """
    Baixa o PDF da publicação e gera um arquivo PDF separado para cada
    ocorrência encontrada, contendo apenas as páginas da portaria associada.

    Nome do arquivo: "{titulo_portaria} - {nome_pessoa}.pdf"
    Exemplo: "PORTARIA Nº 262, DE 08 DE MAIO DE 2026 - MARINA COSTA.pdf"

    Retorna lista de caminhos dos PDFs gerados (vazia se falhar).

    Quando `portarias` (lista ORDENADA de atos da edição, vinda de
    extrair_portarias) é fornecida, o fim de cada portaria é o início do ato
    seguinte — evitando arrastar páginas quando a portaria é seguida por atos de
    outro tipo (extrato, termo…). Sem `portarias`, mantém o comportamento antigo.
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

        # Fronteira final da portaria: início do PRÓXIMO ato na ordem real do
        # Diário (lista `portarias`, segmentada via ato_separator). Sem a lista,
        # ou se o próximo ato não for localizável no PDF, recai no comportamento
        # antigo (próximo PORTARIA Nº; depois fim do documento).
        prox_ato = _prox_ato_titulo(portaria, portarias)
        prox_titulo_norm = _normalizar(prox_ato) if prox_ato else None

        paginas_incluidas = _paginas_da_portaria(
            combined, page_offsets, start_pos, titulo_norm,
            prox_titulo_norm, all_portaria_positions,
        )
        for pg in paginas_incluidas:
            writer.add_page(reader.pages[pg - 1])

        if not paginas_incluidas:
            log.warning(f"Nenhuma página encontrada para '{titulo}' — ocorrência pulada.")
            continue

        paginas_incluidas = sorted(set(paginas_incluidas))
        nomes_log = ", ".join(nomes)
        # debug (não info) para não expor nomes (PII) no console
        log.debug(f"Páginas {paginas_incluidas} extraídas para [{nomes_log}].")

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
        # basename garante que o arquivo nunca escape da pasta de destino
        caminho_saida = os.path.join(pasta, os.path.basename(nome_arquivo))
        with open(caminho_saida, "wb") as f:
            writer.write(f)

        log.info(f"PDF gerado: {caminho_saida}")
        caminhos_gerados.append(caminho_saida)

    return caminhos_gerados
