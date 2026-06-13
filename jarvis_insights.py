"""
╔══════════════════════════════════════════════════════════╗
║      J.A.R.V.I.S  —  PLUGIN DE INSIGHTS                 ║
║  Cruza progresso de estudos, provas e agenda             ║
╚══════════════════════════════════════════════════════════╝

Como instalar:
  1. Copie jarvis_plugins/ (pasta completa) para a pasta do JARVIS
  2. Copie este arquivo (jarvis_insights.py) para a pasta do JARVIS
  3. No jarvis_core.py, aplique o PATCH no final deste arquivo

Comandos de voz:
  "Jarvis, como estou indo nos estudos"
  "Jarvis, faz um raio-x da semana"
  "Jarvis, to atrasado em alguma matéria"
  "Jarvis, prioridade de hoje"

O que ele faz:
  - Lê ~/.jarvis_progresso.json (dias estudados, sessões de quiz)
  - Lê ~/.jarvis_provas.json (provas/entregas futuras)
  - Cruza: matéria com prova em <=5 dias mas sem estudo nos últimos
    2 dias -> alerta de risco
  - Sugere foco do dia combinando urgência de prova + lacuna de estudo
"""

import os
import json
import datetime
import logging

from jarvis_plugins import registrar

log = logging.getLogger("JARVIS.Insights")

ARQUIVO_PROVAS    = os.path.expanduser("~/.jarvis_provas.json")
ARQUIVO_PROGRESSO = os.path.expanduser("~/.jarvis_progresso.json")


def _carregar(arquivo: str) -> dict:
    if os.path.exists(arquivo):
        try:
            with open(arquivo, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            log.error(f"Erro lendo {arquivo}: {e}")
    return {}


# ═══════════════════════════════════════════════════════════
#  NOMES DE MATÉRIAS (evita import direto de jarvis_estudos
#  para não criar dependência forte — fallback para a chave bruta)
# ═══════════════════════════════════════════════════════════
def _nome_materia(chave: str) -> str:
    try:
        from jarvis_estudos import MATERIAS
        return MATERIAS.get(chave, {}).get("nome", chave)
    except Exception:
        return chave.capitalize()


# ═══════════════════════════════════════════════════════════
#  ANÁLISE PRINCIPAL
# ═══════════════════════════════════════════════════════════
def _dias_desde_ultimo_estudo(chave: str, progresso: dict) -> int | None:
    datas = progresso.get(chave, {}).get("datas", [])
    if not datas:
        return None
    hoje = datetime.date.today()
    try:
        ultima = max(datetime.date.fromisoformat(d) for d in datas)
        return (hoje - ultima).days
    except Exception:
        return None


def _provas_por_materia(provas: dict) -> dict:
    """Retorna {chave: dias_para_prova_mais_proxima}."""
    hoje = datetime.date.today()
    resultado = {}
    for chave, lista in provas.items():
        dias_min = None
        for p in lista:
            try:
                data = datetime.date.fromisoformat(p["data"])
                dias = (data - hoje).days
                if dias >= 0 and (dias_min is None or dias < dias_min):
                    dias_min = dias
            except Exception:
                continue
        if dias_min is not None:
            resultado[chave] = dias_min
    return resultado


def gerar_raio_x() -> str:
    """
    Gera um relatório falado cruzando provas próximas com
    o quão recente foi o estudo de cada matéria envolvida.
    """
    progresso = _carregar(ARQUIVO_PROGRESSO)
    provas    = _carregar(ARQUIVO_PROVAS)
    proximidade = _provas_por_materia(provas)

    if not proximidade:
        return "Nenhuma prova cadastrada, então não tenho muito o que cruzar ainda."

    alertas  = []   # prova próxima + estudo desatualizado
    ok       = []   # prova próxima mas estudo em dia
    sem_dado = []   # prova próxima, nunca estudou (sem registro)

    for chave, dias_prova in sorted(proximidade.items(), key=lambda x: x[1]):
        nome = _nome_materia(chave)
        dias_estudo = _dias_desde_ultimo_estudo(chave, progresso)

        if dias_estudo is None:
            sem_dado.append((nome, dias_prova))
        elif dias_estudo > 2 and dias_prova <= 5:
            alertas.append((nome, dias_prova, dias_estudo))
        else:
            ok.append((nome, dias_prova, dias_estudo))

    partes = ["Raio-X da semana:"]

    if alertas:
        for nome, dp, de in alertas:
            prazo = "hoje" if dp == 0 else "amanhã" if dp == 1 else f"em {dp} dias"
            partes.append(
                f"Atenção: {nome} tem prova {prazo}, mas você não estuda "
                f"essa matéria há {de} dias."
            )

    if sem_dado:
        for nome, dp in sem_dado:
            prazo = "hoje" if dp == 0 else "amanhã" if dp == 1 else f"em {dp} dias"
            partes.append(
                f"{nome} tem prova {prazo} e ainda não tem registro de estudo."
            )

    if ok:
        nomes_ok = ", ".join(nome for nome, _, _ in ok)
        partes.append(f"Em dia: {nomes_ok}.")

    if not alertas and not sem_dado:
        partes.append("De resto, nenhum risco óbvio identificado.")

    return " ".join(partes)


def gerar_prioridade_do_dia() -> str:
    """
    Combina urgência de prova + lacuna de estudo para sugerir
    UMA matéria prioritária pra hoje (mais direto que o raio-x completo).
    """
    progresso = _carregar(ARQUIVO_PROGRESSO)
    provas    = _carregar(ARQUIVO_PROVAS)
    proximidade = _provas_por_materia(provas)

    if not proximidade:
        return "Sem provas cadastradas. Sugiro seguir o plano de estudos padrão."

    pontuacoes = {}
    for chave, dias_prova in proximidade.items():
        dias_estudo = _dias_desde_ultimo_estudo(chave, progresso)
        de = dias_estudo if dias_estudo is not None else 99

        # quanto menor dias_prova e maior dias sem estudar, maior a urgência
        urgencia = (10 - min(dias_prova, 10)) + min(de, 10)
        pontuacoes[chave] = (urgencia, dias_prova, de)

    chave_top = max(pontuacoes, key=lambda c: pontuacoes[c][0])
    urg, dp, de = pontuacoes[chave_top]
    nome = _nome_materia(chave_top)

    prazo = "hoje" if dp == 0 else "amanhã" if dp == 1 else f"em {dp} dias"
    if de >= 99:
        estudo_str = "sem registro de estudo ainda"
    else:
        estudo_str = f"último estudo há {de} dia{'s' if de != 1 else ''}"

    return (
        f"Prioridade de hoje: {nome}. Prova {prazo}, {estudo_str}. "
        f"Recomendo focar nela primeiro."
    )


# ═══════════════════════════════════════════════════════════
#  HANDLERS (plugins)
# ═══════════════════════════════════════════════════════════
def _handler_raio_x(comando, ctx):
    ctx.hud.safe_update("foco", "RAIO-X", "Cruzando dados...")
    ctx.falar(gerar_raio_x())


def _handler_prioridade(comando, ctx):
    ctx.hud.safe_update("foco", "PRIORIDADE", "Calculando...")
    ctx.falar(gerar_prioridade_do_dia())


# ═══════════════════════════════════════════════════════════
#  REGISTRO
# ═══════════════════════════════════════════════════════════
registrar(
    padroes=[
        "raio-x", "raio x", "como estou indo nos estudos",
        "como estão meus estudos", "estou atrasado em alguma matéria",
        "to atrasado em alguma matéria", "tô atrasado em alguma matéria",
        "risco nas provas",
    ],
    handler=_handler_raio_x,
    nome="insights.raio_x",
)

registrar(
    padroes=[
        "prioridade de hoje", "qual prioridade", "no que eu foco hoje",
        "em que eu devo focar", "qual matéria estudar agora",
    ],
    handler=_handler_prioridade,
    nome="insights.prioridade",
)


"""
═══════════════════════════════════════════════════════════
 PATCH PARA jarvis_core.py
═══════════════════════════════════════════════════════════

── PATCH 1: IMPORTS (após os imports existentes, antes de CONFIGURAÇÃO) ──

import jarvis_insights  # noqa: F401  (registra os comandos via plugin)
from jarvis_plugins import processar_via_plugins
from jarvis_plugins.jarvis_context import JarvisContext

(Garanta que a pasta jarvis_plugins/ esteja no mesmo diretório do
 jarvis_core.py, e que jarvis_estudos.py também esteja presente —
 jarvis_insights usa MATERIAS dele para exibir nomes bonitos.)


── PATCH 2: processar_comando — checagem de plugins ANTES da NLU/elifs ──

Logo após estas linhas existentes:

    def processar_comando(comando: str, hud):
        comando = _resolver_intencao(comando)
        log.info(f"CMD: {comando}")
        hud.safe_update("ativo", "ATIVADO", comando[:32])
        hud.push_historico(re.sub(WAKE_WORD, "", comando).strip())

adicione:

        # ── Tenta resolver via sistema de plugins ────────────
        ctx = JarvisContext(
            hud=hud,
            falar_fn=falar,
            falar_sync_fn=falar_sync,
            ouvir_pergunta_fn=ouvir_pergunta,
            consultar_ia_fn=consultar_ia,
            usuario=USUARIO,
            confirmar_fn=_confirmar,
            notificar_fn=notificar,
            processar_comando_fn=lambda c: processar_comando(c, hud),
        )
        if processar_via_plugins(comando, ctx):
            time.sleep(0.3)
            hud.safe_update(False, "STANDBY", "Aguardando comando...")
            return

E o resto da cadeia de "if any(p in comando for p in [...])" continua
exatamente como está, sem nenhuma alteração — ela só passa a ser o
fallback para o que os plugins não cobrirem.


── PATCH 3 (opcional): migrar comandos existentes pros plugins ──

Conforme for confortável, você pode ir cortando blocos elif do core
e recriando como `registrar(...)` em arquivos próprios (ex: mover o
bloco de "clima" para um jarvis_clima.py com seu próprio registro).
Isso é incremental — não precisa fazer tudo de uma vez.
"""
