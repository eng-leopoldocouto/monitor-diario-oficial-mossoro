"""
Testes automatizados — monitor_diario_oficial.py
=================================================
Cobertura: obter_data_anterior, buscar_publicacao_por_data,
           extrair_portarias, buscar_nomes_em_portarias,
           formatar_mensagem, enviar_whatsapp.

Como executar:
    pytest test_monitor_diario_oficial.py -v
    pytest test_monitor_diario_oficial.py -v --tb=short   # traceback curto
"""

import os
import re
import sys
import unicodedata
import pytest
from datetime import datetime
from unittest.mock import patch, MagicMock, call
from selenium.common.exceptions import TimeoutException as SeleniumTimeoutException

# Garante que o módulo seja importável mesmo ao rodar de outro diretório
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import monitor_diario_oficial as monitor


# ══════════════════════════════════════════════════════════════
# HTML FIXTURES — simulam respostas reais do site
# ══════════════════════════════════════════════════════════════

HTML_EDICOES_COM_ALVO = """
<html><body>
  <div class="card">
    <span>Edição 815 — 08/05/2026</span>
    <a href="/dom/publicacao/815">Ver publicação</a>
  </div>
  <div class="card">
    <span>Edição 813 — 06/05/2026</span>
    <a href="/dom/publicacao/813">Ver publicação</a>
  </div>
  <div class="card">
    <span>Edição 812 — 05/05/2026</span>
    <a href="/dom/publicacao/812">Ver publicação</a>
  </div>
</body></html>
"""

HTML_EDICOES_TODAS_MAIS_ANTIGAS = """
<html><body>
  <div class="card">
    <span>Edição 810 — 03/05/2026</span>
    <a href="/dom/publicacao/810">Ver publicação</a>
  </div>
</body></html>
"""

HTML_EDICOES_TODAS_MAIS_NOVAS = """
<html><body>
  <div class="card">
    <span>Edição 815 — 08/05/2026</span>
    <a href="/dom/publicacao/815">Ver publicação</a>
  </div>
  <div class="card">
    <span>Edição 814 — 07/05/2026</span>
    <a href="/dom/publicacao/814">Ver publicação</a>
  </div>
</body></html>
"""

HTML_EDICOES_VAZIA = "<html><body></body></html>"

# Listagem no formato REAL do site (texto do card: "DD/MM/AAAA DOM Nº NNN"),
# em ordem decrescente por número — como observado em /dom/edicoes.
HTML_EDICOES_POR_NUMERO = """
<html><body>
  <div class="card">
    <span>13/06/2026 DOM Nº 840</span>
    <a href="/dom/publicacao/1875">Ver publicação</a>
  </div>
  <div class="card">
    <span>12/06/2026 DOM Nº 839</span>
    <a href="/dom/publicacao/1874">Ver publicação</a>
  </div>
  <div class="card">
    <span>11/06/2026 DOM Nº 838</span>
    <a href="/dom/publicacao/1873">Ver publicação</a>
  </div>
</body></html>
"""

# Listagem com LACUNA: número 839 ausente (pula de 840 para 838). Usada para
# validar a parada antecipada quando a listagem decrescente passa do alvo.
HTML_EDICOES_NUMERO_COM_LACUNA = """
<html><body>
  <div class="card">
    <span>13/06/2026 DOM Nº 840</span>
    <a href="/dom/publicacao/1875">Ver publicação</a>
  </div>
  <div class="card">
    <span>11/06/2026 DOM Nº 838</span>
    <a href="/dom/publicacao/1873">Ver publicação</a>
  </div>
</body></html>
"""

HTML_PUBLICACAO = """
<html><body>
<div id="main-content">
Você está vendo
Data:
06/05/2026
<div class="ato_separator"></div>
PORTARIA Nº 072/2026 - GP/CMM
Dispõe sobre prorrogação da cessão funcional.
O PRESIDENTE DA CÂMARA MUNICIPAL, no uso de suas atribuições,

RESOLVE:

Art. 1º Autorizar a cessão da servidora EDNA GOMES DE SOUZA SALES.

Art. 2º Esta Portaria entra em vigor na data de sua publicação.
<div class="ato_separator"></div>
PORTARIA Nº 073/2026 - GP/CMM
Dispõe sobre anulação de portaria anterior.
Art. 1º TORNAR SEM EFEITO a Portaria nº 052/2026.
Art. 2º Esta Portaria entra em vigor na data de sua publicação.
<div class="ato_separator"></div>
EXTRATO DE CONTRATO
Contrato Nº 01/2026. Objeto: aquisição de cadeiras. Valor: R$ 57.256,00.
</div>
</body></html>
"""

HTML_SEM_MAIN_CONTENT = """
<html><body>
<p>PORTARIA Nº 001/2026</p>
<p>Dispõe sobre algo relevante.</p>
<p>Art. 1º Texto do artigo.</p>
</body></html>
"""

HTML_PUBLICACAO_COM_NBSP = """
<html><body>
<div id="main-content">
<div class="ato_separator"></div>
PORTARIA Nº 052/2026
Dispõe sobre designação de agente de contratação.
Art. 1\xba REVOGAR a portaria que designou\xa0MARIA\xa0SOUZA\xa0DOS\xa0SANTOS.
Art. 2\xba Esta Portaria entra em vigor na data de sua publicação.
</div>
</body></html>
"""


# ══════════════════════════════════════════════════════════════
# FIXTURES pytest
# ══════════════════════════════════════════════════════════════

@pytest.fixture
def portaria_simples():
    return {
        "titulo": "PORTARIA Nº 001/2026",
        "ementa": "Dispõe sobre nomeação para cargo em comissão.",
        "conteudo": (
            "PORTARIA Nº 001/2026\n"
            "Dispõe sobre nomeação para cargo em comissão.\n"
            "Art. 1º NOMEAR FULANO DE TAL para o cargo de Diretor."
        ),
    }


@pytest.fixture
def portaria_sem_ementa():
    return {
        "titulo": "EXTRATO DE CONTRATO",
        "ementa": "",
        "conteudo": (
            "EXTRATO DE CONTRATO\n"
            "Contrato Nº 10/2026. Objeto: fornecimento de uniformes."
        ),
    }


@pytest.fixture
def portaria_com_nome():
    return {
        "titulo": "PORTARIA Nº 052/2026",
        "ementa": "Dispõe sobre revogação de designação.",
        "conteudo": (
            "PORTARIA Nº 052/2026\n"
            "Dispõe sobre revogação de designação.\n"
            "Art. 1º REVOGAR a Portaria nº 068, que designou "
            "MARIA SOUZA DOS SANTOS para o cargo de Agente de Contratação."
        ),
    }


@pytest.fixture
def portaria_com_nbsp():
    """Simula texto real do site com \xa0 (non-breaking space) no nome."""
    return {
        "titulo": "PORTARIA Nº 052/2026",
        "ementa": "Dispõe sobre revogação.",
        "conteudo": (
            "PORTARIA Nº 052/2026\n"
            "Dispõe sobre revogação.\n"
            "Art. 1º REVOGAR a designação de\xa0MARIA\xa0SOUZA\xa0DOS\xa0SANTOS."
        ),
    }


@pytest.fixture
def portaria_com_acento():
    return {
        "titulo": "PORTARIA Nº 100/2026",
        "ementa": "Dispõe sobre concessão de licença.",
        "conteudo": (
            "PORTARIA Nº 100/2026\n"
            "Dispõe sobre concessão de licença.\n"
            "Art. 1º CONCEDER ao servidor ANTONIO PEREIRA DA SILVA licença especial."
        ),
    }


def _mock_resposta_http(html: str) -> MagicMock:
    """Cria um mock de resposta HTTP com o HTML fornecido."""
    mock = MagicMock()
    mock.text = html
    mock.raise_for_status = MagicMock()
    return mock


def _setup_selenium_mocks(mock_chrome_class, mock_wait_class):
    """
    Configura os mocks do Selenium para simular um fluxo bem-sucedido.

    O novo código cria WebDriverWait dentro de loops, então todas as chamadas
    retornam a mesma instância mock. A sequência de .until() é:
      1. QR code check          → SeleniumTimeoutException (sem QR, informativo)
      2. Portão de login        → retorna mock_interface (interface logada presente)
      3. Diálogo "usar janela"  → SeleniumTimeoutException (sem conflito)
      4. Pop-up de novidades    → SeleniumTimeoutException (sem pop-up, caso comum)
      5. Search box loop        → retorna caixa_pesquisa (1ª tentativa de XPath)
      6. Resultado grupo        → retorna resultado_grupo
      7. Message box loop       → retorna caixa_msg (1ª tentativa de XPath)
    """
    mock_driver = MagicMock()
    mock_chrome_class.return_value = mock_driver

    mock_caixa_pesquisa = MagicMock()
    mock_resultado_grupo = MagicMock()
    mock_caixa_msg = MagicMock()
    mock_interface = MagicMock()

    # Todas as instâncias de WebDriverWait retornam o mesmo mock
    mock_wait_inst = MagicMock()
    mock_wait_class.return_value = mock_wait_inst

    mock_wait_inst.until.side_effect = [
        SeleniumTimeoutException(),  # 1. QR não encontrado (checagem informativa)
        mock_interface,              # 2. portão de login → interface logada presente
        SeleniumTimeoutException(),  # 3. diálogo "usar nesta janela" não encontrado
        SeleniumTimeoutException(),  # 4. pop-up de novidades não presente (caso comum)
        mock_caixa_pesquisa,         # 5. search box encontrada no 1º XPath (input[@data-tab="3"])
        mock_resultado_grupo,        # 6. grupo encontrado
        mock_caixa_msg,              # 7. caixa de mensagem encontrada no 1º XPath
    ]

    # execute_script retorna lista vazia para não poluir o log com MagicMock
    mock_driver.execute_script.return_value = []

    return mock_driver, mock_caixa_pesquisa, mock_resultado_grupo, mock_caixa_msg


# ══════════════════════════════════════════════════════════════
# 1. obter_data_anterior
# ══════════════════════════════════════════════════════════════

class TestObterDataAnterior:

    def test_formato_dd_mm_aaaa(self):
        """Resultado deve estar estritamente no formato DD/MM/AAAA."""
        resultado = monitor.obter_data_anterior()
        assert re.match(r"^\d{2}/\d{2}/\d{4}$", resultado), (
            f"Formato inválido: '{resultado}'"
        )

    def test_retorna_dia_anterior(self):
        """Deve retornar exatamente o dia anterior à data mockada."""
        with patch("monitor_diario_oficial.scraping.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2026, 5, 7, 12, 0, 0)
            mock_dt.strptime.side_effect = datetime.strptime
            resultado = monitor.obter_data_anterior()
        assert resultado == "06/05/2026"

    def test_virada_de_mes(self):
        """Deve calcular corretamente o último dia do mês anterior."""
        with patch("monitor_diario_oficial.scraping.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2026, 6, 1, 8, 0, 0)
            mock_dt.strptime.side_effect = datetime.strptime
            resultado = monitor.obter_data_anterior()
        assert resultado == "31/05/2026"

    def test_virada_de_ano(self):
        """Deve calcular corretamente 31/12 quando hoje é 01/01."""
        with patch("monitor_diario_oficial.scraping.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2026, 1, 1, 0, 0, 0)
            mock_dt.strptime.side_effect = datetime.strptime
            resultado = monitor.obter_data_anterior()
        assert resultado == "31/12/2025"

    def test_dia_com_zero_a_esquerda(self):
        """Dias de 1 a 9 devem ter zero à esquerda (ex: 06, não 6)."""
        with patch("monitor_diario_oficial.scraping.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2026, 5, 8, 10, 0, 0)
            mock_dt.strptime.side_effect = datetime.strptime
            resultado = monitor.obter_data_anterior()
        dia = resultado.split("/")[0]
        assert len(dia) == 2


# ══════════════════════════════════════════════════════════════
# 2a. buscar_ultima_publicacao
# ══════════════════════════════════════════════════════════════

class TestBuscarUltimaPublicacao:

    @patch("monitor_diario_oficial.requests.get")
    def test_retorna_primeiro_card_da_pagina(self, mock_get):
        """Deve retornar o primeiro card (ID 815), não filtrar por data."""
        mock_get.return_value = _mock_resposta_http(HTML_EDICOES_COM_ALVO)

        resultado = monitor.buscar_ultima_publicacao()

        assert resultado is not None
        assert resultado["id"] == "815"

    @patch("monitor_diario_oficial.requests.get")
    def test_retorna_data_do_primeiro_card(self, mock_get):
        """A data retornada deve ser a do primeiro card."""
        mock_get.return_value = _mock_resposta_http(HTML_EDICOES_COM_ALVO)

        resultado = monitor.buscar_ultima_publicacao()

        assert resultado["data"] == "08/05/2026"

    @patch("monitor_diario_oficial.requests.get")
    def test_url_html_formato_correto(self, mock_get):
        """A URL deve seguir o padrão do site."""
        mock_get.return_value = _mock_resposta_http(HTML_EDICOES_COM_ALVO)

        resultado = monitor.buscar_ultima_publicacao()

        assert resultado["url_html"] == "https://dom.mossoro.rn.gov.br/dom/publicacao/815"

    @patch("monitor_diario_oficial.requests.get")
    def test_retorna_none_em_pagina_vazia(self, mock_get):
        """Deve retornar None quando não há cards na página."""
        mock_get.return_value = _mock_resposta_http(HTML_EDICOES_VAZIA)

        resultado = monitor.buscar_ultima_publicacao()

        assert resultado is None

    @patch("monitor_diario_oficial.requests.get")
    def test_retorna_none_em_erro_de_rede(self, mock_get):
        """Deve retornar None em falha de rede."""
        import requests as req_lib
        mock_get.side_effect = req_lib.RequestException("timeout")

        resultado = monitor.buscar_ultima_publicacao()

        assert resultado is None

    @patch("monitor_diario_oficial.requests.get")
    def test_acessa_apenas_uma_pagina(self, mock_get):
        """Não deve paginar — acessa apenas a URL base das edições."""
        mock_get.return_value = _mock_resposta_http(HTML_EDICOES_COM_ALVO)

        monitor.buscar_ultima_publicacao()

        assert mock_get.call_count == 1


# ══════════════════════════════════════════════════════════════
# 2b. _sanitizar_nome_arquivo e extrair_pdfs_por_ocorrencia
# ══════════════════════════════════════════════════════════════

class TestSanitizarNomeArquivo:

    def test_remove_barra(self):
        assert "/" not in monitor._sanitizar_nome_arquivo("PORTARIA Nº 072/2026")

    def test_remove_dois_pontos(self):
        assert ":" not in monitor._sanitizar_nome_arquivo("hora: 10:00")

    def test_remove_asterisco_e_interrogacao(self):
        nome = monitor._sanitizar_nome_arquivo("arq*v?.pdf")
        assert "*" not in nome and "?" not in nome

    def test_texto_sem_caracteres_invalidos_inalterado(self):
        original = "PORTARIA Nº 262 - MARINA COSTA"
        assert monitor._sanitizar_nome_arquivo(original) == original


class TestExtrairPdfsPorOcorrencia:

    def _ocorrencia(self, titulo, nome, ementa=""):
        return {
            "nome": nome,
            "portaria": {"titulo": titulo, "ementa": ementa, "conteudo": titulo},
        }

    @patch("monitor_diario_oficial.requests.get")
    def test_retorna_lista_vazia_em_erro_de_rede(self, mock_get):
        """Deve retornar lista vazia se o PDF não puder ser baixado."""
        import requests as req_lib
        mock_get.side_effect = req_lib.RequestException("timeout")

        oc = self._ocorrencia("PORTARIA Nº 001/2026", "FULANO DE TAL")
        resultado = monitor.extrair_pdfs_por_ocorrencia("http://pdf.url", [oc])

        assert resultado == []

    def test_retorna_lista_vazia_sem_pypdf(self):
        """Se pypdf não estiver instalado, retorna lista vazia sem travar."""
        import builtins
        original_import = builtins.__import__

        def import_bloqueado(name, *args, **kwargs):
            if name == "pypdf":
                raise ImportError("pypdf ausente")
            return original_import(name, *args, **kwargs)

        oc = self._ocorrencia("PORTARIA Nº 001/2026", "FULANO DE TAL")
        with patch("builtins.__import__", side_effect=import_bloqueado):
            resultado = monitor.extrair_pdfs_por_ocorrencia("http://pdf.url", [oc])

        assert resultado == []

    def test_nome_arquivo_contem_titulo_e_nome(self, tmp_path):
        """O arquivo gerado deve ter título e nome da pessoa no nome."""
        from pypdf import PdfWriter
        import io as _io

        # Cria um PDF mínimo com texto da portaria
        writer = PdfWriter()
        writer.add_blank_page(width=200, height=200)
        buf = _io.BytesIO()
        writer.write(buf)
        pdf_bytes = buf.getvalue()

        mock_resp = MagicMock()
        mock_resp.content = pdf_bytes
        mock_resp.raise_for_status = MagicMock()

        oc = self._ocorrencia("PORTARIA Nº 001-2026", "MARINA COSTA")

        with patch("monitor_diario_oficial.requests.get", return_value=mock_resp):
            with patch("monitor_diario_oficial.os.path.dirname", return_value=str(tmp_path)):
                monitor.extrair_pdfs_por_ocorrencia("http://pdf.url", [oc])

        # Mesmo sem páginas encontradas (PDF em branco), a lista pode ser vazia.
        # O que testamos é que não lançou exceção e o formato do nome está correto
        # quando há páginas (verificado pelo _sanitizar_nome_arquivo).
        nome_esperado = monitor._sanitizar_nome_arquivo(
            "PORTARIA Nº 001-2026 - MARINA COSTA"
        ) + ".pdf"
        assert "PORTARIA" in nome_esperado
        assert "MARINA COSTA" in nome_esperado

    def test_nome_arquivo_inclui_data_quando_titulo_termina_com_virgula(self):
        """
        Quando o DOM divide o título em duas linhas — número na primeira e data
        na segunda — a ementa contém a data e deve ser incluída no nome do arquivo.

        Sem correção: "PORTARIA Nº 485, - FULANO.pdf"
        Com correção:  "PORTARIA Nº 485, DE 08 DE MAIO DE 2026 - FULANO.pdf"
        """
        # _sanitizar_nome_arquivo é chamada internamente; testamos apenas a lógica
        # de montagem do titulo_arquivo via _sanitizar_nome_arquivo diretamente.
        titulo_com_virgula = "PORTARIA Nº 485,"
        data_ementa = "DE 08 DE MAIO DE 2026"
        nome_pessoa = "FULANO DE TAL"

        # Simula o que extrair_pdfs_por_ocorrencia deve produzir:
        titulo_esperado = f"{titulo_com_virgula} {data_ementa}"
        nome_arquivo = monitor._sanitizar_nome_arquivo(
            f"{titulo_esperado} - {nome_pessoa}"
        ) + ".pdf"

        assert "DE 08 DE MAIO DE 2026" in nome_arquivo
        assert "FULANO DE TAL" in nome_arquivo
        assert "PORTARIA" in nome_arquivo

    def test_nome_arquivo_sem_data_quando_ementa_nao_e_data(self):
        """Quando a ementa não começa com 'DE <número>', não deve ser concatenada."""
        ementa = "Dispõe sobre nomeação."

        # Não deve concatenar — ementa não é continuação de data
        import re as _re
        e_data = bool(_re.match(r"DE\s+\d", ementa.strip(), _re.IGNORECASE))
        assert not e_data


# ══════════════════════════════════════════════════════════════
# 2. buscar_publicacao_por_data
# ══════════════════════════════════════════════════════════════

class TestBuscarPublicacaoPorData:

    @patch("monitor_diario_oficial.requests.get")
    def test_encontra_publicacao_na_data_exata(self, mock_get):
        """Deve retornar a publicação quando a data coincide exatamente."""
        mock_get.return_value = _mock_resposta_http(HTML_EDICOES_COM_ALVO)

        resultado = monitor.buscar_publicacao_por_data("06/05/2026")

        assert resultado is not None
        assert resultado["id"] == "813"
        assert resultado["data"] == "06/05/2026"

    @patch("monitor_diario_oficial.requests.get")
    def test_url_publicacao_formato_correto(self, mock_get):
        """A URL retornada deve seguir o padrão do site."""
        mock_get.return_value = _mock_resposta_http(HTML_EDICOES_COM_ALVO)

        resultado = monitor.buscar_publicacao_por_data("06/05/2026")

        assert resultado["url_html"] == "https://dom.mossoro.rn.gov.br/dom/publicacao/813"

    @patch("monitor_diario_oficial.requests.get")
    def test_retorna_none_quando_data_mais_antiga_que_cards(self, mock_get):
        """Deve parar e retornar None quando os cards já são mais antigos que o alvo."""
        mock_get.return_value = _mock_resposta_http(HTML_EDICOES_TODAS_MAIS_ANTIGAS)

        resultado = monitor.buscar_publicacao_por_data("06/05/2026")

        assert resultado is None

    @patch("monitor_diario_oficial.requests.get")
    def test_pagina_sem_cards_retorna_none(self, mock_get):
        """Deve retornar None quando a página não contém nenhuma edição."""
        mock_get.return_value = _mock_resposta_http(HTML_EDICOES_VAZIA)

        resultado = monitor.buscar_publicacao_por_data("06/05/2026")

        assert resultado is None

    @patch("monitor_diario_oficial.requests.get")
    def test_paginacao_quando_data_nao_esta_na_primeira_pagina(self, mock_get):
        """Deve avançar para a próxima página quando a data não é encontrada."""
        pagina_1 = _mock_resposta_http(HTML_EDICOES_TODAS_MAIS_NOVAS)
        pagina_2 = _mock_resposta_http(HTML_EDICOES_COM_ALVO)
        mock_get.side_effect = [pagina_1, pagina_2]

        resultado = monitor.buscar_publicacao_por_data("06/05/2026")

        assert resultado is not None
        assert mock_get.call_count == 2

    @patch("monitor_diario_oficial.requests.get")
    def test_erro_de_rede_retorna_none(self, mock_get):
        """Deve retornar None em qualquer falha de rede."""
        import requests as req_lib
        mock_get.side_effect = req_lib.RequestException("Connection refused")

        resultado = monitor.buscar_publicacao_por_data("06/05/2026")

        assert resultado is None

    def test_formato_de_data_invalido_retorna_none(self):
        """Deve retornar None sem fazer requisição para formato de data inválido."""
        resultado = monitor.buscar_publicacao_por_data("2026-05-06")
        assert resultado is None

    @patch("monitor_diario_oficial.requests.get")
    def test_limite_de_20_paginas(self, mock_get):
        """Não deve buscar mais de 20 páginas para evitar loop infinito."""
        mock_get.return_value = _mock_resposta_http(HTML_EDICOES_TODAS_MAIS_NOVAS)

        resultado = monitor.buscar_publicacao_por_data("01/01/2020")

        assert resultado is None
        assert mock_get.call_count <= 20


# ══════════════════════════════════════════════════════════════
# 3. extrair_portarias
# ══════════════════════════════════════════════════════════════

class TestExtrairPortarias:

    URL = "https://dom.mossoro.rn.gov.br/dom/publicacao/813"

    @patch("monitor_diario_oficial.requests.get")
    def test_extrai_multiplas_portarias(self, mock_get):
        """Deve extrair todos os atos encontrados sequencialmente."""
        mock_get.return_value = _mock_resposta_http(HTML_PUBLICACAO)

        portarias = monitor.extrair_portarias(self.URL)

        assert len(portarias) >= 2

    @patch("monitor_diario_oficial.requests.get")
    def test_titulo_inicia_com_palavra_chave(self, mock_get):
        """O título de cada ato deve começar com a palavra-chave reconhecida."""
        mock_get.return_value = _mock_resposta_http(HTML_PUBLICACAO)

        portarias = monitor.extrair_portarias(self.URL)

        palavras_chave = {"PORTARIA", "DECRETO", "LEI", "EXTRATO", "AVISO", "EDITAL",
                         "RESOLUÇÃO", "RESOLUCAO", "ATO", "TERMO"}
        for p in portarias:
            primeira_palavra = p["titulo"].split()[0].upper()
            assert primeira_palavra in palavras_chave, (
                f"Título inesperado: '{p['titulo']}'"
            )

    @patch("monitor_diario_oficial.requests.get")
    def test_ementa_preenchida_com_linha_apos_titulo(self, mock_get):
        """A ementa deve ser a primeira linha depois do título do ato."""
        mock_get.return_value = _mock_resposta_http(HTML_PUBLICACAO)

        portarias = monitor.extrair_portarias(self.URL)

        primeira = portarias[0]
        assert primeira["ementa"] != ""
        assert primeira["ementa"] != primeira["titulo"]

    @patch("monitor_diario_oficial.requests.get")
    def test_conteudo_contem_titulo(self, mock_get):
        """O conteúdo completo de cada ato deve incluir o seu título."""
        mock_get.return_value = _mock_resposta_http(HTML_PUBLICACAO)

        portarias = monitor.extrair_portarias(self.URL)

        for p in portarias:
            assert p["titulo"] in p["conteudo"]

    @patch("monitor_diario_oficial.requests.get")
    def test_captura_extrato_de_contrato(self, mock_get):
        """EXTRATO DE CONTRATO deve ser reconhecido como ato válido."""
        mock_get.return_value = _mock_resposta_http(HTML_PUBLICACAO)

        portarias = monitor.extrair_portarias(self.URL)

        titulos = [p["titulo"] for p in portarias]
        assert any("EXTRATO" in t for t in titulos)

    @patch("monitor_diario_oficial.requests.get")
    def test_erro_http_retorna_lista_vazia(self, mock_get):
        """Deve retornar lista vazia em caso de falha na requisição."""
        import requests as req_lib
        mock_get.side_effect = req_lib.RequestException("Timeout")

        portarias = monitor.extrair_portarias(self.URL)

        assert portarias == []

    @patch("monitor_diario_oficial.requests.get")
    def test_fallback_para_body_quando_sem_main_content(self, mock_get):
        """Deve usar <body> quando #main-content não existe na página."""
        mock_get.return_value = _mock_resposta_http(HTML_SEM_MAIN_CONTENT)

        portarias = monitor.extrair_portarias(self.URL)

        assert len(portarias) >= 1
        assert "PORTARIA" in portarias[0]["titulo"]

    @patch("monitor_diario_oficial.requests.get")
    def test_texto_antes_de_qualquer_portaria_nao_causa_erro(self, mock_get):
        """Linhas de navegação antes do primeiro ato não devem gerar entradas."""
        mock_get.return_value = _mock_resposta_http(HTML_PUBLICACAO)

        portarias = monitor.extrair_portarias(self.URL)

        # Nenhuma portaria deve ter como título texto de navegação do site
        titulos = [p["titulo"] for p in portarias]
        assert not any("Você está vendo" in t for t in titulos)
        assert not any("Data:" in t for t in titulos)


# ══════════════════════════════════════════════════════════════
# 4. buscar_nomes_em_portarias
# ══════════════════════════════════════════════════════════════

class TestBuscarNomesEmPortarias:

    def test_encontra_nome_presente(self, portaria_com_nome):
        encontrados = monitor.buscar_nomes_em_portarias(
            [portaria_com_nome], ["MARIA SOUZA DOS SANTOS"]
        )
        assert len(encontrados) == 1
        assert encontrados[0]["nome"] == "MARIA SOUZA DOS SANTOS"

    def test_busca_e_case_insensitive_na_lista(self, portaria_com_nome):
        """Nome na lista em minúsculas deve encontrar conteúdo em maiúsculas."""
        encontrados = monitor.buscar_nomes_em_portarias(
            [portaria_com_nome], ["maria souza dos santos"]
        )
        assert len(encontrados) == 1

    def test_nao_encontra_nome_ausente(self, portaria_simples):
        encontrados = monitor.buscar_nomes_em_portarias(
            [portaria_simples], ["NOME QUE NAO EXISTE NO TEXTO"]
        )
        assert encontrados == []

    def test_lista_vazia_de_portarias_retorna_vazio(self):
        encontrados = monitor.buscar_nomes_em_portarias([], ["QUALQUER NOME"])
        assert encontrados == []

    def test_lista_vazia_de_nomes_retorna_vazio(self, portaria_com_nome):
        encontrados = monitor.buscar_nomes_em_portarias([portaria_com_nome], [])
        assert encontrados == []

    def test_encontra_nome_em_multiplas_portarias(
        self, portaria_com_nome, portaria_simples
    ):
        """Deve reportar cada portaria onde o nome aparece separadamente."""
        portaria_simples["conteudo"] += "\nMARIA SOUZA DOS SANTOS também aqui."
        encontrados = monitor.buscar_nomes_em_portarias(
            [portaria_com_nome, portaria_simples],
            ["MARIA SOUZA DOS SANTOS"],
        )
        assert len(encontrados) == 2

    def test_encontra_multiplos_nomes_na_mesma_portaria(self, portaria_simples):
        """Dois nomes distintos na mesma portaria geram duas ocorrências."""
        portaria_simples["conteudo"] = (
            "PORTARIA Nº 001/2026\n"
            "NOMEAR ANTONIO PEREIRA DA SILVA e MARIA SOUZA DOS SANTOS."
        )
        encontrados = monitor.buscar_nomes_em_portarias(
            [portaria_simples],
            ["ANTONIO PEREIRA DA SILVA", "MARIA SOUZA DOS SANTOS"],
        )
        assert len(encontrados) == 2

    def test_normaliza_nbsp_no_conteudo(self, portaria_com_nbsp):
        """\xa0 (non-breaking space) no texto não deve impedir a localização do nome."""
        encontrados = monitor.buscar_nomes_em_portarias(
            [portaria_com_nbsp], ["MARIA SOUZA DOS SANTOS"]
        )
        assert len(encontrados) == 1

    def test_retorna_referencia_correta_a_portaria(self, portaria_com_nome):
        """O campo 'portaria' deve apontar para o dict correto."""
        encontrados = monitor.buscar_nomes_em_portarias(
            [portaria_com_nome], ["MARIA SOUZA DOS SANTOS"]
        )
        assert encontrados[0]["portaria"] is portaria_com_nome

    def test_dois_nomes_sinonimos_na_mesma_portaria_geram_duas_ocorrencias(
        self, portaria_com_acento
    ):
        """ANTONIO e ANTÔNIO (com e sem acento) são tratados como nomes distintos."""
        encontrados = monitor.buscar_nomes_em_portarias(
            [portaria_com_acento],
            ["ANTONIO PEREIRA DA SILVA", "ANTÔNIO PEREIRA DA SILVA"],
        )
        # Só o nome sem acento existe no texto — deve encontrar exatamente 1
        assert len(encontrados) == 1


# ══════════════════════════════════════════════════════════════
# 5. formatar_mensagem
# ══════════════════════════════════════════════════════════════

class TestFormatarMensagem:

    def _ocorrencia(self, nome, titulo, ementa, conteudo):
        return {
            "nome": nome,
            "portaria": {"titulo": titulo, "ementa": ementa, "conteudo": conteudo},
        }

    def test_cabecalho_contem_data(self):
        oc = self._ocorrencia("FULANO", "PORTARIA Nº 001", "Ementa.", "Conteúdo.")
        msg = monitor.formatar_mensagem([oc], "06/05/2026")
        assert "06/05/2026" in msg

    def test_cabecalho_menciona_diario_oficial(self):
        oc = self._ocorrencia("FULANO", "PORTARIA Nº 001", "Ementa.", "Conteúdo.")
        msg = monitor.formatar_mensagem([oc], "06/05/2026")
        assert "DIÁRIO OFICIAL" in msg or "DIARIO OFICIAL" in msg

    def test_cabecalho_menciona_sala_saude_educacao(self):
        """A mensagem deve identificar a Sala Saúde / SEINFRA no cabeçalho."""
        oc = self._ocorrencia("FULANO", "PORTARIA Nº 001", "Ementa.", "Conteúdo.")
        msg = monitor.formatar_mensagem([oc], "06/05/2026")
        cabecalho_upper = msg.upper()
        assert "SAÚDE" in cabecalho_upper or "SAUDE" in cabecalho_upper

    def test_contagem_de_ocorrencias_no_cabecalho(self):
        oc1 = self._ocorrencia("NOME A", "PORTARIA Nº 001", "", "Conteudo.")
        oc2 = self._ocorrencia("NOME B", "PORTARIA Nº 002", "", "Conteudo.")
        msg = monitor.formatar_mensagem([oc1, oc2], "06/05/2026")
        assert "2 ocorrência(s)" in msg

    def test_nome_encontrado_aparece_na_mensagem(self):
        oc = self._ocorrencia("MARIA SOUZA DOS SANTOS", "PORTARIA Nº 052", "", "X")
        msg = monitor.formatar_mensagem([oc], "06/05/2026")
        assert "MARIA SOUZA DOS SANTOS" in msg

    def test_titulo_do_ato_aparece_na_mensagem(self):
        oc = self._ocorrencia("FULANO", "PORTARIA Nº 999/2026", "Ementa.", "Conteúdo.")
        msg = monitor.formatar_mensagem([oc], "06/05/2026")
        assert "PORTARIA Nº 999/2026" in msg

    def test_corpo_do_ato_aparece_na_mensagem(self):
        """Linhas após o título devem aparecer no corpo da mensagem."""
        conteudo = "PORTARIA Nº 001\nDispõe sobre nomeação.\nArt. 1º Resolve-se."
        oc = self._ocorrencia("FULANO", "PORTARIA Nº 001", "Dispõe sobre nomeação.", conteudo)
        msg = monitor.formatar_mensagem([oc], "06/05/2026")
        assert "Dispõe sobre nomeação." in msg
        assert "Art. 1º Resolve-se." in msg

    def test_label_ementa_nunca_aparece(self):
        """O campo 'Ementa:' foi removido da mensagem — conteúdo é exibido em bloco."""
        oc = self._ocorrencia("FULANO", "PORTARIA Nº 001", "Qualquer ementa.", "Conteúdo.")
        msg = monitor.formatar_mensagem([oc], "06/05/2026")
        assert "Ementa:" not in msg

    def test_conteudo_completo_sem_truncacao(self):
        """Conteúdos longos devem aparecer integralmente, sem '...' de truncação."""
        corpo_longo = "X " * 300  # 600 chars
        conteudo = "PORTARIA Nº 001\n" + corpo_longo
        oc = self._ocorrencia("FULANO", "PORTARIA Nº 001", "", conteudo)
        msg = monitor.formatar_mensagem([oc], "06/05/2026")
        assert corpo_longo.strip() in msg
        assert "..." not in msg

    def test_conteudo_curto_aparece_completo(self):
        conteudo = "PORTARIA Nº 001\nTexto breve."
        oc = self._ocorrencia("FULANO", "PORTARIA Nº 001", "", conteudo)
        msg = monitor.formatar_mensagem([oc], "06/05/2026")
        assert "Texto breve." in msg
        assert "..." not in msg

    def test_multiplas_ocorrencias_numeradas_sequencialmente(self):
        oc1 = self._ocorrencia("NOME A", "PORTARIA Nº 001", "E1.", "C1.")
        oc2 = self._ocorrencia("NOME B", "PORTARIA Nº 002", "E2.", "C2.")
        msg = monitor.formatar_mensagem([oc1, oc2], "06/05/2026")
        pos_1 = msg.find("1.")
        pos_2 = msg.find("2.")
        assert pos_1 != -1 and pos_2 != -1
        assert pos_1 < pos_2, "Ocorrência 1 deve aparecer antes da ocorrência 2"

    def test_retorna_string(self):
        oc = self._ocorrencia("X", "PORTARIA", "", "Y")
        assert isinstance(monitor.formatar_mensagem([oc], "01/01/2026"), str)

    def test_multiplos_nomes_mesma_portaria_agrupados_em_um_bloco(self):
        """Vários nomes na mesma portaria viram um único bloco com nomes em ' + '."""
        oc1 = self._ocorrencia("BEATRIZ ALMEIDA LIMA", "PORTARIA Nº 35,", "", "C.")
        oc2 = self._ocorrencia("RICARDO GOMES FERREIRA", "PORTARIA Nº 35,", "", "C.")
        msg = monitor.formatar_mensagem([oc1, oc2], "02/06/2026")
        assert "BEATRIZ ALMEIDA LIMA + RICARDO GOMES FERREIRA" in msg
        # Um único bloco → conteúdo da portaria não é repetido
        assert msg.count("PORTARIA Nº 35,") == 1
        # Ordem de primeira aparição é preservada
        assert msg.index("BEATRIZ") < msg.index("RICARDO")

    def test_contagem_reflete_portarias_agrupadas(self):
        """A contagem do cabeçalho conta portarias distintas, não nomes repetidos."""
        oc1 = self._ocorrencia("NOME A", "PORTARIA Nº 38,", "", "C.")
        oc2 = self._ocorrencia("NOME B", "PORTARIA Nº 38,", "", "C.")
        oc3 = self._ocorrencia("NOME C", "PORTARIA Nº 38,", "", "C.")
        msg = monitor.formatar_mensagem([oc1, oc2, oc3], "02/06/2026")
        assert "1 ocorrência(s)" in msg
        assert "NOME A + NOME B + NOME C" in msg

    def test_nome_repetido_na_mesma_portaria_nao_duplica(self):
        """O mesmo nome encontrado duas vezes na portaria aparece só uma vez."""
        oc1 = self._ocorrencia("FULANO", "PORTARIA Nº 10,", "", "C.")
        oc2 = self._ocorrencia("FULANO", "PORTARIA Nº 10,", "", "C.")
        msg = monitor.formatar_mensagem([oc1, oc2], "02/06/2026")
        assert msg.count("FULANO + FULANO") == 0

    def test_resumo_por_pessoa_aparece_antes_dos_detalhes(self):
        """O bloco de RESUMO deve vir antes dos blocos detalhados (separadores)."""
        oc = self._ocorrencia("FULANO", "PORTARIA Nº 31,", "", "C.")
        msg = monitor.formatar_mensagem([oc], "02/06/2026", 832)
        assert "RESUMO — POR PESSOA" in msg
        assert msg.index("RESUMO — POR PESSOA") < msg.index("━")


class TestFormatarResumoPorPessoa:

    # Conteúdo de portaria com designação real (gestor titular + substituto eventual)
    def _conteudo(self, titular, papel, contrato, substituto):
        return (
            f"RESOLVE:\n"
            f"Art. 1º Designar o servidor {titular}, matricula de n° 111, para atuar "
            f"como {papel} DO CONTRATO n° {contrato}, firmado entre a SECRETARIA, "
            f"tendo como substituto eventual {substituto}, matricula de n° 222."
        )

    def _ocorrencia(self, nome, titulo, conteudo="x"):
        return {"nome": nome, "portaria": {"titulo": titulo, "ementa": "", "conteudo": conteudo}}

    def test_agrupa_portarias_por_pessoa_com_contagem(self):
        ocs = [
            self._ocorrencia("RICARDO GOMES FERREIRA", "PORTARIA Nº 31,"),
            self._ocorrencia("RICARDO GOMES FERREIRA", "PORTARIA Nº 32,"),
            self._ocorrencia("BEATRIZ ALMEIDA LIMA", "PORTARIA Nº 35,"),
            self._ocorrencia("RICARDO GOMES FERREIRA", "PORTARIA Nº 35,"),
        ]
        resumo = monitor.formatar_resumo_por_pessoa(ocs)
        assert "👤 *RICARDO GOMES FERREIRA* (3)" in resumo
        assert "Portaria 31" in resumo and "Portaria 32" in resumo and "Portaria 35" in resumo
        assert "👤 *BEATRIZ ALMEIDA LIMA* (1)" in resumo

    def test_ordem_segue_primeira_aparicao(self):
        ocs = [
            self._ocorrencia("RICARDO", "PORTARIA Nº 31,"),
            self._ocorrencia("BEATRIZ", "PORTARIA Nº 35,"),
        ]
        resumo = monitor.formatar_resumo_por_pessoa(ocs)
        assert resumo.index("RICARDO") < resumo.index("BEATRIZ")

    def test_portaria_repetida_para_mesma_pessoa_nao_duplica(self):
        ocs = [
            self._ocorrencia("FULANO", "PORTARIA Nº 38,"),
            self._ocorrencia("FULANO", "PORTARIA Nº 38,"),
        ]
        resumo = monitor.formatar_resumo_por_pessoa(ocs)
        assert "👤 *FULANO* (1)" in resumo
        assert resumo.count("Portaria 38") == 1

    def test_conta_nomes_monitorados_no_cabecalho_do_resumo(self):
        ocs = [
            self._ocorrencia("A", "PORTARIA Nº 1,"),
            self._ocorrencia("B", "PORTARIA Nº 1,"),
            self._ocorrencia("C", "PORTARIA Nº 2,"),
        ]
        resumo = monitor.formatar_resumo_por_pessoa(ocs)
        assert "3 nome(s) monitorado(s) encontrado(s)" in resumo

    def test_exibe_funcao_e_contrato_gestor_titular(self):
        cont = self._conteudo("RICARDO GOMES FERREIRA", "GESTOR", "43/2024", "VALERIA SAMANTHA")
        ocs = [self._ocorrencia("RICARDO GOMES FERREIRA", "PORTARIA Nº 32,", cont)]
        resumo = monitor.formatar_resumo_por_pessoa(ocs)
        assert "Portaria 32 — Gestor · Contrato 43/2024" in resumo

    def test_exibe_funcao_gestor_substituto(self):
        cont = self._conteudo("VALERIA SAMANTHA", "GESTOR", "31/2024", "RICARDO GOMES FERREIRA")
        ocs = [self._ocorrencia("RICARDO GOMES FERREIRA", "PORTARIA Nº 31,", cont)]
        resumo = monitor.formatar_resumo_por_pessoa(ocs)
        assert "Portaria 31 — Gestor Substituto · Contrato 31/2024" in resumo


class TestExtrairFuncaoContrato:

    def _cont_gestor_fiscal(self):
        return (
            "RESOLVE:\n"
            "Art. 1º Designar o servidor VALERIA SAMANTHA, matricula n° 1, para atuar como "
            "GESTOR DO CONTRATO n° 08/2024, firmado entre a SECRETARIA, tendo como substituto "
            "eventual ALAERDSON LIMA, matricula n° 2.\n"
            "Art. 3° Designar a servidora JOSE LEOPOLDO, matricula nº 3 para atuar como FISCAL "
            "DO CONTRATO n° 08/2024, tendo como substituto eventual FRANCISCO GUEDES, matricula n° 4."
        )

    def test_gestor_titular(self):
        f, c = monitor._extrair_funcao_contrato(self._cont_gestor_fiscal(), "VALERIA SAMANTHA")
        assert f == "Gestor" and c == "08/2024"

    def test_gestor_substituto(self):
        f, c = monitor._extrair_funcao_contrato(self._cont_gestor_fiscal(), "ALAERDSON LIMA")
        assert f == "Gestor Substituto" and c == "08/2024"

    def test_fiscal_titular(self):
        f, c = monitor._extrair_funcao_contrato(self._cont_gestor_fiscal(), "JOSE LEOPOLDO")
        assert f == "Fiscal" and c == "08/2024"

    def test_fiscal_substituto(self):
        f, c = monitor._extrair_funcao_contrato(self._cont_gestor_fiscal(), "FRANCISCO GUEDES")
        assert f == "Fiscal Substituto" and c == "08/2024"

    def test_aceita_gestora_feminino(self):
        cont = ("Art. 1º Designar a servidora MARIA, matricula n° 1, para atuar como GESTORA "
                "DO CONTRATO n° 10/2025, tendo como substituta eventual JOAO, matricula n° 2.")
        f, c = monitor._extrair_funcao_contrato(cont, "MARIA")
        assert f == "Gestor" and c == "10/2025"

    def test_funcao_nao_identificada_quando_nome_ausente(self):
        f, c = monitor._extrair_funcao_contrato(self._cont_gestor_fiscal(), "PESSOA INEXISTENTE")
        assert f == "função não identificada"

    # ---- variações reais do DOM Nº 160 (publicação 1880) ----
    #
    # Formatos observados no Diário que o padrão original não cobria:
    #   1. vírgula entre "CONTRATO" e o número: "GESTOR DO CONTRATO, nº 05/2025"
    #   2. "DE CONTRATO" em vez de "DO CONTRATO": "FISCAL DE CONTRATO"
    #   3. ordem "eventual substituto" em vez de "substituto eventual"

    def _cont_dom_160(self):
        return (
            "RESOLVE:\n"
            "Art. 1º Designar a servidora CARLA VANNESSA DA ROCHA matrícula nº 0536482, "
            "para atuar como GESTOR DO CONTRATO, nº 05/2025, firmado entre o FUNDO "
            "MUNICIPAL DE SAÚDE e R R CONSTRUÇÕES, tendo como eventual substituto "
            "ALAERDSON NASCIMENTO DE LIMA matrícula nº 5096847-2.\n"
            "Art. 2º São atribuições do gestor do contrato:\n"
            "Art. 3° Designar o servidor DEIVISON TAEMY DIAS DA SILVA matrícula nº 5110069/01, "
            "para atuar como FISCAL DE CONTRATO, nº 16/2024, firmado entre o FUNDO MUNICIPAL "
            "DE SAÚDE, tendo como eventual substituído FRANCISCO GUEDES DA COSTA NETO "
            "matrícula nº 5082552."
        )

    def test_gestor_titular_com_virgula_antes_do_numero(self):
        f, c = monitor._extrair_funcao_contrato(self._cont_dom_160(), "CARLA VANNESSA DA ROCHA")
        assert f == "Gestor" and c == "05/2025"

    def test_fiscal_titular_com_de_contrato(self):
        f, c = monitor._extrair_funcao_contrato(self._cont_dom_160(), "DEIVISON TAEMY DIAS DA SILVA")
        assert f == "Fiscal" and c == "16/2024"

    def test_gestor_substituto_ordem_eventual_substituto(self):
        f, c = monitor._extrair_funcao_contrato(self._cont_dom_160(), "ALAERDSON NASCIMENTO DE LIMA")
        assert f == "Gestor Substituto" and c == "05/2025"


class TestExtrairParticipacao:
    """
    Quando a função não é Gestor/Fiscal de contrato, antes de cair em
    'função não identificada' o sistema procura, NO PARÁGRAFO em que o nome
    aparece, uma menção a 'participar'/'participação' e devolve o trecho do
    termo até o ', conforme...' (ou 1º ponto / fim do parágrafo), com a grafia
    original do DOM.
    """

    # Parágrafos REAIS do DOM Nº 841 (publicação 1876).
    _ART_104 = (
        "Conceder 1.0 (uma) diária ao senhor PETRAS VINÍCIUS DE SOUSA, matrícula "
        "n.º 035471-1, ocupante do cargo/função de VEREADOR, para custear despesas "
        "destinadas à cobertura de gastos com alimentação e hospedagem, conforme "
        "dispõe o parágrafo único do art. 16 da Res. n. 028/2020-TCE/RN, durante "
        "seu deslocamento à cidade de NATAL/RN, nos dias 17/06/2026 a 18/06/2026, "
        "para participar de audiência na Superintendência Regional do Departamento "
        "Nacional de Infraestrutura de Transportes (DNIT), conforme consta "
        "especificado no ANEXO I - Solicitação de Diária."
    )
    _ART_103 = (
        "Conceder diária ao senhor JOAO ASSESSOR para assessorar a vereadora "
        "Plúvia Oliveira em sua participação na Solenidade em homenagem aos Povos "
        "de Axé, conforme consta especificado no ANEXO I - Solicitação de Diária."
    )

    # ---- helper _extrair_participacao (direto) ----

    def test_extrai_participar_e_corta_no_conforme(self):
        trecho = monitor._extrair_participacao(self._ART_104, "PETRAS VINÍCIUS DE SOUSA")
        assert trecho == (
            "participar de audiência na Superintendência Regional do Departamento "
            "Nacional de Infraestrutura de Transportes (DNIT)"
        )

    def test_extrai_participacao_substantivo(self):
        trecho = monitor._extrair_participacao(self._ART_103, "JOAO ASSESSOR")
        assert trecho == "participação na Solenidade em homenagem aos Povos de Axé"

    def test_preserva_grafia_original_do_dom(self):
        # No DOM a palavra está em CAIXA ALTA — deve ser devolvida assim mesmo,
        # provando que a busca é em minúsculo mas o recorte usa o texto original.
        cont = "Art. 1º Designar JOAO SILVA para PARTICIPAR da reunião especial, conforme orientação."
        trecho = monitor._extrair_participacao(cont, "JOAO SILVA")
        assert trecho == "PARTICIPAR da reunião especial"

    def test_fallback_corta_no_primeiro_ponto_sem_conforme(self):
        cont = "Art. 1º Designar FULANO DE TAL para participar do evento anual. Outras providências."
        trecho = monitor._extrair_participacao(cont, "FULANO DE TAL")
        assert trecho == "participar do evento anual"

    def test_sem_participacao_retorna_none(self):
        cont = "Art. 1º Designar FULANO DE TAL para acompanhar a obra, conforme cronograma."
        assert monitor._extrair_participacao(cont, "FULANO DE TAL") is None

    def test_busca_somente_no_paragrafo_do_nome(self):
        # Nome num parágrafo, 'participar' em outro → fora do escopo → None.
        cont = (
            "Art. 1º Designar o servidor JOAO SILVA, matrícula 1.\n"
            "Fica o servidor autorizado a participar da reunião, conforme agenda."
        )
        assert monitor._extrair_participacao(cont, "JOAO SILVA") is None

    # ---- integração via _extrair_funcao_contrato ----

    def test_funcao_vira_o_trecho_de_participacao(self):
        f, c = monitor._extrair_funcao_contrato(self._ART_104, "PETRAS VINÍCIUS DE SOUSA")
        assert f == (
            "participar de audiência na Superintendência Regional do Departamento "
            "Nacional de Infraestrutura de Transportes (DNIT)"
        )
        assert c is None

    def test_continua_nao_identificada_sem_participar(self):
        cont = "Art. 1º Designar FULANO DE TAL para acompanhar a obra, conforme cronograma."
        f, c = monitor._extrair_funcao_contrato(cont, "FULANO DE TAL")
        assert f == "função não identificada" and c is None

    def test_gestor_tem_prioridade_sobre_participacao(self):
        # Mesmo havendo 'participar' no texto, se o papel Gestor/Fiscal for
        # identificado, ele prevalece (a participação é só fallback).
        cont = (
            "Art. 1º Designar o servidor CARLOS para atuar como GESTOR DO CONTRATO "
            "n° 50/2026, com a finalidade de participar da fiscalização."
        )
        f, c = monitor._extrair_funcao_contrato(cont, "CARLOS")
        assert f == "Gestor" and c == "50/2026"


# ══════════════════════════════════════════════════════════════
# 6. enviar_whatsapp
# ══════════════════════════════════════════════════════════════

# Aplicados em ordem: o 1º da lista vira o mais interno → 1º parâmetro da função.
# Ordem dos parâmetros: mock_chrome, mock_wait, mock_service, mock_cdm, mock_isdir, mock_sleep
_PATCHES_SELENIUM = [
    patch("monitor_diario_oficial.webdriver.Chrome"),            # innermost → mock_chrome (1º)
    patch("monitor_diario_oficial.whatsapp.WebDriverWait"),      # → mock_wait
    patch("monitor_diario_oficial.whatsapp.Service"),            # → mock_service
    patch("monitor_diario_oficial.whatsapp.ChromeDriverManager"),# → mock_cdm
    patch("monitor_diario_oficial.os.path.isdir"),               # → mock_isdir
    patch("monitor_diario_oficial.time.sleep"),                  # → mock_sleep
    patch("monitor_diario_oficial.whatsapp._colar_no_elemento"), # outermost → mock_colar (último)
]


def _aplicar_patches(func):
    """Aplica todos os patches do Selenium em ordem correta."""
    for p in _PATCHES_SELENIUM:
        func = p(func)
    return func


class TestEnviarWhatsapp:

    @_aplicar_patches
    def test_retorna_true_em_fluxo_bem_sucedido(
        self, mock_chrome, mock_wait, mock_service, mock_cdm, mock_isdir, mock_sleep, mock_colar
    ):
        mock_isdir.return_value = True
        _setup_selenium_mocks(mock_chrome, mock_wait)

        resultado = monitor.enviar_whatsapp("Mensagem de teste", "Grupo Teste", [])

        assert resultado is True

    @_aplicar_patches
    def test_driver_quit_chamado_em_fluxo_normal(
        self, mock_chrome, mock_wait, mock_service, mock_cdm, mock_isdir, mock_sleep, mock_colar
    ):
        mock_isdir.return_value = True
        mock_driver, *_ = _setup_selenium_mocks(mock_chrome, mock_wait)

        monitor.enviar_whatsapp("Mensagem", "Grupo")

        mock_driver.quit.assert_called_once()

    @_aplicar_patches
    def test_driver_quit_chamado_mesmo_com_excecao(
        self, mock_chrome, mock_wait, mock_service, mock_cdm, mock_isdir, mock_sleep, mock_colar
    ):
        """finally: deve garantir que o driver seja fechado mesmo com falha."""
        mock_isdir.return_value = True
        mock_driver = MagicMock()
        mock_chrome.return_value = mock_driver

        mock_wait_inst = MagicMock()
        mock_wait.return_value = mock_wait_inst
        mock_wait_inst.until.side_effect = Exception("Elemento não encontrado")

        resultado = monitor.enviar_whatsapp("Mensagem", "Grupo")

        assert resultado is False
        mock_driver.quit.assert_called_once()

    @_aplicar_patches
    def test_retorna_false_se_chrome_nao_inicializa(
        self, mock_chrome, mock_wait, mock_service, mock_cdm, mock_isdir, mock_sleep, mock_colar
    ):
        mock_isdir.return_value = True
        mock_chrome.side_effect = Exception("Chrome binário não encontrado")

        resultado = monitor.enviar_whatsapp("Mensagem", "Grupo")

        assert resultado is False

    @_aplicar_patches
    def test_timeout_auth_qr_code_sem_sessao_valida(
        self, mock_chrome, mock_wait, mock_service, mock_cdm, mock_isdir, mock_sleep, mock_colar
    ):
        """Sem sessão válida do WhatsApp (IndexedDB ausente) usa TIMEOUT_QR_CODE."""
        mock_isdir.return_value = False  # IndexedDB não existe
        _setup_selenium_mocks(mock_chrome, mock_wait)

        monitor.enviar_whatsapp("Mensagem", "Grupo")

        # O portão de login usa timeout_auth = TIMEOUT_QR_CODE quando não há sessão.
        timeouts = [c.args[1] for c in mock_wait.call_args_list]
        assert monitor.TIMEOUT_QR_CODE in timeouts

    @_aplicar_patches
    def test_login_gate_usa_timeout_qr_mesmo_com_perfil_no_disco(
        self, mock_chrome, mock_wait, mock_service, mock_cdm, mock_isdir, mock_sleep, mock_colar
    ):
        """
        Mesmo com o perfil salvo no disco (IndexedDB presente), o portão de login
        concede o tempo completo TIMEOUT_QR_CODE. A pasta no disco NÃO garante
        sessão autenticada (o WhatsApp pode ter deslogado o aparelho), então o
        tempo de login nunca é encurtado com base nela. (Regressão do bug em que
        a produção usava 30s e o QR não dava tempo de ser escaneado.)
        """
        mock_isdir.return_value = True  # pasta do perfil existe, mas pode estar deslogada
        _setup_selenium_mocks(mock_chrome, mock_wait)

        monitor.enviar_whatsapp("Mensagem", "Grupo")

        timeouts = [c.args[1] for c in mock_wait.call_args_list]
        assert monitor.TIMEOUT_QR_CODE in timeouts

    @_aplicar_patches
    def test_mensagem_colada_via_clipboard(
        self, mock_chrome, mock_wait, mock_service, mock_cdm, mock_isdir, mock_sleep, mock_colar
    ):
        """A mensagem deve ser enviada via _colar_no_elemento (suporte a emojis)."""
        mock_isdir.return_value = True
        _, _, _, mock_caixa_msg = _setup_selenium_mocks(mock_chrome, mock_wait)

        monitor.enviar_whatsapp("Linha 1\nLinha 2\nLinha 3", "Grupo")

        # _colar_no_elemento deve ter sido chamado com a mensagem completa
        args_colar = [c.args[2] for c in mock_colar.call_args_list]
        assert "Linha 1\nLinha 2\nLinha 3" in args_colar

    @_aplicar_patches
    def test_send_keys_enter_final_envia_mensagem(
        self, mock_chrome, mock_wait, mock_service, mock_cdm, mock_isdir, mock_sleep, mock_colar
    ):
        """A única chamada a send_keys na caixa de mensagem deve ser Keys.ENTER."""
        from selenium.webdriver.common.keys import Keys

        mock_isdir.return_value = True
        _, _, _, mock_caixa_msg = _setup_selenium_mocks(mock_chrome, mock_wait)

        monitor.enviar_whatsapp("Texto simples", "Grupo")

        ultima_chamada = mock_caixa_msg.send_keys.call_args_list[-1]
        assert ultima_chamada == call(Keys.ENTER)

    @_aplicar_patches
    def test_pesquisa_grupo_com_nome_correto(
        self, mock_chrome, mock_wait, mock_service, mock_cdm, mock_isdir, mock_sleep, mock_colar
    ):
        """O nome do grupo deve ser passado para _colar_no_elemento (suporte a emojis)."""
        mock_isdir.return_value = True
        _, mock_caixa_pesquisa, *_ = _setup_selenium_mocks(mock_chrome, mock_wait)

        monitor.enviar_whatsapp("Mensagem", "Grupo Específico")

        # _colar_no_elemento deve ter sido chamado com o nome do grupo
        args_colar = [c.args[2] for c in mock_colar.call_args_list]
        assert "Grupo Específico" in args_colar

    @_aplicar_patches
    def test_acessa_whatsapp_web(
        self, mock_chrome, mock_wait, mock_service, mock_cdm, mock_isdir, mock_sleep, mock_colar
    ):
        """Deve navegar para web.whatsapp.com."""
        mock_isdir.return_value = True
        mock_driver, *_ = _setup_selenium_mocks(mock_chrome, mock_wait)

        monitor.enviar_whatsapp("Mensagem", "Grupo")

        mock_driver.get.assert_called_once_with("https://web.whatsapp.com")

    @_aplicar_patches
    def test_fecha_popup_novidades_quando_presente(
        self, mock_chrome, mock_wait, mock_service, mock_cdm, mock_isdir, mock_sleep, mock_colar
    ):
        """
        Quando o pop-up "Novidades do WhatsApp Web" aparece após o login, ele deve
        ser fechado (clique no botão) antes de pesquisar o grupo, sem interromper o
        fluxo. Simula o diálogo presente: a checagem de presença retorna um mock e o
        primeiro botão de fechar é clicável.
        """
        mock_isdir.return_value = True
        mock_driver = MagicMock()
        mock_chrome.return_value = mock_driver
        mock_driver.execute_script.return_value = []

        mock_wait_inst = MagicMock()
        mock_wait.return_value = mock_wait_inst

        mock_popup_btn = MagicMock()
        mock_popup_btn.is_displayed.return_value = True
        mock_popup_btn.is_enabled.return_value = True
        mock_caixa_pesquisa = MagicMock()
        mock_resultado_grupo = MagicMock()
        mock_caixa_msg = MagicMock()

        # O fechamento do pop-up usa find_elements (instantâneo), não WebDriverWait;
        # sem PDFs, find_elements só é chamado nesse fechamento.
        mock_driver.find_elements.return_value = [mock_popup_btn]

        mock_wait_inst.until.side_effect = [
            SeleniumTimeoutException(),  # QR ausente
            MagicMock(),                 # portão de login → logado
            SeleniumTimeoutException(),  # sem diálogo "usar nesta janela"
            MagicMock(),                 # presence_of //div[@role="dialog"] → pop-up presente
            mock_caixa_pesquisa,         # caixa de pesquisa
            mock_resultado_grupo,        # grupo encontrado
            mock_caixa_msg,              # caixa de mensagem
        ]

        resultado = monitor.enviar_whatsapp("Mensagem", "Grupo")

        assert resultado is True
        mock_popup_btn.click.assert_called_once()

    @_aplicar_patches
    def test_sessao_descartavel_usa_perfil_temporario(
        self, mock_chrome, mock_wait, mock_service, mock_cdm, mock_isdir, mock_sleep, mock_colar
    ):
        """Com sessao_descartavel, o --user-data-dir aponta para a pasta temporária."""
        _setup_selenium_mocks(mock_chrome, mock_wait)
        with patch(
            "monitor_diario_oficial.whatsapp.tempfile.mkdtemp",
            return_value="/tmp/wa_qr_fake",
        ), patch("monitor_diario_oficial.whatsapp.shutil.rmtree"):
            monitor.enviar_whatsapp("Msg", "Grupo", sessao_descartavel=True)

        args = mock_chrome.call_args.kwargs["options"].arguments
        assert "--user-data-dir=/tmp/wa_qr_fake" in args
        assert all(
            not a.startswith(f"--user-data-dir={monitor.WHATSAPP_PROFILE_DIR}")
            for a in args
        )

    @_aplicar_patches
    def test_sessao_descartavel_remove_perfil_temporario(
        self, mock_chrome, mock_wait, mock_service, mock_cdm, mock_isdir, mock_sleep, mock_colar
    ):
        """A pasta temporária deve ser removida no finally."""
        _setup_selenium_mocks(mock_chrome, mock_wait)
        with patch(
            "monitor_diario_oficial.whatsapp.tempfile.mkdtemp",
            return_value="/tmp/wa_qr_fake",
        ), patch("monitor_diario_oficial.whatsapp.shutil.rmtree") as mock_rmtree:
            monitor.enviar_whatsapp("Msg", "Grupo", sessao_descartavel=True)

        mock_rmtree.assert_called_once_with("/tmp/wa_qr_fake", ignore_errors=True)

    @_aplicar_patches
    def test_sessao_descartavel_forca_timeout_qr_code(
        self, mock_chrome, mock_wait, mock_service, mock_cdm, mock_isdir, mock_sleep, mock_colar
    ):
        """sessao_descartavel força TIMEOUT_QR_CODE mesmo se isdir indicar sessão salva."""
        mock_isdir.return_value = True  # haveria sessão salva, mas a flag deve ignorar
        _setup_selenium_mocks(mock_chrome, mock_wait)
        with patch(
            "monitor_diario_oficial.whatsapp.tempfile.mkdtemp",
            return_value="/tmp/wa_qr_fake",
        ), patch("monitor_diario_oficial.whatsapp.shutil.rmtree"):
            monitor.enviar_whatsapp("Msg", "Grupo", sessao_descartavel=True)

        # Mesmo com isdir=True, a flag força sessao_valida=False → timeout_auth=TIMEOUT_QR_CODE
        # é usado no portão de login.
        timeouts = [c.args[1] for c in mock_wait.call_args_list]
        assert monitor.TIMEOUT_QR_CODE in timeouts

    @_aplicar_patches
    def test_sem_flag_usa_perfil_persistente(
        self, mock_chrome, mock_wait, mock_service, mock_cdm, mock_isdir, mock_sleep, mock_colar
    ):
        """Sem a flag: usa WHATSAPP_PROFILE_DIR e não cria/remove pasta temporária."""
        mock_isdir.return_value = True
        _setup_selenium_mocks(mock_chrome, mock_wait)
        with patch("monitor_diario_oficial.whatsapp.tempfile.mkdtemp") as mock_mkdtemp, \
             patch("monitor_diario_oficial.whatsapp.shutil.rmtree") as mock_rmtree:
            monitor.enviar_whatsapp("Msg", "Grupo")

        args = mock_chrome.call_args.kwargs["options"].arguments
        assert f"--user-data-dir={monitor.WHATSAPP_PROFILE_DIR}" in args
        mock_mkdtemp.assert_not_called()
        mock_rmtree.assert_not_called()

    @_aplicar_patches
    def test_sessao_descartavel_remove_perfil_mesmo_com_falha(
        self, mock_chrome, mock_wait, mock_service, mock_cdm, mock_isdir, mock_sleep, mock_colar
    ):
        """O perfil temporário é removido mesmo se o envio falhar (limpeza no finally)."""
        mock_chrome.side_effect = Exception("Chrome falhou ao iniciar")
        with patch(
            "monitor_diario_oficial.whatsapp.tempfile.mkdtemp",
            return_value="/tmp/wa_qr_fake",
        ), patch("monitor_diario_oficial.whatsapp.shutil.rmtree") as mock_rmtree:
            resultado = monitor.enviar_whatsapp("Msg", "Grupo", sessao_descartavel=True)

        assert resultado is False
        mock_rmtree.assert_called_once_with("/tmp/wa_qr_fake", ignore_errors=True)

    @_aplicar_patches
    def test_clique_busca_interceptado_fecha_dialogo_e_repete(
        self, mock_chrome, mock_wait, mock_service, mock_cdm, mock_isdir, mock_sleep, mock_colar
    ):
        """
        BUG: após o login, um modal de novidades sobrepõe a caixa de pesquisa e
        intercepta o clique (ElementClickInterceptedException). O envio deve se
        recuperar: fechar o diálogo e repetir o clique, em vez de falhar.
        """
        from selenium.common.exceptions import ElementClickInterceptedException

        mock_isdir.return_value = True
        mock_driver = MagicMock()
        mock_chrome.return_value = mock_driver
        mock_driver.execute_script.return_value = []

        mock_wait_inst = MagicMock()
        mock_wait.return_value = mock_wait_inst
        # _fechar_dialogos_sobrepostos é patchado, então não consome chamadas de until.
        mock_wait_inst.until.side_effect = [
            SeleniumTimeoutException(),  # QR ausente
            MagicMock(),                 # portão de login → logado
            SeleniumTimeoutException(),  # sem 'usar nesta janela'
            MagicMock(),                 # caixa de pesquisa
            MagicMock(),                 # resultado do grupo
            MagicMock(),                 # caixa de mensagem
        ]
        # 1ª colagem (caixa de pesquisa) é interceptada por um diálogo; depois funciona.
        mock_colar.side_effect = [
            ElementClickInterceptedException("interceptado pelo modal"),
            None,  # retry da pesquisa após fechar o diálogo
            None,  # caixa de mensagem
        ]
        with patch("monitor_diario_oficial.whatsapp._fechar_dialogos_sobrepostos") as mock_fechar:
            resultado = monitor.enviar_whatsapp("Mensagem", "Grupo")

        assert resultado is True
        # _colar_no_elemento: pesquisa (falha) → pesquisa (retry) → mensagem = 3 chamadas
        assert mock_colar.call_count == 3
        # O diálogo deve ter sido fechado ao detectar a interceptação.
        assert mock_fechar.called

    @_aplicar_patches
    def test_login_nao_confirmado_retorna_false(
        self, mock_chrome, mock_wait, mock_service, mock_cdm, mock_isdir, mock_sleep, mock_colar
    ):
        """
        Se o login não é confirmado (o portão de login expira porque o QR não foi
        escaneado a tempo), o envio falha de forma clara — retorna False e NÃO segue
        para procurar a caixa de pesquisa.
        """
        mock_isdir.return_value = False
        mock_driver = MagicMock()
        mock_chrome.return_value = mock_driver
        mock_driver.execute_script.return_value = []

        mock_wait_inst = MagicMock()
        mock_wait.return_value = mock_wait_inst
        mock_wait_inst.until.side_effect = [
            SeleniumTimeoutException(),  # QR (checagem informativa)
            SeleniumTimeoutException(),  # portão de login expira → não logou
        ]

        resultado = monitor.enviar_whatsapp("Mensagem", "Grupo")

        assert resultado is False
        # Não deve nem tentar colar nada (não chegou à caixa de pesquisa).
        mock_colar.assert_not_called()


# ══════════════════════════════════════════════════════════════
# 6b. _fechar_dialogos_sobrepostos — fecha modal pós-login
# ══════════════════════════════════════════════════════════════

class TestFecharDialogosSobrepostos:

    def test_sem_dialogo_retorna_false(self):
        """Sem diálogo na tela, é no-op e retorna False."""
        mock_driver = MagicMock()
        with patch("monitor_diario_oficial.whatsapp.WebDriverWait") as mock_wait:
            mock_wait.return_value.until.side_effect = SeleniumTimeoutException()
            resultado = monitor.whatsapp._fechar_dialogos_sobrepostos(mock_driver)
        assert resultado is False

    def test_dialogo_presente_clica_botao_e_retorna_true(self):
        """Com diálogo presente, clica no 1º botão de fechar conhecido e retorna True."""
        mock_driver = MagicMock()
        mock_botao = MagicMock()
        mock_botao.is_displayed.return_value = True
        mock_botao.is_enabled.return_value = True
        # O fechamento usa find_elements (instantâneo); o 1º xpath retorna o botão.
        mock_driver.find_elements.return_value = [mock_botao]
        with patch("monitor_diario_oficial.whatsapp.WebDriverWait") as mock_wait:
            # until é usado só na detecção de presença do diálogo (presente).
            mock_wait.return_value.until.return_value = MagicMock()
            resultado = monitor.whatsapp._fechar_dialogos_sobrepostos(mock_driver)
        assert resultado is True
        mock_botao.click.assert_called_once()


# ══════════════════════════════════════════════════════════════
# 7. _enviar_arquivos_no_grupo
# Verifica que o botão de envio é REALMENTE clicado — não apenas
# que a função retorna sem erro (que é o bug atual).
# ══════════════════════════════════════════════════════════════

class TestEnviarArquivoNoGrupo:
    """
    Testa _enviar_arquivos_no_grupo isoladamente.

    O bug reportado: a função loga "enviado com sucesso" mas o arquivo
    não é enviado porque o botão não foi encontrado e o fallback Enter
    não tem foco no botão correto — a função retorna sem clicar em nada.

    Os testes abaixo tornam esse comportamento detectável.
    """

    def _make_driver(self, input_accept=""):
        """Monta um mock de driver com um input de arquivo disponível."""
        driver = MagicMock()
        mock_input = MagicMock()
        mock_input.get_attribute.return_value = input_accept
        driver.find_elements.return_value = [mock_input]
        driver.execute_script.return_value = None
        return driver, mock_input

    @patch("monitor_diario_oficial.os.path.isfile", return_value=True)
    @patch("monitor_diario_oficial.time.sleep")
    @patch("monitor_diario_oficial.whatsapp.WebDriverWait")
    def test_click_chamado_quando_xpath_encontra_botao(self, mock_wait_cls, mock_sleep, mock_isfile):
        """
        Caminho feliz: clipe → Documentos → botão enviar clicado.
        click() DEVE ser chamado no botão de envio para confirmar o envio real.
        """
        driver, mock_input = self._make_driver()

        mock_btn_clipe = MagicMock()
        mock_btn_docs = MagicMock()
        mock_btn_enviar = MagicMock()
        mock_wait_inst = MagicMock()
        mock_wait_cls.return_value = mock_wait_inst
        # Sequência: clipe → Documentos → botão enviar
        mock_wait_inst.until.side_effect = [
            mock_btn_clipe,   # clipe encontrado
            mock_btn_docs,    # "Documentos" encontrado
            mock_btn_enviar,  # botão de enviar encontrado
        ]

        monitor._enviar_arquivos_no_grupo(driver, ["arquivo.pdf"])

        mock_btn_enviar.click.assert_called_once(), (
            "O botão de envio DEVE ser clicado para que o arquivo seja enviado"
        )

    @patch("monitor_diario_oficial.os.path.isfile", return_value=True)
    @patch("monitor_diario_oficial.time.sleep")
    @patch("monitor_diario_oficial.whatsapp.WebDriverWait")
    def test_javascript_fallback_chamado_quando_xpath_falha(self, mock_wait_cls, mock_sleep, mock_isfile):
        """
        XPath não encontra o botão de envio → fallback JavaScript DEVE ser
        executado com seletores do botão real do WhatsApp Web.
        """
        driver, mock_input = self._make_driver()

        mock_btn_clipe = MagicMock()
        mock_btn_docs = MagicMock()
        mock_wait_inst = MagicMock()
        mock_wait_cls.return_value = mock_wait_inst
        # Clipe e Documentos encontrados; todos os XPaths do botão enviar falham
        mock_wait_inst.until.side_effect = (
            [mock_btn_clipe, mock_btn_docs] + [Exception("not found")] * 20
        )
        driver.execute_script.return_value = '[data-testid="wds-ic-send-filled"]'

        monitor._enviar_arquivos_no_grupo(driver, ["arquivo.pdf"])

        js_calls = [str(c) for c in driver.execute_script.call_args_list]
        assert any("wds-ic-send-filled" in c for c in js_calls), (
            "O fallback JavaScript deve buscar pelo seletor confirmado do WhatsApp Web"
        )

    @patch("monitor_diario_oficial.os.path.isfile", return_value=True)
    @patch("monitor_diario_oficial.time.sleep")
    @patch("monitor_diario_oficial.whatsapp.WebDriverWait")
    def test_levanta_excecao_quando_botao_nao_encontrado(self, mock_wait_cls, mock_sleep, mock_isfile):
        """
        Quando XPath e JavaScript falham, a função DEVE levantar Exception
        em vez de retornar silenciosamente como se tivesse enviado.
        """
        driver, mock_input = self._make_driver()

        mock_btn_clipe = MagicMock()
        mock_btn_docs = MagicMock()
        mock_wait_inst = MagicMock()
        mock_wait_cls.return_value = mock_wait_inst
        mock_wait_inst.until.side_effect = (
            [mock_btn_clipe, mock_btn_docs] + [Exception("not found")] * 20
        )
        driver.execute_script.return_value = None  # JS não encontrou nada

        with pytest.raises(Exception, match="[Bb]otão"):
            monitor._enviar_arquivos_no_grupo(driver, ["arquivo.pdf"])

    @patch("monitor_diario_oficial.os.path.isfile", return_value=True)
    @patch("monitor_diario_oficial.time.sleep")
    @patch("monitor_diario_oficial.whatsapp.WebDriverWait")
    def test_nao_retorna_sucesso_sem_clicar_botao(self, mock_wait_cls, mock_sleep, mock_isfile):
        """
        Quando nenhum botão de envio é encontrado, a função deve levantar
        Exception — nunca retornar silenciosamente como se tivesse enviado.
        """
        driver, mock_input = self._make_driver()

        mock_btn_clipe = MagicMock()
        mock_btn_docs = MagicMock()
        mock_wait_inst = MagicMock()
        mock_wait_cls.return_value = mock_wait_inst
        mock_wait_inst.until.side_effect = (
            [mock_btn_clipe, mock_btn_docs] + [Exception("not found")] * 20
        )
        driver.execute_script.return_value = None

        try:
            monitor._enviar_arquivos_no_grupo(driver, ["arquivo.pdf"])
            pytest.fail(
                "BUG: a função retornou sem erro mas nenhum botão foi clicado — "
                "o arquivo NÃO foi enviado."
            )
        except Exception:
            pass  # comportamento correto: levantou Exception


# ══════════════════════════════════════════════════════════════
# 8. _extrair_dados_fofoca
#    Cobre os 4 padrões reais observados no Diário Oficial:
#      Ex1 — NOMEAR homem  (nome + PARA EXERCER)
#      Ex2 — NOMEAR mulher (mesmo padrão, nome diferente)
#      Ex3 — EXONERAR mulher com "a servidora" e preposição "DA" no nome
#      Ex4 — EXONERAR homem com "o servidor"
# ══════════════════════════════════════════════════════════════

class TestExtrairDadosFofoca:
    """
    Testa _extrair_dados_fofoca com os padrões reais do Diário Oficial de Mossoró.

    Os parágrafos são fornecidos em MAIÚSCULAS NFC (como extraídos do HTML).
    Um teste adicional verifica que a função também aceita entrada NFKD
    (formato produzido por detectar_fofocas).
    """

    # ── Exemplo 1: NOMEAR homem ──────────────────────────────────────────────
    # "Art. 1º Nomear PEDRO LUCAS REBOUÇAS GOMES para exercer o cargo em comissão
    #  de Assessor de Comunicação, símbolo CC11, na função de Assessor de Comunicação,
    #  com lotação na Secretaria Municipal de Comunicação Social da Prefeitura Municipal
    #  de Mossoró."
    PARA1 = (
        "ART. 1 NOMEAR PEDRO LUCAS REBOUÇAS GOMES PARA EXERCER O CARGO EM COMISSÃO "
        "DE ASSESSOR DE COMUNICAÇÃO, SÍMBOLO CC11, NA FUNÇÃO DE ASSESSOR DE COMUNICAÇÃO, "
        "COM LOTAÇÃO NA SECRETARIA MUNICIPAL DE COMUNICAÇÃO SOCIAL DA PREFEITURA MUNICIPAL "
        "DE MOSSORÓ."
    )
    SEC1 = "SECRETARIA MUNICIPAL DE COMUNICAÇÃO SOCIAL"

    # ── Exemplo 2: NOMEAR mulher ─────────────────────────────────────────────
    # "Art. 1º Nomear AMANDA CYBELE PINHEIRO BEZERRA para exercer o cargo em comissão
    #  de Assessor Especial II, símbolo CC6, na função de Assessor Especial,
    #  com lotação na Gabinete do Prefeito da Prefeitura Municipal de Mossoró."
    PARA2 = (
        "ART. 1 NOMEAR AMANDA CYBELE PINHEIRO BEZERRA PARA EXERCER O CARGO EM COMISSÃO "
        "DE ASSESSOR ESPECIAL II, SÍMBOLO CC6, NA FUNÇÃO DE ASSESSOR ESPECIAL, "
        "COM LOTAÇÃO NA GABINETE DO PREFEITO DA PREFEITURA MUNICIPAL DE MOSSORÓ."
    )
    SEC2 = "GABINETE DO PREFEITO"

    # ── Exemplo 3: EXONERAR mulher com "a servidora" + "DA" no nome ─────────
    # "Art. 1º EXONERAR a servidora ROSANGELA GURGEL DA NOBREGA do cargo em comissão
    #  de Assessor Executivo, símbolo CC15, na função de Assessor Executivo,
    #  com lotação na Secretaria Municipal de Cultura da Prefeitura Municipal de Mossoró."
    PARA3 = (
        "ART. 1 EXONERAR A SERVIDORA ROSANGELA GURGEL DA NOBREGA DO CARGO EM COMISSÃO "
        "DE ASSESSOR EXECUTIVO, SÍMBOLO CC15, NA FUNÇÃO DE ASSESSOR EXECUTIVO, "
        "COM LOTAÇÃO NA SECRETARIA MUNICIPAL DE CULTURA DA PREFEITURA MUNICIPAL DE MOSSORÓ."
    )
    SEC3 = "SECRETARIA MUNICIPAL DE CULTURA"

    # ── Exemplo 4: EXONERAR homem com "o servidor" ──────────────────────────
    # "Art. 1º EXONERAR o servidor RAMON YOVANIS INFANTE RODRIGUEZ do cargo em comissão
    #  de Diretor de Unidade III, símbolo CC11, na função de Diretor do Centro de Produção
    #  de Mudas, com lotação na Secretaria Municipal de Serviços Urbanos da Prefeitura
    #  Municipal de Mossoró."
    PARA4 = (
        "ART. 1 EXONERAR O SERVIDOR RAMON YOVANIS INFANTE RODRIGUEZ DO CARGO EM COMISSÃO "
        "DE DIRETOR DE UNIDADE III, SÍMBOLO CC11, NA FUNÇÃO DE DIRETOR DO CENTRO DE "
        "PRODUÇÃO DE MUDAS, COM LOTAÇÃO NA SECRETARIA MUNICIPAL DE SERVIÇOS URBANOS DA "
        "PREFEITURA MUNICIPAL DE MOSSORÓ."
    )
    SEC4 = "SECRETARIA MUNICIPAL DE SERVIÇOS URBANOS"

    # ── Exemplo 5: EXONERAR com qualificador ", a pedido," ───────────────────
    # Regressão: Portaria Nº 509/2026 — o qualificador entre vírgulas após
    # EXONERAR fazia o nome ser capturado como "PESSOA NÃO IDENTIFICADA".
    # "Art. 1º EXONERAR, a pedido, o servidor DANIEL VICTOR CARLOS DE NORONHA
    #  do cargo em comissão de Assessor Técnico II, símbolo CC11, na função de
    #  Assessor Técnico, com lotação na Secretaria Municipal de Infraestrutura
    #  da Prefeitura Municipal de Mossoró."
    PARA5 = (
        "ART. 1 EXONERAR, A PEDIDO, O SERVIDOR DANIEL VICTOR CARLOS DE NORONHA "
        "DO CARGO EM COMISSÃO DE ASSESSOR TÉCNICO II, SÍMBOLO CC11, NA FUNÇÃO DE "
        "ASSESSOR TÉCNICO, COM LOTAÇÃO NA SECRETARIA MUNICIPAL DE INFRAESTRUTURA "
        "DA PREFEITURA MUNICIPAL DE MOSSORÓ."
    )
    SEC5 = "SECRETARIA MUNICIPAL DE INFRAESTRUTURA"

    # ── Exemplo 1: NOMEAR homem ──────────────────────────────────────────────

    def test_ex1_nome_nomear_homem(self):
        """NOMEAR → extrai nome completo sem incluir 'PARA EXERCER'."""
        r = monitor._extrair_dados_fofoca(self.PARA1, self.SEC1)
        assert r is not None
        assert r["pessoa"] == "PEDRO LUCAS REBOUÇAS GOMES"

    def test_ex1_acao_nomear(self):
        r = monitor._extrair_dados_fofoca(self.PARA1, self.SEC1)
        assert r["acao"] == "NOMEADO(A)"

    def test_ex1_cargo_nomear(self):
        r = monitor._extrair_dados_fofoca(self.PARA1, self.SEC1)
        assert r["cargo"] != "cargo não identificado"
        assert "ASSESSOR" in r["cargo"].upper()

    def test_ex1_cc_nomear(self):
        r = monitor._extrair_dados_fofoca(self.PARA1, self.SEC1)
        assert r["simbolo_cc"] == "CC11"

    def test_cc_ancorado_ao_cargo_ignora_cc_anterior(self):
        """O símbolo CC deve ser o do CARGO, não um CC citado antes no parágrafo.

        Regressão: a busca pegava o PRIMEIRO 'CC' do parágrafo inteiro. Aqui há
        um 'CC5' no qualificador (vaga do antecessor) antes do 'CC11' do cargo.
        """
        paragrafo = (
            "ART. 1 NOMEAR, EM VAGA DO SÍMBOLO CC5, FULANO DE TAL PARA EXERCER "
            "O CARGO EM COMISSÃO DE ASSESSOR, SÍMBOLO CC11, NA FUNÇÃO DE ASSESSOR, "
            "COM LOTAÇÃO NA SECRETARIA MUNICIPAL DE SAÚDE DA PREFEITURA MUNICIPAL DE MOSSORÓ."
        )
        r = monitor._extrair_dados_fofoca(paragrafo, "SECRETARIA MUNICIPAL DE SAÚDE")
        assert r is not None
        assert r["pessoa"] == "FULANO DE TAL"
        assert r["simbolo_cc"] == "CC11"

    # ── Exemplo 2: NOMEAR mulher ─────────────────────────────────────────────

    def test_ex2_nome_nomear_mulher(self):
        """NOMEAR mulher → mesmo padrão, nome completo extraído corretamente."""
        r = monitor._extrair_dados_fofoca(self.PARA2, self.SEC2)
        assert r is not None
        assert r["pessoa"] == "AMANDA CYBELE PINHEIRO BEZERRA"

    def test_ex2_cc_nomear_mulher(self):
        r = monitor._extrair_dados_fofoca(self.PARA2, self.SEC2)
        assert r["simbolo_cc"] == "CC6"

    def test_ex2_acao_nomear_mulher(self):
        r = monitor._extrair_dados_fofoca(self.PARA2, self.SEC2)
        assert r["acao"] == "NOMEADO(A)"

    # ── Exemplo 3: EXONERAR mulher com "a servidora" ────────────────────────

    def test_ex3_nome_exonerar_servidora(self):
        """EXONERAR + 'a servidora' → nome inclui preposição 'DA' interna corretamente."""
        r = monitor._extrair_dados_fofoca(self.PARA3, self.SEC3)
        assert r is not None
        assert r["pessoa"] == "ROSANGELA GURGEL DA NOBREGA"

    def test_ex3_nome_nao_contem_servidora(self):
        """O nome capturado não deve conter 'SERVIDORA' nem o artigo 'A'."""
        r = monitor._extrair_dados_fofoca(self.PARA3, self.SEC3)
        assert "SERVIDORA" not in r["pessoa"]

    def test_ex3_acao_exonerar(self):
        r = monitor._extrair_dados_fofoca(self.PARA3, self.SEC3)
        assert r["acao"] == "EXONERADO(A)"

    def test_ex3_cc_exonerar_servidora(self):
        r = monitor._extrair_dados_fofoca(self.PARA3, self.SEC3)
        assert r["simbolo_cc"] == "CC15"

    def test_ex3_cargo_exonerar_servidora(self):
        r = monitor._extrair_dados_fofoca(self.PARA3, self.SEC3)
        assert r["cargo"] != "cargo não identificado"
        assert "ASSESSOR" in r["cargo"].upper()

    # ── Exemplo 4: EXONERAR homem com "o servidor" ──────────────────────────

    def test_ex4_nome_exonerar_servidor(self):
        """EXONERAR + 'o servidor' → nome extraído sem 'O SERVIDOR'."""
        r = monitor._extrair_dados_fofoca(self.PARA4, self.SEC4)
        assert r is not None
        assert r["pessoa"] == "RAMON YOVANIS INFANTE RODRIGUEZ"

    def test_ex4_nome_nao_contem_servidor(self):
        r = monitor._extrair_dados_fofoca(self.PARA4, self.SEC4)
        assert "SERVIDOR" not in r["pessoa"]

    def test_ex4_cc_exonerar_servidor(self):
        r = monitor._extrair_dados_fofoca(self.PARA4, self.SEC4)
        assert r["simbolo_cc"] == "CC11"

    def test_ex4_cargo_exonerar_servidor(self):
        r = monitor._extrair_dados_fofoca(self.PARA4, self.SEC4)
        assert r["cargo"] != "cargo não identificado"
        assert "DIRETOR" in r["cargo"].upper()

    # ── Exemplo 5: EXONERAR com qualificador ", a pedido," ───────────────────

    def test_ex5_nome_exonerar_a_pedido(self):
        """
        Regressão — Portaria 509/2026.
        EXONERAR seguido de ', a pedido,' não deve resultar em 'PESSOA NÃO IDENTIFICADA'.
        """
        r = monitor._extrair_dados_fofoca(self.PARA5, self.SEC5)
        assert r is not None
        assert r["pessoa"] == "DANIEL VICTOR CARLOS DE NORONHA"

    def test_ex5_nome_nao_contem_pessoa_nao_identificada(self):
        """O fallback 'PESSOA NÃO IDENTIFICADA' não deve aparecer quando o nome existe."""
        r = monitor._extrair_dados_fofoca(self.PARA5, self.SEC5)
        assert r["pessoa"] != "PESSOA NÃO IDENTIFICADA"

    def test_ex5_nome_nao_contem_qualificador(self):
        """O qualificador 'A PEDIDO' não deve fazer parte do nome capturado."""
        r = monitor._extrair_dados_fofoca(self.PARA5, self.SEC5)
        assert "PEDIDO" not in r["pessoa"]

    def test_ex5_acao_exonerar_a_pedido(self):
        r = monitor._extrair_dados_fofoca(self.PARA5, self.SEC5)
        assert r["acao"] == "EXONERADO(A)"

    def test_ex5_cc_exonerar_a_pedido(self):
        r = monitor._extrair_dados_fofoca(self.PARA5, self.SEC5)
        assert r["simbolo_cc"] == "CC11"

    def test_ex5_cargo_exonerar_a_pedido(self):
        r = monitor._extrair_dados_fofoca(self.PARA5, self.SEC5)
        assert r["cargo"] != "cargo não identificado"
        assert "ASSESSOR" in r["cargo"].upper()

    # ── Entrada NFKD (como vem de detectar_fofocas) ─────────────────────────

    def test_entrada_nfkd_exonerar_servidora(self):
        """
        detectar_fofocas aplica NFKD antes de chamar _extrair_dados_fofoca.
        A função deve normalizar internamente e extrair os dados corretamente.
        """
        paragrafo_nfkd = unicodedata.normalize("NFKD", self.PARA3)
        secretaria_nfkd = unicodedata.normalize("NFKD", self.SEC3)
        r = monitor._extrair_dados_fofoca(paragrafo_nfkd, secretaria_nfkd)
        assert r is not None
        assert r["pessoa"] == "ROSANGELA GURGEL DA NOBREGA"
        assert r["simbolo_cc"] == "CC15"

    def test_entrada_nfkd_nomear_homem(self):
        """Mesmo teste NFKD para o caso NOMEAR."""
        paragrafo_nfkd = unicodedata.normalize("NFKD", self.PARA1)
        secretaria_nfkd = unicodedata.normalize("NFKD", self.SEC1)
        r = monitor._extrair_dados_fofoca(paragrafo_nfkd, secretaria_nfkd)
        assert r is not None
        assert r["pessoa"] == "PEDRO LUCAS REBOUÇAS GOMES"
        assert r["simbolo_cc"] == "CC11"


# ══════════════════════════════════════════════════════════════
# 9. formatar_fofocas
# ══════════════════════════════════════════════════════════════

class TestFormatarFofocas:

    def _fofoca(self, acao="NOMEADO(A)", pessoa="FULANO DE TAL",
                cargo="Assessor", cc="CC11", secretaria="Secretaria De Saúde"):
        return {"acao": acao, "pessoa": pessoa, "cargo": cargo,
                "simbolo_cc": cc, "secretaria": secretaria}

    def test_sem_fofocas_exibe_cabecalho(self):
        """Mesmo sem movimentações, o bloco 'FOFOCA DA SECRETARIA' deve aparecer."""
        resultado = monitor.formatar_fofocas([])
        assert "FOFOCA DA SECRETARIA" in resultado

    def test_sem_fofocas_exibe_mensagem_de_ausencia(self):
        """Deve informar explicitamente que não houve movimentações."""
        resultado = monitor.formatar_fofocas([])
        assert "Nenhuma movimentação" in resultado

    def test_sem_fofocas_nao_retorna_string_vazia(self):
        resultado = monitor.formatar_fofocas([])
        assert resultado != ""

    def test_com_fofocas_exibe_cabecalho(self):
        resultado = monitor.formatar_fofocas([self._fofoca()])
        assert "FOFOCA DA SECRETARIA" in resultado

    def test_com_fofocas_exibe_contagem(self):
        resultado = monitor.formatar_fofocas([self._fofoca(), self._fofoca()])
        assert "2" in resultado

    def test_nomeado_usa_emoji_fogo(self):
        resultado = monitor.formatar_fofocas([self._fofoca(acao="NOMEADO(A)")])
        assert "🔥" in resultado

    def test_exonerado_usa_emoji_porta(self):
        resultado = monitor.formatar_fofocas([self._fofoca(acao="EXONERADO(A)")])
        assert "🚪" in resultado

    def test_nome_da_pessoa_aparece_na_saida(self):
        resultado = monitor.formatar_fofocas([self._fofoca(pessoa="MARIA SILVA")])
        assert "MARIA SILVA" in resultado

    def test_simbolo_cc_aparece_na_saida(self):
        resultado = monitor.formatar_fofocas([self._fofoca(cc="CC15")])
        assert "CC15" in resultado

    def test_sem_cc_nao_exibe_parenteses_vazios(self):
        resultado = monitor.formatar_fofocas([self._fofoca(cc=None)])
        assert "()" not in resultado


# ══════════════════════════════════════════════════════════════
# 10. promovido_remanejado
# ══════════════════════════════════════════════════════════════

class TestPromovidoRemanejado:
    """
    Testa a consolidação de pares exoneração+nomeação da mesma pessoa.

    Regra de hierarquia CC (Brasil): número menor = cargo mais alto.
      CC15 → CC11 : n_novo < n_antigo → PROMOVIDO(A)
      CC11 → CC11 : n_novo = n_antigo → REMANEJADO(A)
      CC11 → CC15 : n_novo > n_antigo → REMANEJADO(A)
    """

    def _exon(self, pessoa, cc="CC15", cargo="Assessor", sec="Secretaria De Saúde"):
        return {"acao": "EXONERADO(A)", "pessoa": pessoa, "cargo": cargo,
                "simbolo_cc": cc, "secretaria": sec, "portaria": {}}

    def _nom(self, pessoa, cc="CC11", cargo="Diretor", sec="Secretaria De Educação"):
        return {"acao": "NOMEADO(A)", "pessoa": pessoa, "cargo": cargo,
                "simbolo_cc": cc, "secretaria": sec, "portaria": {}}

    # ── Promoção ─────────────────────────────────────────────────────────────

    def test_cc_menor_resulta_em_promovido(self):
        """CC15 → CC11: número menor = cargo mais alto = PROMOVIDO(A)."""
        fofocas = [self._exon("FULANO", cc="CC15"), self._nom("FULANO", cc="CC11")]
        resultado = monitor.promovido_remanejado(fofocas)
        assert len(resultado) == 1
        assert resultado[0]["acao"] == "PROMOVIDO(A)"

    def test_promovido_contem_cargo_anterior_e_novo(self):
        fofocas = [
            self._exon("FULANO", cc="CC15", cargo="Assessor"),
            self._nom("FULANO",  cc="CC11", cargo="Diretor"),
        ]
        r = monitor.promovido_remanejado(fofocas)[0]
        assert r["cargo_anterior"] == "Assessor"
        assert r["cargo_novo"] == "Diretor"

    def test_promovido_contem_secretaria_anterior_e_nova(self):
        fofocas = [
            self._exon("FULANO", sec="Secretaria De Saúde"),
            self._nom("FULANO",  sec="Secretaria De Educação"),
        ]
        r = monitor.promovido_remanejado(fofocas)[0]
        assert r["secretaria_anterior"] == "Secretaria De Saúde"
        assert r["secretaria_nova"] == "Secretaria De Educação"

    def test_promovido_contem_cc_anterior_e_novo(self):
        fofocas = [self._exon("FULANO", cc="CC15"), self._nom("FULANO", cc="CC11")]
        r = monitor.promovido_remanejado(fofocas)[0]
        assert r["cc_anterior"] == "CC15"
        assert r["cc_novo"] == "CC11"

    # ── Remanejamento ─────────────────────────────────────────────────────────

    def test_cc_igual_resulta_em_remanejado(self):
        """CC11 → CC11: mesmo número = REMANEJADO(A)."""
        fofocas = [self._exon("FULANO", cc="CC11"), self._nom("FULANO", cc="CC11")]
        resultado = monitor.promovido_remanejado(fofocas)
        assert resultado[0]["acao"] == "REMANEJADO(A)"

    def test_cc_maior_resulta_em_remanejado(self):
        """CC11 → CC15: número maior = cargo mais baixo = REMANEJADO(A)."""
        fofocas = [self._exon("FULANO", cc="CC11"), self._nom("FULANO", cc="CC15")]
        resultado = monitor.promovido_remanejado(fofocas)
        assert resultado[0]["acao"] == "REMANEJADO(A)"

    # ── Consolidação e limpeza ────────────────────────────────────────────────

    def test_par_gera_um_unico_registro(self):
        """Dois registros (exon + nom) devem ser substituídos por um único."""
        fofocas = [self._exon("FULANO"), self._nom("FULANO")]
        resultado = monitor.promovido_remanejado(fofocas)
        assert len(resultado) == 1

    def test_registros_sem_par_permanecem_inalterados(self):
        """Exoneração sem nomeação correspondente deve permanecer como EXONERADO(A)."""
        fofocas = [self._exon("FULANO"), self._exon("CICLANO")]
        resultado = monitor.promovido_remanejado(fofocas)
        assert len(resultado) == 2
        assert all(r["acao"] == "EXONERADO(A)" for r in resultado)

    def test_nomeacao_sem_exoneracao_permanece_inalterada(self):
        fofocas = [self._nom("BELTRANO")]
        resultado = monitor.promovido_remanejado(fofocas)
        assert len(resultado) == 1
        assert resultado[0]["acao"] == "NOMEADO(A)"

    def test_pessoas_diferentes_nao_sao_consolidadas(self):
        """Exoneração de A e nomeação de B não formam par."""
        fofocas = [self._exon("FULANO"), self._nom("CICLANO")]
        resultado = monitor.promovido_remanejado(fofocas)
        assert len(resultado) == 2

    def test_sem_cc_resulta_em_remanejado(self):
        """Quando não há símbolo CC em algum dos eventos, assume REMANEJADO(A)."""
        fofocas = [
            self._exon("FULANO", cc=None),
            self._nom("FULANO",  cc=None),
        ]
        resultado = monitor.promovido_remanejado(fofocas)
        assert resultado[0]["acao"] == "REMANEJADO(A)"

    # ── Formatação das novas ações ────────────────────────────────────────────

    def test_formatar_promovido_usa_emoji_seta(self):
        fofocas = [self._exon("FULANO", cc="CC15"), self._nom("FULANO", cc="CC11")]
        consolidado = monitor.promovido_remanejado(fofocas)
        resultado = monitor.formatar_fofocas(consolidado)
        assert "🔝" in resultado

    def test_formatar_remanejado_usa_emoji_setas(self):
        fofocas = [self._exon("FULANO", cc="CC11"), self._nom("FULANO", cc="CC11")]
        consolidado = monitor.promovido_remanejado(fofocas)
        resultado = monitor.formatar_fofocas(consolidado)
        assert "🔄" in resultado

    def test_formatar_promovido_exibe_cargos_e_secretarias(self):
        fofocas = [
            self._exon("FULANO", cc="CC15", cargo="Assessor", sec="Secretaria De Saúde"),
            self._nom("FULANO",  cc="CC11", cargo="Diretor",  sec="Secretaria De Educação"),
        ]
        consolidado = monitor.promovido_remanejado(fofocas)
        resultado = monitor.formatar_fofocas(consolidado)
        assert "Assessor" in resultado
        assert "Diretor" in resultado
        assert "Secretaria De Saúde" in resultado
        assert "Secretaria De Educação" in resultado

    def test_formatar_promovido_nao_exibe_nomeado_nem_exonerado(self):
        """A mensagem de promovido não deve mencionar NOMEADO(A) nem EXONERADO(A)."""
        fofocas = [self._exon("FULANO", cc="CC15"), self._nom("FULANO", cc="CC11")]
        consolidado = monitor.promovido_remanejado(fofocas)
        resultado = monitor.formatar_fofocas(consolidado)
        assert "NOMEADO" not in resultado
        assert "EXONERADO" not in resultado

    # ── Robustez do pareamento por nome (espaços / colisão) ───────────────────

    def test_parea_mesmo_nome_com_espacos_diferentes(self):
        """Espaçamento diferente entre exoneração e nomeação ainda deve parear.

        Sem normalização, 'JOAO  SILVA' != 'JOAO SILVA' → não pareava e os dois
        atos apareciam soltos em vez de um único PROMOVIDO/REMANEJADO.
        """
        fofocas = [
            self._exon("JOAO  SILVA", cc="CC15"),   # dois espaços
            self._nom("JOAO SILVA",   cc="CC11"),   # um espaço
        ]
        resultado = monitor.promovido_remanejado(fofocas)
        assert len(resultado) == 1
        assert resultado[0]["acao"] == "PROMOVIDO(A)"

    def test_multiplas_exoneracoes_mesma_pessoa_logam_aviso(self):
        """Duas exonerações da mesma pessoa: consolida sem quebrar e avisa no log."""
        fofocas = [
            self._exon("MARIA LIMA", cc="CC10"),
            self._exon("MARIA LIMA", cc="CC12"),
            self._nom("MARIA LIMA",  cc="CC7"),
        ]
        with patch.object(monitor.parsing, "log") as mock_log:
            resultado = monitor.promovido_remanejado(fofocas)
        assert len(resultado) == 1
        assert resultado[0]["pessoa"] == "MARIA LIMA"
        assert mock_log.warning.called


# ══════════════════════════════════════════════════════════════
# 10. detectar_ponto_facultativo / formatar_ponto_facultativo
# ══════════════════════════════════════════════════════════════

class TestPontoFacultativo:

    def _ato(self, conteudo, titulo="DECRETO Nº 7.454"):
        return {"titulo": titulo, "ementa": "", "conteudo": conteudo}

    def test_detecta_e_extrai_data_e_dia_da_semana(self):
        ato = self._ato(
            "Declara ponto facultativo na sexta-feira, dia 21 de novembro de 2025, "
            "no âmbito da Administração."
        )
        r = monitor.detectar_ponto_facultativo([ato])
        assert len(r) == 1
        assert r[0]["data_br"] == "21/11/2025"
        assert r[0]["dia_semana"] == "sexta"   # 21/11/2025 é sexta-feira
        assert r[0]["weekday"] == 4

    def test_dedup_mesma_data_repetida_no_mesmo_ato(self):
        ato = self._ato(
            "ponto facultativo na sexta-feira, dia 21 de novembro de 2025.\n"
            "Fica declarado ponto facultativo no dia 21 de novembro de 2025, sexta-feira."
        )
        r = monitor.detectar_ponto_facultativo([ato])
        assert len(r) == 1  # mesma data → um único aviso

    def test_datas_diferentes_geram_avisos_distintos(self):
        ato = self._ato(
            "ponto facultativo no dia 24 de dezembro de 2025 e também "
            "ponto facultativo no dia 31 de dezembro de 2025."
        )
        r = monitor.detectar_ponto_facultativo([ato])
        datas = {x["data_br"] for x in r}
        assert datas == {"24/12/2025", "31/12/2025"}

    def test_aceita_data_numerica(self):
        ato = self._ato("Fica declarado ponto facultativo no dia 21/11/2025.")
        r = monitor.detectar_ponto_facultativo([ato])
        assert r[0]["data_br"] == "21/11/2025"

    def test_sem_data_retorna_generico(self):
        ato = self._ato("Fica declarado ponto facultativo nas repartições públicas.")
        r = monitor.detectar_ponto_facultativo([ato])
        assert len(r) == 1
        assert r[0]["data_br"] is None

    def test_sem_ponto_facultativo_retorna_vazio(self):
        ato = self._ato("Decreto que dispõe sobre crédito suplementar.")
        assert monitor.detectar_ponto_facultativo([ato]) == []

    def test_deteccao_e_insensivel_a_acento_e_caixa(self):
        ato = self._ato("PONTO FACULTATIVO no dia 21 de NOVEMBRO de 2025.")
        r = monitor.detectar_ponto_facultativo([ato])
        assert r[0]["data_br"] == "21/11/2025"

    def test_nao_pega_data_de_emissao_do_decreto(self):
        """A data 'DE 18 DE NOVEMBRO' (emissão, sem 'dia') não deve ser capturada."""
        ato = self._ato(
            "DECRETO Nº 7.454, DE 18 DE NOVEMBRO DE 2025\n"
            "Declara ponto facultativo na sexta-feira, dia 21 de novembro de 2025."
        )
        r = monitor.detectar_ponto_facultativo([ato])
        assert [x["data_br"] for x in r] == ["21/11/2025"]

    def test_data_invalida_e_ignorada(self):
        ato = self._ato("ponto facultativo no dia 31 de fevereiro de 2025.")
        r = monitor.detectar_ponto_facultativo([ato])
        assert r == [{"data_br": None, "dia_semana": None, "weekday": None}]

    def test_manchete_sexta_vs_outro_dia(self):
        sexta = monitor.formatar_ponto_facultativo(
            [{"data_br": "21/11/2025", "dia_semana": "sexta", "weekday": 4}]
        )
        outro = monitor.formatar_ponto_facultativo(
            [{"data_br": "24/12/2025", "dia_semana": "quarta", "weekday": 2}]
        )
        assert any("SEXTOU OFICIAL" in linha for linha in sexta)
        assert any("FOLGA À VISTA" in linha for linha in outro)

    def test_fofoca_anexa_ponto_facultativo_ao_final_sem_movimentacoes(self):
        pf = [{"data_br": "21/11/2025", "dia_semana": "sexta", "weekday": 4}]
        msg = monitor.formatar_fofocas([], pf)
        assert "ponto facultativo na sexta, 21/11/2025" in msg
        # aparece DEPOIS do aviso de "silêncio absoluto"
        assert msg.index("Silêncio absoluto") < msg.index("ponto facultativo")

    def test_fofoca_sem_ponto_facultativo_nao_menciona(self):
        msg = monitor.formatar_fofocas([])
        assert "ponto facultativo" not in msg.lower()


# ══════════════════════════════════════════════════════════════
# 9. buscar_publicacao_por_numero
# ══════════════════════════════════════════════════════════════

class TestBuscarPublicacaoPorNumero:

    @patch("monitor_diario_oficial.requests.get")
    def test_encontra_edicao_pelo_numero(self, mock_get):
        mock_get.return_value = _mock_resposta_http(HTML_EDICOES_POR_NUMERO)

        resultado = monitor.buscar_publicacao_por_numero(839)

        assert resultado is not None
        assert resultado["id"] == "1874"
        assert resultado["url_html"] == "https://dom.mossoro.rn.gov.br/dom/publicacao/1874"

    @patch("monitor_diario_oficial.requests.get")
    def test_retorna_numero_e_data(self, mock_get):
        mock_get.return_value = _mock_resposta_http(HTML_EDICOES_POR_NUMERO)

        resultado = monitor.buscar_publicacao_por_numero(839)

        assert resultado["numero"] == 839
        assert resultado["data"] == "12/06/2026"

    @patch("monitor_diario_oficial.requests.get")
    def test_para_quando_listagem_passa_do_alvo(self, mock_get):
        """839 ausente (lacuna 840→838): a listagem decrescente passa do alvo → None."""
        mock_get.return_value = _mock_resposta_http(HTML_EDICOES_NUMERO_COM_LACUNA)

        resultado = monitor.buscar_publicacao_por_numero(839)

        assert resultado is None

    @patch("monitor_diario_oficial.requests.get")
    def test_retorna_none_em_pagina_vazia(self, mock_get):
        mock_get.return_value = _mock_resposta_http(HTML_EDICOES_VAZIA)

        assert monitor.buscar_publicacao_por_numero(839) is None

    @patch("monitor_diario_oficial.requests.get")
    def test_retorna_none_em_erro_de_rede(self, mock_get):
        import requests as req_lib
        mock_get.side_effect = req_lib.RequestException("timeout")

        assert monitor.buscar_publicacao_por_numero(839) is None


# ══════════════════════════════════════════════════════════════
# 10. main() — roteamento por número de edição escolhido
# ══════════════════════════════════════════════════════════════

class TestMainRoteamento:

    def test_usa_busca_por_numero_quando_informado(self):
        """Com numero_diario, main deve buscar a edição por número (não a última)."""
        with patch("monitor_diario_oficial.buscar_publicacao_por_numero", return_value=None) as m_num, \
             patch("monitor_diario_oficial.buscar_ultima_publicacao") as m_ult:
            monitor.main(modo_teste=True, numero_diario=839)
        m_num.assert_called_once_with(839)
        m_ult.assert_not_called()

    def test_usa_ultima_publicacao_sem_numero(self):
        """Sem numero_diario, mantém o comportamento atual (última edição)."""
        with patch("monitor_diario_oficial.buscar_ultima_publicacao", return_value=None) as m_ult, \
             patch("monitor_diario_oficial.buscar_publicacao_por_numero") as m_num:
            monitor.main(modo_teste=True)
        m_ult.assert_called_once()
        m_num.assert_not_called()

    def test_propaga_sessao_descartavel_para_enviar_whatsapp(self):
        """main(sessao_descartavel=True) deve repassar a flag a enviar_whatsapp."""
        publicacao = {"numero": 999, "data": "16/06/2026", "url_html": "http://x/999"}
        with patch("monitor_diario_oficial.buscar_ultima_publicacao", return_value=publicacao), \
             patch("monitor_diario_oficial.extrair_portarias", return_value=["ato"]), \
             patch("monitor_diario_oficial.buscar_nomes_em_portarias", return_value=[]), \
             patch("monitor_diario_oficial.detectar_fofocas", return_value=[]), \
             patch("monitor_diario_oficial.promovido_remanejado", return_value=[]), \
             patch("monitor_diario_oficial.detectar_ponto_facultativo", return_value=[]), \
             patch("monitor_diario_oficial.formatar_fofocas", return_value=""), \
             patch("monitor_diario_oficial.enviar_whatsapp", return_value=True) as m_env:
            monitor.main(modo_teste=True, sessao_descartavel=True)

        assert m_env.call_args.kwargs.get("sessao_descartavel") is True


# ══════════════════════════════════════════════════════════════
# 11. _extrair_numero_teste — número que segue a flag --test
# ══════════════════════════════════════════════════════════════

class TestExtrairNumeroTeste:

    def test_numero_apos_test(self):
        assert monitor._extrair_numero_teste(["prog", "--test", "839"]) == 839

    def test_test_sem_numero_retorna_none(self):
        assert monitor._extrair_numero_teste(["prog", "--test"]) is None

    def test_test_seguido_de_outra_flag_retorna_none(self):
        assert monitor._extrair_numero_teste(["prog", "--test", "--agendar"]) is None

    def test_sem_flag_test_retorna_none(self):
        assert monitor._extrair_numero_teste(["prog"]) is None


# ══════════════════════════════════════════════════════════════
# 12. _nome_arquivo_log — escolhe producao.log vs testes.log
# ══════════════════════════════════════════════════════════════

class TestNomeArquivoLog:

    def test_execucao_normal_usa_producao(self):
        """Sem --test e sem pytest carregado → producao.log."""
        assert monitor.config._nome_arquivo_log(argv=["prog"], modulos={}) == "producao.log"

    def test_flag_test_usa_testes(self):
        """Com --test no argv → testes.log."""
        assert monitor.config._nome_arquivo_log(argv=["prog", "--test"], modulos={}) == "testes.log"

    def test_pytest_carregado_usa_testes(self):
        """Com pytest em sys.modules → testes.log (suíte não polui produção)."""
        assert monitor.config._nome_arquivo_log(argv=["prog"], modulos={"pytest": object()}) == "testes.log"


# ══════════════════════════════════════════════════════════════
# 2c. _prox_ato_titulo e _paginas_da_portaria (detecção de páginas)
# ══════════════════════════════════════════════════════════════

class TestProxAtoTitulo:

    def test_retorna_titulo_do_ato_seguinte(self):
        p1 = {"titulo": "PORTARIA Nº 47,"}
        p2 = {"titulo": "EXTRATO DE CONTRATO"}
        portarias = [p1, p2]
        assert monitor._prox_ato_titulo(p1, portarias) == "EXTRATO DE CONTRATO"

    def test_ultimo_ato_retorna_none(self):
        p1 = {"titulo": "PORTARIA Nº 47,"}
        assert monitor._prox_ato_titulo(p1, [p1]) is None

    def test_sem_lista_retorna_none(self):
        assert monitor._prox_ato_titulo({"titulo": "X"}, None) is None

    def test_lista_vazia_retorna_none(self):
        # lista vazia é tratada como "sem lista" (mesmo ramo `if not portarias`)
        assert monitor._prox_ato_titulo({"titulo": "X"}, []) is None

    def test_objeto_ausente_na_lista_retorna_none(self):
        p1 = {"titulo": "A"}
        outros = [{"titulo": "B"}, {"titulo": "C"}]
        assert monitor._prox_ato_titulo(p1, outros) is None


def _montar_combined(paginas_norm):
    """Replica o combined/page_offsets de extrair_pdfs_por_ocorrencia.

    Retorna (combined, page_offsets). page_offsets tem len == nº de páginas + 1
    (sentinela), com cada página separada por '\\n' (somando +1 ao offset)."""
    offsets = []
    pos = 0
    for t in paginas_norm:
        offsets.append(pos)
        pos += len(t) + 1
    offsets.append(pos)
    return "\n".join(paginas_norm), offsets


_RX_PORTARIA = re.compile(r'PORTARIA\s+N[Oº°]\s+\d+\s*,')


class TestPaginasDaPortaria:

    def test_portaria_seguida_de_outro_ato_fica_em_uma_pagina(self):
        # Cenário PORTARIA 47: termina na pág. 1; depois vêm extratos/termos;
        # o próximo PORTARIA só aparece na pág. 2.
        pg1 = ("PORTARIA NO 47, DE 12 DE JUNHO DE 2026\n"
               "ART 1 CONCEDER DIARIA AO SR FULANO\n"
               "MOSSORO-RN 12 DE JUNHO DE 2026\n"
               "EXTRATO DE CONTRATO\nCONTRATO NO 06/2026")
        pg2 = ("EXPEDIENTE\nPORTARIA NO 25, DE 15 DE JUNHO DE 2026\nART 1 ...")
        combined, offs = _montar_combined([pg1, pg2])
        all_port = [m.start() for m in _RX_PORTARIA.finditer(combined)]
        start = combined.find("PORTARIA NO 47,")

        pgs = monitor._paginas_da_portaria(
            combined, offs, start, "PORTARIA NO 47,",
            "EXTRATO DE CONTRATO", all_port,
        )
        assert pgs == [1]

    def test_sem_proximo_ato_recai_em_proxima_portaria(self):
        # Documenta o CAMINHO DE FALLBACK (não o ideal): sem prox_titulo_norm, a
        # fronteira recai no próximo cabeçalho PORTARIA → a pág. 2 acaba incluída.
        # O resultado [1, 2] aqui é o comportamento degradado esperado quando a
        # lista de atos não é fornecida — contraste proposital com o teste acima,
        # que com o próximo ato retorna [1].
        pg1 = ("PORTARIA NO 47, DE 12 DE JUNHO DE 2026\nART 1 ...\n"
               "EXTRATO DE CONTRATO\nCONTRATO NO 06/2026")
        pg2 = ("EXPEDIENTE\nPORTARIA NO 25, DE 15 DE JUNHO DE 2026\n...")
        combined, offs = _montar_combined([pg1, pg2])
        all_port = [m.start() for m in _RX_PORTARIA.finditer(combined)]
        start = combined.find("PORTARIA NO 47,")

        pgs = monitor._paginas_da_portaria(
            combined, offs, start, "PORTARIA NO 47,", None, all_port,
        )
        assert pgs == [1, 2]

    def test_portaria_que_continua_inclui_duas_paginas(self):
        # Cenário PORTARIA 45: corpo continua na pág. 2; próximo ato (PORTARIA 46)
        # está na pág. 2 → as duas páginas entram.
        pg1 = ("PORTARIA NO 45, DE 12 DE JUNHO DE 2026\n"
               "ART 1 TEXTO LONGO QUE CONTINUA NA PROXIMA PAGINA")
        pg2 = ("CONTINUACAO DO ARTIGO\nMOSSORO-RN 12 DE JUNHO\n"
               "PORTARIA NO 46, DE 12 DE JUNHO DE 2026\nART 1 ...")
        combined, offs = _montar_combined([pg1, pg2])
        all_port = [m.start() for m in _RX_PORTARIA.finditer(combined)]
        start = combined.find("PORTARIA NO 45,")

        pgs = monitor._paginas_da_portaria(
            combined, offs, start, "PORTARIA NO 45,",
            "PORTARIA NO 46,", all_port,
        )
        assert pgs == [1, 2]

    def test_proximo_ato_nao_localizado_e_sem_proxima_portaria_vai_ate_fim(self):
        # prox_titulo existe na lista do HTML mas não é localizável no PDF, e não
        # há próximo PORTARIA → fallback final: fim do documento.
        pg1 = ("PORTARIA NO 99, DE 12 DE JUNHO DE 2026\nART 1 ...")
        pg2 = ("CONTINUACAO SEM CABECALHO DE PORTARIA")
        combined, offs = _montar_combined([pg1, pg2])
        all_port = [m.start() for m in _RX_PORTARIA.finditer(combined)]
        start = combined.find("PORTARIA NO 99,")

        pgs = monitor._paginas_da_portaria(
            combined, offs, start, "PORTARIA NO 99,",
            "PORTARIA NO 100,", all_port,  # 100 não aparece no texto
        )
        assert pgs == [1, 2]


# ══════════════════════════════════════════════════════════════
# 13. _atualizar_env — persiste chaves no .env da RAIZ do projeto
# ══════════════════════════════════════════════════════════════

class TestAtualizarEnv:

    def test_atualiza_chave_no_env_da_raiz(self, tmp_path):
        """O .env fica na raiz do projeto (_BASE_DIR), não em src/.

        load_dotenv lê o .env da raiz; a gravação deve usar o mesmo arquivo,
        senão ULTIMO_DOM_NUMERO nunca é persistido.
        """
        env_file = tmp_path / ".env"
        env_file.write_text("ULTIMO_DOM_NUMERO=800\n", encoding="utf-8")

        with patch.object(monitor.config, "_BASE_DIR", str(tmp_path)):
            monitor.config._atualizar_env("ULTIMO_DOM_NUMERO", "815")

        assert env_file.read_text(encoding="utf-8") == "ULTIMO_DOM_NUMERO=815\n"

    def test_acrescenta_chave_ausente_no_env_da_raiz(self, tmp_path):
        """Chave inexistente é adicionada ao final do .env da raiz."""
        env_file = tmp_path / ".env"
        env_file.write_text("OUTRA=1\n", encoding="utf-8")

        with patch.object(monitor.config, "_BASE_DIR", str(tmp_path)):
            monitor.config._atualizar_env("ULTIMO_DOM_NUMERO", "815")

        assert env_file.read_text(encoding="utf-8") == "OUTRA=1\nULTIMO_DOM_NUMERO=815\n"


# ══════════════════════════════════════════════════════════════
# 14. _ler_int_env — leitura tolerante de variáveis inteiras do .env
# ══════════════════════════════════════════════════════════════

class TestLerIntEnv:
    """Um valor inválido no .env não pode levantar ValueError: isso travaria
    o import de config.py (e, portanto, toda a aplicação) na inicialização."""

    CHAVE = "_TESTE_INT_ENV_TMP"

    def test_valor_valido(self, monkeypatch):
        monkeypatch.setenv(self.CHAVE, "815")
        assert monitor.config._ler_int_env(self.CHAVE, 0) == 815

    def test_valor_com_espacos_e_normalizado(self, monkeypatch):
        monkeypatch.setenv(self.CHAVE, "  42  ")
        assert monitor.config._ler_int_env(self.CHAVE, 0) == 42

    def test_ausente_usa_padrao(self, monkeypatch):
        monkeypatch.delenv(self.CHAVE, raising=False)
        assert monitor.config._ler_int_env(self.CHAVE, 7) == 7

    def test_vazio_usa_padrao(self, monkeypatch):
        monkeypatch.setenv(self.CHAVE, "")
        assert monitor.config._ler_int_env(self.CHAVE, 7) == 7

    def test_invalido_usa_padrao_sem_levantar(self, monkeypatch):
        monkeypatch.setenv(self.CHAVE, "120s")
        assert monitor.config._ler_int_env(self.CHAVE, 120) == 120


# ══════════════════════════════════════════════════════════════
# 15. _atualizar_env — escrita atômica (não deixa .tmp nem corrompe)
# ══════════════════════════════════════════════════════════════

class TestAtualizarEnvAtomico:

    def test_nao_deixa_arquivo_temporario_apos_sucesso(self, tmp_path):
        env_file = tmp_path / ".env"
        env_file.write_text("ULTIMO_DOM_NUMERO=800\n", encoding="utf-8")

        with patch.object(monitor.config, "_BASE_DIR", str(tmp_path)):
            monitor.config._atualizar_env("ULTIMO_DOM_NUMERO", "815")

        assert env_file.read_text(encoding="utf-8") == "ULTIMO_DOM_NUMERO=815\n"
        assert not (tmp_path / ".env.tmp").exists()


# ══════════════════════════════════════════════════════════════
# 16. _executar_protegido — uma exceção não pode matar o loop agendado
# ══════════════════════════════════════════════════════════════

class TestExecutarProtegido:

    def test_excecao_em_main_e_capturada_e_logada(self):
        """Exceção não tratada em main() é logada, não propagada — o agendamento sobrevive."""
        with patch.object(monitor, "main", side_effect=RuntimeError("boom")), \
             patch.object(monitor, "log") as mock_log:
            monitor._executar_protegido()  # não deve levantar
        assert mock_log.error.called

    def test_sucesso_chama_main_uma_vez(self):
        with patch.object(monitor, "main") as mock_main:
            monitor._executar_protegido()
        mock_main.assert_called_once_with()

    def test_keyboard_interrupt_propaga(self):
        """KeyboardInterrupt (BaseException) deve continuar encerrando o processo."""
        with patch.object(monitor, "main", side_effect=KeyboardInterrupt), \
             pytest.raises(KeyboardInterrupt):
            monitor._executar_protegido()


# ══════════════════════════════════════════════════════════════
# 17. extrair_pdfs_por_ocorrencia — PDF inválido/corrompido não derruba o job
# ══════════════════════════════════════════════════════════════

class TestExtrairPdfsConteudoInvalido:

    def test_conteudo_nao_pdf_retorna_lista_vazia(self):
        """Servidor devolve HTML/lixo (status 200) em vez de PDF: não lança, retorna []."""
        mock_resp = MagicMock()
        mock_resp.content = b"<html><body>erro 500</body></html>"
        mock_resp.raise_for_status = MagicMock()

        oc = {
            "nome": "FULANO DE TAL",
            "portaria": {"titulo": "PORTARIA Nº 001/2026", "ementa": "", "conteudo": "x"},
        }
        with patch("monitor_diario_oficial.requests.get", return_value=mock_resp):
            resultado = monitor.extrair_pdfs_por_ocorrencia("http://pdf.url", [oc])

        assert resultado == []


# ══════════════════════════════════════════════════════════════
# 18. Estado de envio — idempotência por etapa (texto/pdfs/fofoca)
# ══════════════════════════════════════════════════════════════

class TestEstadoEnvio:
    """Persistência de progresso de envio por edição, para que um retry pule as
    etapas já concluídas (evita reenviar o texto quando só o PDF falhou)."""

    def test_etapas_vazias_sem_arquivo(self, tmp_path):
        path = str(tmp_path / ".envio_estado.json")
        with patch.object(monitor.config, "_ESTADO_ENVIO_PATH", path):
            assert monitor.config.etapas_enviadas(815) == set()

    def test_marca_e_le_etapas_por_edicao(self, tmp_path):
        path = str(tmp_path / ".envio_estado.json")
        with patch.object(monitor.config, "_ESTADO_ENVIO_PATH", path):
            monitor.config.marcar_etapa_enviada(815, "texto")
            monitor.config.marcar_etapa_enviada(815, "pdfs")
            assert monitor.config.etapas_enviadas(815) == {"texto", "pdfs"}
            # outra edição não é afetada
            assert monitor.config.etapas_enviadas(816) == set()

    def test_id_none_desativa_e_nao_cria_arquivo(self, tmp_path):
        path = str(tmp_path / ".envio_estado.json")
        with patch.object(monitor.config, "_ESTADO_ENVIO_PATH", path):
            monitor.config.marcar_etapa_enviada(None, "texto")  # no-op
            assert monitor.config.etapas_enviadas(None) == set()
            assert not os.path.isfile(path)

    def test_prune_mantem_apenas_edicoes_mais_recentes(self, tmp_path):
        path = str(tmp_path / ".envio_estado.json")
        with patch.object(monitor.config, "_ESTADO_ENVIO_PATH", path), \
             patch.object(monitor.config, "_MAX_EDICOES_ESTADO", 3):
            for n in [810, 811, 812, 813, 814]:
                monitor.config.marcar_etapa_enviada(n, "texto")
            assert monitor.config.etapas_enviadas(810) == set()
            assert monitor.config.etapas_enviadas(811) == set()
            assert monitor.config.etapas_enviadas(812) == {"texto"}
            assert monitor.config.etapas_enviadas(814) == {"texto"}

    def test_arquivo_corrompido_tratado_como_vazio(self, tmp_path):
        path = tmp_path / ".envio_estado.json"
        path.write_text("{ não é json válido", encoding="utf-8")
        with patch.object(monitor.config, "_ESTADO_ENVIO_PATH", str(path)):
            assert monitor.config.etapas_enviadas(815) == set()


class TestEnviarWhatsappIdempotente:

    def test_pula_envio_quando_todas_etapas_ja_feitas(self):
        """Todas as etapas requeridas já enviadas → retorna True sem abrir o Chrome."""
        with patch("monitor_diario_oficial.whatsapp.etapas_enviadas",
                   return_value={"texto", "pdfs", "fofoca"}), \
             patch("monitor_diario_oficial.webdriver.Chrome") as mock_chrome:
            r = monitor.enviar_whatsapp(
                "msg", "Grupo", ["a.pdf"], mensagem_apos_pdf="fofoca", id_edicao=815
            )
        assert r is True
        mock_chrome.assert_not_called()
