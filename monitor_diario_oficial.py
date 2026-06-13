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

"""Ponto de entrada — orquestra os módulos do pacote src/.

Reexporta as funções e constantes dos submódulos para preservar a API
pública usada pelos testes (monitor_diario_oficial.<nome>).
"""
import os
import sys
import time
from datetime import datetime, timedelta

# Importados para que os testes possam aplicar patch em
# monitor_diario_oficial.requests / .webdriver (módulos compartilhados).
import requests  # noqa: F401
from selenium import webdriver  # noqa: F401

# Submódulos expostos como atributos — permite patch em
# monitor_diario_oficial.whatsapp.WebDriverWait, .scraping.datetime, etc.
from src import config, scraping, parsing, pdf, whatsapp  # noqa: F401

from src.config import (  # noqa: F401
    configurar_logging, log, _atualizar_env,
    NOMES_MONITORADOS, SECRETARIAS_MOSSORO, WHATSAPP_GRUPO, NOME_SALA,
    WHATSAPP_GRUPO_TESTE, TIMEOUT_QR_CODE, BASE_URL,
    WHATSAPP_PROFILE_DIR, LOG_DIR, PDF_TEMP_DIR,
)
from src.scraping import (  # noqa: F401
    obter_data_anterior, buscar_publicacao_por_data,
    buscar_ultima_publicacao, buscar_publicacao_por_numero, extrair_portarias,
)
from src.parsing import (  # noqa: F401
    buscar_nomes_em_portarias, _extrair_dados_fofoca, detectar_fofocas,
    detectar_ponto_facultativo, formatar_ponto_facultativo, promovido_remanejado,
    formatar_fofocas, _extrair_funcao_contrato, formatar_resumo_por_pessoa,
    formatar_mensagem,
)
from src.pdf import (  # noqa: F401
    buscar_url_pdf, _sanitizar_nome_arquivo, extrair_pdfs_por_ocorrencia,
)
from src.whatsapp import (  # noqa: F401
    _colar_windows, _colar_no_elemento, _enviar_arquivos_no_grupo, enviar_whatsapp,
)


def main(modo_teste: bool = False, numero_diario: int | None = None):
    log.info("=" * 60)
    log.info("Iniciando monitoramento do Diário Oficial de Mossoró")
    if modo_teste:
        log.info(f"MODO TESTE ativo — destino: grupo '{WHATSAPP_GRUPO_TESTE}'")
    if numero_diario is not None:
        log.info(f"Edição escolhida para teste: DOM Nº {numero_diario}")
    log.info("=" * 60)

    # Em modo teste, as mensagens vão para o grupo de testes, não para o grupo real.
    grupo_destino = WHATSAPP_GRUPO_TESTE if modo_teste else WHATSAPP_GRUPO

    # 1. Obtém a publicação: por número escolhido (teste) ou a mais recente.
    if numero_diario is not None:
        publicacao = buscar_publicacao_por_numero(numero_diario)
        if not publicacao:
            log.warning(f"Edição Nº {numero_diario} não encontrada no DOM. Encerrando.")
            return
    else:
        publicacao = buscar_ultima_publicacao()
        if not publicacao:
            log.warning("Não foi possível obter a última edição do DOM. Encerrando.")
            return

    # 2. Verifica se a edição já foi monitorada (evita reprocessar a mesma edição).
    #    Em modo teste, trata ULTIMO_DOM_NUMERO como 0 para sempre reprocessar a
    #    edição mais recente, mesmo que já tenha sido monitorada.
    numero_atual = publicacao.get("numero")
    ultimo_salvo = 0 if modo_teste else int(os.environ.get("ULTIMO_DOM_NUMERO", "0"))
    if numero_atual is not None and numero_atual <= ultimo_salvo:
        log.info(
            f"Edição Nº {numero_atual} já foi monitorada "
            f"(último número salvo: {ultimo_salvo}). Encerrando."
        )
        return

    # 2a. Persiste o número da edição atual no .env para evitar reprocessamento futuro.
    #     Em modo teste NÃO persiste, para não interferir no rastreamento real.
    if numero_atual is not None and not modo_teste:
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

    # 4a2. Detecta ponto facultativo (decreto geral, varredura independente)
    pontos_facultativos = detectar_ponto_facultativo(portarias)

    # 4b. Formata a seção de fofocas (sempre exibe o bloco, mesmo sem movimentações);
    #     o aviso de ponto facultativo, quando houver, é anexado ao final.
    secao_fofoca = formatar_fofocas(fofocas, pontos_facultativos)
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
        enviar_whatsapp(mensagem_vazia, grupo_destino, mensagem_apos_pdf=secao_fofoca)
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
    sucesso = enviar_whatsapp(mensagem, grupo_destino, caminhos_pdf, mensagem_apos_pdf=secao_fofoca)

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


def _extrair_numero_teste(argv: list[str]) -> int | None:
    """
    Retorna o número da edição informado logo após a flag --test, se houver.

    Ex.: ["prog", "--test", "839"] → 839
         ["prog", "--test"]        → None  (usa a edição mais recente)
         ["prog", "--test", "--x"] → None  (token seguinte não é número)
    """
    if "--test" not in argv:
        return None
    idx = argv.index("--test")
    if idx + 1 < len(argv) and argv[idx + 1].isdigit():
        return int(argv[idx + 1])
    return None


if __name__ == "__main__":
    # ── Modo teste ────────────────────────────────────────────────────────────
    # Acionado por: python monitor_diario_oficial.py --test [NÚMERO]
    # Sem número → edição mais recente. Com número (ex.: --test 839) → busca essa
    # edição específica pelo nº do DOM. Em ambos: trata ULTIMO_DOM_NUMERO como 0
    # (sempre reprocessa) e envia ao grupo de testes (WHATSAPP_GRUPO_TESTE), sem
    # alterar o rastreamento real no .env.
    if "--test" in sys.argv:
        main(modo_teste=True, numero_diario=_extrair_numero_teste(sys.argv))
    # ── Modo agendado (execução contínua) ────────────────────────────────────
    # Acionado APENAS por: python monitor_diario_oficial.py --agendar
    # HORARIO_EXECUCAO define o horário, mas NÃO ativa o modo sozinho.
    # Agendamento externo (Claude Routines, Task Scheduler, cron):
    #   → execute sem --agendar; o script roda uma vez e encerra.
    elif "--agendar" in sys.argv:
        horario = os.environ.get("HORARIO_EXECUCAO", "05:00").strip()
        _agendar_execucao(horario)
    else:
        # ── Execução pontual (padrão) ────────────────────────────────────────
        # Roda uma única vez e encerra — modo correto para agendamento externo.
        main()