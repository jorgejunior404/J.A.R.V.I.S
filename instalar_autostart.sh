#!/bin/bash
# ╔══════════════════════════════════════════════════════════╗
# ║      J.A.R.V.I.S — INSTALADOR DE AUTOSTART             ║
# ║  Instala o launcher para iniciar junto com o sistema    ║
# ╚══════════════════════════════════════════════════════════╝
#
# Como usar:
#   chmod +x instalar_autostart.sh
#   ./instalar_autostart.sh
#
# O script detecta automaticamente onde estão seus arquivos
# e cria a entrada de autostart correta para o seu ambiente.

set -e

# ── Detecta onde estão os arquivos do JARVIS ─────────────
JARVIS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LAUNCHER="$JARVIS_DIR/jarvis_launcher.py"
PYTHON="$(which python3)"

echo "╔══════════════════════════════════════════════════════╗"
echo "║         J.A.R.V.I.S — Instalador de Autostart       ║"
echo "╚══════════════════════════════════════════════════════╝"
echo ""
echo "📁 Diretório do JARVIS: $JARVIS_DIR"
echo "🐍 Python: $PYTHON"
echo ""

# Verifica se o launcher existe
if [ ! -f "$LAUNCHER" ]; then
    echo "❌ ERRO: jarvis_launcher.py não encontrado em $JARVIS_DIR"
    echo "   Certifique-se de rodar este script dentro da pasta do JARVIS."
    exit 1
fi

# ── MÉTODO 1: XDG Autostart (.desktop no ~/.config/autostart) ──
# Funciona em: GNOME, KDE, XFCE, Cinnamon e qualquer DE que siga o padrão XDG
echo "📌 Instalando via XDG Autostart (funciona em GNOME, KDE, XFCE, etc)..."

AUTOSTART_DIR="$HOME/.config/autostart"
mkdir -p "$AUTOSTART_DIR"

cat > "$AUTOSTART_DIR/jarvis.desktop" << EOF
[Desktop Entry]
Type=Application
Name=J.A.R.V.I.S
Comment=JARVIS Mark XII - Assistente Pessoal
Exec=$PYTHON $LAUNCHER
Icon=utilities-terminal
Terminal=false
Hidden=false
NoDisplay=false
X-GNOME-Autostart-enabled=true
X-KDE-autostart-after=panel
StartupNotify=false
EOF

echo "   ✅ Arquivo criado: $AUTOSTART_DIR/jarvis.desktop"

# ── MÉTODO 2: systemd --user (mais robusto, reinicia se travar) ──
echo ""
echo "📌 Instalando via systemd --user (mais robusto, reinicia automaticamente)..."

SYSTEMD_DIR="$HOME/.config/systemd/user"
mkdir -p "$SYSTEMD_DIR"

cat > "$SYSTEMD_DIR/jarvis.service" << EOF
[Unit]
Description=J.A.R.V.I.S Mark XII - Assistente Pessoal
Documentation=https://github.com/seu-repo/jarvis
After=graphical-session.target
Wants=graphical-session.target

[Service]
Type=simple
WorkingDirectory=$JARVIS_DIR
ExecStart=$PYTHON $LAUNCHER
Restart=on-failure
RestartSec=5s
Environment=DISPLAY=:0
Environment=DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/%i/bus

[Install]
WantedBy=graphical-session.target
EOF

# Recarrega o systemd e habilita o serviço
if systemctl --user daemon-reload 2>/dev/null; then
    systemctl --user enable jarvis.service 2>/dev/null && \
        echo "   ✅ Serviço systemd habilitado: ~/.config/systemd/user/jarvis.service" || \
        echo "   ⚠️  Serviço criado mas não pôde ser habilitado agora (normal antes do login gráfico)"
else
    echo "   ⚠️  systemd --user não disponível agora (o arquivo foi criado de qualquer forma)"
fi

# ── MÉTODO 3: Script de inicialização manual (fallback) ──
echo ""
echo "📌 Criando script de controle rápido..."

cat > "$JARVIS_DIR/jarvis_start.sh" << EOF
#!/bin/bash
# Script de inicialização manual do JARVIS
# Use este se os métodos automáticos não funcionarem

cd "$JARVIS_DIR"
nohup $PYTHON jarvis_launcher.py > /tmp/jarvis_output.log 2>&1 &
echo "JARVIS iniciado. PID: \$!"
echo "Log em: /tmp/jarvis_output.log"
EOF

chmod +x "$JARVIS_DIR/jarvis_start.sh"
echo "   ✅ Script criado: $JARVIS_DIR/jarvis_start.sh"

# ── Resumo ────────────────────────────────────────────────
echo ""
echo "╔══════════════════════════════════════════════════════╗"
echo "║                   INSTALAÇÃO CONCLUÍDA               ║"
echo "╚══════════════════════════════════════════════════════╝"
echo ""
echo "✅ O JARVIS agora inicia automaticamente quando você fizer login."
echo ""
echo "📋 O que foi instalado:"
echo "   • XDG Autostart → $AUTOSTART_DIR/jarvis.desktop"
echo "   • Serviço systemd → $SYSTEMD_DIR/jarvis.service"
echo "   • Script manual → $JARVIS_DIR/jarvis_start.sh"
echo ""
echo "🔧 Comandos úteis:"
echo "   Iniciar agora:     $JARVIS_DIR/jarvis_start.sh"
echo "   Ver logs:          tail -f /tmp/jarvis_output.log"
echo "   Status systemd:    systemctl --user status jarvis"
echo "   Parar serviço:     systemctl --user stop jarvis"
echo "   Desabilitar auto:  systemctl --user disable jarvis"
echo ""
echo "💡 Dica: reinicie o sistema para confirmar que funcionou."
echo "   Ou teste agora sem reiniciar:"
echo "   $JARVIS_DIR/jarvis_start.sh"
