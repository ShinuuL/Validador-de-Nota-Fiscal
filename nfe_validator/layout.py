"""
Modelo de leiaute derivado dos XSDs oficiais (RN05).

Por que este módulo existe
--------------------------
O `catalogo_erros.py` tem ~22 campos descritos à mão. O leiaute da NF-e tem
898. Ou seja: a esmagadora maioria dos campos recebia a mensagem genérica
"'X' é exigido pelo layout da NF-e/NFC-e neste ponto do XML", que não diz
nada sobre o campo.

Ao mesmo tempo, o XSD oficial que já está em `schemas/` carrega:
  * 1.036 blocos `xs:documentation` cobrindo ~95% dos campos, em português;
  * qual campo é obrigatório (ausência de `minOccurs`);
  * as 21 variantes do `xs:choice` do ICMS, cada uma declarando exatamente
    quais campos aquele CST exige;
  * o mapa CST/CSOSN -> variante, via `xs:enumeration` inline;
  * os grupos "tudo ou nada" (`xs:sequence minOccurs="0"` com filhos exigidos);
  * as alternativas XOR internas (IPITrib: vBC+pIPI *ou* qUnid+vUnid).

Este módulo lê tudo isso. É a diferença entre *derivar* a regra do arquivo
oficial e *reescrevê-la de memória* — que é justamente o que a RN05 proíbe:

    "O agente não pode inventar, resumir ou recriar de memória as regras de
     um XSD — os arquivos .xsd reais devem ser obtidos e usados como estão."

Consequências de design que seguem daí
--------------------------------------
1. Toda informação carrega `Origem(arquivo, linha)`. Se o relatório afirma
   algo "oficial", dá para abrir o .xsd naquela linha e conferir.
2. Todo texto é **cópia literal** do `xs:documentation`. Os typos da SEFAZ
   ("Tributção", "Não tributda") e os marcadores "(v2.0)" ficam como estão:
   corrigir seria reescrever a regra, o que a RN07 também proíbe.
3. Este módulo **não valida nada**. Ele descreve; `schema.py` valida. Duas
   fontes de veredito sobre a mesma regra é como se cria divergência.
4. Nada aqui levanta exceção para o chamador. É camada de enriquecimento: se
   o XSD não estiver instalado, as consultas devolvem None/vazio e o
   validador segue com o aviso XSD-INDISPONIVEL que já existia.
"""

import re
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from lxml import etree

# `schema` é importado sob demanda dentro de `carregar_modelo`, e não aqui no
# topo, para não fechar o ciclo:
#     catalogo_erros -> layout -> schema -> catalogo_erros
# O `catalogo_erros` precisa deste módulo para descrever campos, e o `schema`
# precisa do `catalogo_erros` para montar a mensagem. Só o carregamento do
# modelo depende de `schema`, então o import tardio resolve sem duplicar
# `caminho_schema`.

XS = "{http://www.w3.org/2001/XMLSchema}"

# Compositores: atravessamos sem sair do grupo atual.
COMPOSITORES = (f"{XS}sequence", f"{XS}choice", f"{XS}all", f"{XS}group")

# Linhas de legenda de enumeração dentro da documentação, no formato que a
# SEFAZ usa: "0 - Margem Valor Agregado (%);" / "1 - Pauta (valor);"
_LEGENDA = re.compile(r"^\s*([\w.]{1,6})\s*[-–=]\s*(.+?)\s*[;.]?\s*$")

# Acima deste tamanho, a documentação tem conteúdo real e serve como
# justificativa fiscal. Abaixo, é só um rótulo ("Bairro", "Cfop") — ótimo
# como nome do campo, inútil como explicação de por que a SEFAZ rejeita.
LIMITE_TEXTO_SUBSTANTIVO = 60

# Acima deste tamanho o texto não serve como nome amigável (o NCM tem 400
# caracteres de documentação; virar "nome do campo" ficaria ilegível).
LIMITE_NOME_AMIGAVEL = 60


@dataclass(frozen=True)
class Origem:
    """De onde no XSD a afirmação veio. Exigência da RN05: toda informação do
    modelo tem que ser rastreável até um nó de um arquivo oficial."""
    arquivo: str
    linha: Optional[int] = None

    def como_dict(self) -> dict:
        return {"arquivo": self.arquivo, "linha": self.linha}


@dataclass(frozen=True)
class Descricao:
    """Texto oficial do `xs:documentation`, copiado sem reescrita (RN07).

    `texto` é a versão de uma linha, para caber numa mensagem de erro.
    `texto_integral` preserva as quebras, porque as legendas de enumeração
    vêm multilinha e perdem sentido achatadas.
    """
    texto: str
    texto_integral: str
    linhas_de_legenda: tuple[str, ...] = ()
    tipo_xsd: Optional[str] = None
    herdada_do_tipo: bool = False
    origem: Optional[Origem] = None

    @property
    def substantiva(self) -> bool:
        """Tem conteúdo suficiente para explicar o campo, não só nomeá-lo."""
        return len(self.texto) > LIMITE_TEXTO_SUBSTANTIVO

    @property
    def serve_como_nome(self) -> bool:
        return 0 < len(self.texto) <= LIMITE_NOME_AMIGAVEL


@dataclass(frozen=True)
class ValorEnumerado:
    valor: str
    rotulo: Optional[str] = None

    def __str__(self) -> str:
        return f"{self.valor}={self.rotulo}" if self.rotulo else self.valor


@dataclass(frozen=True)
class CampoLeiaute:
    nome: str
    obrigatorio: bool
    repetivel: bool = False
    tipo_xsd: Optional[str] = None
    descricao: Optional[Descricao] = None
    enumeracao: tuple[ValorEnumerado, ...] = ()
    aceita_vazio: bool = False
    origem: Optional[Origem] = None


@dataclass(frozen=True)
class GrupoTodoOuNada:
    """`<xs:sequence minOccurs="0">` cujos filhos não têm minOccurs: o grupo
    inteiro é opcional, mas se UM campo aparecer todos os outros passam a ser
    exigidos. Ex.: ICMS00 -> (pFCP, vFCP); ICMS20 -> (vBCFCP, pFCP, vFCP)."""
    campos: tuple[str, ...]
    opcionais_internos: tuple[str, ...] = ()
    origem: Optional[Origem] = None


@dataclass(frozen=True)
class Alternativa:
    """Ramo de um `xs:choice` INTERNO a um grupo — não a escolha de variante.
    Ex.: IPITrib -> [(vBC, pIPI), (qUnid, vUnid)]."""
    campos: tuple[str, ...]
    origem: Optional[Origem] = None


@dataclass(frozen=True)
class Variante:
    """Um filho do `xs:choice` de um grupo tributário (ICMS00, PISAliq, ...).

    É aqui que mora a obrigatoriedade condicional: `obrigatorios` são os
    campos que aquele CST/CSOSN exige, lidos do complexType da variante."""
    nome: str
    grupo: str
    codigos: tuple[str, ...] = ()
    campo_do_codigo: Optional[str] = None
    obrigatorios: tuple[str, ...] = ()
    opcionais: tuple[str, ...] = ()
    todos_ou_nada: tuple[GrupoTodoOuNada, ...] = ()
    alternativas: tuple[Alternativa, ...] = ()
    descricao: Optional[Descricao] = None
    origem: Optional[Origem] = None


@dataclass(frozen=True)
class Grupo:
    """Qualquer elemento com complexType do leiaute (ide, prod, ICMS, ICMS00,
    ICMSTot...). Grupo e Variante coexistem: ICMS00 é variante de ICMS e
    também um grupo consultável por `campos_obrigatorios_de`."""
    nome: str
    campos: tuple[CampoLeiaute, ...] = ()
    variantes: tuple[str, ...] = ()
    todos_ou_nada: tuple[GrupoTodoOuNada, ...] = ()
    alternativas: tuple[Alternativa, ...] = ()
    descricao: Optional[Descricao] = None
    origem: Optional[Origem] = None

    @property
    def obrigatorios(self) -> tuple[str, ...]:
        return tuple(c.nome for c in self.campos if c.obrigatorio)

    @property
    def opcionais(self) -> tuple[str, ...]:
        return tuple(c.nome for c in self.campos if not c.obrigatorio)


@dataclass
class ModeloLeiaute:
    """Índice consultável do leiaute. Construído uma vez e cacheado."""
    tipo_documento: str
    versao: str
    arquivo_raiz: str
    leiaute_emprestado_de: Optional[str] = None
    grupos: dict[str, Grupo] = field(default_factory=dict)
    grupos_ambiguos: dict[str, int] = field(default_factory=dict)
    campos_por_contexto: dict[tuple[str, str], CampoLeiaute] = field(default_factory=dict)
    campos_por_tag: dict[str, tuple[CampoLeiaute, ...]] = field(default_factory=dict)
    variantes: dict[str, Variante] = field(default_factory=dict)
    variantes_por_grupo: dict[str, tuple[str, ...]] = field(default_factory=dict)
    codigo_para_variante: dict[tuple[str, str], str] = field(default_factory=dict)
    codigos_ambiguos: set[tuple[str, str]] = field(default_factory=set)
    grupo_pai_da_variante: dict[str, str] = field(default_factory=dict)

    # -- consultas -----------------------------------------------------
    def descricao_do_campo(self, tag: str, contexto: Optional[str] = None) -> Optional[Descricao]:
        """Descrição oficial de um campo, do contexto mais específico ao menos.

        Sem contexto e com o mesmo nome de tag aparecendo em grupos diferentes
        com textos divergentes, devolve None de propósito: entregar a
        documentação do grupo errado com selo de "oficial" é o pior modo de
        falha possível (`vBC` existe em ICMS, IPI, PIS, COFINS e ICMSTot)."""
        if contexto:
            campo = self.campos_por_contexto.get((contexto, tag))
            if campo is not None and campo.descricao is not None:
                return campo.descricao
            # Variante sem descrição própria: sobe para o grupo pai (ICMS00 -> ICMS).
            pai = self.grupo_pai_da_variante.get(contexto)
            if pai:
                campo = self.campos_por_contexto.get((pai, tag))
                if campo is not None and campo.descricao is not None:
                    return campo.descricao

        ocorrencias = self.campos_por_tag.get(tag) or ()
        descricoes = [c.descricao for c in ocorrencias if c.descricao is not None]
        if not descricoes:
            return None
        if len(descricoes) == 1:
            return descricoes[0]
        textos = {d.texto for d in descricoes}
        return descricoes[0] if len(textos) == 1 else None

    def enumeracao_de(self, tag: str, contexto: Optional[str] = None) -> tuple[ValorEnumerado, ...]:
        if contexto:
            campo = self.campos_por_contexto.get((contexto, tag))
            if campo is not None and campo.enumeracao:
                return campo.enumeracao
        ocorrencias = self.campos_por_tag.get(tag) or ()
        conjuntos = {c.enumeracao for c in ocorrencias if c.enumeracao}
        return next(iter(conjuntos)) if len(conjuntos) == 1 else ()

    def campos_obrigatorios_de(self, nome_do_grupo: str) -> tuple[str, ...]:
        grupo = self.grupos.get(nome_do_grupo)
        return grupo.obrigatorios if grupo else ()

    def variante_para_cst(self, grupo: str, codigo: str) -> Optional[Variante]:
        """A variante que aquele CST/CSOSN seleciona, ou None se o código não
        identifica uma variante só.

        Ambiguidade é real e comum: o CST 20 é enumerado tanto em ICMS20
        quanto em ICMSPart, e o mesmo vale para 10, 41, 60 e 90. Devolver None
        em vez de escolher é deliberado — inventar desempate seria exatamente
        a regra "de memória" que a RN05 proíbe. Quem precisa saber quais são
        os candidatos usa `variantes_para_cst`."""
        candidatos = self.variantes_para_cst(grupo, codigo)
        return candidatos[0] if len(candidatos) == 1 else None

    def variantes_para_cst(self, grupo: str, codigo: str) -> tuple[Variante, ...]:
        """TODAS as variantes do grupo que aceitam esse CST/CSOSN.

        É o que uma mensagem de erro precisa: "o CST 20 pertence ao grupo
        ICMS20 ou ICMSPart" é útil; "não sei" não é."""
        nomes = [
            nome for nome in self.variantes_por_grupo.get(grupo, ())
            if codigo in (self.variantes[nome].codigos if nome in self.variantes else ())
        ]
        return tuple(self.variantes[n] for n in nomes)


# ---------------------------------------------------------------------------
# Limpeza de texto — o ÚNICO ponto de transformação, deliberadamente mínimo.
# ---------------------------------------------------------------------------
def limpar_documentacao(bruto: Optional[str]) -> tuple[str, str, tuple[str, ...]]:
    """Normaliza whitespace do `xs:documentation` e extrai as legendas.

    Devolve (texto_uma_linha, texto_integral, linhas_de_legenda).

    NÃO corrige typos da SEFAZ nem remove marcadores de versão: o texto é a
    regra oficial, e "melhorar" a redação seria reescrevê-la (RN07)."""
    if not bruto:
        return "", "", ()

    linhas = [linha.replace("\t", " ").strip() for linha in bruto.replace("\r\n", "\n").split("\n")]
    linhas = [re.sub(r" {2,}", " ", linha) for linha in linhas]
    uteis = [linha for linha in linhas if linha]

    texto_integral = "\n".join(uteis)
    texto = re.sub(r" {2,}", " ", " ".join(uteis)).strip()
    legendas = tuple(linha for linha in uteis if _LEGENDA.match(linha))
    return texto, texto_integral, legendas


def _rotulos_das_legendas(legendas: tuple[str, ...]) -> dict[str, str]:
    """Converte ("0 - Margem Valor Agregado (%);", ...) em {"0": "Margem..."}."""
    mapa: dict[str, str] = {}
    for linha in legendas:
        achou = _LEGENDA.match(linha)
        if achou:
            mapa.setdefault(achou.group(1), achou.group(2))
    return mapa


# ---------------------------------------------------------------------------
# Leitura dos arquivos
# ---------------------------------------------------------------------------
def _carregar_documentos(entrada: Path) -> list[tuple[str, etree._ElementTree]]:
    """Lê o XSD de entrada e resolve `xs:include` recursivamente.

    `xs:import` é ignorado de propósito: o único import nos XSDs da SEFAZ é o
    xmldsig, e `ds:Signature` não é campo de leiaute."""
    documentos: list[tuple[str, etree._ElementTree]] = []
    visitados: set[Path] = set()
    pendentes = [entrada]

    while pendentes:
        caminho = pendentes.pop(0)
        resolvido = caminho.resolve()
        if resolvido in visitados or not caminho.exists():
            continue
        visitados.add(resolvido)

        arvore = etree.parse(str(caminho))
        documentos.append((caminho.name, arvore))

        for inc in arvore.getroot().findall(f"{XS}include"):
            local = inc.get("schemaLocation")
            if local:
                pendentes.append(caminho.parent / local)

    return documentos


def _documentacao(no, arquivo: str, tipo_xsd: Optional[str] = None,
                  herdada: bool = False) -> Optional[Descricao]:
    anotacao = no.find(f"{XS}annotation")
    if anotacao is None:
        return None
    doc = anotacao.find(f"{XS}documentation")
    if doc is None:
        return None
    texto, integral, legendas = limpar_documentacao(doc.text)
    if not texto:
        return None
    return Descricao(
        texto=texto,
        texto_integral=integral,
        linhas_de_legenda=legendas,
        tipo_xsd=tipo_xsd,
        herdada_do_tipo=herdada,
        origem=Origem(arquivo, no.sourceline),
    )


def _sem_ns(nome: Optional[str]) -> Optional[str]:
    if not nome:
        return None
    return nome.split("}")[-1].split(":")[-1]


def _traduzir_pattern_xsd(bruto: str) -> str:
    """Converte um `xs:pattern` para regex do Python, no que importa aqui.

    O pattern do XSD é implicitamente ancorado (casa a string inteira), então
    usamos `re.fullmatch`. As diferenças de sintaxe que sobram (`\\i`, `\\c`,
    blocos Unicode) não aparecem nos XSDs da NF-e; se aparecerem, a compilação
    falha e quem chama trata como "não sei"."""
    return bruto.replace("\\i", "[A-Za-z_:]").replace("\\c", "[A-Za-z0-9_:.-]")


def _aceita_string_vazia(no_simpletype) -> bool:
    """O tipo aceita conteúdo vazio?

    Existe porque a premissa "no leiaute 4.00 nenhuma tag folha pode estar
    vazia" é FALSA, e o XSD prova: `cBenef` tem o pattern
    `([!-ÿ]{8}|[!-ÿ]{10}|SEM CBENEF)?` — o `?` final aceita a string vazia, e
    `<cBenef></cBenef>` aparece em notas autorizadas pela SEFAZ. Perguntar ao
    arquivo oficial em vez de assumir é o que a RN05 pede."""
    if no_simpletype is None:
        return False
    restricao = no_simpletype.find(f"{XS}restriction")
    if restricao is None:
        return False

    for facet in restricao.findall(f"{XS}minLength"):
        if facet.get("value") == "0":
            return True

    patterns = [p.get("value") for p in restricao.findall(f"{XS}pattern")]
    for bruto in patterns:
        if not bruto:
            continue
        try:
            if re.fullmatch(_traduzir_pattern_xsd(bruto), "") is not None:
                return True
        except re.error:
            continue
    # Uma enumeração que inclua "" também aceitaria vazio.
    for enum in restricao.findall(f"{XS}enumeration"):
        if enum.get("value") == "":
            return True
    return False


def _enumeracoes_do_simpletype(no_simpletype, rotulos: dict[str, str]) -> tuple[ValorEnumerado, ...]:
    if no_simpletype is None:
        return ()
    restricao = no_simpletype.find(f"{XS}restriction")
    if restricao is None:
        return ()
    valores = []
    for enum in restricao.findall(f"{XS}enumeration"):
        valor = enum.get("value")
        if valor is None:
            continue
        valores.append(ValorEnumerado(valor, rotulos.get(valor)))
    return tuple(valores)


def _modelo_de_conteudo(no_complextype):
    """Devolve o compositor raiz do complexType (sequence/choice/all),
    atravessando complexContent/extension quando houver."""
    if no_complextype is None:
        return None
    for nome in ("sequence", "choice", "all"):
        achado = no_complextype.find(f"{XS}{nome}")
        if achado is not None:
            return achado
    conteudo = no_complextype.find(f"{XS}complexContent")
    if conteudo is not None:
        for envelope in ("extension", "restriction"):
            no = conteudo.find(f"{XS}{envelope}")
            if no is None:
                continue
            for nome in ("sequence", "choice", "all"):
                achado = no.find(f"{XS}{nome}")
                if achado is not None:
                    return achado
    return None


def _e_choice_de_variantes(no_choice) -> bool:
    """Distingue as duas coisas muito diferentes que um `xs:choice` pode ser.

    VARIANTES  -> todos os filhos são `xs:element` com complexType próprio.
                  É o caso de ICMS (21 variantes), PIS, COFINS e TIpi: cada
                  ramo é um grupo inteiro, selecionado pelo CST.
    ALTERNATIVA -> qualquer outra forma. É o caso de emit (CNPJ | CPF, filhos
                  com simpleType) e de IPITrib (ramos que são `xs:sequence`).

    Este é o ponto mais frágil do parser, por isso vive isolado numa função só
    e é coberto por teste com os 5 casos reais do leiaute."""
    filhos = [f for f in no_choice if isinstance(f.tag, str) and f.tag != f"{XS}annotation"]
    if not filhos:
        return False
    for filho in filhos:
        if filho.tag != f"{XS}element":
            return False
        if filho.find(f"{XS}complexType") is None:
            return False
    return True


def _nomes_de_elementos(no) -> tuple[str, ...]:
    """Nomes dos xs:element abaixo de `no`, sem descer em complexType filho."""
    nomes: list[str] = []

    def anda(atual):
        for filho in atual:
            if not isinstance(filho.tag, str):
                continue
            if filho.tag == f"{XS}element":
                nome = filho.get("name") or _sem_ns(filho.get("ref"))
                if nome:
                    nomes.append(nome)
            elif filho.tag in COMPOSITORES:
                anda(filho)

    anda(no)
    return tuple(nomes)


def _e_opcional(no_elemento) -> bool:
    return no_elemento.get("minOccurs") == "0"


def _e_repetivel(no_elemento) -> bool:
    maximo = no_elemento.get("maxOccurs")
    if not maximo:
        return False
    if maximo == "unbounded":
        return True
    try:
        return int(maximo) > 1
    except ValueError:
        return False


def _resolver_simples(nome_tipo: Optional[str], tipos_simples: dict,
                      saltos: int = 5) -> tuple[Optional[Descricao], tuple[ValorEnumerado, ...]]:
    """Resolve um simpleType nomeado: documentação e enumeração.

    Segue `xs:restriction base=` um nível por vez (limite de saltos) porque
    alguns tipos da SEFAZ restringem outros tipos nomeados, e a enumeração
    pode estar no ancestral."""
    atual = nome_tipo
    while atual and saltos > 0:
        entrada = tipos_simples.get(atual)
        if entrada is None:
            return None, ()
        no, arquivo = entrada
        descricao = _documentacao(no, arquivo, tipo_xsd=atual, herdada=True)
        rotulos = _rotulos_das_legendas(descricao.linhas_de_legenda) if descricao else {}
        enumeracoes = _enumeracoes_do_simpletype(no, rotulos)
        if enumeracoes or descricao:
            return descricao, enumeracoes
        restricao = no.find(f"{XS}restriction")
        atual = _sem_ns(restricao.get("base")) if restricao is not None else None
        saltos -= 1
    return None, ()


def _construir_campo(no_elemento, arquivo: str, obrigatorio: bool,
                     tipos_simples: dict) -> Optional[CampoLeiaute]:
    nome = no_elemento.get("name") or _sem_ns(no_elemento.get("ref"))
    if not nome:
        return None

    tipo = _sem_ns(no_elemento.get("type"))
    descricao = _documentacao(no_elemento, arquivo, tipo_xsd=tipo)

    # Enumeração declarada inline no próprio elemento (o padrão da SEFAZ para
    # CST/CSOSN: cada variante restringe o código aos seus próprios valores).
    inline = no_elemento.find(f"{XS}simpleType")
    rotulos = _rotulos_das_legendas(descricao.linhas_de_legenda) if descricao else {}
    enumeracoes = _enumeracoes_do_simpletype(inline, rotulos)

    aceita_vazio = _aceita_string_vazia(inline)
    if not aceita_vazio and tipo and tipo in tipos_simples:
        aceita_vazio = _aceita_string_vazia(tipos_simples[tipo][0])

    # Sem doc/enumeração própria, herda do tipo nomeado (ex.: orig -> Torig,
    # que declara os valores 0 a 8).
    if tipo and (descricao is None or not enumeracoes):
        doc_do_tipo, enum_do_tipo = _resolver_simples(tipo, tipos_simples)
        if descricao is None:
            descricao = doc_do_tipo
        if not enumeracoes and enum_do_tipo:
            # Os valores vêm do tipo, mas a legenda do PRÓPRIO elemento é mais
            # específica e ganha. É o caso do `orig`: o Torig só lista 0..8 sem
            # texto, enquanto a documentação do elemento nomeia cada origem.
            # (A cobertura pode ser parcial — a documentação da SEFAZ para
            # `orig` para no valor 2 — e ficar parcial mesmo é o correto: só
            # rotulamos o que o arquivo oficial rotula.)
            enumeracoes = tuple(
                ValorEnumerado(v.valor, v.rotulo or rotulos.get(v.valor))
                for v in enum_do_tipo
            )

    return CampoLeiaute(
        nome=nome,
        obrigatorio=obrigatorio,
        repetivel=_e_repetivel(no_elemento),
        tipo_xsd=tipo,
        descricao=descricao,
        enumeracao=enumeracoes,
        aceita_vazio=aceita_vazio,
        origem=Origem(arquivo, no_elemento.sourceline),
    )


def _analisar_conteudo(no_complextype, arquivo: str, tipos_simples: dict):
    """Percorre o modelo de conteúdo de UM grupo e devolve
    (campos, variantes, todos_ou_nada, alternativas).

    Regra de travessia: atravessamos compositores sem sair do grupo, paramos
    em qualquer `xs:element`, e NUNCA descemos no complexType de um filho -
    isso iniciaria um grupo novo."""
    campos: list[CampoLeiaute] = []
    variantes: list[str] = []
    todos_ou_nada: list[GrupoTodoOuNada] = []
    alternativas: list[Alternativa] = []

    raiz = _modelo_de_conteudo(no_complextype)
    if raiz is None:
        return (), (), (), ()

    def tratar_choice(no_choice, opcional_herdado: bool):
        """Um `xs:choice` é uma de duas coisas bem diferentes — ver
        `_e_choice_de_variantes`. Isso tem que valer tanto quando o choice é a
        RAIZ do complexType (ICMS, PIS, COFINS, TIpi) quanto quando está
        aninhado (IPITrib)."""
        if _e_choice_de_variantes(no_choice):
            # Cada ramo é um grupo inteiro selecionado pelo CST. Não descemos:
            # os campos pertencem à variante, não a este grupo.
            variantes.extend(
                f.get("name") for f in no_choice
                if f.tag == f"{XS}element" and f.get("name")
            )
            return
        # Alternativa (XOR): registramos os ramos e seguimos, mas nada dentro
        # de um choice pode ser exigido incondicionalmente.
        for ramo in no_choice:
            if not isinstance(ramo.tag, str) or ramo.tag == f"{XS}annotation":
                continue
            nomes = ((ramo.get("name"),) if ramo.tag == f"{XS}element"
                     else _nomes_de_elementos(ramo))
            nomes = tuple(n for n in nomes if n)
            if nomes:
                alternativas.append(
                    Alternativa(nomes, Origem(arquivo, ramo.sourceline))
                )
        anda(no_choice, opcional_herdado=True)

    def anda(no, opcional_herdado: bool):
        for filho in no:
            if not isinstance(filho.tag, str):
                continue

            if filho.tag == f"{XS}element":
                campo = _construir_campo(
                    filho, arquivo,
                    obrigatorio=not opcional_herdado and not _e_opcional(filho),
                    tipos_simples=tipos_simples,
                )
                if campo is not None:
                    campos.append(campo)

            elif filho.tag == f"{XS}choice":
                tratar_choice(filho, opcional_herdado)

            elif filho.tag in COMPOSITORES:
                sequencia_opcional = filho.get("minOccurs") == "0"
                if sequencia_opcional:
                    diretos = [f for f in filho if f.tag == f"{XS}element" and f.get("name")]
                    exigidos = tuple(f.get("name") for f in diretos if not _e_opcional(f))
                    internos = tuple(f.get("name") for f in diretos if _e_opcional(f))
                    if len(exigidos) > 1:
                        # Um único campo exigido não é "tudo ou nada": é só um
                        # campo opcional. O par (pFCP, vFCP) é que importa.
                        todos_ou_nada.append(
                            GrupoTodoOuNada(exigidos, internos, Origem(arquivo, filho.sourceline))
                        )
                anda(filho, opcional_herdado=opcional_herdado or sequencia_opcional)

    # A raiz pode ser ela mesma um choice de variantes — é assim que o ICMS
    # declara suas 21 variantes, e era por isso que elas passavam batido.
    if raiz.tag == f"{XS}choice":
        tratar_choice(raiz, opcional_herdado=False)
    else:
        anda(raiz, opcional_herdado=False)

    return tuple(campos), tuple(variantes), tuple(todos_ou_nada), tuple(alternativas)


# Campos que carregam o código de seleção da variante tributária.
CAMPOS_DE_CODIGO = ("CST", "CSOSN")


def _construir_modelo(tipo_documento: str, versao: str, entrada: Path,
                      emprestado_de: Optional[str]) -> ModeloLeiaute:
    documentos = _carregar_documentos(entrada)

    # Passo 1: tipos globais nomeados.
    tipos_simples: dict[str, tuple] = {}
    tipos_complexos: dict[str, tuple] = {}
    for arquivo, arvore in documentos:
        raiz = arvore.getroot()
        for no in raiz.findall(f"{XS}simpleType"):
            nome = no.get("name")
            if nome and nome not in tipos_simples:
                tipos_simples[nome] = (no, arquivo)
        for no in raiz.findall(f"{XS}complexType"):
            nome = no.get("name")
            if nome and nome not in tipos_complexos:
                tipos_complexos[nome] = (no, arquivo)

    modelo = ModeloLeiaute(
        tipo_documento=tipo_documento,
        versao=versao,
        arquivo_raiz=entrada.name,
        leiaute_emprestado_de=emprestado_de,
    )

    ocorrencias_de_tag: dict[str, list[CampoLeiaute]] = {}

    def registrar_grupo(nome: str, no_complextype, arquivo: str,
                        descricao: Optional[Descricao], linha: Optional[int]):
        campos, variantes, todos, alts = _analisar_conteudo(
            no_complextype, arquivo, tipos_simples
        )
        grupo = Grupo(
            nome=nome, campos=campos, variantes=variantes,
            todos_ou_nada=todos, alternativas=alts,
            descricao=descricao, origem=Origem(arquivo, linha),
        )
        if nome in modelo.grupos:
            modelo.grupos_ambiguos[nome] = modelo.grupos_ambiguos.get(nome, 1) + 1
        else:
            modelo.grupos[nome] = grupo

        for campo in campos:
            modelo.campos_por_contexto.setdefault((nome, campo.nome), campo)
            ocorrencias_de_tag.setdefault(campo.nome, []).append(campo)

        if variantes:
            modelo.variantes_por_grupo[nome] = variantes
            for filho in variantes:
                modelo.grupo_pai_da_variante[filho] = nome
        return grupo

    # Passo 2: cada elemento com complexType (inline ou nomeado) e um grupo.
    for arquivo, arvore in documentos:
        for no in arvore.iter(f"{XS}element"):
            nome = no.get("name")
            if not nome:
                continue
            inline = no.find(f"{XS}complexType")
            if inline is not None:
                registrar_grupo(nome, inline, arquivo,
                                _documentacao(no, arquivo), no.sourceline)
                continue
            # Elemento tipado por um complexType nomeado (ex.: IPI -> TIpi): o
            # grupo existe com o nome do ELEMENTO, mas a estrutura vem do tipo.
            tipo = _sem_ns(no.get("type"))
            if tipo and tipo in tipos_complexos:
                no_tipo, arquivo_tipo = tipos_complexos[tipo]
                descricao = (_documentacao(no, arquivo)
                             or _documentacao(no_tipo, arquivo_tipo, tipo_xsd=tipo, herdada=True))
                registrar_grupo(nome, no_tipo, arquivo_tipo, descricao, no.sourceline)

    # complexTypes nomeados tambem viram grupo consultavel pelo nome do tipo.
    for nome_tipo, (no_tipo, arquivo_tipo) in tipos_complexos.items():
        if nome_tipo not in modelo.grupos:
            registrar_grupo(nome_tipo, no_tipo, arquivo_tipo,
                            _documentacao(no_tipo, arquivo_tipo), no_tipo.sourceline)

    modelo.campos_por_tag = {tag: tuple(lista) for tag, lista in ocorrencias_de_tag.items()}

    # Passo 3: variantes tributarias e o indice CST/CSOSN -> variante.
    for grupo_pai, nomes in modelo.variantes_por_grupo.items():
        for nome in nomes:
            if nome in modelo.variantes:
                # A mesma variante pode ser alcançada pelo ELEMENTO (IPI) e
                # pelo TIPO que o define (TIpi). Fica com o primeiro, que é o
                # elemento — é o nome que aparece no XML e a chave que o
                # catálogo usa ("IPI.vBC"). Sobrescrever aqui faria o grupo
                # virar "TIpi" e o catálogo deixaria de casar.
                continue
            grupo = modelo.grupos.get(nome)
            if grupo is None:
                continue
            campo_codigo = next(
                (c for c in grupo.campos if c.nome in CAMPOS_DE_CODIGO), None
            )
            codigos = tuple(v.valor for v in campo_codigo.enumeracao) if campo_codigo else ()
            modelo.variantes[nome] = Variante(
                nome=nome, grupo=grupo_pai,
                codigos=codigos,
                campo_do_codigo=campo_codigo.nome if campo_codigo else None,
                obrigatorios=grupo.obrigatorios,
                opcionais=grupo.opcionais,
                todos_ou_nada=grupo.todos_ou_nada,
                alternativas=grupo.alternativas,
                descricao=grupo.descricao,
                origem=grupo.origem,
            )
            for codigo in codigos:
                chave = (grupo_pai, codigo)
                if chave in modelo.codigo_para_variante:
                    # Dois ramos aceitando o mesmo CST: nao inventamos desempate.
                    modelo.codigos_ambiguos.add(chave)
                else:
                    modelo.codigo_para_variante[chave] = nome

    return modelo


# ---------------------------------------------------------------------------
# Cache e API publica
# ---------------------------------------------------------------------------
_MODELOS: dict[tuple[str, str, bool], Optional[ModeloLeiaute]] = {}
_TRAVA = threading.Lock()


def carregar_modelo(tipo_documento: str = "NFe", versao: str = "4.00",
                    permitir_leiaute_equivalente: bool = False) -> Optional[ModeloLeiaute]:
    """Carrega (e cacheia) o modelo de leiaute. Devolve None se nao der.

    NUNCA levanta: este modulo e camada de enriquecimento, nao pode ser uma
    nova causa de falha na validacao.

    `permitir_leiaute_equivalente` deixa a NFC-e usar o leiaute da NF-e da
    MESMA versao, porque a SEFAZ nao publica um leiaute separado para mod 65.
    Vale so para TEXTO EXPLICATIVO: `schema.carregar_schema` continua exigindo
    o XSD proprio e continua levantando SchemaIndisponivel (RN05/RN15)."""
    chave = (tipo_documento, versao, permitir_leiaute_equivalente)
    if chave in _MODELOS:
        return _MODELOS[chave]

    with _TRAVA:
        if chave in _MODELOS:
            return _MODELOS[chave]

        from .schema import SchemaIndisponivel, caminho_schema  # ver nota no topo

        modelo: Optional[ModeloLeiaute] = None
        try:
            entrada = caminho_schema(tipo_documento, versao)
            emprestado_de = None

            if (not entrada.exists() and permitir_leiaute_equivalente
                    and tipo_documento != "NFe"):
                # So empresta se a pasta propria nao tem NENHUM xsd: se a SEFAZ
                # publicar um leiaute de NFC-e divergente, o emprestimo desliga
                # sozinho em vez de explicar campos com o documento errado.
                propria = entrada.parent
                if not propria.exists() or not any(propria.glob("*.xsd")):
                    alternativa = caminho_schema("NFe", versao)   # mesma versao (RN15)
                    if alternativa.exists():
                        entrada, emprestado_de = alternativa, "NFe"

            if entrada.exists():
                modelo = _construir_modelo(tipo_documento, versao, entrada, emprestado_de)
        except (SchemaIndisponivel, OSError, etree.LxmlError):
            modelo = None

        # Falha e cacheada: sem isso, uma nota com 40 erros tentaria 40 cargas.
        _MODELOS[chave] = modelo
        return modelo


def limpar_cache() -> None:
    """So para testes: descarta os modelos ja construidos."""
    with _TRAVA:
        _MODELOS.clear()


def disponivel(tipo_documento: str = "NFe", versao: str = "4.00",
               permitir_leiaute_equivalente: bool = False) -> bool:
    return carregar_modelo(tipo_documento, versao, permitir_leiaute_equivalente) is not None


def descricao_do_campo(tag: str, contexto: Optional[str] = None, *,
                       tipo_documento: str = "NFe", versao: str = "4.00",
                       permitir_leiaute_equivalente: bool = False) -> Optional[Descricao]:
    modelo = carregar_modelo(tipo_documento, versao, permitir_leiaute_equivalente)
    return modelo.descricao_do_campo(tag, contexto) if modelo else None


def enumeracao_de(tag: str, contexto: Optional[str] = None, *,
                  tipo_documento: str = "NFe", versao: str = "4.00",
                  permitir_leiaute_equivalente: bool = False) -> tuple[ValorEnumerado, ...]:
    modelo = carregar_modelo(tipo_documento, versao, permitir_leiaute_equivalente)
    return modelo.enumeracao_de(tag, contexto) if modelo else ()


def legenda_de_valores(tag: str, contexto: Optional[str] = None, limite: int = 10, *,
                       tipo_documento: str = "NFe", versao: str = "4.00") -> str:
    """Lista os valores aceitos com o rotulo oficial, pronta para entrar no
    campo `esperado` de um erro de enumeracao."""
    valores = enumeracao_de(tag, contexto, tipo_documento=tipo_documento, versao=versao)
    if not valores:
        return ""
    mostrados = [str(v) for v in valores[:limite]]
    if len(valores) > limite:
        mostrados.append(f"... (+{len(valores) - limite} valores)")
    return "; ".join(mostrados)


def campos_obrigatorios_de(nome_do_grupo: str, *, tipo_documento: str = "NFe",
                           versao: str = "4.00") -> tuple[str, ...]:
    modelo = carregar_modelo(tipo_documento, versao)
    return modelo.campos_obrigatorios_de(nome_do_grupo) if modelo else ()


def campos_de(nome_do_grupo: str, *, tipo_documento: str = "NFe",
              versao: str = "4.00") -> tuple[CampoLeiaute, ...]:
    modelo = carregar_modelo(tipo_documento, versao)
    grupo = modelo.grupos.get(nome_do_grupo) if modelo else None
    return grupo.campos if grupo else ()


def variantes_de(grupo: str, *, tipo_documento: str = "NFe",
                 versao: str = "4.00") -> tuple[Variante, ...]:
    modelo = carregar_modelo(tipo_documento, versao)
    if not modelo:
        return ()
    nomes = modelo.variantes_por_grupo.get(grupo, ())
    return tuple(modelo.variantes[n] for n in nomes if n in modelo.variantes)


def variante_para_cst(grupo: str, cst: str, *, tipo_documento: str = "NFe",
                      versao: str = "4.00") -> Optional[Variante]:
    modelo = carregar_modelo(tipo_documento, versao)
    return modelo.variante_para_cst(grupo, cst) if modelo else None


def variantes_para_cst(grupo: str, cst: str, *, tipo_documento: str = "NFe",
                       versao: str = "4.00") -> tuple[Variante, ...]:
    modelo = carregar_modelo(tipo_documento, versao)
    return modelo.variantes_para_cst(grupo, cst) if modelo else ()


def variante_do_elemento(nome: str, *, tipo_documento: str = "NFe",
                         versao: str = "4.00") -> Optional[Variante]:
    """A variante correspondente a um elemento presente no XML (ICMS00, PISAliq).

    É este o caminho que a validação deve usar: ler qual variante o XML
    realmente abriu e conferir os campos DELA. Ir pelo CST não funciona, porque
    5 dos CSTs do ICMS pertencem a mais de uma variante."""
    modelo = carregar_modelo(tipo_documento, versao)
    return modelo.variantes.get(nome) if modelo else None


def grupos_todos_ou_nada(variante: str, *, tipo_documento: str = "NFe",
                         versao: str = "4.00") -> tuple[GrupoTodoOuNada, ...]:
    modelo = carregar_modelo(tipo_documento, versao)
    if not modelo:
        return ()
    achada = modelo.variantes.get(variante)
    if achada is not None:
        return achada.todos_ou_nada
    grupo = modelo.grupos.get(variante)
    return grupo.todos_ou_nada if grupo else ()


def alternativas_de(nome: str, *, tipo_documento: str = "NFe",
                    versao: str = "4.00") -> tuple[Alternativa, ...]:
    modelo = carregar_modelo(tipo_documento, versao)
    if not modelo:
        return ()
    grupo = modelo.grupos.get(nome)
    return grupo.alternativas if grupo else ()


def aceita_vazio(tag: str, contexto: Optional[str] = None, *,
                 tipo_documento: str = "NFe", versao: str = "4.00") -> bool:
    """O layout aceita esta tag com conteudo vazio?

    Serve para nao acusar como "nao preenchido" um campo que o XSD permite em
    branco. O caso concreto: `cBenef` tem pattern terminando em `?`, e
    `<cBenef></cBenef>` aparece em notas AUTORIZADAS pela SEFAZ.

    Na duvida (campo desconhecido, XSD ausente) devolve False, mantendo o
    comportamento anterior."""
    modelo = carregar_modelo(tipo_documento, versao)
    if modelo is None:
        return False
    if contexto:
        campo = modelo.campos_por_contexto.get((contexto, tag))
        if campo is not None:
            return campo.aceita_vazio
    ocorrencias = modelo.campos_por_tag.get(tag) or ()
    # So afirma que aceita vazio se TODAS as ocorrencias aceitarem: e a
    # resposta conservadora quando nao sabemos o contexto.
    return bool(ocorrencias) and all(c.aceita_vazio for c in ocorrencias)


def e_grupo(tag: str, *, tipo_documento: str = "NFe", versao: str = "4.00") -> bool:
    """Esta tag e um GRUPO (complexType) e nao um campo simples?

    `<infAdic></infAdic>` e um grupo vazio, nao um campo em branco - tratar os
    dois igual gera erro sem sentido."""
    modelo = carregar_modelo(tipo_documento, versao)
    return bool(modelo and tag in modelo.grupos)
