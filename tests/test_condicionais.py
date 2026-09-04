"""
Testes da RN19 - obrigatoriedade condicional derivada do XSD.

O teste mais importante desta suíte é o de FALSO POSITIVO: uma regra que
acusa erro numa nota válida destrói a credibilidade do relatório inteiro, e o
usuário passa a ignorar todos os erros. Por isso as notas válidas vêm primeiro
e cobrem uma variante de cada forma (com campos, sem campos, Simples Nacional,
grupo opcional completo, e os dois ramos do XOR do IPI).

Rodar com:
    python -m unittest discover -s tests -p "test_*.py" -v
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from nfe_validator.nucleo import layout
from nfe_validator.nucleo.parser import parsear_xml
from nfe_validator.nucleo.regras.obrigatorios_condicionais import (
    validar_obrigatorios_condicionais,
)
from nfe_validator.nucleo.validador import validar

NS = 'xmlns="http://www.portalfiscal.inf.br/nfe"'

ICMS00_COMPLETO = (
    "<ICMS><ICMS00><orig>0</orig><CST>00</CST><modBC>3</modBC>"
    "<vBC>100.00</vBC><pICMS>18.00</pICMS><vICMS>18.00</vICMS></ICMS00></ICMS>"
)


def _nota(imposto: str, n_item: str = "1") -> str:
    """Nota mínima para exercitar a RN19.

    O `<ide><mod>` é indispensável: sem ele a RN01 não identifica o documento e
    `validar()` retorna antes de chegar às regras de item."""
    return (
        f'<?xml version="1.0" encoding="UTF-8"?>\n<NFe {NS}>'
        f'<infNFe versao="4.00" Id="NFe{"1" * 44}">'
        "<ide><mod>55</mod></ide>"
        f'<det nItem="{n_item}"><prod><cProd>1</cProd></prod>'
        f"<imposto>{imposto}</imposto></det>"
        "</infNFe></NFe>"
    )


def _rn19(imposto: str, n_item: str = "1") -> list[dict]:
    return validar_obrigatorios_condicionais(parsear_xml(_nota(imposto, n_item)))


def _codigos(erros: list[dict]) -> list[str]:
    return [e["codigo"] for e in erros]


def _tags(erros: list[dict]) -> set[str]:
    return {e["detalhe"]["tagXml"] for e in erros}


@unittest.skipUnless(layout.disponivel(), "XSD oficial de NF-e não instalado")
class TesteSemFalsoPositivo(unittest.TestCase):
    """Notas tributariamente corretas não podem produzir NENHUM erro RN19."""

    def _sem_erro(self, titulo: str, imposto: str):
        erros = _rn19(imposto)
        self.assertEqual(
            erros, [],
            f"{titulo}: falso positivo -> "
            + ", ".join(f"{e['codigo']}/{e['detalhe']['tagXml']}" for e in erros),
        )

    def test_icms00_completo(self):
        self._sem_erro("ICMS00 completo", ICMS00_COMPLETO)

    def test_icms00_com_grupo_fcp_completo(self):
        self._sem_erro(
            "ICMS00 + FCP",
            ICMS00_COMPLETO.replace(
                "</ICMS00>", "<pFCP>2.00</pFCP><vFCP>2.00</vFCP></ICMS00>"
            ),
        )

    def test_icms40_que_quase_nao_tem_campos(self):
        self._sem_erro("ICMS40", "<ICMS><ICMS40><orig>0</orig><CST>40</CST></ICMS40></ICMS>")

    def test_icmssn102_do_simples_nacional(self):
        """Só `CSOSN` é exigido: `orig` está com minOccurs="0" nesta variante.
        Uma tabela escrita de memória exigiria `orig` aqui e geraria falso
        positivo em toda nota de optante do Simples."""
        self._sem_erro("ICMSSN102", "<ICMS><ICMSSN102><CSOSN>102</CSOSN></ICMSSN102></ICMS>")

    def test_ipi_ad_valorem(self):
        self._sem_erro(
            "IPITrib ad valorem",
            "<IPI><cEnq>999</cEnq><IPITrib><CST>00</CST><vBC>100.00</vBC>"
            "<pIPI>5.00</pIPI><vIPI>5.00</vIPI></IPITrib></IPI>",
        )

    def test_ipi_por_unidade(self):
        """O outro ramo do XOR: quantidade x valor unitário, sem vBC/pIPI."""
        self._sem_erro(
            "IPITrib por unidade",
            "<IPI><cEnq>999</cEnq><IPITrib><CST>00</CST><qUnid>10.0000</qUnid>"
            "<vUnid>1.0000</vUnid><vIPI>10.00</vIPI></IPITrib></IPI>",
        )

    def test_pis_e_cofins_completos(self):
        self._sem_erro(
            "PIS + COFINS",
            "<PIS><PISAliq><CST>01</CST><vBC>100.00</vBC><pPIS>1.65</pPIS>"
            "<vPIS>1.65</vPIS></PISAliq></PIS>"
            "<COFINS><COFINSAliq><CST>01</CST><vBC>100.00</vBC>"
            "<pCOFINS>7.60</pCOFINS><vCOFINS>7.60</vCOFINS></COFINSAliq></COFINS>",
        )

    def test_grupo_de_imposto_ausente_nao_e_problema_da_rn19(self):
        """Item sem <ICMS> nenhum: quem reclama é o XSD, não esta regra."""
        self._sem_erro("imposto vazio", "")

    def test_grupo_aberto_sem_variante_nao_e_problema_da_rn19(self):
        """<ICMS></ICMS> sem variante dentro: o XSD reporta como grupo
        incompleto. Duplicar aqui só poluiria o relatório."""
        self._sem_erro("ICMS sem variante", "<ICMS></ICMS>")


@unittest.skipUnless(layout.disponivel(), "XSD oficial de NF-e não instalado")
class TesteDeteccao(unittest.TestCase):

    def test_reporta_todos_os_campos_faltantes_de_uma_vez(self):
        """O ganho central sobre o libxml2, que para no primeiro campo de cada
        grupo e obriga o usuário a corrigir-reenviar-descobrir em ciclos."""
        erros = _rn19(
            "<ICMS><ICMS00><orig>0</orig><CST>00</CST><modBC>3</modBC></ICMS00></ICMS>"
        )
        self.assertEqual(_tags(erros), {"vBC", "pICMS", "vICMS"})
        self.assertEqual(set(_codigos(erros)), {"RN19-CONDICIONAL-AUSENTE"})

    def test_mensagem_cita_o_grupo_que_criou_a_obrigacao(self):
        """É o que distingue a RN19 da RN18: não é "falta um campo", é "falta
        este campo PORQUE você declarou este grupo"."""
        erro = _rn19(
            "<ICMS><ICMS00><orig>0</orig><CST>00</CST><modBC>3</modBC>"
            "<pICMS>1</pICMS><vICMS>1</vICMS></ICMS00></ICMS>"
        )[0]
        self.assertEqual(erro["detalhe"]["tagXml"], "vBC")
        self.assertIn("ICMS00", erro["detalhe"]["gatilho"])
        self.assertIn("ICMS00", erro["motivo_rejeicao"])

    def test_campo_exigido_apenas_por_uma_variante(self):
        """`pRedBC` é obrigatório no ICMS20 e não existe no ICMS00 — o tipo de
        regra que só o XSD sabe direito."""
        erros = _rn19(
            "<ICMS><ICMS20><orig>0</orig><CST>20</CST><modBC>3</modBC>"
            "<vBC>80.00</vBC><pICMS>18.00</pICMS><vICMS>14.40</vICMS></ICMS20></ICMS>"
        )
        self.assertEqual(_tags(erros), {"pRedBC"})

    def test_cst_incompativel_com_o_grupo_onde_foi_declarado(self):
        erros = _rn19(
            "<ICMS><ICMS00><orig>0</orig><CST>40</CST><modBC>3</modBC>"
            "<vBC>1</vBC><pICMS>1</pICMS><vICMS>1</vICMS></ICMS00></ICMS>"
        )
        self.assertEqual(_codigos(erros), ["RN19-CODIGO-INCOMPATIVEL"])
        # A mensagem tem que dizer para onde o código pertence.
        self.assertIn("ICMS40", erros[0]["detalhe"]["esperado"])

    def test_grupo_tudo_ou_nada_pela_metade(self):
        erros = _rn19(
            ICMS00_COMPLETO.replace("</ICMS00>", "<pFCP>2.00</pFCP></ICMS00>")
        )
        self.assertEqual(_codigos(erros), ["RN19-GRUPO-INCOMPLETO"])
        self.assertEqual(_tags(erros), {"vFCP"})
        self.assertIn("pFCP", erros[0]["detalhe"]["gatilho"])

    def test_xor_com_os_dois_ramos_informados(self):
        erros = _rn19(
            "<IPI><cEnq>999</cEnq><IPITrib><CST>00</CST><vBC>100.00</vBC>"
            "<pIPI>5.00</pIPI><qUnid>10.0000</qUnid><vUnid>1.0000</vUnid>"
            "<vIPI>5.00</vIPI></IPITrib></IPI>"
        )
        self.assertIn("RN19-ALTERNATIVA-VIOLADA", _codigos(erros))

    def test_xor_com_ramo_incompleto(self):
        erros = _rn19(
            "<IPI><cEnq>999</cEnq><IPITrib><CST>00</CST><vBC>100.00</vBC>"
            "<vIPI>5.00</vIPI></IPITrib></IPI>"
        )
        self.assertIn("RN19-ALTERNATIVA-VIOLADA", _codigos(erros))

    def test_numero_do_item_vem_do_nitem(self):
        erros = _rn19(
            "<ICMS><ICMS00><orig>0</orig><CST>00</CST><modBC>3</modBC></ICMS00></ICMS>",
            n_item="7",
        )
        for erro in erros:
            self.assertIn("Item 7", erro["detalhe"]["onde"])

    def test_variante_ambigua_por_cst_ainda_e_validada_pelo_elemento(self):
        """CST 20 vale para ICMS20 e ICMSPart. Como lemos a variante do XML e
        não deduzimos do CST, a validação funciona mesmo assim."""
        erros = _rn19(
            "<ICMS><ICMSPart><orig>0</orig><CST>20</CST><modBC>3</modBC>"
            "<vBC>1</vBC><pICMS>1</pICMS><vICMS>1</vICMS></ICMSPart></ICMS>"
        )
        faltantes = _tags(erros)
        self.assertIn("pBCOp", faltantes, "campos próprios do ICMSPart devem ser exigidos")
        self.assertIn("UFST", faltantes)


class TesteIntegracaoNoValidador(unittest.TestCase):

    def test_rn19_pode_ser_desligada(self):
        """RN13 (a de verdade): cada regra é um módulo nomeado e desligável."""
        xml = _nota("<ICMS><ICMS00><orig>0</orig><CST>00</CST></ICMS00></ICMS>")
        com = validar(xml, aplicar_xsd=False)
        sem = validar(xml, aplicar_xsd=False, aplicar_condicionais=False)
        codigos_com = {e["codigo"] for e in com["erros"]}
        codigos_sem = {e["codigo"] for e in sem["erros"]}
        self.assertTrue(any(c.startswith("RN19") for c in codigos_com))
        self.assertFalse(any(c.startswith("RN19") for c in codigos_sem))

    def test_erros_da_rn19_respeitam_o_contrato_rn17(self):
        from nfe_validator.nucleo.validador import ORIGENS_VALIDAS
        resultado = validar(_nota("<ICMS><ICMS00><orig>0</orig><CST>00</CST></ICMS00></ICMS>"))
        rn19 = [e for e in resultado["erros"] if e["codigo"].startswith("RN19")]
        self.assertTrue(rn19)
        for erro in rn19:
            self.assertIn(erro["origem"], ORIGENS_VALIDAS)
            self.assertEqual(erro["subOrigem"], "obrigatorio-condicional")
            self.assertTrue(erro["mensagem"])

    def test_explicacao_mais_rica_sobrevive_a_deduplicacao(self):
        """Quando o XSD e a RN19 acham o mesmo campo faltante, quem fica é a
        mensagem que explica o gatilho — mesmo que o XSD tenha sido anexado
        primeiro."""
        from nfe_validator.nucleo.validador import _deduplicar, _riqueza
        pobre = {"codigo": "XSD-X", "campo": "vBC", "xpath": "/a/vBC",
                 "detalhe": {"tagXml": "vBC", "tipoViolacao": "t"}}
        rico = {"codigo": "RN19-X", "campo": "vBC", "xpath": "/a/vBC",
                "detalhe": {"tagXml": "vBC", "tipoViolacao": "t",
                            "gatilho": " porque o grupo é <ICMS00>",
                            "fonte": "catalogo", "onde": "Item 1"}}
        self.assertGreater(_riqueza(rico), _riqueza(pobre))
        self.assertEqual([e["codigo"] for e in _deduplicar([pobre, rico])], ["RN19-X"])

    def test_degrada_sem_modelo_de_leiaute(self):
        """Sem XSD instalado a regra devolve lista vazia, não um erro."""
        arvore = parsear_xml(_nota(ICMS00_COMPLETO))
        self.assertEqual(
            validar_obrigatorios_condicionais(arvore, "NFe", "9.99"), []
        )

    def test_nota_sem_infnfe_nao_estoura(self):
        arvore = parsear_xml('<outra xmlns="urn:x"><a>1</a></outra>')
        self.assertEqual(validar_obrigatorios_condicionais(arvore), [])


if __name__ == "__main__":
    unittest.main()
