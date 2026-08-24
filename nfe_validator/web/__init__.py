"""Camada web da UI de arrastar-e-soltar (ver spec-ui-drag-and-drop.md).

Sem regra de negócio: recebe o XML, chama `nfe_validator.validador.validar()`
e devolve o JSON como sai.
"""

from .servidor import criar_servidor, processar_validacao, servir

__all__ = ["criar_servidor", "processar_validacao", "servir"]
