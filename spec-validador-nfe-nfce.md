# Especificação do Sistema — Validador de XML de NF-e/NFC-e

> Este documento é a fonte única de verdade do projeto. Qualquer agente de IA (Claude Code ou outro) que for implementar este sistema deve seguir estritamente as regras de negócio da Seção 3 e o passo a passo da Seção 7. Nada fora do escopo definido na Seção 8 deve ser implementado sem confirmação explícita do responsável pelo projeto.

## 1. Objetivo

Construir um validador de arquivos XML de **Nota Fiscal Eletrônica (NF-e, modelo 55)** e **Nota Fiscal de Consumidor Eletrônica (NFC-e, modelo 65)** que:

1. Recebe o conteúdo de um XML (texto colado ou arquivo `.xml` enviado).
2. Verifica se o XML está bem-formado (sintaxe).
3. Valida o XML contra o **XSD oficial** correspondente ao layout e à versão declarados no próprio documento.
4. Aplica regras de negócio complementares que o XSD sozinho não cobre (dígitos verificadores, consistência de valores, etc.).
5. Devolve um relatório claro de erros e avisos, com a localização exata do problema no XML.

## 2. Escopo

**Dentro do escopo:**
- Validação estrutural (XSD) de NF-e (mod. 55) e NFC-e (mod. 65).
- Suporte ao layout nacional vigente (atualmente baseado na versão 4.00, com os grupos adicionais da Reforma Tributária — IBS/CBS/IS — que estão sendo introduzidos ao longo de 2026 via Notas Técnicas do ENCAT/CONFAZ).
- Validação offline (não depende de consulta a web service da SEFAZ).
- Validações de negócio adicionais listadas na Seção 3.3.

**Fora do escopo (ver Seção 8 para detalhes):** emissão de NF-e, assinatura digital, transmissão para SEFAZ, geração de DANFE, consulta de situação na SEFAZ.

## 3. Regras de Negócio (o agente NÃO pode fugir destas regras)

### 3.1 Identificação do documento
- **RN01** — O sistema deve identificar automaticamente se o XML é uma NF-e ou NFC-e lendo o campo `mod` (55 = NF-e, 65 = NFC-e) dentro do grupo `ide`, e não pelo nome do arquivo.
- **RN02** — O sistema deve identificar a versão do layout pelo atributo `versao` presente na tag raiz `<NFe>`/`<infNFe>` (ex.: `4.00`).
- **RN03** — Se a versão do layout não for suportada pelo conjunto de XSDs disponíveis no sistema, o processo deve **parar e informar claramente** qual versão foi encontrada e quais são suportadas — nunca tentar validar contra um schema incompatível "no chute".

### 3.2 Validação estrutural (XSD)
- **RN04** — O XML deve primeiro ser checado quanto a **boa formação** (well-formed). Se falhar aqui, a validação de schema nem deve ser tentada — o erro de sintaxe deve ser reportado imediatamente.
- **RN05** — A validação de schema deve usar **exclusivamente os arquivos XSD oficiais** publicados pela SEFAZ/ENCAT (portal nacional `www.nfe.fazenda.gov.br` ou portais estaduais homologados, ex. SVRS). O agente **não pode inventar, resumir ou recriar de memória** as regras de um XSD — os arquivos `.xsd` reais devem ser obtidos e usados como estão.
- **RN06** — O namespace correto (`http://www.portalfiscal.inf.br/nfe`) deve ser respeitado; XML sem namespace ou com namespace divergente deve ser rejeitado com mensagem explicando o motivo.
- **RN07** — Cada erro de validação de schema deve ser reportado com: caminho XPath do elemento, linha/coluna (quando disponível), e a mensagem original do validador, sem reescrever ou "traduzir" a regra de forma imprecisa.

### 3.3 Regras de negócio complementares (além do XSD)
O XSD garante apenas estrutura e tipos. As regras abaixo são adicionais e obrigatórias:
- **RN08** — Validar o **dígito verificador da Chave de Acesso** (44 dígitos, campo `Id` da tag `infNFe`, prefixo `NFe`), recalculando o módulo 11 e comparando com o último dígito.
- **RN09** — Validar que os dados da Chave de Acesso (UF, AAMM, CNPJ do emitente, modelo, série, número, tipo de emissão, código numérico) **batem exatamente** com os mesmos campos declarados no corpo do XML (grupo `ide` e `emit`).
- **RN10** — Validar dígitos verificadores de **CNPJ e CPF** presentes em `emit`, `dest` e demais grupos que os contenham.
- **RN11** — Validar que a soma dos itens (`vProd`, `vDesc`, impostos) bate com os totais declarados no grupo `ICMSTot`, dentro de uma tolerância de arredondamento definida (ex.: R$ 0,01 por item).
- **RN12** — Validar formato de datas (`dhEmi`, `dhSaiEnt`) conforme ISO 8601 com timezone, como exigido pelo layout.
- **RN13** — Essas regras de negócio devem ser implementadas como **módulos independentes e nomeados**, cada um podendo ser ativado/desativado individualmente — nunca embutidas de forma implícita dentro do parser.

### 3.4 Atualização de schemas
- **RN14** — Como o layout está em constante evolução (Reforma Tributária, Notas Técnicas do CONFAZ/ENCAT ao longo de 2026), o sistema deve manter os XSDs **versionados em pasta própria** (ex. `/schemas/v4.00/`), permitindo adicionar novas versões sem alterar o código de validação.
- **RN15** — O sistema nunca deve validar "silenciosamente" contra a versão errada — se houver ambiguidade de versão, deve falhar de forma explícita.

### 3.5 Saída do sistema
- **RN16** — O resultado da validação deve ser sempre um objeto estruturado (ex. JSON) contendo: `valido` (booleano), `tipoDocumento` (NFe/NFCe), `versaoLayout`, `erros` (lista) e `avisos` (lista), nunca apenas texto livre.
- **RN17** — Cada item de `erros`/`avisos` deve conter no mínimo: `codigo`, `campo`/`xpath`, `mensagem`, `origem` (`xsd` ou `regra-negocio`).

## 4. Requisitos Funcionais

| ID | Requisito |
|----|-----------|
| RF01 | Aceitar entrada via upload de arquivo `.xml` |
| RF02 | Aceitar entrada via texto colado diretamente (string XML) |
| RF03 | Detectar automaticamente NF-e vs NFC-e e a versão do layout |
| RF04 | Validar boa formação do XML |
| RF05 | Validar contra o XSD correspondente |
| RF06 | Executar as regras de negócio complementares (Seção 3.3) |
| RF07 | Gerar relatório estruturado de erros/avisos |
| RF08 | Permitir validar múltiplos arquivos em lote (opcional, definir se entra no MVP) |
| RF09 | Exibir/exportar o relatório em formato legível (ex. tela + JSON/CSV) |

## 5. Requisitos Não-Funcionais

- **RNF01** — Validação 100% offline (sem chamadas à SEFAZ), exceto para atualizar os arquivos XSD localmente quando solicitado.
- **RNF02** — Tempo de resposta: validar um XML individual em menos de 2 segundos em condições normais.
- **RNF03** — Código modular, separando: (a) parsing, (b) validação de schema, (c) regras de negócio, (d) formatação de saída.
- **RNF04** — Cobertura de testes automatizados para cada regra de negócio (RN08 a RN12, no mínimo).
- **RNF05** — Logs claros de qual versão de XSD foi usada em cada validação, para rastreabilidade.

## 6. Contrato de Entrada e Saída

**Entrada:**
```json
{
  "conteudoXml": "<NFe xmlns=...>...</NFe>",
  "origem": "upload" 
}
```

**Saída esperada:**
```json
{
  "valido": false,
  "tipoDocumento": "NFe",
  "versaoLayout": "4.00",
  "chaveAcesso": "35260112345678000199550010000001231000001238",
  "erros": [
    {
      "codigo": "XSD-001",
      "xpath": "/NFe/infNFe/ide/dhEmi",
      "mensagem": "Formato de data inválido",
      "origem": "xsd"
    },
    {
      "codigo": "RN08",
      "campo": "chaveAcesso",
      "mensagem": "Dígito verificador da chave de acesso não confere",
      "origem": "regra-negocio"
    }
  ],
  "avisos": []
}
```

## 7. Passo a Passo de Implementação (ordem obrigatória)

1. **Preparar os schemas oficiais**
   - Baixar os XSDs oficiais da versão 4.00 (NF-e e NFC-e) do portal nacional (`www.nfe.fazenda.gov.br`) ou de um portal estadual homologado (ex. SVRS).
   - Organizar em pastas por versão: `/schemas/v4.00/nfe/`, `/schemas/v4.00/nfce/`.
   - Nunca reescrever XSDs à mão — usar os arquivos originais.

2. **Implementar o parser e checagem de boa formação**
   - Usar uma biblioteca XML nativa e confiável da linguagem escolhida (ex. `lxml`/`xmlschema` em Python, `libxmljs2` em Node).
   - Retornar erro imediato e específico se o XML não for bem-formado (RN04).

3. **Implementar a detecção de tipo/versão**
   - Ler `mod` e `versao` do XML (RN01, RN02).
   - Selecionar dinamicamente o XSD correto com base nesses valores (RN03).

4. **Implementar a validação de schema**
   - Validar o XML contra o XSD selecionado.
   - Capturar todos os erros do validador (não só o primeiro), com XPath e linha/coluna quando a biblioteca permitir (RN07).

5. **Implementar os módulos de regra de negócio (RN08–RN12)**
   - Cada regra em um arquivo/função isolada, com nome próprio e testável individualmente (RN13).
   - Implementar primeiro: dígito verificador da chave de acesso (RN08) e consistência chave x corpo do XML (RN09), por serem as mais críticas.
   - Em seguida: validação de CNPJ/CPF (RN10), totais (RN11) e datas (RN12).

6. **Implementar a camada de saída**
   - Consolidar erros do XSD + erros de regras de negócio no formato definido na Seção 6.
   - Garantir que `valido = true` só ocorre quando não há nenhum erro (avisos não bloqueiam).

7. **Criar interface de entrada**
   - Endpoint/função que aceita upload de arquivo ou texto colado (RF01, RF02).
   - Validar que o texto recebido não está vazio e é XML antes de processar.

8. **Escrever testes automatizados**
   - Casos de XML válido (NF-e e NFC-e).
   - Casos de XML malformado.
   - Casos de XML válido na sintaxe mas com XSD violado (campo obrigatório faltando, tipo errado).
   - Casos de XML válido no XSD mas que falha em cada regra de negócio (RN08 a RN12) individualmente.

9. **Documentar o mecanismo de atualização de schema**
   - Instruções de como adicionar uma nova versão de layout sem alterar a lógica principal (RN14).

10. **Revisão final contra este documento**
    - Antes de considerar o sistema pronto, revisar cada RN e RF desta especificação e confirmar que foi atendido ou explicitamente adiado com justificativa.

## 8. Fora de Escopo (não implementar sem pedido explícito)

- Emissão, assinatura digital ou transmissão da NF-e/NFC-e para a SEFAZ.
- Geração de representação gráfica (DANFE).
- Consulta de status/cancelamento junto à SEFAZ.
- Suporte a outros documentos fiscais eletrônicos (CT-e, MDF-e, NFS-e) — só entram se o escopo for expandido explicitamente.
- Interface visual complexa — o MVP pode ser via linha de comando, API ou upload simples; design de UI só entra se solicitado.

## 9. Fontes Oficiais para os XSDs

- Portal Nacional da NF-e: `https://www.nfe.fazenda.gov.br`
- Portal SVRS (documentação técnica e notas técnicas): `https://dfe-portal.svrs.rs.gov.br/NFe/Documentos`

> Observação importante: o layout está sendo atualizado ao longo de 2026 por causa da Reforma Tributária (inclusão de campos de IBS/CBS/IS via Notas Técnicas do CONFAZ/ENCAT, ex. NT 2025.002 e NT 2026.002). O agente deve sempre confirmar qual é a versão de XSD vigente no momento da implementação e não assumir de memória que a versão 4.00 "pura" (sem os grupos da reforma) ainda é suficiente, dependendo da data em que o projeto for construído.

## 10. Critérios de Aceite (Definition of Done)

- [ ] Um XML de NF-e válido é aceito com `valido: true` e lista de erros vazia.
- [ ] Um XML de NFC-e válido é aceito com `valido: true` e lista de erros vazia.
- [ ] Um XML malformado retorna erro de sintaxe sem tentar validar schema.
- [ ] Um XML bem-formado mas violando o XSD retorna os erros específicos com XPath.
- [ ] Um XML com chave de acesso adulterada é rejeitado pela RN08.
- [ ] Um XML com CNPJ inválido é rejeitado pela RN10.
- [ ] Todas as regras de negócio (RN08–RN12) têm teste automatizado próprio e passam.
- [ ] O sistema não faz nenhuma chamada de rede em tempo de validação (RNF01).
