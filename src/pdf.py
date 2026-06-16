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
            return portarias[i + 1]["titulo"] if i + 1 < len(portarias) else None
    return None


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
