"""
Testes dos documentos de serviço: eventos, consultas, inutilização, retornos.

O que está sob teste aqui é o ROTEAMENTO. Antes, todo XML que não fosse uma
nota morria em `identificar_documento` com "Não foi encontrado o elemento
<infNFe>", e um cancelamento - o arquivo que o pessoal do fiscal mais mexe
depois da autorização - não recebia validação estrutural nenhuma.

As fixtures são XMLs montados à mão a partir dos XSDs oficiais, com CNPJ e
chave fictícios. As "válidas" passam pelo XSD de verdade: se um dia o schema
mudar de forma incompatível, elas quebram e é isso que se quer saber.

Rodar com:
    python -m unittest discover -s tests -p "test_*.py" -v
"""

import unittest
from pathlib import Path

from nfe_validator.nucleo import schema, servicos
from nfe_validator.nucleo.validador import validar

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _validar(nome: str) -> dict:
    return validar((FIXTURES / nome).read_text(encoding="utf-8"))


class TesteRoteamentoPorRaiz(unittest.TestCase):
    """Cada família é reconhecida pela raiz e ganha o rótulo e a versão certos."""

    CASOS = [
        # arquivo, rótulo esperado, versão esperada
        ("evento_cancelamento_valido.xml", "Evento", "1.00"),
        ("consulta_situacao_valida.xml", "ConsultaSituacao", "4.00"),
        ("consulta_cadastro_valida.xml", "ConsultaCadastro", "2.00"),
        ("inutilizacao_valida.xml", "Inutilizacao", "4.00"),
        ("retorno_lote_valido.xml", "RetornoLote", "4.00"),
        ("retorno_recibo_valido.xml", "RetornoRecibo", "4.00"),
        ("resumo_nfe_valido.xml", "ResumoNFe", "1.01"),
        ("distribuicao_dfe_valida.xml", "DistribuicaoDFe", "1.01"),
    ]

    def test_reconhece_familia_e_versao(self):
        for arquivo, rotulo, versao in self.CASOS:
            with self.subTest(arquivo=arquivo):
                r = _validar(arquivo)
                self.assertEqual(r["tipoDocumento"], rotulo)
                self.assertEqual(r["versaoLayout"], versao)

    def test_nao_reclama_de_infNFe_ausente(self):
        """A regressão que motivou o módulo.

        Um evento não tem <infNFe> e nunca teve. A mensagem antiga mandava o
        usuário "verificar se o arquivo é realmente uma NF-e" - culpando o
        arquivo por não ser algo que ele nunca se propôs a ser.
        """
        for arquivo, _, _ in self.CASOS:
            with self.subTest(arquivo=arquivo):
                r = _validar(arquivo)
                codigos = [e["codigo"] for e in r["erros"]]
                self.assertNotIn("IDENTIFICACAO-FALHOU", codigos)
                for erro in r["erros"]:
                    self.assertNotIn("infNFe", erro.get("mensagem_tecnica") or "")

    def test_todas_as_fixtures_validas_passam_pelo_xsd(self):
        """Prova que o XSD foi realmente aplicado, não silenciosamente pulado."""
        for arquivo, _, _ in self.CASOS:
            with self.subTest(arquivo=arquivo):
                r = _validar(arquivo)
                self.assertTrue(r["resumo"]["xsdAplicado"],
                                "XSD não foi aplicado - schema não encontrado?")
                self.assertEqual(r["erros"], [])
                self.assertTrue(r["valido"])


class TesteEventoRejeitado(unittest.TestCase):
    """Achar o erro é metade; explicar por que a SEFAZ rejeita é a outra."""

    def setUp(self):
        self.resultado = _validar("evento_cancelamento_invalido.xml")

    def test_reprova_e_aponta_o_campo(self):
        self.assertFalse(self.resultado["valido"])
        campos = {e["campo"] for e in self.resultado["erros"]}
        self.assertIn("cOrgao", campos)

    def test_erro_traz_xpath_linha_e_valores_aceitos(self):
        """RN07: xpath + linha + mensagem original, mais a orientação."""
        erro = next(e for e in self.resultado["erros"] if e["campo"] == "cOrgao")
        self.assertTrue(erro["xpath"].startswith("/procEventoNFe/"))
        self.assertIsNotNone(erro["linha"])
        self.assertIn("99", erro["motivo_rejeicao"])
        # A lista de valores aceitos é o que transforma "valor inválido" em
        # algo acionável - foi por ela que a classificação de facets existe.
        # A orientação mostra os primeiros e diz quantos ficaram de fora, em vez
        # de despejar as 30 UFs; a lista completa fica na mensagem técnica.
        corrigir = erro["detalhe"]["comoCorrigir"]
        self.assertIn("11", corrigir)
        self.assertIn("valores", corrigir)
        self.assertIn("'35'", erro["mensagem_tecnica"])

    def test_erro_de_schema_tem_origem_xsd(self):
        """RN17: o contrato de `origem` não muda por ser documento de serviço."""
        for erro in self.resultado["erros"]:
            self.assertEqual(erro["origem"], "xsd")
            self.assertEqual(erro["subOrigem"], "schema")


class TesteChaveReferenciada(unittest.TestCase):
    """O cabeçalho mostra a chave da nota de que o documento fala."""

    CHAVE = "35240112345678000199550010000000011234567890"

    def test_evento_expoe_a_chave_da_nota_cancelada(self):
        self.assertEqual(_validar("evento_cancelamento_valido.xml")["chaveAcesso"],
                         self.CHAVE)

    def test_consulta_situacao_expoe_a_chave_consultada(self):
        self.assertEqual(_validar("consulta_situacao_valida.xml")["chaveAcesso"],
                         self.CHAVE)

    def test_documento_sem_chave_nao_inventa_uma(self):
        """Inutilização e consulta cadastro não falam de uma nota específica."""
        self.assertIsNone(_validar("inutilizacao_valida.xml")["chaveAcesso"])
        self.assertIsNone(_validar("consulta_cadastro_valida.xml")["chaveAcesso"])

    def test_resumo_de_nota_de_terceiro_expoe_a_chave(self):
        """O resumo do distribuiçãoDFe é sobre uma nota, e traz a chave dela."""
        self.assertEqual(_validar("resumo_nfe_valido.xml")["chaveAcesso"], self.CHAVE)

    def test_lote_com_varias_notas_nao_escolhe_uma(self):
        """Com mais de uma chave, `None` é honesto e a primeira seria mentira.

        O retorno de um lote traz um <protNFe> por nota. Apontar a primeira no
        cabeçalho faria o relatório parecer ser sobre aquela nota.
        """
        base = (FIXTURES / "retorno_recibo_valido.xml").read_text(encoding="utf-8")
        # Duplica o bloco <protNFe> trocando a chave, para virar um lote de duas.
        inicio = base.index("<protNFe")
        fim = base.index("</protNFe>") + len("</protNFe>")
        bloco = base[inicio:fim]
        outra = bloco.replace(self.CHAVE, "35240112345678000199550010000000029999999999")
        duas = base[:fim] + "\n  " + outra + base[fim:]

        resultado = validar(duas)
        self.assertTrue(resultado["resumo"]["xsdAplicado"])
        self.assertIsNone(resultado["chaveAcesso"])


class TesteVersaoAusente(unittest.TestCase):
    """RN15: sem versão declarada, falhar explicitamente em vez de chutar."""

    def test_raiz_sem_versao_e_erro_explicado(self):
        xml = ('<?xml version="1.0" encoding="UTF-8"?>'
               '<consSitNFe xmlns="http://www.portalfiscal.inf.br/nfe">'
               '<tpAmb>2</tpAmb><xServ>CONSULTAR</xServ>'
               '<chNFe>35240112345678000199550010000000011234567890</chNFe>'
               '</consSitNFe>')
        r = validar(xml)

        self.assertFalse(r["valido"])
        self.assertFalse(r["resumo"]["xsdAplicado"])
        # A família foi reconhecida: o problema é só a versão.
        self.assertEqual(r["tipoDocumento"], "ConsultaSituacao")
        self.assertIsNone(r["versaoLayout"])

        erro = r["erros"][0]
        self.assertEqual(erro["codigo"], "IDENTIFICACAO-FALHOU")
        self.assertEqual(erro["campo"], "versao")
        self.assertIn("versao", erro["motivo_rejeicao"])


class TesteSemXsd(unittest.TestCase):
    """Sem schema instalado, um evento não pode ser declarado válido.

    Na nota, `aplicar_xsd=False` ainda deixa as regras de negócio rodando, e
    elas sustentam um veredito. Num evento não sobra conferência nenhuma -
    dizer "válido" ali seria afirmar algo que não foi verificado.
    """

    def test_sem_xsd_nao_declara_valido_e_avisa(self):
        conteudo = (FIXTURES / "evento_cancelamento_valido.xml").read_text(encoding="utf-8")
        r = validar(conteudo, aplicar_xsd=False)

        self.assertFalse(r["valido"])
        self.assertFalse(r["resumo"]["xsdAplicado"])
        self.assertEqual(r["erros"], [])

    def test_versao_nao_instalada_avisa_em_vez_de_validar_contra_outra(self):
        """RN15: versão 9.99 não existe, e não pode cair na 1.00."""
        conteudo = (FIXTURES / "evento_cancelamento_valido.xml").read_text(encoding="utf-8")
        r = validar(conteudo.replace('<procEventoNFe xmlns="http://www.portalfiscal.inf.br/nfe" versao="1.00">',
                                     '<procEventoNFe xmlns="http://www.portalfiscal.inf.br/nfe" versao="9.99">'))

        self.assertFalse(r["resumo"]["xsdAplicado"])
        self.assertFalse(r["valido"])
        self.assertEqual([a["codigo"] for a in r["avisos"]], ["XSD-INDISPONIVEL"])
        self.assertIn("9.99", r["avisos"][0]["motivo_rejeicao"])


class TesteMensagemFalaDoDocumentoCerto(unittest.TestCase):
    """Duas coisas que estavam erradas para tudo que não é nota."""

    def setUp(self):
        self.evento = _validar("evento_cancelamento_invalido.xml")
        self.erro = next(e for e in self.evento["erros"] if e["campo"] == "cOrgao")

    def test_descricao_vem_do_leiaute_da_familia(self):
        """`cOrgao` não existe no leiauteNFe - a descrição tem que sair do
        leiauteEvento, ou o erro cai no texto genérico.

        A frase é citada entre aspas de propósito: quem lê precisa saber que é
        texto da SEFAZ, não nosso (RN07).
        """
        por_que = self.erro["detalhe"]["porQueRejeita"]
        self.assertIn("órgão de recepção do Evento", por_que)
        self.assertEqual(self.erro["detalhe"]["fonte"], "xsd")

    def test_nao_diz_que_a_sefaz_rejeita_a_nota(self):
        """O documento é um evento; chamá-lo de "nota" confunde quem lê."""
        for erro in self.evento["erros"]:
            texto = erro["motivo_rejeicao"]
            self.assertIn("o evento", texto)
            self.assertNotIn("rejeita a nota", texto)
            self.assertNotIn("processar a nota", texto)

    def test_cada_familia_usa_o_proprio_substantivo(self):
        # tpNF só aceita 0 e 1: força um erro de enumeração no resumo.
        conteudo = (FIXTURES / "resumo_nfe_valido.xml").read_text(encoding="utf-8")
        r = validar(conteudo.replace("<tpNF>1</tpNF>", "<tpNF>9</tpNF>"))
        self.assertIn("processar o resumo", r["erros"][0]["motivo_rejeicao"])

    def test_a_nota_continua_dizendo_nota(self):
        """A correção não pode ter regredido o caminho principal."""
        conteudo = (FIXTURES / "nfe_exemplo_invalida.xml").read_text(encoding="utf-8")
        textos = " ".join(e["motivo_rejeicao"] for e in validar(conteudo)["erros"])
        self.assertIn("a nota", textos)
        self.assertNotIn("o evento", textos)


class TesteRegistroDeServicos(unittest.TestCase):
    """O registro e os XSDs instalados têm que continuar batendo."""

    # Raiz -> versão em que ela está instalada. Se um dia entrar uma versão
    # nova, este mapa muda junto com a pasta - é o ponto onde a RN14 aparece.
    VERSAO_INSTALADA = {
        "envEvento": "1.00", "retEnvEvento": "1.00", "procEventoNFe": "1.00",
        "consSitNFe": "4.00", "retConsSitNFe": "4.00",
        "ProcInutNFe": "4.00",
        "ConsCad": "2.00", "retConsCad": "2.00",
        "retEnviNFe": "4.00", "retConsReciNFe": "4.00",
        "distDFeInt": "1.01", "retDistDFeInt": "1.01",
        "resNFe": "1.01", "resEvento": "1.01",
    }

    def test_toda_raiz_do_registro_tem_xsd_instalado(self):
        self.assertEqual(set(servicos.SERVICOS), set(self.VERSAO_INSTALADA),
                         "registro e mapa de versões saíram de sincronia")
        for raiz, versao in self.VERSAO_INSTALADA.items():
            with self.subTest(raiz=raiz):
                caminho = schema.caminho_schema(
                    servicos.SERVICOS[raiz].tipo, versao, raiz)
                self.assertTrue(caminho.exists(), f"XSD ausente: {caminho}")

    def test_todo_xsd_de_servico_compila(self):
        """Um `xs:include` quebrado só aparece na hora de compilar."""
        for raiz, versao in self.VERSAO_INSTALADA.items():
            with self.subTest(raiz=raiz):
                schema.carregar_schema(servicos.SERVICOS[raiz].tipo, versao, raiz)

    def test_raizes_que_contem_nota_ficam_fora_do_registro(self):
        """`enviNFe` e `nfeProc` trazem uma nota dentro.

        Se caíssem no registro, o documento seria validado só estruturalmente e
        a nota lá dentro perderia as regras de negócio - RN08..RN12, RN18, RN19.
        """
        self.assertNotIn("enviNFe", servicos.SERVICOS)
        self.assertNotIn("nfeProc", servicos.SERVICOS)
        self.assertIn("enviNFe", schema.ENTRADA_POR_RAIZ)
        self.assertIn("nfeProc", schema.ENTRADA_POR_RAIZ)

    def test_nota_e_envelopes_nao_sao_confundidos_com_servico(self):
        from nfe_validator.nucleo import parser
        conteudo = (FIXTURES / "nfe_exemplo_invalida.xml").read_text(encoding="utf-8")
        self.assertIsNone(servicos.identificar(parser.parsear_xml(conteudo)))


if __name__ == "__main__":
    unittest.main()
