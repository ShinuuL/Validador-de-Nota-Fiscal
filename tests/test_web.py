"""
Testes da UI de arrastar-e-soltar (spec-ui-drag-and-drop.md).

Duas camadas:

  * `processar_validacao()` sem HTTP nenhum — é o núcleo agnóstico de
    framework, e é onde as regras de resposta são verificadas;
  * um servidor de verdade em porta efêmera, para conferir o que só aparece no
    HTTP: status, cabeçalhos, servir estáticos e recusa de caminho.

O front em si (drag-and-drop, foco, estados) não tem runner de navegador aqui.
O que dá para garantir sem navegador é verificado por inspeção do HTML/JS:
que os handlers exigidos existem, que a área de drop é alcançável por teclado
e — o mais importante — que o JS **não** reimplementa validação (Seção 2 da
spec e último item do Definition of Done).

Rodar com:
    python -m unittest discover -s tests -p "test_*.py" -v
"""

import json
import re
import sys
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from nfe_validator.web import servidor
from nfe_validator.web.servidor import (
    TAMANHO_MAXIMO,
    criar_servidor,
    processar_validacao,
)

RAIZ = Path(__file__).resolve().parent.parent
FIXTURE = RAIZ / "tests" / "fixtures" / "nfe_exemplo_invalida.xml"
ESTATICO = RAIZ / "nfe_validator" / "web" / "estatico"

_BLOCO = re.compile(r"/\*.*?\*/", re.DOTALL)
_LINHA = re.compile(r"(?<!:)//[^\n]*")     # o (?<!:) preserva "http://"


def _sem_comentarios(js: str) -> str:
    """Remove comentários do JS para poder afirmar coisas sobre o CÓDIGO.

    Aproximação suficiente para teste: não trata `//` dentro de string, exceto
    o caso de URL, que é o único que aparece aqui."""
    return _LINHA.sub("", _BLOCO.sub("", js))


class TesteNucleoDoEndpoint(unittest.TestCase):
    """`processar_validacao` recebe bytes e devolve (status, dict)."""

    def _validar(self, payload: dict):
        return processar_validacao(json.dumps(payload).encode("utf-8"))

    def test_devolve_o_resultado_do_validar_sem_transformar(self):
        """Seção 7 passo 1: 'retornar o JSON exatamente como o validar() já
        produz — sem transformação de dados'."""
        from nfe_validator import validar
        conteudo = FIXTURE.read_text(encoding="utf-8")
        status, resposta = self._validar({"conteudoXml": conteudo})
        self.assertEqual(status, 200)
        self.assertEqual(resposta, validar(conteudo))

    def test_json_invalido(self):
        status, resposta = processar_validacao(b"isto nao e json")
        self.assertEqual(status, 400)
        self.assertEqual(resposta["erro"]["codigo"], "JSON-INVALIDO")

    def test_corpo_que_nao_e_objeto(self):
        status, resposta = processar_validacao(b'["lista"]')
        self.assertEqual(status, 400)
        self.assertEqual(resposta["erro"]["codigo"], "JSON-INVALIDO")

    def test_sem_campo_conteudo_xml(self):
        status, resposta = self._validar({"xml": "<NFe/>"})
        self.assertEqual(status, 400)
        self.assertEqual(resposta["erro"]["codigo"], "XML-AUSENTE")

    def test_conteudo_em_branco(self):
        status, resposta = self._validar({"conteudoXml": "   \n  "})
        self.assertEqual(status, 400)
        self.assertEqual(resposta["erro"]["codigo"], "XML-AUSENTE")

    def test_conteudo_nao_textual(self):
        status, resposta = self._validar({"conteudoXml": 42})
        self.assertEqual(status, 400)
        self.assertEqual(resposta["erro"]["codigo"], "XML-AUSENTE")

    def test_corpo_acima_do_limite(self):
        corpo = b'{"conteudoXml":"' + b"x" * (TAMANHO_MAXIMO + 10) + b'"}'
        status, resposta = processar_validacao(corpo)
        self.assertEqual(status, 413)
        self.assertEqual(resposta["erro"]["codigo"], "CORPO-GRANDE")

    def test_bytes_que_nao_sao_utf8(self):
        status, resposta = processar_validacao(b"\xff\xfe\x00nao utf8")
        self.assertEqual(status, 400)
        self.assertEqual(resposta["erro"]["codigo"], "ENCODING-INVALIDO")

    def test_xml_malformado_e_resultado_de_validacao_nao_erro_de_servidor(self):
        """RN-UI09: XML quebrado é resposta 200 com `valido: false`. Devolver
        500 faria a UI mostrar 'falha de comunicação' em vez de explicar a nota."""
        status, resposta = self._validar({"conteudoXml": "<NFe><infNFe></NFe>"})
        self.assertEqual(status, 200)
        self.assertFalse(resposta["valido"])
        self.assertEqual(resposta["erros"][0]["codigo"], "XML-MALFORMADO")

    def test_excecao_inesperada_vira_json_e_nao_stack_trace(self):
        original = servidor.validar
        try:
            servidor.validar = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom"))
            status, resposta = self._validar({"conteudoXml": "<NFe/>"})
        finally:
            servidor.validar = original
        self.assertEqual(status, 500)
        self.assertEqual(resposta["erro"]["codigo"], "FALHA-INESPERADA")
        self.assertNotIn("boom", json.dumps(resposta))
        self.assertIn("RuntimeError", resposta["erro"]["mensagem"])


class TesteServidorHttp(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.servidor = criar_servidor("127.0.0.1", 0)   # porta efêmera
        cls.base = f"http://127.0.0.1:{cls.servidor.server_port}"
        cls.thread = threading.Thread(target=cls.servidor.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.servidor.shutdown()
        cls.servidor.server_close()
        cls.thread.join(timeout=5)

    def _pedir(self, caminho, dados=None, metodo=None):
        req = urllib.request.Request(
            self.base + caminho,
            data=json.dumps(dados).encode("utf-8") if dados is not None else None,
            headers={"Content-Type": "application/json"} if dados is not None else {},
            method=metodo,
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return r.status, r.headers, r.read()
        except urllib.error.HTTPError as e:
            return e.code, e.headers, e.read()

    def test_serve_a_pagina_na_raiz(self):
        status, cabecalhos, corpo = self._pedir("/")
        self.assertEqual(status, 200)
        self.assertIn("text/html", cabecalhos["Content-Type"])
        self.assertIn(b"area-drop", corpo)

    def test_serve_css_e_js(self):
        for caminho, tipo in (("/estilo.css", "css"), ("/app.js", "javascript")):
            status, cabecalhos, corpo = self._pedir(caminho)
            self.assertEqual(status, 200, caminho)
            self.assertIn(tipo, cabecalhos["Content-Type"])
            self.assertTrue(corpo)

    def test_nada_e_cacheado(self):
        """RN-UI11: sem persistência. Cache de resposta com dado fiscal ficaria
        no disco do navegador."""
        for caminho in ("/", "/app.js"):
            _, cabecalhos, _ = self._pedir(caminho)
            self.assertEqual(cabecalhos["Cache-Control"], "no-store")

    def test_valida_via_http(self):
        status, cabecalhos, corpo = self._pedir(
            "/api/validar", {"conteudoXml": FIXTURE.read_text(encoding="utf-8")}
        )
        self.assertEqual(status, 200)
        self.assertIn("application/json", cabecalhos["Content-Type"])
        dados = json.loads(corpo)
        self.assertFalse(dados["valido"])
        self.assertGreater(dados["resumo"]["totalErros"], 0)

    def test_erro_vem_como_json_nunca_html(self):
        status, cabecalhos, corpo = self._pedir("/api/validar", {"nada": 1})
        self.assertEqual(status, 400)
        self.assertIn("application/json", cabecalhos["Content-Type"])
        self.assertIn("erro", json.loads(corpo))
        self.assertNotIn(b"<html", corpo.lower())

    def test_rota_desconhecida_devolve_json(self):
        status, cabecalhos, corpo = self._pedir("/nao-existe")
        self.assertEqual(status, 404)
        self.assertIn("application/json", cabecalhos["Content-Type"])
        self.assertEqual(json.loads(corpo)["erro"]["codigo"], "NAO-ENCONTRADO")

    def test_post_em_rota_errada(self):
        status, _, corpo = self._pedir("/api/outra", {"conteudoXml": "<NFe/>"})
        self.assertEqual(status, 404)

    def test_travessia_de_caminho_e_recusada(self):
        for tentativa in ("/../pyproject.toml", "/..%2fpyproject.toml",
                          "/estatico/../../pyproject.toml"):
            status, _, corpo = self._pedir(tentativa)
            self.assertEqual(status, 404, tentativa)
            self.assertNotIn(b"build-system", corpo)

    def test_endpoint_de_saude(self):
        status, _, corpo = self._pedir("/api/saude")
        self.assertEqual(status, 200)
        self.assertTrue(json.loads(corpo)["ok"])

    def test_nao_anuncia_a_versao_do_python(self):
        _, cabecalhos, _ = self._pedir("/api/saude")
        self.assertNotIn("Python", cabecalhos.get("Server", ""))


class TesteContratoDoFrontend(unittest.TestCase):
    """O que dá para verificar sem navegador. Os itens de comportamento visual
    ficam com a revisão manual (Seção 7 passo 8)."""

    @classmethod
    def setUpClass(cls):
        cls.html = (ESTATICO / "index.html").read_text(encoding="utf-8")
        cls.js = (ESTATICO / "app.js").read_text(encoding="utf-8")
        cls.css = (ESTATICO / "estilo.css").read_text(encoding="utf-8")
        cls.js_codigo = _sem_comentarios(cls.js)

    def _assertNaoNoCodigo(self, termo, motivo):
        """Procura no JS SEM comentários.

        Necessário porque os comentários citam de propósito o que NÃO fazemos
        ("nada de localStorage") — e a busca crua acusaria justamente a
        documentação da boa prática."""
        self.assertNotIn(termo, self.js_codigo, f"{termo}: {motivo}")

    def test_nao_usa_biblioteca_externa(self):
        """RNF-UI03. Nenhum <script src> ou <link> apontando para fora."""
        externos = re.findall(r'(?:src|href)\s*=\s*["\'](https?:|//)', self.html)
        self.assertEqual(externos, [])

    def test_nao_reimplementa_validacao_no_cliente(self):
        """Último item do Definition of Done, e o risco mais real de desvio:
        alguém 'adiantar' a validação no navegador. O cliente só pode olhar
        extensão, tamanho e vazio."""
        for termo in ("DOMParser", "infNFe", "cStat", "chNFe",
                      "modulo11", "digitoVerificador"):
            self._assertNaoNoCodigo(termo, "sugere validação duplicada no cliente")

    def test_area_de_drop_e_operavel_por_teclado(self):
        """RN-UI02 / RNF-UI02."""
        self.assertIn('tabindex="0"', self.html)
        self.assertIn('role="button"', self.html)
        self.assertIn("keydown", self.js)
        self.assertIn('"Enter"', self.js)

    def test_trata_os_quatro_eventos_de_drag_and_drop(self):
        """Seção 7 passo 3."""
        for evento in ("dragenter", "dragover", "dragleave", "drop"):
            self.assertIn(f'"{evento}"', self.js, evento)

    def test_previne_o_default_no_dragover(self):
        """Sem isso o navegador abre o XML numa aba em vez de validar."""
        self.assertIn("preventDefault", self.js)

    def test_tem_os_tres_caminhos_de_entrada(self):
        """RN-UI03: arrastar, selecionar e colar levam ao MESMO backend."""
        self.assertIn('id="area-drop"', self.html)
        self.assertIn('type="file"', self.html)
        self.assertIn('id="area-texto"', self.html)
        # Um único ponto de envio garante que os três caminhos não divergem.
        self.assertEqual(self.js.count("fetch("), 1)

    def test_limite_de_tamanho_bate_com_o_servidor(self):
        """RNF-UI05. Divergir faria o cliente aceitar o que o servidor recusa."""
        self.assertIn("5 * 1024 * 1024", self.js)
        self.assertEqual(TAMANHO_MAXIMO, 5 * 1024 * 1024)

    def test_tem_estado_de_carregamento_e_de_falha(self):
        """RN-UI05 e RF-UI11."""
        self.assertIn('id="painel-carregando"', self.html)
        self.assertIn('id="painel-falha"', self.html)
        self.assertIn("AbortController", self.js)

    def test_tem_acao_de_validar_outro_sem_recarregar(self):
        """RN-UI10."""
        self.assertIn('id="btn-validar-outro"', self.html)
        self.assertIn("irParaOcioso", self.js)
        self._assertNaoNoCodigo("location.reload", "RN-UI10 pede sem recarregar")

    def test_tem_copia_do_json(self):
        """RF-UI09."""
        self.assertIn('id="btn-copiar-json"', self.html)

    def test_nao_persiste_nada(self):
        """RN-UI11: sem localStorage/sessionStorage/cookie."""
        for termo in ("localStorage", "sessionStorage", "document.cookie", "indexedDB"):
            self._assertNaoNoCodigo(termo, "persistiria dado fiscal no navegador")

    def test_erro_e_aviso_tem_estilo_distinto(self):
        """RN-UI08: cor diferente E não só cor (borda + ícone + texto)."""
        self.assertIn(".item.erro", self.css)
        self.assertIn(".item.aviso", self.css)
        self.assertIn("--erro:", self.css)
        self.assertIn("--aviso:", self.css)

    def test_motivo_tem_mais_destaque_que_o_xpath(self):
        """RN-UI07 é explícita: 'nunca o inverso'. O motivo é 1rem/600, o campo
        técnico é 0.88rem em cor fraca."""
        motivo = re.search(r"\.item-motivo\s*\{([^}]*)\}", self.css).group(1)
        campo = re.search(r"\.item-campo\s*\{([^}]*)\}", self.css).group(1)
        self.assertIn("font-weight: 600", motivo)
        self.assertIn("texto-fraco", campo)
        self.assertNotIn("font-weight: 600", campo)

    def test_detalhes_tecnicos_ficam_colapsados(self):
        """RF-UI07: expansível, não em destaque."""
        self.assertIn("createElement(\"details\")", self.js)
        self.assertIn("createElement(\"summary\")", self.js)

    def test_conteudo_do_xml_nunca_entra_como_html(self):
        """Defesa de injeção: o XML vem de terceiro. Tudo via textContent."""
        for termo in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write"):
            self._assertNaoNoCodigo(termo, "conteúdo de XML de terceiro como HTML")

    def test_e_responsivo(self):
        """RNF-UI01."""
        self.assertIn("viewport", self.html)
        self.assertIn("@media", self.css)

    def test_respeita_preferencia_de_menos_movimento(self):
        self.assertIn("prefers-reduced-motion", self.css)


if __name__ == "__main__":
    unittest.main()
