"""Saída das mensagens no terminal (modo --terminal, sem WhatsApp).

Substitui o envio via WhatsApp: nada é enviado e NENHUM PDF é baixado ou
fatiado. Apenas imprime no terminal, bem formatadas, as mensagens que seriam
enviadas (texto principal e, quando houver, a Fofoca da Secretaria).
"""
from .config import log


_LARGURA = 60


def _bloco(titulo: str, conteudo: str) -> str:
    """Monta um bloco com cabeçalho destacado e o conteúdo abaixo."""
    barra = "═" * _LARGURA
    return f"\n{barra}\n {titulo}\n{barra}\n{conteudo.rstrip()}\n"


def imprimir_no_terminal(
    mensagem: str,
    grupo: str,
    caminhos_pdf: list[str] | None = None,
    mensagem_apos_pdf: str = "",
) -> bool:
    """Imprime no terminal as mensagens que seriam enviadas ao WhatsApp.

    Drop-in de ``enviar_whatsapp`` para o modo --terminal: mantém a mesma
    assinatura essencial, mas não abre o navegador, não envia nada e não
    manipula PDFs. ``caminhos_pdf`` é aceito por compatibilidade e ignorado
    (no modo terminal o PDF nem chega a ser baixado/fatiado).

    Retorna sempre True — imprimir no terminal não falha o fluxo.
    """
    partes = [
        "\n" + "█" * _LARGURA,
        f" MODO TERMINAL — nada será enviado ao WhatsApp",
        f" Destino que seria usado: {grupo}",
        "█" * _LARGURA,
        _bloco("MENSAGEM PRINCIPAL", mensagem),
    ]

    if mensagem_apos_pdf and mensagem_apos_pdf.strip():
        partes.append(_bloco("FOFOCA DA SECRETARIA", mensagem_apos_pdf))

    partes.append("█" * _LARGURA + "\n")

    saida = "\n".join(partes)
    # print() garante a exibição no terminal mesmo quando o logging está
    # direcionado a arquivo; o log fica como registro de que o modo rodou.
    print(saida)
    log.info("Mensagens exibidas no terminal (modo --terminal, sem envio ao WhatsApp).")
    return True
