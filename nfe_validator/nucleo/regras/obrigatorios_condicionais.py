"""
RN19 - Obrigatoriedade CONDICIONAL, derivada do XSD oficial.

A diferença em relação à RN18
-----------------------------
A RN18 cobre o que é obrigatório em QUALQUER nota (`ide/cUF`, `prod/NCM`...).
Mas a maior parte das rejeições reais da SEFAZ é condicional: o campo só é
exigido por causa de outra coisa que a nota declarou. `vBC` do ICMS é
obrigatório num ICMS00 e nem existe num ICMS40; `pRedBC` é obrigatório só no
ICMS20; `pFCP` e `vFCP` são opcionais, mas informar um sem o outro é inválido.

De onde vêm essas regras (RN05)
-------------------------------
Nenhuma delas está escrita aqui. Todas saem do `layout.py`, que as lê do XSD
oficial em `schemas/`: o `xs:choice` do ICMS tem 21 variantes, e o complexType
de cada uma declara exatamente quais campos aquele CST exige. Escrever essa
tabela à mão a partir do MOC seria a "regra recriada de memória" que a RN05
proíbe — e erraria: `ICMSSN102`, por exemplo, tem `orig` com `minOccurs="0"`,
ao contrário de todas as variantes de ICMS normal.

Por que não basta o XSD já validar isso
---------------------------------------
O libxml2 valida, mas para no PRIMEIRO campo faltante de cada grupo e reporta
"Missing child element(s)" apontando para o grupo, não para o campo. Num
ICMS00 sem `vBC`, `pICMS` e `vICMS`, ele devolve um erro; o usuário corrige,
reenvia, e descobre o segundo. Aqui reportamos os três de uma vez, cada um
dizendo qual grupo tornou o campo obrigatório.

Por que a variante é lida do XML, e não deduzida do CST
-------------------------------------------------------
Cinco CSTs do ICMS (10, 20, 41, 60 e 90) são enumerados em mais de uma
variante — o CST 20 vale para `ICMS20` e para `ICMSPart`. Então o caminho
confiável é o inverso: ver qual variante o XML realmente abriu e conferir os
campos DELA. O CST serve para uma checagem separada (ele combina com o grupo
onde foi declarado?), não para escolher a regra.
"""

from typing import Optional

from lxml import etree

from .. import layout
from ..catalogo_erros import montar_explicacao
from ..localizacao import caminho_legivel, localizar
from .campos_obrigatorios import _descer, _filhos, _numero_do_item

# Grupos de imposto do item que usam xs:choice de variantes no leiaute.
GRUPOS_COM_VARIANTE = ("ICMS", "IPI", "PIS", "COFINS")


def _erro(codigo: str, explicacao: dict, localizacao) -> dict:
    return {
        "codigo": codigo,
        "campo": explicacao["campo"],
        "xpath": localizacao.xpath,
        "linha": localizacao.linha,
        "mensagem_tecnica": (
            f"{explicacao['tagXml']}: {explicacao['tipoViolacao']}"
            + (f" (gatilho: {explicacao['gatilho'].strip()})" if explicacao.get("gatilho") else "")
        ),
        "mensagem": explicacao["motivo_rejeicao"],
        "motivo_rejeicao": explicacao["motivo_rejeicao"],
        "origem": "regra-negocio",
        "subOrigem": "obrigatorio-condicional",
        "severidade": "erro",
        "detalhe": explicacao,
    }


def _variante_presente(grupo_elemento, nomes_de_variante: tuple[str, ...]):
    """Qual variante o XML abriu dentro deste grupo de imposto."""
    for filho in grupo_elemento:
        if not isinstance(filho.tag, str):
            continue
        nome = filho.tag.split("}")[-1]
        if nome in nomes_de_variante:
            return nome, filho
    return None, None


def _presentes(elemento) -> set[str]:
    """Nomes dos filhos diretos presentes, sem namespace."""
    return {
        filho.tag.split("}")[-1]
        for filho in elemento
        if isinstance(filho.tag, str)
    }


def _localizar(elemento, tag: Optional[str], item: Optional[int]):
    loc = localizar(caminho_legivel(elemento), elemento.sourceline, tag)
    loc.item = item if item is not None else loc.item
    return loc


def _conferir_codigo(variante, elemento, item: Optional[int]) -> list[dict]:
    """O CST/CSOSN declarado é aceito pelo grupo em que foi escrito?"""
    if not variante.campo_do_codigo or not variante.codigos:
        return []

    achados = _filhos(elemento, variante.campo_do_codigo)
    if not achados:
        return []
    valor = (achados[0].text or "").strip()
    if not valor or valor in variante.codigos:
        return []

    # Onde esse código seria válido? É a informação que resolve o problema.
    candidatos = layout.variantes_para_cst(variante.grupo, valor)
    if candidatos:
        destino = " ou ".join(f"<{c.nome}>" for c in candidatos)
        esperado = (
            f"o código '{valor}' pertence ao grupo {destino}; "
            f"<{variante.nome}> aceita {', '.join(variante.codigos)}"
        )
    else:
        esperado = (
            f"<{variante.nome}> aceita apenas {', '.join(variante.codigos)}, e o código "
            f"'{valor}' não consta em nenhuma variante de {variante.grupo} no layout"
        )

    loc = _localizar(achados[0], variante.campo_do_codigo, item)
    explicacao = montar_explicacao(
        variante.campo_do_codigo, "codigo_incompativel_com_grupo", loc,
        valor=valor, esperado=esperado,
    )
    return [_erro("RN19-CODIGO-INCOMPATIVEL", explicacao, loc)]


def _conferir_obrigatorios(variante, elemento, item: Optional[int]) -> list[dict]:
    """Campos que ESTA variante exige e que o XML não trouxe."""
    presentes = _presentes(elemento)
    erros: list[dict] = []
    gatilho = f" porque o grupo informado é <{variante.nome}>"

    for campo in variante.obrigatorios:
        if campo in presentes:
            continue
        loc = _localizar(elemento, None, item)
        explicacao = montar_explicacao(
            campo, "obrigatorio_condicional_ausente", loc,
            esperado=f"exigido por <{variante.nome}>",
            grupo_pai=variante.grupo,
            gatilho=gatilho,
        )
        erros.append(_erro("RN19-CONDICIONAL-AUSENTE", explicacao, loc))
    return erros


def _conferir_todos_ou_nada(variante, elemento, item: Optional[int]) -> list[dict]:
    """Grupos opcionais em conjunto: meio preenchido é inválido."""
    presentes = _presentes(elemento)
    erros: list[dict] = []

    for grupo in variante.todos_ou_nada:
        informados = [c for c in grupo.campos if c in presentes]
        if not informados or len(informados) == len(grupo.campos):
            continue  # nenhum ou todos: ambos válidos
        faltando = [c for c in grupo.campos if c not in presentes]
        loc = _localizar(elemento, None, item)
        explicacao = montar_explicacao(
            faltando[0], "grupo_parcialmente_preenchido", loc,
            esperado=(
                f"o grupo é ({', '.join(grupo.campos)}); "
                f"informado: {', '.join(informados)}; falta: {', '.join(faltando)}"
            ),
            grupo_pai=variante.grupo,
            gatilho=f" porque <{informados[0]}> foi informado",
        )
        erros.append(_erro("RN19-GRUPO-INCOMPLETO", explicacao, loc))
    return erros


def _conferir_alternativas(variante, elemento, item: Optional[int]) -> list[dict]:
    """Caminhos mutuamente exclusivos (IPITrib: vBC+pIPI XOR qUnid+vUnid)."""
    if len(variante.alternativas) < 2:
        return []

    presentes = _presentes(elemento)
    ramos_tocados = [
        alt for alt in variante.alternativas
        if any(campo in presentes for campo in alt.campos)
    ]
    completos = [
        alt for alt in variante.alternativas
        if all(campo in presentes for campo in alt.campos)
    ]
    if len(completos) == 1 and len(ramos_tocados) == 1:
        return []   # exatamente um caminho, inteiro: correto

    rotulo = " | ".join("(" + ", ".join(alt.campos) + ")" for alt in variante.alternativas)
    if len(ramos_tocados) > 1:
        gatilho = " porque campos de mais de um caminho foram informados"
    elif ramos_tocados:
        gatilho = " porque o caminho iniciado não foi completado"
    else:
        gatilho = " porque nenhum dos caminhos foi informado"

    referencia = ramos_tocados[0].campos[0] if ramos_tocados else variante.alternativas[0].campos[0]
    loc = _localizar(elemento, None, item)
    explicacao = montar_explicacao(
        referencia, "alternativa_violada", loc,
        esperado=rotulo, grupo_pai=variante.grupo, gatilho=gatilho,
    )
    return [_erro("RN19-ALTERNATIVA-VIOLADA", explicacao, loc)]


def validar_obrigatorios_condicionais(arvore: etree._ElementTree,
                                      tipo_documento: str = "NFe",
                                      versao: str = "4.00") -> list[dict]:
    """Confere, item a item, a obrigatoriedade condicional dos grupos de imposto.

    Degrada para lista vazia se o modelo de leiaute não estiver disponível —
    esta regra não pode ser uma nova causa de falha."""
    modelo = layout.carregar_modelo(tipo_documento, versao)
    if modelo is None:
        return []

    raiz = arvore.getroot()
    inf_nfe = _descer(raiz, "infNFe")
    if inf_nfe is None:
        achados = (raiz.findall(".//{http://www.portalfiscal.inf.br/nfe}infNFe")
                   or raiz.findall(".//infNFe"))
        if not achados:
            return []
        inf_nfe = achados[0]

    erros: list[dict] = []

    for det in _filhos(inf_nfe, "det"):
        numero = det.get("nItem")
        item = int(numero) if numero and numero.isdigit() else _numero_do_item(det)

        imposto = _descer(det, "imposto")
        if imposto is None:
            continue

        for nome_grupo in GRUPOS_COM_VARIANTE:
            nomes_de_variante = modelo.variantes_por_grupo.get(nome_grupo, ())
            if not nomes_de_variante:
                continue

            for grupo_elemento in _filhos(imposto, nome_grupo):
                nome_variante, elemento = _variante_presente(grupo_elemento, nomes_de_variante)
                if elemento is None:
                    # Grupo aberto sem nenhuma variante dentro. Quem reporta é
                    # o XSD (grupo_incompleto) - não duplicamos aqui.
                    continue

                variante = modelo.variantes.get(nome_variante)
                if variante is None:
                    continue

                erros.extend(_conferir_codigo(variante, elemento, item))
                erros.extend(_conferir_obrigatorios(variante, elemento, item))
                erros.extend(_conferir_todos_ou_nada(variante, elemento, item))
                erros.extend(_conferir_alternativas(variante, elemento, item))

    return erros
