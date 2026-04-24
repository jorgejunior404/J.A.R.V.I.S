"""
jarvis_plugins.py
Cada plugin é uma função pura que recebe (comando, cfg, hud, falar_fn)
e retorna True se tratou o comando, False se não é da sua alçada.
Adicione novos plugins aqui sem tocar no jarvis_core.py
"""

import os
import subprocess
import datetime
import psutil
import requests


# ─────────────────────────────────────────────
#  Utilitário interno
# ─────────────────────────────────────────────

def _match(comando: str, lista: list) -> bool:
    return any(p in comando for p in lista)


# ─────────────────────────────────────────────
#  Plugin: Mídia (playerctl)
# ─────────────────────────────────────────────

def plugin_media(comando, cfg, hud, falar):
    c = cfg.get("plugins", {}).get("media", {})
    if not c.get("ativo", True):
        return False

    if _match(comando, c.get("comandos_pause", [])):
        os.system("playerctl pause")
        falar("Música pausada, senhor.")
        hud.safe_update(cfg["hud"]["cor_primaria"], "PAUSADO", "playerctl")
        return True

    if _match(comando, c.get("comandos_next", [])):
        os.system("playerctl next")
        falar("Pulando faixa.")
        return True

    if _match(comando, c.get("comandos_prev", [])):
        os.system("playerctl previous")
        falar("Retornando faixa.")
        return True

    if _match(comando, c.get("comandos_play", [])):
        os.system("playerctl play")
        falar("Retomando reprodução.")
        return True

    return False


# ─────────────────────────────────────────────
#  Plugin: Aplicativos
# ─────────────────────────────────────────────

def plugin_apps(comando, cfg, hud, falar):
    c = cfg.get("plugins", {}).get("apps", {})
    if not c.get("ativo", True):
        return False

    gatilhos = ["abrir", "iniciar", "abre", "inicia", "lança", "lancar"]
    if not _match(comando, gatilhos):
        return False

    mapa = c.get("mapeamento", {})
    for app, palavras in mapa.items():
        if _match(comando, palavras):
            try:
                subprocess.Popen([app])
                falar(f"Abrindo {app}, senhor.")
                hud.safe_update(cfg["hud"]["cor_ok"], "ABRINDO", app[:12])
            except FileNotFoundError:
                falar(f"Não encontrei o {app} instalado, senhor.")
            return True

    falar("Não identifiquei qual aplicativo abrir, senhor.")
    return True


# ─────────────────────────────────────────────
#  Plugin: Foco / Pomodoro
# ─────────────────────────────────────────────

def plugin_foco(comando, cfg, hud, falar):
    c = cfg.get("plugins", {}).get("foco", {})
    if not c.get("ativo", True):
        return False

    if not _match(comando, c.get("comandos", [])):
        return False

    dur = c.get("duracao_minutos", 25)
    hud.safe_update(cfg["hud"]["cor_foco"], "MODO FOCO", f"{dur} min")
    falar(f"Protocolo de foco iniciado. {dur} minutos no relógio, senhor.")
    return True


# ─────────────────────────────────────────────
#  Plugin: Clima
# ─────────────────────────────────────────────

def plugin_clima(comando, cfg, hud, falar):
    c = cfg.get("plugins", {}).get("clima", {})
    if not c.get("ativo", True):
        return False

    if not _match(comando, c.get("comandos", [])):
        return False

    cidade = c.get("cidade", "Sao_Paulo")
    try:
        r = requests.get(f"http://wttr.in/{cidade}?format=3", timeout=4)
        info = r.text.strip()
        falar(f"Condição atual: {info}")
        hud.safe_update(cfg["hud"]["cor_primaria"], "CLIMA", info[:20])
    except Exception:
        falar("Não consegui acessar os dados meteorológicos, senhor.")
    return True


# ─────────────────────────────────────────────
#  Plugin: Hora e Data
# ─────────────────────────────────────────────

def plugin_hora_data(comando, cfg, hud, falar):
    c = cfg.get("plugins", {}).get("hora_data", {})
    if not c.get("ativo", True):
        return False

    if _match(comando, c.get("comandos_hora", [])):
        hora = datetime.datetime.now().strftime("%H:%M")
        falar(f"São exatamente {hora}, senhor.")
        return True

    if _match(comando, c.get("comandos_data", [])):
        hoje = datetime.datetime.now().strftime("%d de %B de %Y")
        falar(f"Hoje é {hoje}, senhor.")
        return True

    return False


# ─────────────────────────────────────────────
#  Plugin: Bateria
# ─────────────────────────────────────────────

def plugin_bateria(comando, cfg, hud, falar):
    c = cfg.get("plugins", {}).get("bateria", {})
    if not c.get("ativo", True):
        return False

    if not _match(comando, c.get("comandos", [])):
        return False

    try:
        bat = psutil.sensors_battery()
        nivel = int(bat.percent)
        carregando = "carregando" if bat.power_plugged else "descarregando"
        falar(f"Bateria em {nivel} por cento, {carregando}, senhor.")
        hud.barra_bat.set(nivel / 100)
        hud.safe_update(cfg["hud"]["cor_primaria"], "BATERIA", f"{nivel}%")
    except Exception:
        falar("Não consegui ler o status da bateria.")
    return True


# ─────────────────────────────────────────────
#  Plugin: Sistema (desligar, silêncio, voz)
# ─────────────────────────────────────────────

def plugin_sistema(comando, cfg, hud, falar, falar_sync_fn, estado):
    """
    estado: dict mutável compartilhado com o core.
    Campos usados: estado['silencioso']
    """
    c = cfg.get("plugins", {}).get("sistema", {})
    if not c.get("ativo", True):
        return False

    if _match(comando, c.get("comandos_desligar", [])):
        falar_sync_fn("Desligando sistemas. Tenha um bom dia, senhor.")
        hud.animacao_shutdown()
        return True

    if _match(comando, c.get("comandos_silencio", [])):
        estado["silencioso"] = True
        hud.safe_update(cfg["hud"]["cor_foco"], "SILENCIOSO", "Sem voz")
        # Não fala — está no modo silencioso
        return True

    if _match(comando, c.get("comandos_voz", [])):
        estado["silencioso"] = False
        hud.safe_update(cfg["hud"]["cor_ok"], "VOZ ATIVA", "Falando")
        falar("Modo de voz reativado, senhor.")
        return True

    return False


# ─────────────────────────────────────────────
#  Registro de todos os plugins (ordem = prioridade)
# ─────────────────────────────────────────────

PLUGINS = [
    plugin_hora_data,
    plugin_bateria,
    plugin_clima,
    plugin_media,
    plugin_apps,
    plugin_foco,
    # plugin_sistema é tratado separadamente por precisar de falar_sync + estado
]
