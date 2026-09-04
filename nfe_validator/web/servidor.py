"""
Servidor HTTP da UI de drag-and-drop (spec-ui-drag-and-drop.md, Seção 7 passo 1).

Escolha de dependência
----------------------
A spec sugere "um framework leve (ex. FastAPI/Flask)". Usamos a `http.server`
da biblioteca padrão: mantém a única dependência do projeto em `lxml`, e o
alvo real é uma ferramenta LOCAL — a pessoa do fiscal roda na própria máquina e
arrasta o XML. Um framework web inteiro para dois endpoints seria peso morto
(mesmo espírito da RNF-UI03).

`processar_validacao()` é deliberadamente agnóstica de framework: recebe bytes,
devolve (status, dict). Montar em FastAPI ou Flask depois é escrever a rota e
chamar essa função — nenhuma lógica migra.

Escopo e limites
----------------
Este servidor NÃO é endurecido para produção (a própria doc da `http.server`
avisa isso). Por padrão ele escuta só em 127.0.0.1: um XML de NF-e carrega
CNPJ, valores e dados de cliente, e expor isso na rede por acidente seria bem
pior que a inconveniência de digitar `--host`.

A camada web não tem NENHUMA regra de negócio (Seção 2 da spec): ela recebe o
texto, chama `validar()` e devolve o JSON exatamente como sai — sem
transformação.
"""

import json
import mimetypes
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Optional

from ..nucleo.validador import validar

ESTATICOS = Path(__file__).resolve().parent / "estatico"

# RNF-UI05: teto no cliente é 5 MB; aqui é o mesmo teto, porque validação no
# cliente é conveniência e não defesa — o servidor não pode confiar nela.
TAMANHO_MAXIMO = 5 * 1024 * 1024

# Só estes arquivos são servidos. Lista explícita em vez de varredura do
# diretório: elimina travessia de caminho por construção.
ARQUIVOS_PUBLICOS = {
    "/": "index.html",
    "/index.html": "index.html",
    "/estilo.css": "estilo.css",
    "/app.js": "app.js",
}

_NOME_SEGURO = re.compile(r"^[A-Za-z0-9._-]+$")


def _erro(codigo: str, mensagem: str) -> dict:
    """Formato único de erro da camada web.

    Nunca devolvemos HTML de erro cru (Seção 7 passo 1). E a forma é distinta
    do contrato de validação — assim o front sabe, sem heurística, se recebeu
    um resultado de nota ou uma falha de infraestrutura."""
    return {"erro": {"codigo": codigo, "mensagem": mensagem}}


def processar_validacao(corpo: bytes) -> tuple[int, dict]:
    """Núcleo do endpoint, sem nada de HTTP: bytes entram, (status, dict) sai.

    É o ponto de montagem para qualquer framework."""
    if len(corpo) > TAMANHO_MAXIMO:
        return 413, _erro(
            "CORPO-GRANDE",
            f"O conteúdo enviado passa de {TAMANHO_MAXIMO // (1024 * 1024)} MB. "
            "Um XML de NF-e raramente chega perto disso — confira se o arquivo "
            "é mesmo uma nota.",
        )

    try:
        dados = json.loads(corpo.decode("utf-8"))
    except UnicodeDecodeError:
        return 400, _erro(
            "ENCODING-INVALIDO",
            "O corpo da requisição não está em UTF-8.",
        )
    except json.JSONDecodeError:
        return 400, _erro(
            "JSON-INVALIDO",
            "O corpo da requisição não é um JSON válido. Esperado: "
            '{"conteudoXml": "<NFe ...>"}',
        )

    if not isinstance(dados, dict):
        return 400, _erro("JSON-INVALIDO", "O corpo deve ser um objeto JSON.")

    conteudo = dados.get("conteudoXml")
    if not isinstance(conteudo, str) or not conteudo.strip():
        return 400, _erro(
            "XML-AUSENTE",
            "Informe o XML no campo 'conteudoXml'.",
        )

    try:
        # A única linha que importa: o resultado vai puro para o front.
        return 200, validar(conteudo)
    except Exception as exc:  # noqa: BLE001 - a UI não pode receber stack trace
        return 500, _erro(
            "FALHA-INESPERADA",
            f"O validador falhou de forma inesperada ({type(exc).__name__}). "
            "Isso é um defeito do servidor, não da sua nota.",
        )


class Manipulador(BaseHTTPRequestHandler):
    server_version = "nfe-validator"
    sys_version = ""      # não anunciar a versão do Python

    # -- utilitários ---------------------------------------------------
    def _responder_json(self, status: int, corpo: dict, fechar: bool = False) -> None:
        dados = json.dumps(corpo, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(dados)))
        self.send_header("Cache-Control", "no-store")   # RN-UI11: nada persiste
        if fechar:
            # Usado quando sobrou corpo não lido no socket.
            self.send_header("Connection", "close")
            self.close_connection = True
        self.end_headers()
        self.wfile.write(dados)

    def _responder_arquivo(self, nome: str) -> None:
        if not _NOME_SEGURO.match(nome):
            self._responder_json(404, _erro("NAO-ENCONTRADO", "Recurso inexistente."))
            return
        caminho = ESTATICOS / nome
        if not caminho.is_file():
            self._responder_json(
                500,
                _erro("ESTATICO-AUSENTE",
                      f"O arquivo '{nome}' da interface não foi encontrado na "
                      "instalação. Reinstale o pacote."),
            )
            return

        dados = caminho.read_bytes()
        tipo = mimetypes.guess_type(nome)[0] or "application/octet-stream"
        if tipo.startswith("text/") or tipo == "application/javascript":
            tipo += "; charset=utf-8"
        self.send_response(200)
        self.send_header("Content-Type", tipo)
        self.send_header("Content-Length", str(len(dados)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(dados)

    # -- verbos --------------------------------------------------------
    def do_GET(self) -> None:
        caminho = self.path.split("?", 1)[0]
        if caminho in ARQUIVOS_PUBLICOS:
            self._responder_arquivo(ARQUIVOS_PUBLICOS[caminho])
        elif caminho == "/api/saude":
            self._responder_json(200, {"ok": True})
        else:
            self._responder_json(404, _erro("NAO-ENCONTRADO", "Recurso inexistente."))

    def do_POST(self) -> None:
        try:
            tamanho = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            tamanho = 0

        if tamanho > TAMANHO_MAXIMO:
            # Aqui NÃO drenamos: não faz sentido puxar 500 MB só para descobrir
            # que é grande demais. Como o corpo fica pendente no socket, a
            # conexão tem que ser encerrada — senão o próximo pedido leria o
            # resto deste como se fosse dele.
            self._responder_json(
                413,
                _erro("CORPO-GRANDE",
                      f"O conteúdo passa de {TAMANHO_MAXIMO // (1024 * 1024)} MB."),
                fechar=True,
            )
            return

        # O corpo é lido ANTES de decidir a rota. Responder 404 deixando o
        # corpo no socket faz o cliente levar ConnectionReset em vez do 404 —
        # a UI mostraria "não foi possível falar com o validador" no lugar da
        # mensagem real.
        corpo = self.rfile.read(tamanho) if tamanho else b""

        if self.path.split("?", 1)[0] != "/api/validar":
            self._responder_json(404, _erro("NAO-ENCONTRADO", "Recurso inexistente."))
            return

        status, resposta = processar_validacao(corpo)
        self._responder_json(status, resposta)

    def log_message(self, formato: str, *args) -> None:
        """Só método, caminho e status — o corpo carrega dados fiscais e não
        tem por que aparecer em log (mesmo espírito da RN-UI11)."""
        print(f"  {self.address_string()} - {formato % args}")


def criar_servidor(host: str = "127.0.0.1", porta: int = 8765) -> ThreadingHTTPServer:
    return ThreadingHTTPServer((host, porta), Manipulador)


def servir(host: str = "127.0.0.1", porta: int = 8765,
           abrir_navegador: bool = True) -> None:
    servidor = criar_servidor(host, porta)
    endereco = f"http://{host}:{servidor.server_port}"

    print(f"Validador de NF-e/NFC-e em {endereco}")
    if host not in ("127.0.0.1", "localhost"):
        print("  ATENÇÃO: escutando fora de 127.0.0.1. Os XMLs enviados contêm")
        print("  CNPJ, valores e dados de cliente — confirme que esta rede é confiável.")
    print("  Ctrl+C para encerrar.")

    if abrir_navegador:
        import webbrowser
        webbrowser.open(endereco)

    try:
        servidor.serve_forever()
    except KeyboardInterrupt:
        print("\nEncerrando.")
    finally:
        servidor.server_close()


def main(argumentos: Optional[list[str]] = None) -> None:
    import argparse

    parser = argparse.ArgumentParser(
        prog="nfe-validator-web",
        description="Sobe a interface de arrastar-e-soltar do validador de NF-e/NFC-e.",
    )
    parser.add_argument("--host", default="127.0.0.1",
                        help="endereço de escuta (padrão: 127.0.0.1, só esta máquina)")
    parser.add_argument("--porta", type=int, default=8765, help="porta (padrão: 8765)")
    parser.add_argument("--sem-navegador", action="store_true",
                        help="não abrir o navegador automaticamente")
    args = parser.parse_args(argumentos)

    servir(args.host, args.porta, not args.sem_navegador)


if __name__ == "__main__":
    main()
