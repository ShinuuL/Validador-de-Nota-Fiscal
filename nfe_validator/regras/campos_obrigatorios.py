"""
RN18 - Campos obrigatórios não preenchidos (independente de XSD).

Por que esta regra existe
-------------------------
O XSD pega campo ausente e campo vazio, mas:

  1. ele só roda se o XSD oficial estiver instalado (ver RN05 / aviso
     XSD-INDISPONIVEL) - sem ele, uma nota com metade dos campos em branco
     passava sem nenhum erro de preenchimento;
  2. a mensagem do XSD para tag AUSENTE é sempre "Missing child element(s)"
     apontando para o GRUPO, não para o campo, e o lxml para no primeiro erro
     de cada grupo - então um <emit> sem CNPJ, sem xNome e sem IE gerava
     UM erro, e o usuário só descobria os outros dois nas rodadas seguintes;
  3. o XSD aceita como válido um campo preenchido só com espaços (" ") em
     tipos string, que a SEFAZ trata como não preenchido.

Esta regra varre o XML e reporta TODOS os campos obrigatórios não preenchidos
de uma vez, com o número do item, distinguindo três situações que exigem
correções diferentes: ausente, vazio e só espaços.
"""

from typing import Optional

from lxml import etree

from ..catalogo_erros import montar_explicacao
from ..localizacao import caminho_legivel as _xpath_de, localizar

NS = "http://www.portalfiscal.inf.br/nfe"

# ---------------------------------------------------------------------------
# Tabela declarativa de obrigatoriedade.
#
# Cada entrada é (caminho_do_grupo, [campos obrigatórios diretos]). O caminho
# é relativo a <infNFe> e resolvido sem depender de namespace. Só entram aqui
# campos obrigatórios em QUALQUER operação de NF-e/NFC-e 4.00 - campos
# condicionais (que dependem de CST, tpNF, indIEDest etc.) ficam de fora para
# não gerar falso positivo; quem cobre esses é o XSD + as regras específicas.
# ---------------------------------------------------------------------------
OBRIGATORIOS_POR_GRUPO: list[tuple[str, tuple[str, ...]]] = [
    ("ide", ("cUF", "cNF", "natOp", "mod", "serie", "nNF", "dhEmi",
             "tpNF", "idDest", "cMunFG", "tpImp", "tpEmis", "cDV",
             "tpAmb", "finNFe", "indFinal", "indPres", "procEmi", "verProc")),
    ("emit", ("xNome", "CRT")),
    ("emit/enderEmit", ("xLgr", "nro", "xBairro", "cMun", "xMun", "UF")),
    ("total/ICMSTot", ("vBC", "vICMS", "vProd", "vNF")),
    ("transp", ("modFrete",)),
]

# Campos obrigatórios dentro de cada item <det>.
OBRIGATORIOS_POR_ITEM: list[tuple[str, tuple[str, ...]]] = [
    ("prod", ("cProd", "xProd", "NCM", "CFOP", "uCom", "qCom",
              "vUnCom", "vProd", "uTrib", "qTrib", "vUnTrib", "indTot")),
]

# Grupos onde o layout exige EXATAMENTE UM entre vários campos (escolha
# exclusiva). (caminho_do_grupo, opções, obrigatório?)
ESCOLHAS_EXCLUSIVAS: list[tuple[str, tuple[str, ...], bool]] = [
    ("emit", ("CNPJ", "CPF"), True),
    ("dest", ("CNPJ", "CPF", "idEstrangeiro"), False),
]


def _erro(codigo: str, explicacao: dict, localizacao, severidade: str = "erro") -> dict:
    """Monta o dict de erro no contrato de saída do validador (RN16)."""
    return {
        "codigo": codigo,
        "campo": explicacao["campo"],
        "xpath": localizacao.xpath,
        "linha": localizacao.linha,
        "mensagem_tecnica": (
            f"{explicacao['tagXml']}: {explicacao['tipoViolacao']}"
            + (f" (valor: {explicacao['valorInformado']!r})" if explicacao["valorInformado"] else "")
        ),
        "mensagem": explicacao["motivo_rejeicao"],
        "motivo_rejeicao": explicacao["motivo_rejeicao"],
        "origem": "regra-negocio",      # RN17 aceita só xsd|regra-negocio
        "subOrigem": "campo-obrigatorio",
        "severidade": severidade,
        "detalhe": explicacao,
    }


def _filhos(elemento, nome: str) -> list:
    """Busca filhos diretos por nome, com e sem namespace."""
    return elemento.findall(f"{{{NS}}}{nome}") or elemento.findall(nome)


def _descer(elemento, caminho: str):
    """Resolve um caminho tipo 'emit/enderEmit' a partir de um elemento,
    tolerando XML com ou sem namespace. Devolve None se o grupo não existe."""
    atual = elemento
    for parte in caminho.split("/"):
        achados = _filhos(atual, parte)
        if not achados:
            return None
        atual = achados[0]
    return atual


def _classificar_preenchimento(elemento) -> Optional[str]:
    """Devolve o tipo de violação de preenchimento, ou None se está OK."""
    texto = elemento.text
    if texto is None or texto == "":
        # Tag existe mas sem conteúdo. Se tiver filhos, é um grupo, não um
        # campo simples - não é o nosso caso.
        return None if len(elemento) else "vazio"
    if not texto.strip():
        return "so_espacos"
    return None


def _numero_do_item(elemento) -> Optional[int]:
    """Sobe pelos ancestrais até achar um <det> e devolve o número do item.

    O atributo nItem é a fonte da verdade (é ele que a SEFAZ referencia nas
    rejeições); o índice posicional do xpath só serve de reserva, e pode
    divergir quando o gerador numera os itens fora de ordem."""
    atual = elemento
    while atual is not None:
        if isinstance(atual.tag, str) and atual.tag.split("}")[-1] == "det":
            numero = atual.get("nItem")
            if numero and numero.isdigit():
                return int(numero)
            pai = atual.getparent()
            if pai is not None:
                irmaos = [f for f in pai if f.tag == atual.tag]
                return irmaos.index(atual) + 1
            return 1
        atual = atual.getparent()
    return None


def _verificar_campos(grupo, caminho_grupo: str, campos: tuple[str, ...],
                      item: Optional[int]) -> list[dict]:
    """Reporta os campos da tabela que estão AUSENTES no grupo.

    Campo presente mas em branco não é tratado aqui: quem cobre isso é
    _varrer_tags_vazias(), que vale para todo o XML. Deixar a checagem em um
    lugar só evita o mesmo campo aparecer duas vezes no relatório."""
    erros: list[dict] = []
    for nome in campos:
        if _filhos(grupo, nome):
            continue
        loc = localizar(_xpath_de(grupo), grupo.sourceline, None)
        loc.item = item if item is not None else loc.item
        explicacao = montar_explicacao(nome, "obrigatorio_ausente", loc)
        erros.append(_erro("RN18-AUSENTE", explicacao, loc))
    return erros


def _varrer_tags_vazias(inf_nfe) -> list[dict]:
    """Reporta TODA tag folha vazia (ou só com espaços) dentro de <infNFe>.

    O layout 4.00 não tem nenhum tipo simples que aceite conteúdo vazio: se a
    tag existe, ela tem que ter valor. Por isso essa varredura é genérica -
    pega vBC, pICMS, xNome, qCom e qualquer campo futuro sem precisar entrar
    na tabela de obrigatórios, e é o que resolve o caso clássico
    '<vBC></vBC>' dentro de ICMS00, que o gerador do ERP deixa em branco
    quando o cálculo do imposto falha silenciosamente."""
    from .. import layout   # import tardio: ver a nota de ciclo em layout.py

    erros: list[dict] = []
    for elemento in inf_nfe.iter():
        if not isinstance(elemento.tag, str):
            continue
        if len(elemento):            # tem filhos: é grupo, não campo
            continue
        if elemento is inf_nfe:
            continue
        tipo = _classificar_preenchimento(elemento)
        if not tipo:
            continue

        nome = elemento.tag.split("}")[-1]

        # Duas exceções que o XSD conhece e nós não podíamos adivinhar. Ambas
        # apareceram em notas REAIS já autorizadas pela SEFAZ:
        #
        # 1. Grupo declarado sem filhos (`<infAdic></infAdic>`) não é campo em
        #    branco — é grupo vazio, e o layout permite.
        # 2. Alguns campos aceitam conteúdo vazio: `cBenef` tem o pattern
        #    `([!-ÿ]{8}|[!-ÿ]{10}|SEM CBENEF)?`, e o `?` final admite a string
        #    vazia. A premissa "no leiaute 4.00 nenhuma tag folha pode estar
        #    vazia" era simplesmente falsa.
        if layout.e_grupo(nome) or layout.aceita_vazio(nome):
            continue

        loc = localizar(_xpath_de(elemento), elemento.sourceline, nome)
        loc.item = _numero_do_item(elemento) or loc.item
        explicacao = montar_explicacao(nome, tipo, loc, valor=elemento.text or "")
        codigo = "RN18-VAZIO" if tipo == "vazio" else "RN18-ESPACOS"
        erros.append(_erro(codigo, explicacao, loc))
    return erros


def _verificar_escolha_exclusiva(grupo, caminho_grupo: str, opcoes: tuple[str, ...],
                                 obrigatorio: bool) -> list[dict]:
    presentes = [nome for nome in opcoes if _filhos(grupo, nome)]
    loc = localizar(_xpath_de(grupo), grupo.sourceline, None)
    rotulo = " ou ".join(f"<{o}>" for o in opcoes)

    if not presentes and obrigatorio:
        explicacao = montar_explicacao(
            opcoes[0], "obrigatorio_ausente", loc, esperado=rotulo,
        )
        explicacao["motivo_rejeicao"] = (
            f"{loc.descrever()}: o grupo <{caminho_grupo}> não informou nenhuma "
            f"identificação fiscal ({rotulo}) - o campo não existe no XML. "
            "Por que isso impede o envio: a SEFAZ precisa identificar essa parte da "
            "operação para validar cadastro e situação fiscal; sem CNPJ nem CPF a nota "
            "não pode ser processada. Como corrigir: informe exatamente uma das opções "
            f"({rotulo}), de acordo com a natureza da pessoa (jurídica ou física)."
        )
        return [_erro("RN18-IDENTIFICACAO-AUSENTE", explicacao, loc)]

    if len(presentes) > 1:
        explicacao = montar_explicacao(
            presentes[0], "grupo_exclusivo_violado", loc,
            esperado=rotulo, valor=", ".join(presentes),
        )
        explicacao["motivo_rejeicao"] = (
            f"{loc.descrever()}: o grupo <{caminho_grupo}> informou "
            f"{' e '.join(presentes)} ao mesmo tempo, mas o layout aceita apenas uma "
            f"dessas opções ({rotulo}). Por que isso impede o envio: a SEFAZ não "
            "consegue decidir qual documento identifica a pessoa, e a validação de "
            "cadastro fica ambígua. Como corrigir: mantenha apenas a opção correta e "
            "remova a outra do XML."
        )
        return [_erro("RN18-IDENTIFICACAO-DUPLICADA", explicacao, loc)]

    return []


def validar_campos_obrigatorios(arvore: etree._ElementTree) -> list[dict]:
    """Varre o XML e reporta TODOS os campos obrigatórios não preenchidos.

    Retorna a lista de erros no contrato padrão do validador. Grupos que não
    existem no XML são reportados uma única vez (como grupo incompleto), em vez
    de gerar um erro por campo filho - assim um <emit> ausente não produz sete
    erros dizendo a mesma coisa."""
    raiz = arvore.getroot()
    inf_nfe = _descer(raiz, "infNFe")
    if inf_nfe is None and str(raiz.tag).endswith("infNFe"):
        inf_nfe = raiz
    if inf_nfe is None:
        achados = raiz.findall(f".//{{{NS}}}infNFe") or raiz.findall(".//infNFe")
        if not achados:
            return []
        inf_nfe = achados[0]

    erros: list[dict] = []

    # Varredura generica de tags vazias primeiro: ela cobre qualquer campo do
    # layout, inclusive os que nao estao na tabela de obrigatorios.
    erros.extend(_varrer_tags_vazias(inf_nfe))

    for caminho, campos in OBRIGATORIOS_POR_GRUPO:
        grupo = _descer(inf_nfe, caminho)
        if grupo is None:
            # Grupo inteiro ausente: um erro só, com a lista do que falta.
            loc = localizar(_xpath_de(inf_nfe), inf_nfe.sourceline, None)
            explicacao = montar_explicacao(
                caminho.split("/")[-1], "obrigatorio_ausente", loc,
                esperado=", ".join(campos),
            )
            explicacao["motivo_rejeicao"] = (
                f"O grupo obrigatório <{caminho}> não existe no XML. Por que isso "
                "impede o envio: sem esse grupo faltam de uma vez todos os campos que "
                f"ele carrega ({', '.join(campos)}), e a SEFAZ não tem como validar essa "
                "parte da nota. Como corrigir: inclua o grupo completo, na posição e "
                "ordem definidas pelo layout."
            )
            erros.append(_erro("RN18-GRUPO-AUSENTE", explicacao, loc))
            continue
        erros.extend(_verificar_campos(grupo, caminho, campos, item=None))

    for caminho, opcoes, obrigatorio in ESCOLHAS_EXCLUSIVAS:
        grupo = _descer(inf_nfe, caminho)
        if grupo is not None:
            erros.extend(_verificar_escolha_exclusiva(grupo, caminho, opcoes, obrigatorio))

    itens = _filhos(inf_nfe, "det")
    for indice, det in enumerate(itens, start=1):
        # nItem é a fonte da verdade para o número do item; o índice é o fallback.
        numero = det.get("nItem")
        item = int(numero) if numero and numero.isdigit() else indice
        for caminho, campos in OBRIGATORIOS_POR_ITEM:
            grupo = _descer(det, caminho)
            if grupo is None:
                loc = localizar(_xpath_de(det), det.sourceline, None)
                loc.item = item
                explicacao = montar_explicacao(
                    caminho, "obrigatorio_ausente", loc, esperado=", ".join(campos),
                )
                explicacao["motivo_rejeicao"] = (
                    f"Item {item} da nota: o grupo obrigatório <{caminho}> não existe no "
                    "XML. Por que isso impede o envio: sem ele o item não tem descrição "
                    "nem valores, e a SEFAZ não consegue validar nem totalizar a nota. "
                    f"Como corrigir: inclua <{caminho}> no item com os campos "
                    f"{', '.join(campos)}."
                )
                erros.append(_erro("RN18-GRUPO-AUSENTE", explicacao, loc))
                continue
            erros.extend(_verificar_campos(grupo, caminho, campos, item=item))

    return erros
