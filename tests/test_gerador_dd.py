"""
Testes do gerador do dicionário `.dd` consumido pelo ERP.

O arquivo gerado vai para outro desenvolvedor colocar no projeto do ERP, então
o que importa aqui é o CONTRATO com o leitor Java:

  * `NfeServico.getXSDTagInf()` troca `.xsd` por `.dd` — o nome do arquivo tem
    que casar com o XSD que o ERP valida;
  * a chave é o caminho pontilhado de `NfeReaderXML.pathToString()`, sem índice
    de repetição;
  * `Properties.load(InputStream)` lê em ISO-8859-1, então o arquivo tem que
    ser ASCII puro com `\\uXXXX` para os acentos.

Um erro em qualquer um dos três produz um arquivo que o ERP simplesmente
ignora, sem avisar ninguém.

Rodar com:
    python -m unittest discover -s tests -p "test_*.py" -v
"""

import codecs
import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from nfe_validator import layout
from nfe_validator.gerador_dd import (
    RAIZES,
    _escapar_valor,
    escrever_dd,
    gerar_dicionario,
)

RAIZ_PROJETO = Path(__file__).resolve().parent.parent

# Como o java.util.Properties interpreta um valor: \\uXXXX viram caracteres.
_ESCAPE_UNICODE = re.compile(r"\\u([0-9a-fA-F]{4})")


def _como_o_java_le(valor: str) -> str:
    return _ESCAPE_UNICODE.sub(lambda m: chr(int(m.group(1), 16)), valor)


def _carregar_properties(texto: str) -> dict[str, str]:
    """Parser mínimo no formato Properties, só o suficiente para conferir."""
    pares: dict[str, str] = {}
    for linha in texto.splitlines():
        if not linha.strip() or linha.lstrip().startswith(("#", "!")):
            continue
        chave, _, valor = linha.partition("=")
        pares[chave.strip()] = valor
    return pares


class TesteEscapeDeValor(unittest.TestCase):

    def test_acentos_viram_escape_unicode(self):
        self.assertEqual(_escapar_valor("Alíquota"), "Al\\u00edquota")

    def test_ascii_passa_intacto(self):
        self.assertEqual(_escapar_valor("Valor da BC do ICMS"), "Valor da BC do ICMS")

    def test_quebra_de_linha_e_tab_viram_espaco(self):
        """Properties trataria a quebra como fim do valor, comendo o resto."""
        resultado = _escapar_valor("linha um\nlinha dois\tcom tab")
        self.assertNotIn("\n", resultado)
        self.assertNotIn("\t", resultado)
        self.assertEqual(resultado, "linha um linha dois com tab")

    def test_barra_invertida_e_duplicada(self):
        self.assertEqual(_escapar_valor("a\\b"), "a\\\\b")

    def test_resultado_e_sempre_ascii(self):
        for entrada in ("Tributção pelo ICMS", "Não tributda", "ção çãõ ü"):
            _escapar_valor(entrada).encode("ascii")  # levanta se não for

    def test_roundtrip_com_a_leitura_do_java(self):
        original = "Alíquota do ICMS — situação não tributada"
        self.assertEqual(_como_o_java_le(_escapar_valor(original)), original)


@unittest.skipUnless(layout.disponivel(), "XSD oficial de NF-e não instalado")
class TesteGeracaoDoDicionario(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.dicionario = gerar_dicionario("enviNFe", versao="4.00")

    def test_gera_um_volume_plausivel_de_chaves(self):
        self.assertGreater(len(self.dicionario), 800)

    def test_chave_usa_caminho_pontilhado_sem_indice(self):
        """`NfeReaderXML` não numera repetições: o item 1 e o item 40 dividem a
        mesma chave. Emitir `det[1]` produziria chave que o ERP nunca busca."""
        self.assertIn("enviNFe.NFe.infNFe.det.prod.cProd", self.dicionario)
        for chave in self.dicionario:
            self.assertNotIn("[", chave, f"índice de repetição em {chave}")
            self.assertNotIn("/", chave, f"separador errado em {chave}")

    def test_cobre_os_caminhos_que_o_erp_referencia_no_codigo(self):
        """`NfeServico.validate()` testa literalmente
        `path.startsWith("enviNFe.NFe.infNFe.det")` e lê
        `enviNFe.NFe.infNFe.det.prod.cProd`."""
        self.assertIn("enviNFe.NFe.infNFe.det.prod.cProd", self.dicionario)
        self.assertTrue(
            any(c.startswith("enviNFe.NFe.infNFe.det") for c in self.dicionario)
        )

    def test_cobre_os_campos_do_dia_a_dia(self):
        esperados = [
            "enviNFe.NFe.infNFe.ide.cUF",
            "enviNFe.NFe.infNFe.ide.dhEmi",
            "enviNFe.NFe.infNFe.emit.CNPJ",
            "enviNFe.NFe.infNFe.det.prod.NCM",
            "enviNFe.NFe.infNFe.det.prod.CFOP",
            "enviNFe.NFe.infNFe.det.imposto.ICMS.ICMS00.vBC",
            "enviNFe.NFe.infNFe.total.ICMSTot.vNF",
        ]
        faltando = [c for c in esperados if c not in self.dicionario]
        self.assertEqual(faltando, [])

    def test_catalogo_escrito_a_mao_vence_o_texto_curto_do_xsd(self):
        """Regressão: `ICMS00.vBC` não casava com a chave `ICMS.vBC` do
        catálogo e caía no "Valor da BC do ICMS" do XSD, jogando fora a
        explicação boa — que é justamente o que o ERP não tem."""
        texto = self.dicionario["enviNFe.NFe.infNFe.det.imposto.ICMS.ICMS00.vBC"]
        self.assertIn("Base de Cálculo do ICMS", texto)
        self.assertIn("Como corrigir:", texto)
        self.assertNotEqual(texto, "Valor da BC do ICMS")

    def test_mesma_tag_em_grupos_diferentes_recebe_texto_diferente(self):
        icms = self.dicionario["enviNFe.NFe.infNFe.det.imposto.ICMS.ICMS00.vBC"]
        pis = self.dicionario["enviNFe.NFe.infNFe.det.imposto.PIS.PISAliq.vBC"]
        self.assertIn("ICMS", icms)
        self.assertIn("PIS", pis)
        self.assertNotEqual(icms, pis)

    def test_campo_sem_catalogo_usa_o_texto_oficial_do_xsd(self):
        """`natOp` não está no catálogo escrito à mão, então herda o
        `xs:documentation` do XSD, copiado literalmente."""
        natop = self.dicionario["enviNFe.NFe.infNFe.ide.natOp"]
        self.assertTrue(natop)
        self.assertNotIn("Como corrigir:", natop)

    def test_campo_catalogado_traz_a_orientacao_de_correcao(self):
        """Esse é o ganho para o operador: hoje o ERP não mostra descrição
        nenhuma, e passa a mostrar o que fazer."""
        cuf = self.dicionario["enviNFe.NFe.infNFe.ide.cUF"]
        self.assertIn("Como corrigir:", cuf)
        self.assertIn("IBGE", cuf)

    def test_nenhum_valor_vazio(self):
        vazios = [c for c, v in self.dicionario.items() if not v.strip()]
        self.assertEqual(vazios, [])

    def test_raiz_desconhecida_devolve_vazio(self):
        self.assertEqual(gerar_dicionario("naoExiste"), {})

    def test_versao_inexistente_devolve_vazio(self):
        self.assertEqual(gerar_dicionario("enviNFe", versao="9.99"), {})


@unittest.skipUnless(layout.disponivel(), "XSD oficial de NF-e não instalado")
class TesteArquivoEscrito(unittest.TestCase):

    def setUp(self):
        import tempfile
        self.pasta = Path(tempfile.mkdtemp(prefix="dd-"))
        self.destino = self.pasta / "enviNFe_v4.00.dd"
        escrever_dd(self.destino, gerar_dicionario("enviNFe"), "enviNFe", "4.00")
        self.texto = self.destino.read_text(encoding="ascii")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.pasta, ignore_errors=True)

    def test_arquivo_e_ascii_puro(self):
        """`Properties.load(InputStream)` lê ISO-8859-1. ASCII puro com
        \\uXXXX funciona em qualquer leitura, sem depender de encoding."""
        self.destino.read_bytes().decode("ascii")

    def test_nome_do_arquivo_casa_com_o_xsd_validado(self):
        """`getXSDTagInf()` faz `caminho.replace(".xsd", ".dd")` — qualquer
        outro nome e o ERP não encontra o dicionário."""
        esperado = RAIZES["enviNFe"].format(versao="4.00").replace(".xsd", ".dd")
        self.assertEqual(self.destino.name, esperado)

    def test_todo_valor_cabe_em_uma_linha(self):
        pares = _carregar_properties(self.texto)
        self.assertGreater(len(pares), 800)
        # Uma linha sem "=" indicaria valor quebrado em duas linhas.
        for linha in self.texto.splitlines():
            if linha.strip() and not linha.lstrip().startswith("#"):
                self.assertIn("=", linha)

    def test_sem_chaves_duplicadas(self):
        chaves = [
            linha.partition("=")[0]
            for linha in self.texto.splitlines()
            if linha.strip() and not linha.lstrip().startswith("#")
        ]
        self.assertEqual(len(chaves), len(set(chaves)))

    def test_escapes_sao_validos_para_o_java(self):
        """Um `\\u` incompleto faz o Properties.load() lançar
        IllegalArgumentException e derrubar a leitura inteira."""
        for valor in _carregar_properties(self.texto).values():
            for pedaco in re.findall(r"\\u.{0,4}", valor):
                self.assertRegex(pedaco, r"^\\u[0-9a-fA-F]{4}$")

    def test_valores_voltam_legiveis_na_leitura_do_java(self):
        pares = _carregar_properties(self.texto)
        texto = _como_o_java_le(pares["enviNFe.NFe.infNFe.det.imposto.ICMS.ICMS00.vBC"])
        self.assertIn("Base de Cálculo do ICMS", texto)
        self.assertNotIn("\\u", texto)

    def test_cabecalho_explica_de_onde_veio(self):
        self.assertIn("getXSDTagInf", self.texto)
        self.assertIn("ISO-8859-1", self.texto)
        self.assertIn("gerador_dd.py", self.texto)


class TesteArtefatoNaRaizDoProjeto(unittest.TestCase):
    """O arquivo entregue fica na raiz, para ser encaminhado ao outro dev."""

    def test_o_dd_entregue_existe_e_esta_consistente(self):
        entregue = RAIZ_PROJETO / "enviNFe_v4.00.dd"
        if not entregue.exists():
            self.skipTest("enviNFe_v4.00.dd ainda não gerado")
        texto = entregue.read_text(encoding="ascii")
        pares = _carregar_properties(texto)
        self.assertGreater(len(pares), 800)
        self.assertIn("enviNFe.NFe.infNFe.det.prod.cProd", pares)


if __name__ == "__main__":
    unittest.main()
