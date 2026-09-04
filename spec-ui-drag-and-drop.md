# Especificação da UI — Validador de XML de NF-e/NFC-e (Drag-and-Drop)

> Este documento complementa `spec-validador-nfe-nfce.md` (regras de negócio e backend). Ele define **somente a interface web** que consome o validador já implementado. Qualquer agente de IA que for construir esta UI deve seguir estritamente as regras da Seção 3 e o passo a passo da Seção 7, e não deve reimplementar regras de validação que já existem no backend (Seção 2).

## 1. Objetivo

Criar uma página web simples onde o usuário possa **arrastar e soltar** (drag-and-drop) um arquivo XML de NF-e/NFC-e — ou selecioná-lo manualmente, ou colar o conteúdo — e ver instantaneamente o resultado da validação, com cada erro explicado em linguagem de negócio (por que a Receita/SEFAZ rejeitaria a nota), reaproveitando o validador Python já existente.

## 2. Relação com o backend (não reimplementar)

- A UI **não valida XML no navegador**. Ela apenas envia o conteúdo para um endpoint de backend que chama a função `validar()` do pacote `nfe_validator` já implementado.
- O contrato de resposta é exatamente o já definido na especificação do backend (`valido`, `tipoDocumento`, `versaoLayout`, `chaveAcesso`, `erros[]`, `avisos[]`, cada item de erro com `codigo`, `campo`, `xpath`, `linha`, `mensagem_tecnica`, `motivo_rejeicao`, `origem`). A UI apenas **exibe** esses campos — não decide motivos de rejeição, não duplica o catálogo de erros.
- **Endpoint sugerido (a implementar junto com a UI, fora do escopo de regra de negócio):**
  - `POST /api/validar` — corpo: `{ "conteudoXml": "<NFe ...>...</NFe>" }` — resposta: o JSON do contrato acima.
  - Deve envolver `nfe_validator.nucleo.validador.validar()` em um framework leve (ex. FastAPI/Flask), sem adicionar lógica de negócio nova nessa camada.

## 3. Regras de Negócio da UI (o agente NÃO pode fugir destas regras)

- **RN-UI01** — O usuário deve poder soltar (drag-and-drop) um único arquivo `.xml` em uma área claramente demarcada da tela.
- **RN-UI02** — A mesma área deve também aceitar clique para abrir o seletor de arquivos do sistema operacional (fallback para quem não usa drag-and-drop, incluindo acessibilidade via teclado).
- **RN-UI03** — Deve existir uma opção alternativa de **colar o XML como texto** (textarea), para quem não tem o arquivo salvo localmente. Drag-and-drop e colar texto são dois caminhos para o mesmo backend — nenhum deve ter lógica de validação diferente do outro.
- **RN-UI04** — Antes de enviar ao backend, a UI só deve fazer uma checagem trivial no cliente: o arquivo tem extensão `.xml` (ou o texto colado não está vazio). Qualquer validação de conteúdo (bem-formação, XSD, regras de negócio) é responsabilidade exclusiva do backend.
- **RN-UI05** — Enquanto a validação está em andamento, a UI deve mostrar um estado de carregamento claro (spinner/skeleton) — nunca deixar a tela parada sem feedback.
- **RN-UI06** — O resultado deve deixar óbvio, em destaque visual imediato (cor + ícone + texto), se a nota é **válida** ou **inválida** — sem obrigar o usuário a rolar a tela para descobrir.
- **RN-UI07** — Cada erro/aviso deve ser exibido como um cartão/linha individual mostrando, no mínimo: o **motivo em linguagem de negócio** (`motivo_rejeicao`) em destaque, e o campo técnico (`campo`/`xpath`) como informação secundária — nunca o inverso (não pode dar mais destaque ao XPath do que à explicação).
- **RN-UI08** — Erros (`erros[]`) e avisos (`avisos[]`) devem ser visualmente diferenciados (ex. vermelho para erro que bloqueia envio à SEFAZ, amarelo para aviso que não bloqueia).
- **RN-UI09** — Se o arquivo solto/colado não for um XML válido de NF-e/NFC-e (erro de identificação, ver `IDENTIFICACAO-FALHOU` no backend), a UI deve mostrar essa mensagem de forma amigável, sem quebrar a tela ou mostrar erro técnico bruto (stack trace) para o usuário final.
- **RN-UI10** — A UI deve permitir validar um novo arquivo facilmente após o resultado aparecer (botão "Validar outro arquivo" ou continuar aceitando novo drag-and-drop na mesma tela), sem precisar recarregar a página.
- **RN-UI11** — Nenhum dado do XML deve ser persistido/armazenado pela UI além da sessão atual do navegador, salvo se isso for pedido explicitamente em uma fase futura (histórico de validações). Por padrão: sem persistência.
- **RN-UI12** — A UI não deve tentar "corrigir" ou sugerir edição automática do XML — o escopo é validar e explicar, não editar (mesma regra de fora-de-escopo do backend).

## 4. Requisitos Funcionais

| ID | Requisito |
|----|-----------|
| RF-UI01 | Área de drop visível, com destaque visual quando um arquivo é arrastado sobre ela (`dragover`) |
| RF-UI02 | Clique na área de drop abre o seletor de arquivo nativo |
| RF-UI03 | Opção "colar XML" com textarea e botão para validar o texto colado |
| RF-UI04 | Exibição do nome do arquivo e tamanho após seleção/drop, antes de confirmar o envio |
| RF-UI05 | Estado de carregamento durante a chamada ao backend |
| RF-UI06 | Painel de resultado com status geral (válido/inválido), tipo de documento, versão do layout e chave de acesso |
| RF-UI07 | Lista de erros, cada um expansível para mostrar detalhes técnicos (`xpath`, `linha`, `mensagem_tecnica`) |
| RF-UI08 | Lista de avisos, separada visualmente dos erros |
| RF-UI09 | Botão para copiar o JSON completo do resultado (para quem quiser depurar) |
| RF-UI10 | Botão/ação para validar um novo documento sem recarregar a página |
| RF-UI11 | Mensagem de erro amigável para falhas de rede/servidor (backend fora do ar, timeout) |

## 5. Requisitos Não-Funcionais

- **RNF-UI01** — Interface responsiva (funciona em desktop e em telas menores/tablet).
- **RNF-UI02** — Acessibilidade: área de drop deve ser operável por teclado (foco + Enter/Espaço abre seletor de arquivo), contraste de cores adequado para os estados de erro/aviso/sucesso, textos alternativos em ícones.
- **RNF-UI03** — Nenhuma biblioteca pesada desnecessária — drag-and-drop nativo do navegador (`HTML5 Drag and Drop API`) é suficiente, sem necessidade de biblioteca externa só para isso.
- **RNF-UI04** — Tempo de resposta percebido: feedback visual em até 300ms após o drop/clique (mesmo que a validação em si demore mais, o "recebi seu arquivo" deve ser imediato).
- **RNF-UI05** — Tamanho máximo de arquivo aceito no cliente deve ser validado antes do envio (sugestão inicial: 5 MB — um XML de NF-e raramente passa disso; ajustável).

## 6. Estados da Tela (máquina de estados da UI)

```
[Ocioso / aguardando arquivo]
   -> usuário arrasta arquivo sobre a área  -> [Arrastando sobre a área] (destaque visual)
   -> usuário solta o arquivo OU seleciona via clique OU cola texto e confirma
        -> [Enviando para validação] (loading)
             -> sucesso da chamada -> [Resultado exibido] (válido ou inválido, com erros/avisos)
             -> falha de rede/servidor -> [Erro de comunicação] (mensagem amigável + botão "tentar novamente")
   a partir de [Resultado exibido]:
        -> "Validar outro arquivo" -> volta para [Ocioso / aguardando arquivo]
```

- Nenhum estado deve deixar a tela "travada" sem indicação do que está acontecendo (ligado à RN-UI05).

## 7. Passo a Passo de Implementação (ordem obrigatória)

1. **Expor o validador via API**
   - Criar um endpoint HTTP simples (`POST /api/validar`) que recebe `{ conteudoXml }` e chama `nfe_validator.nucleo.validador.validar()`.
   - Retornar o JSON exatamente como o `validar()` já produz — sem transformação de dados.
   - Tratar erros inesperados do backend (ex. exceção não prevista) devolvendo um JSON de erro padronizado (nunca um HTML de erro cru).

2. **Montar a estrutura básica da página**
   - Uma área de drop central, com texto instrutivo ("Arraste seu XML aqui ou clique para selecionar").
   - Um link/botão secundário para alternar para o modo "colar texto".

3. **Implementar drag-and-drop nativo**
   - Bind nos eventos `dragenter`, `dragover`, `dragleave`, `drop` do elemento da área de drop.
   - `dragover`: `preventDefault()` obrigatório (senão o navegador abre o arquivo direto).
   - `drop`: capturar `event.dataTransfer.files[0]`, checar extensão `.xml` (RN-UI04), ler conteúdo via `FileReader`/`file.text()`.

4. **Implementar seleção manual e colar texto**
   - `<input type="file" accept=".xml" hidden>` acionado pelo clique na área de drop.
   - Textarea + botão "Validar texto colado" como caminho alternativo (RN-UI03).

5. **Implementar o envio e o estado de carregamento**
   - Ao ter o conteúdo do XML (de qualquer uma das três origens), mostrar o estado de loading (RF-UI05) e chamar `POST /api/validar`.

6. **Implementar a exibição do resultado**
   - Cabeçalho de status (válido/inválido) com cor e ícone (RN-UI06).
   - Metadados: tipo de documento, versão do layout, chave de acesso.
   - Lista de erros: `motivo_rejeicao` em destaque, detalhes técnicos em um elemento expansível/colapsável (RF-UI07).
   - Lista de avisos, com estilo visualmente distinto dos erros (RN-UI08).

7. **Implementar os estados de erro de comunicação e o "validar outro arquivo"**
   - Tratar falha de rede/timeout com mensagem amigável e botão de nova tentativa (RF-UI11).
   - Botão para reiniciar o fluxo sem recarregar a página (RN-UI10).

8. **Revisão de acessibilidade e responsividade**
   - Testar navegação só por teclado.
   - Testar em uma largura de tela pequena (ex. 375px) e uma grande (ex. 1440px).

9. **Revisão final contra este documento**
   - Conferir cada RN-UI e RF-UI desta especificação.

## 8. Fora de Escopo (não implementar sem pedido explícito)

- Autenticação/login de usuários.
- Histórico de validações anteriores (persistência entre sessões).
- Upload/validação de múltiplos arquivos em lote na mesma tela (pode ser uma v2, mas não faz parte deste MVP de UI).
- Edição do XML na própria tela.
- Geração de DANFE ou qualquer visualização gráfica da nota fiscal em si (a UI mostra o **resultado da validação**, não a nota renderizada).
- Envio da nota para a SEFAZ a partir da UI.

## 9. Wireframe textual (referência de layout, não vincula tecnologia)

```
┌──────────────────────────────────────────────────────────┐
│  Validador de NF-e / NFC-e                                │
├──────────────────────────────────────────────────────────┤
│                                                            │
│     ┌────────────────────────────────────────────────┐   │
│     │                                                  │   │
│     │        Arraste seu XML aqui                      │   │
│     │        ou clique para selecionar                 │   │
│     │                                                  │   │
│     │              [ colar XML como texto ]             │   │
│     └────────────────────────────────────────────────┘   │
│                                                            │
└──────────────────────────────────────────────────────────┘

--- após validar ---

┌──────────────────────────────────────────────────────────┐
│  ✔ / ✘  Nota INVÁLIDA — NF-e, layout 4.00                 │
│  Chave de acesso: 3526...1238                              │
│                                          [Validar outro]    │
├──────────────────────────────────────────────────────────┤
│  Erros (3)                                                 │
│  ──────────────────────────────────────────────────────    │
│  ● Base de Cálculo do ICMS (vBC) está vazia                │
│    A SEFAZ rejeita a nota porque... [ver detalhes técnicos]│
│  ──────────────────────────────────────────────────────    │
│  ● CNPJ inválido em <emit>                                 │
│    A Receita rejeita porque... [ver detalhes técnicos]     │
│  ──────────────────────────────────────────────────────    │
│  Avisos (0)                                                 │
└──────────────────────────────────────────────────────────┘
```

## 10. Critérios de Aceite (Definition of Done)

- [ ] Arrastar um `.xml` válido para a área de drop dispara a validação e mostra "válido" com destaque verde.
- [ ] Arrastar um `.xml` com erros mostra a lista de erros, cada um com `motivo_rejeicao` em destaque.
- [ ] Colar um XML como texto produz o mesmo resultado que soltar o arquivo equivalente.
- [ ] Arrastar um arquivo que não é `.xml` é rejeitado no cliente com mensagem clara, sem chamar o backend.
- [ ] Derrubar o backend (ou simular timeout) mostra mensagem de erro amigável, não uma tela em branco ou travada.
- [ ] Toda a jornada (arrastar → carregando → resultado → validar outro) funciona sem recarregar a página.
- [ ] Área de drop é operável 100% via teclado.
- [ ] Nenhuma regra de validação de XML foi duplicada/reimplementada no front-end.
