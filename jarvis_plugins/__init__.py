"""
╔══════════════════════════════════════════════════════════╗
║      J.A.R.V.I.S  —  SISTEMA DE PLUGINS                 ║
║  Registro central de comandos por regex                  ║
╚══════════════════════════════════════════════════════════╝

COMO FUNCIONA
─────────────
Cada plugin (jarvis_estudos, jarvis_gcalendar, jarvis_insights, etc.)
chama `registrar(padroes, handler)` no momento da importação.

O jarvis_core, em processar_comando, percorre os plugins registrados
ANTES de cair na cadeia de elif legada. Se um padrão bater, o handler
do plugin é chamado e processar_comando retorna.

ASSINATURA DO HANDLER
──────────────────────
def handler(comando: str, ctx: "JarvisContext") -> None:
    ctx.falar("...")
    ctx.falar_sync("...")
    ctx.hud.safe_update(...)
    resp = ctx.ouvir_pergunta(timeout=8, limite=10)

EXEMPLO DE REGISTRO (no topo do módulo, fora de qualquer função)
──────────────────────────────────────────────────────────────
    from jarvis_plugins import registrar

    def _handler_plano(comando, ctx):
        ctx.falar(gerar_plano_hoje())

    registrar(
        padroes=["plano de estudos", "o que estudar hoje", "o que estudar"],
        handler=_handler_plano,
        nome="estudos.plano",
    )

PRIORIDADE
──────────
Plugins são checados na ordem de registro. Se dois padrões colidem,
o primeiro registrado ganha. Use `prioridade` (menor = checado antes)
se precisar forçar ordem específica.
"""

import logging

log = logging.getLogger("JARVIS.Plugins")

# Lista de plugins registrados: cada item é um dict
#   {"padroes": [...], "handler": fn, "nome": str, "prioridade": int}
_REGISTRO = []


def registrar(padroes, handler, nome: str = "", prioridade: int = 100):
    """
    Registra um conjunto de padrões (substrings, case-insensitive)
    associados a uma função handler.

    padroes:    lista de strings. Se QUALQUER uma estiver contida no
                comando (já em lowercase), o handler é chamado.
    handler:    função (comando: str, ctx: JarvisContext) -> None
    nome:       identificador para debug/logs (opcional)
    prioridade: ordem de checagem, menor = primeiro (default 100)
    """
    if not padroes or not callable(handler):
        log.warning(f"Registro inválido ignorado: nome={nome!r}")
        return

    _REGISTRO.append({
        "padroes": [p.lower() for p in padroes],
        "handler": handler,
        "nome": nome or handler.__name__,
        "prioridade": prioridade,
    })
    # Mantém ordenado por prioridade (estável: mesma prioridade preserva ordem de registro)
    _REGISTRO.sort(key=lambda r: r["prioridade"])
    log.info(f"Plugin registrado: {nome or handler.__name__} ({len(padroes)} padrões)")


def listar_plugins():
    """Retorna lista de nomes de plugins registrados, na ordem de checagem."""
    return [r["nome"] for r in _REGISTRO]


def resolver(comando: str):
    """
    Procura um handler cujo padrão bata com o comando.
    Retorna (handler, nome_do_plugin) ou (None, None) se nada bateu.
    """
    cmd_lower = comando.lower()
    for entrada in _REGISTRO:
        for padrao in entrada["padroes"]:
            if padrao in cmd_lower:
                return entrada["handler"], entrada["nome"]
    return None, None


def processar_via_plugins(comando: str, ctx) -> bool:
    """
    Tenta resolver e executar o comando via plugins.
    Retorna True se algum plugin tratou o comando, False caso contrário
    (nesse caso o core deve cair no fallback / cadeia legada).
    """
    handler, nome = resolver(comando)
    if handler is None:
        return False

    log.info(f"Plugin '{nome}' tratando: {comando[:50]}")
    try:
        handler(comando, ctx)
    except Exception as e:
        log.error(f"Erro no plugin '{nome}': {e}")
        ctx.falar(f"Tive um problema executando isso, {ctx.usuario}.")
    return True
