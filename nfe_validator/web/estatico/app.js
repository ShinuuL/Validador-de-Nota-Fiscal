/*
 * UI do validador de NF-e/NFC-e.
 *
 * REGRA CENTRAL (Seção 2 e RN-UI04 da spec): este arquivo NÃO valida XML.
 * A única checagem no cliente é trivial — extensão .xml, tamanho e texto não
 * vazio. Bem-formação, XSD e regras de negócio são exclusividade do backend.
 * Se você for adicionar aqui qualquer coisa que "decida" sobre o conteúdo da
 * nota, pare: o lugar é o pacote nfe_validator.
 *
 * Sem bibliotecas externas (RNF-UI03): drag-and-drop é a API nativa do HTML5.
 */
"use strict";

const TAMANHO_MAXIMO = 5 * 1024 * 1024;   // RNF-UI05
const TEMPO_LIMITE = 30000;                // RF-UI11

const el = (id) => document.getElementById(id);

const painel = {
  entrada: el("painel-entrada"),
  carregando: el("painel-carregando"),
  falha: el("painel-falha"),
  resultado: el("painel-resultado"),
};

// Última entrada, guardada só em memória para o "tentar novamente" da falha de
// rede. RN-UI11: nada de localStorage/sessionStorage — recarregar a página
// apaga tudo.
let ultimaEntrada = null;     // { conteudo, rotulo }
let arquivoPendente = null;
let ultimoResultado = null;

/* ------------------------------------------------------------------ *
 * Máquina de estados (Seção 6): exatamente um painel visível por vez.
 * ------------------------------------------------------------------ */
function mostrar(estado) {
  Object.values(painel).forEach((p) => { p.hidden = true; });
  painel[estado].hidden = false;
}

function irParaOcioso() {
  arquivoPendente = null;
  el("seletor-arquivo").value = "";
  el("arquivo-escolhido").hidden = true;
  el("painel-texto").hidden = true;
  el("area-texto").value = "";
  limparAvisoCliente();
  mostrar("entrada");
  el("area-drop").focus();
}

/* ------------------------------------------------------------------ *
 * Avisos do cliente (RN-UI04)
 * ------------------------------------------------------------------ */
function avisarCliente(mensagem) {
  const aviso = el("aviso-cliente");
  aviso.textContent = mensagem;
  aviso.hidden = false;
}

function limparAvisoCliente() {
  const aviso = el("aviso-cliente");
  aviso.textContent = "";
  aviso.hidden = true;
}

function formatarTamanho(bytes) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(2)} MB`;
}

/**
 * A única checagem de conteúdo permitida no cliente. Devolve null se está ok,
 * ou a mensagem do problema.
 */
function problemaNoArquivo(arquivo) {
  if (!arquivo.name.toLowerCase().endsWith(".xml")) {
    return `"${arquivo.name}" não é um arquivo .xml. Selecione o XML da nota `
         + "(não o PDF do DANFE, nem um .zip).";
  }
  if (arquivo.size === 0) {
    return `"${arquivo.name}" está vazio.`;
  }
  if (arquivo.size > TAMANHO_MAXIMO) {
    return `"${arquivo.name}" tem ${formatarTamanho(arquivo.size)}. O limite é `
         + `${formatarTamanho(TAMANHO_MAXIMO)} — um XML de NF-e raramente `
         + "chega perto disso.";
  }
  return null;
}

/* ------------------------------------------------------------------ *
 * Seleção de arquivo (RF-UI04: mostra nome e tamanho antes de enviar)
 * ------------------------------------------------------------------ */
function receberArquivo(arquivo) {
  limparAvisoCliente();
  const problema = problemaNoArquivo(arquivo);
  if (problema) {
    // Recusado sem tocar no backend.
    arquivoPendente = null;
    el("arquivo-escolhido").hidden = true;
    avisarCliente(problema);
    return;
  }
  arquivoPendente = arquivo;
  el("arquivo-nome").textContent = arquivo.name;
  el("arquivo-tamanho").textContent = `(${formatarTamanho(arquivo.size)})`;
  el("arquivo-escolhido").hidden = false;
  el("painel-texto").hidden = true;
  el("btn-validar-arquivo").focus();
}

/* ------------------------------------------------------------------ *
 * Drag-and-drop nativo (RF-UI01, Seção 7 passo 3)
 * ------------------------------------------------------------------ */
const areaDrop = el("area-drop");
let profundidadeArrasto = 0;   // dragenter/dragleave disparam nos filhos também

function pararEvento(evento) {
  evento.preventDefault();
  evento.stopPropagation();
}

areaDrop.addEventListener("dragenter", (evento) => {
  pararEvento(evento);
  profundidadeArrasto += 1;
  areaDrop.classList.add("arrastando");
});

// preventDefault no dragover é obrigatório: sem ele o navegador abre o arquivo.
areaDrop.addEventListener("dragover", (evento) => {
  pararEvento(evento);
  if (evento.dataTransfer) evento.dataTransfer.dropEffect = "copy";
  areaDrop.classList.add("arrastando");
});

areaDrop.addEventListener("dragleave", (evento) => {
  pararEvento(evento);
  profundidadeArrasto = Math.max(0, profundidadeArrasto - 1);
  if (profundidadeArrasto === 0) areaDrop.classList.remove("arrastando");
});

areaDrop.addEventListener("drop", (evento) => {
  pararEvento(evento);
  profundidadeArrasto = 0;
  areaDrop.classList.remove("arrastando");

  const arquivos = evento.dataTransfer ? evento.dataTransfer.files : null;
  if (!arquivos || arquivos.length === 0) return;
  if (arquivos.length > 1) {
    // Lote em uma tela só está fora de escopo (Seção 8).
    avisarCliente("Solte um arquivo por vez. Validação em lote não faz parte "
                + "desta tela — use a linha de comando com --lote.");
    return;
  }
  receberArquivo(arquivos[0]);
});

// Se soltar fora da área, o navegador abriria o XML numa aba. Evita isso.
["dragover", "drop"].forEach((tipo) => {
  window.addEventListener(tipo, (evento) => {
    if (!areaDrop.contains(evento.target)) evento.preventDefault();
  });
});

/* ------------------------------------------------------------------ *
 * Clique e teclado (RF-UI02, RNF-UI02)
 * ------------------------------------------------------------------ */
areaDrop.addEventListener("click", () => el("seletor-arquivo").click());

areaDrop.addEventListener("keydown", (evento) => {
  if (evento.key === "Enter" || evento.key === " " || evento.key === "Spacebar") {
    evento.preventDefault();      // Espaço rolaria a página
    el("seletor-arquivo").click();
  }
});

el("seletor-arquivo").addEventListener("change", (evento) => {
  const arquivo = evento.target.files && evento.target.files[0];
  if (arquivo) receberArquivo(arquivo);
});

/* ------------------------------------------------------------------ *
 * Colar texto (RN-UI03/RF-UI03)
 * ------------------------------------------------------------------ */
el("btn-alternar-texto").addEventListener("click", () => {
  const painelTexto = el("painel-texto");
  painelTexto.hidden = !painelTexto.hidden;
  if (!painelTexto.hidden) {
    el("arquivo-escolhido").hidden = true;
    arquivoPendente = null;
    limparAvisoCliente();
    el("area-texto").focus();
  }
});

el("btn-cancelar-texto").addEventListener("click", () => {
  el("painel-texto").hidden = true;
  el("area-texto").value = "";
  el("btn-alternar-texto").focus();
});

el("btn-validar-texto").addEventListener("click", () => {
  const texto = el("area-texto").value;
  limparAvisoCliente();
  if (!texto.trim()) {
    avisarCliente("Cole o conteúdo do XML antes de validar.");
    return;
  }
  if (texto.length > TAMANHO_MAXIMO) {
    avisarCliente(`O texto colado passa de ${formatarTamanho(TAMANHO_MAXIMO)}.`);
    return;
  }
  // Mesmo caminho do arquivo: um único backend, uma única lógica (RN-UI03).
  enviar(texto, "texto colado");
});

/* ------------------------------------------------------------------ *
 * Envio (RF-UI05, RNF-UI04)
 * ------------------------------------------------------------------ */
el("btn-validar-arquivo").addEventListener("click", async () => {
  if (!arquivoPendente) return;
  const arquivo = arquivoPendente;
  // Feedback imediato: o loading aparece antes da leitura do disco, para não
  // ficar tela parada em arquivo grande (RNF-UI04).
  el("carregando-nome").textContent = arquivo.name;
  mostrar("carregando");
  try {
    const conteudo = await arquivo.text();
    if (!conteudo.trim()) {
      mostrar("entrada");
      avisarCliente(`"${arquivo.name}" está vazio.`);
      return;
    }
    enviar(conteudo, arquivo.name);
  } catch (erro) {
    mostrarFalha("Não foi possível ler o arquivo do disco. "
               + "Ele pode ter sido movido ou não ter permissão de leitura.");
  }
});

el("btn-descartar-arquivo").addEventListener("click", irParaOcioso);

async function enviar(conteudo, rotulo) {
  ultimaEntrada = { conteudo, rotulo };
  el("carregando-nome").textContent = rotulo;
  mostrar("carregando");

  // Cão de guarda do PAINEL, e não da requisição — é a diferença que importa.
  //
  // O `abortador` abaixo protege o `fetch`, mas só serve se o `fetch` de fato
  // rejeitar quando o sinal dispara. Dois casos reais quebram isso e deixam a
  // página em "Validando…" para sempre, sem mensagem nenhuma:
  //
  //   * navegador que tem `AbortController` mas ignora o `signal` no `fetch`
  //     (Edge legado, Safari antigo). O `abort()` roda, a promessa nunca se
  //     resolve, o `finally` nunca chega e o painel fica preso;
  //   * qualquer exceção lançada aqui fora do `try` — que escapava como
  //     rejeição não tratada, já com o painel de carregando visível.
  //
  // Este temporizador não depende de nenhum dos dois: ele olha o estado da
  // tela. Se o painel de carregando ainda estiver visível depois do prazo, a
  // falha aparece — não importa o que travou. Some segundos ao limite do
  // `fetch` para que, quando o caminho normal funcionar, seja a mensagem dele
  // que ganhe (ela sabe distinguir XML grande de janela fechada).
  const guarda = setTimeout(() => {
    if (!painel.carregando.hidden) {
      mostrarFalha(
        "A validação passou de " + Math.round((TEMPO_LIMITE + 5000) / 1000)
        + " segundos sem resposta e a página parou de esperar. Confirme que o "
        + "validador continua aberto — se você fechou a janela dele, ou se "
        + "sobrou uma cópia antiga rodando em segundo plano, abra o validador "
        + "de novo antes de tentar."
      );
    }
  }, TEMPO_LIMITE + 5000);

  let abortador = null;
  let relogio = null;

  try {
    // Dentro do `try` de propósito: em navegador sem `AbortController` o `new`
    // estoura, e aqui isso vira uma falha visível em vez de uma promessa
    // rejeitada que ninguém escuta.
    abortador = new AbortController();
    relogio = setTimeout(() => abortador.abort(), TEMPO_LIMITE);

    const resposta = await fetch("api/validar", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ conteudoXml: conteudo }),
      signal: abortador.signal,
    });

    let dados;
    try {
      dados = await resposta.json();
    } catch (_) {
      mostrarFalha(`O servidor respondeu ${resposta.status} em um formato que `
                 + "não é JSON. Verifique se a porta é a do validador.");
      return;
    }

    // O backend usa uma forma distinta para falha de infraestrutura, então dá
    // para separar sem heurística.
    if (dados && dados.erro) {
      mostrarFalha(dados.erro.mensagem || "Falha no servidor.");
      return;
    }
    if (!resposta.ok) {
      mostrarFalha(`O servidor respondeu ${resposta.status}.`);
      return;
    }

    renderizar(dados);
  } catch (erro) {
    if (erro.name === "AbortError") {
      // Duas causas levam ao mesmo tempo esgotado, e culpar só o tamanho do XML
      // manda quem caiu na outra procurar no lugar errado: um XML enorme
      // realmente demora, mas a janela do validador ter sido fechada (ou uma
      // instância velha ter ficado presa na porta) dá exatamente este sintoma -
      // a página fica em "Validando…" até o tempo limite.
      mostrarFalha(`A validação passou de ${TEMPO_LIMITE / 1000} segundos sem `
                 + "resposta. Confirme que a janela do validador continua aberta; "
                 + "se ela foi fechada, abra o validador de novo. Se o XML é muito "
                 + "grande, vale tentar pela linha de comando.");
    } else {
      // Quem recebeu o .exe e nunca abriu um terminal não sabe o que é
      // "o terminal onde você rodou 'nfe-validator-web'". E desde que o
      // executável passou a rodar sem console, também não há janela preta para
      // citar: o validador fica em segundo plano, sem nada na tela.
      mostrarFalha("O validador não respondeu. Ele precisa continuar rodando "
                 + "enquanto você usa esta página — abra o nfe-validator.exe de "
                 + "novo e recarregue.");
    }
  } finally {
    clearTimeout(relogio);
    clearTimeout(guarda);
  }
}

/* ------------------------------------------------------------------ *
 * Falha de comunicação (RF-UI11)
 * ------------------------------------------------------------------ */
function mostrarFalha(mensagem) {
  el("falha-mensagem").textContent = mensagem;
  mostrar("falha");
  el("btn-tentar-novamente").focus();
}

el("btn-tentar-novamente").addEventListener("click", () => {
  if (ultimaEntrada) {
    enviar(ultimaEntrada.conteudo, ultimaEntrada.rotulo);
  } else {
    irParaOcioso();
  }
});

el("btn-voltar-falha").addEventListener("click", irParaOcioso);

/* ------------------------------------------------------------------ *
 * Resultado (RN-UI06/07/08/09, RF-UI06/07/08)
 * ------------------------------------------------------------------ */
function montarMetadados(resultado) {
  const lista = el("metadados");
  lista.textContent = "";

  const resumo = resultado.resumo || {};
  const campos = [
    ["Documento", resultado.tipoDocumento || "não identificado"],
    ["Layout", resultado.versaoLayout || "—"],
    ["Chave de acesso", resultado.chaveAcesso || "não informada"],
    ["Erros", String(resumo.totalErros ?? (resultado.erros || []).length)],
    ["Avisos", String(resumo.totalAvisos ?? (resultado.avisos || []).length)],
  ];
  if (resumo.totalCamposNaoPreenchidos) {
    campos.push(["Campos não preenchidos", String(resumo.totalCamposNaoPreenchidos)]);
  }
  if (resumo.xsdAplicado === false) {
    campos.push(["Atenção", "schema (XSD) não aplicado — relatório incompleto"]);
  }

  for (const [rotulo, valor] of campos) {
    const dt = document.createElement("dt");
    dt.textContent = rotulo;
    const dd = document.createElement("dd");
    dd.textContent = valor;
    lista.append(dt, dd);
  }
}

/**
 * RN-UI07: motivo em destaque, campo/xpath como secundário. Usamos
 * textContent em tudo — o conteúdo vem de um XML de terceiro, e montar HTML
 * por concatenação seria injeção esperando acontecer.
 */
function montarItem(item, tipo) {
  const li = document.createElement("li");
  li.className = `item ${tipo}`;

  const detalhe = item.detalhe || {};

  const motivo = document.createElement("p");
  motivo.className = "item-motivo";
  motivo.textContent = detalhe.onde
    ? `${detalhe.campo || item.campo || "documento"} — ${detalhe.oQueAconteceu || ""}`
    : (item.mensagem || item.motivo_rejeicao || "");
  li.appendChild(motivo);

  const identificacao = document.createElement("p");
  identificacao.className = "item-campo";
  const codigo = document.createElement("span");
  codigo.className = "item-codigo";
  codigo.textContent = item.codigo || "";
  identificacao.appendChild(codigo);
  identificacao.appendChild(
    document.createTextNode(detalhe.onde || item.xpath || "")
  );
  li.appendChild(identificacao);

  // Quando o backend manda a explicação em partes, mostramos em blocos — é
  // mais legível que o texto corrido, e é o mesmo dado.
  if (detalhe.porQueRejeita || detalhe.comoCorrigir) {
    const partes = document.createElement("div");
    partes.className = "item-partes";
    for (const [rotulo, valor] of [["Por quê", detalhe.porQueRejeita],
                                   ["Como corrigir", detalhe.comoCorrigir]]) {
      if (!valor) continue;
      const p = document.createElement("p");
      p.className = "item-parte";
      const forte = document.createElement("strong");
      forte.textContent = `${rotulo}: `;
      p.appendChild(forte);
      p.appendChild(document.createTextNode(valor));
      partes.appendChild(p);
    }
    li.appendChild(partes);
  } else if (detalhe.onde && (item.mensagem || item.motivo_rejeicao)) {
    const p = document.createElement("p");
    p.className = "item-parte";
    p.textContent = item.mensagem || item.motivo_rejeicao;
    li.appendChild(p);
  }

  // RF-UI07: detalhes técnicos expansíveis, nunca em destaque.
  const tecnicos = [
    ["xpath", item.xpath],
    ["linha", item.linha],
    ["origem", item.origem],
    ["subOrigem", item.subOrigem],
    ["mensagem técnica", item.mensagem_tecnica],
  ].filter(([, valor]) => valor !== null && valor !== undefined && valor !== "");

  if (tecnicos.length) {
    const detalhes = document.createElement("details");
    const resumo = document.createElement("summary");
    resumo.textContent = "ver detalhes técnicos";
    detalhes.appendChild(resumo);
    const pre = document.createElement("pre");
    pre.className = "item-tecnico";
    pre.textContent = tecnicos.map(([k, v]) => `${k}: ${v}`).join("\n");
    detalhes.appendChild(pre);
    li.appendChild(detalhes);
  }

  return li;
}

function montarLista(itens, bloco, titulo, lista, rotulo, tipo) {
  const alvo = el(lista);
  alvo.textContent = "";
  if (!itens || itens.length === 0) {
    el(bloco).hidden = true;
    return;
  }
  el(titulo).textContent = `${rotulo} (${itens.length})`;
  itens.forEach((item) => alvo.appendChild(montarItem(item, tipo)));
  el(bloco).hidden = false;
}

// Concordância de gênero do "inválido/inválida". Antes era "inválida" fixo,
// que combinava com NFe e NFCe porque se lê "nota". Com eventos e consultas no
// jogo, o texto passou a sair como "Evento inválida".
//
// A lista é curta e fechada - são as famílias de `servicos.py` -, então um mapa
// explícito é mais honesto que adivinhar pela terminação: "Evento" termina em
// "o" e é masculino, mas "ConsultaSituacao" também termina em "o" e é feminino
// (lê-se "consulta").
const TIPOS_FEMININOS = new Set([
  "NFe", "NFCe", "ConsultaSituacao", "ConsultaCadastro", "Inutilizacao",
]);

function flexionarInvalido(tipo) {
  return TIPOS_FEMININOS.has(tipo) ? "inválida" : "inválido";
}

function renderizar(resultado) {
  ultimoResultado = resultado;

  const erros = resultado.erros || [];
  const avisos = resultado.avisos || [];

  // RN-UI09: falha de identificação é mostrada como mensagem amigável, não
  // como erro técnico solto.
  const identificacao = erros.find(
    (e) => e.codigo === "IDENTIFICACAO-FALHOU" || e.codigo === "XML-MALFORMADO"
  );

  const faixa = el("faixa-status");
  faixa.classList.remove("valida", "invalida");

  if (resultado.valido) {
    faixa.classList.add("valida");
    el("status-icone").textContent = "✓";
    el("status-texto").textContent = "Documento válido";
    el("status-resumo").textContent =
      "Passou no schema oficial e nas regras de negócio aplicadas.";
  } else {
    faixa.classList.add("invalida");
    el("status-icone").textContent = "✕";
    if (identificacao) {
      // Um IDENTIFICACAO-FALHOU com tipoDocumento preenchido não é "não sei o
      // que é isso": o documento FOI reconhecido (evento, consulta...) e o que
      // falhou foi um detalhe dele, como a versão de layout ausente. Dizer
      // "não parece ser uma NF-e" ali manda o usuário conferir a coisa errada.
      const reconhecido = identificacao.codigo !== "XML-MALFORMADO"
        && Boolean(resultado.tipoDocumento);
      el("status-texto").textContent =
        identificacao.codigo === "XML-MALFORMADO"
          ? "Este arquivo não é um XML válido"
          : reconhecido
            ? `${resultado.tipoDocumento}: não foi possível identificar o layout`
            : "Este arquivo não parece ser uma NF-e ou NFC-e";
      el("status-resumo").textContent = identificacao.mensagem
        || identificacao.motivo_rejeicao || "";
    } else {
      const tipo = resultado.tipoDocumento || "documento";
      const layout = resultado.versaoLayout ? `, layout ${resultado.versaoLayout}` : "";
      el("status-texto").textContent = `${tipo} ${flexionarInvalido(tipo)}${layout}`;
      el("status-resumo").textContent =
        `${erros.length} ${erros.length === 1 ? "problema impede" : "problemas impedem"}`
        + " o envio à SEFAZ.";
    }
  }

  montarMetadados(resultado);
  montarLista(erros, "bloco-erros", "titulo-erros", "lista-erros", "Erros", "erro");
  montarLista(avisos, "bloco-avisos", "titulo-avisos", "lista-avisos", "Avisos", "aviso");
  el("sem-problemas").hidden = !(erros.length === 0 && avisos.length === 0);

  el("aviso-copia").textContent = "";
  mostrar("resultado");
  el("faixa-status").scrollIntoView({ block: "start", behavior: "smooth" });
}

/* ------------------------------------------------------------------ *
 * Copiar JSON (RF-UI09) e validar outro (RN-UI10/RF-UI10)
 * ------------------------------------------------------------------ */
el("btn-copiar-json").addEventListener("click", async () => {
  if (!ultimoResultado) return;
  const texto = JSON.stringify(ultimoResultado, null, 2);
  const aviso = el("aviso-copia");
  try {
    await navigator.clipboard.writeText(texto);
    aviso.textContent = "JSON copiado.";
  } catch (_) {
    // clipboard exige contexto seguro; em http:// pode falhar.
    const area = document.createElement("textarea");
    area.value = texto;
    area.setAttribute("readonly", "");
    area.style.position = "fixed";
    area.style.opacity = "0";
    document.body.appendChild(area);
    area.select();
    const deuCerto = document.execCommand && document.execCommand("copy");
    document.body.removeChild(area);
    aviso.textContent = deuCerto
      ? "JSON copiado."
      : "Não foi possível copiar automaticamente — use Ctrl+C no terminal.";
  }
  setTimeout(() => { aviso.textContent = ""; }, 4000);
});

el("btn-validar-outro").addEventListener("click", irParaOcioso);

/* ------------------------------------------------------------------ *
 * Rede de segurança: nenhum erro pode deixar a página presa em silêncio
 * ------------------------------------------------------------------ */
//
// O pior defeito desta UI não é mostrar a mensagem errada — é não mostrar
// mensagem nenhuma. Um erro que escapa com o painel de carregando visível
// deixa "Validando…" na tela para sempre, e quem está do outro lado não tem
// como saber se o arquivo é grande, se o validador caiu ou se a página travou.
// Fica esperando.
//
// Estes dois ouvintes são o último recurso: qualquer exceção não tratada ou
// promessa rejeitada sem `catch` vira uma falha visível, desde que a página
// esteja justamente no estado onde o silêncio custa caro. Fora dele não
// interferem — um erro no botão de copiar JSON não deve trocar a tela de
// resultado por uma de falha.
function _resgatarDoCarregando(detalhe) {
  if (painel.carregando.hidden) return;
  mostrarFalha(
    "A validação foi interrompida por um erro na página (" + detalhe + "). "
    + "Recarregue e tente de novo; se repetir, use a linha de comando: "
    + "nfe-validator.exe nota.xml"
  );
}

window.addEventListener("unhandledrejection", (evento) => {
  _resgatarDoCarregando(
    (evento.reason && (evento.reason.name || evento.reason.message)) || "falha assíncrona"
  );
});

window.addEventListener("error", (evento) => {
  _resgatarDoCarregando((evento.error && evento.error.name) || evento.message || "erro");
});

/* Estado inicial. */
mostrar("entrada");
