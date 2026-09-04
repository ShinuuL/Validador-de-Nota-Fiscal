"""
RN11 - Valida que os totais declarados em <ICMSTot> batem com a soma dos
itens/impostos do XML, dentro de uma tolerância de arredondamento.
"""

TOLERANCIA_PADRAO = 0.02  # tolerância em reais por conferência, ajustável

# Composição de vNF, conforme o MOC. Antes, esta regra comparava vNF apenas
# com a soma de vProd dos itens (marcado no código como "simplificado"), e
# isso reprovava qualquer nota com frete, desconto, IPI ou ST — 11 de 24 notas
# reais JÁ AUTORIZADAS pela SEFAZ eram acusadas de erro por causa disso.
#
# A fórmula abaixo foi conferida contra essas 24 notas: 24 conferem, 0 divergem.
COMPONENTES_QUE_SOMAM = (
    "vProd", "vST", "vFCPST", "vFrete", "vSeg", "vOutro",
    "vII", "vIPI", "vIPIDevol", "vServ",
)
COMPONENTES_QUE_SUBTRAEM = ("vDesc", "vICMSDeson")


def calcular_vnf_esperado(componentes: dict) -> tuple[float, str]:
    """Recompõe vNF a partir dos componentes declarados em <ICMSTot>.

    Devolve (valor, memoria_de_calculo). A memória lista só as parcelas
    diferentes de zero — numa nota simples ela fica curta, e numa nota
    complicada é justamente o que o usuário precisa ver para achar a diferença.
    """
    def valor(nome: str) -> float:
        try:
            return float(componentes.get(nome) or 0.0)
        except (TypeError, ValueError):
            return 0.0

    total = 0.0
    partes: list[str] = []
    for nome in COMPONENTES_QUE_SOMAM:
        v = valor(nome)
        total += v
        if v:
            partes.append(f"+ {nome} {v:.2f}")
    for nome in COMPONENTES_QUE_SUBTRAEM:
        v = valor(nome)
        total -= v
        if v:
            partes.append(f"- {nome} {v:.2f}")

    memoria = " ".join(partes).lstrip("+ ").strip() or "sem parcelas informadas"
    return round(total, 2), memoria


def _erro(codigo: str, campo: str, motivo: str) -> dict:
    return {
        "codigo": codigo,
        "campo": campo,
        "xpath": None,
        "linha": None,
        "mensagem_tecnica": None,
        "mensagem": motivo,
        "motivo_rejeicao": motivo,
        "origem": "regra-negocio",
        "subOrigem": "totais",
    }


def validar_totais(
    soma_vprod_itens: float,
    v_prod_total_declarado: float,
    soma_vicms_itens: float,
    v_icms_total_declarado: float,
    v_nf_declarado: float,
    v_nf_esperado: float | None = None,
    tolerancia: float = TOLERANCIA_PADRAO,
    componentes_icmstot: dict | None = None,
) -> list[dict]:
    """Confere os totais de <ICMSTot> contra a soma dos itens.

    `componentes_icmstot`: quando informado, vNF é recomposto pela fórmula do
    MOC (ver `calcular_vnf_esperado`) e a mensagem traz a memória de cálculo.
    `v_nf_esperado` continua aceito para quem já calculou o valor por fora.
    """
    erros: list[dict] = []
    memoria = ""
    if componentes_icmstot is not None:
        v_nf_esperado, memoria = calcular_vnf_esperado(componentes_icmstot)
    elif v_nf_esperado is None:
        v_nf_esperado = soma_vprod_itens

    if abs(soma_vprod_itens - v_prod_total_declarado) > tolerancia:
        erros.append(_erro(
            "RN11-VPROD", "ICMSTot/vProd",
            f"A soma do valor dos produtos dos itens (R$ {soma_vprod_itens:.2f}) "
            f"não confere com o total declarado em ICMSTot/vProd "
            f"(R$ {v_prod_total_declarado:.2f}). A SEFAZ rejeita a nota porque "
            "o total não pode ser conferido a partir dos itens.",
        ))

    if abs(soma_vicms_itens - v_icms_total_declarado) > tolerancia:
        erros.append(_erro(
            "RN11-VICMS", "ICMSTot/vICMS",
            f"A soma do ICMS calculado item a item (R$ {soma_vicms_itens:.2f}) "
            f"não confere com o total declarado em ICMSTot/vICMS "
            f"(R$ {v_icms_total_declarado:.2f}). A nota é rejeitada porque o "
            "imposto total não pode ser conferido.",
        ))

    if abs(v_nf_declarado - v_nf_esperado) > tolerancia:
        diferenca = v_nf_declarado - v_nf_esperado
        erros.append(_erro(
            "RN11-VNF", "ICMSTot/vNF",
            f"O valor total da nota declarado (R$ {v_nf_declarado:.2f}) não confere "
            f"com o valor recomposto a partir das parcelas de <ICMSTot> "
            f"(R$ {v_nf_esperado:.2f}), uma diferença de R$ {diferenca:+.2f}. "
            + (f"Memória de cálculo: {memoria}. " if memoria else "")
            + "A SEFAZ rejeita porque o valor total cobrado do destinatário não "
            "pode ser conferido. Como corrigir: confira qual parcela está errada "
            "(vProd, vDesc, vFrete, vSeg, vOutro, vST, vIPI) — a diferença acima "
            "normalmente aponta direto para ela.",
        ))

    return erros
