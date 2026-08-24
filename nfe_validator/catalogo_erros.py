"""
Catálogo de erros de negócio.

Este módulo é o coração do requisito: para cada campo/erro genérico
encontrado (seja pela validação de XSD, seja pelas regras de negócio),
o sistema deve responder "por que a nota não pode ser enviada para a
Receita/SEFAZ", e não apenas "campo inválido".

Como a explicação é montada (v2)
--------------------------------
Antes, se o campo estivesse no catálogo, o texto fixo do catálogo era usado
e o TIPO real da violação era ignorado — então um vBC com valor "ABC"
recebia a mesma mensagem de um vBC vazio ("está vazio ou ausente"), o que
mandava o usuário procurar o problema errado. Agora a mensagem é COMPOSTA
em quatro camadas independentes:

    1. ONDE      -> localizacao.Localizacao.descrever() (item, grupo, linha)
    2. O QUE     -> DIAGNOSTICOS[tipo_violacao]: o que exatamente aconteceu
                    com o valor informado
    3. POR QUE   -> ExplicacaoCampo.motivo: o papel fiscal do campo e por que
                    a SEFAZ não aceita a nota sem ele
    4. COMO      -> ExplicacaoCampo.como_corrigir (ou a orientação genérica do
                    tipo de violação): a ação concreta para resolver

Assim o catálogo passa a ENRIQUECER o diagnóstico técnico em vez de
SUBSTITUÍ-LO, e um campo desconhecido ainda recebe as camadas 1, 2 e 4 —
nunca sobra erro "cru" para o usuário.
"""

from dataclasses import dataclass
from typing import Optional

from .localizacao import Localizacao


@dataclass
class ExplicacaoCampo:
    nome_amigavel: str
    motivo: str
    como_corrigir: str = ""
    consequencia: str = "A SEFAZ rejeita a nota automaticamente na validação de schema."


# ---------------------------------------------------------------------------
# Camada 2 - o que aconteceu, por TIPO de violação. Texto factual sobre o
# valor informado, sem opinião sobre qual campo é.
# ---------------------------------------------------------------------------
DIAGNOSTICOS: dict[str, str] = {
    "obrigatorio_ausente":
        "o campo não foi informado no XML (a tag não existe)",
    "vazio":
        "o campo existe no XML mas está em branco (tag aberta e fechada sem conteúdo)",
    "so_espacos":
        "o campo contém apenas espaços ou quebras de linha, o que equivale a não preenchido",
    "zero_indevido":
        "o campo foi preenchido com zero, mas a operação declarada exige um valor maior que zero",
    "tipo_invalido":
        "o valor informado ('{valor}') não é do tipo esperado pelo layout",
    "decimal_invalido":
        "o valor informado ('{valor}') não é um número decimal válido - o layout exige ponto como "
        "separador decimal, sem símbolo de moeda, sem separador de milhar e sem espaços",
    "fora_do_padrao":
        "o valor informado ('{valor}') não respeita a máscara/expressão exigida pelo layout",
    "fora_da_enumeracao":
        "o valor informado ('{valor}') não está na lista de valores aceitos pelo layout",
    "tamanho_invalido":
        "o valor informado ('{valor}') tem tamanho fora do permitido pelo layout",
    "estrutura_inesperada":
        "o campo apareceu em uma posição que o layout não espera",
    "grupo_incompleto":
        "o grupo foi aberto no XML mas não trouxe todos os campos filhos obrigatórios",
    "grupo_exclusivo_violado":
        "foram informados campos de opções mutuamente exclusivas do layout - só uma delas é permitida",
    # --- RN19: obrigatoriedade condicional, derivada do XSD ---
    "obrigatorio_condicional_ausente":
        "o campo não foi informado, e neste caso ele é obrigatório{gatilho}",
    "codigo_incompativel_com_grupo":
        "o código '{valor}' foi informado dentro de um grupo que não o aceita",
    "grupo_parcialmente_preenchido":
        "o grupo foi preenchido pela metade: no layout esses campos são opcionais em "
        "conjunto, mas se um for informado todos passam a ser exigidos",
    "alternativa_violada":
        "o layout oferece caminhos alternativos e mutuamente exclusivos neste grupo, e "
        "o XML não seguiu exatamente um deles",
}

# ---------------------------------------------------------------------------
# Camada 4 - orientação genérica de correção, por TIPO de violação. Usada
# quando o campo não tem `como_corrigir` próprio no catálogo.
# ---------------------------------------------------------------------------
ORIENTACOES: dict[str, str] = {
    "obrigatorio_ausente":
        "Inclua a tag '{campo}' no XML, dentro do grupo correto e na ordem definida pelo layout, "
        "com o valor correspondente à operação.",
    "vazio":
        "Preencha a tag '{campo}' com o valor real. Se o campo não se aplica a esta operação, "
        "verifique no MOC/layout se ele deve ser OMITIDO por completo em vez de enviado em branco - "
        "campo obrigatório não aceita conteúdo vazio.",
    "so_espacos":
        "Remova os espaços/quebras de linha e preencha a tag '{campo}' com o valor real.",
    "zero_indevido":
        "Confira o cálculo que alimenta '{campo}'. Se o valor realmente é zero, revise o "
        "CST/CSOSN e o grupo tributário escolhido - provavelmente a operação deveria usar outro grupo.",
    "tipo_invalido":
        "Ajuste o valor de '{campo}' para o tipo exigido pelo layout antes de gerar o XML.",
    "decimal_invalido":
        "Formate '{campo}' como número com ponto decimal e a quantidade de casas exigida "
        "(ex.: 1234.56, e não 1.234,56 nem R$ 1.234,56).",
    "fora_do_padrao":
        "Confira o valor de '{campo}' contra a máscara do layout{sufixo_esperado} e reenvie sem "
        "caracteres extras (pontos, barras, espaços) que a máscara não aceita.",
    "fora_da_enumeracao":
        "Substitua o valor de '{campo}' por um dos códigos válidos da tabela do layout{sufixo_esperado}.",
    "tamanho_invalido":
        "Ajuste o tamanho de '{campo}' para o intervalo permitido pelo layout, completando com "
        "zeros à esquerda quando o campo for numérico de tamanho fixo.",
    "estrutura_inesperada":
        "Verifique a ordem das tags no grupo{sufixo_esperado}. Esse erro normalmente indica um campo "
        "obrigatório anterior que ficou faltando, um campo fora de sequência, ou um elemento de uma "
        "versão de layout diferente da declarada no atributo versao de <infNFe>.",
    "grupo_incompleto":
        "Complete o grupo com os campos obrigatórios que faltam{sufixo_esperado}, ou não envie o "
        "grupo se ele não se aplica à operação.",
    "grupo_exclusivo_violado":
        "Envie apenas uma das opções{sufixo_esperado} e remova a outra do XML.",
    # --- RN19 ---
    "obrigatorio_condicional_ausente":
        "Informe a tag '{campo}'{sufixo_esperado}. Se o campo realmente não se aplica à "
        "operação, então o grupo/código tributário escolhido é que está errado - reveja "
        "o CST/CSOSN antes de tentar omitir o campo.",
    "codigo_incompativel_com_grupo":
        "Corrija o código de '{campo}' para um valor que o grupo aceite, ou troque o "
        "grupo para o que corresponde ao código pretendido{sufixo_esperado}.",
    "grupo_parcialmente_preenchido":
        "Complete os campos que faltam{sufixo_esperado}, ou remova todos eles do XML - "
        "o layout aceita o grupo inteiro ou nenhuma parte dele.",
    "alternativa_violada":
        "Escolha exatamente um dos caminhos{sufixo_esperado}: informe todos os campos de "
        "um deles e nenhum campo dos outros.",
}


# Chave = tag XML (sem namespace). Valor = explicação de negócio.
# Quando o mesmo nome de tag existe em grupos diferentes (ex. vBC em
# ICMS/IPI/PIS/COFINS), usamos chaves compostas "GRUPO.TAG" com
# prioridade sobre a chave simples "TAG".
CATALOGO_CAMPOS: dict[str, ExplicacaoCampo] = {
    # --- ICMS ---
    "ICMS.vBC": ExplicacaoCampo(
        nome_amigavel="Base de Cálculo do ICMS (vBC)",
        motivo=(
            "vBC é a base de cálculo do ICMS: é sobre esse valor que a alíquota "
            "(pICMS) é aplicada para chegar ao imposto devido (vICMS). Sem ele a "
            "SEFAZ não tem como conferir o imposto declarado no item."
        ),
        como_corrigir=(
            "Informe a base de cálculo do item (normalmente vProd + frete + seguro + outras "
            "despesas - desconto, conforme a operação) e garanta que vBC x pICMS / 100 = vICMS."
        ),
    ),
    "ICMS.pICMS": ExplicacaoCampo(
        nome_amigavel="Alíquota do ICMS (pICMS)",
        motivo=(
            "pICMS é a alíquota aplicada sobre a base de cálculo. Sem a alíquota a SEFAZ "
            "não consegue conferir se o vICMS declarado bate com o cálculo esperado."
        ),
        como_corrigir=(
            "Informe a alíquota vigente para a UF/operação com 2 ou 4 casas decimais "
            "(ex.: 18.00) e confira se vBC x pICMS / 100 = vICMS."
        ),
    ),
    "ICMS.vICMS": ExplicacaoCampo(
        nome_amigavel="Valor do ICMS (vICMS)",
        motivo=(
            "vICMS é o imposto efetivamente devido no item. A SEFAZ recalcula esse valor a "
            "partir de vBC e pICMS; divergência ou ausência impede a conferência e a "
            "cobrança correta do imposto."
        ),
        como_corrigir="Recalcule vICMS = vBC x pICMS / 100, arredondando para 2 casas decimais.",
    ),
    "ICMS.CST": ExplicacaoCampo(
        nome_amigavel="Código de Situação Tributária do ICMS (CST)",
        motivo=(
            "O CST define como o ICMS deve ser tratado na operação (tributado, isento, "
            "substituição tributária, diferido etc.). É ele que determina quais campos do "
            "grupo ICMS são obrigatórios - sem CST a SEFAZ não sabe como processar o grupo."
        ),
        como_corrigir=(
            "Informe o CST de 2 dígitos compatível com a operação e com o regime do emitente. "
            "Emitente do Simples Nacional usa CSOSN, não CST."
        ),
    ),
    "ICMS.CSOSN": ExplicacaoCampo(
        nome_amigavel="Código de Situação da Operação no Simples Nacional (CSOSN)",
        motivo=(
            "O CSOSN é o equivalente ao CST para emitentes optantes pelo Simples Nacional e "
            "define o enquadramento tributário da operação. Sem ele a SEFAZ não valida o "
            "tratamento fiscal do item."
        ),
        como_corrigir=(
            "Informe o CSOSN de 3 dígitos (ex.: 102, 500) coerente com o CRT declarado em "
            "<emit><CRT>. Se o emitente não é do Simples, use CST no lugar de CSOSN."
        ),
    ),
    "ICMS.orig": ExplicacaoCampo(
        nome_amigavel="Origem da Mercadoria (orig)",
        motivo=(
            "orig indica a procedência da mercadoria (nacional, importada etc.) e é o "
            "primeiro campo obrigatório de todo grupo ICMS. Ele afeta a alíquota "
            "interestadual aplicável."
        ),
        como_corrigir="Informe orig com um dígito de 0 a 8, conforme a tabela de origem do MOC.",
    ),
    # --- IPI ---
    "IPI.vBC": ExplicacaoCampo(
        nome_amigavel="Base de Cálculo do IPI (vBC)",
        motivo=(
            "A base de cálculo do IPI é exigida quando o grupo IPI é informado como "
            "tributado (IPITrib). Sem ela o valor do IPI não pode ser conferido."
        ),
        como_corrigir="Informe vBC do IPI, ou troque para o grupo IPINT se a operação não é tributada.",
    ),
    "IPI.vIPI": ExplicacaoCampo(
        nome_amigavel="Valor do IPI (vIPI)",
        motivo="vIPI é o imposto devido no item e é recalculado pela SEFAZ a partir de vBC x pIPI.",
        como_corrigir="Recalcule vIPI = vBC x pIPI / 100 (ou qUnid x vUnid, na tributação por unidade).",
    ),
    # --- PIS ---
    "PIS.vBC": ExplicacaoCampo(
        nome_amigavel="Base de Cálculo do PIS (vBC)",
        motivo="A base de cálculo do PIS é obrigatória no grupo PISAliq e é usada para conferir vPIS.",
        como_corrigir="Informe vBC do PIS e confira se vBC x pPIS / 100 = vPIS.",
    ),
    "PIS.vPIS": ExplicacaoCampo(
        nome_amigavel="Valor do PIS (vPIS)",
        motivo="vPIS é a contribuição devida no item e é recalculada pela Receita a partir de vBC x pPIS.",
        como_corrigir="Recalcule vPIS = vBC x pPIS / 100, com 2 casas decimais.",
    ),
    # --- COFINS ---
    "COFINS.vBC": ExplicacaoCampo(
        nome_amigavel="Base de Cálculo da COFINS (vBC)",
        motivo="A base de cálculo da COFINS é obrigatória no grupo COFINSAliq e é usada para conferir vCOFINS.",
        como_corrigir="Informe vBC da COFINS e confira se vBC x pCOFINS / 100 = vCOFINS.",
    ),
    "COFINS.vCOFINS": ExplicacaoCampo(
        nome_amigavel="Valor da COFINS (vCOFINS)",
        motivo="vCOFINS é a contribuição devida no item e é recalculada pela Receita a partir de vBC x pCOFINS.",
        como_corrigir="Recalcule vCOFINS = vBC x pCOFINS / 100, com 2 casas decimais.",
    ),
    # --- Identificação da nota / emitente / destinatário ---
    "CNPJ": ExplicacaoCampo(
        nome_amigavel="CNPJ",
        motivo=(
            "O CNPJ identifica de forma única a pessoa jurídica envolvida na operação. A "
            "Receita valida o dígito verificador e o cadastro; sem um CNPJ íntegro não é "
            "possível identificar com segurança quem emitiu ou recebeu a nota."
        ),
        como_corrigir=(
            "Envie os 14 dígitos do CNPJ sem pontuação e confira o dígito verificador. "
            "Para destinatário pessoa física, use <CPF> em vez de <CNPJ>."
        ),
    ),
    "CPF": ExplicacaoCampo(
        nome_amigavel="CPF",
        motivo=(
            "O CPF identifica a pessoa física da operação. Um CPF com dígito verificador "
            "inválido impede a identificação segura do destinatário."
        ),
        como_corrigir="Envie os 11 dígitos do CPF sem pontuação e confira o dígito verificador.",
    ),
    "IE": ExplicacaoCampo(
        nome_amigavel="Inscrição Estadual (IE)",
        motivo=(
            "A IE comprova o cadastro estadual do contribuinte na UF da operação. A SEFAZ "
            "consulta esse cadastro; IE ausente ou em formato inválido para a UF impede a "
            "confirmação."
        ),
        como_corrigir=(
            "Informe a IE no formato da UF, sem pontuação. Para destinatário não contribuinte, "
            "use indIEDest=9 e não envie a tag IE; para isento, indIEDest=2 com IE ausente."
        ),
    ),
    "dhEmi": ExplicacaoCampo(
        nome_amigavel="Data/Hora de Emissão (dhEmi)",
        motivo=(
            "dhEmi registra o instante exato da emissão e compõe o trecho AAMM da chave de "
            "acesso. Além de obrigatório, um valor incorreto aqui invalida a chave e, com "
            "ela, a nota inteira. A SEFAZ também recusa notas com emissão muito atrasada ou "
            "no futuro em relação ao horário do servidor."
        ),
        como_corrigir=(
            "Envie no formato ISO 8601 com fuso, ex.: 2026-08-07T14:30:00-03:00 "
            "(o fuso é obrigatório e deve refletir a UF do emitente)."
        ),
    ),
    "cUF": ExplicacaoCampo(
        nome_amigavel="Código da UF (cUF)",
        motivo=(
            "cUF é o código IBGE da UF do emitente e define para qual SEFAZ a nota é "
            "roteada. Também compõe os 2 primeiros dígitos da chave de acesso."
        ),
        como_corrigir="Informe o código IBGE de 2 dígitos da UF do emitente (ex.: 35 para SP, 31 para MG).",
    ),
    "CFOP": ExplicacaoCampo(
        nome_amigavel="CFOP",
        motivo=(
            "O CFOP classifica fiscalmente a operação (venda, devolução, remessa, dentro ou "
            "fora do estado, para o exterior). É o que diz à SEFAZ o que essa nota "
            "representa; um CFOP incompatível com o tipo de operação (tpNF) ou com as UFs "
            "envolvidas derruba a nota."
        ),
        como_corrigir=(
            "Informe um CFOP de 4 dígitos coerente com tpNF (0=entrada / 1=saída) e com as UFs "
            "de emitente e destinatário: 1xxx/5xxx dentro do estado, 2xxx/6xxx interestadual, "
            "3xxx/7xxx exterior."
        ),
    ),
    "NCM": ExplicacaoCampo(
        nome_amigavel="NCM",
        motivo=(
            "O NCM classifica a mercadoria e determina alíquotas e regras tributárias "
            "aplicáveis ao item (IPI, ICMS-ST, PIS/COFINS monofásicos). Sem NCM válido a "
            "SEFAZ não consegue validar a tributação do produto."
        ),
        como_corrigir=(
            "Informe os 8 dígitos do NCM da tabela vigente. Só use '00' no caso previsto no "
            "MOC (item sem mercadoria / nota complementar de serviço)."
        ),
    ),
    "vNF": ExplicacaoCampo(
        nome_amigavel="Valor Total da Nota (vNF)",
        motivo=(
            "vNF é o valor total cobrado do destinatário e é recalculado pela SEFAZ a partir "
            "dos itens e impostos. Divergência aqui significa que o total da nota não pode "
            "ser conferido - é uma das rejeições mais comuns."
        ),
        como_corrigir=(
            "Recalcule vNF = vProd - vDesc + vFrete + vSeg + vOutro + vST + vIPI (mais as "
            "demais parcelas aplicáveis) e confira se ICMSTot bate com a soma item a item."
        ),
    ),
    "vProd": ExplicacaoCampo(
        nome_amigavel="Valor do Produto (vProd)",
        motivo=(
            "vProd é o valor bruto do item e alimenta todos os totais da nota. "
            "Inconsistência com quantidade x valor unitário derruba a validação de totais."
        ),
        como_corrigir="Confira vProd = qCom x vUnCom, com o arredondamento em 2 casas decimais.",
    ),
    "chNFe": ExplicacaoCampo(
        nome_amigavel="Chave de Acesso (chNFe)",
        motivo=(
            "A chave de acesso de 44 dígitos é o identificador único da nota em todo o "
            "sistema nacional e embute cUF, AAMM, CNPJ do emitente, modelo, série, número, "
            "tipo de emissão, código numérico e o DV. Chave ausente ou inconsistente é "
            "rejeitada de imediato."
        ),
        como_corrigir=(
            "Regere a chave a partir dos campos do próprio XML e recalcule o DV (módulo 11), "
            "conferindo o atributo Id do elemento <infNFe> (formato NFe + 44 dígitos)."
        ),
    ),
}

# Compatibilidade retroativa: código anterior importava TEMPLATES_GENERICOS.
TEMPLATES_GENERICOS = ORIENTACOES


def explicar_campo(tag: str, grupo_pai: Optional[str] = None) -> Optional[ExplicacaoCampo]:
    """Busca a explicação de negócio para uma tag, priorizando o contexto
    (grupo_pai.tag) e caindo para a tag isolada se não houver entrada
    específica para o grupo."""
    if grupo_pai:
        chave_composta = f"{grupo_pai}.{tag}"
        if chave_composta in CATALOGO_CAMPOS:
            return CATALOGO_CAMPOS[chave_composta]
    return CATALOGO_CAMPOS.get(tag)


def _sufixo_esperado(esperado: str) -> str:
    return f" (o layout esperava neste ponto: {esperado})" if esperado else ""


def diagnosticar(tipo_violacao: str, valor: str = "", gatilho: str = "") -> str:
    """Camada 2: descreve, em uma frase, o que aconteceu com o valor.

    `gatilho` é o que tornou o campo obrigatório neste caso concreto (ex.:
    " porque o grupo informado é ICMS20"). Só a RN19 preenche."""
    modelo = DIAGNOSTICOS.get(tipo_violacao, DIAGNOSTICOS["estrutura_inesperada"])
    return modelo.format(valor=valor, gatilho=gatilho)


def orientar(tipo_violacao: str, campo: str, esperado: str = "") -> str:
    """Camada 4: ação concreta de correção para o tipo de violação."""
    modelo = ORIENTACOES.get(tipo_violacao, ORIENTACOES["estrutura_inesperada"])
    return modelo.format(campo=campo, sufixo_esperado=_sufixo_esperado(esperado))


def explicacao_generica(tipo_violacao: str, campo: str, valor: str = "", esperado: str = "") -> str:
    """Fallback autocontido para campos fora do catálogo: junta diagnóstico
    técnico, consequência e orientação, sem depender do catálogo."""
    return (
        f"O campo '{campo}' não pôde ser aceito: {diagnosticar(tipo_violacao, valor)}. "
        "A SEFAZ rejeita a nota porque o documento não pode ser processado com essa "
        f"informação incompleta ou inválida. {orientar(tipo_violacao, campo, esperado)}"
    )


def _descricao_oficial(tag: str, contexto: Optional[str],
                       localizacao: Optional[Localizacao]):
    """Busca a descrição oficial do campo no XSD, tolerando XSD ausente.

    Tenta o contexto mais específico primeiro (o grupo imediato, ex. ICMS00),
    depois o grupo tributário (ICMS). Sem contexto nenhum, o `layout` devolve
    None quando a tag é ambígua — o que é o comportamento desejado: melhor não
    dizer nada do que atribuir ao campo a descrição de outro grupo."""
    from . import layout  # import tardio: ver a nota de ciclo em layout.py

    candidatos = []
    if localizacao is not None and localizacao.grupo:
        candidatos.append(localizacao.grupo)
    if contexto:
        candidatos.append(contexto)
    candidatos.append(None)

    for candidato in candidatos:
        descricao = layout.descricao_do_campo(tag, candidato)
        if descricao is not None:
            return descricao
    return None


def _esperado_enriquecido(tipo_violacao: str, tag: str, contexto: Optional[str],
                          esperado: str) -> str:
    """Para erro de enumeração, troca a lista crua do libxml2 pela lista com o
    rótulo oficial de cada código ("0=Margem Valor Agregado (%); ...").

    A lista crua continua intacta em `mensagem_tecnica` (RN07)."""
    if tipo_violacao != "fora_da_enumeracao":
        return esperado
    from . import layout

    legenda = layout.legenda_de_valores(tag, contexto)
    return legenda or esperado


def montar_explicacao(
    tag: str,
    tipo_violacao: str,
    localizacao: Optional[Localizacao] = None,
    valor: str = "",
    esperado: str = "",
    grupo_pai: Optional[str] = None,
    gatilho: str = "",
) -> dict:
    """Compõe as quatro camadas em um erro pronto para o relatório.

    Devolve as partes separadas (para quem quer montar a própria UI) e o texto
    corrido em `motivo_rejeicao` (para quem só quer ler a explicação).

    Precedência das fontes de texto (ver `layout.py`):
      1. `CATALOGO_CAMPOS["GRUPO.TAG"]` / `["TAG"]` - escrito à mão, mais rico
         fiscalmente que a documentação da SEFAZ, então ganha sempre;
      2. o `xs:documentation` do XSD oficial, CITADO literalmente;
      3. o texto genérico por tipo de violação.

    As camadas 'nome' e 'por que' usam limiares DIFERENTES sobre a mesma
    documentação, e isso é o ponto que impede a integração de piorar
    mensagens: "Logradouro" é um ótimo nome de campo e uma péssima
    justificativa fiscal; "Cfop" não serve nem para uma coisa nem para outra
    como explicação, mas serve como rótulo."""
    contexto = grupo_pai or (localizacao.grupo_tributario if localizacao else None)
    explicacao = explicar_campo(tag, contexto)

    # Consulta ao leiaute oficial. Nunca levanta: se o XSD não estiver
    # instalado, `oficial` é None e caímos no texto genérico de antes.
    oficial = _descricao_oficial(tag, contexto, localizacao)

    onde = localizacao.descrever() if localizacao else None
    o_que = diagnosticar(tipo_violacao, valor, gatilho)

    if explicacao:
        nome_amigavel = explicacao.nome_amigavel
        por_que = explicacao.motivo
        consequencia = explicacao.consequencia
        fonte = "catalogo"
    else:
        nome_amigavel = tag
        por_que = (
            f"'{tag}' é exigido pelo layout da NF-e/NFC-e neste ponto do XML; sem essa "
            "informação a SEFAZ não consegue processar o documento."
        )
        consequencia = (
            "A SEFAZ rejeita a nota na validação de schema, antes de qualquer análise fiscal."
        )
        fonte = "generico"

        if oficial is not None:
            if oficial.serve_como_nome:
                # Só a pontuação final sai: vários textos da SEFAZ terminam em
                # "." e "Valor do FCP. (vFCP)" fica estranho como rótulo.
                nome_amigavel = f"{oficial.texto.rstrip('.').strip()} ({tag})"
                fonte = "xsd"
            if oficial.substantiva:
                # Citado entre aspas de propósito: quem lê tem que saber que
                # essa frase é da SEFAZ, não nossa (RN07).
                por_que = (
                    f'O layout oficial define \'{tag}\' como: "{oficial.texto}". '
                    "Sem essa informação a SEFAZ não consegue processar o documento."
                )
                fonte = "xsd"

    como = (
        explicacao.como_corrigir
        if explicacao and explicacao.como_corrigir
        else orientar(tipo_violacao, tag, _esperado_enriquecido(tipo_violacao, tag, contexto, esperado))
    )

    prefixo = f"{onde}: " if onde else ""
    motivo_rejeicao = (
        f"{prefixo}{nome_amigavel} - {o_que}. "
        f"Por que isso impede o envio: {por_que} {consequencia} "
        f"Como corrigir: {como}"
    )

    detalhe = {
        "campo": nome_amigavel,
        "tagXml": tag,
        "tipoViolacao": tipo_violacao,
        "valorInformado": valor or None,
        "esperado": esperado or None,
        "onde": onde,
        "oQueAconteceu": o_que,
        "porQueRejeita": por_que,
        "comoCorrigir": como,
        "catalogado": explicacao is not None,
        "fonte": fonte,
        "gatilho": gatilho or None,
        "motivo_rejeicao": motivo_rejeicao,
    }
    if fonte == "xsd" and oficial is not None and oficial.origem is not None:
        # Rastreabilidade da RN05: dá para abrir o .xsd nessa linha e conferir.
        detalhe["origemXsd"] = oficial.origem.como_dict()
    return detalhe
