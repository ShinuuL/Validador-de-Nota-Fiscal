# -*- mode: python ; coding: utf-8 -*-
"""
Receita do PyInstaller para o executável distribuível.

Construir com:

    python -m PyInstaller --clean --noconfirm nfe-validator.spec

Sai em `dist/nfe-validator.exe`, um arquivo só, sem nada para instalar na
máquina de destino.

Por que um .spec e não a linha de comando
-----------------------------------------
Porque a parte que importa aqui são os DADOS, não as opções. Os .xsd oficiais e
os arquivos da UI são lidos do disco em tempo de execução
(`Path(__file__).parent / "schemas"`), e o PyInstaller não descobre isso
analisando imports. Se eles ficarem de fora, o .exe SOBE E FUNCIONA — só que
degrada em silêncio para o aviso XSD-INDISPONIVEL em toda nota, ou serve a UI
com ESTATICO-AUSENTE. É uma falha plausível e invisível, e é a coisa que este
arquivo existe para impedir. Deixá-la versionada, comentada, é mais seguro que
um comando de 400 caracteres no histórico do shell de alguém.
"""

from pathlib import Path

RAIZ = Path(SPECPATH)
PACOTE = RAIZ / "nfe_validator"

# Coletado por varredura, não por lista fixa: os schemas seguem a RN14
# (schemas/v{versao}/{tipo}/), então uma versão nova de layout é uma PASTA
# nova. Uma lista escrita à mão sairia de sincronia sem avisar - e o modo de
# falha, de novo, é silencioso.
dados = []
for arquivo in sorted((PACOTE / "schemas").rglob("*")):
    if arquivo.is_file() and arquivo.suffix.lower() in (".xsd", ".txt", ".md"):
        destino = arquivo.parent.relative_to(RAIZ).as_posix()
        dados.append((str(arquivo), destino))

# A UI é servida do disco pelo próprio pacote (`ESTATICOS` em web/servidor.py).
for arquivo in sorted((PACOTE / "web" / "estatico").iterdir()):
    if arquivo.is_file() and arquivo.suffix.lower() in (".html", ".css", ".js"):
        dados.append((str(arquivo), "nfe_validator/web/estatico"))

analise = Analysis(
    [str(PACOTE / "desktop.py")],
    pathex=[str(RAIZ)],
    binaries=[],
    datas=dados,
    # `webbrowser` e `mimetypes` só são importados dentro de função, e
    # `http.server` puxa o resto do servidor. Declarados para o analisador não
    # decidir que ninguém usa.
    hiddenimports=["webbrowser", "mimetypes", "http.server", "lxml._elementpath"],
    hookspath=[],
    runtime_hooks=[],
    # `tkinter` não é usado (a UI é o navegador) e sozinho engorda o .exe em
    # vários MB. `tests` não vai para a mão do usuário final.
    excludes=["tkinter", "unittest", "tests"],
    noarchive=False,
)

pyz = PYZ(analise.pure)

exe = EXE(
    pyz,
    analise.scripts,
    analise.binaries,
    analise.datas,
    name="nfe-validator",
    debug=False,
    strip=False,
    upx=False,
    # console=False: o público majoritário do .exe é quem dá duplo clique e
    # quer a janela do navegador, não uma tela preta. O preço é que, sem
    # console, o Windows deixa `sys.stdout`/`sys.stderr` valendo None - por
    # isso `desktop.main()` chama `_garantir_saidas()` antes do primeiro
    # print, senão o programa morre de AttributeError sem abrir nada.
    #
    # O uso de CLI continua existindo, mas passa a exigir redirecionamento
    # explícito para ver a saída (`nfe-validator.exe nota.xml --json > s.json`);
    # sem redirecionar, o texto vai para o dispositivo nulo. O código de saída
    # continua correto para quem chama do ERP.
    console=False,
    onefile=True,
    disable_windowed_traceback=False,
)
