"""
Testes automatizados com unittest (sem dependências externas, já que o
ambiente pode não ter pytest instalado). Rodar com:

    python3 -m unittest discover -s tests -p "test_*.py" -v
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from nfe_validator.regras.chave_acesso import calcular_dv_modulo11, validar_chave_acesso
from nfe_validator.regras.documento_fiscal import cnpj_valido, cpf_valido, validar_documentos
from nfe_validator.regras.totais import validar_totais
from nfe_validator.regras.datas import validar_data
from nfe_validator.parser import parsear_xml, identificar_documento, XmlMalformado
from nfe_validator.validador import validar


class TesteChaveAcesso(unittest.TestCase):
    def test_dv_correto_nao_gera_erro(self):
        corpo = "3526011234567800019955001000000123100000123"
        dv = calcular_dv_modulo11(corpo)
        chave = corpo + str(dv)
        erros = validar_chave_acesso(
            chave,
            {"mod": "55", "serie": "1", "nNF": "123"},
            {"CNPJ": "12345678000199"},
        )
        # não deve haver erro de DV (RN08-DV)
        self.assertFalse(any(e["codigo"] == "RN08-DV" for e in erros))

    def test_dv_incorreto_gera_erro(self):
        chave = "3" * 44  # DV certamente errado
        erros = validar_chave_acesso(chave, {}, {})
        self.assertTrue(any(e["codigo"] == "RN08-DV" for e in erros))

    def test_tamanho_invalido(self):
        erros = validar_chave_acesso("123", {}, {})
        self.assertTrue(any(e["codigo"] == "RN08-TAMANHO" for e in erros))

    def test_chave_ausente(self):
        erros = validar_chave_acesso("", {}, {})
        self.assertTrue(any(e["codigo"] == "RN08-AUSENTE" for e in erros))


class TesteDocumentoFiscal(unittest.TestCase):
    def test_cnpj_valido_conhecido(self):
        # CNPJ de exemplo com DV matematicamente correto (fictício)
        self.assertTrue(cnpj_valido("11222333000181"))

    def test_cnpj_invalido(self):
        self.assertFalse(cnpj_valido("11111111000100"))

    def test_cpf_valido_conhecido(self):
        self.assertTrue(cpf_valido("11144477735"))

    def test_cpf_invalido(self):
        self.assertFalse(cpf_valido("11111111111"))

    def test_validar_documentos_relata_grupo(self):
        erros = validar_documentos({"emit": {"CNPJ": "00000000000000"}})
        self.assertEqual(erros[0]["codigo"], "RN10-CNPJ")
        self.assertIn("emit", erros[0]["campo"])


class TesteTotais(unittest.TestCase):
    def test_totais_consistentes_sem_erro(self):
        erros = validar_totais(100.0, 100.0, 18.0, 18.0, 100.0, 100.0)
        self.assertEqual(erros, [])

    def test_vnf_inconsistente_gera_erro(self):
        erros = validar_totais(100.0, 100.0, 18.0, 18.0, 150.0, 100.0)
        self.assertTrue(any(e["codigo"] == "RN11-VNF" for e in erros))


class TesteDatas(unittest.TestCase):
    def test_data_valida(self):
        self.assertEqual(validar_data("2026-08-07T10:00:00-03:00", "ide/dhEmi"), [])

    def test_data_ausente(self):
        erros = validar_data("", "ide/dhEmi")
        self.assertEqual(erros[0]["codigo"], "RN12-AUSENTE")

    def test_data_formato_invalido(self):
        erros = validar_data("07/08/2026", "ide/dhEmi")
        self.assertEqual(erros[0]["codigo"], "RN12-FORMATO")


class TesteParser(unittest.TestCase):
    def test_xml_malformado_levanta_excecao(self):
        with self.assertRaises(XmlMalformado):
            parsear_xml("<NFe><infNFe></NFe>")  # tag não fechada corretamente

    def test_identifica_nfe_e_versao(self):
        xml = (
            '<NFe xmlns="http://www.portalfiscal.inf.br/nfe">'
            '<infNFe versao="4.00" Id="NFe1"><ide><mod>55</mod></ide></infNFe>'
            "</NFe>"
        )
        arvore = parsear_xml(xml)
        tipo, versao = identificar_documento(arvore)
        self.assertEqual(tipo, "NFe")
        self.assertEqual(versao, "4.00")


class TesteValidadorFimAFim(unittest.TestCase):
    def test_fixture_invalida_retorna_multiplos_erros_com_motivo(self):
        caminho = Path(__file__).parent / "fixtures" / "nfe_exemplo_invalida.xml"
        conteudo = caminho.read_text(encoding="utf-8")
        resultado = validar(conteudo)

        self.assertFalse(resultado["valido"])
        self.assertEqual(resultado["tipoDocumento"], "NFe")
        # cada erro deve ter uma explicação de negócio não vazia
        for erro in resultado["erros"]:
            self.assertTrue(erro["motivo_rejeicao"])


if __name__ == "__main__":
    unittest.main()
