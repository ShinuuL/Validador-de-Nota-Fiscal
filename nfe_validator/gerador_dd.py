"""
Gerador do dicionário `.dd` que o ERP (server-weld) já sabe ler e nunca teve.

O buraco que isto preenche
--------------------------
`NfeServico.getXSDTagInf(File xsdFile, String tag)` monta o nome do dicionário
trocando a extensão do XSD (`enviNFe_v4.00.xsd` -> `enviNFe_v4.00.dd`), carrega
o arquivo como `java.util.Properties` e busca a descrição do campo pela chave.

Se o arquivo não existe, o método devolve `null` e `NfeServico.validate()` cai
no ramo `msg == null`: a mensagem mostrada ao operador perde a linha
`Descrição:` e sobra só a mensagem crua do Xerces
(`cvc-datatype-valid.1.2.1: '' is not a valid value for 'decimal'`).

Não existe nenhum `.dd` no projeto do ERP. O leitor está pronto há anos; o
dicionário nunca foi escrito. Este módulo o gera a partir do MESMO XSD que o
ERP valida, mais o catálogo de negócio deste projeto.

Formato da chave
----------------
`NfeReaderXML` empilha `reader.getLocalName()` a cada `startElement` e
`pathToString` junta com ponto. Não há índice de repetição: o item 1 e o item 40
compartilham a chave. Logo:

    enviNFe.NFe.infNFe.det.prod.cProd
    enviNFe.NFe.infNFe.det.imposto.ICMS.ICMS00.vBC

A raiz é a do documento que o ERP valida. No fluxo de envio é `enviNFe`
(`NfeServicoEnvioImpl` chama `getXsd(..., "enviNFe")`), então o arquivo tem que
se chamar `enviNFe_v4.00.dd`.

Formato do arquivo
------------------
`Properties.load(InputStream)` lê em **ISO-8859-1**. Para não depender de
encoding, todo caractere fora de ASCII sai escapado como `\\uXXXX` — que o
`Properties` interpreta em qualquer leitura. Valores ficam em uma linha só.
"""

import unicodedata
from pathlib import Path
from typing import Iterator, Optional

from . import layout
from .catalogo_erros import explicar_campo
from .layout import XS, _documentacao, _modelo_de_conteudo, _sem_ns
from .localizacao import localizar

# Profundidade máxima da árvore de caminhos. O leiaute da NF-e não tem tipo
# recursivo, mas um XSD futuro pode ter, e um estouro de pilha aqui seria um
# jeito idiota de quebrar uma ferramenta de apoio.
PROFUNDIDADE_MAXIMA = 25

# Raízes que o ERP valida, e o XSD de entrada de cada uma. O nome do `.dd`
# deriva do nome do XSD, então gerar para a raiz errada produz um arquivo que
# o ERP nunca vai abrir.
RAIZES = {
    "enviNFe": "enviNFe_v{versao}.xsd",
    "NFe": "nfe_v{versao}.xsd",
    "nfeProc": "procNFe_v{versao}.xsd",
}


def _escapar_valor(texto: str) -> str:
    """Deixa o texto no formato de valor de `java.util.Properties`."""
    saida = []
    for caractere in texto:
        if caractere == "\\":
            saida.append("\\\\")
        elif caractere in "\n\r":
            saida.append(" ")
        elif caractere == "\t":
            saida.append(" ")
        elif ord(caractere) < 128:
            saida.append(caractere)
        else:
            saida.append(f"\\u{ord(caractere):04x}")
    return " ".join("".join(saida).split())


def _descricao_para(tag: str, caminho: str, descricao_oficial) -> Optional[str]:
    """Monta o texto da descrição, preferindo o catálogo escrito à mão.

    O catálogo é mais rico fiscalmente que o `xs:documentation` (compare
    "Valor da BC do ICMS" com a entrada de `ICMS.vBC`), e é justamente isso que
    falta na tela do operador — então ele vem primeiro e completo.

    Os contextos são tentados do mais específico ao menos: o grupo imediato
    (`ICMS00`), depois o grupo tributário do caminho (`ICMS`), depois a tag
    sozinha. Sem o segundo passo, `det.imposto.ICMS.ICMS00.vBC` não casaria com
    a chave `ICMS.vBC` do catálogo e cairia no texto curto do XSD."""
    partes = caminho.split(".")
    grupo_imediato = partes[-2] if len(partes) >= 2 else None
    grupo_tributario = localizar("/".join(partes), None, tag).grupo_tributario

    explicacao = None
    for contexto in (grupo_imediato, grupo_tributario, None):
        explicacao = explicar_campo(tag, contexto)
        if explicacao is not None:
            break

    if explicacao is not None:
        partes = [explicacao.nome_amigavel.rstrip(".") + ".", explicacao.motivo]
        if explicacao.como_corrigir:
            partes.append(f"Como corrigir: {explicacao.como_corrigir}")
        return " ".join(partes)

    if descricao_oficial is not None and descricao_oficial.texto:
        return descricao_oficial.texto
    return None


def _percorrer(no_complextype, caminho: str, arquivo: str,
               tipos_complexos: dict, profundidade: int,
               tipos_no_caminho: frozenset) -> Iterator[tuple[str, str, Optional[str], object]]:
    """Anda o modelo de conteúdo gerando (caminho, tag, grupo_pai, descricao).

    Mesma regra de travessia do `layout.py`: atravessa compositores, para em
    `xs:element`, e só desce no complexType de um filho para gerar os caminhos
    DELE — que é exatamente o que o `.dd` precisa."""
    if profundidade > PROFUNDIDADE_MAXIMA:
        return
    raiz = _modelo_de_conteudo(no_complextype)
    if raiz is None:
        return

    grupo_atual = caminho.rsplit(".", 1)[-1]

    def anda(no):
        for filho in no:
            if not isinstance(filho.tag, str):
                continue

            if filho.tag == f"{XS}element":
                nome = filho.get("name")
                if not nome:
                    continue
                novo_caminho = f"{caminho}.{nome}"
                yield (novo_caminho, nome, grupo_atual,
                       _documentacao(filho, arquivo, tipo_xsd=_sem_ns(filho.get("type"))))

                inline = filho.find(f"{XS}complexType")
                if inline is not None:
                    yield from _percorrer(inline, novo_caminho, arquivo,
                                          tipos_complexos, profundidade + 1,
                                          tipos_no_caminho)
                    continue

                tipo = _sem_ns(filho.get("type"))
                if tipo and tipo in tipos_complexos and tipo not in tipos_no_caminho:
                    no_tipo, arquivo_tipo = tipos_complexos[tipo]
                    yield from _percorrer(no_tipo, novo_caminho, arquivo_tipo,
                                          tipos_complexos, profundidade + 1,
                                          tipos_no_caminho | {tipo})

            elif filho.tag in layout.COMPOSITORES:
                yield from anda(filho)

    yield from anda(raiz)


def gerar_dicionario(raiz: str = "enviNFe", tipo_documento: str = "NFe",
                     versao: str = "4.00") -> dict[str, str]:
    """Monta {caminho_pontilhado: descrição} para todos os campos alcançáveis
    a partir de `raiz`. Devolve {} se o XSD não estiver instalado."""
    from .schema import SCHEMAS_DIR

    nome_entrada = RAIZES.get(raiz, "").format(versao=versao)
    if not nome_entrada:
        return {}
    entrada = SCHEMAS_DIR / f"v{versao}" / tipo_documento.lower() / nome_entrada
    if not entrada.exists():
        return {}

    documentos = layout._carregar_documentos(entrada)

    tipos_complexos: dict[str, tuple] = {}
    for arquivo, arvore in documentos:
        for no in arvore.getroot().findall(f"{XS}complexType"):
            nome = no.get("name")
            if nome and nome not in tipos_complexos:
                tipos_complexos[nome] = (no, arquivo)

    # O elemento global da raiz.
    no_raiz = arquivo_raiz = None
    for arquivo, arvore in documentos:
        for no in arvore.getroot().findall(f"{XS}element"):
            if no.get("name") == raiz:
                no_raiz, arquivo_raiz = no, arquivo
                break
        if no_raiz is not None:
            break
    if no_raiz is None:
        return {}

    dicionario: dict[str, str] = {}

    descricao_raiz = _documentacao(no_raiz, arquivo_raiz)
    if descricao_raiz and descricao_raiz.texto:
        dicionario[raiz] = descricao_raiz.texto

    inline = no_raiz.find(f"{XS}complexType")
    if inline is not None:
        partida, arquivo_partida = inline, arquivo_raiz
    else:
        tipo = _sem_ns(no_raiz.get("type"))
        if not tipo or tipo not in tipos_complexos:
            return dicionario
        partida, arquivo_partida = tipos_complexos[tipo]

    for caminho, tag, grupo_pai, oficial in _percorrer(
        partida, raiz, arquivo_partida, tipos_complexos, 1, frozenset()
    ):
        if caminho in dicionario:
            continue
        texto = _descricao_para(tag, caminho, oficial)
        if texto:
            dicionario[caminho] = texto

    return dicionario


def _veio_do_catalogo(caminho: str, texto: str) -> bool:
    """O texto desta chave saiu do catalogo escrito a mao?

    Reconhecido pelo marcador que so o catalogo produz: a orientacao de
    correcao. Serve so para a estatistica do cabecalho."""
    return "Como corrigir:" in texto


def _sem_acento(texto: str) -> str:
    """Só para o cabeçalho de comentário, que é lido por gente e não pelo
    Properties."""
    return "".join(
        c for c in unicodedata.normalize("NFKD", texto)
        if not unicodedata.combining(c)
    )


def escrever_dd(destino: str | Path, dicionario: dict[str, str],
                raiz: str = "enviNFe", versao: str = "4.00") -> Path:
    """Escreve o arquivo no formato `java.util.Properties`."""
    caminho = Path(destino)
    catalogados = sum(
        1 for chave, texto in dicionario.items()
        if _veio_do_catalogo(chave, texto)
    )

    linhas = [
        "# Dicionario de campos para NfeServico.getXSDTagInf()",
        f"# Raiz: <{raiz}>   Layout: {versao}",
        "#",
        "# COMO O ERP USA ESTE ARQUIVO",
        "#   getXSDTagInf() troca a extensao do XSD validado por .dd, carrega",
        "#   como java.util.Properties e busca a descricao pela chave. A chave e",
        "#   o caminho pontilhado que NfeReaderXML.pathToString() monta, sem",
        "#   indice de repeticao. Basta colocar este arquivo ao lado do",
        f"#   {RAIZES.get(raiz, '?').format(versao=versao)} no diretorio do pacote de schemas.",
        "#",
        "# ENCODING",
        "#   Properties.load(InputStream) le em ISO-8859-1, entao todo caractere",
        "#   fora de ASCII esta escapado como \\uXXXX. Nao converta o arquivo.",
        "#",
        "# ORIGEM DOS TEXTOS",
        f"#   {catalogados} de {len(dicionario)} chaves usam o catalogo de negocio do",
        "#   nfe_validator (texto proprio, com o motivo da rejeicao e como",
        "#   corrigir). As demais usam o xs:documentation oficial do XSD,",
        "#   copiado literalmente.",
        "#",
        "# Gerado por nfe_validator/gerador_dd.py - nao editar a mao:",
        "# regerar mantem o arquivo em sincronia com o XSD.",
        "",
    ]

    for chave in sorted(dicionario):
        linhas.append(f"{chave}={_escapar_valor(dicionario[chave])}")

    caminho.write_text("\n".join(linhas) + "\n", encoding="ascii")
    return caminho


def main() -> None:
    import sys

    raiz = sys.argv[1] if len(sys.argv) > 1 else "enviNFe"
    versao = sys.argv[2] if len(sys.argv) > 2 else "4.00"

    if raiz not in RAIZES:
        print(f"Raiz desconhecida: {raiz}. Use uma de: {', '.join(RAIZES)}",
              file=sys.stderr)
        sys.exit(2)

    dicionario = gerar_dicionario(raiz, versao=versao)
    if not dicionario:
        print(f"Nao foi possivel gerar: XSD de entrada da raiz <{raiz}> nao "
              f"encontrado para a versao {versao}.", file=sys.stderr)
        sys.exit(1)

    nome = RAIZES[raiz].format(versao=versao).replace(".xsd", ".dd")
    destino = escrever_dd(nome, dicionario, raiz, versao)
    print(f"{destino}: {len(dicionario)} chaves")


if __name__ == "__main__":
    main()
