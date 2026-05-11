#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════════════╗
║         J.A.R.V.I.S  —  LAUNCHER                        ║
║  Bandeja do sistema · Atalho global · Instalar serviço   ║
╚══════════════════════════════════════════════════════════╝
"""

import os, sys, signal, socket, subprocess, threading, time, argparse
from pathlib import Path

# ── Caminho absoluto deste launcher ──────────────────────
HERE     = Path(__file__).resolve().parent
HUD_PY   = HERE / "jarvis_hud.py"
PYTHON   = sys.executable
LOCK_FILE = Path("/tmp/jarvis_hud.lock")   # PID do processo HUD

# ... [MANTIVE TODAS AS FUNÇÕES DE PID E PROCESSO IGUAIS] ...

def _pid_rodando(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except (ProcessLookupError, PermissionError):
        return False

def _ler_pid() -> int | None:
    try:
        return int(LOCK_FILE.read_text().strip())
    except Exception:
        return None

def _salvar_pid(pid: int):
    LOCK_FILE.write_text(str(pid))

def _limpar_lock():
    try:
        LOCK_FILE.unlink()
    except Exception:
        pass

def jarvis_esta_rodando() -> bool:
    pid = _ler_pid()
    return pid is not None and _pid_rodando(pid)

def iniciar_jarvis() -> bool:
    if jarvis_esta_rodando():
        return False
    env = os.environ.copy()
    proc = subprocess.Popen(
        [PYTHON, str(HUD_PY)],
        cwd=str(HERE),
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    _salvar_pid(proc.pid)
    return True

def alternar_visibilidade():
    pid = _ler_pid()
    if pid and _pid_rodando(pid):
        os.kill(pid, signal.SIGUSR1)
    else:
        _limpar_lock()
        iniciar_jarvis()

def encerrar_jarvis():
    pid = _ler_pid()
    if pid and _pid_rodando(pid):
        os.kill(pid, signal.SIGTERM)
    _limpar_lock()

# ═══════════════════════════════════════════════════════════
#  ÍCONE NA BANDEJA (pystray) - SEU VISUAL ORIGINAL
# ═══════════════════════════════════════════════════════════
def _criar_icone_imagem(cor_borda="#00BFFF", cor_nucleo="#001828"):
    from PIL import Image, ImageDraw
    img  = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    cx, cy, r = 32, 32, 28
    draw.ellipse([cx-r, cy-r, cx+r, cy+r], fill="#050d1a")
    for radius, alpha in [(28, 80), (22, 40), (18, 20)]:
        draw.ellipse([cx-radius, cy-radius, cx+radius, cy+radius],
                     outline="#00BFFF" + f"{alpha:02x}", width=1)
    draw.ellipse([cx-r, cy-r, cx+r, cy+r], outline="#00BFFF", width=2)
    draw.ellipse([cx-12, cy-12, cx+12, cy+12], fill="#001828", outline="#00BFFF", width=2)
    for dx, dy in [(-4,-3),(-3,-3),(-2,-3),(-4,-2),(-4,-1),(-3,-1),(-2,-1),(-4,0),(-4,1),(-4,2)]:
        draw.point([cx+dx, cy+dy], fill="#00BFFF")
    for dx, dy in [(2,-3),(4,-3),(3,-3),(2,-2),(4,-2),(2,-1),(3,-1),(4,-1),(2,0),(4,0),(2,1),(4,1),(2,2),(4,2)]:
        draw.point([cx+dx, cy+dy], fill="#00BFFF")
    return img

def _criar_icone_vermelho():
    from PIL import Image, ImageDraw
    img  = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    cx, cy, r = 32, 32, 28
    draw.ellipse([cx-r, cy-r, cx+r, cy+r], fill="#050d1a")
    draw.ellipse([cx-r, cy-r, cx+r, cy+r], outline="#FF3333", width=2)
    draw.ellipse([cx-12, cy-12, cx+12, cy+12], fill="#1a0010", outline="#FF3333", width=2)
    return img

# ... [MANTIVE A FUNÇÃO rodar_tray() EXATAMENTE COMO VOCÊ ESCREVEU] ...
def _set_nivel(n):
    pid = _ler_pid()
    if pid and _pid_rodando(pid):
        Path("/tmp/jarvis_nivel").write_text(str(n))
        os.kill(pid, signal.SIGUSR2)
    else:
        iniciar_jarvis()

def rodar_tray():
    try:
        import pystray
        from PIL import Image
    except ImportError:
        print("⚠  pystray/Pillow não encontrado")
        _hotkey_loop()
        return

    icone_on  = _criar_icone_imagem()
    icone_off = _criar_icone_vermelho()

    def _status_title():
        return "J.A.R.V.I.S - ONLINE" if jarvis_esta_rodando() else "J.A.R.V.I.S - OFFLINE"

    def _on_click(icon, item):
        txt = str(item)
        if txt == "Iniciar / Mostrar Jarvis":
            if jarvis_esta_rodando():
                alternar_visibilidade()
            else:
                iniciar_jarvis()
                time.sleep(0.8)
        elif txt == "Nível 1 — Só a bola": _set_nivel(1)
        elif txt == "Nível 2 — Métricas": _set_nivel(2)
        elif txt == "Nível 3 — Completo": _set_nivel(3)
        elif txt == "Encerrar Jarvis": encerrar_jarvis()
        elif txt == "Sair do Launcher":
            icon.stop()
            sys.exit(0)

    menu = pystray.Menu(
        pystray.MenuItem("Iniciar / Mostrar Jarvis", _on_click, default=True),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Nível 1 — Só a bola",  _on_click),
        pystray.MenuItem("Nível 2 — Métricas",   _on_click),
        pystray.MenuItem("Nível 3 — Completo",   _on_click),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Encerrar Jarvis",       _on_click),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Sair do Launcher",      _on_click),
    )

    icon = pystray.Icon("jarvis", icone_on, _status_title(), menu)
    threading.Thread(target=lambda: (time.sleep(2), _hotkey_loop()), daemon=True).start()
    
    if not jarvis_esta_rodando():
        threading.Thread(target=iniciar_jarvis, daemon=True).start()
    icon.run()

# ═══════════════════════════════════════════════════════════
#  O BLOCO QUE PRECISAVA DE CORREÇÃO (Ajustado)
# ═══════════════════════════════════════════════════════════
def _hotkey_loop():
    try:
        from pynput import keyboard as kb

        # Usamos o GlobalHotKeys para simplificar a lógica e evitar erros de 'hash'
        # Trocamos ALT por SHIFT nos níveis (1, 2, 3) para não conflitar com o Linux
        with kb.GlobalHotKeys({
            '<ctrl>+<alt>+j': alternar_visibilidade,
            '<ctrl>+<alt>+k': encerrar_jarvis,
            '<ctrl>+<shift>+1': lambda: _set_nivel(1),
            '<ctrl>+<shift>+2': lambda: _set_nivel(2),
            '<ctrl>+<shift>+3': lambda: _set_nivel(3),
        }) as h:
            print("✓ [SISTEMA] Atalhos configurados:")
            print("  - Ctrl+Alt+J: Mostrar/Esconder")
            print("  - Ctrl+Alt+K: Encerrar")
            print("  - Ctrl+Shift+1/2/3: Mudar Nível (Tamanho)")
            h.join()

    except Exception as e:
        print(f"⚠ Erro no loop de atalhos: {e}")
        # Mantém a thread viva caso ocorra um erro temporário
        import time
        while True:
            time.sleep(60)

if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--instalar", action="store_true")
    p.add_argument("--desinstalar", action="store_true")
    p.add_argument("--toggle", action="store_true")
    args = p.parse_args()

    if args.instalar: # [Sua lógica de instalação original...]
        pass 
    elif args.toggle: alternar_visibilidade()
    else: rodar_tray()