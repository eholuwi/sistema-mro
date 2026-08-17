"""v6.6.0 — Atualizar o Sistema MRO em produção pelo próprio app.

O problema que isto resolve: até a v6.5.2, publicar uma versão significava empacotar no
notebook, mandar o zip pelo Teams, acessar o PC-servidor da sala MRO, extrair e copiar
arquivos à mão. Agora o zip continua chegando pelo Teams, mas quem opera a máquina só
escolhe o arquivo em **Configurações › Atualização** e o resto acontece sozinho.

──────────────────────────────────────────────────────────────────────────────────────
A restrição que define o desenho

O app roda **de dentro de `app\\`** — a mesma pasta que a atualização substitui inteira.
Nenhum processo consegue mover a pasta de onde ele próprio está lendo código, então a
troca não pode acontecer aqui: este módulo só **valida, guarda e dispara**. Quem troca é
`deploy/aplicar_atualizacao.bat`, lançado como processo DESTACADO (ver `disparar`), que
sobrevive ao `taskkill` do Streamlit e faz backup → swap → religa.

O bat viaja dentro do próprio pacote (`release.itens_do_pacote()` → `app\\deploy\\`), e é
COPIADO para `dados\\atualizacoes\\` antes de rodar: executado de dentro de `app\\`, ele
seguraria lock na pasta que precisa mover.

──────────────────────────────────────────────────────────────────────────────────────
Só stdlib, de propósito

`scripts/release.py` roda com o Python do sistema (sem as dependências do app instaladas)
e importa `ler_versao` daqui para não manter uma segunda regex de VERSAO. Um import de
pandas/streamlit neste módulo quebraria o empacotamento. `tests/test_v660_atualizacao.py`
trava isso.
"""

from __future__ import annotations

import io
import os
import re
import shutil
import subprocess
import zipfile
from pathlib import Path

# FONTE ÚNICA da leitura de `VERSAO = "6.6.0"` em services/constants.py. Usada por
# `scripts/release.py` (para nomear o zip) e por `inspecionar_pacote` (para ler a versão
# DE DENTRO de um zip, sem importar código de outra versão do sistema — importar seria
# executar código de origem não confiável só para descobrir um número).
VERSAO_RE = re.compile(r'^VERSAO\s*=\s*["\']v?([\d.]+)["\']', re.M)

NOME_MOTOR = "aplicar_atualizacao.bat"
NOME_PASTA = "atualizacoes"

# Assinatura mínima de um pacote do Sistema MRO. Não é segurança (o zip vem do Luis pelo
# Teams) — é evitar que um zip qualquer arrastado para a tela destrua a instalação.
ARQUIVOS_OBRIGATORIOS = ("app.py", "services/constants.py")

# O release real tem ~484 KB. O teto é folgado e serve só para barrar o engano óbvio de
# subir o pacote PORTÁTIL (~148 MB), que tem outro layout e não serve para esta troca.
TAMANHO_MAX_PACOTE = 20 * 1024 * 1024

# Quantos zips ficam em dados\atualizacoes\ antes de os antigos serem apagados.
PACOTES_MANTIDOS = 5


def ler_versao(texto: str) -> str | None:
    """Extrai `6.6.0` de um `services/constants.py` (ou None se não houver VERSAO)."""
    m = VERSAO_RE.search(texto or "")
    return m.group(1) if m else None


# ══════════════════════════════════════════════════════════════════════════════
# ONDE O SISTEMA ESTÁ INSTALADO
# ══════════════════════════════════════════════════════════════════════════════


def raiz_instalacao(db_path: str | os.PathLike | None = None) -> Path:
    """Pasta que contém `app\\`, `runtime\\` e `dados\\` — o `C:\\MRO` de produção.

    Deduzida do banco, não de `__file__`: `database.DB_PATH` é a única coisa que sabe
    onde a instalação REAL mora (produção define `MRO_DB_PATH=C:\\MRO\\dados\\mro.db`
    em `deploy/iniciar_mro.bat`, o único caminho de subida desde a v6.8.2). Em dev o
    banco fica na raiz do repositório e não há pasta `dados\\` — daí o if.
    """
    if db_path is None:
        import database

        db_path = database.DB_PATH
    pasta = Path(db_path).resolve().parent
    return pasta.parent if pasta.name.lower() == "dados" else pasta


def modo_producao(raiz: Path | None = None, origem: Path | None = None) -> bool:
    """O código em execução está DENTRO de `<raiz>\\app\\` — a pasta que a troca substitui?

    Essa é a pergunta que de fato importa, e é por isso que ela é feita diretamente. A
    primeira versão perguntava outra coisa ("existe `runtime\\` ou `MRO.exe` ao lado?"),
    que é um palpite sobre COMO a instalação foi montada: uma instalação legítima com
    outro layout responderia "não" e a tela nasceria desabilitada em produção — o
    mecanismo inteiro sem servir para nada, e por um motivo invisível para quem olha.

    Em dev (`streamlit run app.py` na raiz do repositório) continua False, que é o ponto
    inegociável: `raiz\\app\\` não existe e o código roda da raiz, então mover a pasta de
    trabalho do Luis está fora de questão.

    `origem` existe para o teste; em runtime é a pasta que contém `services/`.
    """
    raiz = raiz or raiz_instalacao()
    pasta_app = raiz / "app"
    if not (pasta_app / "app.py").is_file():
        return False
    origem = origem or Path(__file__).resolve().parent.parent
    return Path(origem).resolve() == pasta_app.resolve()


def pasta_atualizacoes(raiz: Path | None = None) -> Path:
    """`<raiz>\\dados\\atualizacoes` — fora de `app\\`, que é substituída inteira."""
    raiz = raiz or raiz_instalacao()
    return raiz / "dados" / NOME_PASTA


def motor_de_origem() -> Path:
    """O `aplicar_atualizacao.bat` que veio dentro DESTA versão do código.

    `services/atualizacao.py` → `deploy/aplicar_atualizacao.bat` funciona igual nos dois
    layouts: `<repo>\\deploy\\` em dev e `C:\\MRO\\app\\deploy\\` em produção.
    """
    return Path(__file__).resolve().parent.parent / "deploy" / NOME_MOTOR


# ══════════════════════════════════════════════════════════════════════════════
# VALIDAÇÃO DO PACOTE
# ══════════════════════════════════════════════════════════════════════════════


def inspecionar_pacote(dados: bytes) -> tuple[bool, dict]:
    """O zip é um release válido do Sistema MRO? Qual versão traz?

    Devolve `(ok, info)` no contrato dos outros imports do sistema. `info["erro"]` só
    existe quando `ok` é False, e o texto vai direto para a tela — precisa dizer o que
    fazer, não só o que houve.
    """
    info: dict = {"versao": None, "arquivos": 0, "tamanho": len(dados or b"")}

    if not dados:
        return False, {**info, "erro": "Arquivo vazio."}
    if len(dados) > TAMANHO_MAX_PACOTE:
        mb = len(dados) / (1024 * 1024)
        return False, {
            **info,
            "erro": (
                f"Arquivo grande demais ({mb:.0f} MB). Esta tela recebe o pacote de "
                "ATUALIZAÇÃO (mro-<versao>.zip, ~0,5 MB), não o pacote portátil completo."
            ),
        }

    try:
        with zipfile.ZipFile(io.BytesIO(dados)) as zf:
            corrompido = zf.testzip()
            if corrompido:
                return False, {**info, "erro": f"Zip corrompido (arquivo ruim: {corrompido})."}
            nomes = zf.namelist()
            conjunto = set(nomes)
            faltando = [n for n in ARQUIVOS_OBRIGATORIOS if n not in conjunto]
            if faltando:
                return False, {
                    **info,
                    "erro": ("Este zip não é um pacote do Sistema MRO — falta " + ", ".join(faltando) + "."),
                }
            # Caminho absoluto ou com `..` escaparia de app\ no Expand-Archive.
            for nome in nomes:
                if nome.startswith(("/", "\\")) or ".." in Path(nome).parts or ":" in nome:
                    return False, {**info, "erro": f"Zip com caminho inválido: {nome}"}
            texto = zf.read("services/constants.py").decode("utf-8", "replace")
    except zipfile.BadZipFile:
        return False, {**info, "erro": "O arquivo não é um .zip válido."}
    except OSError as e:
        return False, {**info, "erro": f"Não consegui ler o arquivo: {e}"}

    versao = ler_versao(texto)
    if not versao:
        return False, {**info, "erro": "Não encontrei a VERSAO dentro do pacote."}

    return True, {"versao": versao, "arquivos": len(nomes), "tamanho": len(dados)}


def _tupla_versao(v: str | None) -> tuple[int, ...] | None:
    try:
        return tuple(int(p) for p in str(v).strip().lstrip("vV").split("."))
    except (ValueError, AttributeError):
        return None


def comparar_versoes(instalada: str, pacote: str) -> str:
    """`"nova"` | `"mesma"` | `"downgrade"` | `"desconhecida"`.

    Compara por TUPLA DE INTEIROS, não por texto: `"6.10.0" > "6.9.0"` é verdade em
    SemVer e falso em ordem alfabética. O sistema vai chegar na 6.10 — o bug nasceria
    calado, deixando de oferecer a atualização.
    """
    a, b = _tupla_versao(instalada), _tupla_versao(pacote)
    if a is None or b is None:
        return "desconhecida"
    tam = max(len(a), len(b))
    a = a + (0,) * (tam - len(a))
    b = b + (0,) * (tam - len(b))
    if b > a:
        return "nova"
    if b == a:
        return "mesma"
    return "downgrade"


# ══════════════════════════════════════════════════════════════════════════════
# GRAVAÇÃO E DISPARO
# ══════════════════════════════════════════════════════════════════════════════


def guardar_pacote(dados: bytes, versao: str, raiz: Path | None = None) -> Path:
    """Grava o zip em `dados\\atualizacoes\\` e poda os antigos. Devolve o caminho."""
    destino_dir = pasta_atualizacoes(raiz)
    destino_dir.mkdir(parents=True, exist_ok=True)
    destino = destino_dir / f"mro-{versao}.zip"
    destino.write_bytes(dados)

    antigos = sorted(
        (p for p in destino_dir.glob("mro-*.zip") if p != destino),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    for velho in antigos[PACOTES_MANTIDOS - 1 :]:
        try:
            velho.unlink()
        except OSError:
            pass  # poda é higiene, não pode derrubar a atualização
    return destino


def preparar_motor(raiz: Path | None = None) -> Path:
    """Copia o bat de `app\\deploy\\` para `dados\\atualizacoes\\` e devolve a cópia.

    Rodar o motor de dentro de `app\\` seguraria lock exatamente na pasta que ele vai
    mover — o `move` falharia e a atualização abortaria sempre.
    """
    origem = motor_de_origem()
    if not origem.is_file():
        raise FileNotFoundError(f"Motor de atualização ausente: {origem}")
    destino_dir = pasta_atualizacoes(raiz)
    destino_dir.mkdir(parents=True, exist_ok=True)
    destino = destino_dir / NOME_MOTOR
    shutil.copy2(origem, destino)
    return destino


def montar_comando(motor: Path, pacote: Path, raiz: Path, pid: int) -> list[str]:
    """Linha de comando do processo destacado (pura — testável sem executar nada).

    Chamado via `cmd.exe /c` em vez de apontar direto para o `.bat`: desde o
    endurecimento do `subprocess` contra o BatBadBut (CVE-2024-3566), as regras de
    citação de `.bat`/`.cmd` mudaram entre versões do Python, e passar pelo COMSPEC é
    o caminho que não depende disso. Caminho com espaço/acento (`C:\\Tarefas Diárias\\`)
    sobrevive porque a forma é LISTA, sem shell.
    """
    return [
        os.environ.get("COMSPEC") or "cmd.exe",
        "/c",
        str(motor),
        str(pacote),
        str(pid),
        str(raiz),
    ]


def disparar(pacote: Path, raiz: Path | None = None, pid: int | None = None) -> tuple[bool, str]:
    """Lança a troca num processo que SOBREVIVE à morte deste. Volta na hora.

    As duas flags são o coração do mecanismo: `DETACHED_PROCESS` corta o vínculo com o
    console do Streamlit (sem ela o filho morre junto quando a janela preta fecha) e
    `CREATE_NEW_PROCESS_GROUP` tira o filho do grupo que recebe o CTRL_CLOSE_EVENT. Sem
    as duas, o motor morreria no passo 1 — logo depois de matar o app e ANTES de religar.

    Saída para DEVNULL porque o próprio bat escreve `ultima_atualizacao.log` ao lado de
    si mesmo: um processo destacado não tem console para onde escrever, e sem o log um
    fracasso vira uma tela em branco sem rastro.
    """
    raiz = raiz or raiz_instalacao()
    pid = os.getpid() if pid is None else pid
    try:
        motor = preparar_motor(raiz)
    except (OSError, FileNotFoundError) as e:
        return False, f"Não consegui preparar o atualizador: {e}"

    cmd = montar_comando(motor, pacote, raiz, pid)
    flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    try:
        subprocess.Popen(
            cmd,
            cwd=str(pasta_atualizacoes(raiz)),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
            creationflags=flags,
        )
    except OSError as e:
        return False, f"Não consegui iniciar o atualizador: {e}"
    return True, "Atualização iniciada."
