"""
Testes do modelo de leiaute derivado do XSD (`nfe_validator/layout.py`).

Divididos em dois grupos, de propósito:

  * testes de LÓGICA, contra XSDs sintéticos montados no próprio teste. São
    rápidos e é onde o parser é realmente verificado.
  * testes de CONTRATO, contra o XSD oficial de 352 KB em `schemas/`. Pulam
    sozinhos se o XSD não estiver instalado. Fixam os fatos que o resto do
    sistema passa a assumir (ICMS00 exige vBC, CST 20 é ambíguo, etc.) — se a
    SEFAZ mudar o leiaute, é aqui que aparece.

Rodar com:
    python -m unittest discover -s tests -p "test_*.py" -v
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lxml import etree

from nfe_validator.nucleo import layout
from nfe_validator.nucleo.layout import (
    LIMITE_TEXTO_SUBSTANTIVO,
    _analisar_conteudo,
    _e_choice_de_variantes,
    _modelo_de_conteudo,
    limpar_documentacao,
)

XS = "{http://www.w3.org/2001/XMLSchema}"


def _complextype(xml_do_complextype: str):
    """Parseia um trecho de XSD e devolve o nó xs:complexType."""
    doc = etree.fromstring(
        '<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema">'
        + xml_do_complextype
        + "</xs:schema>"
    )
    return doc.find(f"{XS}complexType")


def _analisar(xml_do_complextype: str):
    return _analisar_conteudo(_complextype(xml_do_complextype), "sintetico.xsd", {})


NS_NFE = "http://www.portalfiscal.inf.br/nfe"
_ESQUEMAS_DE_VARIANTE: dict[str, object] = {}


def _esquema_da_variante(nome: str):
    """Promove uma variante local (ICMS00, PISAliq...) a elemento GLOBAL num
    schema que inclui o leiaute oficial, para poder validar o fragmento
    isoladamente com o libxml2.

    É o que permite perguntar ao libxml2 "este ICMS00 é válido?" sem montar
    uma NF-e inteira — e sem tocar em nada dentro de `schemas/`."""
    if nome in _ESQUEMAS_DE_VARIANTE:
        return _ESQUEMAS_DE_VARIANTE[nome]

    import copy as _copy
    from nfe_validator.nucleo.schema import caminho_schema

    leiaute = caminho_schema("NFe", "4.00").parent / "leiauteNFe_v4.00.xsd"
    arvore = etree.parse(str(leiaute))
    raiz = arvore.getroot()
    alvo = next(e for e in arvore.iter(f"{XS}element") if e.get("name") == nome)

    # O nsmap tem que ser preservado: `type="Torig"` é um QName sem prefixo,
    # resolvido pelo namespace DEFAULT do documento.
    sintetico = etree.Element(f"{XS}schema", dict(raiz.attrib), nsmap=raiz.nsmap)
    include = etree.SubElement(sintetico, f"{XS}include")
    include.set("schemaLocation", leiaute.name)
    sintetico.append(_copy.deepcopy(alvo))

    # O base_url precisa ser um nome DIFERENTE na mesma pasta: com o mesmo
    # nome, o libxml2 acusa "the schema must not include itself".
    documento = etree.fromstring(
        etree.tostring(sintetico),
        base_url=str(leiaute.parent / f"_teste_{nome}.xsd"),
    )
    esquema = etree.XMLSchema(documento.getroottree())
    _ESQUEMAS_DE_VARIANTE[nome] = esquema
    return esquema


def _validar_variante(nome: str, campos: list[tuple[str, str]]) -> bool:
    """Pergunta ao libxml2 se esse conjunto de campos forma uma variante válida."""
    corpo = "".join(f"<{tag}>{valor}</{tag}>" for tag, valor in campos)
    fragmento = f'<{nome} xmlns="{NS_NFE}">{corpo}</{nome}>'
    documento = etree.fromstring(fragmento.encode()).getroottree()
    return bool(_esquema_da_variante(nome).validate(documento))


class TesteLimpezaDeDocumentacao(unittest.TestCase):
    """A RN07 proíbe reescrever a regra oficial. Aqui garantimos que a única
    transformação é de whitespace."""

    def test_normaliza_whitespace_sem_alterar_o_texto(self):
        texto, integral, legendas = limpar_documentacao(
            "\t\tValor da BC do ICMS\r\n\r\n   com   espacos  \n"
        )
        self.assertEqual(texto, "Valor da BC do ICMS com espacos")
        self.assertEqual(integral, "Valor da BC do ICMS\ncom espacos")
        self.assertEqual(legendas, ())

    def test_typos_da_sefaz_sao_preservados(self):
        """'Tributção' e 'Não tributda' existem no XSD oficial. Corrigir seria
        reescrever a regra — a RN07 não permite."""
        texto, _, _ = limpar_documentacao("Tributção pelo ICMS\nNão tributda (v.2.0)")
        self.assertIn("Tributção", texto)
        self.assertIn("Não tributda", texto)
        self.assertIn("(v.2.0)", texto)

    def test_extrai_legendas_de_enumeracao(self):
        _, _, legendas = limpar_documentacao(
            "Modalidade de determinação da BC do ICMS:\n"
            "0 - Margem Valor Agregado (%);\n"
            "1 - Pauta (valor);\n"
            "3 - Valor da Operação."
        )
        self.assertEqual(len(legendas), 3)
        self.assertIn("0 - Margem Valor Agregado (%);", legendas)

    def test_linha_de_prosa_nao_e_confundida_com_legenda(self):
        """'Modalidade de determinação da BC do ICMS:' não é uma legenda."""
        _, _, legendas = limpar_documentacao("Modalidade de determinação da BC do ICMS:")
        self.assertEqual(legendas, ())

    def test_documentacao_vazia_ou_ausente(self):
        self.assertEqual(limpar_documentacao(None), ("", "", ()))
        self.assertEqual(limpar_documentacao("   \n\t "), ("", "", ()))


class TesteHeuristicaDeChoice(unittest.TestCase):
    """`_e_choice_de_variantes` é o ponto mais frágil do parser: um choice pode
    ser "escolha de grupo inteiro" (ICMS) ou "escolha de campo" (CNPJ|CPF).
    Confundir os dois faz o modelo perder variantes ou inventar campos."""

    def test_choice_de_grupos_e_variante(self):
        no = _complextype(
            '<xs:complexType><xs:choice>'
            '<xs:element name="ICMS00"><xs:complexType><xs:sequence>'
            '<xs:element name="vBC"/></xs:sequence></xs:complexType></xs:element>'
            '<xs:element name="ICMS40"><xs:complexType><xs:sequence>'
            '<xs:element name="CST"/></xs:sequence></xs:complexType></xs:element>'
            "</xs:choice></xs:complexType>"
        )
        self.assertTrue(_e_choice_de_variantes(_modelo_de_conteudo(no)))

    def test_choice_de_campos_simples_e_alternativa(self):
        """emit: CNPJ | CPF. São campos, não grupos."""
        no = _complextype(
            '<xs:complexType><xs:choice>'
            '<xs:element name="CNPJ" type="xs:string"/>'
            '<xs:element name="CPF" type="xs:string"/>'
            "</xs:choice></xs:complexType>"
        )
        self.assertFalse(_e_choice_de_variantes(_modelo_de_conteudo(no)))

    def test_choice_de_sequences_e_alternativa(self):
        """IPITrib: (vBC, pIPI) | (qUnid, vUnid)."""
        no = _complextype(
            '<xs:complexType><xs:sequence><xs:choice>'
            '<xs:sequence><xs:element name="vBC"/><xs:element name="pIPI"/></xs:sequence>'
            '<xs:sequence><xs:element name="qUnid"/><xs:element name="vUnid"/></xs:sequence>'
            "</xs:choice></xs:sequence></xs:complexType>"
        )
        campos, variantes, _, alternativas = _analisar(
            '<xs:complexType><xs:sequence><xs:choice>'
            '<xs:sequence><xs:element name="vBC"/><xs:element name="pIPI"/></xs:sequence>'
            '<xs:sequence><xs:element name="qUnid"/><xs:element name="vUnid"/></xs:sequence>'
            "</xs:choice></xs:sequence></xs:complexType>"
        )
        self.assertEqual(variantes, ())
        self.assertEqual([a.campos for a in alternativas],
                         [("vBC", "pIPI"), ("qUnid", "vUnid")])
        # Nada dentro de um choice pode ser exigido incondicionalmente.
        self.assertEqual([c.nome for c in campos if c.obrigatorio], [])


class TesteRegraDeCampoDireto(unittest.TestCase):
    """A definição de "campo direto obrigatório": sem minOccurs, sem ancestral
    opcional dentro do grupo, e fora de qualquer choice."""

    def test_obrigatorio_e_a_ausencia_de_minoccurs(self):
        campos, _, _, _ = _analisar(
            '<xs:complexType><xs:sequence>'
            '<xs:element name="obrigatorio"/>'
            '<xs:element name="opcional" minOccurs="0"/>'
            "</xs:sequence></xs:complexType>"
        )
        por_nome = {c.nome: c.obrigatorio for c in campos}
        self.assertTrue(por_nome["obrigatorio"])
        self.assertFalse(por_nome["opcional"])

    def test_sequence_opcional_torna_os_filhos_opcionais(self):
        campos, _, todos, _ = _analisar(
            '<xs:complexType><xs:sequence>'
            '<xs:element name="sempre"/>'
            '<xs:sequence minOccurs="0">'
            '<xs:element name="pFCP"/><xs:element name="vFCP"/>'
            "</xs:sequence></xs:sequence></xs:complexType>"
        )
        por_nome = {c.nome: c.obrigatorio for c in campos}
        self.assertTrue(por_nome["sempre"])
        self.assertFalse(por_nome["pFCP"], "dentro de sequence minOccurs=0 não é obrigatório")
        self.assertFalse(por_nome["vFCP"])
        # ...mas os dois formam um grupo tudo-ou-nada.
        self.assertEqual([g.campos for g in todos], [("pFCP", "vFCP")])

    def test_grupo_tudo_ou_nada_separa_os_opcionais_internos(self):
        _, _, todos, _ = _analisar(
            '<xs:complexType><xs:sequence>'
            '<xs:sequence minOccurs="0">'
            '<xs:element name="vICMSDeson"/>'
            '<xs:element name="motDesICMS"/>'
            '<xs:element name="indDeduzDeson" minOccurs="0"/>'
            "</xs:sequence></xs:sequence></xs:complexType>"
        )
        self.assertEqual(len(todos), 1)
        self.assertEqual(todos[0].campos, ("vICMSDeson", "motDesICMS"))
        self.assertEqual(todos[0].opcionais_internos, ("indDeduzDeson",))

    def test_campo_opcional_isolado_nao_e_grupo_tudo_ou_nada(self):
        """Um `sequence minOccurs=0` com um só campo exigido é apenas um campo
        opcional — chamar isso de "tudo ou nada" geraria erro sem sentido."""
        _, _, todos, _ = _analisar(
            '<xs:complexType><xs:sequence>'
            '<xs:sequence minOccurs="0"><xs:element name="unico"/></xs:sequence>'
            "</xs:sequence></xs:complexType>"
        )
        self.assertEqual(todos, ())

    def test_nao_desce_no_complextype_de_um_filho(self):
        """`prod` é campo de `det`, mas os campos de `prod` não são de `det`."""
        campos, _, _, _ = _analisar(
            '<xs:complexType><xs:sequence>'
            '<xs:element name="prod"><xs:complexType><xs:sequence>'
            '<xs:element name="cProd"/></xs:sequence></xs:complexType></xs:element>'
            "</xs:sequence></xs:complexType>"
        )
        self.assertEqual([c.nome for c in campos], ["prod"])

    def test_variante_na_raiz_do_complextype(self):
        """Regressão: quando o choice de variantes é a RAIZ do complexType — o
        caso do ICMS — as 21 variantes passavam batido."""
        campos, variantes, _, _ = _analisar(
            '<xs:complexType><xs:choice>'
            '<xs:element name="ICMS00"><xs:complexType><xs:sequence>'
            '<xs:element name="vBC"/></xs:sequence></xs:complexType></xs:element>'
            '<xs:element name="ICMS40"><xs:complexType><xs:sequence>'
            '<xs:element name="CST"/></xs:sequence></xs:complexType></xs:element>'
            "</xs:choice></xs:complexType>"
        )
        self.assertEqual(variantes, ("ICMS00", "ICMS40"))
        self.assertEqual(campos, (), "os campos pertencem à variante, não ao grupo pai")


class TesteDegradacao(unittest.TestCase):
    """A camada de leiaute nunca pode ser uma nova causa de falha."""

    def test_versao_inexistente_devolve_none_sem_levantar(self):
        self.assertIsNone(layout.carregar_modelo("NFe", "9.99"))
        self.assertFalse(layout.disponivel("NFe", "9.99"))

    def test_consultas_com_modelo_ausente_devolvem_vazio(self):
        self.assertIsNone(layout.descricao_do_campo("vBC", "ICMS00", versao="9.99"))
        self.assertEqual(layout.campos_obrigatorios_de("ICMS00", versao="9.99"), ())
        self.assertEqual(layout.variantes_de("ICMS", versao="9.99"), ())
        self.assertIsNone(layout.variante_para_cst("ICMS", "00", versao="9.99"))
        self.assertEqual(layout.legenda_de_valores("orig", "ICMS00", versao="9.99"), "")

    def test_grupo_desconhecido_nao_estoura(self):
        self.assertEqual(layout.campos_obrigatorios_de("GrupoQueNaoExiste"), ())
        self.assertEqual(layout.grupos_todos_ou_nada("GrupoQueNaoExiste"), ())
        self.assertIsNone(layout.variante_do_elemento("GrupoQueNaoExiste"))


@unittest.skipUnless(layout.disponivel(), "XSD oficial de NF-e não instalado")
class TesteContratoComXsdOficial(unittest.TestCase):
    """Fixa o que o resto do sistema passa a assumir sobre o leiaute oficial."""

    @classmethod
    def setUpClass(cls):
        cls.modelo = layout.carregar_modelo()

    # --- obrigatoriedade por variante -------------------------------------
    def test_campos_exigidos_por_icms00(self):
        self.assertEqual(
            layout.campos_obrigatorios_de("ICMS00"),
            ("orig", "CST", "modBC", "vBC", "pICMS", "vICMS"),
        )

    def test_icms20_exige_predbc_alem_do_que_icms00_exige(self):
        icms00 = set(layout.campos_obrigatorios_de("ICMS00"))
        icms20 = set(layout.campos_obrigatorios_de("ICMS20"))
        self.assertEqual(icms20 - icms00, {"pRedBC"})

    def test_icmssn102_exige_apenas_csosn(self):
        """`orig` é declarado com minOccurs="0" em ICMSSN102 (leiauteNFe:3943).
        Este teste existe porque é contraintuitivo — em toda variante de ICMS
        "normal" o orig é obrigatório — e é o tipo de detalhe que uma tabela
        escrita de memória erraria."""
        self.assertEqual(layout.campos_obrigatorios_de("ICMSSN102"), ("CSOSN",))

    def test_grupos_tudo_ou_nada_do_fcp(self):
        self.assertEqual(
            [g.campos for g in layout.grupos_todos_ou_nada("ICMS00")],
            [("pFCP", "vFCP")],
        )
        grupos20 = {g.campos: g for g in layout.grupos_todos_ou_nada("ICMS20")}
        self.assertIn(("vBCFCP", "pFCP", "vFCP"), grupos20)
        self.assertIn(("vICMSDeson", "motDesICMS"), grupos20)
        self.assertEqual(
            grupos20[("vICMSDeson", "motDesICMS")].opcionais_internos,
            ("indDeduzDeson",),
        )

    def test_alternativa_xor_do_ipi(self):
        self.assertEqual(
            [a.campos for a in layout.alternativas_de("IPITrib")],
            [("vBC", "pIPI"), ("qUnid", "vUnid")],
        )

    # --- variantes e CST ---------------------------------------------------
    def test_icms_tem_as_21_variantes_do_choice(self):
        nomes = {v.nome for v in layout.variantes_de("ICMS")}
        self.assertEqual(len(nomes), 21)
        for esperado in ("ICMS00", "ICMS20", "ICMS40", "ICMSPart", "ICMSST",
                         "ICMSSN101", "ICMSSN102", "ICMSSN900"):
            self.assertIn(esperado, nomes)

    def test_pis_e_cofins_tem_quatro_variantes(self):
        self.assertEqual(len(layout.variantes_de("PIS")), 4)
        self.assertEqual(len(layout.variantes_de("COFINS")), 4)

    def test_cst_unico_resolve_a_variante(self):
        self.assertEqual(layout.variante_para_cst("ICMS", "00").nome, "ICMS00")
        self.assertEqual(layout.variante_para_cst("ICMS", "102").nome, "ICMSSN102")

    def test_cst_ambiguo_nao_e_desempatado_por_chute(self):
        """CST 20 é enumerado em ICMS20 (leiauteNFe:2503) E em ICMSPart
        (:3641). Escolher um seria inventar regra — a RN05 proíbe."""
        self.assertIsNone(layout.variante_para_cst("ICMS", "20"))
        candidatos = {v.nome for v in layout.variantes_para_cst("ICMS", "20")}
        self.assertEqual(candidatos, {"ICMS20", "ICMSPart"})

    def test_variante_e_resolvida_pelo_elemento_presente(self):
        """O caminho confiável: ler qual variante o XML abriu. É o que a
        validação tem que usar, já que 5 CSTs do ICMS são ambíguos."""
        variante = layout.variante_do_elemento("ICMSPart")
        self.assertEqual(variante.grupo, "ICMS")
        self.assertIn("pBCOp", variante.obrigatorios)

    # --- descrições oficiais ----------------------------------------------
    def test_descricao_literal_do_vbc_do_icms(self):
        self.assertEqual(
            layout.descricao_do_campo("vBC", "ICMS00").texto,
            "Valor da BC do ICMS",
        )

    def test_mesma_tag_em_grupos_diferentes_recebe_texto_diferente(self):
        self.assertEqual(layout.descricao_do_campo("vBC", "PISAliq").texto,
                         "Valor da BC do PIS")
        self.assertNotEqual(layout.descricao_do_campo("vBC", "ICMS00").texto,
                            layout.descricao_do_campo("vBC", "PISAliq").texto)

    def test_tag_ambigua_sem_contexto_devolve_none(self):
        """O pior modo de falha possível seria devolver a documentação do grupo
        errado com selo de "oficial". `vBC` existe em ICMS, IPI, PIS, COFINS e
        ICMSTot com textos diferentes — sem contexto, calamos."""
        self.assertIsNone(layout.descricao_do_campo("vBC"))

    def test_classifica_texto_substantivo_e_texto_de_rotulo(self):
        """O limiar é o que impede a integração de PIORAR mensagens: 'Cfop' é
        um bom nome de campo e uma péssima justificativa fiscal."""
        cfop = layout.descricao_do_campo("CFOP", "prod")
        self.assertEqual(cfop.texto, "Cfop")
        self.assertFalse(cfop.substantiva)
        self.assertTrue(cfop.serve_como_nome)

        ncm = layout.descricao_do_campo("NCM", "prod")
        self.assertTrue(ncm.substantiva)
        self.assertGreater(len(ncm.texto), LIMITE_TEXTO_SUBSTANTIVO)

    def test_toda_descricao_tem_origem_rastreavel(self):
        """RN05: se afirmamos algo "oficial", tem que dar para abrir o .xsd
        naquela linha e conferir."""
        for tag, ctx in (("vBC", "ICMS00"), ("NCM", "prod"), ("CFOP", "prod")):
            descricao = layout.descricao_do_campo(tag, ctx)
            self.assertIsNotNone(descricao.origem)
            self.assertTrue(descricao.origem.arquivo.endswith(".xsd"))
            self.assertIsInstance(descricao.origem.linha, int)

    # --- enumerações -------------------------------------------------------
    def test_enumeracao_do_cst_vem_com_o_rotulo_oficial(self):
        legenda = layout.legenda_de_valores("CST", "ICMS00")
        self.assertEqual(legenda, "00=Tributada integralmente")

    def test_enumeracao_com_legenda_multilinha(self):
        legenda = layout.legenda_de_valores("modBC", "ICMS00")
        self.assertIn("0=Margem Valor Agregado (%)", legenda)
        self.assertIn("3=Valor da Operação", legenda)

    def test_enumeracao_herdada_de_tipo_nomeado(self):
        """`orig` é `type="Torig"`: os valores vêm do tipo, os rótulos do
        elemento. A cobertura de rótulos é parcial porque a documentação da
        SEFAZ para `orig` para no valor 2 — e ficar parcial é o correto."""
        valores = layout.enumeracao_de("orig", "ICMS00")
        self.assertEqual(len(valores), 9)
        self.assertEqual([v.valor for v in valores], list("012345678"))
        self.assertTrue(any(v.rotulo for v in valores))

    def test_cobertura_de_documentacao_do_leiaute(self):
        """Guarda-corpo da premissa do projeto: se a cobertura despencar, a
        integração com o catálogo deixa de valer a pena."""
        tags = self.modelo.campos_por_tag
        com_descricao = sum(
            1 for ocorrencias in tags.values()
            if any(c.descricao for c in ocorrencias)
        )
        self.assertGreater(com_descricao / len(tags), 0.90)

    # --- concordância com o libxml2 ---------------------------------------
    def test_modelo_concorda_com_o_libxml2_sobre_icms00(self):
        """O teste mais valioso da suíte: valida a nossa leitura do XSD contra
        o veredito do PRÓPRIO libxml2, em vez de contra ela mesma.

        Se `campos_obrigatorios_de("ICMS00")` está certo, então um ICMS00 com
        exatamente esses campos é válido, e remover qualquer um deles o torna
        inválido. Quem responde isso é o libxml2, não o nosso parser.

        (Não dá para fazer esse teste com uma NF-e inteira: o libxml2 pararia
        no primeiro campo faltante de `ide` e nunca chegaria ao ICMS00 — que é
        exatamente a limitação que a RN18 e a RN19 existem para contornar.)"""
        exigidos = list(layout.campos_obrigatorios_de("ICMS00"))
        valores = {"orig": "0", "CST": "00", "modBC": "3", "vBC": "100.00",
                   "pICMS": "18.00", "vICMS": "18.00",
                   "pFCP": "2.00", "vFCP": "2.00"}
        completo = [(nome, valores[nome]) for nome in exigidos]

        self.assertTrue(
            _validar_variante("ICMS00", completo),
            f"o libxml2 deveria aceitar ICMS00 com exatamente {exigidos}",
        )
        for removido in exigidos:
            parcial = [par for par in completo if par[0] != removido]
            self.assertFalse(
                _validar_variante("ICMS00", parcial),
                f"o libxml2 aceitou ICMS00 sem '{removido}', que o modelo diz "
                "ser obrigatório",
            )

    def test_libxml2_confirma_a_semantica_do_grupo_tudo_ou_nada(self):
        """`pFCP` e `vFCP` são opcionais, mas não independentes: informar um
        sem o outro é inválido. É isso que `GrupoTodoOuNada` afirma."""
        completo = [("orig", "0"), ("CST", "00"), ("modBC", "3"),
                    ("vBC", "100.00"), ("pICMS", "18.00"), ("vICMS", "18.00")]
        grupo = layout.grupos_todos_ou_nada("ICMS00")[0]
        self.assertEqual(grupo.campos, ("pFCP", "vFCP"))

        self.assertTrue(_validar_variante("ICMS00", completo),
                        "sem o grupo opcional, deve ser válido")
        self.assertFalse(_validar_variante("ICMS00", completo + [("pFCP", "2.00")]),
                         "metade do grupo tudo-ou-nada deve ser inválido")
        self.assertTrue(
            _validar_variante("ICMS00", completo + [("pFCP", "2.00"), ("vFCP", "2.00")]),
            "o grupo completo deve ser válido",
        )


if __name__ == "__main__":
    unittest.main()
