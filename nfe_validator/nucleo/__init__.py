"""
Núcleo da validação: tudo que decide se a nota passa ou não.

A divisão do pacote é por RESPONSABILIDADE, não por camada técnica:

  * `nucleo/`      - lê o XML, identifica o documento, roda XSD e regras;
  * `nucleo/regras/` - uma regra de negócio por arquivo;
  * `web/`         - servidor HTTP e a UI que fala com o núcleo;
  * `ferramentas/` - utilitários de apoio que não entram no caminho da
                     validação (gerador do dicionário de dados, coletor de
                     erros do ERP);
  * `__main__.py` e `desktop.py` - os dois pontos de entrada.

Nada aqui dentro importa `web` ou `ferramentas`: a dependência é sempre de
fora para dentro. Se um import inverter esse sentido, a regra de negócio
passou a depender de apresentação, e é hora de parar.
"""
