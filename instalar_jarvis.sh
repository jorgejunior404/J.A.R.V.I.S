#!/usr/bin/env bash
# ╔══════════════════════════════════════════════════════════╗
# ║         J.A.R.V.I.S  —  INSTALADOR LINUX                ║
# ║  systemd user service + autostart + atalho de app        ║
# ╚══════════════════════════════════════════════════════════╝
set -e

# ── Cores ────────────────────────────────────────────────
CYAN='\033[0;36m'; GREEN='\033[0;32m'; RED='\033[0;31m'; NC='\033[0m'
info()  { echo -e "${CYAN}[JARVIS]${NC} $*"; }
ok()    { echo -e "${GREEN}[OK]${NC}    $*"; }
erro()  { echo -e "${RED}[ERRO]${NC}  $*"; exit 1; }

# ── Detectar onde o projeto está ─────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LAUNCHER="$SCRIPT_DIR/jarvis_launcher.py"
PYTHON="$(which python3)"

[ -f "$LAUNCHER" ] || erro "jarvis_launcher.py não encontrado em $SCRIPT_DIR"
[ -x "$PYTHON"   ] || erro "python3 não encontrado no PATH"

info "Diretório do projeto : $SCRIPT_DIR"
info "Python               : $PYTHON"

# ════════════════════════════════════════════════════════
# 1. DEPENDÊNCIAS
# ════════════════════════════════════════════════════════
info "Verificando dependências Python..."
pip install --quiet --break-system-packages pystray pillow pynput 2>/dev/null \
  || pip install --quiet pystray pillow pynput 2>/dev/null \
  || info "⚠ Não foi possível instalar automaticamente — instale manualmente se necessário"
ok "Dependências OK"

# ════════════════════════════════════════════════════════
# 2. ÍCONE (PNG 64×64 gerado via Python)
# ════════════════════════════════════════════════════════
ICON_DIR="$HOME/.local/share/icons/hicolor/64x64/apps"
ICON_PATH="$ICON_DIR/jarvis.png"
mkdir -p "$ICON_DIR"

info "Gerando ícone PNG..."
python3 - <<'PYEOF'
import sys, os
sys.path.insert(0, os.environ.get("SCRIPT_DIR", "."))
try:
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
    icon_path = os.path.join(os.environ.get("ICON_DIR",""), "jarvis.png")
    img.save(icon_path)
    print(f"Ícone salvo em {icon_path}")
except Exception as e:
    print(f"Aviso: não foi possível gerar ícone PNG: {e}")
PYEOF
export SCRIPT_DIR ICON_DIR
python3 - <<'PYEOF'
import sys, os
sys.path.insert(0, os.environ.get("SCRIPT_DIR", "."))
try:
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
    icon_path = os.path.join(os.environ.get("ICON_DIR",""), "jarvis.png")
    img.save(icon_path)
except Exception as e:
    print(f"Aviso: {e}")
PYEOF
ok "Ícone: $ICON_PATH"

# ════════════════════════════════════════════════════════
# 3. SYSTEMD USER SERVICE
# ════════════════════════════════════════════════════════
SERVICE_DIR="$HOME/.config/systemd/user"
SERVICE_FILE="$SERVICE_DIR/jarvis.service"
mkdir -p "$SERVICE_DIR"

info "Criando serviço systemd do usuário..."
cat > "$SERVICE_FILE" <<EOF
[Unit]
Description=J.A.R.V.I.S HUD Launcher
Documentation=https://github.com/seu-usuario/jarvis
# Garante que a sessão gráfica (D-Bus, display) esteja pronta
After=graphical-session.target
PartOf=graphical-session.target

[Service]
Type=simple
ExecStart=$PYTHON $LAUNCHER
Restart=on-failure
RestartSec=5
# Passa as variáveis de ambiente da sessão gráfica
Environment=DISPLAY=:0
Environment=DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/%U/bus
# Evita loop de reinício em caso de crash constante
StartLimitBurst=5
StartLimitIntervalSec=60

[Install]
WantedBy=graphical-session.target
EOF
ok "Serviço criado: $SERVICE_FILE"

# ════════════════════════════════════════════════════════
# 4. AUTOSTART (XDG — funciona em GNOME, KDE, XFCE, etc.)
# ════════════════════════════════════════════════════════
AUTOSTART_DIR="$HOME/.config/autostart"
AUTOSTART_FILE="$AUTOSTART_DIR/jarvis.desktop"
mkdir -p "$AUTOSTART_DIR"

info "Criando entrada de autostart XDG..."
cat > "$AUTOSTART_FILE" <<EOF
[Desktop Entry]
Type=Application
Name=J.A.R.V.I.S
Comment=Assistente HUD — inicia automaticamente
Exec=$PYTHON $LAUNCHER
Icon=$ICON_PATH
Terminal=false
Hidden=false
X-GNOME-Autostart-enabled=true
EOF
ok "Autostart: $AUTOSTART_FILE"

# ════════════════════════════════════════════════════════
# 5. ATALHO NO MENU DO SISTEMA (Lançador de Aplicativos)
# ════════════════════════════════════════════════════════
APP_DIR="$HOME/.local/share/applications"
APP_FILE="$APP_DIR/jarvis.desktop"
mkdir -p "$APP_DIR"

info "Registrando no menu de aplicativos..."
cat > "$APP_FILE" <<EOF
[Desktop Entry]
Version=1.0
Type=Application
Name=J.A.R.V.I.S
GenericName=Assistente HUD
Comment=Abre ou alterna a visibilidade do J.A.R.V.I.S
Exec=$PYTHON $LAUNCHER
Icon=$ICON_PATH
Terminal=false
Categories=Utility;System;
Keywords=jarvis;hud;assistente;
StartupNotify=false
EOF
ok "Menu: $APP_FILE"

# ════════════════════════════════════════════════════════
# 6. ATIVAR E INICIAR O SERVIÇO
# ════════════════════════════════════════════════════════
info "Ativando serviço systemd..."
systemctl --user daemon-reload
systemctl --user enable jarvis.service
systemctl --user start  jarvis.service
ok "Serviço ativo e rodando!"

# ════════════════════════════════════════════════════════
# 7. RESUMO FINAL
# ════════════════════════════════════════════════════════
echo ""
echo -e "${CYAN}╔══════════════════════════════════════════════════╗${NC}"
echo -e "${CYAN}║        J.A.R.V.I.S — INSTALAÇÃO CONCLUÍDA       ║${NC}"
echo -e "${CYAN}╚══════════════════════════════════════════════════╝${NC}"
echo ""
echo -e "  ${GREEN}✓${NC} Serviço systemd  : jarvis.service (user)"
echo -e "  ${GREEN}✓${NC} Autostart XDG    : ~/.config/autostart/jarvis.desktop"
echo -e "  ${GREEN}✓${NC} Menu de apps     : ~/.local/share/applications/jarvis.desktop"
echo -e "  ${GREEN}✓${NC} Ícone            : $ICON_PATH"
echo ""
echo -e "  ${CYAN}Comandos úteis:${NC}"
echo -e "    systemctl --user status  jarvis   # Ver status"
echo -e "    systemctl --user stop    jarvis   # Parar"
echo -e "    systemctl --user restart jarvis   # Reiniciar"
echo -e "    systemctl --user disable jarvis   # Remover do boot"
echo ""
echo -e "  ${CYAN}Atalhos de teclado:${NC}"
echo -e "    Ctrl+Alt+J   → Mostrar / Esconder"
echo -e "    Ctrl+Alt+K   → Encerrar"
echo -e "    Ctrl+Shift+1/2/3 → Mudar nível"
echo ""
