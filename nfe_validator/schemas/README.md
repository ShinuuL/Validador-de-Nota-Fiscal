# Como instalar os XSDs oficiais

Os arquivos `.xsd` são **parte da entrega**, não artefato de build. A RN05 exige
validar contra os arquivos reais publicados pela SEFAZ/ENCAT — nunca uma
recriação. Sem eles, `validar()` não quebra: degrada em silêncio para o aviso
`XSD-INDISPONIVEL` e perde a validação estrutural, a RN19 e as descrições
oficiais de campo.

## Estado atual

| Documento | Pasta | Situação |
| --- | --- | --- |
| **NF-e** (modelo 55) | `v4.00/nfe/` | ✅ **instalado** — 8 arquivos, validação completa |
| **NFC-e** (modelo 65) | `v4.00/nfce/` | ⬜ **vazio** — só regras de negócio, sem XSD |

Confira a qualquer momento com:

```bash
python -c "from nfe_validator import layout; print('NF-e :', layout.disponivel('NFe','4.00')); print('NFC-e:', layout.disponivel('NFCe','4.00'))"
```

## Instalar a NFC-e (o que está faltando)

**1. Baixe o pacote de schemas**

Portal Nacional da NF-e — `https://www.nfe.fazenda.gov.br` → *Documentos* →
*Documentos Técnicos* → *Pacote de Liberação de Schemas*. O portal da SVRS
costuma ser mais direto: `https://dfe-portal.svrs.rs.gov.br/Nfe/Documentos`.

Baixe o **Pacote de Liberação (PL)** mais recente da versão **4.00**. Hoje é a
linha `PL_010B_NT2025_002` (Nota Técnica 2025.002, IBS/CBS da Reforma
Tributária).

**2. Entenda o que a SEFAZ publica**

A SEFAZ **não publica um leiaute separado para NFC-e**. O mesmo
`leiauteNFe_v4.00.xsd` cobre modelo 55 e 65 — a diferença é operacional
(`ide/mod`, `indPres`, regras de destinatário), não de schema.

Na prática, o que existe é o mesmo pacote. Duas opções:

**Opção A — copiar o pacote (recomendada, respeita a RN15)**

Copie do PL baixado para `v4.00/nfce/`, renomeando **só** o ponto de entrada:

```
nfe_v4.00.xsd          ->  nfce_v4.00.xsd      (renomeie o ARQUIVO, nunca o conteúdo)
leiauteNFe_v4.00.xsd   ->  leiauteNFe_v4.00.xsd
tiposBasico_v4.00.xsd  ->  tiposBasico_v4.00.xsd
DFeTiposBasicos_v1.00.xsd
xmldsig-core-schema_v1.01.xsd
enviNFe_v4.00.xsd      (opcional: valida o envelope de envio)
procNFe_v4.00.xsd      (opcional: valida a nota autorizada)
retEnviNFe_v4.00.xsd   (opcional)
```

> ⚠️ Renomear `nfe_v4.00.xsd` para `nfce_v4.00.xsd` é seguro: esse arquivo tem
> 9 linhas e só declara `<xs:element name="NFe" type="TNFe">` mais um
> `xs:include`. O nome do arquivo não aparece dentro dele. **Todos os arquivos
> precisam ficar na mesma pasta**, porque os `xs:include` são relativos.

**Opção B — não copiar, e aceitar o limite**

Se preferir não duplicar 400 KB de XSD, a NFC-e continua rodando as regras de
negócio (RN08–RN19) com o aviso `XSD-INDISPONIVEL`. Para ela ao menos receber
as **descrições oficiais de campo**, ligue o empréstimo de leiaute:

```python
layout.carregar_modelo("NFCe", "4.00", permitir_leiaute_equivalente=True)
```

Isso usa o leiaute de NF-e da **mesma versão** apenas para texto explicativo —
nunca para validar. O padrão é `False` porque, se a SEFAZ algum dia publicar um
leiaute de NFC-e divergente, o empréstimo passaria a explicar campos com o
documento errado, em silêncio. O empréstimo se desliga sozinho quando a pasta
`nfce/` ganha qualquer `.xsd`.

**3. Confirme o nome do ponto de entrada**

O código espera `nfce_v4.00.xsd` (dicionário `ARQUIVOS_ENTRADA` em
`nfe_validator/schema.py`). Se o pacote baixado usar outro nome, ajuste o
dicionário — **não edite o conteúdo do XSD**.

**4. Verifique**

```bash
python -c "from nfe_validator import layout; print(layout.disponivel('NFCe','4.00'))"
python -m unittest discover -s tests -p "test_*.py"
```

Se instalou o pacote com `pip install .`, **reinstale** — os XSDs são
`package-data` e o ambiente instalado tem a própria cópia.

## Pontos de entrada instalados em `v4.00/nfe/`

Um XSD de entrada só declara a raiz global e inclui o `leiauteNFe_v4.00.xsd`.
Qual deles é usado depende da **raiz do documento** validado
(`ENTRADA_POR_RAIZ` em `nfe_validator/schema.py`):

| Arquivo | Raiz global | Quando aparece |
| --- | --- | --- |
| `nfe_v4.00.xsd` | `NFe` | nota isolada, sem envelope |
| `enviNFe_v4.00.xsd` | `enviNFe` | o que o ERP monta e transmite à SEFAZ |
| `procNFe_v4.00.xsd` | `nfeProc` | nota autorizada (NFe + protNFe) |
| `retEnviNFe_v4.00.xsd` | `retEnviNFe` | retorno do lote |

Os três últimos vieram do pacote `PL_010B_NT2025_002_v130` usado pelo ERP.
O `leiauteNFe_v4.00.xsd` **não** foi substituído: o nosso tem 527 definições
contra 520 do pacote do ERP, com 7 exclusivas e nenhuma faltando — trocar seria
downgrade.

## Adicionando uma nova versão de layout (RN14)

Quando sair uma versão nova (ex. `4.01`), **não altere código**: crie
`v4.01/nfe/` (e/ou `nfce/`) com os XSDs correspondentes. O sistema escolhe o
schema pelo atributo `versao` lido do próprio XML (RN02/RN03), e falha
explicitamente se a versão não estiver instalada (RN15) — nunca valida contra a
versão errada em silêncio.

Depois de adicionar uma versão, se o projeto estiver instalado, rode
`pip install .` de novo.
