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
| **NFC-e** (modelo 65) | `v4.00/nfce/` | ✅ **instalado** — 8 arquivos, validação completa |

Confira a qualquer momento com:

```bash
python -c "from nfe_validator import layout; print('NF-e :', layout.disponivel('NFe','4.00')); print('NFC-e:', layout.disponivel('NFCe','4.00'))"
```

## Como a NFC-e foi instalada

Instalada em 2026-08-26 como **cópia do conjunto de `v4.00/nfe/`**, com uma
única alteração: o nome do arquivo de entrada
(`nfe_v4.00.xsd` → `nfce_v4.00.xsd`). Nenhum conteúdo de XSD foi editado (RN05).

A SEFAZ **não publica um leiaute separado para NFC-e**. O mesmo
`leiauteNFe_v4.00.xsd` cobre modelo 55 e 65 — a diferença é operacional
(`ide/mod`, `indPres`, regras de destinatário), não de schema. Então instalar a
NFC-e é replicar o mesmo pacote sob o nome de entrada que
`ARQUIVOS_ENTRADA` espera.

> ⚠️ Renomear o arquivo de entrada é seguro: ele tem 9 linhas e só declara
> `<xs:element name="NFe" type="TNFe">` mais um `xs:include`. O nome do arquivo
> não aparece dentro dele. **Todos os arquivos precisam ficar na mesma pasta**,
> porque os `xs:include` são relativos.

### Por que copiar de `nfe/` em vez de um pacote baixado do portal

Porque o conjunto em `v4.00/nfe/` é o **mais novo** que o projeto tem — mais
novo que os PLs disponíveis para download que foram conferidos. Comparação
feita arquivo por arquivo, por nome de tipo e de elemento:

| Pacote | Situação frente a `v4.00/nfe/` |
| --- | --- |
| `PL_010b_NT2025_002_v1.30` | o mais **antigo** dos três — falta um grupo inteiro de ICMS desonerado/diferido (`vICMSDeson`, `pDif`, `vFCPDif`, `cBenefRBC`, `motDesICMS`, `indDeduzDeson`) |
| `PL_010c_NT2022_002v1.30` | mais novo que o `010b` (tem o grupo de ICMS), mas ainda **atrás** do instalado |
| `v4.00/nfe/` (instalado) | **o mais novo** |

O que o instalado tem a mais que o `PL_010c`:

- Em `DFeTiposBasicos_v1.00.xsd` (62 KB contra 49 KB): os tipos e elementos da
  **Zona Franca de Manaus / crédito presumido de IBS** e de DF-e referenciado —
  `TALCZFMCBS`, `TALCZFMCBS_NFe`, `TCredPresIBSZFM`, `gALCZFMCBS`,
  `tpALCZFMCBS`, `nProcSuframa`, `refDFe`, `refDFeAnt`, `pDevTrib`, `adRemIS`,
  além de `TCIBS_NFe`, `TChDFeRTC`, `TCnpjRTC`, `TCnpjBaseRTC`, `TRBSN`,
  `TPagRef`.
- O `PL_010c` tem só um elemento que o instalado não tem: `pISEspec` —
  aparentemente **renomeado** para `adRemIS` (alíquota *ad rem* do Imposto
  Seletivo) na revisão mais nova. Não é conteúdo perdido.

### Correção: IBS/CBS **está** instalado

Uma análise anterior afirmou que nenhum pacote trazia os grupos da Reforma
Tributária. Isso estava errado — a busca tinha olhado só o `leiauteNFe`. Os
grupos IBS/CBS vivem em **`DFeTiposBasicos_v1.00.xsd`** (`gIBSCBS`, `gIBS`,
`gCBS`, `gIBSUF`, `gIBSMun`, `gIBSCBSMono`, `gIBSCredPres`, `gCBSCredPres`,
`TIBSCBSTot`, `TCIBS`…), e o leiaute os **liga** ao documento em dois pontos:

```
leiauteNFe_v4.00.xsd:5186   <xs:element name="IBSCBS"    type="TTribNFe"       minOccurs="0"/>   (det/imposto)
leiauteNFe_v4.00.xsd:5622   <xs:element name="IBSCBSTot" type="TIBSCBSMonoTot" minOccurs="0"/>   (total)
```

Ou seja: a validação de IBS/CBS funciona, tanto em NF-e quanto agora em NFC-e.

### Procedência do `nfe/`: confirmada

O conjunto instalado em `v4.00/nfe/` é **byte-a-byte idêntico** ao
`PL_010e_v1.02/NFe` (publicado em 10/07/2026) — todos os 5 arquivos, `cmp`
sem diferença. Está oficial e atualizado; não há o que trocar.

Isso encerra uma dúvida que ficou aberta: 7 elementos do leiaute instalado
(`cIndOp` em `ide`, `ISUFEmit` em `emit`, e o grupo `infPAA` / `CNPJPAA` /
`PAASignature` / `RSAKeyValue` / `SignatureValue` — "Provedor de Assinatura e
Autorização" —, mais `TRSAKeyValueType` em `tiposBasico`) não apareciam nos
pacotes `PL_010b` e `PL_010c`, e chegou-se a suspeitar que fossem extraoficiais.
**São oficiais.** O bloco PAA entra no `PL_010d` e o `ISUFEmit`/`cIndOp` no
`PL_010e`; os pacotes anteriores eram só mais antigos.

### Pacotes conferidos

Em ordem, do mais antigo ao mais novo:

| Pacote | Data | Situação frente a `v4.00/nfe/` |
| --- | --- | --- |
| `PL_010b_NT2025_002_v1.30` | — | mais antigo: falta o grupo de ICMS desonerado/diferido, o bloco PAA e o bloco ZFM/RTC |
| `PL_010c_NT2022_002v1.30` | — | ganha o grupo de ICMS; ainda sem PAA nem ZFM/RTC |
| `PL_010d_v1.03` | 10/07/2026 | leiaute de 08/07 14:57 — ganha o bloco PAA; **ainda atrás**: sem `ISUFEmit`/`cIndOp` e sem o bloco ZFM/RTC no `DFeTiposBasicos` (49 KB contra 62 KB) |
| **`PL_010e_v1.02`** | 10/07/2026 | leiaute de 08/07 22:14 — **é exatamente o que está instalado** |

O `010d` e o `010e` saíram no mesmo dia e são **revisões diferentes** do mesmo
leiaute, com 7 horas de diferença: o `010e` é a mais nova. O único elemento que
o `010d` tem e o `010e` não é o `pISEspec`, renomeado para `adRemIS` (alíquota
*ad rem* do Imposto Seletivo). Não é conteúdo perdido.

### O que o `PL_010d` traz que o projeto não tem

O `010d` é o pacote de **serviços**, e é aí que ele não se sobrepõe ao `010e`.
São 17 XSDs de eventos e consultas, todos compilando sem erro, cada um com sua
raiz global — nenhuma delas suportada hoje:

| Serviço | Arquivos | Raízes |
| --- | --- | --- |
| Eventos (cancelamento, CC-e, manifestação) | `envEvento_v1.00`, `retEnvEvento_v1.00`, `procEventoNFe_v1.00`, `leiauteEvento_v1.00` | `envEvento`, `retEnvEvento`, `procEventoNFe` |
| Consulta situação da nota | `consSitNFe_v4.00`, `retConsSitNFe_v4.00`, `leiauteConsSitNFe_v4.00` | `consSitNFe`, `retConsSitNFe` |
| Inutilização de numeração | `leiauteInutNFe_v4.00`, `procInutNFe_v4.00` | `ProcInutNFe` |
| Consulta cadastro de contribuinte | `consCad_v2.00`, `retConsCad_v2.00`, `leiauteConsultaCadastro_v2.00` | `ConsCad`, `retConsCad` |
| Retorno do recibo do lote | `retConsReciNFe_v4.00` | `retConsReciNFe` |

Suportá-los seria estender `ENTRADA_POR_RAIZ` (ver abaixo) com essas raízes e
criar as pastas correspondentes — trabalho de recurso novo, não de atualização
de schema. Nada disso foi instalado.

### Verificar

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
| `nfe_v4.00.xsd` | `NFe` | nota isolada, sem envelope (`nfce_v4.00.xsd` na NFC-e) |
| `enviNFe_v4.00.xsd` | `enviNFe` | o que o ERP monta e transmite à SEFAZ |
| `procNFe_v4.00.xsd` | `nfeProc` | nota autorizada (NFe + protNFe) |
| `retEnviNFe_v4.00.xsd` | `retEnviNFe` | retorno do lote |

A raiz `NFe` fica **fora** de `ENTRADA_POR_RAIZ` de propósito: o nome do arquivo
de entrada dela varia por tipo de documento (`nfe_` x `nfce_`), então quem
resolve é `ARQUIVOS_ENTRADA`. Fixá-la no mapa por raiz apontaria a NFC-e para
`nfe_v4.00.xsd`, que não existe em `nfce/`.

Os três últimos vieram do pacote `PL_010B_NT2025_002_v130` usado pelo ERP.
O `leiauteNFe_v4.00.xsd` **não** foi substituído — ver a comparação com os
pacotes baixados na seção anterior: o instalado é o mais novo dos três, e trocar
seria downgrade.

## Adicionando uma nova versão de layout (RN14)

Quando sair uma versão nova (ex. `4.01`), **não altere código**: crie
`v4.01/nfe/` (e/ou `nfce/`) com os XSDs correspondentes. O sistema escolhe o
schema pelo atributo `versao` lido do próprio XML (RN02/RN03), e falha
explicitamente se a versão não estiver instalada (RN15) — nunca valida contra a
versão errada em silêncio.

Depois de adicionar uma versão, se o projeto estiver instalado, rode
`pip install .` de novo.
