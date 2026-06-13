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
   - Mensagem de texto com um **resumo por pessoa** — em cada portaria, a função
     designada (Gestor / Gestor Substituto / Fiscal / Fiscal Substituto) e o nº do
     contrato — seguido dos atos detalhados; vários nomes na mesma portaria são
     agrupados em um único bloco
   - Os PDFs recortados, todos de uma vez
   - A "Fofoca da Secretaria" com as movimentações de pessoal e, quando houver,
     um aviso de **ponto facultativo**

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

# Grupo de testes — destino das mensagens quando rodar com a flag --test
# (opcional; se omitido, usa "TESTES SCRIPTs")
WHATSAPP_GRUPO_TESTE=TESTES SCRIPTs

# Identificação que aparece no cabeçalho de cada mensagem enviada
NOME_SALA=Minha Equipe

# Horário de execução automática (formato HH:MM, fuso horário local)
HORARIO_EXECUCAO=05:00

# Segundos disponíveis para escanear o QR code do WhatsApp na 1ª execução
TIMEOUT_QR_CODE=120
```

> **Importante:** o arquivo `.env` nunca é enviado ao GitHub — ele fica apenas no seu computador. Não compartilhe esse arquivo com ninguém. **Nunca** coloque nomes reais ou o nome do grupo real em arquivos versionados (código, testes, `.env.example`); use apenas dados fictícios.

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

### Modo de teste

```bash
python monitor_diario_oficial.py --test
```

Roda uma única vez **reprocessando a edição mais recente** (trata `ULTIMO_DOM_NUMERO` como `0`) e envia as mensagens para o **grupo de testes** definido em `WHATSAPP_GRUPO_TESTE` (padrão: `TESTES SCRIPTs`), sem alterar o controle de edições já monitoradas. Útil para validar o formato das mensagens sem incomodar o grupo real.

#### Testar uma edição específica

Para testar uma edição que **não** é a mais recente, informe o número do DOM logo após `--test`:

```bash
python monitor_diario_oficial.py --test 839
```

O script procura na listagem do site a edição `DOM Nº 839`, resolve a URL correta da publicação e processa essa edição (enviando ao grupo de testes, como qualquer `--test`). Se o número não existir, o script avisa e encerra sem enviar nada.

O modo de teste difere da execução normal em três pontos:

| | Execução normal | `--test` |
|---|---|---|
| Grupo de destino | `WHATSAPP_GRUPO` | `WHATSAPP_GRUPO_TESTE` |
| Edição reprocessada? | Não (pula se já monitorada) | Sim (ignora `ULTIMO_DOM_NUMERO`) |
| Atualiza `ULTIMO_DOM_NUMERO` no `.env`? | Sim | Não |

> Para usar, configure `WHATSAPP_GRUPO_TESTE` no `.env` com o nome **exato** do
> grupo de testes no WhatsApp. Se a variável não existir, o valor padrão
> `TESTES SCRIPTs` é usado.

---

## O que chega no WhatsApp

### Quando há ocorrências

**1ª mensagem — Resumo das ocorrências:** começa com um bloco **RESUMO — POR PESSOA**
(índice de leitura rápida) e, em seguida, traz os blocos detalhados de cada portaria.
No resumo, cada portaria aparece com a **função designada** à pessoa — *Gestor*,
*Gestor Substituto*, *Fiscal* ou *Fiscal Substituto* — e o **nº do contrato**. Quando
**vários nomes monitorados aparecem na mesma portaria**, eles são agrupados em um único
bloco detalhado, com os nomes separados por `+`.

```
📢 MONITORAMENTO — DIÁRIO OFICIAL DE MOSSORÓ

👥 Minha Equipe

📅 EDIÇÃO Nº 832: 09/05/2026
🔍 2 ocorrência(s) encontrada(s)

📋 RESUMO — POR PESSOA
2 nome(s) monitorado(s) encontrado(s)

👤 FULANO DE TAL (2)
   • Portaria 35 — Gestor · Contrato 12/2025
   • Portaria 37 — Gestor Substituto · Contrato 20/2025

👤 BELTRANA SOUZA (1)
   • Portaria 35 — Fiscal Substituto · Contrato 12/2025

━━━━━━━━━━━━━━━━━━
1. Nome: FULANO DE TAL + BELTRANA SOUZA
Ato: PORTARIA Nº 35, DE 08 DE MAIO DE 2026

(conteúdo completo da portaria...)

━━━━━━━━━━━━━━━━━━
2. Nome: FULANO DE TAL
Ato: PORTARIA Nº 37, DE 08 DE MAIO DE 2026

(conteúdo completo da portaria...)
```

> A função e o contrato são extraídos do texto da portaria ("...para atuar como
> *GESTOR DO CONTRATO* n° XX/AAAA..." e "...tendo como *substituto eventual*..."). Se
> não for possível identificar, mostra `função não identificada`.

> A contagem `🔍 N ocorrência(s)` conta **portarias distintas** (não nomes repetidos):
> uma portaria com dois nomes monitorados é uma ocorrência.

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

🍹 SEXTOU OFICIAL?
Saiu no Diário: ponto facultativo na sexta, 21/11/2025! Já pode planejar a folga... 🏖️ (exceto serviços essenciais, claro 😅)
```

> **Ponto facultativo:** sempre que a edição traz um decreto declarando *ponto
> facultativo*, um aviso é anexado ao **final** da Fofoca — mesmo nas edições sem
> movimentações de pessoal. O programa extrai a data e calcula o dia da semana
> (manchete adaptável: sexta-feira → *"SEXTOU OFICIAL?"*; demais dias → *"FOLGA À
> VISTA!"*). Datas diferentes geram avisos separados; se a data não for identificada,
> exibe um aviso genérico. *(Apenas texto — o PDF do decreto não é anexado.)*

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
| `WHATSAPP_GRUPO_TESTE` | Grupo de destino quando rodar com a flag `--test` | `TESTES SCRIPTs` |

---

## Tratamento de dados pessoais (LGPD)

Este projeto trata dados pessoais (nomes de servidores) e, portanto, observa a
Lei nº 13.709/2018 (LGPD). Resumo do tratamento:

- **Finalidade:** acompanhar atos administrativos publicados no Diário Oficial de
  Mossoró que citem nomes previamente definidos pelo responsável, para fins de
  informação interna da equipe.
- **Origem dos dados:** fonte **pública oficial** (o próprio Diário Oficial do
  Município), acessada sem autenticação.
- **Base legal:** dado de acesso público tratado conforme o art. 7º, §3º da LGPD,
  respeitando boa-fé, finalidade legítima e os direitos do titular.
- **Destinatários:** apenas os membros do grupo de WhatsApp configurado em
  `WHATSAPP_GRUPO`. Restrinja esse grupo às pessoas estritamente necessárias.
- **Armazenamento e retenção:** os dados não são gravados em banco. Há apenas
  artefatos **locais e temporários**: PDFs em `pdfs_temporarios/` (removidos após
  o envio) e logs em `monitor_dom.log`. Recomenda-se **expurgar os logs
  periodicamente** (ex.: a cada 30 dias), pois podem conter nomes.
- **Dados sensíveis:** o arquivo `.env` (nomes monitorados e grupos) **não é
  versionado** e não deve ser compartilhado. Nunca inclua nomes reais no código,
  nos testes ou em qualquer arquivo versionado — use sempre dados fictícios.
- **Direitos do titular:** solicitações de informação, correção ou exclusão devem
  ser encaminhadas ao responsável pela operação do monitor.

---

## Estrutura do projeto

```
monitor-diario-oficial-mossoro/
├── monitor_diario_oficial.py   # Ponto de entrada — orquestra os módulos do src/
├── src/                        # Código organizado por responsabilidade
│   ├── config.py               # Variáveis de ambiente, constantes e logging
│   ├── scraping.py             # Busca de edições e extração de atos do site
│   ├── parsing.py              # Portarias, fofocas, ponto facultativo e mensagens
│   ├── pdf.py                  # Download e fatiamento de PDFs por ocorrência
│   └── whatsapp.py             # Envio de mensagens e arquivos via WhatsApp Web
├── test_monitor_diario_oficial.py  # Testes automatizados
├── requirements.txt            # Dependências Python
├── .env.example                # Modelo de configuração (versão pública)
├── .env                        # Sua configuração real (não versionado)
└── .gitignore                  # Arquivos ignorados pelo Git
```

O comando de execução não muda: `monitor_diario_oficial.py` continua sendo o
ponto de entrada e reexporta toda a API pública dos módulos em `src/`.

Pastas criadas automaticamente durante o uso:

```
├── .whatsapp_profile/          # Sessão do Chrome/WhatsApp (não versionada)
├── pdfs_temporarios/           # PDFs gerados antes do envio (apagados após envio)
└── monitor_dom.log             # Log de execução (rotativo, máx. 5 MB)
```

---

## Bibliotecas utilizadas

Todas as dependências são instaladas automaticamente pelo `pip install -r requirements.txt`.

| Biblioteca | Versão mínima | Para que serve |
|---|---|---|
| [requests](https://docs.python-requests.org/) | 2.31.0 | Faz as requisições HTTP ao site do Diário Oficial para baixar as páginas e o PDF |
| [beautifulsoup4](https://www.crummy.com/software/BeautifulSoup/) | 4.12.0 | Analisa o HTML das páginas do DOM para extrair links, títulos e conteúdo dos atos |
| [selenium](https://www.selenium.dev/) | 4.18.0 | Controla o Chrome automaticamente para abrir o WhatsApp Web e enviar mensagens e arquivos |
| [webdriver-manager](https://github.com/SergeyPirogov/webdriver_manager) | 4.0.0 | Baixa e gerencia automaticamente a versão correta do ChromeDriver (sem instalação manual) |
| [pypdf](https://pypdf.readthedocs.io/) | 4.0.0 | Lê e recorta o PDF do Diário Oficial, extraindo apenas as páginas de cada portaria |
| [python-dotenv](https://github.com/theskumar/python-dotenv) | 1.0.0 | Carrega as configurações do arquivo `.env` para as variáveis de ambiente do programa |

> As bibliotecas `io`, `os`, `re`, `sys`, `time`, `logging`, `platform` e `unicodedata` são nativas do Python — não precisam ser instaladas.

---

## Rodando os testes

O projeto possui 129 testes automatizados. Para executá-los:

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

Todos os 129 testes devem passar antes de abrir o Pull Request. Se você adicionar uma nova funcionalidade, adicione também o teste correspondente.

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

## Roadmap

### 🐳 Docker e Docker Compose (planejado)

Em uma versão futura, o projeto terá suporte a **Docker** e **Docker Compose**, permitindo executar o monitor em qualquer sistema operacional — Windows, macOS e Linux — sem precisar instalar Python, Chrome ou ChromeDriver manualmente.

Com Docker, o fluxo de instalação será simplificado para:

```bash
# Copiar e preencher o .env
cp .env.example .env

# Subir o container
docker compose up -d
```

Toda a configuração de ambiente (Python, Chrome, ChromeDriver, dependências) ficará encapsulada no container, tornando a implantação mais simples, portátil e reproduzível em qualquer máquina.

---

## Licença

Este projeto é de uso livre. Consulte o arquivo `LICENSE` para detalhes (se presente), ou entre em contato com o autor para uso comercial.
