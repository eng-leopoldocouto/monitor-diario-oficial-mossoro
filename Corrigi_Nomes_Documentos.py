import os
import urllib.parse

def renomear_arquivos():
    # Pega o diretório onde o script está
    pasta_atual = os.path.dirname(os.path.abspath(__file__))
    
    for nome_arquivo in os.listdir(pasta_atual):
        # Ignora o próprio script para evitar erros
        if nome_arquivo == os.path.basename(__file__):
            continue

        # Decodifica caracteres de URL (como %C2%B0, %20, etc) de uma vez só
        nome_novo = urllib.parse.unquote(nome_arquivo)

        # Substitui o sufixo duplicado "_assinado_assinado" por "_assinado"
        if "_assinado_assinado" in nome_novo:
            nome_novo = nome_novo.replace("_assinado_assinado", "_assinado")
            
        # Só tenta renomear se o nome realmente mudou
        if nome_novo != nome_arquivo:
            caminho_antigo = os.path.join(pasta_atual, nome_arquivo)
            caminho_novo = os.path.join(pasta_atual, nome_novo)

            if not os.path.exists(caminho_novo):
                try:
                    os.rename(caminho_antigo, caminho_novo)
                    print(f'Sucesso: "{nome_arquivo}" → "{nome_novo}"')
                except Exception as e:
                    print(f'Erro ao renomear "{nome_arquivo}": {e}')
            else:
                print(f'Ignorado (já existe): "{nome_novo}"')

if __name__ == "__main__":
    renomear_arquivos()