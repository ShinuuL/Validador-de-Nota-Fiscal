"""
Coletor de XMLs produzidos pelo ERP (server-weld), para revalidação.

O que o ERP faz hoje
--------------------
Antes de transmitir, o ERP monta o XML via JAXB, ajusta os namespaces e valida
contra o XSD com `javax.xml.validation` (SAX). Quando a validação falha, ele
despeja o XML inteiro no stderr, entre marcadores:

    ================ ERRO NFE ====================
    <enviNFe ...>...</enviNFe>
    ==============================================

E o stderr do monitor é redirecionado para `out/monitor-nfe-<maquina>-<data>.out.txt`
(ver `ServidorDocumentoEletronicoMonitor.installOut()`), com expurgo de
arquivos com mais de 5 dias.

Ou seja: a pasta `out/` acumula o XML completo, pré-transmissão, de cada nota
que a SEFAZ teria rejeitado — exatamente o material que este validador precisa.

Por que revalidar aqui vale a pena
----------------------------------
A validação do ERP usa SAX e **lança exceção no primeiro erro**. O operador vê
um campo, corrige, reenvia, e descobre o próximo. Este validador roda o XSD
inteiro mais as regras RN08..RN19 e devolve a lista completa de uma vez.

Além disso, `NfeServico.getXSDTagInf()` busca a descrição do campo num arquivo
`.dd` (Properties) ao lado do `.xsd` — e **não existe nenhum arquivo `.dd` no
projeto**. Então a linha "Descrição:" da mensagem do ERP nunca é preenchida na
prática, e o operador recebe apenas a mensagem crua do Xerces
(`cvc-datatype-valid.1.2.1: ...`). É esse buraco que o `catalogo_erros` +
`layout` preenchem.

Este módulo é somente leitura sobre a pasta do ERP: coleta, não altera nada.
"""

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, Optional

# Os marcadores que o ERP imprime em NfeServico.validate(). Casados de forma
# tolerante porque a quantidade de "=" já variou entre versões.
MARCADOR_INICIO = re.compile(r"^={4,}\s*ERRO\s+NFE\s*={4,}\s*$")
MARCADOR_FIM = re.compile(r"^={10,}\s*$")

# Encodings tentados em ordem: o monitor grava com o charset default da JVM no
# Windows (cp1252), mas instalações mais novas gravam UTF-8.
ENCODINGS = ("utf-8", "cp1252", "latin-1")

EXTENSOES_DE_LOG = (".out.txt", ".log", ".txt")
EXTENSOES_DE_XML = (".xml",)


@dataclass
class XmlColetado:
    """Um XML encontrado, com a procedência para o relatório."""
    conteudo: str
    origem: str            # caminho do arquivo de onde veio
    linha: Optional[int] = None   # linha do log onde o bloco começa
    rotulo: str = ""       # identificação curta para o relatório

    def __post_init__(self):
        if not self.rotulo:
            nome = Path(self.origem).name
            self.rotulo = f"{nome}:{self.linha}" if self.linha else nome


def _ler_texto(caminho: Path) -> Optional[str]:
    """Lê o arquivo tentando os encodings prováveis; None se não der."""
    for encoding in ENCODINGS:
        try:
            return caminho.read_text(encoding=encoding)
        except (UnicodeDecodeError, LookupError):
            continue
        except OSError:
            return None
    try:
        return caminho.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def extrair_xmls_do_log(texto: str, origem: str = "<log>") -> list[XmlColetado]:
    """Extrai os blocos de XML despejados entre os marcadores de erro do ERP.

    Tolera bloco sem marcador de fechamento: nesse caso o XML termina na
    primeira linha que não parece continuação (o monitor mistura stdout e
    stderr no mesmo arquivo, então isso acontece)."""
    coletados: list[XmlColetado] = []
    linhas = texto.splitlines()
    i = 0

    while i < len(linhas):
        if not MARCADOR_INICIO.match(linhas[i].strip()):
            i += 1
            continue

        inicio = i + 1
        corpo: list[str] = []
        j = inicio
        while j < len(linhas):
            atual = linhas[j]
            if MARCADOR_FIM.match(atual.strip()):
                break
            # Sem marcador de fim, paramos quando o conteúdo deixa de parecer
            # XML — evita engolir o resto do log dentro do "XML".
            if corpo and not atual.strip().startswith("<") and "<" not in atual:
                break
            corpo.append(atual)
            j += 1

        conteudo = "\n".join(corpo).strip()
        if conteudo.startswith("<"):
            coletados.append(XmlColetado(conteudo, origem, inicio + 1))
        i = j + 1

    return coletados


def _e_log(caminho: Path) -> bool:
    nome = caminho.name.lower()
    return any(nome.endswith(ext) for ext in EXTENSOES_DE_LOG)


def _e_xml(caminho: Path) -> bool:
    return caminho.suffix.lower() in EXTENSOES_DE_XML


def coletar(origem: str | Path, recursivo: bool = True) -> Iterator[XmlColetado]:
    """Percorre um arquivo ou pasta e devolve os XMLs encontrados.

    Aceita as duas formas em que o ERP deixa XML no disco:
      * logs `out/monitor-nfe-*.out.txt`, com os blocos entre marcadores;
      * arquivos `.xml` soltos (ex.: `nfe_baixadas/`), que podem ser envelopes
        `nfeProc`/`enviNFe` — o validador já sabe desembrulhar."""
    caminho = Path(origem)

    if caminho.is_file():
        alvos = [caminho]
    elif caminho.is_dir():
        padrao = "**/*" if recursivo else "*"
        alvos = sorted(p for p in caminho.glob(padrao) if p.is_file())
    else:
        return

    for alvo in alvos:
        if _e_xml(alvo):
            texto = _ler_texto(alvo)
            if texto and texto.lstrip().startswith(("<", "﻿<")):
                yield XmlColetado(texto.lstrip("﻿"), str(alvo))
        elif _e_log(alvo):
            texto = _ler_texto(alvo)
            if texto and "ERRO NFE" in texto:
                yield from extrair_xmls_do_log(texto, str(alvo))


# Raízes de DFe que este validador NÃO cobre. A pasta do ERP guarda tudo junto,
# e chamar de "nota inválida" um arquivo que não é nota seria ruído, não achado.
#
# Esta lista era bem maior. Eventos, inutilização e retorno de consulta de
# situação saíram dela quando o roteamento por família passou a existir (ver
# `servicos`): eram pulados porque o validador não sabia validá-los, não porque
# não interessassem — um cancelamento rejeitado é exatamente o tipo de coisa que
# se quer achar numa varredura da pasta do ERP.
#
# O que sobrou tem um motivo comum: não há XSD instalado para essas raízes. Os
# resumos e o retorno do distribuiçãoDFe vêm no pacote do DistDFeInt, e o
# status do serviço no de ConsStatServ — nenhum dos dois foi baixado. Instalar
# esses pacotes e registrar as raízes em `servicos` é o que tira cada linha
# daqui; até então, dizer "fora de escopo" é mais honesto que validar contra o
# schema errado (RN15).
RAIZES_FORA_DE_ESCOPO = {
    "resNFe": "resumo de NF-e do distribuiçãoDFe",
    "resEvento": "resumo de evento do distribuiçãoDFe",
    "retDistDFeInt": "retorno do distribuiçãoDFe",
    "retConsStatServ": "retorno de status do serviço",
}


def _raiz_de(conteudo: str) -> Optional[str]:
    """Nome da tag raiz, sem parsear o documento inteiro."""
    achado = re.search(r"<\s*([A-Za-z_][\w.:-]*)", conteudo.lstrip("﻿"))
    if not achado:
        return None
    return achado.group(1).split(":")[-1]


def revalidar(origem: str | Path, recursivo: bool = True,
              aplicar_xsd: bool = True) -> list[dict]:
    """Coleta e revalida tudo, devolvendo um resultado por XML.

    Cada item tem `rotulo`, `origem` e um destes: `resultado` (a saída de
    `validar()`), `foraDeEscopo` (documento que não é NF-e/NFC-e) ou
    `erroLeitura` (nem deu para interpretar)."""
    from .validador import validar

    resultados: list[dict] = []
    for coletado in coletar(origem, recursivo):
        item = {"rotulo": coletado.rotulo, "origem": coletado.origem}
        raiz = _raiz_de(coletado.conteudo)

        if raiz in RAIZES_FORA_DE_ESCOPO:
            item["foraDeEscopo"] = f"{raiz}: {RAIZES_FORA_DE_ESCOPO[raiz]}"
            resultados.append(item)
            continue

        try:
            item["resultado"] = validar(coletado.conteudo, aplicar_xsd=aplicar_xsd)
        except Exception as exc:  # o coletor não pode morrer por um arquivo ruim
            item["erroLeitura"] = f"{type(exc).__name__}: {exc}"
        resultados.append(item)
    return resultados


def resumir(resultados: list[dict]) -> dict:
    """Agrega os resultados de um lote: é a visão que interessa em cima de
    centenas de notas."""
    from collections import Counter

    por_codigo: Counter = Counter()
    por_campo: Counter = Counter()
    fora_de_escopo: Counter = Counter()
    validos = invalidos = ilegiveis = 0

    for item in resultados:
        if "erroLeitura" in item:
            ilegiveis += 1
            continue
        if "foraDeEscopo" in item:
            fora_de_escopo[item["foraDeEscopo"]] += 1
            continue
        resultado = item["resultado"]
        if resultado["valido"]:
            validos += 1
            continue
        invalidos += 1
        for erro in resultado["erros"]:
            por_codigo[erro["codigo"]] += 1
            detalhe = erro.get("detalhe") or {}
            if detalhe.get("tagXml"):
                por_campo[detalhe["tagXml"]] += 1

    return {
        "totalXmls": len(resultados),
        "validos": validos,
        "invalidos": invalidos,
        "ilegiveis": ilegiveis,
        "foraDeEscopo": sum(fora_de_escopo.values()),
        "foraDeEscopoPorTipo": dict(fora_de_escopo.most_common()),
        "porCodigo": dict(por_codigo.most_common()),
        "camposMaisProblematicos": dict(por_campo.most_common(15)),
    }
