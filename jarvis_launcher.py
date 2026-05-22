#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════════════╗
║         J.A.R.V.I.S  —  LAUNCHER                        ║
║  Bandeja do sistema · Atalho global · Instalar serviço   ║
╚══════════════════════════════════════════════════════════╝
"""

import os, sys, signal, subprocess, threading, time, argparse
from pathlib import Path

# ── Caminho absoluto deste launcher ──────────────────────
HERE      = Path(__file__).resolve().parent
HUD_PY    = HERE / "jarvis_hud.py"
PYTHON    = sys.executable
LOCK_FILE = Path("/tmp/jarvis_hud.lock")

# ═══════════════════════════════════════════════════════════
#  CONTROLE DE PROCESSO
# ═══════════════════════════════════════════════════════════
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

def _set_nivel(n):
    pid = _ler_pid()
    if pid and _pid_rodando(pid):
        Path("/tmp/jarvis_nivel").write_text(str(n))
        os.kill(pid, signal.SIGUSR2)
    else:
        iniciar_jarvis()

# ═══════════════════════════════════════════════════════════
#  ÍCONE NA BANDEJA
# ═══════════════════════════════════════════════════════════
def _criar_icone_imagem():
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

# ═══════════════════════════════════════════════════════════
#  INSTALAÇÃO / DESINSTALAÇÃO (Linux — systemd user)
# ═══════════════════════════════════════════════════════════
def _instalar():
    """Instala o J.A.R.V.I.S como serviço systemd do usuário."""
    import shutil, stat

    home        = Path.home()
    icon_dir    = home / ".local/share/icons/hicolor/64x64/apps"
    service_dir = home / ".config/systemd/user"
    autostart   = home / ".config/autostart"
    apps_dir    = home / ".local/share/applications"
    icon_path   = icon_dir / "jarvis.png"

    # Criar diretórios
    for d in [icon_dir, service_dir, autostart, apps_dir]:
        d.mkdir(parents=True, exist_ok=True)

    print("📦 Instalando dependências...")
    subprocess.run(
        [PYTHON, "-m", "pip", "install", "--quiet",
         "--break-system-packages", "pystray", "pillow", "pynput"],
        check=False
    )

    # Gerar ícone PNG
    print("🎨 Gerando ícone...")
    try:
        img = _criar_icone_imagem()
        img.save(str(icon_path))
        print(f"   ✓ Ícone: {icon_path}")
    except Exception as e:
        print(f"   ⚠ Não foi possível gerar ícone: {e}")

    # systemd user service
    service_content = f"""[Unit]
Description=J.A.R.V.I.S HUD Launcher
After=graphical-session.target
PartOf=graphical-session.target

[Service]
Type=simple
ExecStart={PYTHON} {HERE / 'jarvis_launcher.py'}
Restart=on-failure
RestartSec=5
Environment=DISPLAY=:0
Environment=DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/%U/bus
StartLimitBurst=5
StartLimitIntervalSec=60

[Install]
WantedBy=graphical-session.target
"""
    service_file = service_dir / "jarvis.service"
    service_file.write_text(service_content)
    print(f"   ✓ Serviço: {service_file}")

    # XDG Autostart
    desktop_content = f"""[Desktop Entry]
Type=Application
Name=J.A.R.V.I.S
Comment=Assistente HUD — inicia automaticamente
Exec={PYTHON} {HERE / 'jarvis_launcher.py'}
Icon={icon_path}
Terminal=false
Hidden=false
X-GNOME-Autostart-enabled=true
"""
    (autostart / "jarvis.desktop").write_text(desktop_content)
    print(f"   ✓ Autostart: {autostart / 'jarvis.desktop'}")

    # Menu de aplicativos
    menu_content = f"""[Desktop Entry]
Version=1.0
Type=Application
Name=J.A.R.V.I.S
GenericName=Assistente HUD
Comment=Abre ou alterna a visibilidade do J.A.R.V.I.S
Exec={PYTHON} {HERE / 'jarvis_launcher.py'}
Icon={icon_path}
Terminal=false
Categories=Utility;System;
Keywords=jarvis;hud;assistente;
StartupNotify=false
"""
    (apps_dir / "jarvis.desktop").write_text(menu_content)
    print(f"   ✓ Menu: {apps_dir / 'jarvis.desktop'}")

    # Ativar serviço
    print("⚙️  Ativando serviço systemd...")
    subprocess.run(["systemctl", "--user", "daemon-reload"], check=False)
    subprocess.run(["systemctl", "--user", "enable", "jarvis.service"], check=False)
    subprocess.run(["systemctl", "--user", "start",  "jarvis.service"], check=False)

    print("""
╔══════════════════════════════════════════════════════╗
║       J.A.R.V.I.S — INSTALADO COM SUCESSO!          ║
╚══════════════════════════════════════════════════════╝

  ✓ Inicia automaticamente com sua sessão gráfica
  ✓ Ícone na bandeja do sistema
  ✓ Aparece no menu de aplicativos

  Comandos:
    systemctl --user status  jarvis
    systemctl --user stop    jarvis
    systemctl --user restart jarvis
    systemctl --user disable jarvis  (remove do boot)

  Atalhos:
    Ctrl+Alt+J       → Mostrar / Esconder
    Ctrl+Alt+K       → Encerrar
    Ctrl+Shift+1/2/3 → Mudar nível
""")


def _desinstalar():
    """Remove todos os arquivos e o serviço systemd."""
    home = Path.home()

    print("🛑 Parando serviço...")
    subprocess.run(["systemctl", "--user", "stop",    "jarvis.service"], check=False)
    subprocess.run(["systemctl", "--user", "disable", "jarvis.service"], check=False)

    arquivos = [
        home / ".config/systemd/user/jarvis.service",
        home / ".config/autostart/jarvis.desktop",
        home / ".local/share/applications/jarvis.desktop",
        home / ".local/share/icons/hicolor/64x64/apps/jarvis.png",
        Path("/tmp/jarvis_hud.lock"),
        Path("/tmp/jarvis_nivel"),
    ]
    for f in arquivos:
        if f.exists():
            f.unlink()
            print(f"   ✓ Removido: {f}")

    subprocess.run(["systemctl", "--user", "daemon-reload"], check=False)
    print("\n✓ J.A.R.V.I.S desinstalado com sucesso.")


# ═══════════════════════════════════════════════════════════
#  TRAY
# ═══════════════════════════════════════════════════════════
def rodar_tray():
    try:
        import pystray
    except ImportError:
        print("⚠  pystray/Pillow não encontrado — rode: pip install pystray pillow pynput")
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
        elif txt == "Nível 2 — Métricas":  _set_nivel(2)
        elif txt == "Nível 3 — Completo":  _set_nivel(3)
        elif txt == "Encerrar Jarvis":      encerrar_jarvis()
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
#  ATALHOS GLOBAIS
# ═══════════════════════════════════════════════════════════
def _hotkey_loop():
    try:
        from pynput import keyboard as kb
        with kb.GlobalHotKeys({
            '<ctrl>+<alt>+j':   alternar_visibilidade,
            '<ctrl>+<alt>+k':   encerrar_jarvis,
            '<ctrl>+<shift>+1': lambda: _set_nivel(1),
            '<ctrl>+<shift>+2': lambda: _set_nivel(2),
            '<ctrl>+<shift>+3': lambda: _set_nivel(3),
        }) as h:
            print("✓ Atalhos ativos:")
            print("  Ctrl+Alt+J       → Mostrar/Esconder")
            print("  Ctrl+Alt+K       → Encerrar")
            print("  Ctrl+Shift+1/2/3 → Mudar Nível")
            h.join()
    except Exception as e:
        print(f"⚠ Erro nos atalhos: {e}")
        while True:
            time.sleep(60)


# ═══════════════════════════════════════════════════════════
#  ENTRY POINT
# ═══════════════════════════════════════════════════════════
if __name__ == "__main__":
    p = argparse.ArgumentParser(description="J.A.R.V.I.S Launcher")
    p.add_argument("--instalar",    action="store_true", help="Instala como serviço do sistema")
    p.add_argument("--desinstalar", action="store_true", help="Remove o serviço do sistema")
    p.add_argument("--toggle",      action="store_true", help="Alterna visibilidade do HUD")
    args = p.parse_args()

    if   args.instalar:    _instalar()
    elif args.desinstalar: _desinstalar()
    elif args.toggle:      alternar_visibilidade()
    else:                  rodar_tray()