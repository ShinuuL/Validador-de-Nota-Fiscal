"""
Validação estrutural (XSD) do XML de NF-e/NFC-e.

Regras de negócio implementadas aqui (ver spec, Seção 3.2):
  RN04 - só valida XSD se o XML já estiver bem-formado.
  RN05 - usa exclusivamente arquivos .xsd oficiais fornecidos pelo usuário
         em schemas/v{versao}/{tipo}/ (nunca recria regra "de memória").
  RN07 - cada erro de schema é reportado com xpath + linha + mensagem original,
         além da explicação de negócio (catálogo).

Classificação de mensagens (v2)
-------------------------------
O lxml devolve mensagens cruas em inglês, com formatos bem distintos. Antes,
quase tudo caía em "estrutura_inesperada" e a lista de valores aceitos era
descartada - o usuário recebia "campo fora do padrão" sem saber qual padrão.
Agora `analisar_mensagem` reconhece os formatos de facet do libxml2
(enumeration, pattern, length, minInclusive...) e preserva a LISTA COMPLETA de
valores/campos esperados, que vira a orientação de correção.
"""

import re
from pathlib import Path
from typing import Optional

from lxml import etree

from . import servicos
from .catalogo_erros import ContextoDocumento, montar_explicacao
from .localizacao import caminho_legivel, localizar

# Os XSDs moram DENTRO do pacote (não ao lado dele) para viajarem no
# `pip install`. Fora do pacote, um ambiente instalado ficaria sem nenhum XSD e
# o validador degradaria em silêncio para o aviso XSD-INDISPONIVEL em toda
# nota — perdendo validação estrutural, RN19 e as descrições oficiais.
# A estrutura interna segue a RN14: schemas/v{versao}/{tipo}/.
#
# `parents[1]` e nao `parent`: este modulo mora em `nfe_validator/nucleo/`, e
# os XSD ficam na raiz do pacote, ao lado de `web/`. Errar esse nivel nao
# levanta excecao - a pasta simplesmente nao existe e toda nota passa a sair
# com XSD-INDISPONIVEL, que e exatamente o modo de falha silencioso que o
# comentario acima descreve.
SCHEMAS_DIR = Path(__file__).resolve().parents[1] / "schemas"

NS_NFE = "http://www.portalfiscal.inf.br/nfe"

# Arquivo raiz esperado dentro de cada pasta de schema. O XSD oficial da
# SEFAZ para NF-e usa o nome "nfe_v4.00.xsd" como ponto de entrada
# (que por sua vez importa leiauteNFe_v4.00.xsd, tiposBasico_v4.00.xsd etc).
# Ajuste este nome caso a estrutura oficial baixada seja diferente.
ARQUIVOS_ENTRADA = {
    "NFe": "nfe_v{versao}.xsd",
    "NFCe": "nfce_v{versao}.xsd",
}

# Ponto de entrada por RAIZ do documento. O ERP não transmite uma <NFe> nua:
# ele monta e valida um <enviNFe>, e o que volta autorizado é um <nfeProc>
# (NFe + protNFe). Cada um tem seu próprio XSD de entrada, que só declara a
# raiz global e inclui o mesmo leiauteNFe.
#
# Com estes arquivos instalados, validamos o envelope INTEIRO — inclusive o
# protNFe — em vez de extrair a <NFe> e ignorar o resto.
# A raiz <NFe> nua fica de FORA deste mapa de proposito: o nome do XSD de
# entrada dela varia por tipo de documento (nfe_ x nfce_), entao quem resolve e
# ARQUIVOS_ENTRADA. Fixa-la aqui apontaria a NFC-e para "nfe_v4.00.xsd".
# Só as raízes que CONTÊM uma nota: `identificar_documento` acha o <infNFe>
# lá dentro, e as regras de negócio da nota se aplicam ao que está no envelope.
#
# `retEnviNFe` e `retConsReciNFe` saíram daqui para o registro em `servicos`.
# Apesar do nome, não trazem nota nenhuma - <infRec> e <protNFe>, sem <infNFe>
# -, então `identificar_documento` falhava neles e este mapa nunca era
# alcançado por `validar()`. Os XSDs continuam na pasta da nota, porque incluem
# o `leiauteNFe` completo; o que mudou é quem faz o roteamento.
ENTRADA_POR_RAIZ = {
    "enviNFe": "enviNFe_v{versao}.xsd",
    "nfeProc": "procNFe_v{versao}.xsd",
}

# Tipos do XSD que representam número - usados para escolher entre
# "decimal_invalido" (mensagem com dica de formatação) e "tipo_invalido".
_TIPOS_NUMERICOS = re.compile(
    r"TDec|decimal|double|float|integer|^int$|long|short|byte|nonNegative|positiveInteger",
    re.IGNORECASE,
)


class SchemaIndisponivel(Exception):
    """Levantado quando não há XSD instalado para o tipo/versão do XML."""


def caminho_schema(tipo_documento: str, versao: str,
                   raiz: Optional[str] = None) -> Path:
    """Caminho do XSD de entrada.

    `raiz`: nome da tag raiz do documento a validar. Quando informada e
    conhecida, escolhe o XSD de entrada daquele envelope; senão cai no XSD da
    <NFe> nua, que é o comportamento anterior."""
    # Documento de serviço (evento, consulta, inutilização): a família dita a
    # pasta e o arquivo de entrada, e ela vem do registro em `servicos`. Os
    # eventos moram em v1.00/evento/ e a consulta cadastro em v2.00/conscad/,
    # então a pasta NÃO pode sair de `tipo_documento` como na nota.
    servico = servicos.SERVICOS.get(raiz) if raiz else None
    if servico is not None:
        pasta = SCHEMAS_DIR / f"v{versao}" / servico.tipo.lower()
        return pasta / servico.entrada.format(versao=versao)

    pasta = SCHEMAS_DIR / f"v{versao}" / tipo_documento.lower()
    modelo = ""
    if raiz and raiz in ENTRADA_POR_RAIZ:
        modelo = ENTRADA_POR_RAIZ[raiz]
    if not modelo:
        modelo = ARQUIVOS_ENTRADA.get(tipo_documento, "")
    return pasta / modelo.format(versao=versao)


def carregar_schema(tipo_documento: str, versao: str,
                    raiz: Optional[str] = None) -> etree.XMLSchema:
    caminho = caminho_schema(tipo_documento, versao, raiz)
    if not caminho.exists():
        alvo = f"raiz <{raiz}> de " if raiz else ""
        raise SchemaIndisponivel(
            f"Nenhum XSD oficial encontrado para a {alvo}{tipo_documento} versão "
            f"{versao} em '{caminho}'. Baixe o XSD oficial da SEFAZ/ENCAT e "
            f"coloque-o nesse caminho (ver schemas/README.md)."
        )
    with open(caminho, "rb") as f:
        xsd_doc = etree.parse(f)
    return etree.XMLSchema(xsd_doc)


def _tag_sem_namespace(nome: str) -> str:
    return nome.split("}")[-1] if "}" in nome else nome


def _extrair_grupo_pai(xpath: Optional[str]) -> Optional[str]:
    """Compatibilidade: devolve o grupo tributário mais próximo no xpath.
    A implementação real vive em localizacao.localizar(), que resolve o grupo
    de dentro para fora e reconhece subgrupos (ICMS00, PISAliq, ...)."""
    return localizar(xpath).grupo_tributario


# Lista de nomes/valores dentro dos parênteses de "Expected is ( ... )".
_LISTA_NOMES = re.compile(r"(?:\{[^}]*\})?([\w.:-]+)")


def _limpar_lista(bruto: str, limite: int = 8) -> str:
    """Normaliza a lista de valores/campos esperados que o libxml2 imprime,
    removendo namespaces e truncando listas gigantes (a enumeração de CST/CFOP
    tem dezenas de itens e não ajuda em uma mensagem de erro)."""
    nomes = [n for n in _LISTA_NOMES.findall(bruto or "") if n]
    if not nomes:
        return ""
    if len(nomes) > limite:
        return ", ".join(nomes[:limite]) + f" ... (+{len(nomes) - limite} valores)"
    return ", ".join(nomes)


def analisar_mensagem(mensagem: str) -> dict:
    """Traduz a mensagem crua do libxml2 em um diagnóstico estruturado.

    Devolve: tipo_violacao, tag (o campo culpado), valor (o que veio no XML),
    esperado (lista de valores/campos aceitos) e ancora (o elemento em que o
    libxml2 pendurou o erro, que para 'Missing child' é o GRUPO PAI, não o
    campo faltante - distinção que importa para localizar o problema)."""
    msg = mensagem or ""

    def resultado(tipo, tag="", valor="", esperado="", ancora=""):
        return {
            "tipo_violacao": tipo,
            "tag": _tag_sem_namespace(tag),
            "valor": valor,
            "esperado": esperado,
            "ancora": _tag_sem_namespace(ancora),
        }

    # --- Facets: as mensagens mais informativas do libxml2 ---
    # [facet 'enumeration'] The value 'X' is not an element of the set {'a','b'}.
    m = re.search(
        r"Element '([^']+)'.*?\[facet 'enumeration'\].*?The value '([^']*)' is not an "
        r"element of the set \{([^}]*)\}",
        msg,
    )
    if m:
        return resultado("fora_da_enumeracao", m.group(1), m.group(2),
                         _limpar_lista(m.group(3)), m.group(1))

    # [facet 'pattern'] The value 'X' is not accepted by the pattern 'P'.
    m = re.search(
        r"Element '([^']+)'.*?The value '([^']*)' is not accepted by the pattern '([^']*)'",
        msg,
    )
    if m:
        return resultado("fora_do_padrao", m.group(1), m.group(2),
                         f"padrão {m.group(3)}", m.group(1))

    # Variante sem o valor explícito.
    m = re.search(r"Element '([^']+)'.*?is not accepted by the pattern '([^']*)'", msg)
    if m:
        return resultado("fora_do_padrao", m.group(1), "", f"padrão {m.group(2)}", m.group(1))

    m = re.search(r"Element '([^']+)'.*?is not accepted by the pattern", msg)
    if m:
        return resultado("fora_do_padrao", m.group(1), "", "", m.group(1))

    # [facet 'minLength'/'maxLength'/'length'] ... has a length of N ...
    m = re.search(
        r"Element '([^']+)'.*?\[facet '(?:min|max)?[Ll]ength'\].*?The value(?: has a length of "
        r"'?(\d+)'?)?",
        msg,
    )
    if m:
        alvo = re.search(r"this underruns|exceeds|allowed (?:minimum|maximum) length of '?(\d+)", msg)
        esperado = f"tamanho {alvo.group(1)}" if alvo and alvo.group(1) else ""
        return resultado("tamanho_invalido", m.group(1), m.group(2) or "", esperado, m.group(1))

    # [facet 'minInclusive'/'maxInclusive'/'totalDigits'/'fractionDigits']
    m = re.search(
        r"Element '([^']+)'.*?\[facet '(\w+)'\].*?The value '([^']*)'", msg
    )
    if m:
        return resultado("fora_do_padrao", m.group(1), m.group(3),
                         f"restrição {m.group(2)}", m.group(1))

    # --- Valor inválido para o tipo atômico ---
    # Element 'vBC': '' is not a valid value of the atomic type 'TDec_1302'.
    m = re.search(
        r"Element '([^']+)':\s*'([^']*)' is not a valid value of (?:the )?(?:atomic |list |union )?"
        r"type '([^']*)'",
        msg,
    )
    if m:
        tag, valor = m.group(1), m.group(2)
        tipo_xsd = _tag_sem_namespace(m.group(3))
        rotulo_tipo = f"tipo {tipo_xsd}" if tipo_xsd else ""
        if valor == "":
            # Campo em branco: o nome do tipo XSD não ajuda quem vai corrigir.
            return resultado("vazio", tag, "", "", tag)
        if not valor.strip():
            return resultado("so_espacos", tag, valor, "", tag)
        if _TIPOS_NUMERICOS.search(tipo_xsd):
            return resultado("decimal_invalido", tag, valor, rotulo_tipo, tag)
        return resultado("tipo_invalido", tag, valor, rotulo_tipo, tag)

    # Forma reduzida, sem o nome do tipo.
    m = re.search(r"Element '([^']+)':\s*'([^']*)'\s+is not a valid value", msg)
    if m:
        valor = m.group(2)
        if valor == "":
            return resultado("vazio", m.group(1), "", "", m.group(1))
        if not valor.strip():
            return resultado("so_espacos", m.group(1), valor, "", m.group(1))
        return resultado("tipo_invalido", m.group(1), valor, "", m.group(1))

    # --- Elemento presente mas fora de ordem / não esperado ---
    m = re.search(
        r"Element '([^']+)':\s*This element is not expected\."
        r"(?:\s*Expected is (?:one of )?\(([^)]*)\))?",
        msg,
    )
    if m:
        return resultado("estrutura_inesperada", m.group(1), "",
                         _limpar_lista(m.group(2) or ""), m.group(1))

    # --- Grupo aberto sem os filhos obrigatórios ---
    # Element 'ICMS00': Missing child element(s). Expected is ( vBC ).
    m = re.search(
        r"(?:Element '([^']+)':\s*)?Missing child element\(s\)\.\s*"
        r"Expected is (?:one of )?\(([^)]*)\)",
        msg,
    )
    if m:
        ancora = m.group(1) or ""
        esperados = _LISTA_NOMES.findall(m.group(2) or "")
        if len(esperados) == 1:
            # Um único candidato: sabemos exatamente qual campo falta.
            return resultado("obrigatorio_ausente", esperados[0], "", "", ancora)
        # Vários candidatos (choice): o grupo está incompleto, mas o campo
        # exato depende da operação - reportamos o grupo com as opções.
        return resultado("grupo_incompleto", ancora or (esperados[0] if esperados else ""),
                         "", _limpar_lista(m.group(2)), ancora)

    m = re.search(r"Element '([^']+)':\s*Missing child element\(s\)", msg)
    if m:
        return resultado("grupo_incompleto", m.group(1), "", "", m.group(1))

    # --- Elemento obrigatório faltando (outras redações) ---
    m = re.search(r"Element '([^']+)'.*?[Mm]issing", msg)
    if m:
        return resultado("obrigatorio_ausente", m.group(1), "", "", m.group(1))

    # --- Raiz sem declaração no schema: layout/versão errados ---
    m = re.search(r"Element '([^']+)':\s*No matching global declaration", msg)
    if m:
        return resultado("estrutura_inesperada", m.group(1), "",
                         "elemento raiz declarado no XSD desta versão", m.group(1))

    m = re.search(r"Element '([^']+)'", msg)
    if m:
        return resultado("estrutura_inesperada", m.group(1), "", "", m.group(1))

    return resultado("estrutura_inesperada", "desconhecido")


def _indexar_por_linha(xml_doc: etree._ElementTree) -> dict[int, list]:
    """Agrupa os elementos do XML pela linha em que abrem, para conseguir
    reencontrar o elemento a que cada erro de XSD se refere."""
    indice: dict[int, list] = {}
    for elemento in xml_doc.iter():
        if not isinstance(elemento.tag, str):
            continue
        linha = elemento.sourceline
        if linha is not None:
            indice.setdefault(linha, []).append(elemento)
    return indice


def _elemento_do_erro(indice: dict[int, list], linha, ancora: str):
    """Encontra o elemento que o libxml2 apontou. Prefere o que tem o mesmo
    nome da ancora da mensagem; se nao houver, cai no primeiro da linha."""
    if linha is None:
        return None
    candidatos = indice.get(linha) or []
    if not candidatos:
        return None
    if ancora:
        for elemento in candidatos:
            if elemento.tag.split("}")[-1] == ancora:
                return elemento
    return candidatos[0]


def _classificar_e_extrair(mensagem: str) -> tuple[str, str, str, str]:
    """Compatibilidade com a assinatura anterior: (tipo, tag, valor, esperado)."""
    analise = analisar_mensagem(mensagem)
    return (
        analise["tipo_violacao"],
        analise["tag"],
        analise["valor"],
        analise["esperado"],
    )


# Envelopes que carregam uma <NFe> dentro. O XSD de entrada que temos
# (`nfe_v4.00.xsd`) declara como raiz global apenas `NFe`, então validar um
# envelope direto devolve "No matching global declaration available for the
# validation root" — um erro nosso, disfarçado de erro da nota.
#
# Os XSDs próprios de envelope existem no pacote oficial (`procNFe_v4.00.xsd`,
# `enviNFe_v4.00.xsd`) mas não estão instalados aqui. Enquanto não estiverem,
# extraímos a <NFe> e validamos ela — o que é honesto: valida o que dá para
# validar, e não inventa um veredito sobre a parte não coberta.
ENVELOPES_COM_NFE = ("nfeProc", "enviNFe", "procNFe", "retEnviNFe")


def _desembrulhar_envelope(xml_doc: etree._ElementTree) -> etree._ElementTree:
    """Se a raiz é um envelope, devolve a árvore da <NFe> interna.

    Os arquivos que o ERP guarda e transmite são envelopes: `enviNFe` no envio
    e `nfeProc` (NFe + protNFe) depois da autorização. Uma nota autorizada de
    verdade chegava aqui e era reprovada só por causa da raiz."""
    raiz = xml_doc.getroot()
    nome = str(raiz.tag).split("}")[-1]
    if nome not in ENVELOPES_COM_NFE:
        return xml_doc

    internas = raiz.findall(f"{{{NS_NFE}}}NFe") or raiz.findall("NFe")
    if not internas:
        return xml_doc
    # `getroottree()` num filho devolve a árvore do DOCUMENTO (ainda enraizada
    # no envelope) — tem que ser uma árvore nova, enraizada na <NFe>.
    return etree.ElementTree(internas[0])


def validar_contra_xsd(xml_doc: etree._ElementTree, tipo_documento: str, versao: str) -> list[dict]:
    """Valida o XML já parseado contra o XSD oficial e devolve uma lista de
    erros estruturados, cada um já com a explicação de negócio.

    Erros repetidos (mesma violação, mesmo campo, mesma linha) são colapsados:
    o libxml2 costuma emitir a mesma queixa várias vezes ao tentar casar
    alternativas de um <choice>, e isso inflava o relatório."""
    raiz = str(xml_doc.getroot().tag).split("}")[-1]

    # Documento de serviço: não há nota dentro para desembrulhar, e cair no
    # XSD da nota daria uma enxurrada de erros sobre a raiz errada. Se o XSD da
    # família não estiver instalado, `carregar_schema` levanta
    # SchemaIndisponivel e quem chama transforma isso no aviso XSD-INDISPONIVEL
    # (RN15: falhar explicitamente, nunca validar contra o schema errado).
    if raiz in servicos.SERVICOS:
        schema = carregar_schema(tipo_documento, versao, raiz)

    # Com o XSD do envelope instalado, validamos o documento como ele é. Sem
    # ele, extraímos a <NFe> — valida menos, mas não reprova a nota por causa
    # de uma raiz que o nosso schema não conhece.
    elif raiz in ENTRADA_POR_RAIZ and caminho_schema(tipo_documento, versao, raiz).exists():
        schema = carregar_schema(tipo_documento, versao, raiz)
    else:
        schema = carregar_schema(tipo_documento, versao)
        xml_doc = _desembrulhar_envelope(xml_doc)

    # Contexto do documento, montado uma vez: leva as mensagens ao leiaute
    # certo (um evento não tem `cOrgao` no leiauteNFe) e faz o texto genérico
    # dizer "A SEFAZ rejeita o evento" em vez de "a nota".
    servico = servicos.SERVICOS.get(raiz)
    contexto_documento = ContextoDocumento(
        tipo=servico.tipo if servico else tipo_documento,
        versao=versao,
        raiz=raiz,
        substantivo=servico.substantivo if servico else "a nota",
    )

    erros: list[dict] = []

    if schema.validate(xml_doc):
        return erros

    vistos: set[tuple] = set()
    indice_por_linha = _indexar_por_linha(xml_doc)

    for log in schema.error_log:
        analise = analisar_mensagem(log.message)
        tag = analise["tag"]

        # A âncora do libxml2 é o elemento onde o erro foi detectado; para
        # "Missing child" ela é o grupo pai, então o campo faltante NÃO deve
        # ser removido do fim do xpath.
        tag_a_descartar = tag if analise["ancora"] == tag else None

        # log.path vem como "/*/*/*[1]" quando o XML usa namespace default,
        # então preferimos reconstruir o caminho a partir do elemento real.
        elemento = _elemento_do_erro(indice_por_linha, log.line, analise["ancora"])
        caminho = caminho_legivel(elemento) if elemento is not None else log.path
        loc = localizar(caminho, log.line, tag_a_descartar)

        chave = (analise["tipo_violacao"], tag, loc.xpath, log.line)
        if chave in vistos:
            continue
        vistos.add(chave)

        explicacao = montar_explicacao(
            tag,
            analise["tipo_violacao"],
            localizacao=loc,
            valor=analise["valor"],
            esperado=analise["esperado"],
            documento=contexto_documento,
        )

        erros.append({
            "codigo": f"XSD-{analise['tipo_violacao'].upper()}",
            "campo": explicacao["campo"],
            "xpath": loc.xpath,
            "linha": log.line,
            "mensagem_tecnica": log.message,
            "mensagem": explicacao["motivo_rejeicao"],
            "motivo_rejeicao": explicacao["motivo_rejeicao"],
            "origem": "xsd",
            "subOrigem": "schema",
            "severidade": "erro",
            "detalhe": explicacao,
        })

    return erros
