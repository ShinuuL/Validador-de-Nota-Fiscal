"""
Demonstração isolada (não faz parte do pacote): prova que o pipeline de
tradução de erros de XSD -> explicação de negócio funciona, usando um XSD
mínimo de teste (NÃO é o XSD oficial da SEFAZ, é só um recorte didático
do grupo ICMS00 para reproduzir o exemplo pedido: "vBC do ICMS vazio").
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lxml import etree
from nfe_validator.nucleo.schema import _classificar_e_extrair, _extrair_grupo_pai
from nfe_validator.nucleo.catalogo_erros import explicar_campo, explicacao_generica

XSD_TESTE = """<?xml version="1.0" encoding="UTF-8"?>
<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema">
  <xs:element name="ICMS00">
    <xs:complexType>
      <xs:sequence>
        <xs:element name="CST" type="xs:string"/>
        <xs:element name="vBC" type="xs:decimal"/>
        <xs:element name="pICMS" type="xs:decimal"/>
        <xs:element name="vICMS" type="xs:decimal"/>
      </xs:sequence>
    </xs:complexType>
  </xs:element>
</xs:schema>
"""

XML_COM_VBC_VAZIO = """<?xml version="1.0" encoding="UTF-8"?>
<ICMS00>
  <CST>00</CST>
  <vBC></vBC>
  <pICMS>18.00</pICMS>
  <vICMS>18.00</vICMS>
</ICMS00>
"""

schema = etree.XMLSchema(etree.fromstring(XSD_TESTE.encode()).getroottree())
doc = etree.fromstring(XML_COM_VBC_VAZIO.encode()).getroottree()

valido = schema.validate(doc)
print(f"XML válido segundo o XSD de teste? {valido}\n")

for log in schema.error_log:
    tipo_violacao, tag, valor, esperado = _classificar_e_extrair(log.message)
    grupo_pai = _extrair_grupo_pai(log.path) or "ICMS"  # xsd de teste não tem o grupo ICMS pai
    explicacao = explicar_campo(tag, grupo_pai)
    motivo = explicacao.motivo if explicacao else explicacao_generica(tipo_violacao, tag, valor, esperado)

    print("=== Erro técnico bruto (lxml) ===")
    print(f"  mensagem: {log.message}")
    print(f"  xpath:    {log.path}")
    print(f"  linha:    {log.line}")
    print("=== Traduzido para o negócio ===")
    print(f"  campo:            {tag} (grupo {grupo_pai})")
    print(f"  tipo de violação: {tipo_violacao}")
    print(f"  motivo_rejeicao:  {motivo}")
    print()
