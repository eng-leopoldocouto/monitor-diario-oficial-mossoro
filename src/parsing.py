"""Parsing e formatação: portarias, fofocas, ponto facultativo e mensagens."""
import re
import unicodedata
from datetime import datetime

from .config import log, NOME_SALA


def buscar_nomes_em_portarias(portarias: list[dict], nomes: list[str]) -> list[dict]:
    """
    Varre todas as portarias buscando os nomes da lista monitorada.

    Retorna uma lista de ocorrências, cada uma com:
        nome      - nome encontrado
        portaria  - dicionário com dados da portaria onde foi achado
    """
    encontrados = []
    nomes_upper = [n.upper() for n in nomes]
    for portaria in portarias:
        texto_busca = " ".join(portaria["conteudo"].upper().split())
        for nome in nomes_upper:
            if nome in texto_busca:
                # debug (não info) para não expor nome (PII) no console
                log.debug(f"Nome encontrado: '{nome}' na portaria: {portaria['titulo']}")
                encontrados.append({
                    "nome": nome,
                    "portaria": portaria,
                })

    return encontrados


def _extrair_dados_fofoca(paragrafo: str, secretaria: str) -> dict | None:
    """
    Extrai nome, ação, cargo e símbolo CC de um parágrafo de portaria.
    Retorna None se não conseguir extrair ação + pessoa mínimos.

    O parágrafo pode chegar em NFKD (vindo de detectar_fofocas) — é normalizado
    para NFC internamente para que as regexes com acentos compostos funcionem.

    Padrões suportados:
      NOMEAR: "NOMEAR <NOME> PARA EXERCER O CARGO EM COMISSÃO DE <CARGO>, SÍMBOLO <CC>"
      EXONERAR: "EXONERAR [A SERVIDORA|O SERVIDOR] <NOME> DO CARGO EM COMISSÃO DE <CARGO>"
    """
    # Normaliza para NFC: detectar_fofocas usa NFKD para comparar secretarias,
    # mas as regexes esperam chars acentuados compostos (ex: "Ã" e não "A"+combining).
    paragrafo = unicodedata.normalize("NFC", paragrafo)
    secretaria = unicodedata.normalize("NFC", secretaria)

    MAPA_ACAO = {
        "NOMEAR":    "NOMEADO(A)",
        "NOMEIA":    "NOMEADO(A)",
        "NOMEADO":   "NOMEADO(A)",
        "NOMEADA":   "NOMEADO(A)",
        "EXONERAR":  "EXONERADO(A)",
        "EXONERA":   "EXONERADO(A)",
        "EXONERADO": "EXONERADO(A)",
        "EXONERADA": "EXONERADO(A)",
    }

    # Ação
    m_acao = re.search(
        r'\b(NOMEAR|NOMEIA|NOMEADO[A]?|EXONERAR|EXONERA|EXONERADO[A]?)\b',
        paragrafo,
    )
    if not m_acao:
        return None
    acao = MAPA_ACAO.get(m_acao.group(1), "NOMEADO(A)")

    # Nome da pessoa — estratégia diferente por tipo de ação:
    #
    # NOMEAR: "NOMEAR <NOME> PARA EXERCER..."
    #   → nome termina antes de "PARA"
    #
    # EXONERAR: "EXONERAR [A SERVIDORA|O SERVIDOR] <NOME> DO CARGO..."
    #   → skipa artigo + "servidor(a)" opcionais; nome termina antes de "DO/DA CARGO"
    #
    # Usamos regex gananciosa com backtracking: o grupo captura o máximo possível
    # de palavras e recua até o lookahead de parada ser satisfeito — isso permite
    # nomes com preposições internas como "GURGEL DA NOBREGA".
    _LETRAS = r'[A-ZÁÉÍÓÚÂÊÎÔÛÃÕÀÈÌÒÙÇ]'
    _PALAVRA = rf'{_LETRAS}+'
    _NOME_GREED = rf'(?:{_PALAVRA}\s+)*{_PALAVRA}'  # sequência greedy de palavras

    acao_str = m_acao.group(1)
    m_nome = None

    # Qualificador opcional entre vírgulas após o verbo:
    # ex. "EXONERAR, a pedido, o servidor …"
    #     "EXONERAR, a bem do serviço, a servidora …"
    #     "NOMEAR, nos termos do art. 5º, FULANO …"
    _QUALIF = r'(?:,\s*[^,\r\n]+,)?'

    if acao_str.startswith("NOME"):
        # NOMEAR / NOMEIA / NOMEADO(A): nome termina antes de "PARA"
        m_nome = re.search(
            rf'\b(?:NOMEAR|NOMEIA|NOMEADO[A]?){_QUALIF}\s+({_NOME_GREED})(?=\s+PARA\b)',
            paragrafo,
        )
        if not m_nome:
            # Fallback: captura até 7 palavras maiúsculas (padrão anterior)
            m_nome = re.search(
                rf'\b(?:NOMEAR|NOMEIA|NOMEADO[A]?){_QUALIF}\s+'
                rf'((?:{_LETRAS}{{2,}}\s+){{0,6}}{_LETRAS}{{2,}})',
                paragrafo,
            )
    else:
        # EXONERAR / EXONERA / EXONERADO(A): pula qualificador e "a servidora"/"o servidor"
        m_nome = re.search(
            rf'\b(?:EXONERAR|EXONERA|EXONERADO[A]?){_QUALIF}\s+'
            rf'(?:(?:A|O)\s+)?(?:SERVIDORA?\s+)?'
            rf'({_NOME_GREED})(?=\s+(?:DO|DA|AO|NO|EM)\s+CARGO\b)',
            paragrafo,
        )
        if not m_nome:
            # Fallback: pula artigo/servidor mas sem lookahead de parada
            m_nome = re.search(
                rf'\b(?:EXONERAR|EXONERA|EXONERADO[A]?){_QUALIF}\s+'
                rf'(?:(?:A|O)\s+)?(?:SERVIDORA?\s+)?'
                rf'((?:{_LETRAS}{{2,}}\s+){{0,6}}{_LETRAS}{{2,}})',
                paragrafo,
            )

    pessoa = m_nome.group(1).strip() if m_nome else "PESSOA NÃO IDENTIFICADA"

    # Cargo — texto após "CARGO EM COMISSÃO DE", "CARGO DE", "FUNÇÃO DE" ou "EMPREGO DE"
    m_cargo = re.search(
        r'(?:CARGO\s+(?:EM\s+COMISS[AÃ]O\s+DE|DE)|FUN[CÇ][AÃ]O\s+DE|EMPREGO\s+DE)\s+'
        r'(.+?)(?:,|\.|S[IÍ]MBOLO\b|(?=\bCC\d))',
        paragrafo,
    )
    cargo = m_cargo.group(1).strip().rstrip(",").strip() if m_cargo else "cargo não identificado"

    # Símbolo CC
    m_cc = re.search(r'\bCC\s*(\d+)\b', paragrafo)
    simbolo_cc = f"CC{m_cc.group(1)}" if m_cc else None

    # Converte secretaria de volta para Title Case legível
    secretaria_fmt = secretaria.title()

    return {
        "acao": acao,
        "pessoa": pessoa,
        "cargo": cargo,
        "simbolo_cc": simbolo_cc,
        "secretaria": secretaria_fmt,
    }


def detectar_fofocas(portarias: list[dict], secretarias: list[str]) -> list[dict]:
    """
    Varre as portarias extraídas buscando nomeações e exonerações
    vinculadas a secretarias municipais de Mossoró.

    Um parágrafo dispara a detecção quando contém simultaneamente:
      - Palavra-chave de movimentação: NOMEAR ou EXONERAR (e variantes)
      - Nome de uma secretaria da lista

    Retorna lista de dicionários com: acao, pessoa, cargo, simbolo_cc,
    secretaria, portaria.
    """
    fofocas = []
    secretarias_upper = [unicodedata.normalize("NFKD", s.upper()) for s in secretarias]
    RE_ACAO = re.compile(
        r'\b(NOMEAR|NOMEIA|NOMEADO[A]?|EXONERAR|EXONERA|EXONERADO[A]?)\b'
    )

    for portaria in portarias:
        conteudo_norm = unicodedata.normalize("NFKD", portaria["conteudo"].upper())
        paragrafos = [p.strip() for p in conteudo_norm.split("\n") if p.strip()]

        for paragrafo in paragrafos:
            if not RE_ACAO.search(paragrafo):
                continue

            secretaria_encontrada = None
            for sec in secretarias_upper:
                if sec in paragrafo:
                    secretaria_encontrada = sec
                    break

            if not secretaria_encontrada:
                continue

            dados = _extrair_dados_fofoca(paragrafo, secretaria_encontrada)
            if dados:
                dados["portaria"] = portaria
                fofocas.append(dados)
                # debug (não info) para não expor pessoa (PII) no console
                log.debug(
                    f"Fofoca detectada: {dados['acao']} — "
                    f"{dados['pessoa']} — {dados['secretaria']}"
                )

    log.info(f"Total de fofocas detectadas: {len(fofocas)}")
    return fofocas


# Meses por extenso (sem acento, minúsculos) → número, para parsear datas.
_MESES_PT = {
    "janeiro": 1, "fevereiro": 2, "marco": 3, "abril": 4, "maio": 5, "junho": 6,
    "julho": 7, "agosto": 8, "setembro": 9, "outubro": 10, "novembro": 11, "dezembro": 12,
}

# Dia da semana a partir de date.weekday() (segunda=0 … domingo=6), forma curta.
_DIAS_SEMANA = ["segunda", "terça", "quarta", "quinta", "sexta", "sábado", "domingo"]


def _sem_acento(texto: str) -> str:
    """Normaliza para minúsculas sem acentos (NFKD + remoção de combinantes)."""
    nfkd = unicodedata.normalize("NFKD", texto.lower())
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def detectar_ponto_facultativo(portarias: list[dict]) -> list[dict]:
    """
    Varre TODOS os atos da edição procurando a expressão "ponto facultativo"
    (independente de secretarias ou nomes monitorados — é decreto geral).

    Para cada ato que contém a expressão, tenta extrair a(s) data(s) no formato
    "dia DD de <mês> de AAAA" ou "dia DD/MM/AAAA". O dia da semana é calculado
    a partir da data (mais confiável que parsear o texto).

    Retorna uma lista deduplicada por data, cada item com:
        data_br    - "DD/MM/AAAA" (ou None quando não foi possível extrair)
        dia_semana - forma curta ("sexta", "segunda", …) ou None
        weekday    - índice 0-6 (segunda=0) ou None
    Quando há ponto facultativo mas nenhuma data é extraída, retorna um único
    item genérico (data_br=None). Se não houver ponto facultativo, retorna [].
    """
    # Regex de datas (aplicadas sobre texto sem acento/minúsculo):
    #   "dia 21 de novembro de 2025"  e  "dia 21/11/2025"
    re_extenso = re.compile(r'dia\s+(\d{1,2})\s+de\s+([a-z]+)\s+de\s+(\d{4})')
    re_numerica = re.compile(r'dia\s+(\d{1,2})/(\d{1,2})/(\d{4})')

    datas_ordenadas: list[str] = []      # preserva ordem de aparição
    info_por_data: dict[str, dict] = {}  # data_br -> {dia_semana, weekday}
    houve_ponto = False

    for portaria in portarias:
        texto = _sem_acento(portaria.get("conteudo", ""))
        if "ponto facultativo" not in texto:
            continue
        houve_ponto = True

        achados: list[tuple[int, int, int]] = []  # (dia, mes, ano)
        for d, mes_txt, ano in re_extenso.findall(texto):
            mes = _MESES_PT.get(mes_txt)
            if mes:
                achados.append((int(d), mes, int(ano)))
        for d, m, ano in re_numerica.findall(texto):
            achados.append((int(d), int(m), int(ano)))

        for dia, mes, ano in achados:
            try:
                data_obj = datetime(ano, mes, dia).date()
            except ValueError:
                continue  # data inválida (ex.: 31/02) — ignora
            data_br = data_obj.strftime("%d/%m/%Y")
            if data_br not in info_por_data:
                wd = data_obj.weekday()
                info_por_data[data_br] = {
                    "data_br": data_br,
                    "dia_semana": _DIAS_SEMANA[wd],
                    "weekday": wd,
                }
                datas_ordenadas.append(data_br)

    if not houve_ponto:
        return []

    if not datas_ordenadas:
        # Há ponto facultativo, mas nenhuma data extraída → genérico único.
        log.info("Ponto facultativo detectado (sem data extraída).")
        return [{"data_br": None, "dia_semana": None, "weekday": None}]

    resultado = [info_por_data[d] for d in datas_ordenadas]
    log.info(f"Ponto facultativo detectado em: {', '.join(datas_ordenadas)}")
    return resultado


def formatar_ponto_facultativo(pontos: list[dict]) -> list[str]:
    """
    Gera as linhas do bloco de ponto facultativo (estilo descontraído),
    para anexar ao FINAL da seção Fofoca da Secretaria. Uma "manchete" por data.

    A manchete se adapta ao dia da semana: sexta-feira vira "SEXTOU OFICIAL?",
    os demais dias viram "FOLGA À VISTA!".
    """
    if not pontos:
        return []

    linhas: list[str] = [""]
    for p in pontos:
        data_br = p.get("data_br")
        if data_br:
            dia_semana = p.get("dia_semana", "")
            titulo = "🍹 *SEXTOU OFICIAL?*" if p.get("weekday") == 4 else "🎈 *FOLGA À VISTA!*"
            linhas.append(titulo)
            linhas.append(
                f"Saiu no Diário: *ponto facultativo na {dia_semana}, {data_br}*! "
                f"Já pode planejar a folga... 🏖️ (exceto serviços essenciais, claro 😅)"
            )
        else:
            linhas.append("🍹 *PONTO FACULTATIVO!*")
            linhas.append(
                "Saiu no Diário: foi decretado *ponto facultativo* nesta edição! "
                "Confira a data no decreto. 🏖️ (exceto serviços essenciais, claro 😅)"
            )
        linhas.append("")
    return linhas


def promovido_remanejado(fofocas: list[dict]) -> list[dict]:
    """
    Consolida pares exoneração + nomeação da mesma pessoa em um único evento.

    Quando alguém é exonerado de um cargo e nomeado em outro na mesma edição,
    os dois registros separados são substituídos por um único registro com ação:
      PROMOVIDO(A)  — novo símbolo CC tem número MENOR  (cargo mais alto na hierarquia)
      REMANEJADO(A) — novo símbolo CC tem número IGUAL ou MAIOR (mesmo nível ou abaixo)

    Registros sem par (só exoneração ou só nomeação) permanecem inalterados.

    Exemplo:
      CC15 → CC11 : n_novo (11) < n_antigo (15) → PROMOVIDO(A)
      CC11 → CC11 : n_novo (11) = n_antigo (11) → REMANEJADO(A)
      CC11 → CC15 : n_novo (15) > n_antigo (11) → REMANEJADO(A)
    """
    exoneracoes = {f["pessoa"]: f for f in fofocas if "EXONERADO" in f.get("acao", "")}
    nomeacoes   = {f["pessoa"]: f for f in fofocas if "NOMEADO"   in f.get("acao", "")}

    pessoas_consolidadas: set[str] = set()
    consolidados: list[dict] = []

    for pessoa, exon in exoneracoes.items():
        if pessoa not in nomeacoes:
            continue

        nom = nomeacoes[pessoa]
        pessoas_consolidadas.add(pessoa)

        cc_ant_str = exon.get("simbolo_cc") or ""
        cc_nov_str = nom.get("simbolo_cc")  or ""

        # Extrai o número do símbolo CC para comparação (ex: "CC11" → 11)
        m_ant = re.search(r'\d+', cc_ant_str)
        m_nov = re.search(r'\d+', cc_nov_str)

        if m_ant and m_nov and int(m_nov.group()) < int(m_ant.group()):
            acao = "PROMOVIDO(A)"
        else:
            acao = "REMANEJADO(A)"

        consolidados.append({
            "acao":               acao,
            "pessoa":             pessoa,
            "cargo_anterior":     exon.get("cargo", "cargo não identificado"),
            "secretaria_anterior":exon.get("secretaria", "secretaria não identificada"),
            "cc_anterior":        exon.get("simbolo_cc"),
            "cargo_novo":         nom.get("cargo", "cargo não identificado"),
            "secretaria_nova":    nom.get("secretaria", "secretaria não identificada"),
            "cc_novo":            nom.get("simbolo_cc"),
            "portaria_exon":      exon.get("portaria"),
            "portaria_nom":       nom.get("portaria"),
        })
        # debug (não info) para não expor pessoa (PII) no console
        log.debug(
            f"{acao}: {pessoa} | "
            f"{exon.get('secretaria')} → {nom.get('secretaria')}"
        )

    # Mantém registros sem par (exoneração ou nomeação sem correspondente)
    restantes = [f for f in fofocas if f["pessoa"] not in pessoas_consolidadas]

    return consolidados + restantes


def formatar_fofocas(fofocas: list[dict], pontos_facultativos: list[dict] | None = None) -> str:
    """
    Gera a seção "Fofoca da Secretaria" em formato informal/divertido
    para ser anexada à mensagem principal do WhatsApp.
    Sempre exibe o cabeçalho da seção — quando vazia, informa que não houve movimentações.

    Se `pontos_facultativos` for informado, um bloco de aviso de ponto facultativo
    é anexado ao FINAL da seção — inclusive quando não há movimentações de pessoal.
    """
    bloco_ponto = formatar_ponto_facultativo(pontos_facultativos or [])

    linhas = [
        "",
        "🗣️ *FOFOCA DA SECRETARIA*",
    ]

    if not fofocas:
        linhas += [
            "💤 Silêncio absoluto nos bastidores...\nNenhuma movimentação de pessoal detectada nesta edição.",
            "",
        ]
        linhas += bloco_ponto
        return "\n".join(linhas)

    linhas += [
        f"_{len(fofocas)} movimentação(ões) de pessoal detectada(s)_",
        "",
    ]

    for fofoca in fofocas:
        pessoa = fofoca.get("pessoa", "???")
        acao   = fofoca.get("acao", "???")

        if acao in ("PROMOVIDO(A)", "REMANEJADO(A)"):
            c_ant  = fofoca.get("cargo_anterior", "cargo não identificado")
            cc_ant = fofoca.get("cc_anterior")
            s_ant  = fofoca.get("secretaria_anterior", "secretaria não identificada")
            c_nov  = fofoca.get("cargo_novo", "cargo não identificado")
            cc_nov = fofoca.get("cc_novo")
            s_nov  = fofoca.get("secretaria_nova", "secretaria não identificada")
            cc_ant_str = f" ({cc_ant})" if cc_ant else ""
            cc_nov_str = f" ({cc_nov})" if cc_nov else ""

            if acao == "PROMOVIDO(A)":
                texto = (
                    f"🔝 *{pessoa}* foi *PROMOVIDO(A)*!\n"
                    f"   De: _{c_ant}{cc_ant_str}_ na _{s_ant}_\n"
                    f"   Para: _{c_nov}{cc_nov_str}_ na _{s_nov}_"
                )
            else:
                texto = (
                    f"🔄 *{pessoa}* foi *REMANEJADO(A)*.\n"
                    f"   De: _{c_ant}{cc_ant_str}_ na _{s_ant}_\n"
                    f"   Para: _{c_nov}{cc_nov_str}_ na _{s_nov}_"
                )

        elif "NOMEADO" in acao:
            cargo      = fofoca.get("cargo", "cargo não identificado")
            cc         = fofoca.get("simbolo_cc")
            secretaria = fofoca.get("secretaria", "secretaria não identificada")
            cc_str     = f" ({cc})" if cc else ""
            texto = (
                f"🔥 *{pessoa}* foi *NOMEADO(A)* no cargo de "
                f"_{cargo}{cc_str}_ na _{secretaria}_!"
            )
        else:
            cargo      = fofoca.get("cargo", "cargo não identificado")
            cc         = fofoca.get("simbolo_cc")
            secretaria = fofoca.get("secretaria", "secretaria não identificada")
            cc_str     = f" ({cc})" if cc else ""
            texto = (
                f"🚪 *{pessoa}* deixou a casa! Foi *EXONERADO(A)* "
                f"do cargo de _{cargo}{cc_str}_ na _{secretaria}_."
            )

        linhas.append(texto)
        linhas.append("")

    linhas += bloco_ponto
    return "\n".join(linhas)


def _extrair_funcao_contrato(conteudo: str, nome: str) -> tuple[str, str | None]:
    """
    Determina a FUNÇÃO de uma pessoa numa portaria de designação e o nº do contrato.

    Funções possíveis: "Gestor", "Gestor Substituto", "Fiscal", "Fiscal Substituto".

    Estratégia: divide o conteúdo em blocos a cada "Designar" (cada bloco traz uma
    designação — titular + eventual substituto). No bloco onde o nome aparece:
      - se o nome vem DEPOIS de "substituto(a) eventual" → é o substituto;
      - caso contrário → é o titular.
    O papel (GESTOR/FISCAL) e o contrato vêm de "para atuar como <PAPEL> DO CONTRATO
    n° <XX/AAAA>" do próprio bloco.

    Retorna (funcao, contrato). Se não identificar o papel → ("função não
    identificada", contrato_ou_None); se não achar o contrato → (funcao, None).
    """
    # Colapsa espaços/quebras/nbsp (mesma normalização de buscar_nomes_em_portarias)
    texto = " ".join(conteudo.upper().split())
    nome_up = " ".join(nome.upper().split())

    re_papel = re.compile(
        r'PARA ATUAR COMO\s+(GESTOR[A]?|FISCAL)\s+DO\s+CONTRATO\s+'
        r'N[°ºO.]*\s*(\d+\s*/\s*\d+)'
    )
    re_subst = re.compile(r'SUBSTITUT[OA]\s+EVENTUAL')

    # Blocos: um por "DESIGNAR"
    indices = [m.start() for m in re.finditer(r'\bDESIGNAR\b', texto)]
    blocos = (
        [texto[ini: (indices[i + 1] if i + 1 < len(indices) else len(texto))]
         for i, ini in enumerate(indices)]
        if indices else [texto]
    )

    for bloco in blocos:
        pos_nome = bloco.find(nome_up)
        if pos_nome == -1:
            continue

        m_papel = re_papel.search(bloco)
        contrato = m_papel.group(2).replace(" ", "") if m_papel else None
        if not m_papel:
            return ("função não identificada", None)

        papel = "Gestor" if m_papel.group(1).startswith("GESTOR") else "Fiscal"
        m_subst = re_subst.search(bloco)
        eh_substituto = m_subst is not None and pos_nome > m_subst.start()
        funcao = f"{papel} Substituto" if eh_substituto else papel
        return (funcao, contrato)

    return ("função não identificada", None)


def formatar_resumo_por_pessoa(ocorrencias: list[dict]) -> str:
    """
    Gera o bloco de RESUMO "por pessoa": para cada nome monitorado encontrado,
    lista as portarias em que ele aparece e, em cada uma, a FUNÇÃO designada
    (Gestor / Gestor Substituto / Fiscal / Fiscal Substituto) + o nº do contrato.

    É inserido no topo da mensagem principal, logo abaixo do cabeçalho e antes
    dos blocos detalhados, funcionando como um índice de leitura rápida.

    A ordem das pessoas e das portarias segue a primeira aparição nas
    ocorrências; portarias repetidas para a mesma pessoa não são duplicadas.
    """
    # pessoa → lista ordenada de refs de portaria (sem repetir)
    pessoa_portarias: dict[str, list[str]] = {}
    # (pessoa, ref) → (funcao, contrato)
    detalhes: dict[tuple[str, str], tuple[str, str | None]] = {}

    for oc in ocorrencias:
        nome = oc["nome"]
        portaria = oc["portaria"]
        m = re.search(r'N[ºo°]\s*(\d+)', portaria["titulo"])
        ref = m.group(1) if m else portaria["titulo"]
        pessoa_portarias.setdefault(nome, [])
        if ref not in pessoa_portarias[nome]:
            pessoa_portarias[nome].append(ref)
            detalhes[(nome, ref)] = _extrair_funcao_contrato(
                portaria.get("conteudo", ""), nome
            )

    linhas = [
        "📋 *RESUMO — POR PESSOA*",
        f"_{len(pessoa_portarias)} nome(s) monitorado(s) encontrado(s)_",
        "",
    ]
    for nome, refs in pessoa_portarias.items():
        linhas.append(f"👤 *{nome}* ({len(refs)})")
        for ref in refs:
            funcao, contrato = detalhes[(nome, ref)]
            rotulo = f"Portaria {ref}" if str(ref).isdigit() else ref
            contrato_str = f" · Contrato {contrato}" if contrato else ""
            linhas.append(f"   • {rotulo} — {funcao}{contrato_str}")
        linhas.append("")

    return "\n".join(linhas)


def formatar_mensagem(ocorrencias: list[dict], data_str: str, numero: int | None = None) -> str:
    """
    Formata a mensagem principal de WhatsApp com as ocorrências encontradas.
    A seção de fofocas é enviada separadamente após os PDFs.

    A mensagem começa com um bloco de RESUMO por pessoa (índice de leitura
    rápida) e, em seguida, traz os blocos detalhados de cada portaria.

    Quando vários nomes monitorados aparecem na MESMA portaria, eles são
    agrupados em um único bloco — com todos os nomes no título separados
    por " + " — em vez de repetir o conteúdo da portaria para cada nome.
    """
    edicao_str = f"📅 EDIÇÃO Nº {numero}: {data_str}" if numero else f"📅 EDIÇÃO: {data_str}"

    # Agrupa ocorrências por portaria (mesma lógica usada na extração de PDFs),
    # preservando a ordem de primeira aparição e sem repetir nomes.
    portaria_nomes: dict[str, list[str]] = {}
    portaria_obj:   dict[str, dict]      = {}
    for oc in ocorrencias:
        titulo = oc["portaria"]["titulo"]
        if titulo not in portaria_nomes:
            portaria_nomes[titulo] = []
            portaria_obj[titulo]   = oc["portaria"]
        if oc["nome"] not in portaria_nomes[titulo]:
            portaria_nomes[titulo].append(oc["nome"])

    linhas = [
        f"📢 *MONITORAMENTO — DIÁRIO OFICIAL DE MOSSORÓ*\n",
        f"👥 *{NOME_SALA}*\n",
        edicao_str,
        f"🔍 {len(portaria_nomes)} ocorrência(s) encontrada(s)\n",
        formatar_resumo_por_pessoa(ocorrencias),
    ]

    for i, (titulo, nomes) in enumerate(portaria_nomes.items(), start=1):
        portaria = portaria_obj[titulo]
        nomes_str = " + ".join(nomes)

        # Corpo = conteúdo completo sem a primeira linha (título já exibido em *Ato:*)
        linhas_conteudo = portaria["conteudo"].split("\n")
        corpo = "\n".join(linhas_conteudo[1:]).strip()

        linhas += [
            f"━━━━━━━━━━━━━━━━━━",
            f"*{i}. Nome:* {nomes_str}",
            f"*Ato:* {titulo}",
            f"\n{corpo}",
            "",
        ]

    return "\n".join(l for l in linhas if l is not None)
