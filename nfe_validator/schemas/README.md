# Como instalar os XSDs oficiais

Este projeto **não inclui** os arquivos `.xsd` oficiais da NF-e/NFC-e (RN05:
o sistema deve usar exclusivamente os arquivos reais publicados pela
SEFAZ/ENCAT, nunca uma recriação).

## Passo a passo

1. Acesse o Portal Nacional da NF-e:
   `https://www.nfe.fazenda.gov.br` → área de "Documentos Técnicos" / "Schemas XML".
   Alternativamente, o portal SVRS costuma manter os pacotes de schema
   organizados: `https://dfe-portal.svrs.rs.gov.br/NFe/Documentos`.

2. Baixe o pacote de schemas da **versão 4.00** (a versão vigente em 2026,
   que pode incluir extensões da Reforma Tributária via Notas Técnicas —
   confira a nota técnica mais recente antes de baixar).

3. Extraia todos os arquivos `.xsd` do pacote (o layout nacional é
   modular: existe um XSD "de entrada" que importa vários outros —
   ex. `tiposBasico_v4.00.xsd`, `leiauteNFe_v4.00.xsd`, etc. — **todos
   precisam estar na mesma pasta** para a importação funcionar).

4. Copie os arquivos para:
   - NF-e (modelo 55): `schemas/v4.00/nfe/`
   - NFC-e (modelo 65): `schemas/v4.00/nfce/`

   > ⚠️ **Estado atual:** o passo da NFC-e **ainda não foi executado** — a pasta
   > `schemas/v4.00/nfce/` não existe no disco e o `nfce_v4.00.xsd` ainda não foi
   > baixado. A instrução acima permanece válida para quando essa instalação for feita.

5. Confirme que o arquivo de entrada tem o nome esperado pelo código
   (`nfe_validator/schema.py`, dicionário `ARQUIVOS_ENTRADA`):
   - `schemas/v4.00/nfe/nfe_v4.00.xsd`
   - `schemas/v4.00/nfce/nfce_v4.00.xsd`

   Se o nome do arquivo baixado for diferente, ajuste o dicionário
   `ARQUIVOS_ENTRADA` em `schema.py` — não renomeie o conteúdo do XSD.

6. Rode a suíte de testes novamente
   (`python3 -m unittest discover -s tests -v`) para confirmar que o
   carregamento do schema não gera erro de importação/caminho.

## Adicionando uma nova versão de layout (RN14)

Quando sair uma nova versão do layout (ex. `4.01` por causa da Reforma
Tributária), **não altere o código**: apenas crie uma nova pasta
`schemas/v4.01/nfe/` (e/ou `nfce/`) com os XSDs correspondentes. O
sistema seleciona o schema dinamicamente a partir do atributo `versao`
lido do próprio XML (RN02/RN03).


## Pontos de entrada instalados em `v4.00/nfe/`

Um XSD de entrada só declara a raiz global e inclui o `leiauteNFe_v4.00.xsd`.
Qual deles é usado depende da **raiz do documento** que se está validando
(ver `ENTRADA_POR_RAIZ` em `nfe_validator/schema.py`):

| Arquivo | Raiz global | Quando aparece |
| --- | --- | --- |
| `nfe_v4.00.xsd` | `NFe` | nota isolada, sem envelope |
| `enviNFe_v4.00.xsd` | `enviNFe` | o que o ERP monta e transmite à SEFAZ |
| `procNFe_v4.00.xsd` | `nfeProc` | nota autorizada (NFe + protNFe) |
| `retEnviNFe_v4.00.xsd` | `retEnviNFe` | retorno do lote |

Os três últimos vieram do pacote `PL_010B_NT2025_002_v130` usado pelo ERP.
O `leiauteNFe_v4.00.xsd` **não** foi substituído: o nosso tem 527 definições
contra 520 do pacote do ERP, com 7 exclusivas e nenhuma faltando, então trocar
seria downgrade.
