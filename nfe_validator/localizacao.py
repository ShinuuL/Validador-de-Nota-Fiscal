"""
Tradução de um xpath técnico para uma LOCALIZAÇÃO legível por humanos.

Motivação: dizer "o campo vBC está vazio" é inútil numa nota com 40 itens.
O usuário precisa saber *onde* — "Item 3 da nota, grupo ICMS00". Este módulo
extrai essa informação do xpath que o lxml devolve em cada erro de XSD e
também é usado pelas regras de negócio, para que erro de schema e erro de
regra falem a mesma língua.
"""

import re
from dataclasses import dataclass
from typing import Optional

# Seções de primeiro nível do layout da NF-e/NFC-e e como chamá-las para o
# usuário final (quem lê o relatório é o pessoal fiscal, não o dev).
SECOES = {
    "ide": "Identificação da nota",
    "emit": "Emitente",
    "dest": "Destinatário",
    "retirada": "Local de retirada",
    "entrega": "Local de entrega",
    "det": "Item da nota",
    "prod": "Produto do item",
    "imposto": "Impostos do item",
    "total": "Totais da nota",
    "ICMSTot": "Totais da nota (ICMSTot)",
    "transp": "Transporte",
    "vol": "Volumes do transporte",
    "cobr": "Cobrança / faturamento",
    "dup": "Duplicatas da cobrança",
    "pag": "Formas de pagamento",
    "detPag": "Detalhe do pagamento",
    "infAdic": "Informações adicionais",
    "infRespTec": "Responsável técnico",
    "autXML": "Autorizados a baixar o XML",
    "exporta": "Exportação",
    "compra": "Informações de compra",
    "infIntermed": "Intermediador da operação",
}

# Grupos tributários, do mais interno/específico para o mais genérico. Usado
# para desambiguar tags homônimas (vBC existe em ICMS, IPI, PIS, COFINS...).
GRUPOS_TRIBUTARIOS = (
    "ICMSUFDest", "ICMSST", "ICMSSN", "ICMS", "IPI", "II",
    "PIS", "PISST", "COFINS", "COFINSST", "ISSQN", "retTrib",
)

# Tags que COMEÇAM com o nome de um grupo tributário mas não pertencem a ele
# (são totalizadores da nota, não o imposto de um item).
NAO_TRIBUTARIOS = {"ICMSTot", "ISSQNtot", "ISSQNTot", "IPIDevol"}

_INDICE = re.compile(r"\[(\d+)\]")


@dataclass
class Localizacao:
    """Onde, em linguagem de gente, o problema está."""
    xpath: Optional[str] = None
    linha: Optional[int] = None
    secao: Optional[str] = None            # nome amigável da seção (ex. "Item da nota")
    item: Optional[int] = None             # nº do item (det[3] -> 3)
    grupo: Optional[str] = None            # tag pai imediata (ex. "ICMS00")
    grupo_tributario: Optional[str] = None # grupo tributário mais próximo (ex. "ICMS")
    _tag_secao: Optional[str] = None        # tag que originou `secao`, para não repetir

    def descrever(self) -> str:
        """Frase curta de localização, pronta para entrar na mensagem de erro."""
        partes: list[str] = []
        if self.item is not None:
            partes.append(f"Item {self.item} da nota")
        elif self.secao:
            partes.append(self.secao)

        if self.grupo and self.grupo != self._tag_secao:
            partes.append(f"grupo <{self.grupo}>")
        if self.linha:
            partes.append(f"linha {self.linha} do XML")

        return " > ".join(partes) if partes else "Local não identificado no XML"

    def como_dict(self) -> dict:
        return {
            "xpath": self.xpath,
            "linha": self.linha,
            "secao": self.secao,
            "item": self.item,
            "grupo": self.grupo,
            "grupoTributario": self.grupo_tributario,
            "descricao": self.descrever(),
        }


def _segmentos(xpath: str) -> list[str]:
    """Quebra o xpath em nomes de tag, sem namespace e sem índice."""
    brutos = [p for p in xpath.strip("/").split("/") if p]
    limpos = []
    for p in brutos:
        nome = p.split("[")[0]
        nome = nome.split(":")[-1]            # prefixo de namespace (nfe:det)
        nome = nome.split("}")[-1]            # namespace expandido ({...}det)
        if nome:
            limpos.append(nome)
    return limpos


def _indice_do_item(xpath: str) -> Optional[int]:
    """Extrai o número do item a partir de det[N] (ou de qualquer índice logo
    depois de 'det', que é como o lxml numera os itens repetidos)."""
    for trecho in xpath.strip("/").split("/"):
        if trecho.split("[")[0].split(":")[-1].split("}")[-1] == "det":
            achou = _INDICE.search(trecho)
            return int(achou.group(1)) if achou else 1
    return None


def localizar(xpath: Optional[str], linha: Optional[int] = None,
              tag_do_erro: Optional[str] = None) -> Localizacao:
    """Constrói a Localizacao a partir do xpath cru do lxml.

    tag_do_erro: quando informado, é descartado do fim do xpath antes de
    calcular o "grupo pai" — assim um erro em .../ICMS00/vBC reporta grupo
    ICMS00, e não vBC."""
    loc = Localizacao(xpath=xpath, linha=linha)
    if not xpath:
        return loc

    segmentos = _segmentos(xpath)
    if not segmentos:
        return loc

    if tag_do_erro and segmentos and segmentos[-1] == tag_do_erro:
        segmentos = segmentos[:-1]

    loc.item = _indice_do_item(xpath)
    loc.grupo = segmentos[-1] if segmentos else None

    # Grupo tributário: varre de dentro para fora, para que um erro dentro de
    # <IPI> não seja atribuído a <ICMS> só porque ICMS aparece antes na lista.
    for nome in reversed(segmentos):
        if nome in NAO_TRIBUTARIOS:
            continue
        if nome in GRUPOS_TRIBUTARIOS:
            loc.grupo_tributario = nome
            break
        # ICMS00, ICMS10, ICMSSN102, PISAliq, COFINSOutr... herdam o grupo.
        for grupo in GRUPOS_TRIBUTARIOS:
            if nome.startswith(grupo) and nome != grupo:
                loc.grupo_tributario = grupo
                break
        if loc.grupo_tributario:
            break

    # Seção: a mais específica reconhecida, varrendo de dentro para fora.
    for nome in reversed(segmentos):
        if nome in SECOES:
            loc.secao = SECOES[nome]
            loc._tag_secao = nome
            break

    return loc


def caminho_legivel(elemento) -> Optional[str]:
    """Caminho do elemento com nomes de tag sem namespace, e indice apenas
    onde ha repeticao (ex.: /NFe/infNFe/det[2]/prod/NCM).

    Existe porque nem ElementTree.getpath() nem o `path` dos erros do libxml2
    servem: num XML com namespace default os dois devolvem '/*/*/*[1]', que
    nao diz nada ao usuario e impede este modulo de reconhecer 'det' ou 'ICMS'.
    """
    partes: list[str] = []
    atual = elemento
    while atual is not None:
        nome = atual.tag
        if not isinstance(nome, str):  # comentario / instrucao de processamento
            break
        nome = nome.split("}")[-1]
        pai = atual.getparent()
        if pai is not None:
            irmaos = [f for f in pai if f.tag == atual.tag]
            if len(irmaos) > 1:
                nome = f"{nome}[{irmaos.index(atual) + 1}]"
        partes.append(nome)
        atual = pai
    return "/" + "/".join(reversed(partes)) if partes else None


def localizar_elemento(elemento, tag_do_erro: Optional[str] = None) -> Localizacao:
    """Atalho: monta a Localizacao direto de um elemento lxml."""
    return localizar(caminho_legivel(elemento), elemento.sourceline, tag_do_erro)
