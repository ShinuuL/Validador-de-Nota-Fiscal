"""
Orquestrador principal (RN16/RN17 - contrato de saída estruturado).

Uso básico:

    from nfe_validator.validador import validar

    resultado = validar(conteudo_xml_como_string)
    print(resultado["valido"], resultado["erros"])

Novidades da v2 (relatório de erros)
------------------------------------
  * RN18 - varredura de campos obrigatórios NÃO PREENCHIDOS, independente do
    XSD: reporta todos de uma vez, com o número do item, e distingue ausente
    de vazio de "só espaços".
  * Todo erro traz `severidade`, `origem` e um bloco `detalhe` com a explicação
    quebrada em partes (onde / o que aconteceu / por que rejeita / como
    corrigir), para a UI montar a mensagem como quiser.
  * `resumo` agrega contagens por origem, por tipo de violação e por item, e
    lista os campos não preenchidos - é o atalho para "o que preciso arrumar
    nessa nota".
  * Erros duplicados entre o XSD e as regras de negócio (o mesmo campo vazio
    encontrado pelos dois caminhos) são colapsados em um só.
"""

from collections import Counter, defaultdict
from typing import Optional

from .localizacao import localizar

from . import parser
from . import schema
from . import servicos
from .regras import (chave_acesso, documento_fiscal, totais, datas,
                     campos_obrigatorios, obrigatorios_condicionais)

# A RN17 fixa `origem` em exatamente dois valores. Manter esse contrato é o
# que a spec da UI (RN-UI07) declara consumir, então a granularidade fina de
# "qual regra falou" vive em `subOrigem`, um campo aditivo.
ORIGENS_VALIDAS = ("xsd", "regra-negocio")

# subOrigem -> origem da RN17. Só o libxml2 produz veredito de schema; todo o
# resto do validador é regra de negócio numerada na spec (RN01..RN18).
ORIGEM_DA_SUBORIGEM = {
    "schema": "xsd",                 # RN03/RN05 - libxml2 contra o XSD oficial
    "sintaxe": "regra-negocio",      # RN04 - boa formação
    "identificacao": "regra-negocio",  # RN01/RN02 - tipo e versão
    "campo-obrigatorio": "regra-negocio",  # RN18 - campos não preenchidos
    "obrigatorio-condicional": "regra-negocio",  # RN19 - exigido por CST/grupo
    "chave-acesso": "regra-negocio",  # RN08/RN09
    "documento-fiscal": "regra-negocio",  # RN10 - CNPJ/CPF
    "totais": "regra-negocio",       # RN11
    "datas": "regra-negocio",        # RN12
    "configuracao": "regra-negocio",  # RN05 - XSD ausente no ambiente
}

# Ordem de exibição: primeiro o que impede o processamento do arquivo, depois
# o que impede a validação da nota, por último as conferências de cálculo.
PRIORIDADE_SUBORIGEM = {
    "sintaxe": 0,
    "identificacao": 1,
    "schema": 2,
    "campo-obrigatorio": 3,
    "obrigatorio-condicional": 4,
    "chave-acesso": 5,
    "documento-fiscal": 6,
    "totais": 7,
    "datas": 8,
    "configuracao": 9,
}

# Tipos de violação que significam, na prática, "campo não preenchido".
VIOLACOES_NAO_PREENCHIDO = {
    "obrigatorio_ausente", "vazio", "so_espacos", "grupo_incompleto",
    "obrigatorio_condicional_ausente", "grupo_parcialmente_preenchido",
}


def _resultado_base() -> dict:
    return {
        "valido": False,
        "tipoDocumento": None,
        "versaoLayout": None,
        "chaveAcesso": None,
        "erros": [],
        "avisos": [],
        "resumo": {},
    }


def _normalizar(erro: dict) -> dict:
    """Põe todo erro no contrato da RN17, independente de qual regra o criou.

    As regras declaram `subOrigem` (o que elas realmente sabem); aqui derivamos
    a `origem` de dois valores que a RN17 exige, e preenchemos `mensagem` — a
    chave que a RN17 nomeia — com a explicação de negócio. `motivo_rejeicao`
    continua existindo como alias porque é o nome que a spec da UI usa."""
    erro.setdefault("severidade", "erro")
    erro.setdefault("detalhe", None)

    sub = erro.get("subOrigem")
    if sub is None:
        # Regra que ainda não migrou: aceita o valor antigo de `origem` como
        # subOrigem, para não perder a informação de procedência.
        sub = erro.get("origem")
        erro["subOrigem"] = sub

    erro["origem"] = ORIGEM_DA_SUBORIGEM.get(sub, "regra-negocio")
    erro["mensagem"] = erro.get("motivo_rejeicao")
    return erro


def _chave_dedup(erro: dict) -> tuple:
    """Identidade de um erro para fins de deduplicação. Usa a tag XML e o
    tipo de violação quando disponíveis (é assim que um 'vBC vazio' achado
    pelo XSD e pela RN18 se reconhecem como o mesmo problema)."""
    detalhe = erro.get("detalhe") or {}
    tipo = detalhe.get("tipoViolacao")
    tag = detalhe.get("tagXml")
    if tipo and tag:
        return ("campo", tag, tipo, erro.get("xpath"))
    return ("codigo", erro.get("codigo"), erro.get("campo"), erro.get("xpath"))


def _riqueza(erro: dict) -> int:
    """Quanto esse erro explica. Usado para escolher qual sobrevive quando o
    XSD e uma regra nossa acham o MESMO problema.

    Importa porque a RN19 diz *por que* o campo é obrigatório naquele caso
    ("porque o grupo informado é ICMS20"), enquanto o XSD só diz que falta um
    filho — e o XSD é anexado antes, então sem isso a mensagem melhor perdia."""
    detalhe = erro.get("detalhe") or {}
    pontos = 0
    if detalhe:
        pontos += 1
    if detalhe.get("gatilho"):
        pontos += 2
    if detalhe.get("fonte") in ("catalogo", "xsd"):
        pontos += 1
    if detalhe.get("onde"):
        pontos += 1
    return pontos


def _deduplicar(erros: list[dict]) -> list[dict]:
    """Colapsa erros que descrevem o mesmo problema, mantendo o que explica
    melhor (e não simplesmente o primeiro que apareceu)."""
    melhor: dict[tuple, dict] = {}
    ordem: list[tuple] = []
    for erro in erros:
        chave = _chave_dedup(erro)
        if chave not in melhor:
            melhor[chave] = erro
            ordem.append(chave)
        elif _riqueza(erro) > _riqueza(melhor[chave]):
            melhor[chave] = erro
    return [melhor[chave] for chave in ordem]


def _ordenar(erros: list[dict]) -> list[dict]:
    def peso(erro: dict):
        detalhe = erro.get("detalhe") or {}
        return (
            PRIORIDADE_SUBORIGEM.get(erro.get("subOrigem"), 99),
            detalhe.get("onde") is None,          # erros localizados primeiro
            erro.get("linha") if erro.get("linha") is not None else 10**9,
            str(erro.get("campo") or ""),
        )

    return sorted(erros, key=peso)


def _montar_resumo(erros: list[dict], avisos: list[dict]) -> dict:
    """Agrega os erros para dar ao usuário a visão de conjunto que uma lista
    plana não dá: quantos problemas, de que natureza, e em quais itens."""
    por_origem = Counter(e.get("origem") or "indefinida" for e in erros)
    por_suborigem = Counter(e.get("subOrigem") or "indefinida" for e in erros)
    por_violacao = Counter(
        (e.get("detalhe") or {}).get("tipoViolacao") or "nao_classificado" for e in erros
    )

    nao_preenchidos: list[dict] = []
    por_item: dict[str, int] = defaultdict(int)

    for erro in erros:
        detalhe = erro.get("detalhe") or {}
        item = detalhe.get("onde")
        if detalhe.get("tipoViolacao") in VIOLACOES_NAO_PREENCHIDO:
            nao_preenchidos.append({
                "campo": erro.get("campo"),
                "tagXml": detalhe.get("tagXml"),
                "situacao": detalhe.get("tipoViolacao"),
                "onde": item,
                "xpath": erro.get("xpath"),
                "linha": erro.get("linha"),
                "comoCorrigir": detalhe.get("comoCorrigir"),
            })

    for erro in erros:
        xpath = erro.get("xpath") or ""
        numero = localizar(xpath).item if xpath else None
        chave = f"item {numero}" if numero else "nota (fora dos itens)"
        por_item[chave] += 1

    return {
        "totalErros": len(erros),
        "totalAvisos": len(avisos),
        "porOrigem": dict(por_origem),
        "porSubOrigem": dict(por_suborigem),
        "porTipoViolacao": dict(por_violacao),
        "porLocal": dict(por_item),
        "camposNaoPreenchidos": nao_preenchidos,
        "totalCamposNaoPreenchidos": len(nao_preenchidos),
    }


def _chave_referenciada(arvore) -> Optional[str]:
    """A chave da nota de que o documento fala, quando fala de uma só.

    Um cancelamento, uma CC-e, uma consulta de situação: todos apontam para uma
    nota por <chNFe>, e essa chave é o que o pessoal do fiscal usa para achar o
    documento no sistema. Sem isso o cabeçalho do relatório mostrava
    "Chave: (ausente)" num arquivo que traz a chave bem à vista.

    Devolve `None` quando há mais de uma chave distinta - o retorno de um lote
    traz um <protNFe> por nota, e escolher a primeira faria o cabeçalho apontar
    para uma nota específica como se o documento fosse sobre ela. `None` é
    honesto; um palpite não seria.
    """
    chaves = {
        (elemento.text or "").strip()
        for elemento in arvore.iter()
        if servicos.tag_sem_namespace(elemento.tag) == "chNFe"
    }
    chaves.discard("")
    return chaves.pop() if len(chaves) == 1 else None


def _validar_servico(arvore, achado: tuple, aplicar_xsd: bool,
                     resultado: dict) -> dict:
    """Valida um evento ou consulta: só estrutura, e é o certo aqui.

    As regras de negócio RN08..RN12 e RN18/RN19 leem uma NOTA - chave de
    acesso, CNPJ do emitente, soma dos itens, data de emissão, campos
    obrigatórios de `infNFe`. Um `<procEventoNFe>` não tem nada disso, então
    rodá-las produziria uma lista de erros sobre campos que o documento não
    deveria ter. O XSD do evento, por outro lado, é rigoroso: cobre `tpEvento`,
    `nSeqEvento`, o formato da chave referenciada, a assinatura e o conteúdo de
    `detEvento`, que é o que a SEFAZ confere.

    O contrato de saída é o mesmo da nota (RN16/RN17) - `tipoDocumento` traz a
    família, e a UI não precisa de caso especial.
    """
    servico, raiz, versao = achado
    resultado["tipoDocumento"] = servico.rotulo
    resultado["versaoLayout"] = versao or None
    resultado["chaveAcesso"] = _chave_referenciada(arvore)

    # A versão é atributo obrigatório da raiz nos nove XSDs de serviço. Sem
    # ela não há como escolher a pasta, e chutar a versão da família violaria a
    # RN15 - validaria contra um layout que o arquivo não declarou.
    if not versao:
        resultado["erros"].append(_normalizar({
            "codigo": "IDENTIFICACAO-FALHOU",
            "campo": "versao",
            "xpath": f"/{raiz}/@versao",
            "linha": arvore.getroot().sourceline,
            "mensagem_tecnica": f"<{raiz}> sem o atributo 'versao'",
            "motivo_rejeicao": (
                f"O arquivo foi reconhecido como {servico.descricao}, mas a raiz "
                f"<{raiz}> está sem o atributo obrigatório 'versao'. Esse atributo "
                "é o que diz contra qual versão do layout validar (RN02), e o "
                "validador não adivinha: validar contra a versão errada aprovaria "
                "uma estrutura que a SEFAZ rejeita. Como corrigir: acrescente "
                f"versao na tag <{raiz}>, com a versão que o seu emissor gera."
            ),
            "origem": "regra-negocio",
            "subOrigem": "identificacao",
        }))
        resultado["erros"] = _ordenar(resultado["erros"])
        resultado["resumo"] = _montar_resumo(resultado["erros"], resultado["avisos"])
        resultado["resumo"]["xsdAplicado"] = False
        return resultado

    xsd_aplicado = False
    if aplicar_xsd:
        try:
            resultado["erros"].extend(
                schema.validar_contra_xsd(arvore, servico.tipo, versao)
            )
            xsd_aplicado = True
        except schema.SchemaIndisponivel as exc:
            resultado["avisos"].append(_normalizar({
                "codigo": "XSD-INDISPONIVEL",
                "campo": None,
                "xpath": None,
                "linha": None,
                "mensagem_tecnica": str(exc),
                "motivo_rejeicao": (
                    f"O arquivo é {servico.descricao}, na versão {versao}, mas o "
                    f"schema oficial dessa versão não está instalado neste "
                    "ambiente. Num evento ou consulta a validação é inteiramente "
                    "estrutural - as regras de negócio da nota (chave de acesso, "
                    "totais, datas) não se aplicam -, então sem o XSD não sobra "
                    "conferência nenhuma: este relatório não diz nada sobre o "
                    "arquivo. Ver schemas/README.md."
                ),
                "origem": "regra-negocio",
                "subOrigem": "configuracao",
                "severidade": "aviso",
            }))

    resultado["erros"] = _ordenar(_deduplicar([_normalizar(e) for e in resultado["erros"]]))
    # Sem XSD não houve conferência alguma, então "válido" seria mentira - ao
    # contrário da nota, onde as regras de negócio ainda rodam e sustentam o
    # veredito.
    resultado["valido"] = xsd_aplicado and not resultado["erros"]
    resultado["resumo"] = _montar_resumo(resultado["erros"], resultado["avisos"])
    resultado["resumo"]["xsdAplicado"] = xsd_aplicado
    return resultado


def validar(conteudo_xml: str, aplicar_xsd: bool = True,
            aplicar_campos_obrigatorios: bool = True,
            aplicar_condicionais: bool = True) -> dict:
    resultado = _resultado_base()

    # 1) RN04 - boa formação primeiro. Se falhar, para aqui.
    try:
        arvore = parser.parsear_xml(conteudo_xml)
    except parser.XmlMalformado as exc:
        resultado["erros"].append(_normalizar({
            "codigo": "XML-MALFORMADO",
            "campo": None,
            "xpath": None,
            "linha": exc.linha,
            "mensagem_tecnica": exc.mensagem,
            "motivo_rejeicao": (
                "O arquivo não é um XML bem-formado (erro de sintaxe)"
                + (f", detectado na linha {exc.linha}" if exc.linha else "")
                + ". A SEFAZ rejeita a nota antes mesmo de olhar o conteúdo, porque o "
                "documento não pode nem ser interpretado como XML. Como corrigir: "
                "abra o arquivo na linha indicada e procure tag não fechada, tag "
                "fechada fora de ordem, caractere especial não escapado (& < >) ou "
                "conteúdo antes da declaração <?xml?>."
            ),
            "origem": "regra-negocio",
            "subOrigem": "sintaxe",
        }))
        resultado["resumo"] = _montar_resumo(resultado["erros"], resultado["avisos"])
        return resultado

    # 2b) Documento de serviço (evento, consulta, inutilização)? Tem que ser
    # perguntado ANTES de `identificar_documento`, que exige <infNFe> e culparia
    # o arquivo por não ser uma nota. Ver `servicos` para o porquê do registro.
    servico = servicos.identificar(arvore)
    if servico is not None:
        return _validar_servico(arvore, servico, aplicar_xsd, resultado)

    # 2) RN01/RN02 - identifica tipo de documento e versão do layout.
    try:
        tipo_documento, versao = parser.identificar_documento(arvore)
    except ValueError as exc:
        resultado["erros"].append(_normalizar({
            "codigo": "IDENTIFICACAO-FALHOU",
            "campo": None,
            "xpath": None,
            "linha": None,
            "mensagem_tecnica": str(exc),
            "motivo_rejeicao": str(exc),
            "origem": "regra-negocio",
            "subOrigem": "identificacao",
        }))
        resultado["resumo"] = _montar_resumo(resultado["erros"], resultado["avisos"])
        return resultado

    resultado["tipoDocumento"] = tipo_documento
    resultado["versaoLayout"] = versao
    resultado["chaveAcesso"] = parser.extrair_chave_acesso(arvore)

    # 3) RN03/RN05 - validação de XSD (se disponível e solicitada).
    xsd_aplicado = False
    if aplicar_xsd:
        try:
            resultado["erros"].extend(schema.validar_contra_xsd(arvore, tipo_documento, versao))
            xsd_aplicado = True
        except schema.SchemaIndisponivel as exc:
            resultado["avisos"].append(_normalizar({
                "codigo": "XSD-INDISPONIVEL",
                "campo": None,
                "xpath": None,
                "linha": None,
                "mensagem_tecnica": str(exc),
                "motivo_rejeicao": (
                    "A validação estrutural (XSD) não pôde ser executada porque o schema "
                    "oficial ainda não foi instalado neste ambiente. As regras de negócio e "
                    "a checagem de campos obrigatórios (RN18) foram aplicadas normalmente, "
                    "mas a conferência de tipos, máscaras e enumerações do layout está "
                    "pendente até o XSD ser adicionado (ver schemas/README.md)."
                ),
                "origem": "regra-negocio",
                "subOrigem": "configuracao",
                "severidade": "aviso",
            }))

    # 4) RN18 - campos obrigatórios não preenchidos. Roda mesmo sem XSD, e é
    # o que garante o relatório completo de preenchimento (não só o primeiro
    # campo faltante de cada grupo, como o libxml2 devolve).
    if aplicar_campos_obrigatorios:
        resultado["erros"].extend(campos_obrigatorios.validar_campos_obrigatorios(arvore))

    # 4b) RN19 - obrigatoriedade condicional por grupo/CST, derivada do XSD.
    # Complementa a RN18: reporta TODOS os campos que aquela variante exige,
    # citando o grupo que criou a obrigação, em vez do "Missing child" único
    # que o libxml2 devolve por grupo.
    if aplicar_condicionais:
        resultado["erros"].extend(
            obrigatorios_condicionais.validar_obrigatorios_condicionais(
                arvore, tipo_documento, versao
            )
        )

    # 5) RN08/RN09 - chave de acesso.
    campos_ide = parser.extrair_campos_ide(arvore)
    campos_emit = parser.extrair_campos_emit(arvore)
    campos_dest = parser.extrair_campos_dest(arvore)
    resultado["erros"].extend(
        chave_acesso.validar_chave_acesso(resultado["chaveAcesso"], campos_ide, campos_emit)
    )

    # 6) RN10 - CNPJ/CPF.
    resultado["erros"].extend(
        documento_fiscal.validar_documentos({"emit": campos_emit, "dest": campos_dest})
    )

    # 7) RN11 - totais.
    t = parser.extrair_totais(arvore)
    resultado["erros"].extend(totais.validar_totais(
        soma_vprod_itens=t["soma_vprod_itens"],
        v_prod_total_declarado=t["vProd_total"],
        soma_vicms_itens=t["soma_vicms_itens"],
        v_icms_total_declarado=t["vICMS_total"],
        v_nf_declarado=t["vNF"],
        # vNF é recomposto pela fórmula do MOC a partir das parcelas de
        # <ICMSTot>. Antes comparávamos com a soma de vProd, o que reprovava
        # qualquer nota com frete, desconto, IPI ou ST.
        componentes_icmstot=t["componentes_icmstot"],
    ))

    # 8) RN12 - datas.
    resultado["erros"].extend(datas.validar_data(campos_ide.get("dhEmi"), "ide/dhEmi"))

    resultado["erros"] = _ordenar(_deduplicar([_normalizar(e) for e in resultado["erros"]]))
    resultado["valido"] = len(resultado["erros"]) == 0
    resultado["resumo"] = _montar_resumo(resultado["erros"], resultado["avisos"])
    resultado["resumo"]["xsdAplicado"] = xsd_aplicado
    return resultado
