# Validador de XML — NF-e / NFC-e

Implementação inicial (MVP) da especificação `spec-validador-nfe-nfce.md`.
Valida XML de Nota Fiscal Eletrônica (NF-e, mod. 55) e Nota Fiscal de
Consumidor Eletrônica (NFC-e, mod. 65), e — para cada erro encontrado —
explica **por que a nota seria rejeitada pela SEFAZ/Receita**, não apenas
"campo inválido".

## Requisitos

- Python 3.10+
- `lxml` (única dependência externa; usada para parsing e validação de XSD)

Instalar como pacote:
```bash
pip install .
```

Isso disponibiliza os comandos `nfe-validator` e `nfe-validator-dd`, e leva os
XSDs oficiais junto — eles ficam **dentro** de `nfe_validator/schemas/` de
propósito. Fora do pacote, um ambiente instalado ficaria sem nenhum XSD e o
validador degradaria em silêncio para o aviso `XSD-INDISPONIVEL` em toda nota,
perdendo a validação estrutural, a RN19 e as descrições oficiais de campo.

Para rodar sem instalar, basta `lxml` e `python -m nfe_validator` na raiz.

## Estrutura do projeto

```
pyproject.toml         -> empacotamento (pip install .), declara os XSDs como package-data
nfe_validator/
  __init__.py          -> expõe validar()
  __main__.py           -> CLI (python -m nfe_validator arquivo.xml)
  parser.py              -> boa formação + identificação de tipo/versão + extração de campos
  schema.py               -> validação contra XSD oficial + classificação da mensagem do libxml2
  layout.py               -> LEITOR do XSD: descrições oficiais, obrigatoriedade por variante, CST -> grupo
  coletor_erp.py          -> coleta XMLs que o ERP deixou no disco (out/*.out.txt, .xml) e revalida em lote
  gerador_dd.py           -> gera o dicionário .dd que o ERP sabe ler e nunca teve
  web/
    servidor.py             -> POST /api/validar + serve a UI (http.server da stdlib)
    estatico/               -> index.html, estilo.css, app.js (sem biblioteca externa)
  localizacao.py          -> xpath técnico -> localização legível ("Item 3 > grupo ICMS00 > linha 28")
  catalogo_erros.py       -> explicação de negócio por campo + composição da mensagem em 4 camadas
  validador.py             -> orquestrador (junta tudo, deduplica, ordena e resume)
  regras/
    campos_obrigatorios.py  -> RN18 (campos não preenchidos, independente de XSD)
    obrigatorios_condicionais.py -> RN19 (campos exigidos por CST/grupo, derivados do XSD)
    chave_acesso.py         -> RN08/RN09 (dígito verificador + consistência da chave)
    documento_fiscal.py     -> RN10 (CNPJ/CPF)
    totais.py                -> RN11 (consistência de valores)
    datas.py                  -> RN12 (formato de data/hora)
  schemas/                  -> DENTRO do pacote, para viajar no pip install
    README.md                 -> como obter e instalar os XSDs oficiais
    v4.00/nfe/                 -> XSDs oficiais de NF-e: INSTALADOS, com os pontos de
                                  entrada de envelope (nfe_, enviNFe_, procNFe_, retEnviNFe_)
    v4.00/nfce/                -> VAZIO: NFC-e ainda roda só em modo aviso
tests/
  test_regras.py             -> suíte de testes das regras de negócio (unittest, sem dependências)
  test_descricao_erros.py    -> suíte da descrição de erros (classificação, composição, RN18)
  test_layout.py             -> suíte do leitor de XSD (lógica + contrato com o leiaute oficial)
  test_condicionais.py       -> suíte da RN19 (com ênfase em não gerar falso positivo)
  test_integracao_erp.py     -> suíte dos achados vindos das notas reais do ERP
  test_gerador_dd.py         -> suíte do contrato do .dd com o leitor Java do ERP
  test_cli.py                -> suíte do CLI: códigos de saída e formato do CSV
  test_web.py                -> suíte da UI: endpoint, servidor e contrato do front
enviNFe_v4.00.dd             -> ARTEFATO DE ENTREGA: dicionário de campos para o ERP
  demo_xsd_error_translation.py -> demonstração isolada da tradução de erro de XSD
  fixtures/nfe_exemplo_invalida.xml -> XML de exemplo com erros propositais
```

## Como rodar

Validar um arquivo (relatório legível, agrupado por erro):
```bash
python3 -m nfe_validator tests/fixtures/nfe_exemplo_invalida.xml
```

Ver **só o que falta preencher** na nota — a pergunta mais frequente de quem
recebe a nota rejeitada:
```bash
python3 -m nfe_validator minha_nota.xml --so-nao-preenchidos
```

Sair em JSON, para integração:
```bash
python3 -m nfe_validator minha_nota.xml --json
```

Exportar em CSV (RF09) — uma linha por erro, pronto para abrir no Excel:
```bash
python3 -m nfe_validator minha_nota.xml --csv > erros.csv
python3 -m nfe_validator "C:\caminho\out" --lote --csv > erros_do_lote.csv
```

Separador `;` e BOM UTF-8, porque o destino é o Excel em português: com `,` ele
joga tudo numa coluna só, e sem BOM os acentos aparecem quebrados. No modo
`--lote` a coluna `arquivo` diz de qual XML veio cada linha.

Códigos de saída: **0** nota válida, **1** nota com erro, **2** erro de uso.

## Interface de arrastar-e-soltar

```bash
nfe-validator-web              # abre o navegador em http://127.0.0.1:8765
nfe-validator-web --porta 9000 --sem-navegador
```

Ou sem instalar: `python -m nfe_validator.web.servidor`.

Arraste o XML na área central, clique para escolher pelo seletor do sistema, ou
cole o conteúdo como texto — os três caminhos chamam o **mesmo** backend. O
resultado mostra o status em destaque, os metadados da nota e um cartão por
erro com a explicação de negócio em primeiro plano e os detalhes técnicos
(`xpath`, `linha`, `mensagem_tecnica`) recolhidos.

Implementa `spec-ui-drag-and-drop.md`. Pontos que valem registro:

* **Escuta só em `127.0.0.1` por padrão.** Um XML de NF-e carrega CNPJ, valores
  e dados de cliente; expor isso na rede por acidente é pior que ter de digitar
  `--host`. Se você mudar o host, o servidor avisa no terminal.
* **Nenhuma biblioteca no front** (RNF-UI03): drag-and-drop é a API nativa do
  HTML5, e o CSS é próprio. Nada é baixado de CDN.
* **Zero dependência nova no back.** A spec sugeria FastAPI/Flask como
  *exemplo*; usamos a `http.server` da stdlib, o que mantém a única dependência
  do projeto em `lxml`. `processar_validacao()` é agnóstica de framework —
  montar em FastAPI depois é escrever a rota e chamá-la.
* **O front não valida nada** (Seção 2 da spec). A única checagem no cliente é
  extensão `.xml`, tamanho e texto não vazio. Um teste verifica isso lendo o
  próprio `app.js`, porque é o desvio mais provável de acontecer.
* **Nada persiste** (RN-UI11): sem `localStorage`, sem cookie, e
  `Cache-Control: no-store` em toda resposta.
* Este servidor **não é endurecido para produção** — a própria documentação da
  `http.server` avisa. Para uma ferramenta local rodando na máquina de quem usa,
  é adequado; para expor a um time, ponha atrás de um servidor de verdade.

Rodar sem a validação de schema (só as regras de negócio e a RN18):
```bash
python3 -m nfe_validator minha_nota.xml --sem-xsd
```

Revalidar **em lote** o que o ERP deixou no disco — a pasta `out/` do monitor,
ou qualquer pasta com `.xml`:
```bash
python3 -m nfe_validator "C:\caminho\para\SERVER-WELD
fe_baixadas" --lote
python3 -m nfe_validator "C:\caminho\para\out" --lote --json
```

Validar via stdin:
```bash
cat minha_nota.xml | python3 -m nfe_validator -
```

Rodar os testes automatizados:
```bash
python3 -m unittest discover -s tests -p "test_*.py" -v
```

Ver a demonstração isolada de tradução de erro (o exemplo "vBC do ICMS vazio"):
```bash
python3 tests/demo_xsd_error_translation.py
```

## Formato de saída

Todo resultado segue o contrato definido na especificação (RN16/RN17), agora
com `resumo` e com o bloco `detalhe` em cada erro:

```json
{
  "valido": false,
  "tipoDocumento": "NFe",
  "versaoLayout": "4.00",
  "chaveAcesso": "...",
  "erros": [
    {
      "codigo": "RN18-VAZIO",
      "campo": "Base de Cálculo do ICMS (vBC)",
      "xpath": "/NFe/infNFe/det[1]/imposto/ICMS/ICMS00/vBC",
      "linha": 29,
      "mensagem_tecnica": "vBC: vazio",
      "mensagem": "Item 1 da nota > grupo <ICMS00> > linha 29 do XML: Base de Cálculo do ICMS (vBC) - o campo existe no XML mas está em branco (tag aberta e fechada sem conteúdo). Por que isso impede o envio: ...  Como corrigir: ...",
      "motivo_rejeicao": "(idem `mensagem` — alias mantido porque é o nome usado na spec da UI, RN-UI07)",
      "origem": "regra-negocio",
      "subOrigem": "campo-obrigatorio",
      "severidade": "erro",
      "detalhe": {
        "campo": "Base de Cálculo do ICMS (vBC)",
        "tagXml": "vBC",
        "tipoViolacao": "vazio",
        "valorInformado": null,
        "esperado": null,
        "onde": "Item 1 da nota > grupo <ICMS00> > linha 29 do XML",
        "oQueAconteceu": "o campo existe no XML mas está em branco (tag aberta e fechada sem conteúdo)",
        "porQueRejeita": "vBC é a base de cálculo do ICMS: é sobre esse valor que a alíquota (pICMS) é aplicada ...",
        "comoCorrigir": "Informe a base de cálculo do item (normalmente vProd + frete + seguro ...)",
        "catalogado": true
      }
    }
  ],
  "avisos": [],
  "resumo": {
    "totalErros": 40,
    "totalAvisos": 0,
    "porOrigem": { "xsd": 8, "regra-negocio": 32 },
    "porSubOrigem": { "schema": 8, "campo-obrigatorio": 27, "chave-acesso": 2, "documento-fiscal": 2, "totais": 1 },
    "porTipoViolacao": { "obrigatorio_ausente": 28, "vazio": 1, "estrutura_inesperada": 5 },
    "porLocal": { "item 1": 11, "nota (fora dos itens)": 29 },
    "camposNaoPreenchidos": [ { "campo": "...", "situacao": "vazio", "onde": "...", "comoCorrigir": "..." } ],
    "totalCamposNaoPreenchidos": 30,
    "xsdAplicado": true
  }
}
```

### Como a descrição de cada erro é montada

`motivo_rejeicao` deixou de ser um texto fixo por campo. Ele é composto de
quatro camadas, disponíveis separadamente em `detalhe`:

| Camada | Campo em `detalhe` | Responde | Vem de |
| --- | --- | --- | --- |
| **Onde** | `onde` | em que item, grupo e linha está o problema | `localizacao.py`, a partir do xpath |
| **O que** | `oQueAconteceu` | o que exatamente há de errado com o valor | `DIAGNOSTICOS[tipoViolacao]` |
| **Por que** | `porQueRejeita` | qual o papel fiscal do campo e por que a SEFAZ recusa | `CATALOGO_CAMPOS[campo].motivo` |
| **Como** | `comoCorrigir` | a ação concreta para resolver | `.como_corrigir` ou `ORIENTACOES[tipoViolacao]` |

Isso corrige um problema da versão anterior: se o campo estivesse no catálogo,
o texto do catálogo era usado e o **tipo real** da violação era descartado —
um `vBC` com valor `1.234,56` recebia a mensagem "está vazio ou ausente" e
mandava o usuário procurar o problema errado. Agora o catálogo *enriquece* o
diagnóstico técnico em vez de substituí-lo, e um campo que não está no
catálogo ainda recebe as camadas Onde / O que / Como — nunca sobra erro
"cru" para o usuário.

### Procedência de cada erro: `origem` e `subOrigem`

A **RN17** fixa `origem` em exatamente dois valores, e a spec da UI declara
consumir esse contrato. Então `origem` responde apenas *"quem deu o veredito"*,
e a granularidade de *"qual regra falou"* vive em `subOrigem`, que é aditivo:

| `origem` (RN17) | `subOrigem` | Regra | O que produz |
| --- | --- | --- | --- |
| `xsd` | `schema` | RN03/RN05 | veredito do libxml2 contra o XSD oficial |
| `regra-negocio` | `sintaxe` | RN04 | XML mal-formado |
| `regra-negocio` | `identificacao` | RN01/RN02 | tipo/versão não identificados |
| `regra-negocio` | `campo-obrigatorio` | RN18 | campos não preenchidos |
| `regra-negocio` | `chave-acesso` | RN08/RN09 | DV e consistência da chave |
| `regra-negocio` | `documento-fiscal` | RN10 | CNPJ/CPF |
| `regra-negocio` | `totais` | RN11 | conferência de valores |
| `regra-negocio` | `datas` | RN12 | formato de data/hora |
| `regra-negocio` | `configuracao` | RN05 | XSD ausente no ambiente (aviso) |

Só o libxml2 é `origem: xsd`. Toda regra nossa é `regra-negocio`, **mesmo
quando fala sobre estrutura** — a RN18 verifica preenchimento, não schema, e
misturar as duas coisas faria o relatório mentir sobre quem rejeitou o quê.

A `origem` é sempre **derivada** da `subOrigem` em `validador._normalizar()`,
nunca declarada duas vezes; um teste garante que as duas não divergem.

Sobre nomes de campo: a RN17 nomeia a chave **`mensagem`**, e a spec da UI
(RN-UI07) nomeia **`motivo_rejeicao`**. Ambas existem e carregam o mesmo texto —
`motivo_rejeicao` é alias de `mensagem`. `mensagem_tecnica` é coisa diferente:
é a mensagem crua do validador, preservada porque a **RN07** exige não
reescrever nem "traduzir" a regra original.

### Tipos de violação reconhecidos

O classificador de `schema.py` traduz a mensagem crua do libxml2 em um destes
tipos (antes, quase tudo caía em `estrutura_inesperada`):

`obrigatorio_ausente`, `vazio`, `so_espacos`, `zero_indevido`,
`tipo_invalido`, `decimal_invalido`, `fora_do_padrao`, `fora_da_enumeracao`,
`tamanho_invalido`, `estrutura_inesperada`, `grupo_incompleto`,
`grupo_exclusivo_violado`.

Os facets do XSD (`enumeration`, `pattern`, `length`, ...) agora têm a lista
de valores aceitos **preservada** em `detalhe.esperado`, então a orientação de
correção pode dizer *qual* é o padrão esperado, e não apenas que o valor está
fora dele.

### De onde vêm as descrições dos campos

O catálogo escrito à mão (`catalogo_erros.py`) descreve 22 campos. O leiaute da
NF-e tem 898. Antes, os outros ~876 recebiam a frase genérica *"'X' é exigido
pelo layout da NF-e/NFC-e neste ponto do XML"*.

O `layout.py` resolve isso lendo o que o XSD oficial **já traz**: 1.036 blocos
`xs:documentation`, cobrindo 97,9% dos campos indexados, em português. Isso
atende a **RN05** (*"não pode inventar, resumir ou recriar de memória as regras
de um XSD"*) de um jeito que uma tabela escrita à mão não atenderia.

Precedência ao montar a mensagem:

| Ordem | Fonte | `detalhe.fonte` |
| --- | --- | --- |
| 1 | `CATALOGO_CAMPOS["GRUPO.TAG"]` / `["TAG"]` — escrito à mão | `catalogo` |
| 2 | `xs:documentation` do XSD oficial, **citado** entre aspas | `xsd` |
| 3 | texto genérico por tipo de violação | `generico` |

O catálogo à mão vence sempre: é fiscalmente mais rico que *"Valor da BC do
ICMS"*. E as camadas **nome** e **por que** usam limiares **diferentes** sobre
a mesma documentação — é esse detalhe que impede a integração de *piorar*
mensagens:

* texto ≤ 60 caracteres serve como **nome** do campo (`xLgr` → "Logradouro"),
  mas não como justificativa fiscal;
* texto > 60 caracteres entra também como **justificativa**, citado
  literalmente (`indTot`, `NCM`, `modBC`).

Sem esse limiar, `CFOP` (cuja documentação oficial é literalmente `"Cfop"`)
substituiria uma frase genérica útil por uma inútil.

Quando o texto vem do XSD, o erro carrega `detalhe.origemXsd` com arquivo e
linha — dá para abrir o `.xsd` e conferir a afirmação. E os typos da SEFAZ
(`Tributção`, `Não tributda`) e marcadores `(v2.0)` são **preservados**:
corrigir a redação seria reescrever a regra, o que a RN07 proíbe.

Efeito medido no fixture de exemplo: as mensagens genéricas caíram de 34 para
**1** (o elemento raiz `NFe`, que não tem documentação no XSD).

### RN18 — campos não preenchidos

> **Sobre a numeração:** esta regra é a **RN18** porque a `spec-validador-nfe-nfce.md`
> já reserva a **RN13** para outra coisa — *"as regras de negócio devem ser
> implementadas como módulos independentes e nomeados"*. A RN18 é o próximo
> número livre na sequência da spec. Não reutilize RN13 para regras de campo.

`regras/campos_obrigatorios.py` varre a nota e reporta **todos** os campos
obrigatórios não preenchidos de uma vez, com o número do item, separando três
situações que exigem correções diferentes:

| Código | Situação |
| --- | --- |
| `RN18-AUSENTE` | a tag não existe no XML |
| `RN18-VAZIO` | a tag existe mas está em branco (`<vBC></vBC>`) |
| `RN18-ESPACOS` | a tag tem só espaços/quebras de linha |
| `RN18-GRUPO-AUSENTE` | o grupo inteiro falta (um erro só, não um por campo filho) |
| `RN18-IDENTIFICACAO-AUSENTE` | `<emit>` sem `CNPJ` nem `CPF` |
| `RN18-IDENTIFICACAO-DUPLICADA` | `CNPJ` e `CPF` informados no mesmo grupo |

Ela existe porque o XSD, sozinho, não cobre esses casos bem:

1. o XSD só roda se o schema oficial estiver instalado — sem ele, uma nota com
   metade dos campos em branco não gerava nenhum erro de preenchimento;
2. para tag ausente o libxml2 devolve sempre `Missing child element(s)`
   apontando para o **grupo**, e para no primeiro erro de cada grupo — então
   um `<emit>` sem `CNPJ`, sem `xNome` e sem `CRT` gerava **um** erro, e os
   outros dois só apareciam nas rodadas seguintes de correção;
3. o XSD aceita um campo preenchido só com espaços em tipos string, que a
   SEFAZ trata como não preenchido.

A varredura de tags vazias é genérica (vale para qualquer campo do layout, não
só os da tabela), porque o layout 4.00 não tem nenhum tipo simples que aceite
conteúdo vazio: se a tag existe, ela tem que ter valor.

### RN19 — obrigatoriedade condicional

`regras/obrigatorios_condicionais.py`. A RN18 cobre o que é obrigatório em
*qualquer* nota; a RN19 cobre o que é obrigatório **por causa do que a nota
declarou** — que é a origem da maior parte das rejeições reais.

| Código | Situação |
| --- | --- |
| `RN19-CONDICIONAL-AUSENTE` | campo exigido pela variante informada (ex.: `pRedBC` num `ICMS20`) |
| `RN19-CODIGO-INCOMPATIVEL` | CST/CSOSN declarado dentro de um grupo que não o aceita |
| `RN19-GRUPO-INCOMPLETO` | grupo opcional-em-conjunto preenchido pela metade (`pFCP` sem `vFCP`) |
| `RN19-ALTERNATIVA-VIOLADA` | caminhos XOR do layout (`IPITrib`: `vBC`+`pIPI` **ou** `qUnid`+`vUnid`) |

Nada disso está escrito no módulo: tudo sai do `layout.py`, que lê do XSD as 21
variantes do `xs:choice` do ICMS, os campos que cada complexType exige, os
grupos `<xs:sequence minOccurs="0">` e os `xs:choice` internos.

**A variante é lida do XML, não deduzida do CST.** Cinco CSTs do ICMS (10, 20,
41, 60 e 90) são enumerados em mais de uma variante — o CST 20 vale para
`ICMS20` **e** para `ICMSPart`. Então o caminho confiável é o inverso: ver qual
variante o XML abriu e conferir os campos dela. O CST serve para uma checagem
separada (ele combina com o grupo onde foi escrito?).

Ganho concreto sobre o XSD: num `ICMS00` sem `vBC`, `pICMS` e `vICMS`, o
libxml2 reporta **um** erro (`Missing child element(s)`, apontando o grupo) e o
usuário descobre os outros dois em ciclos de corrigir-e-reenviar. A RN19
reporta os **três**, cada um dizendo qual grupo criou a obrigação.

Um detalhe que a documentação oficial revelou e uma tabela de memória erraria:
`ICMSSN102` declara `orig` com `minOccurs="0"`, ao contrário de todas as
variantes de ICMS normal. Exigir `orig` ali geraria falso positivo em toda nota
de optante do Simples Nacional.

## Integração com o ERP (server-weld)

### Como o ERP entrega o XML antes de enviar à Receita

Rastreado em `server-impl/.../faturamento/nfe/NfeServico.java` e
`ServidorDocumentoEletronicoMonitor.java`:

1. o XML é montado por JAXB (`MarshallerUtils.marshal`) a partir das classes
   geradas de `nfe_schemas/PL_010B_NT2025_002_v120/leiauteNFe_v4.00.xsd`;
2. `ajustaXml()` corrige prefixos de namespace (`ns2:`, `ns3:`) e reinsere os
   `xmlns` de `<NFe>` e `<Signature>`;
3. `validate(xml, getXsd(...))` valida contra o XSD do pacote configurado,
   usando `javax.xml.validation` (SAX);
4. o XML assinado é guardado como anexo **`"NFE ENVIO XML"`**
   (`NFE_ENVIO_ANEXO_ID`) e, após autorização, o `procNFe` como **`"NFE XML"`**
   (`NFE_ANEXO_ID`). Os anexos vão para object storage (Cloudflare R2), não
   para disco local;
5. **quando a validação falha**, `NfeServico.validate()` despeja o XML inteiro
   no `System.err`, entre marcadores:

```
================ ERRO NFE ====================
<enviNFe ...>...</enviNFe>
==============================================
```

e `installOut()` redireciona `System.err`/`System.out` para
`out/monitor-nfe-<maquina>-<dd-MM-yy-HH-mm-ss>.out.txt`, expurgando arquivos com
mais de 5 dias.

**Então a pasta `out/` acumula o XML completo, pré-transmissão, de cada nota que
a SEFAZ teria rejeitado.** É o que o modo `--lote` consome.

### Duas limitações do lado do ERP

* **Um erro por vez.** A validação usa SAX e lança `BaseException` no primeiro
  problema. O operador corrige um campo, reenvia, e descobre o próximo. Este
  validador roda o XSD inteiro mais RN08–RN19 e devolve a lista completa.
* **A descrição do campo nunca aparece.** `getXSDTagInf()` lê a descrição de um
  arquivo `.dd` (Java Properties) ao lado do `.xsd` — e **não existe nenhum
  `.dd` no projeto** (`find -name "*.dd"` → 0). Logo a linha `Descrição:` da
  mensagem cai sempre no ramo `msg == null`, e o operador recebe só a mensagem
  crua do Xerces (`cvc-datatype-valid.1.2.1: ...`). É exatamente esse buraco
  que o `catalogo_erros` + `layout` preenchem.

### Pontos de entrada de envelope (do pacote PL_010B_NT2025_002_v130)

O ERP não transmite uma `<NFe>` nua: ele monta e valida um `<enviNFe>`, e o que
volta autorizado é um `<nfeProc>` (NFe + protNFe). Nosso pacote só tinha
`nfe_v4.00.xsd`, que declara a raiz global `NFe` — então toda nota autorizada
era reprovada com `No matching global declaration available for the validation
root`, um erro **nosso** disfarçado de erro da nota.

Trouxemos do pacote do ERP os três pontos de entrada que faltavam:
`enviNFe_v4.00.xsd`, `procNFe_v4.00.xsd` e `retEnviNFe_v4.00.xsd`. São wrappers
de ~600 bytes que só declaram a raiz global e incluem o mesmo
`leiauteNFe_v4.00.xsd` — e o nosso leiaute já definia `TEnviNFe`, `TNfeProc`,
`TRetEnviNFe` e `TProtNFe`, então compilam sem mais nada.

`schema.py` passou a escolher o XSD de entrada pela **raiz do documento**
(`ENTRADA_POR_RAIZ`). Resultado concreto: um `cStat` inválido dentro de
`protNFe` agora é detectado — antes esse ramo inteiro era invisível, porque
extraíamos a `<NFe>` e descartávamos o resto.

> **Sobre migrar o leiaute:** comparei definição por definição. O nosso
> `leiauteNFe_v4.00.xsd` tem **527** definições contra **520** do
> `PL_010B_NT2025_002_v130`, com 7 exclusivas nossas (`CNPJPAA`, `ISUFEmit`,
> `PAASignature`, `RSAKeyValue`, `SignatureValue`, `cIndOp`, `infPAA`) e
> **nenhuma** que só o PL tenha. Trocar o leiaute seria downgrade, então
> mantivemos o nosso e pegamos só o que faltava.

### O dicionário `.dd` para o ERP

`enviNFe_v4.00.dd` na raiz do projeto, gerado por
`python -m nfe_validator.gerador_dd enviNFe 4.00`. **1.016 chaves.**

É o arquivo que `NfeServico.getXSDTagInf()` procura e nunca encontrou. Basta
colocá-lo ao lado do `enviNFe_v4.00.xsd` no pacote de schemas do ERP para a
linha `Descrição:` passar a aparecer na mensagem de erro do operador.

Contrato respeitado (errar qualquer item produz arquivo que o ERP ignora sem
avisar):

| Item | Regra | De onde vem |
| --- | --- | --- |
| Nome | `enviNFe_v4.00.dd` | `getXSDTagInf()` faz `caminho.replace(".xsd", ".dd")` |
| Chave | `enviNFe.NFe.infNFe.det.prod.cProd` | `NfeReaderXML.pathToString()`: `localName` pontilhado, **sem índice** |
| Encoding | ASCII puro com `\uXXXX` | `Properties.load(InputStream)` lê ISO-8859-1 |
| Valor | uma linha só | quebra de linha encerraria o valor |

Dos 1.016 verbetes, **99** usam o catálogo de negócio deste projeto (com o
motivo da rejeição e como corrigir) e o restante usa o `xs:documentation`
oficial, copiado literalmente. Exemplo do que o operador passa a ver num `vBC`
vazio de ICMS00:

> **Descrição:** Base de Cálculo do ICMS (vBC). vBC é a base de cálculo do
> ICMS: é sobre esse valor que a alíquota (pICMS) é aplicada para chegar ao
> imposto devido (vICMS). (…) Como corrigir: Informe a base de cálculo do item
> (…) e garanta que vBC x pICMS / 100 = vICMS.

Regerar mantém o arquivo em sincronia com o XSD — não editar à mão.

### O que as notas reais do ERP corrigiram aqui

Rodar o validador contra as 24 NF-e reais **já autorizadas pela SEFAZ** em
`nfe_baixadas/` reprovou **todas as 24**. Nenhuma tinha erro — eram três bugs
nossos, hoje corrigidos e travados em `tests/test_integracao_erp.py`:

| Bug | Sintoma | Causa |
| --- | --- | --- |
| Envelope não reconhecido | 24/24 com `No matching global declaration` | os arquivos reais têm raiz `nfeProc` (NFe + protNFe); nosso `nfe_v4.00.xsd` declara só `NFe` |
| `cBenef` vazio acusado | 8 ocorrências | o pattern do XSD é `([!-ÿ]{8}\|[!-ÿ]{10}\|SEM CBENEF)?` — o `?` final **aceita vazio** |
| `infAdic` vazio acusado | 1 ocorrência | é um **grupo** sem filhos, não um campo em branco |
| `RN11-VNF` falso | 11/24 | comparávamos vNF com a soma de vProd, reprovando toda nota com frete, desconto, IPI ou ST |

A fórmula de vNF passou a ser a do MOC — `vProd + vST + vFCPST + vFrete + vSeg
+ vOutro + vII + vIPI + vIPIDevol + vServ - vDesc - vICMSDeson` — conferida
contra as 24 notas: **24 conferem, 0 divergem**. A mensagem agora traz a
memória de cálculo das parcelas não-zeradas.

Resultado após as correções: **24/24 notas autorizadas validam limpas.**

O `layout.py` ganhou duas consultas por causa disso: `aceita_vazio(tag)` e
`e_grupo(tag)`. Em vez de assumir "no leiaute 4.00 nenhuma tag folha pode estar
vazia" — premissa que o `cBenef` desmentiu —, perguntamos ao XSD.

> **Nota de escopo.** A pasta `nfe_baixadas/` guarda notas, eventos e resumos
> juntos. O modo `--lote` classifica `procEventoNFe`, `resNFe` e afins como
> *fora de escopo* em vez de reprová-los: a spec cobre NF-e e NFC-e (RN01), e
> chamar um evento de "nota inválida" seria ruído, não achado.

> **Pacotes de leiaute.** O ERP usa `nfe_schemas/PL_010B_NT2025_002_v130`
> (24 arquivos, com IBS/CBS da NT 2025.002) e tem os XSDs de envelope
> (`procNFe_v4.00.xsd`, `enviNFe_v4.00.xsd`) que faltam aqui. Enquanto não
> forem instalados, o envelope é desembrulhado e validamos a `<NFe>` interna —
> honesto, mas parcial.

## O que já está implementado (frente à especificação)

- [x] RF04 — boa formação do XML
- [x] RF03 — detecção automática de NF-e/NFC-e e versão do layout
- [x] RF05 — validação contra XSD **quando o XSD oficial estiver instalado** (ver `schemas/README.md`)
- [x] RF06 — regras de negócio complementares: chave de acesso (RN08/RN09), CNPJ/CPF (RN10), totais (RN11), datas (RN12)
- [x] RF07 — relatório estruturado de erros/avisos, com `motivo_rejeicao` em cada item
- [x] Catálogo de explicações de negócio (`catalogo_erros.py`) + fallback genérico por tipo de violação
- [x] RN18 — varredura de campos obrigatórios não preenchidos, independente do XSD
- [x] Explicação composta em 4 camadas (onde / o que / por que / como corrigir), com as partes expostas em `detalhe`
- [x] Localização legível do erro (`localizacao.py`): item, grupo tributário e linha, em vez de xpath cru
- [x] Deduplicação e ordenação dos erros + bloco `resumo` com as contagens e a lista de campos não preenchidos
- [x] RF09 — exportação em CSV (`--csv`), com separador e BOM que o Excel em português entende
- [x] UI de arrastar-e-soltar (`spec-ui-drag-and-drop.md`) — endpoint, página, acessibilidade por teclado, sem dependência nova
- [x] Empacotamento (`pyproject.toml`) com os XSDs dentro do pacote, verificado por instalação real
- [x] Relatório legível no CLI (`--so-nao-preenchidos`, `--json`, `--csv`, `--sem-xsd`)
- [x] `layout.py` — leitor do XSD oficial: descrição de 97,9% dos campos, obrigatoriedade por variante, mapa CST -> grupo, com rastreabilidade (arquivo + linha) exigida pela RN05
- [x] RN19 — obrigatoriedade condicional por CST/grupo, derivada do XSD (não de tabela escrita à mão)
- [x] Suporte a envelopes `nfeProc`/`enviNFe` (as formas que o ERP realmente grava e transmite)
- [x] RN11 com a fórmula de vNF do MOC, conferida contra 24 notas autorizadas reais
- [x] `--lote`: revalidação em massa dos XMLs que o ERP deixa em `out/` (atende parcialmente RF08)
- [x] Pontos de entrada de envelope (`enviNFe`, `nfeProc`, `retEnviNFe`) — valida o documento inteiro, inclusive `protNFe`
- [x] `gerador_dd.py` + `enviNFe_v4.00.dd`: 1.016 verbetes no formato que o ERP já sabe ler
- [x] Testes automatizados cobrindo cada regra de negócio + fluxo fim a fim

## O que falta para ir além do MVP

- [ ] Aplicar o `enviNFe_v4.00.dd` no projeto do ERP (entrega para o outro dev — lá este projeto é somente leitura)
- [ ] Gerar `.dd` para as outras raízes que o ERP valida (`consSitNFe`, `consReciNFe`, `inutNFe`) — o gerador já aceita a raiz como parâmetro
- [ ] Instalar os XSDs de **NFC-e** — a pasta `schemas/v4.00/nfce/` existe mas está **vazia**, então uma NFC-e (mod 65) hoje só recebe o aviso `XSD-INDISPONIVEL` e roda apenas as regras de negócio. (Os XSDs de **NF-e** já estão instalados em `schemas/v4.00/nfe/` e a validação estrutural funciona.)
- [ ] RF08 — validação em lote: `--lote` e `--csv` já cobrem pasta e log do ERP; falta paralelismo para volumes grandes
- [ ] Ampliar `catalogo_erros.py` com mais campos específicos (hoje cobre os campos mais críticos de ICMS/IPI/PIS/COFINS, identificação e totais — o fallback genérico cobre o restante, mas com menos precisão)
- [ ] Obrigatoriedade condicional que o XSD **não** contém e exige o MOC/Notas Técnicas: aritmética de totais, CST x CRT (regime do emitente), CFOP x UF, validade do NCM contra a tabela real, e CST de IBS/CBS (o `TCST` em `DFeTiposBasicos_v1.00.xsd` é só `pattern="\d{3}"`, sem enumeração — qualquer lista aqui seria invenção, RN05)
- [ ] Validar assinatura digital e demais grupos (transporte, cobrança, etc.), se entrarem no escopo

## Observação importante sobre o XSD

Os XSDs oficiais (v4.00) já estão instalados em `schemas/v4.00/nfe/` e a
validação estrutural completa está funcionando (testado e confirmado).

O arquivo `tests/fixtures/nfe_exemplo_invalida.xml` é uma fixture
**simplificada** para fins de teste — ela propositalmente tem o erro
`vBC` vazio, mas também omite campos que o layout oficial exige (como a
assinatura digital, fora do escopo deste projeto) e por isso gera erros
estruturais adicionais além do exemplo pretendido. Isso é esperado: o
importante é que cada erro, seja qual for, sempre venha com um
`motivo_rejeicao` em linguagem de negócio.
