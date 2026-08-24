"""
RN12 - Valida que campos de data/hora (dhEmi, dhSaiEnt) seguem o formato
ISO 8601 com timezone exigido pelo layout (ex.: 2026-08-07T14:30:00-03:00).
"""

import re

_PADRAO_ISO8601_TZ = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:[+-]\d{2}:\d{2}|Z)$"
)


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
        "subOrigem": "datas",
    }


def validar_data(valor: str, nome_campo: str) -> list[dict]:
    if not valor:
        return [_erro(
            "RN12-AUSENTE", nome_campo,
            f"O campo {nome_campo} está ausente. A SEFAZ exige data/hora "
            "com fuso horário para registrar o momento exato do evento "
            "fiscal (emissão, saída, etc.).",
        )]
    if not _PADRAO_ISO8601_TZ.match(valor):
        return [_erro(
            "RN12-FORMATO", nome_campo,
            f"O campo {nome_campo} tem o valor '{valor}', que não está no "
            "formato ISO 8601 com fuso horário exigido pelo layout "
            "(ex.: 2026-08-07T14:30:00-03:00). A SEFAZ rejeita a nota "
            "porque não consegue interpretar o instante do evento fiscal.",
        )]
    return []
