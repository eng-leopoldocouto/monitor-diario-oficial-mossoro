# 📰 Monitor do Diário Oficial de Mossoró

Ferramenta que lê automaticamente o [Diário Oficial do Município de Mossoró (DOM)](https://dom.mossoro.rn.gov.br) todos os dias e envia um resumo diretamente em um grupo do WhatsApp — com os atos que citam as pessoas monitoradas, os PDFs das páginas relevantes e uma seção de movimentações de pessoal nas secretarias.

---

## O que o programa faz

1. **Acessa o site do DOM** e localiza a edição mais recente publicada.
2. **Lê todos os atos** da edição (portarias, decretos, extratos de contrato, etc.).
3. **Busca os nomes** que você configurou em cada ato.
4. **Gera PDFs** com apenas as páginas do Diário Oficial onde cada ato aparece — sem enviar o documento inteiro.
5. **Detecta movimentações de pessoal** nas secretarias municipais (nomeações, exonerações, promoções e remanejamentos).
6. **Envia tudo para um grupo do WhatsApp**:
   - Mensagem de texto com o resumo das ocorrências
   - Os PDFs recortados, todos de uma vez
   - A "Fofoca da Secretaria" com as movimentações de pessoal

Se nenhum nome for encontrado na edição do dia, o grupo recebe uma mensagem informando que não houve ocorrências.

---

## Pré-requisitos

Antes de tudo, você precisa ter instalado no computador:

| O que | Por quê | Onde baixar |
|---|---|---|
| **Python 3.11 ou mais recente** | Linguagem em que o programa foi escrito | [python.org/downloads](https://www.python.org/downloads/) |
| **Google Chrome** | Usado para abrir o WhatsApp Web e enviar as mensagens | [google.com/chrome](https://www.google.com/chrome/) |

> **Windows:** durante a instalação do Python, marque a opção **"Add Python to PATH"**.

---

## Instalação (passo a passo)

### 1. Baixe o projeto

Clique em **Code → Download ZIP** no GitHub, extraia a pasta ou, se tiver Git instalado:

```bash
git clone https://github.com/eng-leopoldocouto/monitor-diario-oficial-mossoro.git
cd monitor-diario-oficial-mossoro
```

### 2. Instale as dependências

Abra o terminal/prompt de comando **dentro da pasta do projeto** e execute:

```bash
pip install -r requirements.txt
```

Isso instala automaticamente todas as bibliotecas necessárias.

### 3. Crie o arquivo de configuração

Copie o arquivo de exemplo:

```bash
# Linux / macOS
cp .env.example .env

# Windows (Prompt de Comando)
copy .env.example .env
```

Abra o arquivo `.env` em qualquer editor de texto (Bloco de Notas, VS Code, etc.) e preencha os campos:

```env
# Nomes que o programa vai procurar no Diário Oficial
# Use MAIÚSCULAS. Separe múltiplos nomes por vírgula.
# Inclua a versão com e sem acento para não perder nada.
NOMES_MONITORADOS=FULANO DE TAL,BELTRANA PEREIRA SOUZA

# Nome EXATO do grupo do WhatsApp onde as mensagens serão enviadas
# (copie o nome direto do WhatsApp, incluindo emojis se houver)
WHATSAPP_GRUPO=Nome Do Grupo Aqui

# Identificação que aparece no cabeçalho de cada mensagem enviada
NOME_SALA=Minha Equipe

# Horário de execução automática (formato HH:MM, fuso horário local)
HORARIO_EXECUCAO=05:00

# Segundos disponíveis para escanear o QR code do WhatsApp na 1ª execução
TIMEOUT_QR_CODE=120
```

> **Importante:** o arquivo `.env` nunca é enviado ao GitHub — ele fica apenas no seu computador. Não compartilhe esse arquivo com ninguém.

---

## Como usar

### Execução manual (uma vez)

```bash
python monitor_diario_oficial.py
```

O Chrome abrirá automaticamente com o WhatsApp Web. **Na primeira vez**, será necessário escanear o QR code com o celular (da mesma forma que você faria em [web.whatsapp.com](https://web.whatsapp.com)). A sessão fica salva na pasta `.whatsapp_profile/` — nas próximas execuções o Chrome já abre autenticado.

### Execução automática (modo agendado)

Para deixar o programa rodando e disparar sozinho todos os dias no horário definido em `HORARIO_EXECUCAO`:

```bash
python monitor_diario_oficial.py --agendar
```

O programa fica ativo em segundo plano, executa no horário configurado e aguarda o próximo dia. Se o horário do dia já tiver passado quando você iniciar, ele executa imediatamente e depois aguarda o dia seguinte.

> **Dica para Windows:** use o **Agendador de Tarefas** do Windows para iniciar o script automaticamente no boot da máquina, sem precisar deixar um terminal aberto.

---

## O que chega no WhatsApp

### Quando há ocorrências

**1ª mensagem — Resumo das ocorrências:**
```
📢 MONITORAMENTO — DIÁRIO OFICIAL DE MOSSORÓ

👥 Minha Equipe

📅 Edição: 09/05/2026
🔍 2 ocorrência(s) encontrada(s)

━━━━━━━━━━━━━━━━━━
1. Nome: FULANO DE TAL
Ato: PORTARIA Nº 37, DE 08 DE MAIO DE 2026
Ementa: Nomeia servidor...
```

**2ª mensagem — PDFs** com as páginas exatas de cada portaria (todos os arquivos de uma vez).

**3ª mensagem — Fofoca da Secretaria:**
```
🗣️ FOFOCA DA SECRETARIA
3 movimentação(ões) de pessoal detectada(s)

🔝 FULANO DE TAL foi PROMOVIDO(A)!
   De: Assessor (CC15) na Secretaria De Saúde
   Para: Diretor (CC11) na Secretaria De Educação

🔥 BELTRANA SILVA foi NOMEADA no cargo de
   Coordenadora (CC12) na Secretaria De Finanças!

🚪 CICLANO SOUZA deixou a casa! Foi EXONERADO(A)
   do cargo de Gerente (CC13) na Secretaria De Obras.
```

### Quando não há ocorrências

```
📢 MONITORAMENTO — DIÁRIO OFICIAL DE MOSSORÓ
👥 Minha Equipe
📅 Edição: 09/05/2026

❌ Nenhuma ocorrência encontrada para os nomes monitorados nesta edição.
```

Seguida da Fofoca da Secretaria normalmente.

---

## Configurações avançadas (opcionais)

Todas podem ser adicionadas ao arquivo `.env`:

| Variável | O que faz | Padrão |
|---|---|---|
| `SECRETARIAS_MOSSORO` | Lista de secretarias monitoradas pela "Fofoca" (separadas por vírgula) | Todas as secretarias do município |
| `WHATSAPP_PROFILE_DIR` | Caminho da pasta onde a sessão do WhatsApp é salva | `.whatsapp_profile/` ao lado do script |
| `LOG_DIR` | Pasta onde o arquivo de log é gravado | Mesma pasta do script |
| `PDF_TEMP_DIR` | Pasta onde os PDFs recortados são salvos antes do envio | `pdfs_temporarios/` ao lado do script |

---

## Estrutura do projeto

```
monitor-diario-oficial-mossoro/
├── monitor_diario_oficial.py   # Script principal
├── test_monitor_diario_oficial.py  # Testes automatizados
├── requirements.txt            # Dependências Python
├── .env.example                # Modelo de configuração (versão pública)
├── .env                        # Sua configuração real (não versionado)
└── .gitignore                  # Arquivos ignorados pelo Git
```

Pastas criadas automaticamente durante o uso:

```
├── .whatsapp_profile/          # Sessão do Chrome/WhatsApp (não versionada)
├── pdfs_temporarios/           # PDFs gerados antes do envio (apagados após envio)
└── monitor_dom.log             # Log de execução (rotativo, máx. 5 MB)
```

---

## Rodando os testes

O projeto possui 115 testes automatizados. Para executá-los:

```bash
pip install pytest
pytest test_monitor_diario_oficial.py -v
```

Todos os testes rodam sem depender de internet, WhatsApp ou Chrome — usam dados simulados (mocks).

---

## Solução de problemas

**O Chrome abre mas o QR code não aparece ou expira**
- Aumente o valor de `TIMEOUT_QR_CODE` no `.env` (ex.: `TIMEOUT_QR_CODE=180`).
- Certifique-se de que o celular tem acesso à internet no momento do escaneamento.

**"Grupo não encontrado" no log**
- O nome em `WHATSAPP_GRUPO` deve ser **idêntico** ao nome do grupo no WhatsApp, incluindo espaços, letras maiúsculas e emojis.

**Nomes não estão sendo encontrados mesmo aparecendo no Diário**
- O DOM usa PDF com texto; verifique se o nome está em MAIÚSCULAS no `.env`.
- Inclua variantes com e sem acento: `JOSE SILVA,JOSÉ SILVA`.

**O programa fecha sem enviar nada**
- Verifique o arquivo `monitor_dom.log` — ele contém o detalhe completo de cada etapa.

**"Variável de ambiente obrigatória não definida"**
- O arquivo `.env` não foi criado ou está faltando um dos campos obrigatórios (`NOMES_MONITORADOS`, `WHATSAPP_GRUPO`, `NOME_SALA`).

---

## Como contribuir

Contribuições são bem-vindas! Siga os passos abaixo:

### 1. Fork e clone

```bash
git clone https://github.com/eng-leopoldocouto/monitor-diario-oficial-mossoro.git
cd monitor-diario-oficial-mossoro
pip install -r requirements.txt
```

### 2. Crie um branch para sua mudança

```bash
git checkout -b minha-melhoria
```

### 3. Faça as alterações e rode os testes

```bash
pytest test_monitor_diario_oficial.py -v
```

Todos os 115 testes devem passar antes de abrir o Pull Request. Se você adicionar uma nova funcionalidade, adicione também o teste correspondente.

### 4. Envie o Pull Request

Abra o PR descrevendo **o que foi mudado** e **por quê**. Se a mudança corrige um bug, mencione como reproduzi-lo.

---

### Boas práticas para contribuidores

- **Nunca coloque dados reais** (nomes, grupos, senhas) no código — use sempre variáveis de ambiente lidas do `.env`.
- **Mantenha o `.env.example`** atualizado se adicionar novas variáveis de ambiente.
- **Escreva testes** para novas funcionalidades — o projeto usa `pytest` com mocks (sem depender de internet ou WhatsApp real).
- **Siga o estilo existente**: comentários em português, nomes de variáveis e funções em português com `snake_case`.
- O log deve ser informativo: use `log.info` para passos normais, `log.warning` para situações inesperadas mas recuperáveis, e `log.error` para falhas.

### Áreas onde contribuições são especialmente úteis

- Suporte a outros municípios com Diário Oficial semelhante
- Melhoria nos seletores do WhatsApp Web (o WhatsApp atualiza a interface periodicamente)
- Melhoria na extração de cargos e símbolos CC da "Fofoca da Secretaria"
- Testes de integração com o site real do DOM

---

## Licença

Este projeto é de uso livre. Consulte o arquivo `LICENSE` para detalhes (se presente), ou entre em contato com o autor para uso comercial.
