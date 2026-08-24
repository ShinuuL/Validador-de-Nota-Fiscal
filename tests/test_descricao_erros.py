"""
Testes da melhoria de descrição de erros (v2):

  * classificação das mensagens cruas do libxml2 em tipos de violação
    específicos, em vez de cair tudo em "estrutura_inesperada";
  * composição da explicação em 4 camadas (onde / o que / por que / como),
    respeitando o TIPO real da violação mesmo para campo catalogado;
  * localização legível do erro (item, grupo, linha);
  * RN18 - varredura de campos obrigatórios não preenchidos, independente
    de XSD, distinguindo ausente / vazio / só espaços.

Rodar com:
    python -m unittest discover -s tests -p "test_*.py" -v
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from nfe_validator.catalogo_erros import DIAGNOSTICOS, montar_explicacao, explicar_campo
from nfe_validator.localizacao import localizar, caminho_legivel
from nfe_validator.parser import parsear_xml
from nfe_validator.regras.campos_obrigatorios import validar_campos_obrigatorios
from nfe_validator.schema import analisar_mensagem
from nfe_validator.validador import validar

NS = 'xmlns="http://www.portalfiscal.inf.br/nfe"'


def _nota(corpo_infnfe: str, chave: str = "1" * 44) -> str:
    return (
        f'<?xml version="1.0" encoding="UTF-8"?>\n<NFe {NS}>\n'
        f'  <infNFe versao="4.00" Id="NFe{chave}">\n{corpo_infnfe}\n  </infNFe>\n</NFe>\n'
    )


class TesteClassificacaoMensagemXsd(unittest.TestCase):
    """A mensagem crua do libxml2 tem que virar um tipo de violação preciso -
    é isso que diferencia 'campo vazio' de 'campo com valor inválido'."""

    def test_valor_vazio_e_reconhecido_como_vazio(self):
        a = analisar_mensagem(
            "Element '{http://x}vBC': '' is not a valid value of the atomic "
            "type '{http://x}TDec_1302'."
        )
        self.assertEqual(a["tipo_violacao"], "vazio")
        self.assertEqual(a["tag"], "vBC")

    def test_valor_so_com_espacos_nao_e_confundido_com_vazio(self):
        a = analisar_mensagem(
            "Element '{http://x}xNome': ' ' is not a valid value of the atomic "
            "type '{http://x}TString'."
        )
        self.assertEqual(a["tipo_violacao"], "so_espacos")

    def test_numero_mal_formatado_gera_dica_de_decimal(self):
        a = analisar_mensagem(
            "Element '{http://x}vProd': '1.234,56' is not a valid value of the "
            "atomic type '{http://x}TDec_1302'."
        )
        self.assertEqual(a["tipo_violacao"], "decimal_invalido")
        self.assertEqual(a["valor"], "1.234,56")

    def test_enumeracao_preserva_valores_aceitos(self):
        a = analisar_mensagem(
            "Element '{http://x}CST': [facet 'enumeration'] The value 'XX' is not "
            "an element of the set {'00', '10', '20'}."
        )
        self.assertEqual(a["tipo_violacao"], "fora_da_enumeracao")
        self.assertEqual(a["esperado"], "00, 10, 20")

    def test_pattern_preserva_a_mascara(self):
        a = analisar_mensagem(
            "Element '{http://x}CNPJ': [facet 'pattern'] The value '123' is not "
            "accepted by the pattern '[0-9]{14}'."
        )
        self.assertEqual(a["tipo_violacao"], "fora_do_padrao")
        self.assertIn("[0-9]{14}", a["esperado"])

    def test_missing_child_unico_aponta_o_campo_e_ancora_no_grupo(self):
        a = analisar_mensagem(
            "Element '{http://x}ICMS00': Missing child element(s). Expected is "
            "( {http://x}vBC )."
        )
        self.assertEqual(a["tipo_violacao"], "obrigatorio_ausente")
        self.assertEqual(a["tag"], "vBC")        # o campo que falta
        self.assertEqual(a["ancora"], "ICMS00")  # onde o libxml2 detectou

    def test_missing_child_com_varias_opcoes_vira_grupo_incompleto(self):
        a = analisar_mensagem(
            "Element '{http://x}ICMS': Missing child element(s). Expected is one of "
            "( {http://x}ICMS00, {http://x}ICMS10, {http://x}ICMS20 )."
        )
        self.assertEqual(a["tipo_violacao"], "grupo_incompleto")
        self.assertEqual(a["esperado"], "ICMS00, ICMS10, ICMS20")

    def test_enumeracao_gigante_e_truncada(self):
        conjunto = ", ".join(f"'{i:04d}'" for i in range(30))
        a = analisar_mensagem(
            f"Element '{{http://x}}CFOP': [facet 'enumeration'] The value '9999' is "
            f"not an element of the set {{{conjunto}}}."
        )
        self.assertIn("valores)", a["esperado"])
        self.assertLess(len(a["esperado"]), 200)

    def test_mensagem_irreconhecivel_nao_estoura(self):
        a = analisar_mensagem("algo totalmente inesperado do libxml2")
        self.assertEqual(a["tipo_violacao"], "estrutura_inesperada")
        self.assertEqual(a["tag"], "desconhecido")

    def test_todo_tipo_classificado_tem_diagnostico(self):
        """Nenhum tipo produzido pelo classificador pode ficar sem texto."""
        produzidos = {
            "vazio", "so_espacos", "decimal_invalido", "tipo_invalido",
            "fora_do_padrao", "fora_da_enumeracao", "tamanho_invalido",
            "obrigatorio_ausente", "grupo_incompleto", "estrutura_inesperada",
        }
        self.assertTrue(produzidos.issubset(DIAGNOSTICOS.keys()))


class TesteLocalizacao(unittest.TestCase):
    def test_extrai_numero_do_item_e_grupo(self):
        loc = localizar("/NFe/infNFe/det[3]/imposto/ICMS/ICMS00/vBC", 28, "vBC")
        self.assertEqual(loc.item, 3)
        self.assertEqual(loc.grupo, "ICMS00")
        self.assertEqual(loc.grupo_tributario, "ICMS")
        self.assertIn("Item 3", loc.descrever())
        self.assertIn("linha 28", loc.descrever())

    def test_subgrupo_de_pis_nao_e_atribuido_ao_icms(self):
        """vBC dentro de PISAliq tem que resolver para o grupo PIS - senão a
        explicação devolvida seria a do ICMS."""
        loc = localizar("/NFe/infNFe/det[1]/imposto/PIS/PISAliq/vBC", 40, "vBC")
        self.assertEqual(loc.grupo_tributario, "PIS")

    def test_icmstot_nao_e_tratado_como_grupo_de_imposto_do_item(self):
        loc = localizar("/NFe/infNFe/total/ICMSTot/vBC", 50, "vBC")
        self.assertIsNone(loc.grupo_tributario)
        self.assertIsNone(loc.item)

    def test_caminho_legivel_ignora_namespace_default(self):
        xml = _nota("    <det nItem=\"1\"><prod><NCM>1</NCM></prod></det>")
        arvore = parsear_xml(xml)
        ncm = [e for e in arvore.iter() if str(e.tag).endswith("NCM")][0]
        self.assertEqual(caminho_legivel(ncm), "/NFe/infNFe/det/prod/NCM")


class TesteComposicaoDaExplicacao(unittest.TestCase):
    def test_campo_catalogado_respeita_o_tipo_da_violacao(self):
        """Regressão da v1: o texto do catálogo sobrescrevia o diagnóstico, e
        um valor mal formatado era descrito como 'vazio ou ausente'."""
        vazio = montar_explicacao("vBC", "vazio", localizar("//ICMS/ICMS00/vBC"))
        formato = montar_explicacao(
            "vBC", "decimal_invalido", localizar("//ICMS/ICMS00/vBC"), valor="1.234,56"
        )
        self.assertIn("em branco", vazio["oQueAconteceu"])
        self.assertIn("1.234,56", formato["oQueAconteceu"])
        self.assertNotEqual(vazio["motivo_rejeicao"], formato["motivo_rejeicao"])
        # mesmo campo -> mesmo "por que", pois o papel fiscal não muda
        self.assertEqual(vazio["porQueRejeita"], formato["porQueRejeita"])

    def test_desambigua_vbc_por_grupo_tributario(self):
        icms = montar_explicacao("vBC", "vazio", localizar("//det[1]/imposto/ICMS/ICMS00/vBC"))
        pis = montar_explicacao("vBC", "vazio", localizar("//det[1]/imposto/PIS/PISAliq/vBC"))
        self.assertIn("ICMS", icms["campo"])
        self.assertIn("PIS", pis["campo"])

    def test_campo_fora_do_catalogo_ainda_recebe_explicacao_completa(self):
        e = montar_explicacao("xCampoNovo", "obrigatorio_ausente", localizar("//ide/xCampoNovo"))
        self.assertFalse(e["catalogado"])
        for parte in ("oQueAconteceu", "porQueRejeita", "comoCorrigir", "motivo_rejeicao"):
            self.assertTrue(e[parte], f"parte vazia: {parte}")
        self.assertNotIn("{", e["motivo_rejeicao"])  # nenhum placeholder sobrando

    def test_explicacao_traz_as_quatro_camadas_no_texto_corrido(self):
        e = montar_explicacao("vBC", "vazio", localizar("/NFe/infNFe/det[2]/imposto/ICMS/ICMS00/vBC", 30, "vBC"))
        texto = e["motivo_rejeicao"]
        self.assertIn("Item 2", texto)                      # onde
        self.assertIn("em branco", texto)                   # o que
        self.assertIn("Por que isso impede o envio", texto)  # por que
        self.assertIn("Como corrigir", texto)                # como

    def test_todo_campo_do_catalogo_tem_orientacao_de_correcao(self):
        from nfe_validator.catalogo_erros import CATALOGO_CAMPOS
        sem_orientacao = [k for k, v in CATALOGO_CAMPOS.items() if not v.como_corrigir]
        self.assertEqual(sem_orientacao, [])


class TesteIntegracaoComLeiauteOficial(unittest.TestCase):
    """Fase 3: campos fora do catálogo escrito à mão passam a receber o texto
    oficial do XSD em vez da frase genérica."""

    def setUp(self):
        from nfe_validator import layout
        if not layout.disponivel():
            self.skipTest("XSD oficial de NF-e não instalado")

    def test_catalogo_escrito_a_mao_vence_o_xsd(self):
        """As 22 entradas à mão são fiscalmente mais ricas que a documentação
        da SEFAZ ('Valor da BC do ICMS'), então têm precedência."""
        e = montar_explicacao("vBC", "vazio",
                              localizar("/NFe/infNFe/det[1]/imposto/ICMS/ICMS00/vBC", 29, "vBC"))
        self.assertEqual(e["fonte"], "catalogo")
        self.assertTrue(e["catalogado"])
        self.assertNotIn("O layout oficial define", e["porQueRejeita"])

    def test_texto_oficial_substantivo_entra_como_justificativa_citada(self):
        e = montar_explicacao("indTot", "vazio",
                              localizar("/NFe/infNFe/det[1]/prod/indTot", 20, "indTot"))
        self.assertEqual(e["fonte"], "xsd")
        self.assertFalse(e["catalogado"])
        # Citado entre aspas: quem lê tem que saber que a frase é da SEFAZ (RN07).
        self.assertIn("O layout oficial define", e["porQueRejeita"])
        self.assertIn('"', e["porQueRejeita"])

    def test_texto_curto_serve_de_nome_mas_nao_de_justificativa(self):
        """'Logradouro' é um ótimo nome de campo e uma péssima explicação de
        por que a SEFAZ rejeita. Sem essa distinção a integração pioraria
        dezenas de mensagens."""
        e = montar_explicacao("xLgr", "obrigatorio_ausente",
                              localizar("/NFe/infNFe/emit/enderEmit/xLgr", 12, "xLgr"))
        self.assertEqual(e["campo"], "Logradouro (xLgr)")
        self.assertNotIn("O layout oficial define", e["porQueRejeita"])

    def test_origem_xsd_permite_auditar_a_afirmacao(self):
        """RN05: se dizemos que o texto é oficial, tem que dar para abrir o
        arquivo naquela linha e conferir."""
        e = montar_explicacao("modBC", "fora_da_enumeracao",
                              localizar("/NFe/infNFe/det[1]/imposto/ICMS/ICMS00/modBC", 25, "modBC"),
                              valor="9")
        self.assertEqual(e["fonte"], "xsd")
        self.assertIn("origemXsd", e)
        self.assertTrue(e["origemXsd"]["arquivo"].endswith(".xsd"))
        self.assertIsInstance(e["origemXsd"]["linha"], int)

    def test_enumeracao_ganha_a_legenda_oficial_dos_valores(self):
        """O `esperado` deixa de ser a lista crua do libxml2 e passa a dizer o
        que cada código significa."""
        e = montar_explicacao("modBC", "fora_da_enumeracao",
                              localizar("/NFe/infNFe/det[1]/imposto/ICMS/ICMS00/modBC", 25, "modBC"),
                              valor="9", esperado="0, 1, 2, 3")
        self.assertIn("Margem Valor Agregado", e["comoCorrigir"])
        self.assertIn("Valor da Operação", e["comoCorrigir"])

    def test_nome_do_campo_vem_do_texto_oficial(self):
        e = montar_explicacao("pRedBC", "vazio",
                              localizar("/NFe/infNFe/det[1]/imposto/ICMS/ICMS20/pRedBC", 30, "pRedBC"))
        self.assertEqual(e["fonte"], "xsd")
        # Literal do XSD, sem "melhorar" a redação (RN07).
        self.assertEqual(e["campo"], "Percentual de redução da BC (pRedBC)")

    def test_mesma_tag_em_grupos_diferentes_recebe_texto_diferente(self):
        """`vBC` existe em ICMS, PIS, COFINS e IPI. A explicação tem que ser a
        do grupo onde o erro aconteceu, não a do primeiro que casar."""
        pis = montar_explicacao("vBC", "vazio",
                                localizar("/NFe/infNFe/det[1]/imposto/PIS/PISAliq/vBC", 40, "vBC"))
        cofins = montar_explicacao("vBC", "vazio",
                                   localizar("/NFe/infNFe/det[1]/imposto/COFINS/COFINSAliq/vBC", 45, "vBC"))
        self.assertIn("PIS", pis["campo"])
        self.assertIn("COFINS", cofins["campo"])

    def test_a_maioria_dos_erros_deixa_de_ser_generica(self):
        """Guarda-corpo da premissa do projeto: se a integração parar de
        entregar texto específico, ela não vale a complexidade."""
        caminho = Path(__file__).parent / "fixtures" / "nfe_exemplo_invalida.xml"
        resultado = validar(caminho.read_text(encoding="utf-8"))
        com_detalhe = [e for e in resultado["erros"] if e.get("detalhe")]
        genericos = [e for e in com_detalhe if e["detalhe"].get("fonte") == "generico"]
        self.assertLess(
            len(genericos) / len(com_detalhe), 0.10,
            f"{len(genericos)} de {len(com_detalhe)} erros ainda genéricos",
        )

    def test_funciona_sem_xsd_caindo_no_texto_generico(self):
        """A camada de leiaute nunca pode ser obrigatória: sem XSD instalado, a
        mensagem volta a ser a genérica, não um erro."""
        e = montar_explicacao("campoInexistenteNoLeiaute", "obrigatorio_ausente",
                              localizar("/NFe/infNFe/ide/campoInexistenteNoLeiaute", 5, None))
        self.assertEqual(e["fonte"], "generico")
        self.assertNotIn("origemXsd", e)
        self.assertTrue(e["porQueRejeita"])


class TesteCamposObrigatorios(unittest.TestCase):
    def test_tag_vazia_em_qualquer_lugar_e_reportada(self):
        xml = _nota(
            "    <det nItem=\"2\"><imposto><ICMS><ICMS00>"
            "<CST>00</CST><vBC></vBC><pICMS>18.00</pICMS>"
            "</ICMS00></ICMS></imposto></det>"
        )
        erros = validar_campos_obrigatorios(parsear_xml(xml))
        vazios = [e for e in erros if e["codigo"] == "RN18-VAZIO"]
        self.assertEqual(len(vazios), 1)
        self.assertIn("vBC", vazios[0]["detalhe"]["tagXml"])
        self.assertIn("Item 2", vazios[0]["detalhe"]["onde"])

    def test_espacos_sao_distinguidos_de_vazio(self):
        xml = _nota("    <emit><xNome>   </xNome></emit>")
        erros = validar_campos_obrigatorios(parsear_xml(xml))
        espacos = [e for e in erros if e["codigo"] == "RN18-ESPACOS"]
        self.assertEqual(len(espacos), 1)
        self.assertEqual(espacos[0]["detalhe"]["tipoViolacao"], "so_espacos")

    def test_numero_do_item_vem_do_atributo_nitem(self):
        xml = _nota(
            "    <det nItem=\"7\"><prod><cProd>A</cProd></prod></det>"
        )
        erros = validar_campos_obrigatorios(parsear_xml(xml))
        faltando_ncm = [e for e in erros if e["detalhe"]["tagXml"] == "NCM"]
        self.assertEqual(len(faltando_ncm), 1)
        self.assertIn("Item 7", faltando_ncm[0]["detalhe"]["onde"])

    def test_reporta_todos_os_campos_faltantes_do_grupo_de_uma_vez(self):
        """O libxml2 devolve um 'Missing child' por grupo; aqui queremos a
        lista completa para o usuário corrigir tudo numa passada."""
        xml = _nota("    <emit><CNPJ>11222333000181</CNPJ></emit>")
        erros = validar_campos_obrigatorios(parsear_xml(xml))
        faltantes = {e["detalhe"]["tagXml"] for e in erros if e["codigo"] == "RN18-AUSENTE"}
        self.assertIn("xNome", faltantes)
        self.assertIn("CRT", faltantes)

    def test_grupo_inteiro_ausente_gera_um_erro_e_nao_um_por_campo(self):
        erros = validar_campos_obrigatorios(parsear_xml(_nota("    <ide><mod>55</mod></ide>")))
        grupos = [e for e in erros if e["codigo"] == "RN18-GRUPO-AUSENTE"]
        caminhos = [e["detalhe"]["tagXml"] for e in grupos]
        self.assertIn("ICMSTot", caminhos)
        self.assertEqual(len(caminhos), len(set(caminhos)))

    def test_emit_sem_cnpj_nem_cpf(self):
        xml = _nota("    <emit><xNome>ACME</xNome><CRT>3</CRT></emit>")
        erros = validar_campos_obrigatorios(parsear_xml(xml))
        self.assertTrue(any(e["codigo"] == "RN18-IDENTIFICACAO-AUSENTE" for e in erros))

    def test_emit_com_cnpj_e_cpf_ao_mesmo_tempo(self):
        xml = _nota(
            "    <emit><CNPJ>11222333000181</CNPJ><CPF>11144477735</CPF>"
            "<xNome>ACME</xNome><CRT>3</CRT></emit>"
        )
        erros = validar_campos_obrigatorios(parsear_xml(xml))
        self.assertTrue(any(e["codigo"] == "RN18-IDENTIFICACAO-DUPLICADA" for e in erros))

    def test_nota_bem_preenchida_nao_gera_nenhum_falso_positivo(self):
        """A regra mais importante desta suíte: uma nota com todos os campos
        obrigatórios preenchidos não pode gerar UM único erro de RN18, senão o
        relatório perde credibilidade e o usuário passa a ignorá-lo."""
        xml = _nota(
            "  <ide><cUF>35</cUF><cNF>00000123</cNF><natOp>VENDA</natOp><mod>55</mod>"
            "<serie>1</serie><nNF>123</nNF><dhEmi>2026-08-07T10:00:00-03:00</dhEmi>"
            "<tpNF>1</tpNF><idDest>1</idDest><cMunFG>3550308</cMunFG><tpImp>1</tpImp>"
            "<tpEmis>1</tpEmis><cDV>8</cDV><tpAmb>2</tpAmb><finNFe>1</finNFe>"
            "<indFinal>1</indFinal><indPres>1</indPres><procEmi>0</procEmi>"
            "<verProc>1.0</verProc></ide>"
            "  <emit><CNPJ>11222333000181</CNPJ><xNome>ACME LTDA</xNome>"
            "<enderEmit><xLgr>RUA A</xLgr><nro>10</nro><xBairro>CENTRO</xBairro>"
            "<cMun>3550308</cMun><xMun>SAO PAULO</xMun><UF>SP</UF></enderEmit>"
            "<CRT>3</CRT></emit>"
            "  <dest><CNPJ>11444777000161</CNPJ><xNome>CLIENTE</xNome></dest>"
            "  <det nItem=\"1\"><prod><cProd>001</cProd><xProd>PRODUTO</xProd>"
            "<NCM>12345678</NCM><CFOP>5102</CFOP><uCom>UN</uCom><qCom>1.0000</qCom>"
            "<vUnCom>100.00</vUnCom><vProd>100.00</vProd><uTrib>UN</uTrib>"
            "<qTrib>1.0000</qTrib><vUnTrib>100.00</vUnTrib><indTot>1</indTot></prod>"
            "<imposto><ICMS><ICMS00><orig>0</orig><CST>00</CST><modBC>3</modBC>"
            "<vBC>100.00</vBC><pICMS>18.00</pICMS><vICMS>18.00</vICMS>"
            "</ICMS00></ICMS></imposto></det>"
            "  <total><ICMSTot><vBC>100.00</vBC><vICMS>18.00</vICMS>"
            "<vProd>100.00</vProd><vNF>100.00</vNF></ICMSTot></total>"
            "  <transp><modFrete>9</modFrete></transp>"
        )
        erros = validar_campos_obrigatorios(parsear_xml(xml))
        self.assertEqual(
            erros, [],
            "falso positivo em: " + ", ".join(f"{e['codigo']}/{e['xpath']}" for e in erros),
        )

    def test_xml_sem_infnfe_nao_estoura(self):
        arvore = parsear_xml('<outra xmlns="urn:x"><a>1</a></outra>')
        self.assertEqual(validar_campos_obrigatorios(arvore), [])

    def test_funciona_em_xml_sem_namespace(self):
        xml = (
            '<NFe><infNFe versao="4.00" Id="NFe1">'
            "<emit><xNome></xNome></emit></infNFe></NFe>"
        )
        erros = validar_campos_obrigatorios(parsear_xml(xml))
        self.assertTrue(any(e["codigo"] == "RN18-VAZIO" for e in erros))


class TesteContratoDeSaida(unittest.TestCase):
    def setUp(self):
        caminho = Path(__file__).parent / "fixtures" / "nfe_exemplo_invalida.xml"
        self.resultado = validar(caminho.read_text(encoding="utf-8"))

    def test_todo_erro_tem_explicacao_e_metadados(self):
        self.assertGreater(len(self.resultado["erros"]), 0)
        for erro in self.resultado["erros"]:
            self.assertTrue(erro["motivo_rejeicao"])
            self.assertIn("severidade", erro)
            self.assertIn("origem", erro)
            self.assertNotIn("{campo}", erro["motivo_rejeicao"])

    def test_resumo_agrega_e_lista_campos_nao_preenchidos(self):
        resumo = self.resultado["resumo"]
        self.assertEqual(resumo["totalErros"], len(self.resultado["erros"]))
        self.assertGreater(resumo["totalCamposNaoPreenchidos"], 0)
        self.assertEqual(resumo["totalCamposNaoPreenchidos"], len(resumo["camposNaoPreenchidos"]))
        for campo in resumo["camposNaoPreenchidos"]:
            self.assertTrue(campo["comoCorrigir"])

    def test_vbc_vazio_do_icms_e_reportado_com_item_e_linha(self):
        """Caso canônico da spec: <vBC></vBC> dentro de ICMS00."""
        achados = [
            e for e in self.resultado["erros"]
            if (e["detalhe"] or {}).get("tagXml") == "vBC"
            and (e["detalhe"] or {}).get("tipoViolacao") == "vazio"
        ]
        self.assertEqual(len(achados), 1, "vBC vazio deveria aparecer exatamente uma vez")
        erro = achados[0]
        self.assertIn("ICMS", erro["campo"])
        self.assertIn("Item 1", erro["detalhe"]["onde"])
        self.assertIsNotNone(erro["linha"])

    def test_erros_nao_sao_duplicados(self):
        chaves = [
            ((e["detalhe"] or {}).get("tagXml"), (e["detalhe"] or {}).get("tipoViolacao"), e["xpath"])
            for e in self.resultado["erros"]
            if e["detalhe"]
        ]
        self.assertEqual(len(chaves), len(set(chaves)))

    def test_erros_vem_ordenados_por_origem_e_linha(self):
        from nfe_validator.validador import PRIORIDADE_SUBORIGEM
        pesos = [PRIORIDADE_SUBORIGEM.get(e["subOrigem"], 99) for e in self.resultado["erros"]]
        self.assertEqual(pesos, sorted(pesos))

    def test_contrato_rn17_origem_e_mensagem(self):
        """RN17 fixa `origem` em dois valores e exige a chave `mensagem`.
        A granularidade fina vive em `subOrigem`, que é aditivo."""
        from nfe_validator.validador import ORIGENS_VALIDAS, ORIGEM_DA_SUBORIGEM
        for item in self.resultado["erros"] + self.resultado["avisos"]:
            self.assertIn(item["origem"], ORIGENS_VALIDAS, f"origem inválida em {item['codigo']}")
            self.assertTrue(item["mensagem"], f"sem mensagem em {item['codigo']}")
            self.assertEqual(item["mensagem"], item["motivo_rejeicao"])
            self.assertIn(item["subOrigem"], ORIGEM_DA_SUBORIGEM)
            # a origem tem que ser sempre derivada da subOrigem, nunca divergir
            self.assertEqual(item["origem"], ORIGEM_DA_SUBORIGEM[item["subOrigem"]])

    def test_so_o_xsd_tem_origem_xsd(self):
        """Só o veredito do libxml2 é `origem: xsd`; toda regra nossa é
        `regra-negocio`, mesmo quando fala sobre estrutura."""
        for erro in self.resultado["erros"]:
            if erro["origem"] == "xsd":
                self.assertEqual(erro["subOrigem"], "schema")
                self.assertTrue(erro["mensagem_tecnica"])

    def test_campos_obrigatorios_rodam_mesmo_sem_xsd(self):
        caminho = Path(__file__).parent / "fixtures" / "nfe_exemplo_invalida.xml"
        sem_xsd = validar(caminho.read_text(encoding="utf-8"), aplicar_xsd=False)
        self.assertFalse(sem_xsd["resumo"]["xsdAplicado"])
        self.assertGreater(sem_xsd["resumo"]["totalCamposNaoPreenchidos"], 0)

    def test_xml_malformado_explica_como_corrigir(self):
        r = validar("<NFe><infNFe></NFe>")
        self.assertEqual(r["erros"][0]["codigo"], "XML-MALFORMADO")
        self.assertIn("Como corrigir", r["erros"][0]["motivo_rejeicao"])
        self.assertIn("resumo", r)


if __name__ == "__main__":
    unittest.main()
