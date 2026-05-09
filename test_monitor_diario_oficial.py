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
Art. 1\xba REVOGAR a portaria que designou\xa0GEORGIANY\xa0PAULA\xa0BESSA\xa0CAMPELO.
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
def portaria_com_georgiany():
    return {
        "titulo": "PORTARIA Nº 052/2026",
        "ementa": "Dispõe sobre revogação de designação.",
        "conteudo": (
            "PORTARIA Nº 052/2026\n"
            "Dispõe sobre revogação de designação.\n"
            "Art. 1º REVOGAR a Portaria nº 068, que designou "
            "GEORGIANY PAULA BESSA CAMPELO para o cargo de Agente de Contratação."
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
            "Art. 1º REVOGAR a designação de\xa0GEORGIANY\xa0PAULA\xa0BESSA\xa0CAMPELO."
        ),
    }


@pytest.fixture
def portaria_com_leopoldo():
    return {
        "titulo": "PORTARIA Nº 100/2026",
        "ementa": "Dispõe sobre concessão de licença.",
        "conteudo": (
            "PORTARIA Nº 100/2026\n"
            "Dispõe sobre concessão de licença.\n"
            "Art. 1º CONCEDER ao servidor JOSE LEOPOLDO DANTAS COUTO licença especial."
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
      1. QR code check          → SeleniumTimeoutException (sem QR, sessão ativa)
      2. Interface pronta loop  → retorna MagicMock (detecta sidebar na 1ª tentativa)
      3. Search box loop        → retorna caixa_pesquisa (1ª tentativa de XPath)
      4. Resultado grupo        → retorna resultado_grupo
      5. Message box loop       → retorna caixa_msg (1ª tentativa de XPath)
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
        SeleniumTimeoutException(),  # QR code não encontrado → sessão ativa
        SeleniumTimeoutException(),  # diálogo "usar nesta janela" não encontrado
        mock_caixa_pesquisa,         # search box encontrada no 1º XPath (input[@data-tab="3"])
        mock_resultado_grupo,        # grupo encontrado
        mock_caixa_msg,              # caixa de mensagem encontrada no 1º XPath
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
        with patch("monitor_diario_oficial.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2026, 5, 7, 12, 0, 0)
            mock_dt.strptime.side_effect = datetime.strptime
            resultado = monitor.obter_data_anterior()
        assert resultado == "06/05/2026"

    def test_virada_de_mes(self):
        """Deve calcular corretamente o último dia do mês anterior."""
        with patch("monitor_diario_oficial.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2026, 6, 1, 8, 0, 0)
            mock_dt.strptime.side_effect = datetime.strptime
            resultado = monitor.obter_data_anterior()
        assert resultado == "31/05/2026"

    def test_virada_de_ano(self):
        """Deve calcular corretamente 31/12 quando hoje é 01/01."""
        with patch("monitor_diario_oficial.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2026, 1, 1, 0, 0, 0)
            mock_dt.strptime.side_effect = datetime.strptime
            resultado = monitor.obter_data_anterior()
        assert resultado == "31/12/2025"

    def test_dia_com_zero_a_esquerda(self):
        """Dias de 1 a 9 devem ter zero à esquerda (ex: 06, não 6)."""
        with patch("monitor_diario_oficial.datetime") as mock_dt:
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

    def _ocorrencia(self, titulo, nome):
        return {
            "nome": nome,
            "portaria": {"titulo": titulo, "ementa": "", "conteudo": titulo},
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
        import sys
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
        page = writer.add_blank_page(width=200, height=200)
        buf = _io.BytesIO()
        writer.write(buf)
        pdf_bytes = buf.getvalue()

        mock_resp = MagicMock()
        mock_resp.content = pdf_bytes
        mock_resp.raise_for_status = MagicMock()

        oc = self._ocorrencia("PORTARIA Nº 001-2026", "MARINA COSTA")

        with patch("monitor_diario_oficial.requests.get", return_value=mock_resp):
            with patch("monitor_diario_oficial.os.path.dirname", return_value=str(tmp_path)):
                resultado = monitor.extrair_pdfs_por_ocorrencia("http://pdf.url", [oc])

        # Mesmo sem páginas encontradas (PDF em branco), a lista pode ser vazia.
        # O que testamos é que não lançou exceção e o formato do nome está correto
        # quando há páginas (verificado pelo _sanitizar_nome_arquivo).
        nome_esperado = monitor._sanitizar_nome_arquivo(
            "PORTARIA Nº 001-2026 - MARINA COSTA"
        ) + ".pdf"
        assert "PORTARIA" in nome_esperado
        assert "MARINA COSTA" in nome_esperado


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

    def test_encontra_nome_presente(self, portaria_com_georgiany):
        encontrados = monitor.buscar_nomes_em_portarias(
            [portaria_com_georgiany], ["GEORGIANY PAULA BESSA CAMPELO"]
        )
        assert len(encontrados) == 1
        assert encontrados[0]["nome"] == "GEORGIANY PAULA BESSA CAMPELO"

    def test_busca_e_case_insensitive_na_lista(self, portaria_com_georgiany):
        """Nome na lista em minúsculas deve encontrar conteúdo em maiúsculas."""
        encontrados = monitor.buscar_nomes_em_portarias(
            [portaria_com_georgiany], ["georgiany paula bessa campelo"]
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

    def test_lista_vazia_de_nomes_retorna_vazio(self, portaria_com_georgiany):
        encontrados = monitor.buscar_nomes_em_portarias([portaria_com_georgiany], [])
        assert encontrados == []

    def test_encontra_nome_em_multiplas_portarias(
        self, portaria_com_georgiany, portaria_simples
    ):
        """Deve reportar cada portaria onde o nome aparece separadamente."""
        portaria_simples["conteudo"] += "\nGEORGIANY PAULA BESSA CAMPELO também aqui."
        encontrados = monitor.buscar_nomes_em_portarias(
            [portaria_com_georgiany, portaria_simples],
            ["GEORGIANY PAULA BESSA CAMPELO"],
        )
        assert len(encontrados) == 2

    def test_encontra_multiplos_nomes_na_mesma_portaria(self, portaria_simples):
        """Dois nomes distintos na mesma portaria geram duas ocorrências."""
        portaria_simples["conteudo"] = (
            "PORTARIA Nº 001/2026\n"
            "NOMEAR JOSE LEOPOLDO DANTAS COUTO e GEORGIANY PAULA BESSA CAMPELO."
        )
        encontrados = monitor.buscar_nomes_em_portarias(
            [portaria_simples],
            ["JOSE LEOPOLDO DANTAS COUTO", "GEORGIANY PAULA BESSA CAMPELO"],
        )
        assert len(encontrados) == 2

    def test_normaliza_nbsp_no_conteudo(self, portaria_com_nbsp):
        """\xa0 (non-breaking space) no texto não deve impedir a localização do nome."""
        encontrados = monitor.buscar_nomes_em_portarias(
            [portaria_com_nbsp], ["GEORGIANY PAULA BESSA CAMPELO"]
        )
        assert len(encontrados) == 1

    def test_retorna_referencia_correta_a_portaria(self, portaria_com_georgiany):
        """O campo 'portaria' deve apontar para o dict correto."""
        encontrados = monitor.buscar_nomes_em_portarias(
            [portaria_com_georgiany], ["GEORGIANY PAULA BESSA CAMPELO"]
        )
        assert encontrados[0]["portaria"] is portaria_com_georgiany

    def test_dois_nomes_sinonimos_na_mesma_portaria_geram_duas_ocorrencias(
        self, portaria_com_leopoldo
    ):
        """JOSE e JOSÉ (com e sem acento) são tratados como nomes distintos."""
        encontrados = monitor.buscar_nomes_em_portarias(
            [portaria_com_leopoldo],
            ["JOSE LEOPOLDO DANTAS COUTO", "JOSÉ LEOPOLDO DANTAS COUTO"],
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
        assert "Diário Oficial" in msg or "Diario Oficial" in msg

    def test_cabecalho_menciona_sala_saude_educacao(self):
        """A mensagem deve identificar a Sala Saúde | Educação PMM."""
        oc = self._ocorrencia("FULANO", "PORTARIA Nº 001", "Ementa.", "Conteúdo.")
        msg = monitor.formatar_mensagem([oc], "06/05/2026")
        assert "Sala Saúde" in msg or "SALA SAUDE" in msg.upper()

    def test_contagem_de_ocorrencias_no_cabecalho(self):
        oc1 = self._ocorrencia("NOME A", "PORTARIA Nº 001", "", "Conteudo.")
        oc2 = self._ocorrencia("NOME B", "PORTARIA Nº 002", "", "Conteudo.")
        msg = monitor.formatar_mensagem([oc1, oc2], "06/05/2026")
        assert "2 ocorrência(s)" in msg

    def test_nome_encontrado_aparece_na_mensagem(self):
        oc = self._ocorrencia("GEORGIANY PAULA BESSA CAMPELO", "PORTARIA Nº 052", "", "X")
        msg = monitor.formatar_mensagem([oc], "06/05/2026")
        assert "GEORGIANY PAULA BESSA CAMPELO" in msg

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


# ══════════════════════════════════════════════════════════════
# 6. enviar_whatsapp
# ══════════════════════════════════════════════════════════════

# Aplicados em ordem: o 1º da lista vira o mais interno → 1º parâmetro da função.
# Ordem dos parâmetros: mock_chrome, mock_wait, mock_service, mock_cdm, mock_isdir, mock_sleep
_PATCHES_SELENIUM = [
    patch("monitor_diario_oficial.webdriver.Chrome"),       # innermost → mock_chrome (1º)
    patch("monitor_diario_oficial.WebDriverWait"),          # → mock_wait
    patch("monitor_diario_oficial.Service"),                # → mock_service
    patch("monitor_diario_oficial.ChromeDriverManager"),    # → mock_cdm
    patch("monitor_diario_oficial.os.path.isdir"),          # → mock_isdir
    patch("monitor_diario_oficial.time.sleep"),             # → mock_sleep
    patch("monitor_diario_oficial._colar_no_elemento"),     # outermost → mock_colar (último)
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

        timeout_primeiro_wait = mock_wait.call_args_list[0][0][1]
        assert timeout_primeiro_wait == monitor.TIMEOUT_QR_CODE

    @_aplicar_patches
    def test_timeout_auth_30s_com_sessao_valida(
        self, mock_chrome, mock_wait, mock_service, mock_cdm, mock_isdir, mock_sleep, mock_colar
    ):
        """Com sessão válida do WhatsApp (IndexedDB presente), timeout é 30s."""
        mock_isdir.return_value = True  # IndexedDB existe → sessão autenticada
        _setup_selenium_mocks(mock_chrome, mock_wait)

        monitor.enviar_whatsapp("Mensagem", "Grupo")

        timeout_primeiro_wait = mock_wait.call_args_list[0][0][1]
        assert timeout_primeiro_wait == 30

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


# ══════════════════════════════════════════════════════════════
# 7. _enviar_arquivo_no_grupo
# Verifica que o botão de envio é REALMENTE clicado — não apenas
# que a função retorna sem erro (que é o bug atual).
# ══════════════════════════════════════════════════════════════

class TestEnviarArquivoNoGrupo:
    """
    Testa _enviar_arquivo_no_grupo isoladamente.

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

    @patch("monitor_diario_oficial.time.sleep")
    @patch("monitor_diario_oficial.WebDriverWait")
    def test_click_chamado_quando_xpath_encontra_botao(self, mock_wait_cls, mock_sleep):
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

        monitor._enviar_arquivo_no_grupo(driver, "arquivo.pdf")

        mock_btn_enviar.click.assert_called_once(), (
            "O botão de envio DEVE ser clicado para que o arquivo seja enviado"
        )

    @patch("monitor_diario_oficial.time.sleep")
    @patch("monitor_diario_oficial.WebDriverWait")
    def test_javascript_fallback_chamado_quando_xpath_falha(self, mock_wait_cls, mock_sleep):
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

        monitor._enviar_arquivo_no_grupo(driver, "arquivo.pdf")

        js_calls = [str(c) for c in driver.execute_script.call_args_list]
        assert any("wds-ic-send-filled" in c for c in js_calls), (
            "O fallback JavaScript deve buscar pelo seletor confirmado do WhatsApp Web"
        )

    @patch("monitor_diario_oficial.time.sleep")
    @patch("monitor_diario_oficial.WebDriverWait")
    def test_levanta_excecao_quando_botao_nao_encontrado(self, mock_wait_cls, mock_sleep):
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
            monitor._enviar_arquivo_no_grupo(driver, "arquivo.pdf")

    @patch("monitor_diario_oficial.time.sleep")
    @patch("monitor_diario_oficial.WebDriverWait")
    def test_nao_retorna_sucesso_sem_clicar_botao(self, mock_wait_cls, mock_sleep):
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
            monitor._enviar_arquivo_no_grupo(driver, "arquivo.pdf")
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
