"""
RN01/RN02/RN04 - Parsing do XML:
  - checa boa formação (well-formed) antes de qualquer outra coisa;
  - identifica tipo de documento (NFe/NFCe) e versão do layout;
  - extrai os campos usados pelas regras de negócio.
"""

from lxml import etree

NS = {"nfe": "http://www.portalfiscal.inf.br/nfe"}

MODELO_PARA_TIPO = {"55": "NFe", "65": "NFCe"}


class XmlMalformado(Exception):
    def __init__(self, mensagem: str, linha: int | None = None, coluna: int | None = None):
        super().__init__(mensagem)
        self.mensagem = mensagem
        self.linha = linha
        self.coluna = coluna


def parsear_xml(conteudo_xml: str) -> etree._ElementTree:
    """RN04: valida boa formação. Levanta XmlMalformado com detalhes se falhar."""
    try:
        parser = etree.XMLParser(resolve_entities=False, no_network=True)
        raiz = etree.fromstring(conteudo_xml.encode("utf-8"), parser=parser)
        return raiz.getroottree()
    except etree.XMLSyntaxError as exc:
        raise XmlMalformado(str(exc), getattr(exc, "lineno", None), getattr(exc, "offset", None)) from exc


def _texto(raiz, xpath: str) -> str | None:
    achou = raiz.xpath(xpath, namespaces=NS)
    if achou:
        valor = achou[0]
        return valor.text if hasattr(valor, "text") else str(valor)
    return None


def identificar_documento(arvore: etree._ElementTree) -> tuple[str, str]:
    """RN01/RN02: retorna (tipo_documento, versao) a partir do XML.
    tipo_documento: 'NFe' ou 'NFCe'. versao: ex. '4.00'."""
    raiz = arvore.getroot()

    inf_nfe = raiz.xpath("//nfe:infNFe", namespaces=NS)
    if not inf_nfe:
        # tenta sem namespace, caso o XML tenha sido enviado sem xmlns
        inf_nfe = raiz.xpath("//infNFe")
    if not inf_nfe:
        raise ValueError(
            "Não foi encontrado o elemento <infNFe> no XML. Verifique se o "
            "arquivo é realmente uma NF-e/NFC-e no layout nacional."
        )
    inf_nfe = inf_nfe[0]

    versao = inf_nfe.get("versao")
    if not versao:
        raise ValueError(
            "O atributo 'versao' não foi encontrado em <infNFe>. Esse "
            "atributo é obrigatório para selecionar o XSD correto (RN02)."
        )

    mod = _texto(raiz, "//nfe:ide/nfe:mod") or _texto(raiz, "//ide/mod")
    tipo_documento = MODELO_PARA_TIPO.get(mod)
    if not tipo_documento:
        raise ValueError(
            f"O campo <mod> tem valor '{mod}', que não corresponde a NF-e "
            "(55) nem NFC-e (65). Este validador só cobre esses dois modelos (RN01)."
        )

    return tipo_documento, versao


def extrair_campos_ide(arvore: etree._ElementTree) -> dict:
    raiz = arvore.getroot()
    return {
        "mod": _texto(raiz, "//nfe:ide/nfe:mod") or _texto(raiz, "//ide/mod"),
        "serie": _texto(raiz, "//nfe:ide/nfe:serie") or _texto(raiz, "//ide/serie"),
        "nNF": _texto(raiz, "//nfe:ide/nfe:nNF") or _texto(raiz, "//ide/nNF"),
        "dhEmi": _texto(raiz, "//nfe:ide/nfe:dhEmi") or _texto(raiz, "//ide/dhEmi"),
    }


def extrair_campos_emit(arvore: etree._ElementTree) -> dict:
    raiz = arvore.getroot()
    return {
        "CNPJ": _texto(raiz, "//nfe:emit/nfe:CNPJ") or _texto(raiz, "//emit/CNPJ"),
        "CPF": _texto(raiz, "//nfe:emit/nfe:CPF") or _texto(raiz, "//emit/CPF"),
        "IE": _texto(raiz, "//nfe:emit/nfe:IE") or _texto(raiz, "//emit/IE"),
    }


def extrair_campos_dest(arvore: etree._ElementTree) -> dict:
    raiz = arvore.getroot()
    return {
        "CNPJ": _texto(raiz, "//nfe:dest/nfe:CNPJ") or _texto(raiz, "//dest/CNPJ"),
        "CPF": _texto(raiz, "//nfe:dest/nfe:CPF") or _texto(raiz, "//dest/CPF"),
    }


def extrair_chave_acesso(arvore: etree._ElementTree) -> str | None:
    raiz = arvore.getroot()
    inf_nfe = raiz.xpath("//nfe:infNFe", namespaces=NS) or raiz.xpath("//infNFe")
    if not inf_nfe:
        return None
    id_attr = inf_nfe[0].get("Id") or ""
    return id_attr.replace("NFe", "").strip() or None


def extrair_totais(arvore: etree._ElementTree) -> dict:
    raiz = arvore.getroot()

    def num(xpath):
        v = _texto(raiz, xpath)
        try:
            return float(v) if v is not None else 0.0
        except ValueError:
            return 0.0

    itens = raiz.xpath("//nfe:det", namespaces=NS) or raiz.xpath("//det")
    soma_vprod = 0.0
    soma_vicms = 0.0
    for item in itens:
        vprod = item.xpath(".//nfe:prod/nfe:vProd/text()", namespaces=NS) or item.xpath(".//prod/vProd/text()")
        vicms = item.xpath(".//nfe:ICMS//nfe:vICMS/text()", namespaces=NS) or item.xpath(".//ICMS//vICMS/text()")
        soma_vprod += float(vprod[0]) if vprod else 0.0
        soma_vicms += float(vicms[0]) if vicms else 0.0

    # Todos os componentes de <ICMSTot>, para a RN11 poder recompor vNF pela
    # fórmula do MOC em vez de comparar só com a soma de vProd.
    componentes: dict[str, float] = {}
    tot = raiz.xpath("//nfe:ICMSTot", namespaces=NS) or raiz.xpath("//ICMSTot")
    if tot:
        for filho in tot[0]:
            if not isinstance(filho.tag, str):
                continue
            nome = filho.tag.split("}")[-1]
            try:
                componentes[nome] = float(filho.text) if (filho.text or "").strip() else 0.0
            except ValueError:
                componentes[nome] = 0.0

    return {
        "soma_vprod_itens": soma_vprod,
        "soma_vicms_itens": soma_vicms,
        "vProd_total": num("//nfe:ICMSTot/nfe:vProd") or num("//ICMSTot/vProd"),
        "vICMS_total": num("//nfe:ICMSTot/nfe:vICMS") or num("//ICMSTot/vICMS"),
        "vNF": num("//nfe:ICMSTot/nfe:vNF") or num("//ICMSTot/vNF"),
        "componentes_icmstot": componentes,
    }
