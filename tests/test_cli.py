"""
Testes da interface de linha de comando (RF07/RF09).

O CLI é o que o pessoal do fiscal usa de verdade, então o contrato aqui é
comportamental: código de saída, colunas do CSV e o separador que o Excel em
português entende. Rodamos como subprocesso porque `main()` chama `sys.exit()`
e reconfigura o `stdout` — testar em processo separado é o que reflete o uso.

Rodar com:
    python -m unittest discover -s tests -p "test_*.py" -v
"""

import csv
import io
import subprocess
import sys
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
FIXTURE = RAIZ / "tests" / "fixtures" / "nfe_exemplo_invalida.xml"


def _rodar(*argumentos: str, entrada: str | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "nfe_validator", *argumentos],
        cwd=RAIZ, input=entrada, capture_output=True, text=True, encoding="utf-8",
    )


class TesteCodigosDeSaida(unittest.TestCase):
    """Convenção de shell: 0 = ok, 1 = nota reprovada, 2 = erro de uso."""

    def test_ajuda_pedida_sai_zero_no_stdout(self):
        """`--help` pedido de propósito não é falha. Sair com 2 fazia o comando
        parecer quebrado em script e em CI."""
        r = _rodar("--help")
        self.assertEqual(r.returncode, 0)
        self.assertIn("Uso:", r.stdout)
        self.assertEqual(r.stderr, "")

    def test_sem_argumento_e_erro_de_uso(self):
        r = _rodar()
        self.assertEqual(r.returncode, 2)
        self.assertIn("Uso:", r.stderr)

    def test_opcao_desconhecida_e_erro_de_uso(self):
        r = _rodar(str(FIXTURE), "--nao-existe")
        self.assertEqual(r.returncode, 2)
        self.assertIn("desconhecida", r.stderr)

    def test_arquivo_inexistente_e_erro_de_uso(self):
        r = _rodar(str(RAIZ / "nao-existe.xml"))
        self.assertEqual(r.returncode, 2)

    def test_nota_reprovada_sai_um(self):
        self.assertEqual(_rodar(str(FIXTURE)).returncode, 1)

    def test_le_de_stdin(self):
        r = _rodar("-", entrada=FIXTURE.read_text(encoding="utf-8"))
        self.assertEqual(r.returncode, 1)
        self.assertIn("REJEITADA", r.stdout)


class TesteExportacaoCsv(unittest.TestCase):
    """RF09 - exportar o relatório em formato legível além do JSON."""

    @classmethod
    def setUpClass(cls):
        resultado = _rodar(str(FIXTURE), "--csv")
        cls.bruto = resultado.stdout
        cls.codigo = resultado.returncode

    def _linhas(self) -> list[dict]:
        texto = self.bruto.lstrip("﻿")
        return list(csv.DictReader(io.StringIO(texto), delimiter=";"))

    def test_sai_com_o_mesmo_codigo_do_relatorio(self):
        self.assertEqual(self.codigo, 1)

    def test_tem_bom_para_o_excel_nao_quebrar_acentos(self):
        self.assertTrue(self.bruto.startswith("﻿"))

    def test_usa_ponto_e_virgula(self):
        """Com vírgula, o Excel em português joga tudo numa coluna só."""
        cabecalho = self.bruto.lstrip("﻿").splitlines()[0]
        self.assertIn(";", cabecalho)
        self.assertGreater(cabecalho.count(";"), 10)

    def test_uma_linha_por_erro(self):
        from nfe_validator import validar
        resultado = validar(FIXTURE.read_text(encoding="utf-8"))
        esperado = len(resultado["erros"]) + len(resultado["avisos"])
        self.assertEqual(len(self._linhas()), esperado)

    def test_colunas_na_ordem_declarada(self):
        from nfe_validator.__main__ import COLUNAS_CSV
        cabecalho = self.bruto.lstrip("﻿").splitlines()[0]
        self.assertEqual(cabecalho.split(";"), list(COLUNAS_CSV))

    def test_traz_o_que_o_fiscal_precisa_para_corrigir(self):
        linhas = self._linhas()
        self.assertTrue(linhas)
        for linha in linhas:
            self.assertTrue(linha["codigo"])
            self.assertTrue(linha["mensagem"])
            self.assertIn(linha["origem"], ("xsd", "regra-negocio"))

    def test_numero_do_item_preenchido_para_erro_de_item(self):
        de_item = [l for l in self._linhas() if l["item"]]
        self.assertTrue(de_item, "a fixture tem erros em det[1]")
        for linha in de_item:
            self.assertTrue(linha["item"].isdigit())

    def test_valores_com_ponto_e_virgula_ficam_escapados(self):
        """A documentação oficial de vários campos tem `;` no meio das legendas
        de enumeração — sem escape, o CSV ganharia colunas fantasma."""
        linhas = self.bruto.lstrip("﻿").splitlines()
        esperado = linhas[0].count(";")
        for i, linha in enumerate(linhas[1:], start=2):
            if linha.count(";") != esperado:
                self.assertIn('"', linha, f"linha {i} com ; sem aspas")

    def test_csv_em_lote_identifica_o_arquivo_de_origem(self):
        r = _rodar(str(FIXTURE.parent), "--lote", "--csv")
        linhas = list(csv.DictReader(io.StringIO(r.stdout.lstrip("﻿")), delimiter=";"))
        self.assertTrue(linhas)
        for linha in linhas:
            self.assertTrue(linha["arquivo"], "no lote a coluna arquivo é obrigatória")


class TesteOutrosModos(unittest.TestCase):

    def test_json_e_parseavel(self):
        import json
        r = _rodar(str(FIXTURE), "--json")
        dados = json.loads(r.stdout)
        self.assertIn("resumo", dados)
        self.assertIn("erros", dados)

    def test_so_nao_preenchidos_lista_somente_preenchimento(self):
        r = _rodar(str(FIXTURE), "--so-nao-preenchidos")
        self.assertIn("CAMPOS NÃO PREENCHIDOS", r.stdout)

    def test_sem_xsd_avisa_que_o_relatorio_esta_incompleto(self):
        r = _rodar(str(FIXTURE), "--sem-xsd")
        self.assertIn("XSD", r.stdout)


if __name__ == "__main__":
    unittest.main()
