"""
Testes dos achados vindos do ERP (server-weld).

Origem destes testes
--------------------
Rodar o validador contra 24 NF-e reais JÁ AUTORIZADAS pela SEFAZ (as
`nfe_procNFe_*.xml` que o ERP guarda) reprovou todas as 24. Nenhuma delas
tinha erro: eram três bugs nossos.

Cada teste abaixo trava um desses bugs. Os dados são sintéticos de propósito —
as notas reais têm CNPJ e valores de clientes, e fixture de produção não entra
no repositório.

    1. Envelope não reconhecido: os arquivos reais têm raiz `nfeProc`
       (NFe + protNFe) e o nosso XSD de entrada declara só `NFe`.
    2. `cBenef` vazio é VÁLIDO: o pattern do XSD termina em `?`.
    3. `infAdic` vazio é um GRUPO sem filhos, não um campo em branco.
    4. RN11 comparava vNF com a soma de vProd, reprovando qualquer nota com
       frete, desconto, IPI ou ST (11 das 24).

Rodar com:
    python -m unittest discover -s tests -p "test_*.py" -v
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from nfe_validator import layout
from nfe_validator.coletor_erp import (
    extrair_xmls_do_log,
    resumir,
    revalidar,
)
from nfe_validator.parser import parsear_xml
from nfe_validator.regras.campos_obrigatorios import validar_campos_obrigatorios
from nfe_validator.regras.totais import calcular_vnf_esperado, validar_totais
from nfe_validator.schema import _desembrulhar_envelope
from nfe_validator.validador import validar

NS = 'xmlns="http://www.portalfiscal.inf.br/nfe"'


def _nfe_interna(extra_prod: str = "", extra_infnfe: str = "") -> str:
    return (
        f'<NFe {NS}><infNFe versao="4.00" Id="NFe{"1" * 44}">'
        "<ide><mod>55</mod></ide>"
        f'<det nItem="1"><prod><cProd>1</cProd>{extra_prod}</prod></det>'
        f"{extra_infnfe}"
        "</infNFe></NFe>"
    )


class TesteEnvelope(unittest.TestCase):
    """Os arquivos que o ERP guarda e transmite são envelopes, não <NFe> nua."""

    def test_desembrulha_nfeproc(self):
        xml = (
            f'<nfeProc {NS} versao="4.00">{_nfe_interna()}'
            "<protNFe><infProt><cStat>100</cStat></infProt></protNFe></nfeProc>"
        )
        arvore = _desembrulhar_envelope(parsear_xml(xml))
        self.assertEqual(str(arvore.getroot().tag).split("}")[-1], "NFe")

    def test_desembrulha_envinfe(self):
        xml = f'<enviNFe {NS} versao="4.00"><idLote>1</idLote>{_nfe_interna()}</enviNFe>'
        arvore = _desembrulhar_envelope(parsear_xml(xml))
        self.assertEqual(str(arvore.getroot().tag).split("}")[-1], "NFe")

    def test_nfe_nua_passa_intacta(self):
        arvore = parsear_xml(_nfe_interna())
        self.assertIs(_desembrulhar_envelope(arvore), arvore)

    def test_envelope_sem_nfe_dentro_passa_intacto(self):
        """Não inventamos desembrulho onde não há o que desembrulhar."""
        xml = f'<nfeProc {NS} versao="4.00"><protNFe/></nfeProc>'
        arvore = parsear_xml(xml)
        self.assertIs(_desembrulhar_envelope(arvore), arvore)

    def test_envelope_nao_gera_mais_erro_de_raiz(self):
        """Antes: 'No matching global declaration available for the validation
        root' em toda nota autorizada — um erro NOSSO disfarçado de erro da nota."""
        xml = (
            f'<nfeProc {NS} versao="4.00">{_nfe_interna()}'
            "<protNFe><infProt><cStat>100</cStat></infProt></protNFe></nfeProc>"
        )
        resultado = validar(xml)
        tecnicas = " ".join(str(e.get("mensagem_tecnica") or "") for e in resultado["erros"])
        self.assertNotIn("No matching global declaration", tecnicas)


@unittest.skipUnless(layout.disponivel(), "XSD oficial de NF-e não instalado")
class TesteCampoQueAceitaVazio(unittest.TestCase):

    def test_cbenef_aceita_vazio_segundo_o_xsd(self):
        """O pattern é `([!-ÿ]{8}|[!-ÿ]{10}|SEM CBENEF)?` — o `?` final admite
        a string vazia. A premissa "nenhuma tag folha pode estar vazia no
        leiaute 4.00" era falsa, e `<cBenef></cBenef>` aparece em notas
        autorizadas."""
        self.assertTrue(layout.aceita_vazio("cBenef"))

    def test_campo_normal_nao_aceita_vazio(self):
        for tag in ("vBC", "xNome", "NCM", "CFOP"):
            self.assertFalse(layout.aceita_vazio(tag), f"{tag} não deveria aceitar vazio")

    def test_cbenef_vazio_nao_e_mais_acusado(self):
        erros = validar_campos_obrigatorios(parsear_xml(_nfe_interna("<cBenef></cBenef>")))
        vazios = [e for e in erros if e["codigo"] == "RN18-VAZIO"]
        self.assertEqual(vazios, [], "cBenef vazio é válido pelo XSD")

    def test_grupo_vazio_nao_e_campo_em_branco(self):
        """`<infAdic></infAdic>` é um grupo sem filhos. Tratar como campo em
        branco gerava erro sem sentido em nota autorizada."""
        self.assertTrue(layout.e_grupo("infAdic"))
        erros = validar_campos_obrigatorios(
            parsear_xml(_nfe_interna(extra_infnfe="<infAdic></infAdic>"))
        )
        vazios = [e for e in erros if e["detalhe"]["tagXml"] == "infAdic"]
        self.assertEqual(vazios, [])

    def test_campo_realmente_vazio_continua_sendo_acusado(self):
        """A correção não pode ter desligado a regra."""
        erros = validar_campos_obrigatorios(
            parsear_xml(_nfe_interna("<xProd></xProd>"))
        )
        self.assertTrue(any(e["codigo"] == "RN18-VAZIO" and e["detalhe"]["tagXml"] == "xProd"
                            for e in erros))


class TesteFormulaDoVnf(unittest.TestCase):
    """RN11 comparava vNF com a soma de vProd, o que reprovava qualquer nota
    com frete, desconto, IPI ou ST. A fórmula abaixo foi conferida contra as
    24 notas autorizadas: 24 conferem, 0 divergem."""

    def test_soma_e_subtrai_as_parcelas_certas(self):
        valor, memoria = calcular_vnf_esperado({
            "vProd": "1000.00", "vFrete": "100.00", "vSeg": "50.00",
            "vOutro": "10.00", "vDesc": "60.00", "vIPI": "25.00",
            "vST": "15.00", "vICMSDeson": "5.00",
        })
        # 1000 + 100 + 50 + 10 + 25 + 15 - 60 - 5
        self.assertAlmostEqual(valor, 1135.00, places=2)
        self.assertIn("vFrete", memoria)
        self.assertIn("- vDesc", memoria)

    def test_memoria_omite_parcelas_zeradas(self):
        _, memoria = calcular_vnf_esperado({"vProd": "100.00", "vFrete": "0.00"})
        self.assertIn("vProd", memoria)
        self.assertNotIn("vFrete", memoria)

    def test_componentes_ausentes_valem_zero(self):
        valor, _ = calcular_vnf_esperado({"vProd": "100.00"})
        self.assertAlmostEqual(valor, 100.00, places=2)

    def test_valor_nao_numerico_nao_estoura(self):
        valor, _ = calcular_vnf_esperado({"vProd": "abc", "vFrete": None})
        self.assertAlmostEqual(valor, 0.0, places=2)

    def test_nota_com_frete_e_desconto_nao_e_mais_falso_positivo(self):
        componentes = {"vProd": "1000.00", "vFrete": "100.00", "vDesc": "50.00",
                       "vNF": "1050.00"}
        erros = validar_totais(
            soma_vprod_itens=1000.0, v_prod_total_declarado=1000.0,
            soma_vicms_itens=0.0, v_icms_total_declarado=0.0,
            v_nf_declarado=1050.0, componentes_icmstot=componentes,
        )
        self.assertEqual([e for e in erros if e["codigo"] == "RN11-VNF"], [])

    def test_divergencia_real_continua_sendo_pega_com_memoria_de_calculo(self):
        erros = validar_totais(
            soma_vprod_itens=1000.0, v_prod_total_declarado=1000.0,
            soma_vicms_itens=0.0, v_icms_total_declarado=0.0,
            v_nf_declarado=9999.0,
            componentes_icmstot={"vProd": "1000.00", "vFrete": "100.00"},
        )
        vnf = [e for e in erros if e["codigo"] == "RN11-VNF"]
        self.assertEqual(len(vnf), 1)
        self.assertIn("Memória de cálculo", vnf[0]["motivo_rejeicao"])
        self.assertIn("vFrete", vnf[0]["motivo_rejeicao"])

    def test_assinatura_antiga_continua_funcionando(self):
        """Compatibilidade: quem já passava `v_nf_esperado` calculado por fora
        não deve quebrar."""
        self.assertEqual(validar_totais(100.0, 100.0, 18.0, 18.0, 100.0, 100.0), [])


class TesteColetorDeLogDoErp(unittest.TestCase):
    """O ERP despeja o XML no stderr entre marcadores, e o stderr do monitor
    vai para `out/monitor-nfe-*.out.txt`."""

    LOG = (
        "2026-01-05 10:00:01 INFO  monitor iniciado\n"
        "================ ERRO NFE ====================\n"
        '<enviNFe xmlns="http://www.portalfiscal.inf.br/nfe" versao="4.00">'
        "<idLote>1</idLote></enviNFe>\n"
        "==============================================\n"
        "javax.xml.bind.MarshalException: algo\n"
        "================ ERRO NFE ====================\n"
        '<enviNFe xmlns="http://www.portalfiscal.inf.br/nfe" versao="4.00">'
        "<idLote>2</idLote></enviNFe>\n"
        "==============================================\n"
        "2026-01-05 10:05:00 INFO  fim\n"
    )

    def test_extrai_os_blocos_entre_marcadores(self):
        coletados = extrair_xmls_do_log(self.LOG, "out/monitor-nfe-teste.out.txt")
        self.assertEqual(len(coletados), 2)
        self.assertIn("<idLote>1</idLote>", coletados[0].conteudo)
        self.assertIn("<idLote>2</idLote>", coletados[1].conteudo)

    def test_rotulo_aponta_arquivo_e_linha(self):
        coletados = extrair_xmls_do_log(self.LOG, "out/monitor-nfe-teste.out.txt")
        self.assertTrue(coletados[0].rotulo.startswith("monitor-nfe-teste.out.txt:"))
        self.assertIsInstance(coletados[0].linha, int)

    def test_ignora_ruido_de_log_fora_dos_marcadores(self):
        coletados = extrair_xmls_do_log(self.LOG)
        for coletado in coletados:
            self.assertNotIn("MarshalException", coletado.conteudo)
            self.assertNotIn("monitor iniciado", coletado.conteudo)

    def test_bloco_sem_marcador_de_fim_nao_engole_o_resto_do_log(self):
        log = (
            "================ ERRO NFE ====================\n"
            f"{_nfe_interna()}\n"
            "2026-01-05 10:00:02 INFO  linha de log comum\n"
            "mais log ainda\n"
        )
        coletados = extrair_xmls_do_log(log)
        self.assertEqual(len(coletados), 1)
        self.assertNotIn("linha de log comum", coletados[0].conteudo)

    def test_log_sem_erro_nfe_nao_produz_nada(self):
        self.assertEqual(extrair_xmls_do_log("apenas log\nsem xml\n"), [])


class TesteRevalidacaoEmLote(unittest.TestCase):

    def setUp(self):
        import tempfile
        self.pasta = Path(tempfile.mkdtemp(prefix="lote-erp-"))

    def tearDown(self):
        import shutil
        shutil.rmtree(self.pasta, ignore_errors=True)

    def _escrever(self, nome: str, conteudo: str):
        (self.pasta / nome).write_text(conteudo, encoding="utf-8")

    def test_evento_e_validado_e_nao_mais_pulado(self):
        """A pasta do ERP mistura notas, eventos e resumos.

        O evento era classificado como "fora de escopo" - não por não
        interessar, mas porque o validador não sabia validá-lo. Com o
        roteamento por família (ver `servicos`), ele passa pelo XSD do evento.
        Este `<procEventoNFe>` é um esqueleto: `<evento/>` vazio e sem
        `<retEvento>`, então tem que ser REPROVADO, não pulado - um
        cancelamento malformado é exatamente o que uma varredura procura.
        """
        self._escrever(
            "evento.xml",
            f'<procEventoNFe {NS} versao="1.00"><evento/></procEventoNFe>',
        )
        resumo = resumir(revalidar(self.pasta))
        self.assertEqual(resumo["foraDeEscopo"], 0)
        self.assertEqual(resumo["invalidos"], 1)

    def test_resumo_do_distdfe_segue_fora_de_escopo(self):
        """O que sobrou na lista tem um motivo só: não há XSD instalado.

        O pacote do distribuiçãoDFe não foi baixado, então dizer "fora de
        escopo" é mais honesto que validar contra o schema errado (RN15).
        """
        self._escrever("resumo.xml", f'<resNFe {NS} versao="1.01"><chNFe/></resNFe>')
        resumo = resumir(revalidar(self.pasta))
        self.assertEqual(resumo["foraDeEscopo"], 1)
        self.assertEqual(resumo["invalidos"], 0)

    def test_valida_nota_e_agrega_por_codigo(self):
        self._escrever("nota.xml", _nfe_interna())
        resultados = revalidar(self.pasta)
        resumo = resumir(resultados)
        self.assertEqual(resumo["totalXmls"], 1)
        self.assertEqual(resumo["invalidos"], 1)  # nota mínima, incompleta
        self.assertTrue(resumo["porCodigo"])
        self.assertTrue(resumo["camposMaisProblematicos"])

    def test_coleta_xml_de_dentro_de_log_do_erp(self):
        self._escrever(
            "monitor-nfe-maq1-05-01-26-10-00-00.out.txt",
            "================ ERRO NFE ====================\n"
            f"{_nfe_interna()}\n"
            "==============================================\n",
        )
        resultados = revalidar(self.pasta)
        self.assertEqual(len(resultados), 1)
        self.assertIn("resultado", resultados[0])

    def test_arquivo_que_nao_e_xml_e_ignorado(self):
        self._escrever("leiame.md", "# nao sou xml")
        (self.pasta / "vazio.xml").write_text("", encoding="utf-8")
        self.assertEqual(revalidar(self.pasta), [])

    def test_caminho_inexistente_devolve_vazio(self):
        self.assertEqual(revalidar(self.pasta / "nao-existe"), [])

    def test_xml_corrompido_e_reportado_sem_derrubar_o_lote(self):
        self._escrever("bom.xml", _nfe_interna())
        self._escrever("ruim.xml", "<NFe><infNFe></NFe>")
        resultados = revalidar(self.pasta)
        self.assertEqual(len(resultados), 2)
        # XML mal-formado é erro de validação (RN04), não quebra do coletor.
        for item in resultados:
            self.assertNotIn("erroLeitura", item)


if __name__ == "__main__":
    unittest.main()
