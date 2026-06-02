"""
╔══════════════════════════════════════════════════════════╗
║         J.A.R.V.I.S  —  WEB HUD SERVER                  ║
║  FastAPI + WebSocket · Controlável pelo celular          ║
╚══════════════════════════════════════════════════════════╝

Como usar:
    python jarvis_web_hud.py

Acesse no celular (mesma rede Wi-Fi):
    http://<IP-DO-PC>:8765

Para descobrir o IP do PC:
    ip addr show | grep "inet " | grep -v 127

Integração com jarvis_core.py:
    Adicione em rodar_jarvis():
        from jarvis_web_hud import iniciar_servidor_web
        iniciar_servidor_web(hud, falar_sync, processar_comando)
"""

import os, sys, json, time, datetime, asyncio, threading, socket
import psutil
from pathlib import Path
from collections import deque

# ── FastAPI / WebSocket ───────────────────────────────────
try:
    from fastapi import FastAPI, WebSocket, WebSocketDisconnect
    from fastapi.responses import HTMLResponse
    import uvicorn
except ImportError:
    print("ERRO: pip install fastapi uvicorn websockets")
    sys.exit(1)

# ── Tenta importar jarvis_core se disponível ─────────────
try:
    from jarvis_core import (
        processar_comando as _processar,
        falar_sync as _falar_sync,
        falar as _falar,
        ouvir_pergunta,
        log,
        USUARIO,
    )
    _CORE_OK = True
except ImportError:
    _CORE_OK = False
    USUARIO  = "senhor"
    import logging
    log = logging.getLogger("JARVIS.Web")
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s [%(levelname)s] %(message)s")

# ═══════════════════════════════════════════════════════════
#  ESTADO GLOBAL COMPARTILHADO
# ═══════════════════════════════════════════════════════════
class JarvisState:
    def __init__(self):
        self.status   = "STANDBY"
        self.msg      = "Aguardando comando..."
        self.cor      = "accent"
        self.historico = deque(maxlen=20)
        self.clientes: list[WebSocket] = []
        self._lock = threading.Lock()

    def update(self, cor, acao: str, msg: str = ""):
        with self._lock:
            self.cor    = cor or "accent"
            self.status = acao.upper()
            self.msg    = msg or ""
        asyncio.run_coroutine_threadsafe(
            self._broadcast("state", {
                "cor": str(self.cor), "status": self.status, "msg": self.msg
            }),
            _loop
        )

    def push_cmd(self, cmd: str):
        ts = datetime.datetime.now().strftime("%H:%M")
        with self._lock:
            self.historico.appendleft({"cmd": cmd[:60], "ts": ts})
        asyncio.run_coroutine_threadsafe(
            self._broadcast("history", {"cmd": cmd[:60], "ts": ts}),
            _loop
        )

    async def _broadcast(self, tipo: str, payload: dict):
        mortos = []
        msg = json.dumps({"type": tipo, **payload})
        for ws in self.clientes:
            try:
                await ws.send_text(msg)
            except Exception:
                mortos.append(ws)
        for ws in mortos:
            if ws in self.clientes:
                self.clientes.remove(ws)

state  = JarvisState()
_loop: asyncio.AbstractEventLoop = None
_hud_ref   = None
_falar_ref = None
_cmd_ref   = None

# ═══════════════════════════════════════════════════════════
#  ADAPTADOR DE HUD (para usar state.update como safe_update)
# ═══════════════════════════════════════════════════════════
class WebHUDAdapter:
    """Espelha a API do JarvisHUD para o servidor web."""

    def safe_update(self, cor, acao: str, msg: str = ""):
        state.update(cor, acao, msg)
        if _hud_ref:
            _hud_ref.safe_update(cor, acao, msg)

    def push_historico(self, cmd: str):
        state.push_cmd(cmd)
        if _hud_ref:
            _hud_ref.push_historico(cmd)

    def animacao_shutdown(self):
        state.update(True, "OFFLINE", "Desativando...")
        if _hud_ref:
            _hud_ref.animacao_shutdown()

web_hud = WebHUDAdapter()

# ═══════════════════════════════════════════════════════════
#  MÉTRICAS DO SISTEMA
# ═══════════════════════════════════════════════════════════
_net_bytes_prev = sum(psutil.net_io_counters()[:2])

def _coletar_metricas() -> dict:
    global _net_bytes_prev
    cpu = psutil.cpu_percent(interval=None)
    ram = psutil.virtual_memory().percent
    try:
        bat = psutil.sensors_battery()
        bat_pct    = round(bat.percent, 1) if bat else None
        bat_plug   = bat.power_plugged if bat else True
    except Exception:
        bat_pct, bat_plug = None, True

    try:
        nb    = psutil.net_io_counters()
        total = nb.bytes_sent + nb.bytes_recv
        kbps  = max(0, total - _net_bytes_prev) / 1024
        _net_bytes_prev = total
    except Exception:
        kbps = 0

    procs = sorted(
        psutil.process_iter(["name", "cpu_percent"]),
        key=lambda p: p.info["cpu_percent"] or 0, reverse=True
    )[:5]
    top_procs = [
        {"name": p.info["name"], "cpu": round(p.info["cpu_percent"] or 0, 1)}
        for p in procs
    ]

    return {
        "cpu":      round(cpu, 1),
        "ram":      round(ram, 1),
        "bat":      bat_pct,
        "bat_plug": bat_plug,
        "net_kbps": round(kbps, 1),
        "procs":    top_procs,
        "hora":     datetime.datetime.now().strftime("%H:%M:%S"),
        "data":     datetime.datetime.now().strftime("%d/%m/%Y"),
    }

# ═══════════════════════════════════════════════════════════
#  FASTAPI APP
# ═══════════════════════════════════════════════════════════
from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(application: FastAPI):
    global _loop
    _loop = asyncio.get_event_loop()
    asyncio.create_task(_metrics_loop())
    log.info("JARVIS Web HUD iniciado.")
    yield

app = FastAPI(title="JARVIS Web HUD", lifespan=lifespan)

# ── HTML da interface ─────────────────────────────────────
HTML = r"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, user-scalable=no">
<meta name="mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<title>J.A.R.V.I.S · HUD</title>
<style>
  @import url('https://fonts.googleapis.com/css2?family=Share+Tech+Mono&family=Orbitron:wght@400;700;900&display=swap');

  :root {
    --bg:      #050d1a;
    --bg2:     #091525;
    --bg3:     #0c1e35;
    --accent:  #00BFFF;
    --green:   #00FF88;
    --orange:  #FF9900;
    --red:     #FF3333;
    --purple:  #BF5FFF;
    --discord: #7289DA;
    --dim:     #071e30;
    --med:     #0a3a55;
    --text1:   #00BFFF;
    --text2:   #2a6a80;
    --text3:   #1a4a60;
    --glow: 0 0 8px rgba(0,191,255,0.5), 0 0 20px rgba(0,191,255,0.2);
    --glow-red: 0 0 8px rgba(255,51,51,0.5), 0 0 20px rgba(255,51,51,0.2);
  }

  * { margin:0; padding:0; box-sizing:border-box; -webkit-tap-highlight-color:transparent; }

  body {
    background: var(--bg);
    color: var(--text1);
    font-family: 'Share Tech Mono', monospace;
    min-height: 100vh;
    overflow-x: hidden;
    display: flex;
    flex-direction: column;
    align-items: center;
  }

  /* scanline overlay */
  body::before {
    content:'';
    position:fixed; inset:0;
    background: repeating-linear-gradient(
      0deg,
      transparent,
      transparent 2px,
      rgba(0,191,255,0.015) 2px,
      rgba(0,191,255,0.015) 4px
    );
    pointer-events: none;
    z-index: 9999;
  }

  /* ── Header ────────────────────────────────────── */
  header {
    width: 100%;
    padding: 14px 20px 10px;
    display: flex;
    justify-content: space-between;
    align-items: center;
    border-bottom: 1px solid var(--dim);
    position: sticky; top:0; z-index:100;
    background: var(--bg);
  }
  .logo {
    font-family: 'Orbitron', sans-serif;
    font-weight: 900;
    font-size: 18px;
    letter-spacing: 4px;
    color: var(--accent);
    text-shadow: var(--glow);
  }
  .logo span {
    font-size: 9px;
    font-family: 'Share Tech Mono', monospace;
    display: block;
    letter-spacing: 6px;
    color: var(--text2);
    margin-top: -2px;
  }
  .conn-dot {
    width: 8px; height: 8px;
    border-radius: 50%;
    background: var(--red);
    box-shadow: 0 0 6px var(--red);
    transition: all .4s;
    animation: pulse-dot 2s infinite;
  }
  .conn-dot.online {
    background: var(--green);
    box-shadow: 0 0 6px var(--green);
  }
  @keyframes pulse-dot {
    0%,100% { opacity:1; }
    50% { opacity:.4; }
  }

  /* ── Core orb ──────────────────────────────────── */
  .core-wrap {
    display: flex;
    flex-direction: column;
    align-items: center;
    padding: 24px 0 16px;
  }
  .orb-container {
    position: relative;
    width: 160px; height: 160px;
  }
  .orb-svg {
    width: 100%; height: 100%;
    overflow: visible;
  }
  /* status badge abaixo */
  .status-badge {
    margin-top: 14px;
    text-align: center;
  }
  .status-label {
    font-family: 'Orbitron', sans-serif;
    font-size: 13px;
    font-weight: 700;
    letter-spacing: 3px;
    color: var(--accent);
    text-shadow: var(--glow);
    transition: color .3s;
  }
  .status-msg {
    font-size: 10px;
    color: var(--text2);
    letter-spacing: 1px;
    margin-top: 4px;
    max-width: 280px;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  /* ── Waveform ──────────────────────────────────── */
  .wave-wrap {
    display: flex;
    gap: 4px;
    align-items: center;
    height: 36px;
    padding: 0 20px;
    margin: 0 0 8px;
  }
  .wave-bar {
    width: 5px;
    border-radius: 3px;
    background: var(--med);
    height: 4px;
    transition: height .1s, background .3s;
  }
  .wave-bar.active { background: var(--accent); }

  /* ── Seção ─────────────────────────────────────── */
  .section {
    width: 100%;
    max-width: 480px;
    padding: 0 16px 16px;
  }
  .section-title {
    font-size: 9px;
    letter-spacing: 4px;
    color: var(--text3);
    margin-bottom: 10px;
    padding-bottom: 6px;
    border-bottom: 1px solid var(--dim);
  }

  /* ── Métricas ──────────────────────────────────── */
  .metrics-grid {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 10px;
  }
  .metric-card {
    background: var(--bg2);
    border: 1px solid var(--dim);
    border-radius: 8px;
    padding: 12px;
    position: relative;
    overflow: hidden;
  }
  .metric-card::after {
    content:'';
    position:absolute; top:0; left:0; right:0;
    height:1px;
    background: linear-gradient(90deg, transparent, var(--accent), transparent);
    opacity: .3;
  }
  .metric-label {
    font-size: 8px;
    letter-spacing: 3px;
    color: var(--text3);
    margin-bottom: 6px;
  }
  .metric-value {
    font-family: 'Orbitron', sans-serif;
    font-size: 22px;
    font-weight: 700;
    color: var(--accent);
    line-height: 1;
  }
  .metric-value.warn { color: var(--orange); }
  .metric-value.danger { color: var(--red); }
  .metric-bar-bg {
    width: 100%; height: 3px;
    background: var(--dim);
    border-radius: 2px;
    margin-top: 8px;
    overflow: hidden;
  }
  .metric-bar-fill {
    height: 100%;
    background: var(--accent);
    border-radius: 2px;
    transition: width .8s ease, background .5s;
  }

  /* Bateria especial */
  .bat-card {
    grid-column: 1 / -1;
    display: flex;
    align-items: center;
    gap: 14px;
    background: var(--bg2);
    border: 1px solid var(--dim);
    border-radius: 8px;
    padding: 12px 16px;
  }
  .bat-icon {
    font-size: 26px;
    line-height: 1;
    filter: drop-shadow(0 0 4px var(--accent));
  }
  .bat-info { flex:1; }
  .bat-label { font-size: 8px; letter-spacing:3px; color: var(--text3); }
  .bat-val { font-family:'Orbitron',sans-serif; font-size:20px; font-weight:700; color:var(--accent); }
  .bat-bar-bg {
    height:4px; background:var(--dim); border-radius:2px;
    margin-top:6px; overflow:hidden;
  }
  .bat-bar-fill { height:100%; background:var(--accent); border-radius:2px; transition: width .8s, background .5s; }

  /* Net */
  .net-row {
    background: var(--bg2);
    border: 1px solid var(--dim);
    border-radius: 8px;
    padding: 10px 14px;
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-top: 10px;
  }
  .net-label { font-size:8px; letter-spacing:3px; color: var(--text3); }
  .net-val { font-family:'Orbitron',sans-serif; font-size:14px; color: var(--accent); }

  /* ── Mini CPU chart ─────────────────────────────── */
  .cpu-chart {
    width: 100%;
    height: 40px;
    margin-top: 10px;
    background: var(--bg2);
    border: 1px solid var(--dim);
    border-radius: 8px;
    overflow: hidden;
    position: relative;
  }
  #cpuCanvas { width:100%; height:100%; }

  /* ── Top Procs ─────────────────────────────────── */
  .proc-list { display: flex; flex-direction: column; gap: 4px; }
  .proc-row {
    display: flex; align-items: center; gap: 10px;
    background: var(--bg2);
    border: 1px solid var(--dim);
    border-radius: 6px;
    padding: 7px 12px;
  }
  .proc-name { flex:1; font-size:10px; color: var(--text1); overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
  .proc-cpu  { font-size:9px; color: var(--accent); font-family:'Orbitron',sans-serif; min-width:36px; text-align:right; }
  .proc-bar-bg { width:50px; height:3px; background:var(--dim); border-radius:2px; overflow:hidden; }
  .proc-bar-fill { height:100%; background:var(--accent); border-radius:2px; }

  /* ── Comandos de voz ───────────────────────────── */
  .cmd-input-wrap {
    background: var(--bg2);
    border: 1px solid var(--med);
    border-radius: 10px;
    display: flex;
    align-items: center;
    gap: 0;
    overflow: hidden;
  }
  .cmd-prompt {
    padding: 0 10px;
    font-size: 14px;
    color: var(--accent);
    line-height: 1;
  }
  .cmd-input {
    flex: 1;
    background: transparent;
    border: none;
    outline: none;
    color: var(--accent);
    font-family: 'Share Tech Mono', monospace;
    font-size: 13px;
    padding: 14px 0;
    caret-color: var(--accent);
  }
  .cmd-input::placeholder { color: var(--text3); }
  .cmd-send {
    width: 48px; height: 48px;
    background: var(--med);
    border: none;
    cursor: pointer;
    color: var(--accent);
    font-size: 18px;
    display: flex; align-items:center; justify-content:center;
    transition: background .2s;
    touch-action: manipulation;
  }
  .cmd-send:active { background: var(--accent); color: var(--bg); }

  /* Atalhos rápidos */
  .quick-btns {
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: 8px;
    margin-top: 10px;
  }
  .qbtn {
    background: var(--bg2);
    border: 1px solid var(--dim);
    border-radius: 8px;
    padding: 10px 4px;
    color: var(--text1);
    font-family: 'Share Tech Mono', monospace;
    font-size: 9px;
    letter-spacing: 1px;
    cursor: pointer;
    text-align: center;
    transition: all .15s;
    touch-action: manipulation;
    -webkit-user-select: none;
  }
  .qbtn:active, .qbtn:hover {
    background: var(--med);
    border-color: var(--accent);
    color: var(--accent);
    box-shadow: var(--glow);
  }
  .qbtn .qbtn-icon { font-size: 16px; display:block; margin-bottom:4px; }

  /* ── Histórico ─────────────────────────────────── */
  .hist-list { display:flex; flex-direction:column; gap:4px; }
  .hist-item {
    background: var(--bg2);
    border: 1px solid var(--dim);
    border-radius: 6px;
    padding: 8px 12px;
    display: flex;
    align-items: center;
    gap: 10px;
    animation: slideIn .25s ease;
  }
  @keyframes slideIn {
    from { opacity:0; transform:translateY(-8px); }
    to   { opacity:1; transform:translateY(0); }
  }
  .hist-ts { font-size:8px; color: var(--text3); min-width:36px; }
  .hist-cmd { font-size:10px; color: var(--text2); flex:1; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
  .hist-replay {
    font-size:10px; color: var(--text3); cursor:pointer;
    padding:2px 6px;
    border:1px solid var(--dim); border-radius:4px;
    transition:all .15s;
  }
  .hist-replay:active { border-color: var(--accent); color: var(--accent); }

  /* ── Microfone PTT ──────────────────────────────── */
  .ptt-btn {
    width: 100%;
    padding: 18px;
    background: var(--bg2);
    border: 2px solid var(--med);
    border-radius: 12px;
    color: var(--text1);
    font-family: 'Share Tech Mono', monospace;
    font-size: 12px;
    letter-spacing: 3px;
    cursor: pointer;
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 10px;
    transition: all .2s;
    touch-action: manipulation;
    -webkit-user-select: none;
    position: relative;
    overflow: hidden;
  }
  .ptt-btn::before {
    content:'';
    position:absolute; inset:0;
    background: radial-gradient(circle at center, rgba(0,191,255,.1), transparent 70%);
    opacity:0;
    transition:opacity .2s;
  }
  .ptt-btn:active::before, .ptt-btn.listening::before { opacity:1; }
  .ptt-btn:active, .ptt-btn.listening {
    border-color: var(--accent);
    box-shadow: var(--glow), inset 0 0 20px rgba(0,191,255,.05);
    color: var(--accent);
  }
  .ptt-icon { font-size:20px; }
  .ptt-label { letter-spacing:2px; }

  /* ── Hora ───────────────────────────────────────── */
  .clock-row {
    display:flex; justify-content:space-between; align-items:center;
    padding: 10px 16px;
    border-top: 1px solid var(--dim);
    border-bottom: 1px solid var(--dim);
    margin-bottom: 8px;
    background: var(--bg2);
  }
  .clock-time {
    font-family:'Orbitron',sans-serif;
    font-size:24px; font-weight:700;
    color: var(--accent);
    text-shadow: var(--glow);
  }
  .clock-date { font-size:9px; color: var(--text2); letter-spacing:2px; text-align:right; }

  /* ── Footer ─────────────────────────────────────── */
  footer {
    width:100%; margin-top:auto;
    padding:10px 16px;
    border-top:1px solid var(--dim);
    text-align:center;
    font-size:8px; letter-spacing:2px; color: var(--text3);
  }

  /* scrollbar */
  ::-webkit-scrollbar { width:3px; }
  ::-webkit-scrollbar-track { background: var(--bg); }
  ::-webkit-scrollbar-thumb { background: var(--med); border-radius:2px; }
</style>
</head>
<body>

<header>
  <div class="logo">
    J.A.R.V.I.S
    <span>M A R K · X I I I · W E B</span>
  </div>
  <div class="conn-dot" id="connDot"></div>
</header>

<!-- Relógio -->
<div class="clock-row">
  <div class="clock-time" id="clockTime">--:--:--</div>
  <div class="clock-date" id="clockDate">--/--/----</div>
</div>

<!-- Orbe central -->
<div class="core-wrap">
  <div class="orb-container">
    <svg class="orb-svg" viewBox="0 0 160 160" xmlns="http://www.w3.org/2000/svg">
      <!-- Halos -->
      <circle cx="80" cy="80" r="74" fill="none" stroke="#00BFFF" stroke-width=".5" opacity=".06"/>
      <circle cx="80" cy="80" r="66" fill="none" stroke="#00BFFF" stroke-width=".5" opacity=".10"/>
      <circle cx="80" cy="80" r="58" fill="none" stroke="#00BFFF" stroke-width=".5" opacity=".15"/>
      <!-- Anel externo rotativo -->
      <circle cx="80" cy="80" r="68" fill="none" stroke="#0a3a55" stroke-width="1"/>
      <path id="arcA" fill="none" stroke="#00BFFF" stroke-width="2.5" stroke-linecap="round"/>
      <path id="arcB" fill="none" stroke="#0a3a55" stroke-width="2.5" stroke-linecap="round"/>
      <!-- Anel médio -->
      <path id="arcC" fill="none" stroke="#0a3a55" stroke-width="1.5" stroke-linecap="round"/>
      <!-- Anel lento oposto -->
      <path id="arcD" fill="none" stroke="#1a4a60" stroke-width="1" stroke-linecap="round"/>
      <path id="arcE" fill="none" stroke="#1a4a60" stroke-width="1" stroke-linecap="round"/>
      <!-- Marcadores cardinais -->
      <line x1="80" y1="6"  x2="80" y2="13"  stroke="#0a3a55" stroke-width="1.5"/>
      <line x1="80" y1="147" x2="80" y2="154" stroke="#0a3a55" stroke-width="1.5"/>
      <line x1="6"  y1="80" x2="13" y2="80"  stroke="#0a3a55" stroke-width="1.5"/>
      <line x1="147" y1="80" x2="154" y2="80" stroke="#0a3a55" stroke-width="1.5"/>
      <!-- Anel pulsante -->
      <circle id="ringPulse" cx="80" cy="80" r="36" fill="none" stroke="#00BFFF" stroke-width="1.2"/>
      <!-- Núcleo -->
      <circle id="coreCircle" cx="80" cy="80" r="24" fill="#091525" stroke="#00BFFF" stroke-width="2"/>
      <!-- Texto AI -->
      <text x="80" y="85" text-anchor="middle"
            font-family="Orbitron,sans-serif" font-size="12" font-weight="700"
            fill="#00BFFF" id="coreText">AI</text>
    </svg>
  </div>

  <!-- Waveform -->
  <div class="wave-wrap" id="waveWrap">
    <div class="wave-bar" id="wb0"></div>
    <div class="wave-bar" id="wb1"></div>
    <div class="wave-bar" id="wb2"></div>
    <div class="wave-bar" id="wb3"></div>
    <div class="wave-bar" id="wb4"></div>
    <div class="wave-bar" id="wb5"></div>
    <div class="wave-bar" id="wb6"></div>
    <div class="wave-bar" id="wb7"></div>
    <div class="wave-bar" id="wb8"></div>
  </div>

  <div class="status-badge">
    <div class="status-label" id="statusLabel">STANDBY</div>
    <div class="status-msg" id="statusMsg">Aguardando comando...</div>
  </div>
</div>

<!-- Comando -->
<div class="section">
  <div class="section-title">▸ ENTRADA DE COMANDO</div>
  <div class="cmd-input-wrap">
    <span class="cmd-prompt">›</span>
    <input class="cmd-input" id="cmdInput" type="text"
           placeholder="Digite um comando..." autocomplete="off" spellcheck="false">
    <button class="cmd-send" id="cmdSend" onclick="enviarComando()">▶</button>
  </div>
  <div class="quick-btns">
    <button class="qbtn" onclick="cmd('briefing')">
      <span class="qbtn-icon">📋</span>BRIEFING
    </button>
    <button class="qbtn" onclick="cmd('que horas são')">
      <span class="qbtn-icon">🕐</span>HORAS
    </button>
    <button class="qbtn" onclick="cmd('clima aracaju')">
      <span class="qbtn-icon">🌦</span>CLIMA
    </button>
    <button class="qbtn" onclick="cmd('status sistema')">
      <span class="qbtn-icon">💻</span>SISTEMA
    </button>
    <button class="qbtn" onclick="cmd('minha agenda')">
      <span class="qbtn-icon">📅</span>AGENDA
    </button>
    <button class="qbtn" onclick="cmd('screenshot')">
      <span class="qbtn-icon">📸</span>PRINT
    </button>
    <button class="qbtn" onclick="cmd('minhas tarefas')">
      <span class="qbtn-icon">✅</span>TAREFAS
    </button>
    <button class="qbtn" onclick="cmd('pausar')">
      <span class="qbtn-icon">⏸</span>PAUSAR
    </button>
    <button class="qbtn" onclick="cmd('me ajuda com o que estou fazendo')">
      <span class="qbtn-icon">🤖</span>ANALISAR
    </button>
  </div>
</div>

<!-- Métricas -->
<div class="section">
  <div class="section-title">▸ MÉTRICAS DO SISTEMA</div>
  <div class="metrics-grid">
    <div class="metric-card">
      <div class="metric-label">CPU</div>
      <div class="metric-value" id="cpuVal">--</div><span style="font-size:10px;color:var(--text2)">%</span>
      <div class="metric-bar-bg"><div class="metric-bar-fill" id="cpuBar" style="width:0%"></div></div>
    </div>
    <div class="metric-card">
      <div class="metric-label">MEMÓRIA</div>
      <div class="metric-value" id="ramVal">--</div><span style="font-size:10px;color:var(--text2)">%</span>
      <div class="metric-bar-bg"><div class="metric-bar-fill" id="ramBar" style="width:0%;background:var(--green)"></div></div>
    </div>
    <div class="bat-card">
      <div class="bat-icon" id="batIcon">🔋</div>
      <div class="bat-info">
        <div class="bat-label">BATERIA</div>
        <div class="bat-val" id="batVal">--<span style="font-size:12px">%</span></div>
        <div class="bat-bar-bg"><div class="bat-bar-fill" id="batBar" style="width:0%"></div></div>
      </div>
      <div id="batStatus" style="font-size:9px;color:var(--text3);letter-spacing:1px">--</div>
    </div>
  </div>
  <div class="net-row">
    <div>
      <div class="net-label">REDE · KB/S</div>
      <div class="net-val" id="netVal">--</div>
    </div>
    <div style="font-size:9px;color:var(--text3)">⬆⬇ IN/OUT</div>
  </div>
  <div class="cpu-chart" title="CPU History">
    <canvas id="cpuCanvas"></canvas>
  </div>
</div>

<!-- Top processos -->
<div class="section">
  <div class="section-title">▸ TOP PROCESSOS</div>
  <div class="proc-list" id="procList">
    <div style="font-size:9px;color:var(--text3);padding:8px">Aguardando dados...</div>
  </div>
</div>

<!-- Histórico -->
<div class="section">
  <div class="section-title">▸ HISTÓRICO DE COMANDOS</div>
  <div class="hist-list" id="histList">
    <div style="font-size:9px;color:var(--text3);padding:8px">Nenhum comando ainda.</div>
  </div>
</div>

<footer>
  J.A.R.V.I.S MARK XIII · WEB HUD · <span id="footerIP"></span>
</footer>

<script>
// ═══════════════════════════════════════════════
//  WebSocket
// ═══════════════════════════════════════════════
const WS_URL = `ws://${location.host}/ws`;
let ws, reconTimer;
const cpuHistory = new Array(60).fill(0);
let waveActive = false, wavePhase = 0;
let ang = 0, ang2 = 90;

const COR_MAP = {
  'accent': '#00BFFF',
  'True': '#FF3333', 'true': '#FF3333',
  'ativo': '#00FF88',
  'ia': '#BF5FFF',
  'foco': '#FF9900',
  'alerta': '#FF3333',
  'discord': '#7289DA',
  'False': '#00BFFF', 'false': '#00BFFF',
};

function resolverCor(c) {
  return COR_MAP[c] || c || '#00BFFF';
}

function conectar() {
  ws = new WebSocket(WS_URL);
  ws.onopen = () => {
    document.getElementById('connDot').classList.add('online');
  };
  ws.onclose = () => {
    document.getElementById('connDot').classList.remove('online');
    clearTimeout(reconTimer);
    reconTimer = setTimeout(conectar, 3000);
  };
  ws.onmessage = (e) => {
    const d = JSON.parse(e.data);
    if (d.type === 'state')   handleState(d);
    if (d.type === 'history') handleHistory(d);
    if (d.type === 'metrics') handleMetrics(d);
    if (d.type === 'init')    handleInit(d);
  };
}

function handleState(d) {
  const cor = resolverCor(d.cor);
  setOrbColor(cor);
  const lbl = document.getElementById('statusLabel');
  const msg = document.getElementById('statusMsg');
  lbl.textContent = d.status;
  lbl.style.color = cor;
  lbl.style.textShadow = `0 0 8px ${cor}66, 0 0 20px ${cor}33`;
  if (d.msg) msg.textContent = d.msg;
  waveActive = ['ativo','ia','discord','true','True','alerta','foco'].includes(d.cor);
}

function handleHistory(d) {
  addHistItem(d.cmd, d.ts);
}

function handleMetrics(d) {
  updateMetrics(d);
}

function handleInit(d) {
  if (d.history) {
    document.getElementById('histList').innerHTML = '';
    [...d.history].reverse().forEach(h => addHistItem(h.cmd, h.ts));
  }
  if (d.state) handleState(d.state);
}

// ═══════════════════════════════════════════════
//  Enviar comando
// ═══════════════════════════════════════════════
function enviarComando() {
  const inp = document.getElementById('cmdInput');
  const txt = inp.value.trim();
  if (!txt) return;
  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify({type: 'cmd', text: txt}));
    inp.value = '';
  } else {
    alert('Sem conexão com JARVIS');
  }
}

function cmd(txt) {
  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify({type: 'cmd', text: txt}));
  }
}

document.getElementById('cmdInput').addEventListener('keydown', e => {
  if (e.key === 'Enter') enviarComando();
});

// ═══════════════════════════════════════════════
//  Histórico
// ═══════════════════════════════════════════════
function addHistItem(cmdTxt, ts) {
  const list = document.getElementById('histList');
  // Remove placeholder
  const ph = list.querySelector('div[style]');
  if (ph) ph.remove();
  const el = document.createElement('div');
  el.className = 'hist-item';
  el.innerHTML = `
    <span class="hist-ts">${ts}</span>
    <span class="hist-cmd">${cmdTxt}</span>
    <span class="hist-replay" onclick="cmd('${cmdTxt.replace(/'/g,"\\'")}')">↩</span>
  `;
  list.insertBefore(el, list.firstChild);
  // Mantém max 20
  while (list.children.length > 20) list.removeChild(list.lastChild);
}

// ═══════════════════════════════════════════════
//  Métricas
// ═══════════════════════════════════════════════
function updateMetrics(d) {
  // CPU
  const cv = document.getElementById('cpuVal');
  const cb = document.getElementById('cpuBar');
  cv.textContent = d.cpu;
  cv.className = 'metric-value' + (d.cpu > 85 ? ' danger' : d.cpu > 60 ? ' warn' : '');
  cb.style.width = d.cpu + '%';
  cb.style.background = d.cpu > 85 ? 'var(--red)' : d.cpu > 60 ? 'var(--orange)' : 'var(--accent)';

  // RAM
  const rv = document.getElementById('ramVal');
  const rb = document.getElementById('ramBar');
  rv.textContent = d.ram;
  rv.className = 'metric-value' + (d.ram > 90 ? ' danger' : d.ram > 70 ? ' warn' : '');
  rb.style.width = d.ram + '%';
  rb.style.background = d.ram > 90 ? 'var(--red)' : d.ram > 70 ? 'var(--orange)' : 'var(--green)';

  // Bateria
  if (d.bat !== null && d.bat !== undefined) {
    document.getElementById('batVal').innerHTML = d.bat + '<span style="font-size:12px">%</span>';
    document.getElementById('batBar').style.width = d.bat + '%';
    document.getElementById('batBar').style.background =
      d.bat < 15 ? 'var(--red)' : d.bat < 30 ? 'var(--orange)' : 'var(--accent)';
    document.getElementById('batIcon').textContent = d.bat < 15 ? '🪫' : d.bat < 50 ? '🔋' : '🔋';
    document.getElementById('batStatus').textContent = d.bat_plug ? '⚡ CARREGANDO' : '🔌 NA BATERIA';
  } else {
    document.getElementById('batVal').textContent = 'N/A';
    document.getElementById('batStatus').textContent = 'SEM SENSOR';
  }

  // Rede
  document.getElementById('netVal').textContent = d.net_kbps.toFixed(1) + ' KB/s';

  // Clock
  document.getElementById('clockTime').textContent = d.hora;
  document.getElementById('clockDate').textContent = d.data;

  // CPU history
  cpuHistory.push(d.cpu);
  cpuHistory.shift();
  drawCpuChart();

  // Processos
  renderProcs(d.procs || []);
}

// ═══════════════════════════════════════════════
//  CPU Chart
// ═══════════════════════════════════════════════
function drawCpuChart() {
  const canvas = document.getElementById('cpuCanvas');
  const container = canvas.parentElement;
  canvas.width  = container.clientWidth;
  canvas.height = container.clientHeight;
  const ctx = canvas.getContext('2d');
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  const W = canvas.width, H = canvas.height;
  const step = W / (cpuHistory.length - 1);

  // Grid lines
  ctx.strokeStyle = 'rgba(0,191,255,0.07)';
  ctx.lineWidth = 1;
  for (let i = 0; i <= 4; i++) {
    const y = (H / 4) * i;
    ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(W, y); ctx.stroke();
  }

  // Gradient fill
  const grad = ctx.createLinearGradient(0, 0, 0, H);
  grad.addColorStop(0, 'rgba(0,191,255,0.3)');
  grad.addColorStop(1, 'rgba(0,191,255,0)');
  ctx.beginPath();
  cpuHistory.forEach((v, i) => {
    const x = i * step;
    const y = H - (v / 100) * H;
    i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
  });
  ctx.lineTo(W, H); ctx.lineTo(0, H);
  ctx.closePath();
  ctx.fillStyle = grad;
  ctx.fill();

  // Line
  ctx.beginPath();
  ctx.strokeStyle = '#00BFFF';
  ctx.lineWidth = 1.5;
  ctx.shadowColor = '#00BFFF';
  ctx.shadowBlur = 4;
  cpuHistory.forEach((v, i) => {
    const x = i * step;
    const y = H - (v / 100) * H;
    i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
  });
  ctx.stroke();
}

// ═══════════════════════════════════════════════
//  Processos
// ═══════════════════════════════════════════════
function renderProcs(procs) {
  const list = document.getElementById('procList');
  if (!procs.length) return;
  list.innerHTML = '';
  const maxCpu = Math.max(...procs.map(p => p.cpu), 1);
  procs.forEach(p => {
    const row = document.createElement('div');
    row.className = 'proc-row';
    const pct = Math.min((p.cpu / maxCpu) * 100, 100);
    const cor = p.cpu > 50 ? 'var(--red)' : p.cpu > 20 ? 'var(--orange)' : 'var(--accent)';
    row.innerHTML = `
      <span class="proc-name">${p.name}</span>
      <div class="proc-bar-bg"><div class="proc-bar-fill" style="width:${pct}%;background:${cor}"></div></div>
      <span class="proc-cpu" style="color:${cor}">${p.cpu}%</span>
    `;
    list.appendChild(row);
  });
}

// ═══════════════════════════════════════════════
//  Orb animation (SVG)
// ═══════════════════════════════════════════════
let orbColor = '#00BFFF';

function setOrbColor(c) {
  orbColor = c;
  document.getElementById('arcA').setAttribute('stroke', c);
  document.getElementById('ringPulse').setAttribute('stroke', c);
  document.getElementById('coreText').setAttribute('fill', c);
  document.getElementById('coreCircle').setAttribute('stroke', c);
}

function arcPath(cx, cy, r, startDeg, extentDeg) {
  const s = (startDeg * Math.PI) / 180;
  const e = ((startDeg + extentDeg) * Math.PI) / 180;
  const x1 = cx + r * Math.cos(s);
  const y1 = cy + r * Math.sin(s);
  const x2 = cx + r * Math.cos(e);
  const y2 = cy + r * Math.sin(e);
  const large = extentDeg > 180 ? 1 : 0;
  return `M ${x1} ${y1} A ${r} ${r} 0 ${large} 1 ${x2} ${y2}`;
}

let pulseR = 24, pulseDir = 1;

function animateOrb() {
  ang  = (ang  + 1.8) % 360;
  ang2 = (ang2 + 0.7) % 360;

  document.getElementById('arcA').setAttribute('d', arcPath(80,80,50,ang,70));
  document.getElementById('arcB').setAttribute('d', arcPath(80,80,50,ang+180,70));
  document.getElementById('arcC').setAttribute('d', arcPath(80,80,38,ang+90,50));
  document.getElementById('arcD').setAttribute('d', arcPath(80,80,68,-ang2,20));
  document.getElementById('arcE').setAttribute('d', arcPath(80,80,68,-ang2+180,20));

  // Pulso
  pulseR += pulseDir * 0.15;
  if (pulseR > 28) pulseDir = -1;
  if (pulseR < 20) pulseDir = 1;
  const pr = pulseR.toFixed(1);
  document.getElementById('ringPulse').setAttribute('r', pr);

  requestAnimationFrame(animateOrb);
}

// ═══════════════════════════════════════════════
//  Waveform
// ═══════════════════════════════════════════════
const waveBars = Array.from({length:9}, (_,i) => document.getElementById('wb'+i));
const waveAlts = new Array(9).fill(4);

function animateWave() {
  wavePhase += 0.18;
  waveBars.forEach((b, i) => {
    const target = waveActive ? 4 + 14 * Math.abs(Math.sin(wavePhase + i * 0.85)) : 4;
    waveAlts[i] += (target - waveAlts[i]) * 0.22;
    const h = Math.max(4, waveAlts[i]);
    b.style.height = h + 'px';
    b.style.background = waveActive ? orbColor : 'var(--med)';
    b.style.boxShadow = waveActive ? `0 0 4px ${orbColor}66` : 'none';
  });
  setTimeout(animateWave, 40);
}

// ═══════════════════════════════════════════════
//  Init
// ═══════════════════════════════════════════════
document.getElementById('footerIP').textContent = location.hostname + ':' + location.port;

conectar();
requestAnimationFrame(animateOrb);
animateWave();
drawCpuChart();
</script>
</body>
</html>"""

@app.get("/", response_class=HTMLResponse)
async def get_root():
    return HTML

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    state.clientes.append(websocket)
    log.info(f"Cliente WebSocket conectado: {websocket.client}")

    # Envia estado inicial
    init_payload = {
        "type": "init",
        "state": {
            "cor": str(state.cor),
            "status": state.status,
            "msg": state.msg,
        },
        "history": list(state.historico),
    }
    await websocket.send_text(json.dumps(init_payload))

    try:
        while True:
            data = await websocket.receive_text()
            payload = json.loads(data)

            if payload.get("type") == "cmd":
                texto = payload.get("text", "").strip()
                if texto:
                    log.info(f"Web CMD: {texto}")
                    state.push_cmd(texto)
                    state.update("ativo", "WEB CMD", texto[:40])
                    # Executa em thread separada para não travar o WS
                    def _exec(t=texto):
                        if _CORE_OK and _cmd_ref:
                            _cmd_ref(t, web_hud)
                        elif _CORE_OK:
                            from jarvis_core import processar_comando as _pc
                            _pc(t, web_hud)
                        else:
                            # Modo standalone: só ecoa
                            state.update(False, "STANDBY", f"Cmd recebido: {t[:40]}")
                    threading.Thread(target=_exec, daemon=True).start()

    except WebSocketDisconnect:
        log.info("Cliente WebSocket desconectado.")
    except Exception as e:
        log.error(f"WebSocket erro: {e}")
    finally:
        if websocket in state.clientes:
            state.clientes.remove(websocket)


# ═══════════════════════════════════════════════════════════
#  BROADCAST DE MÉTRICAS (task em background)
# ═══════════════════════════════════════════════════════════
async def _metrics_loop():
    while True:
        await asyncio.sleep(2)
        if not state.clientes:
            continue
        m = _coletar_metricas()
        msg = json.dumps({"type": "metrics", **m})
        mortos = []
        for ws in state.clientes:
            try:
                await ws.send_text(msg)
            except Exception:
                mortos.append(ws)
        for ws in mortos:
            if ws in state.clientes:
                state.clientes.remove(ws)



# ═══════════════════════════════════════════════════════════
#  API PÚBLICA — para integrar com jarvis_core.py
# ═══════════════════════════════════════════════════════════
def iniciar_servidor_web(hud=None, falar_fn=None, cmd_fn=None,
                          host: str = "0.0.0.0", port: int = 8765):
    """
    Inicia o servidor web em thread separada.
    Chame no rodar_jarvis() do jarvis_core.py:

        from jarvis_web_hud import iniciar_servidor_web
        iniciar_servidor_web(hud, falar_sync, processar_comando)
    """
    global _hud_ref, _falar_ref, _cmd_ref, _loop

    _hud_ref   = hud
    _falar_ref = falar_fn
    _cmd_ref   = cmd_fn

    def _run():
        global _loop
        loop = asyncio.new_event_loop()
        _loop = loop
        asyncio.set_event_loop(loop)
        config = uvicorn.Config(
            app, host=host, port=port,
            log_level="warning",
            loop="asyncio",
        )
        server = uvicorn.Server(config)
        loop.run_until_complete(server.serve())

    t = threading.Thread(target=_run, daemon=True, name="JarvisWebHUD")
    t.start()

    # Descobre o IP local
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
    except Exception:
        ip = "localhost"

    log.info(f"Web HUD disponível em: http://{ip}:{port}")
    if falar_fn:
        falar_fn(f"Web HUD ativo. Acesse no celular: {ip} porta {port}.")
    print(f"\n🌐 JARVIS Web HUD → http://{ip}:{port}\n")
    return t


# ═══════════════════════════════════════════════════════════
#  MODO STANDALONE
# ═══════════════════════════════════════════════════════════
if __name__ == "__main__":
    import socket as _sock

    try:
        s = _sock.socket(_sock.AF_INET, _sock.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
    except Exception:
        ip = "localhost"

    print("""
╔══════════════════════════════════════════════════════════╗
║         J.A.R.V.I.S  —  WEB HUD SERVER                  ║
╚══════════════════════════════════════════════════════════╝
""")
    print(f"  🌐 Acesse no PC:     http://localhost:8765")
    print(f"  📱 Acesse no celular: http://{ip}:8765")
    print(f"\n  (PC e celular devem estar na mesma rede Wi-Fi)\n")

    # Modo demo: atualiza estado periodicamente para demonstração
    def _demo():
        import time, random
        time.sleep(3)
        demos = [
            ("ativo", "ESCUTANDO", "Aguardando wake word..."),
            ("ia", "CONSULTANDO", "Gemini 2.0 Flash..."),
            (False, "STANDBY", "Aguardando comando..."),
            ("foco", "BRIEFING", "Gerando briefing matinal..."),
            ("ativo", "TTS", "Reproduzindo resposta..."),
            (False, "STANDBY", "Pronto."),
        ]
        i = 0
        while True:
            if state.clientes:
                cor, acao, msg = demos[i % len(demos)]
                state.update(cor, acao, msg)
                if i % 3 == 0:
                    state.push_cmd(random.choice([
                        "briefing", "que horas são", "clima aracaju",
                        "minha agenda", "status sistema", "minhas tarefas"
                    ]))
            i += 1
            time.sleep(4)

    threading.Thread(target=_demo, daemon=True).start()

    loop = asyncio.new_event_loop()
    _loop = loop
    asyncio.set_event_loop(loop)
    config = uvicorn.Config(app, host="0.0.0.0", port=8765,
                             log_level="info", loop="asyncio")
    server = uvicorn.Server(config)
    loop.run_until_complete(server.serve())
