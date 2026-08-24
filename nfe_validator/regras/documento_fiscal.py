"""
RN10 - Valida dígitos verificadores de CNPJ e CPF encontrados no XML
(grupos emit, dest, transporta, etc.).
"""


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
        "subOrigem": "documento-fiscal",
    }


def _dv_cnpj(base: str) -> str:
    pesos1 = [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]
    pesos2 = [6] + pesos1

    def calc(digitos: str, pesos: list[int]) -> str:
        soma = sum(int(d) * p for d, p in zip(digitos, pesos))
        resto = soma % 11
        return "0" if resto < 2 else str(11 - resto)

    dv1 = calc(base, pesos1)
    dv2 = calc(base + dv1, pesos2)
    return dv1 + dv2


def cnpj_valido(cnpj: str) -> bool:
    cnpj = "".join(filter(str.isdigit, cnpj or ""))
    if len(cnpj) != 14 or len(set(cnpj)) == 1:
        return False
    return cnpj[12:] == _dv_cnpj(cnpj[:12])


def _dv_cpf(base: str) -> str:
    def calc(digitos: str, peso_inicial: int) -> str:
        soma = sum(int(d) * (peso_inicial - i) for i, d in enumerate(digitos))
        resto = (soma * 10) % 11
        return "0" if resto == 10 else str(resto)

    dv1 = calc(base, 10)
    dv2 = calc(base + dv1, 11)
    return dv1 + dv2


def cpf_valido(cpf: str) -> bool:
    cpf = "".join(filter(str.isdigit, cpf or ""))
    if len(cpf) != 11 or len(set(cpf)) == 1:
        return False
    return cpf[9:] == _dv_cpf(cpf[:9])


def validar_documentos(campos_por_grupo: dict[str, dict]) -> list[dict]:
    """
    campos_por_grupo: ex. {"emit": {"CNPJ": "..."}, "dest": {"CPF": "..."}}
    Valida cada CNPJ/CPF presente e devolve os erros encontrados.
    """
    erros: list[dict] = []
    for grupo, campos in campos_por_grupo.items():
        cnpj = campos.get("CNPJ")
        if cnpj and not cnpj_valido(cnpj):
            erros.append(_erro(
                "RN10-CNPJ", f"{grupo}/CNPJ",
                f"O CNPJ informado em <{grupo}> ('{cnpj}') tem dígito "
                "verificador inválido. A Receita rejeita a nota porque não "
                "consegue confirmar que esse é um CNPJ real e ativo.",
            ))
        cpf = campos.get("CPF")
        if cpf and not cpf_valido(cpf):
            erros.append(_erro(
                "RN10-CPF", f"{grupo}/CPF",
                f"O CPF informado em <{grupo}> ('{cpf}') tem dígito "
                "verificador inválido. A Receita rejeita a nota porque não "
                "consegue confirmar que esse é um CPF real.",
            ))
    return erros
