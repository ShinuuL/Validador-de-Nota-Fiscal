"""
Interface de linha de comando.

Uso:
    python -m nfe_validator caminho/para/nota.xml           # relatório legível
    python -m nfe_validator nota.xml --json                 # JSON (integração)
    python -m nfe_validator nota.xml --so-nao-preenchidos   # só o que falta preencher
    cat nota.xml | python -m nfe_validator -

Código de saída: 0 se a nota está válida, 1 se há erros, 2 em erro de uso.
"""

import csv
import json
import sys

from .nucleo.validador import validar

AJUDA = (
    "Uso: python -m nfe_validator <arquivo.xml | pasta | -> [opções]\n"
    "\n"
    "  --json                 imprime o resultado estruturado (para integração)\n"
    "  --so-nao-preenchidos   lista apenas os campos obrigatórios não preenchidos\n"
    "  --csv                  exporta uma linha por erro (RF09), pronto para Excel\n"
    "  --sem-xsd              não aplica a validação de schema (só regras de negócio)\n"
    "  --lote                 trata o caminho como pasta/log do ERP e revalida tudo\n"
    "                         (aceita os despejos de XML em out/monitor-nfe-*.out.txt\n"
    "                          e arquivos .xml soltos, inclusive envelopes nfeProc)\n"
    "\n"
    "Valida NF-e e NFC-e (nota nua, enviNFe, nfeProc) e tambem os documentos de\n"
    "servico: eventos (cancelamento, CC-e, manifestacao), consulta de situacao,\n"
    "inutilizacao de numeracao, consulta cadastro e retornos de lote. A familia e\n"
    "reconhecida pela raiz do XML - nao ha opcao para escolher.\n"
)

OPCOES_VALIDAS = {"--json", "--csv", "--so-nao-preenchidos", "--sem-xsd", "--lote"}

SITUACAO_LEGIVEL = {
    "obrigatorio_ausente": "NÃO INFORMADO",
    "vazio": "EM BRANCO",
    "so_espacos": "SÓ ESPAÇOS",
    "grupo_incompleto": "GRUPO INCOMPLETO",
}


def _quebrar(texto: str, largura: int = 96, recuo: str = "     ") -> str:
    """Quebra o texto em linhas, sem depender de textwrap para preservar a
    pontuação das frases longas do catálogo."""
    linhas: list[str] = []
    atual = ""
    for palavra in (texto or "").split():
        if len(atual) + len(palavra) + 1 > largura:
            linhas.append(atual)
            atual = palavra
        else:
            atual = f"{atual} {palavra}".strip()
    if atual:
        linhas.append(atual)
    return f"\n{recuo}".join(linhas)


def _imprimir_cabecalho(resultado: dict) -> None:
    resumo = resultado["resumo"]
    print("=" * 100)
    print(f"  Documento : {resultado['tipoDocumento'] or '(não identificado)'}"
          f"  |  Layout: {resultado['versaoLayout'] or '-'}")
    print(f"  Chave     : {resultado['chaveAcesso'] or '(ausente)'}")
    print(f"  Situação  : {'VÁLIDA' if resultado['valido'] else 'REJEITADA'}"
          f"  |  {resumo['totalErros']} erro(s), {resumo['totalAvisos']} aviso(s)")
    if resumo.get("xsdAplicado") is False:
        print("  Atenção   : validação de schema (XSD) NÃO aplicada - relatório incompleto")
    if resumo["totalCamposNaoPreenchidos"]:
        print(f"  Campos não preenchidos: {resumo['totalCamposNaoPreenchidos']}")
    if resumo.get("porLocal"):
        distribuicao = ", ".join(f"{k}: {v}" for k, v in sorted(resumo["porLocal"].items()))
        print(f"  Distribuição: {distribuicao}")
    print("=" * 100)


def _imprimir_nao_preenchidos(resultado: dict) -> None:
    campos = resultado["resumo"]["camposNaoPreenchidos"]
    if not campos:
        print("Nenhum campo obrigatório não preenchido foi encontrado.")
        return
    print(f"\nCAMPOS NÃO PREENCHIDOS ({len(campos)})\n")
    for i, campo in enumerate(campos, start=1):
        situacao = SITUACAO_LEGIVEL.get(campo["situacao"], campo["situacao"])
        print(f"{i:>3}. [{situacao}] {campo['campo']}")
        print(f"     Onde: {campo['onde'] or campo['xpath'] or '-'}")
        print(f"     Corrigir: {_quebrar(campo['comoCorrigir'] or '-')}")
        print()


def _imprimir_erros(resultado: dict) -> None:
    if not resultado["erros"]:
        print("\nNenhum erro encontrado.")
    else:
        print(f"\nERROS ({len(resultado['erros'])})\n")
    for i, erro in enumerate(resultado["erros"], start=1):
        print(f"{i:>3}. [{erro['codigo']}] {erro['campo'] or '(documento)'}")
        detalhe = erro.get("detalhe") or {}
        if detalhe.get("onde"):
            print(f"     Onde: {detalhe['onde']}")
        elif erro.get("xpath"):
            print(f"     Onde: {erro['xpath']}"
                  + (f" (linha {erro['linha']})" if erro.get("linha") else ""))
        # Quando temos as partes separadas, imprimimos em blocos: repetir o
        # "onde" dentro do texto corrido (como faz motivo_rejeicao) polui a
        # leitura, já que ele acabou de ser impresso na linha acima.
        if detalhe.get("oQueAconteceu"):
            print(f"     Problema: {_quebrar(detalhe['oQueAconteceu'])}")
            print(f"     Por quê:  {_quebrar(detalhe['porQueRejeita'])}")
            print(f"     Corrigir: {_quebrar(detalhe['comoCorrigir'])}")
        else:
            print(f"     {_quebrar(erro['motivo_rejeicao'])}")
        if erro.get("mensagem_tecnica"):
            print(f"     [técnico] {_quebrar(str(erro['mensagem_tecnica']), recuo='                ')}")
        print()

    for aviso in resultado["avisos"]:
        print(f"AVISO [{aviso['codigo']}]")
        print(f"     {_quebrar(aviso['motivo_rejeicao'])}\n")


# RF09: colunas do CSV. A ordem é a de leitura de quem vai corrigir a nota —
# onde está o problema, qual campo, o que fazer — e não a ordem interna do dict.
COLUNAS_CSV = (
    "arquivo", "item", "codigo", "campo", "tagXml", "situacao",
    "onde", "xpath", "linha", "origem", "subOrigem", "severidade",
    "mensagem", "comoCorrigir", "mensagemTecnica",
)


def _linhas_csv(resultado: dict, arquivo: str = "") -> list[dict]:
    """Achata um resultado de validação em uma linha por erro/aviso."""
    from .nucleo.localizacao import localizar

    linhas: list[dict] = []
    for item in resultado["erros"] + resultado["avisos"]:
        detalhe = item.get("detalhe") or {}
        numero = localizar(item.get("xpath") or "").item
        linhas.append({
            "arquivo": arquivo,
            "item": numero if numero is not None else "",
            "codigo": item.get("codigo") or "",
            "campo": item.get("campo") or "",
            "tagXml": detalhe.get("tagXml") or "",
            "situacao": detalhe.get("tipoViolacao") or "",
            "onde": detalhe.get("onde") or "",
            "xpath": item.get("xpath") or "",
            "linha": item.get("linha") if item.get("linha") is not None else "",
            "origem": item.get("origem") or "",
            "subOrigem": item.get("subOrigem") or "",
            "severidade": item.get("severidade") or "",
            "mensagem": item.get("mensagem") or item.get("motivo_rejeicao") or "",
            "comoCorrigir": detalhe.get("comoCorrigir") or "",
            "mensagemTecnica": item.get("mensagem_tecnica") or "",
        })
    return linhas


def _escrever_csv(linhas: list[dict]) -> None:
    """Escreve o CSV no stdout.

    Usa `;` como separador e BOM UTF-8 porque o destino real é o Excel em
    português: com `,` ele joga tudo numa coluna só, e sem BOM os acentos
    aparecem quebrados.

    Reconfigura por cima do UTF-8 que `main()` já pôs: aqui o que muda é o BOM
    (`utf-8-sig`) e o `newline=""`, que o `csv` exige para não duplicar o 
."""
    sys.stdout.reconfigure(encoding="utf-8-sig", newline="")
    escritor = csv.DictWriter(
        sys.stdout, fieldnames=list(COLUNAS_CSV),
        delimiter=";", quoting=csv.QUOTE_MINIMAL, lineterminator="\n",
    )
    escritor.writeheader()
    escritor.writerows(linhas)


def _rodar_lote(origem: str, como_json: bool, aplicar_xsd: bool,
                como_csv: bool = False) -> None:
    """Revalida em lote os XMLs que o ERP deixou no disco (RF08).

    A pasta do ERP é lida e nada mais: o coletor não escreve nela."""
    from .ferramentas.coletor_erp import resumir, revalidar

    resultados = revalidar(origem, aplicar_xsd=aplicar_xsd)
    resumo = resumir(resultados)

    if como_csv:
        linhas = []
        for item in resultados:
            if "resultado" in item:
                linhas.extend(_linhas_csv(item["resultado"], item["rotulo"]))
        _escrever_csv(linhas)
        sys.exit(0 if resumo["invalidos"] == 0 else 1)

    if como_json:
        print(json.dumps({"resumo": resumo, "itens": resultados},
                         indent=2, ensure_ascii=False))
        sys.exit(0 if resumo["invalidos"] == 0 else 1)

    print("=" * 100)
    print(f"  Origem   : {origem}")
    print(f"  XMLs     : {resumo['totalXmls']}"
          f"  |  válidos: {resumo['validos']}"
          f"  |  com erro: {resumo['invalidos']}"
          f"  |  fora de escopo: {resumo['foraDeEscopo']}"
          f"  |  ilegíveis: {resumo['ilegiveis']}")
    print("=" * 100)

    if resumo.get("foraDeEscopoPorTipo"):
        print("\nFORA DE ESCOPO (não são NF-e/NFC-e, não foram validados)\n")
        for tipo, quantas in resumo["foraDeEscopoPorTipo"].items():
            print(f"  {quantas:5}  {tipo}")

    if resumo["porCodigo"]:
        print("\nERROS POR CÓDIGO\n")
        for codigo, quantas in resumo["porCodigo"].items():
            print(f"  {quantas:5}  {codigo}")

    if resumo["camposMaisProblematicos"]:
        print("\nCAMPOS QUE MAIS APARECEM\n")
        for campo, quantas in resumo["camposMaisProblematicos"].items():
            print(f"  {quantas:5}  {campo}")

    com_erro = [i for i in resultados
                if "resultado" in i and not i["resultado"]["valido"]]
    if com_erro:
        print(f"\nDETALHE DOS {len(com_erro)} XML(s) COM ERRO\n")
        for item in com_erro:
            resultado = item["resultado"]
            print(f"--- {item['rotulo']} "
                  f"({resultado['resumo']['totalErros']} erro(s)) ---")
            for erro in resultado["erros"][:6]:
                detalhe = erro.get("detalhe") or {}
                onde = detalhe.get("onde") or erro.get("xpath") or "-"
                print(f"   [{erro['codigo']}] {erro['campo'] or '(documento)'}  |  {onde}")
            restantes = resultado["resumo"]["totalErros"] - 6
            if restantes > 0:
                print(f"   ... e mais {restantes} erro(s)")
            print()

    for item in resultados:
        if "erroLeitura" in item:
            print(f"ILEGÍVEL {item['rotulo']}: {item['erroLeitura']}")

    sys.exit(0 if resumo["invalidos"] == 0 else 1)


def _forcar_utf8_na_saida() -> None:
    """Garante UTF-8 no stdout/stderr antes de qualquer `print`.

    No Windows, quando a saída é redirecionada (pipe, `> arquivo`), o Python
    usa a codificação do locale - cp1252 aqui. Todo o relatório é em português:
    o texto sai com acento quebrado e, num caractere fora do cp1252, o comando
    ainda quebra com UnicodeEncodeError no meio da impressão. O caminho do CSV
    já reconfigurava por conta própria (ele precisa do BOM); os outros modos -
    relatório humano, `--json`, `--help` - não reconfiguravam nada.

    `errors="replace"` é a rede de segurança: um caractere impossível vira `?`
    em vez de derrubar o comando com o relatório pela metade."""
    for fluxo in (sys.stdout, sys.stderr):
        try:
            fluxo.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError, OSError):
            # stdout trocado por algo que não é TextIOWrapper (teste, captura
            # de saída, embedding). Não é motivo para o comando falhar.
            pass


def main() -> None:
    _forcar_utf8_na_saida()
    argumentos = sys.argv[1:]

    # `--help` pedido de propósito vai para o stdout e sai com 0; falta de
    # argumento é erro de uso, vai para o stderr e sai com 2. Misturar os dois
    # faz `--help` parecer falha em script e em CI.
    if "--help" in argumentos or "-h" in argumentos:
        print(AJUDA)
        sys.exit(0)
    if not argumentos:
        print(AJUDA, file=sys.stderr)
        sys.exit(2)

    opcoes = {a for a in argumentos if a.startswith("--")}
    posicionais = [a for a in argumentos if not a.startswith("--")]
    desconhecidas = opcoes - OPCOES_VALIDAS
    if len(posicionais) != 1 or desconhecidas:
        if desconhecidas:
            print(f"Opção desconhecida: {', '.join(sorted(desconhecidas))}\n", file=sys.stderr)
        print(AJUDA, file=sys.stderr)
        sys.exit(2)

    origem = posicionais[0]

    if "--lote" in opcoes:
        _rodar_lote(origem, "--json" in opcoes, "--sem-xsd" not in opcoes,
                    "--csv" in opcoes)
        return

    if origem == "-":
        conteudo = sys.stdin.read()
    else:
        try:
            with open(origem, "r", encoding="utf-8") as f:
                conteudo = f.read()
        except OSError as exc:
            print(f"Não foi possível ler '{origem}': {exc}", file=sys.stderr)
            sys.exit(2)

    resultado = validar(conteudo, aplicar_xsd="--sem-xsd" not in opcoes)

    if "--csv" in opcoes:
        _escrever_csv(_linhas_csv(resultado, origem if origem != "-" else "<stdin>"))
    elif "--json" in opcoes:
        print(json.dumps(resultado, indent=2, ensure_ascii=False))
    else:
        _imprimir_cabecalho(resultado)
        if "--so-nao-preenchidos" in opcoes:
            _imprimir_nao_preenchidos(resultado)
        else:
            _imprimir_erros(resultado)

    sys.exit(0 if resultado["valido"] else 1)


if __name__ == "__main__":
    main()
