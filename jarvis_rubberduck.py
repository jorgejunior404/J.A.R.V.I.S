"""
╔══════════════════════════════════════════════════════════╗
║      J.A.R.V.I.S  —  PLUGIN RUBBER DUCK                 ║
║  Modo "pensar em voz alta" com perguntas socráticas      ║
╚══════════════════════════════════════════════════════════╝

Como instalar:
  1. Copie este arquivo (jarvis_rubberduck.py) para a pasta do JARVIS
  2. No jarvis_core.py, adicione o import (ver PATCH no final)

Comandos de voz:
  "Jarvis, vou pensar em voz alta"
  "Jarvis, modo pato"
  "Jarvis, rubber duck"
  ... (qualquer fala enquanto o modo estiver ativo)
  "Jarvis, sai do modo pato" / "Jarvis, encerrar pato"

O que ele faz:
  - Entra num loop de escuta contínua (sem precisar repetir "jarvis")
  - Para cada coisa que você fala, NÃO dá a resposta direto
  - Em vez disso, faz uma pergunta socrática curta pra te ajudar
    a destravar o raciocínio sozinho
  - Sai do modo com palavras-chave de saída
"""

import logging

from jarvis_plugins import registrar

log = logging.getLogger("JARVIS.RubberDuck")

_ATIVO = False

_PALAVRAS_SAIDA = [
    "sai do modo pato", "encerrar pato", "sair do pato",
    "para o rubber duck", "encerra o rubber duck", "sai do rubber duck",
    "modo pato não", "cancela o pato", "obrigado pato", "valeu pato",
]

_SYSTEM_PROMPT_DUCK = """Você é um "rubber duck" — uma técnica de depuração onde o
desenvolvedor explica o problema em voz alta para um pato de borracha
e, ao fazer isso, encontra a solução sozinho.

Seu papel: NUNCA dar a resposta direta ou a solução do problema.
Em vez disso, faça UMA pergunta curta (no máximo 1 frase) que ajude
a pessoa a questionar suas próprias suposições, considerar um caso
que talvez não tenha pensado, ou reformular o problema.

Exemplos de boas perguntas:
- "E se essa variável já tiver sido modificada antes desse ponto?"
- "O que acontece se essa lista estiver vazia?"
- "Você já confirmou que essa função está sendo chamada mesmo?"
- "Isso acontece sempre ou só em alguns casos?"

Responda em português brasileiro, de forma natural e breve (1 frase,
no máximo 2). Nunca dê a resposta. Nunca escreva código. Apenas pergunte."""


def _handler_iniciar(comando, ctx):
    global _ATIVO
    if _ATIVO:
        ctx.falar(f"O modo pato já está ativo, {ctx.usuario}.")
        return

    _ATIVO = True
    ctx.hud.safe_update("ia", "RUBBER DUCK", "Modo ativo")
    ctx.falar_sync(
        f"Modo pato de borracha ativado, {ctx.usuario}. "
        f"Pode começar a pensar em voz alta. Diga 'sai do modo pato' quando terminar."
    )

    _loop_duck(ctx)


def _loop_duck(ctx):
    global _ATIVO

    while _ATIVO:
        ctx.hud.safe_update("ia", "PATO ESCUTANDO", "")
        fala = ctx.ouvir_pergunta(timeout=30, limite=60)

        if not fala:
            continue

        if any(p in fala for p in _PALAVRAS_SAIDA):
            _ATIVO = False
            ctx.hud.safe_update(False, "STANDBY", "Aguardando comando...")
            ctx.falar(f"Saindo do modo pato, {ctx.usuario}. Foi útil?")
            return

        ctx.hud.safe_update("ia", "PATO PENSANDO", fala[:24])

        if ctx.consultar_ia:
            pergunta = ctx.consultar_ia(
                fala, curto=False, sistema=_SYSTEM_PROMPT_DUCK
            )
        else:
            pergunta = "Hmm, e por que você acha que isso acontece?"

        ctx.falar(pergunta)


def _handler_status(comando, ctx):
    if _ATIVO:
        ctx.falar(f"Modo pato está ativo, {ctx.usuario}.")
    else:
        ctx.falar(f"Modo pato está desligado, {ctx.usuario}.")


registrar(
    padroes=[
        "vou pensar em voz alta", "modo pato", "rubber duck",
        "ativar pato", "pensar em voz alta", "modo de pensamento",
    ],
    handler=_handler_iniciar,
    nome="rubberduck.iniciar",
)

registrar(
    padroes=[
        "status do pato", "modo pato está ativo", "o pato está ativo",
    ],
    handler=_handler_status,
    nome="rubberduck.status",
)


"""
═══════════════════════════════════════════════════════════
 PATCH PARA jarvis_core.py
═══════════════════════════════════════════════════════════

Adicione junto aos outros imports de plugins (mesmo bloco do
jarvis_insights):

import jarvis_rubberduck  # noqa: F401

Não precisa de mais nada — ele já se registra automaticamente
e é resolvido pelo processar_via_plugins que já foi adicionado.

ATENÇÃO — COMPORTAMENTO BLOQUEANTE:
O modo pato entra num while loop dentro do próprio handler,
ou seja, ele BLOQUEIA a thread que está processando o comando
até a pessoa dizer a frase de saída (ou dar timeout 5x seguidos
sem fala, se você quiser adicionar esse limite).

Isso é aceitável porque processar_comando já roda numa thread
separada quando chamado pelo Web HUD (via threading.Thread em
jarvis_web_hud.py) e pelo loop de voz principal (rodar_jarvis)
roda sequencialmente de qualquer forma — então durante o modo
pato, comandos por voz com wake word ficam pausados até saída,
mas o Web HUD / outras integrações continuam funcionando em
suas próprias threads.

Se quiser que o modo pato tenha timeout automático (sai sozinho
após N tentativas sem resposta), me avise que adiciono.
"""
