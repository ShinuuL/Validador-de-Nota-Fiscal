"""
RN08 - Valida o dígito verificador (DV) da chave de acesso (44 dígitos, módulo 11).
RN09 - Valida que os dados embutidos na chave batem com os campos do XML
       (cUF, AAMM, CNPJ emitente, mod, serie, nNF, tpEmis, cNF).
"""

from ..catalogo_erros import CATALOGO_CAMPOS


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
        "subOrigem": "chave-acesso",
    }


def calcular_dv_modulo11(chave_43_digitos: str) -> int:
    """Calcula o dígito verificador (módulo 11) dos 43 primeiros dígitos
    da chave de acesso, conforme especificação do Manual de Orientação
    do Contribuinte (MOC) da NF-e."""
    pesos = [2, 3, 4, 5, 6, 7, 8, 9] * 6  # ciclo de pesos 2..9, repetido
    soma = 0
    for digito, peso in zip(reversed(chave_43_digitos), pesos):
        soma += int(digito) * peso
    resto = soma % 11
    dv = 0 if resto in (0, 1) else 11 - resto
    return dv


def validar_chave_acesso(chave: str, campos_ide: dict, campos_emit: dict) -> list[dict]:
    """
    chave: string da chave de acesso (44 dígitos, geralmente extraída do
        atributo Id="NFe<chave>" da tag infNFe).
    campos_ide: dict com valores lidos do grupo <ide> (cUF, mod, serie, nNF,
        tpEmis, cNF, dhEmi).
    campos_emit: dict com valores lidos do grupo <emit> (CNPJ).
    """
    erros: list[dict] = []

    if not chave:
        erros.append(_erro(
            "RN08-AUSENTE", "Chave de Acesso",
            CATALOGO_CAMPOS["chNFe"].motivo,
        ))
        return erros

    if len(chave) != 44 or not chave.isdigit():
        erros.append(_erro(
            "RN08-TAMANHO", "Chave de Acesso",
            f"A chave de acesso tem {len(chave)} caracteres, mas deveria ter "
            "exatamente 44 dígitos numéricos. A SEFAZ rejeita a nota porque "
            "não consegue decompor a chave nos seus campos (UF, data, CNPJ, "
            "modelo, série, número, tipo de emissão, código numérico e DV).",
        ))
        return erros

    corpo, dv_informado = chave[:43], chave[43]
    dv_calculado = calcular_dv_modulo11(corpo)
    if int(dv_informado) != dv_calculado:
        erros.append(_erro(
            "RN08-DV", "Chave de Acesso",
            f"O dígito verificador da chave de acesso está incorreto "
            f"(informado: {dv_informado}, esperado: {dv_calculado}). "
            "A SEFAZ recusa a nota de imediato porque a chave não é "
            "matematicamente válida — isso pode indicar erro de geração "
            "ou adulteração do XML.",
        ))

    # RN09: consistência entre a chave e o corpo do XML.
    partes_chave = {
        "cUF": chave[0:2],
        "AAMM": chave[2:6],
        "CNPJ": chave[6:20],
        "mod": chave[20:22],
        "serie": chave[22:25],
        "nNF": chave[25:34],
        "tpEmis": chave[34:35],
        "cNF": chave[35:43],
    }

    if campos_emit.get("CNPJ") and partes_chave["CNPJ"] != campos_emit["CNPJ"]:
        erros.append(_erro(
            "RN09-CNPJ", "Chave de Acesso x emit/CNPJ",
            "O CNPJ embutido na chave de acesso não é igual ao CNPJ "
            "declarado no grupo <emit>. A SEFAZ rejeita porque a chave "
            "deixa de identificar corretamente o emitente da nota.",
        ))

    if campos_ide.get("mod") and partes_chave["mod"] != campos_ide["mod"].zfill(2):
        erros.append(_erro(
            "RN09-MOD", "Chave de Acesso x ide/mod",
            "O modelo do documento (mod) embutido na chave de acesso não "
            "confere com o campo mod declarado no grupo <ide>.",
        ))

    if campos_ide.get("serie") and partes_chave["serie"] != str(campos_ide["serie"]).zfill(3):
        erros.append(_erro(
            "RN09-SERIE", "Chave de Acesso x ide/serie",
            "A série embutida na chave de acesso não confere com o campo "
            "serie declarado no grupo <ide>.",
        ))

    if campos_ide.get("nNF") and partes_chave["nNF"] != str(campos_ide["nNF"]).zfill(9):
        erros.append(_erro(
            "RN09-NUMERO", "Chave de Acesso x ide/nNF",
            "O número da nota embutido na chave de acesso não confere com "
            "o campo nNF declarado no grupo <ide>.",
        ))

    return erros
