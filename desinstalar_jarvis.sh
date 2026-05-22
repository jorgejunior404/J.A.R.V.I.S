#!/usr/bin/env bash
# ╔══════════════════════════════════════════════════════════╗
# ║         J.A.R.V.I.S  —  DESINSTALADOR LINUX             ║
# ╚══════════════════════════════════════════════════════════╝
set -e

CYAN='\033[0;36m'; GREEN='\033[0;32m'; RED='\033[0;31m'; NC='\033[0m'
info() { echo -e "${CYAN}[JARVIS]${NC} $*"; }
ok()   { echo -e "${GREEN}[OK]${NC}    $*"; }

info "Parando e desativando o serviço..."
systemctl --user stop    jarvis.service 2>/dev/null && ok "Serviço parado"   || true
systemctl --user disable jarvis.service 2>/dev/null && ok "Serviço desativado" || true

info "Removendo arquivos..."
rm -f "$HOME/.config/systemd/user/jarvis.service"   && ok "Serviço removido"
rm -f "$HOME/.config/autostart/jarvis.desktop"       && ok "Autostart removido"
rm -f "$HOME/.local/share/applications/jarvis.desktop" && ok "Menu removido"
rm -f "$HOME/.local/share/icons/hicolor/64x64/apps/jarvis.png" && ok "Ícone removido"
rm -f /tmp/jarvis_hud.lock /tmp/jarvis_nivel 2>/dev/null || true

systemctl --user daemon-reload

echo ""
echo -e "${GREEN}J.A.R.V.I.S desinstalado com sucesso.${NC}"
