"""
Documentos de serviço da NF-e: eventos e consultas (RN01/RN02/RN14).

Nem todo XML que o ERP guarda é uma nota. Depois da autorização vem o
cancelamento, a carta de correção, a manifestação do destinatário, a
inutilização de faixa de numeração, as consultas de situação e de cadastro, o
retorno do recibo do lote. Tudo isso é XML no layout nacional, tudo isso a
SEFAZ rejeita por erro estrutural, e nada disso tem `<infNFe>`.

Antes deste módulo, um XML de cancelamento chegava ao `validar()` e morria em
`parser.identificar_documento()` com "Não foi encontrado o elemento <infNFe>.
Verifique se o arquivo é realmente uma NF-e/NFC-e no layout nacional" — uma
mensagem que culpa o arquivo por não ser algo que ele nunca se propôs a ser.

Por que um registro e não `if` espalhado
----------------------------------------
As quinze raízes se distinguem por três coisas, e só três: a pasta de schema, o
arquivo de entrada e o nome que o relatório mostra. Nada de lógica por família.
Um registro declarativo mantém isso conferível de bater o olho e faz a próxima
raiz ser uma linha, não um `elif`.

Onde a versão é lida
--------------------
No atributo `versao` da própria raiz — e isso vale para as quinze, conferido nos
XSDs: todas declaram `<xs:attribute name="versao" use="required">` no tipo da
raiz. É mais simples que na nota, onde a versão mora em `<infNFe versao=...>`
(RN02). A RN14 continua valendo: a versão lida escolhe a pasta, e uma versão
não instalada falha explicitamente em vez de validar contra a errada (RN15).
"""

from typing import NamedTuple, Optional

from lxml import etree


class Servico(NamedTuple):
    """Uma raiz de documento de serviço e onde encontrar o XSD dela.

    `tipo` é a PASTA do schema, em minúsculas (RN14:
    `schemas/v{versao}/{tipo}/`). `rotulo` é o que o relatório mostra em
    "Documento:". Os dois são separados porque nem sempre coincidem: o
    `retConsReciNFe` tem o XSD em `nfe/`, e usar a pasta como rótulo fazia o
    cabeçalho anunciar "Documento: NFe" num arquivo que não é nota nenhuma.

    `entrada` é o XSD que declara a raiz global — `{versao}` é substituído pela
    versão lida do XML, nunca fixado no código, senão a RN14 quebraria na
    próxima versão de layout.

    `substantivo` é como as mensagens de erro chamam o documento no meio de uma
    frase. Existe porque o texto genérico dizia "A SEFAZ rejeita a nota" mesmo
    num cancelamento. Vem com o artigo colado ("o evento", "a consulta") para a
    frase sair com o gênero certo sem precisar de concordância no código.
    """
    tipo: str
    rotulo: str
    entrada: str
    descricao: str
    substantivo: str


# Raiz do documento -> família. As chaves são o nome da tag raiz SEM namespace,
# porque é o que `_tag_sem_namespace` entrega e porque XML sem xmlns aparece na
# prática (ERP que monta o arquivo à mão).
#
# Fora deste mapa de propósito: `enviNFe` e `nfeProc`. Essas duas CONTÊM uma
# nota, então seguem o caminho normal - `identificar_documento` acha o
# <infNFe> lá dentro e as regras de negócio da nota se aplicam. Quem resolve o
# XSD delas é `ENTRADA_POR_RAIZ`, em schema.py.
#
# Já `retEnviNFe` e `retConsReciNFe` estão aqui embaixo mesmo tendo o XSD na
# pasta da nota: apesar do nome, não trazem nota nenhuma - o primeiro traz um
# <infRec> e o segundo uma lista de <protNFe>, nenhum dos dois tem <infNFe>.
SERVICOS: dict[str, Servico] = {
    # Eventos (v1.00). Um "evento" é qualquer coisa que se diz sobre uma nota
    # depois de ela existir: cancelamento, carta de correção (CC-e),
    # manifestação do destinatário, EPEC. O leiaute é o mesmo para todos - o
    # que muda é o `tpEvento` e o conteúdo de `detEvento`.
    "envEvento": Servico(
        "Evento", "Evento", "envEvento_v{versao}.xsd",
        "lote de eventos que o ERP transmite à SEFAZ",
        "o lote de eventos",
    ),
    "retEnvEvento": Servico(
        "Evento", "Evento", "retEnvEvento_v{versao}.xsd",
        "retorno da SEFAZ para um lote de eventos",
        "o retorno do evento",
    ),
    "procEventoNFe": Servico(
        "Evento", "Evento", "procEventoNFe_v{versao}.xsd",
        "evento já registrado (evento + retorno), que é o arquivo a guardar",
        "o evento",
    ),

    # Consulta da situação de uma nota (v4.00).
    "consSitNFe": Servico(
        "ConsSitNFe", "ConsultaSituacao", "consSitNFe_v{versao}.xsd",
        "pedido de consulta da situação de uma nota",
        "a consulta",
    ),
    "retConsSitNFe": Servico(
        "ConsSitNFe", "ConsultaSituacao", "retConsSitNFe_v{versao}.xsd",
        "resposta da consulta de situação, com a nota e seus eventos",
        "a resposta da consulta",
    ),

    # Inutilização de faixa de numeração (v4.00). Só a forma "processada"
    # existe como raiz global no pacote oficial - não há XSD de entrada para
    # um `inutNFe` solto.
    "ProcInutNFe": Servico(
        "InutNFe", "Inutilizacao", "procInutNFe_v{versao}.xsd",
        "inutilização de faixa de numeração já homologada pela SEFAZ",
        "a inutilização",
    ),

    # Consulta cadastro de contribuinte (v2.00). Versão de layout própria, e
    # por isso pasta própria - a RN14 é por versão, não por documento.
    "ConsCad": Servico(
        "ConsCad", "ConsultaCadastro", "consCad_v{versao}.xsd",
        "pedido de consulta ao cadastro de contribuinte",
        "a consulta",
    ),
    "retConsCad": Servico(
        "ConsCad", "ConsultaCadastro", "retConsCad_v{versao}.xsd",
        "resposta da consulta ao cadastro de contribuinte",
        "a resposta da consulta",
    ),

    # Retornos do lote (v4.00). O `tipo` aqui é "NFe" porque o XSD destes dois
    # inclui o `leiauteNFe` completo e por isso mora na pasta da nota - não
    # porque eles sejam uma nota. A pasta `nfce/` tem cópia byte-a-byte dos
    # mesmos arquivos, e nada no documento diz se o lote era de modelo 55 ou
    # 65, então apontar para `nfe/` não é escolha arbitrária: é o único palpite
    # possível, e é inofensivo porque os dois schemas são idênticos.
    "retEnviNFe": Servico(
        "NFe", "RetornoLote", "retEnviNFe_v{versao}.xsd",
        "retorno do envio do lote, com o recibo ou os protocolos",
        "o retorno do lote",
    ),
    "retConsReciNFe": Servico(
        "NFe", "RetornoRecibo", "retConsReciNFe_v{versao}.xsd",
        "retorno da consulta do recibo do lote, com os protocolos das notas",
        "o retorno do lote",
    ),

    # Distribuição de DF-e (v1.01). É por aqui que o ERP recebe as notas em que
    # a empresa é DESTINATÁRIA, e é o que mais enche a pasta do ERP: o retorno
    # vem com resumos (`resNFe`, `resEvento`) em vez do documento inteiro.
    # Pacote próprio (PL_NFeDistDFe_104), versão de layout própria.
    "distDFeInt": Servico(
        "DistDFe", "DistribuicaoDFe", "distDFeInt_v{versao}.xsd",
        "pedido de distribuição de DF-e de interesse da empresa",
        "o pedido de distribuição",
    ),
    "retDistDFeInt": Servico(
        "DistDFe", "DistribuicaoDFe", "retDistDFeInt_v{versao}.xsd",
        "retorno da distribuição, com o lote de documentos e resumos",
        "o retorno da distribuição",
    ),
    "resNFe": Servico(
        "DistDFe", "ResumoNFe", "resNFe_v{versao}.xsd",
        "resumo de uma nota em que a empresa é destinatária",
        "o resumo",
    ),
    "resEvento": Servico(
        "DistDFe", "ResumoEvento", "resEvento_v{versao}.xsd",
        "resumo de um evento registrado em nota de terceiro",
        "o resumo do evento",
    ),
}


def tag_sem_namespace(nome) -> str:
    """`{http://...}envEvento` -> `envEvento`. Também aceita tag não-string.

    Um comentário ou instrução de processamento como raiz devolve uma função
    em `.tag`, não uma string - daí o `str()` antes de cortar.
    """
    nome = str(nome)
    return nome.split("}")[-1] if "}" in nome else nome


def identificar(arvore: etree._ElementTree) -> Optional[tuple[Servico, str, str]]:
    """Se a raiz é um documento de serviço, devolve (servico, raiz, versao).

    Devolve `None` para qualquer outra coisa - inclusive para a nota e seus
    envelopes -, e é isso que deixa `validar()` seguir pelo caminho normal.

    A `versao` sai do atributo `versao` da raiz. Quando ele falta, devolvemos
    string vazia em vez de chutar a versão da família: chutar levaria a validar
    contra um layout que o arquivo não declarou, que é o que a RN15 proíbe.
    Quem chama transforma isso em erro explicando o que faltou.
    """
    raiz = arvore.getroot()
    if raiz is None:
        return None
    nome = tag_sem_namespace(raiz.tag)
    servico = SERVICOS.get(nome)
    if servico is None:
        return None
    return servico, nome, (raiz.get("versao") or "").strip()
