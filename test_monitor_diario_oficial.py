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

        resultado = monitor.enviar_whatsapp("Mensagem de teste", "Grupo Teste")

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
