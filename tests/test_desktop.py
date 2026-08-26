"""
Testes do ponto de entrada do executável (.exe).

O que se testa aqui é o DESPACHO e a detecção de porta. A detecção existe por
causa de uma armadilha do Windows: o `allow_reuse_address` que o `HTTPServer`
liga por padrão faz o SO_REUSEADDR aceitar um segundo bind na MESMA porta já em
LISTEN, sem erro. Confiar no bind para descobrir "porta ocupada" levava a dois
servidores disputando as conexões, em silêncio.

Rodar com:
    python -m unittest discover -s tests -p "test_*.py" -v
"""

import socket
import unittest
from contextlib import contextmanager

from nfe_validator import desktop
from nfe_validator.web import servidor


@contextmanager
def _porta_livre():
    """Reserva uma porta, devolve o número e libera antes de ceder o controle."""
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        porta = s.getsockname()[1]
    yield porta


class TesteDeteccaoDePorta(unittest.TestCase):

    def test_porta_sem_ninguem_e_livre(self):
        with _porta_livre() as porta:
            self.assertEqual(desktop.quem_esta_na_porta(porta), "livre")

    def test_reconhece_uma_instancia_nossa(self):
        """Pelo /api/saude, não só pela porta estar ocupada."""
        srv = servidor.criar_servidor("127.0.0.1", 0)
        porta = srv.server_port
        import threading
        t = threading.Thread(target=srv.serve_forever, daemon=True)
        t.start()
        try:
            self.assertEqual(desktop.quem_esta_na_porta(porta), "nosso")
        finally:
            srv.shutdown()
            srv.server_close()

    def test_socket_alheio_e_outro_nao_livre(self):
        """A distinção que impede dois servidores na mesma porta.

        Um socket que aceita conexão mas não fala o nosso protocolo não pode
        ser "livre" (o bind passaria no Windows) nem "nosso" (abrir o navegador
        levaria o usuário à página de outro programa).
        """
        with socket.socket() as alheio:
            alheio.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            alheio.bind(("127.0.0.1", 0))
            alheio.listen(1)
            porta = alheio.getsockname()[1]
            self.assertEqual(desktop.quem_esta_na_porta(porta), "outro")


class TesteDespacho(unittest.TestCase):
    """Sem argumento abre a UI; com argumento é CLI. O .exe tem os dois públicos."""

    def test_ajuda_sai_zero(self):
        """Ajuda pedida de propósito não é falha - mesma convenção do CLI."""
        for pedido in (["-h"], ["--help"], ["/?"]):
            with self.subTest(pedido=pedido):
                with self.assertRaises(SystemExit) as ctx:
                    desktop.main(pedido)
                self.assertEqual(ctx.exception.code, 0)

    def test_argumento_de_arquivo_vai_para_o_cli(self):
        """E NÃO para a UI: um script que passa um caminho quer código de saída."""
        chamou = {}

        def cli_falso():
            chamou["cli"] = True

        original = desktop.cli
        desktop.cli = cli_falso
        try:
            desktop.main(["nota.xml", "--json"])
        finally:
            desktop.cli = original
        self.assertTrue(chamou.get("cli"))

    def test_porta_sem_numero_e_erro_de_uso(self):
        with self.assertRaises(SystemExit) as ctx:
            desktop.main(["--ui", "--porta"])
        self.assertEqual(ctx.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
