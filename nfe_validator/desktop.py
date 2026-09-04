"""
Ponto de entrada do executável distribuível (.exe).

Existe porque um .exe tem dois públicos e um só duplo clique:

  * o pessoal do fiscal abre o arquivo e espera uma janela onde arrastar o XML;
  * quem chama de script ou do ERP espera um CLI com código de saída.

Então o despacho é pelo que veio na linha de comando. Sem argumento nenhum,
sobe a UI e abre o navegador; com qualquer argumento, delega ao CLI de sempre.

Por que não reaproveitar `__main__.main()` direto
------------------------------------------------
Porque `python -m nfe_validator` SEM argumento é erro de uso: imprime a ajuda
no stderr e sai com 2, e isso é contrato testado (um script que esquece o
caminho do arquivo tem que falhar, não abrir navegador em servidor). No .exe a
convenção é a oposta. Manter os dois comportamentos em módulos separados evita
que um mude o outro por acidente.

Este módulo é usado SOMENTE pelo executável. Nada no pacote importa ele.
"""

import os
import sys

# Imports ABSOLUTOS, não relativos: o PyInstaller executa este arquivo como
# `__main__`, e aí `from .__main__ import ...` levanta "attempted relative
# import with no known parent package". Absoluto funciona nos dois modos - como
# ponto de entrada do .exe e como `python -m nfe_validator.desktop`.
#
# Importar aqui no topo também é o que põe os dois no bundle: o analisador do
# PyInstaller segue import, não adivinha.
from nfe_validator.__main__ import main as cli
from nfe_validator.web.servidor import servir


def _e_pedido_de_ajuda(argumentos: list[str]) -> bool:
    return any(a in ("-h", "--help", "/?") for a in argumentos)


def quem_esta_na_porta(porta: int) -> str:
    """Devolve "livre", "nosso" ou "outro".

    São dois testes, e os dois são necessários.

    O primeiro é um `connect` de TCP, e ele existe porque no Windows NÃO dá para
    descobrir isso deixando o bind falhar: o `allow_reuse_address` que o
    `HTTPServer` liga por padrão faz o SO_REUSEADDR aceitar um segundo bind na
    MESMA porta já em LISTEN, sem erro nenhum. O resultado é pior que uma
    exceção - dois servidores disputando as conexões, em silêncio, cada um
    atendendo parte das requisições.

    O segundo é o `/api/saude`, e ele separa "já tem um validador aberto" de
    "tem outra coisa nessa porta". Sem essa distinção, ou mandaríamos o usuário
    para a página de um programa alheio, ou recusaríamos a abrir a janela que
    ele já tem. Qualquer falha na checagem responde "outro": entre errar para o
    lado de avisar e errar para o lado de abrir dois servidores, avisar é o
    menor dano.
    """
    import socket

    with socket.socket() as tentativa:
        tentativa.settimeout(1.0)
        try:
            tentativa.connect(("127.0.0.1", porta))
        except OSError:
            return "livre"

    import json
    import urllib.error
    import urllib.request

    try:
        with urllib.request.urlopen(
            f"http://127.0.0.1:{porta}/api/saude", timeout=1.5
        ) as resposta:
            return "nosso" if json.loads(resposta.read()).get("ok") else "outro"
    except (urllib.error.URLError, OSError, ValueError, json.JSONDecodeError):
        return "outro"


AJUDA_EXE = """Validador de NF-e / NFC-e

Sem argumentos, abre a interface no navegador (arraste o XML para a janela).

Com argumentos, funciona como linha de comando:

  nfe-validator.exe nota.xml              relatorio legivel
  nfe-validator.exe nota.xml --json       saida estruturada
  nfe-validator.exe nota.xml --csv        uma linha por erro, pronto p/ Excel
  nfe-validator.exe pasta --lote          revalida a pasta inteira
  nfe-validator.exe --ui                  forca a interface
  nfe-validator.exe --ui --porta 9000     interface em outra porta

Valida a nota (NF-e e NFC-e) e tambem os documentos de servico: eventos
(cancelamento, CC-e, manifestacao), consultas, inutilizacao, retornos de
lote e distribuicao de DF-e. A familia e reconhecida pela raiz do XML.
"""


def _garantir_saidas() -> None:
    """Dá a `sys.stdout`/`sys.stderr` um destino quando não existe nenhum.

    O .exe é compilado sem console (`console=False` no .spec), e nesse modo o
    PyInstaller deixa `sys.stdout` e `sys.stderr` valendo None. Como este
    módulo imprime desde a primeira linha (ajuda, aviso da janela, endereço do
    servidor), o `print()` estouraria com AttributeError antes de qualquer
    coisa útil acontecer - o usuário veria o programa "não abrir", sem mensagem.

    Redirecionar para o dispositivo nulo mantém o programa vivo e o
    comportamento intacto para quem redireciona a saída para um arquivo
    (`nfe-validator.exe nota.xml --json > saida.json`): aí o stdout existe e
    nada aqui é trocado.
    """
    for nome in ("stdout", "stderr"):
        if getattr(sys, nome, None) is None:
            setattr(sys, nome, open(os.devnull, "w", encoding="utf-8"))


def main(argumentos: list[str] | None = None) -> None:
    _garantir_saidas()
    argumentos = list(sys.argv[1:] if argumentos is None else argumentos)

    if _e_pedido_de_ajuda(argumentos):
        # Ajuda pedida de propósito vai para o stdout e sai com 0 — mesma
        # convenção do CLI, para não parecer falha em script nem em CI.
        print(AJUDA_EXE)
        sys.exit(0)

    abrir_ui = not argumentos or "--ui" in argumentos
    if not abrir_ui:
        cli()
        return

    porta = 8765
    if "--porta" in argumentos:
        indice = argumentos.index("--porta")
        try:
            porta = int(argumentos[indice + 1])
        except (IndexError, ValueError):
            print("--porta precisa de um numero. Ex.: --porta 9000", file=sys.stderr)
            sys.exit(2)

    ocupante = quem_esta_na_porta(porta)

    # Duplo clique duas vezes é o caso comum, não a exceção: quem já deixou o
    # validador aberto e clica de novo quer a janela, não um erro.
    if ocupante == "nosso":
        endereco = f"http://127.0.0.1:{porta}"
        print(f"O validador ja esta aberto em {endereco} - abrindo a janela.")
        import webbrowser
        webbrowser.open(endereco)
        return

    if ocupante == "outro":
        print(f"A porta {porta} esta ocupada por outro programa.", file=sys.stderr)
        print(f"Use outra: nfe-validator.exe --ui --porta {porta + 1}",
              file=sys.stderr)
        sys.exit(1)

    # `host` fica fixo em 127.0.0.1 e não é configurável aqui de propósito: os
    # XMLs carregam CNPJ, valores e dados de cliente, e um .exe que circula por
    # e-mail não é lugar de expor isso na rede por um erro de digitação. Quem
    # precisa escutar fora da máquina usa `nfe-validator-web --host`, onde a
    # escolha é explícita e vem com aviso.
    # Sem isso, NADA do que segue aparece quando a saída é redirecionada: o
    # stdout de um processo cujo destino não é console é bufferizado em bloco, e
    # `serve_forever()` bloqueia para sempre logo abaixo - o buffer só seria
    # despejado no encerramento. Vale para o aviso daqui e para o endereço que
    # o `servir()` imprime, que é justamente o que alguém quer ver ao rodar o
    # .exe com a saída em arquivo (serviço, agendador, log).
    try:
        sys.stdout.reconfigure(line_buffering=True)
    except (AttributeError, ValueError, OSError):
        pass

    # Aviso antes de servir, e não depois: `serve_forever()` bloqueia, então
    # qualquer coisa impressa depois só apareceria no encerramento.
    #
    # O `servir()` já imprime o endereço e "Ctrl+C para encerrar", que é
    # linguagem de quem vive no terminal. Quem recebeu este .exe por e-mail vê
    # uma janela preta e não tem motivo para saber que fechá-la derruba o
    # validador no meio do uso - a página no navegador simplesmente para de
    # responder, e o erro que aparece é "o validador não respondeu".
    print()
    print("=" * 62)
    print("  NAO FECHE ESTA JANELA enquanto estiver usando o validador.")
    print("  Ela e o proprio validador: a pagina no navegador para de")
    print("  funcionar se ela for fechada.")
    print()
    print("  Terminou? Feche esta janela para encerrar.")
    print("=" * 62)
    print()

    try:
        servir(host="127.0.0.1", porta=porta, abrir_navegador=True)
    except OSError as erro:
        print(f"Nao foi possivel abrir a porta {porta}: {erro}", file=sys.stderr)
        print(f"Tente outra: nfe-validator.exe --ui --porta {porta + 1}",
              file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
