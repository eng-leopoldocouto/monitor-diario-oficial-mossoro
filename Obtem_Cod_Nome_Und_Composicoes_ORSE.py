import requests
import re

def extrairTables(html):

    regex_tabela_central = re.compile(
        r'<table[^>]*class=["\']TabelaCentral["\'][^>]*>[\s\S]*?<\/table>[\s\S]*?<\/body>',
        re.I
    )

    match = regex_tabela_central.search(html)

    if not match:
        print("TabelaCentral não encontrada")
        return []

    conteudo_td = match.group(0)

    regex_tables_internas = re.compile(r"<table[\s\S]*?<\/table>", re.I)
    tables_separadas = regex_tables_internas.findall(conteudo_td)

    return tables_separadas


def limpar_html(html):
    return (html
        .replace("&nbsp;", " ")
        .replace("&ccedil;", "ç")
        .replace("&aacute;", "á")
        .replace("&eacute;", "é")
        .replace("&atilde;", "ã")
        .replace("&oacute;", "ó")
        .replace("&uacute;", "ú")
        .replace("&amp;", "&")
    )
def agrupar_extraindo_texto(composicoes_div, qtd):

    regex_img = re.compile(r'src="([^"]+)"', re.I)
    regex_remove_tags = re.compile(r'<[^>]*>')

    array_base = composicoes_div[1:]
    grupos = []

    for i in range(0, len(array_base), qtd):

        bloco = array_base[i:i+qtd]
        bloco_processado = []

        for div in bloco:

            # 🔹 Se tiver imagem → retorna nome do arquivo
            match_img = regex_img.search(div)
            if match_img:
                caminho = match_img.group(1)
                nome_arquivo = caminho.split('/')[-1]
                bloco_processado.append(nome_arquivo.split('.')[0])
                continue

            # 🔹 Remove TODAS as tags HTML
            texto_limpo = regex_remove_tags.sub('', div).strip()

            bloco_processado.append(texto_limpo if texto_limpo else None)

        grupos.append(bloco_processado)

    return grupos
def main():
    for codigo in range(1, 50001):

        url = f"https://orse.cehop.se.gov.br/composicao.asp?font_sg_fonte=ORSE&serv_nr_codigo={codigo}&peri_nr_ano=2025&peri_nr_mes=12&peri_nr_ordem=1"
        response = requests.get(url)
        if response.status_code != 200:
            print(f"{codigo} - {response.status_code}")
            continue

        response = requests.get(url)

        if response.status_code != 200:
            return

        html = response.content.decode("ISO-8859-1")
        html = limpar_html(html)
        resultado = extrairTables(html)

        # TABELA DESCRIÇÃO
        tables_com_descricao = [table for table in resultado if re.search(r"Descrição\s+do\s+Serviço", table, re.I)]
        regex_div = re.compile(r"<td [\s\S]*?>[\s\S]*?<\/td>", re.I)
        composicoes_td = regex_div.findall(tables_com_descricao[0])
        grupos = agrupar_extraindo_texto(composicoes_td, 3)
        with open("arquivo.txt", "a", encoding="utf-8") as arquivo:
            arquivo.write(f"{grupos[1]}\n")

main()