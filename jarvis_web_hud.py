"""
╔══════════════════════════════════════════════════════════╗
║         J.A.R.V.I.S  —  WEB HUD  MARK XIV               ║
║  Redesign completo · Glass-morphism · Mobile-first       ║
╚══════════════════════════════════════════════════════════╝

Como usar:
    python jarvis_web_hud.py

Acesse no celular (mesma rede Wi-Fi):
    http://<IP-DO-PC>:8765

Integração com jarvis_core.py:
    from jarvis_web_hud import iniciar_servidor_web
    iniciar_servidor_web(hud, falar_sync, processar_comando)
"""

import os, sys, json, time, datetime, asyncio, threading, socket
import psutil
from pathlib import Path
from collections import deque

try:
    from fastapi import FastAPI, WebSocket, WebSocketDisconnect
    from fastapi.responses import HTMLResponse
    import uvicorn
except ImportError:
    print("ERRO: pip install fastapi uvicorn websockets")
    sys.exit(1)

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
#  ESTADO GLOBAL
# ═══════════════════════════════════════════════════════════
class JarvisState:
    def __init__(self):
        self.status    = "STANDBY"
        self.msg       = "Aguardando comando..."
        self.cor       = "accent"
        self.historico = deque(maxlen=30)
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
            }), _loop
        )

    def push_cmd(self, cmd: str):
        ts = datetime.datetime.now().strftime("%H:%M")
        with self._lock:
            self.historico.appendleft({"cmd": cmd[:60], "ts": ts})
        asyncio.run_coroutine_threadsafe(
            self._broadcast("history", {"cmd": cmd[:60], "ts": ts}), _loop
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


class WebHUDAdapter:
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
#  MÉTRICAS
# ═══════════════════════════════════════════════════════════
_net_bytes_prev = sum(psutil.net_io_counters()[:2])

def _coletar_metricas() -> dict:
    global _net_bytes_prev
    cpu = psutil.cpu_percent(interval=None)
    ram = psutil.virtual_memory().percent
    try:
        bat      = psutil.sensors_battery()
        bat_pct  = round(bat.percent, 1) if bat else None
        bat_plug = bat.power_plugged if bat else True
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
#  DADOS PESSOAIS — Estudos, Tarefas, Eventos, Hábitos
# ═══════════════════════════════════════════════════════════
import json as _json_mod

_DATA_FILE = Path.home() / ".jarvis_hud_data.json"

_DEFAULT_DATA = {
    "estudos": [
        {"id": 1, "materia": "Python", "meta_min": 60, "feito_min": 0, "cor": "#00b4ff"},
        {"id": 2, "materia": "Inglês", "meta_min": 30, "feito_min": 0, "cor": "#a855f7"},
        {"id": 3, "materia": "Matemática", "meta_min": 45, "feito_min": 0, "cor": "#00e5a0"},
    ],
    "tarefas": [
        {"id": 1, "texto": "Revisar anotações de ontem", "feita": False, "prioridade": "alta"},
        {"id": 2, "texto": "Responder e-mails", "feita": False, "prioridade": "media"},
        {"id": 3, "texto": "Exercícios físicos", "feita": False, "prioridade": "normal"},
    ],
    "eventos": [
        {"id": 1, "titulo": "Reunião de projeto", "hora": "14:00", "cor": "#ff9a1f"},
        {"id": 2, "titulo": "Academia", "hora": "18:30", "cor": "#00e5a0"},
    ],
    "habitos": [
        {"id": 1, "nome": "Água 2L", "icone": "💧", "streak": 0, "feito_hoje": False},
        {"id": 2, "nome": "Leitura", "icone": "📚", "streak": 0, "feito_hoje": False},
        {"id": 3, "nome": "Exercício", "icone": "🏃", "streak": 0, "feito_hoje": False},
        {"id": 4, "nome": "Meditação", "icone": "🧘", "streak": 0, "feito_hoje": False},
    ],
    "ultima_atualizacao": "",
}

def _carregar_dados() -> dict:
    try:
        if _DATA_FILE.exists():
            d = _json_mod.loads(_DATA_FILE.read_text(encoding="utf-8"))
            # reset hábitos/tarefas se for novo dia
            hoje = datetime.date.today().isoformat()
            if d.get("ultima_atualizacao", "") != hoje:
                for h in d.get("habitos", []):
                    h["feito_hoje"] = False
                for t in d.get("tarefas", []):
                    t["feita"] = False
                for e in d.get("estudos", []):
                    e["feito_min"] = 0
                d["ultima_atualizacao"] = hoje
                _DATA_FILE.write_text(_json_mod.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
            return d
    except Exception:
        pass
    data = _DEFAULT_DATA.copy()
    data["ultima_atualizacao"] = datetime.date.today().isoformat()
    _DATA_FILE.write_text(_json_mod.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return data

def _salvar_dados(data: dict):
    try:
        data["ultima_atualizacao"] = datetime.date.today().isoformat()
        _DATA_FILE.write_text(_json_mod.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as e:
        log.error(f"Erro ao salvar dados: {e}")


# ═══════════════════════════════════════════════════════════
#  HTML — REDESIGN MARK XV
# ═══════════════════════════════════════════════════════════
HTML = r"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover,user-scalable=no">
<meta name="mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<meta name="theme-color" content="#030810">
<title>J.A.R.V.I.S · XV</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Syne+Mono&family=Space+Grotesk:wght@300;400;500;600&display=swap" rel="stylesheet">
<style>
*,*::before,*::after{margin:0;padding:0;box-sizing:border-box;-webkit-tap-highlight-color:transparent}

:root{
  --bg:        #030810;
  --bg1:       #060f1e;
  --bg2:       #091526;
  --bg3:       #0d1e35;
  --glass:     rgba(9,21,38,0.7);
  --glass2:    rgba(13,30,53,0.5);
  --border:    rgba(0,180,255,0.12);
  --border2:   rgba(0,180,255,0.22);
  --a:         #00b4ff;
  --a2:        #00d4ff;
  --green:     #00e5a0;
  --orange:    #ff9a1f;
  --red:       #ff3d3d;
  --purple:    #a855f7;
  --t1:        rgba(255,255,255,0.92);
  --t2:        rgba(255,255,255,0.55);
  --t3:        rgba(255,255,255,0.3);
  --t4:        rgba(255,255,255,0.12);
  --radius:    14px;
  --radius-sm: 9px;
  --shadow:    0 8px 32px rgba(0,0,0,0.4);
  --glow:      0 0 20px rgba(0,180,255,0.15);
}

html{background:var(--bg);scroll-behavior:smooth}
body{
  font-family:'Space Grotesk',sans-serif;
  font-weight:400;
  color:var(--t1);
  min-height:100dvh;
  overflow-x:hidden;
  background:
    radial-gradient(ellipse 80% 50% at 20% 0%, rgba(0,100,200,0.08) 0%, transparent 60%),
    radial-gradient(ellipse 60% 40% at 80% 100%, rgba(0,60,150,0.06) 0%, transparent 60%),
    var(--bg);
}

/* scanline */
body::after{
  content:'';
  position:fixed;inset:0;
  background:repeating-linear-gradient(0deg,transparent,transparent 3px,rgba(0,180,255,0.012) 3px,rgba(0,180,255,0.012) 4px);
  pointer-events:none;z-index:9999
}

/* ── Typography ─────────────────────────────────── */
.mono{font-family:'Syne Mono',monospace}

/* ── Layout ─────────────────────────────────────── */
.page{
  max-width:520px;
  margin:0 auto;
  padding:0 0 env(safe-area-inset-bottom,16px);
}

/* ── Header ─────────────────────────────────────── */
.header{
  position:sticky;top:0;z-index:100;
  display:flex;align-items:center;justify-content:space-between;
  padding:14px 20px 12px;
  background:rgba(3,8,16,0.85);
  backdrop-filter:blur(20px);
  -webkit-backdrop-filter:blur(20px);
  border-bottom:1px solid var(--border);
}
.logo-group{display:flex;flex-direction:column;gap:1px}
.logo{
  font-family:'Syne Mono',monospace;
  font-size:16px;letter-spacing:5px;
  color:var(--a);
  text-shadow:0 0 20px rgba(0,180,255,0.4)
}
.logo-sub{font-size:9px;letter-spacing:3px;color:var(--t3);font-weight:300}
.header-right{display:flex;align-items:center;gap:10px}
.conn-pill{
  display:flex;align-items:center;gap:6px;
  padding:5px 10px;
  background:var(--glass2);
  border:1px solid var(--border);
  border-radius:20px;
  font-size:10px;color:var(--t2);letter-spacing:1px
}
.conn-dot{width:6px;height:6px;border-radius:50%;background:var(--red);transition:background .4s}
.conn-dot.on{background:var(--green);box-shadow:0 0 6px var(--green)}

/* ── Clock strip ─────────────────────────────────── */
.clock-strip{
  padding:12px 20px;
  display:flex;align-items:baseline;justify-content:space-between;
  border-bottom:1px solid var(--border)
}
.clock-time{
  font-family:'Syne Mono',monospace;
  font-size:30px;font-weight:400;
  color:var(--a);
  text-shadow:0 0 30px rgba(0,180,255,0.3)
}
.clock-date{font-size:11px;color:var(--t3);letter-spacing:2px}

/* ── Status core ─────────────────────────────────── */
.core-section{
  display:flex;flex-direction:column;align-items:center;
  padding:28px 20px 20px;
  position:relative
}

.orb-wrap{position:relative;width:180px;height:180px}
.orb-svg{width:100%;height:100%;overflow:visible}

.status-block{margin-top:20px;text-align:center}
.status-label{
  font-family:'Syne Mono',monospace;
  font-size:14px;letter-spacing:4px;
  color:var(--a);
  text-shadow:0 0 16px rgba(0,180,255,0.4);
  transition:color .3s
}
.status-msg{
  font-size:11px;color:var(--t3);
  letter-spacing:1.5px;margin-top:5px;
  max-width:260px;overflow:hidden;
  text-overflow:ellipsis;white-space:nowrap
}

/* waveform */
.wave{
  display:flex;gap:3px;align-items:center;
  height:28px;margin:16px 0 0
}
.wb{
  width:4px;border-radius:2px;
  background:var(--border2);height:4px;
  transition:height .1s,background .3s
}

/* ── Glass card ──────────────────────────────────── */
.card{
  background:var(--glass);
  backdrop-filter:blur(16px);
  -webkit-backdrop-filter:blur(16px);
  border:1px solid var(--border);
  border-radius:var(--radius);
  overflow:hidden
}
.card-header{
  display:flex;align-items:center;justify-content:space-between;
  padding:12px 16px;
  border-bottom:1px solid var(--border);
  font-size:9px;letter-spacing:3px;color:var(--t3)
}
.card-header-icon{font-size:14px;opacity:.6}

/* ── Section spacing ─────────────────────────────── */
.section{padding:0 16px;margin-bottom:14px}
.section:first-of-type{padding-top:16px}

/* ── Command input ───────────────────────────────── */
.cmd-card{background:var(--glass);border:1px solid var(--border);border-radius:var(--radius)}
.cmd-row{
  display:flex;align-items:center;
  padding:4px 4px 4px 14px;
  gap:0
}
.cmd-prompt{
  font-family:'Syne Mono',monospace;
  font-size:18px;color:var(--a);
  line-height:1;margin-right:8px;
  opacity:.7;flex-shrink:0
}
.cmd-input{
  flex:1;background:transparent;border:none;outline:none;
  color:var(--t1);
  font-family:'Space Grotesk',sans-serif;
  font-size:14px;
  padding:12px 0;
  caret-color:var(--a)
}
.cmd-input::placeholder{color:var(--t3)}
.cmd-send{
  width:46px;height:46px;
  background:rgba(0,180,255,0.1);
  border:1px solid var(--border2);
  border-radius:10px;
  cursor:pointer;
  color:var(--a);font-size:18px;
  display:flex;align-items:center;justify-content:center;
  transition:background .15s,transform .1s;flex-shrink:0
}
.cmd-send:active{background:var(--a);color:var(--bg);transform:scale(.95)}

/* quick buttons */
.quick-grid{
  display:grid;
  grid-template-columns:repeat(3,1fr);
  gap:8px;
  padding:10px 16px 4px
}
.qbtn{
  background:var(--glass2);
  border:1px solid var(--border);
  border-radius:var(--radius-sm);
  padding:12px 6px 10px;
  display:flex;flex-direction:column;align-items:center;gap:5px;
  cursor:pointer;
  color:var(--t2);
  font-family:'Space Grotesk',sans-serif;
  font-size:9px;letter-spacing:1.5px;
  transition:all .15s;
  -webkit-user-select:none;user-select:none
}
.qbtn-icon{font-size:18px;line-height:1}
.qbtn:active{
  background:rgba(0,180,255,0.12);
  border-color:var(--border2);
  color:var(--a)
}

/* ── Métricas ────────────────────────────────────── */
.metrics-grid{
  display:grid;
  grid-template-columns:1fr 1fr;
  gap:8px;padding:14px 16px
}
.metric{
  background:var(--glass2);
  border:1px solid var(--border);
  border-radius:var(--radius-sm);
  padding:13px 14px
}
.metric-lbl{font-size:8px;letter-spacing:3px;color:var(--t3);margin-bottom:6px}
.metric-val{
  font-family:'Syne Mono',monospace;
  font-size:26px;color:var(--a);line-height:1
}
.metric-val.warn{color:var(--orange)}
.metric-val.danger{color:var(--red)}
.metric-unit{font-size:11px;color:var(--t3);margin-left:2px}
.mbar-bg{height:3px;background:rgba(255,255,255,0.07);border-radius:2px;margin-top:10px;overflow:hidden}
.mbar-fill{height:100%;border-radius:2px;transition:width .8s,background .5s}

/* bat wide */
.bat-row{
  display:flex;align-items:center;gap:14px;
  background:var(--glass2);border:1px solid var(--border);
  border-radius:var(--radius-sm);padding:13px 14px;
  grid-column:1/-1
}
.bat-ico{font-size:24px;line-height:1}
.bat-info{flex:1}
.bat-lbl{font-size:8px;letter-spacing:3px;color:var(--t3);margin-bottom:4px}
.bat-val{font-family:'Syne Mono',monospace;font-size:22px;color:var(--a)}
.bat-status{font-size:9px;color:var(--t3);letter-spacing:1px;margin-top:2px}

/* net */
.net-bar{
  display:flex;align-items:center;justify-content:space-between;
  padding:11px 16px;
  border-top:1px solid var(--border)
}
.net-lbl{font-size:8px;letter-spacing:3px;color:var(--t3)}
.net-val{font-family:'Syne Mono',monospace;font-size:14px;color:var(--a)}

/* CPU chart */
.chart-wrap{
  padding:0 16px 14px;
}
.chart-inner{
  background:var(--glass2);
  border:1px solid var(--border);
  border-radius:var(--radius-sm);
  height:52px;overflow:hidden;position:relative
}
#cpuCanvas{width:100%;height:100%;display:block}

/* ── Processos ───────────────────────────────────── */
.proc-list{padding:4px 0}
.proc-row{
  display:flex;align-items:center;gap:10px;
  padding:10px 16px;
  border-bottom:1px solid var(--border)
}
.proc-row:last-child{border-bottom:none}
.proc-name{flex:1;font-size:12px;color:var(--t2);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.proc-bar-bg{width:44px;height:3px;background:rgba(255,255,255,0.07);border-radius:2px;overflow:hidden}
.proc-bar-fill{height:100%;border-radius:2px}
.proc-pct{font-family:'Syne Mono',monospace;font-size:11px;color:var(--a);min-width:34px;text-align:right}

/* ── Histórico ───────────────────────────────────── */
.hist-list{padding:4px 0}
.hist-item{
  display:flex;align-items:center;gap:10px;
  padding:10px 16px;
  border-bottom:1px solid var(--border);
  animation:slideDown .2s ease
}
.hist-item:last-child{border-bottom:none}
@keyframes slideDown{from{opacity:0;transform:translateY(-6px)}to{opacity:1;transform:translateY(0)}}
.hist-ts{font-family:'Syne Mono',monospace;font-size:9px;color:var(--t3);min-width:36px}
.hist-cmd{font-size:11px;color:var(--t2);flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.hist-replay{
  font-size:14px;color:var(--t3);cursor:pointer;
  padding:4px 8px;border:1px solid var(--border);
  border-radius:6px;transition:all .15s;flex-shrink:0
}
.hist-replay:active{border-color:var(--a);color:var(--a)}

/* ── Footer ──────────────────────────────────────── */
.footer{
  text-align:center;padding:14px 16px 20px;
  font-size:9px;letter-spacing:2px;color:var(--t4)
}

/* ── Scrollbar ───────────────────────────────────── */
::-webkit-scrollbar{width:2px}
::-webkit-scrollbar-track{background:transparent}
::-webkit-scrollbar-thumb{background:var(--border2);border-radius:2px}

/* ── Tabs ────────────────────────────────────────── */
.tabs{
  display:flex;gap:0;
  padding:0 16px;
  overflow-x:auto;
  scrollbar-width:none;
  margin-bottom:2px
}
.tabs::-webkit-scrollbar{display:none}
.tab{
  flex-shrink:0;
  padding:8px 14px;
  font-size:9px;letter-spacing:2px;
  color:var(--t3);
  border-bottom:2px solid transparent;
  cursor:pointer;
  transition:all .2s;
  white-space:nowrap;
  -webkit-user-select:none;user-select:none
}
.tab.active{color:var(--a);border-color:var(--a)}
.tab-panel{display:none}
.tab-panel.active{display:block}

/* ── Estudos ─────────────────────────────────────── */
.estudo-list{padding:8px 0}
.estudo-row{
  padding:12px 16px;
  border-bottom:1px solid var(--border)
}
.estudo-row:last-child{border-bottom:none}
.estudo-top{display:flex;align-items:center;justify-content:space-between;margin-bottom:8px}
.estudo-nome{font-size:13px;color:var(--t1)}
.estudo-meta{font-family:'Syne Mono',monospace;font-size:11px;color:var(--t3)}
.estudo-prog-bg{height:4px;background:rgba(255,255,255,0.07);border-radius:2px;overflow:hidden;margin-bottom:6px}
.estudo-prog-fill{height:100%;border-radius:2px;transition:width .6s}
.estudo-actions{display:flex;gap:6px}
.estudo-btn{
  flex:1;padding:7px 0;
  background:var(--glass2);border:1px solid var(--border);
  border-radius:7px;font-size:10px;letter-spacing:1px;
  color:var(--t2);cursor:pointer;
  transition:all .15s;-webkit-user-select:none;user-select:none
}
.estudo-btn:active{background:rgba(0,180,255,0.1);color:var(--a);border-color:var(--border2)}
.estudo-btn.add{color:var(--green)}
.estudo-total{
  display:flex;align-items:center;justify-content:space-between;
  padding:10px 16px 12px;
  border-top:1px solid var(--border)
}
.estudo-total-lbl{font-size:9px;letter-spacing:2px;color:var(--t3)}
.estudo-total-val{font-family:'Syne Mono',monospace;font-size:13px;color:var(--green)}

/* ── Tarefas ─────────────────────────────────────── */
.task-list{padding:4px 0}
.task-row{
  display:flex;align-items:center;gap:12px;
  padding:11px 16px;
  border-bottom:1px solid var(--border);
  cursor:pointer;
  transition:background .15s;
  -webkit-user-select:none;user-select:none
}
.task-row:last-child{border-bottom:none}
.task-row:active{background:rgba(0,180,255,0.04)}
.task-check{
  width:18px;height:18px;flex-shrink:0;
  border-radius:5px;border:1.5px solid var(--border2);
  display:flex;align-items:center;justify-content:center;
  font-size:10px;transition:all .2s
}
.task-check.done{background:var(--green);border-color:var(--green);color:#000}
.task-texto{flex:1;font-size:12px;color:var(--t2);transition:all .2s}
.task-texto.done{text-decoration:line-through;color:var(--t4)}
.task-pri{
  font-size:7px;letter-spacing:1.5px;padding:3px 7px;
  border-radius:20px;flex-shrink:0
}
.task-pri.alta{background:rgba(255,61,61,0.12);color:var(--red);border:1px solid rgba(255,61,61,0.2)}
.task-pri.media{background:rgba(255,154,31,0.12);color:var(--orange);border:1px solid rgba(255,154,31,0.2)}
.task-pri.normal{background:rgba(0,180,255,0.08);color:var(--t3);border:1px solid var(--border)}
.task-add-row{
  display:flex;align-items:center;gap:0;
  padding:6px 10px 6px 16px;
  border-top:1px solid var(--border)
}
.task-add-inp{
  flex:1;background:transparent;border:none;outline:none;
  color:var(--t1);font-family:'Space Grotesk',sans-serif;font-size:12px;
  padding:8px 0;caret-color:var(--a)
}
.task-add-inp::placeholder{color:var(--t4)}
.task-add-btn{
  width:36px;height:36px;background:rgba(0,180,255,0.08);
  border:1px solid var(--border2);border-radius:8px;
  color:var(--a);font-size:16px;cursor:pointer;
  display:flex;align-items:center;justify-content:center;flex-shrink:0
}
.task-add-btn:active{background:var(--a);color:var(--bg)}
.task-stats{
  display:flex;align-items:center;justify-content:space-between;
  padding:9px 16px;border-top:1px solid var(--border)
}
.task-stats-txt{font-size:9px;letter-spacing:2px;color:var(--t3)}
.task-stats-val{font-family:'Syne Mono',monospace;font-size:12px;color:var(--a)}

/* ── Eventos ─────────────────────────────────────── */
.event-list{padding:6px 0}
.event-row{
  display:flex;align-items:center;gap:12px;
  padding:12px 16px;
  border-bottom:1px solid var(--border)
}
.event-row:last-child{border-bottom:none}
.event-dot{width:8px;height:8px;border-radius:50%;flex-shrink:0}
.event-info{flex:1}
.event-titulo{font-size:13px;color:var(--t1);margin-bottom:2px}
.event-hora{font-family:'Syne Mono',monospace;font-size:10px;color:var(--t3)}
.event-del{
  font-size:13px;color:var(--t4);cursor:pointer;padding:4px 8px;
  border:1px solid var(--border);border-radius:6px;
  transition:all .15s;flex-shrink:0
}
.event-del:active{border-color:var(--red);color:var(--red)}
.event-add-row{
  display:flex;gap:8px;padding:10px 16px;
  border-top:1px solid var(--border)
}
.event-add-inp{
  flex:1;background:var(--glass2);border:1px solid var(--border);
  border-radius:8px;padding:8px 10px;
  color:var(--t1);font-family:'Space Grotesk',sans-serif;font-size:12px;
  outline:none;caret-color:var(--a)
}
.event-add-inp::placeholder{color:var(--t4)}
.event-add-time{width:72px}
.event-add-btn{
  width:36px;height:36px;background:rgba(0,180,255,0.08);
  border:1px solid var(--border2);border-radius:8px;
  color:var(--a);font-size:16px;cursor:pointer;
  display:flex;align-items:center;justify-content:center;flex-shrink:0
}
.event-add-btn:active{background:var(--a);color:var(--bg)}
.event-empty{padding:20px 16px;font-size:11px;color:var(--t4);text-align:center;letter-spacing:1.5px}

/* ── Hábitos ─────────────────────────────────────── */
.habitos-grid{
  display:grid;grid-template-columns:1fr 1fr;
  gap:8px;padding:12px 16px
}
.habito-card{
  background:var(--glass2);border:1px solid var(--border);
  border-radius:var(--radius-sm);
  padding:14px 12px;
  display:flex;flex-direction:column;align-items:center;gap:6px;
  cursor:pointer;transition:all .2s;
  -webkit-user-select:none;user-select:none;
  position:relative;overflow:hidden
}
.habito-card.done{
  border-color:rgba(0,229,160,0.3);
  background:rgba(0,229,160,0.06)
}
.habito-card:active{transform:scale(.97)}
.habito-ico{font-size:24px;line-height:1}
.habito-nome{font-size:10px;letter-spacing:1.5px;color:var(--t2);text-align:center}
.habito-streak{
  font-family:'Syne Mono',monospace;font-size:11px;
  color:var(--t3);
  display:flex;align-items:center;gap:3px
}
.habito-streak .fire{font-size:10px}
.habito-done-ico{
  position:absolute;top:8px;right:8px;
  font-size:10px;color:var(--green);
  opacity:0;transition:opacity .2s
}
.habito-card.done .habito-done-ico{opacity:1}
.habito-summary{
  display:flex;align-items:center;justify-content:space-between;
  padding:8px 16px 12px;border-top:1px solid var(--border)
}
.habito-summary-lbl{font-size:9px;letter-spacing:2px;color:var(--t3)}
.habito-summary-dots{display:flex;gap:5px}
.hdot{width:8px;height:8px;border-radius:50%;background:var(--border);transition:background .2s}
.hdot.on{background:var(--green);box-shadow:0 0 6px var(--green)}
</style>
</head>
<body>
<div class="page">

<!-- Header -->
<header class="header">
  <div class="logo-group">
    <div class="logo mono">J.A.R.V.I.S</div>
    <div class="logo-sub">MARK XV · WEB HUD</div>
  </div>
  <div class="header-right">
    <div class="conn-pill">
      <div class="conn-dot" id="dot"></div>
      <span id="connLabel">OFFLINE</span>
    </div>
  </div>
</header>

<!-- Clock -->
<div class="clock-strip">
  <div class="clock-time mono" id="clockTime">--:--:--</div>
  <div class="clock-date" id="clockDate">--/--/----</div>
</div>

<!-- Core orb + status -->
<div class="core-section">
  <div class="orb-wrap">
    <svg class="orb-svg" viewBox="0 0 180 180" xmlns="http://www.w3.org/2000/svg">
      <!-- halos -->
      <circle cx="90" cy="90" r="84" fill="none" stroke="rgba(0,180,255,0.05)" stroke-width="1"/>
      <circle cx="90" cy="90" r="74" fill="none" stroke="rgba(0,180,255,0.08)" stroke-width="1"/>
      <circle cx="90" cy="90" r="64" fill="none" stroke="rgba(0,180,255,0.11)" stroke-width="1"/>
      <!-- anel outer fixo -->
      <circle cx="90" cy="90" r="76" fill="none" stroke="rgba(0,180,255,0.1)" stroke-width="1.5"/>
      <!-- arcos animados -->
      <path id="arcA" fill="none" stroke="#00b4ff" stroke-width="2.5" stroke-linecap="round"/>
      <path id="arcB" fill="none" stroke="rgba(0,180,255,0.18)" stroke-width="2.5" stroke-linecap="round"/>
      <path id="arcC" fill="none" stroke="rgba(0,180,255,0.14)" stroke-width="1.5" stroke-linecap="round"/>
      <path id="arcD" fill="none" stroke="rgba(0,180,255,0.08)" stroke-width="1" stroke-linecap="round"/>
      <path id="arcE" fill="none" stroke="rgba(0,180,255,0.08)" stroke-width="1" stroke-linecap="round"/>
      <!-- cardinais -->
      <line x1="90" y1="7"   x2="90" y2="16"  stroke="rgba(0,180,255,0.18)" stroke-width="1.5" stroke-linecap="round"/>
      <line x1="90" y1="164" x2="90" y2="173" stroke="rgba(0,180,255,0.18)" stroke-width="1.5" stroke-linecap="round"/>
      <line x1="7"  y1="90" x2="16"  y2="90"  stroke="rgba(0,180,255,0.18)" stroke-width="1.5" stroke-linecap="round"/>
      <line x1="164" y1="90" x2="173" y2="90" stroke="rgba(0,180,255,0.18)" stroke-width="1.5" stroke-linecap="round"/>
      <!-- anel pulsante -->
      <circle id="ringP" cx="90" cy="90" r="40" fill="none" stroke="#00b4ff" stroke-width="1.2"/>
      <!-- núcleo -->
      <circle id="coreC" cx="90" cy="90" r="28" fill="#060f1e" stroke="#00b4ff" stroke-width="2"/>
      <!-- texto -->
      <text x="90" y="96" text-anchor="middle"
        font-family="'Syne Mono',monospace" font-size="13" font-weight="400"
        fill="#00b4ff" id="coreT" letter-spacing="2">AI</text>
    </svg>
  </div>

  <!-- waveform -->
  <div class="wave" id="wave">
    <div class="wb" id="wb0"></div><div class="wb" id="wb1"></div>
    <div class="wb" id="wb2"></div><div class="wb" id="wb3"></div>
    <div class="wb" id="wb4"></div><div class="wb" id="wb5"></div>
    <div class="wb" id="wb6"></div><div class="wb" id="wb7"></div>
    <div class="wb" id="wb8"></div>
  </div>

  <!-- status -->
  <div class="status-block">
    <div class="status-label mono" id="statusLabel">STANDBY</div>
    <div class="status-msg" id="statusMsg">Aguardando comando...</div>
  </div>
</div>

<!-- Comando -->
<div class="section">
  <div class="cmd-card">
    <div class="cmd-row">
      <span class="cmd-prompt">›</span>
      <input class="cmd-input" id="cmdIn" placeholder="Digite um comando..."
             autocomplete="off" spellcheck="false" inputmode="text">
      <button class="cmd-send" id="cmdBtn" onclick="sendCmd()">▶</button>
    </div>
  </div>
</div>

<!-- Quick buttons -->
<div class="quick-grid">
  <button class="qbtn" onclick="cmd('briefing')">
    <span class="qbtn-icon">📋</span>BRIEFING
  </button>
  <button class="qbtn" onclick="cmd('que horas são')">
    <span class="qbtn-icon">🕐</span>HORAS
  </button>
  <button class="qbtn" onclick="cmd('clima')">
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

<!-- Painel pessoal com tabs -->
<div class="section" style="margin-top:10px">
  <div class="card">
    <div class="card-header">
      <span id="painelTitle">PAINEL PESSOAL</span>
      <span class="card-header-icon">🎯</span>
    </div>
    <div class="tabs" id="mainTabs">
      <div class="tab active" onclick="switchTab('estudos')">📖 ESTUDOS</div>
      <div class="tab" onclick="switchTab('tarefas')">✅ TAREFAS</div>
      <div class="tab" onclick="switchTab('eventos')">📅 HOJE</div>
      <div class="tab" onclick="switchTab('habitos')">🔥 HÁBITOS</div>
    </div>

    <!-- ESTUDOS -->
    <div class="tab-panel active" id="panel-estudos">
      <div class="estudo-list" id="estudoList"></div>
      <div class="estudo-total">
        <span class="estudo-total-lbl">TOTAL HOJE</span>
        <span class="estudo-total-val" id="estudoTotal">0 min</span>
      </div>
    </div>

    <!-- TAREFAS -->
    <div class="tab-panel" id="panel-tarefas">
      <div class="task-list" id="taskList"></div>
      <div class="task-add-row">
        <input class="task-add-inp" id="taskInp" placeholder="Nova tarefa..." autocomplete="off">
        <button class="task-add-btn" onclick="addTarefa()">+</button>
      </div>
      <div class="task-stats">
        <span class="task-stats-txt">CONCLUÍDAS</span>
        <span class="task-stats-val" id="taskStats">0/0</span>
      </div>
    </div>

    <!-- EVENTOS -->
    <div class="tab-panel" id="panel-eventos">
      <div class="event-list" id="eventList"></div>
      <div class="event-add-row">
        <input class="event-add-inp" id="eventInp" placeholder="Evento..." autocomplete="off">
        <input class="event-add-inp event-add-time" id="eventHora" type="time">
        <button class="event-add-btn" onclick="addEvento()">+</button>
      </div>
    </div>

    <!-- HÁBITOS -->
    <div class="tab-panel" id="panel-habitos">
      <div class="habitos-grid" id="habitosGrid"></div>
      <div class="habito-summary">
        <span class="habito-summary-lbl">HOJE</span>
        <div class="habito-summary-dots" id="habitosDots"></div>
      </div>
    </div>

  </div>
</div>

<!-- Métricas -->
<div class="section" style="margin-top:8px">
  <div class="card">
    <div class="card-header">
      <span>MÉTRICAS DO SISTEMA</span>
      <span class="card-header-icon">⚡</span>
    </div>
    <div class="metrics-grid">
      <div class="metric">
        <div class="metric-lbl">CPU</div>
        <div><span class="metric-val" id="cpuVal">--</span><span class="metric-unit">%</span></div>
        <div class="mbar-bg"><div class="mbar-fill" id="cpuBar" style="width:0%;background:var(--a)"></div></div>
      </div>
      <div class="metric">
        <div class="metric-lbl">MEMÓRIA</div>
        <div><span class="metric-val" id="ramVal">--</span><span class="metric-unit">%</span></div>
        <div class="mbar-bg"><div class="mbar-fill" id="ramBar" style="width:0%;background:var(--green)"></div></div>
      </div>
      <div class="bat-row">
        <div class="bat-ico" id="batIco">🔋</div>
        <div class="bat-info">
          <div class="bat-lbl">BATERIA</div>
          <div class="bat-val mono" id="batVal">--<span style="font-size:12px">%</span></div>
          <div class="bat-status" id="batSt">--</div>
          <div class="mbar-bg" style="margin-top:7px"><div class="mbar-fill" id="batBar" style="width:0%;background:var(--a)"></div></div>
        </div>
      </div>
    </div>
    <div class="net-bar">
      <div>
        <div class="net-lbl">REDE</div>
        <div class="net-val mono" id="netVal">-- KB/s</div>
      </div>
      <div style="font-size:9px;color:var(--t3);letter-spacing:1px">⬆⬇ IN/OUT</div>
    </div>
  </div>
</div>

<!-- CPU Chart -->
<div class="chart-wrap">
  <div class="chart-inner">
    <canvas id="cpuCanvas"></canvas>
  </div>
</div>

<!-- Processos -->
<div class="section">
  <div class="card">
    <div class="card-header">
      <span>TOP PROCESSOS</span>
      <span class="card-header-icon">📊</span>
    </div>
    <div class="proc-list" id="procList">
      <div class="proc-row">
        <span class="proc-name" style="color:var(--t3)">Aguardando dados...</span>
      </div>
    </div>
  </div>
</div>

<!-- Histórico -->
<div class="section">
  <div class="card">
    <div class="card-header">
      <span>HISTÓRICO DE COMANDOS</span>
      <span class="card-header-icon">🕓</span>
    </div>
    <div class="hist-list" id="histList">
      <div class="hist-item">
        <span class="hist-ts">--:--</span>
        <span class="hist-cmd" style="color:var(--t3)">Nenhum comando ainda.</span>
      </div>
    </div>
  </div>
</div>

<div class="footer mono" id="footerTxt">JARVIS XV · <span id="footerIP"></span></div>

</div><!-- /page -->

<script>
const COR = {
  'accent':'#00b4ff','False':'#00b4ff','false':'#00b4ff',
  'True':'#ff3d3d','true':'#ff3d3d',
  'ativo':'#00e5a0','ia':'#a855f7','foco':'#ff9a1f',
  'alerta':'#ff3d3d','discord':'#7289da'
};
function rc(c){return COR[c]||c||'#00b4ff'}

let ws,reconTmr;
const cpuH=new Array(60).fill(0);
let waveOn=false,wavePhase=0,ang=0,ang2=90,pulseR=40,pulseDir=1;
let orbColor='#00b4ff';

// ── Dados pessoais (carregados via API) ─────────────
let _dados = null;

async function carregarDados(){
  try{
    const r = await fetch('/api/dados');
    _dados = await r.json();
    renderEstudos();
    renderTarefas();
    renderEventos();
    renderHabitos();
  }catch(e){ console.warn('Erro ao carregar dados',e); }
}

async function salvarDados(){
  if(!_dados)return;
  try{
    await fetch('/api/dados',{
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify(_dados)
    });
  }catch(e){ console.warn('Erro ao salvar dados',e); }
}

// ── Tabs ────────────────────────────────────────────
function switchTab(id){
  document.querySelectorAll('.tab').forEach((t,i)=>{
    const ids=['estudos','tarefas','eventos','habitos'];
    t.classList.toggle('active', ids[i]===id);
  });
  document.querySelectorAll('.tab-panel').forEach(p=>{
    p.classList.toggle('active', p.id==='panel-'+id);
  });
}

// ── ESTUDOS ─────────────────────────────────────────
function renderEstudos(){
  if(!_dados)return;
  const list = document.getElementById('estudoList');
  list.innerHTML='';
  let total=0;
  _dados.estudos.forEach(e=>{
    total+=e.feito_min;
    const pct=Math.min(100, Math.round((e.feito_min/e.meta_min)*100));
    const div=document.createElement('div');
    div.className='estudo-row';
    div.innerHTML=`
      <div class="estudo-top">
        <span class="estudo-nome">${e.materia}</span>
        <span class="estudo-meta mono">${e.feito_min}/${e.meta_min} min</span>
      </div>
      <div class="estudo-prog-bg">
        <div class="estudo-prog-fill" style="width:${pct}%;background:${e.cor}"></div>
      </div>
      <div class="estudo-actions">
        <button class="estudo-btn add" onclick="regEstudo(${e.id},15)">+15 min</button>
        <button class="estudo-btn add" onclick="regEstudo(${e.id},30)">+30 min</button>
        <button class="estudo-btn" onclick="regEstudo(${e.id},-15)" style="color:var(--t4)">-15</button>
      </div>`;
    list.appendChild(div);
  });
  document.getElementById('estudoTotal').textContent=total+' min';
}

function regEstudo(id, delta){
  if(!_dados)return;
  const e=_dados.estudos.find(x=>x.id===id);
  if(!e)return;
  e.feito_min=Math.max(0, e.feito_min+delta);
  renderEstudos();
  salvarDados();
}

// ── TAREFAS ─────────────────────────────────────────
function renderTarefas(){
  if(!_dados)return;
  const list=document.getElementById('taskList');
  list.innerHTML='';
  const ts=_dados.tarefas;
  ts.forEach(t=>{
    const div=document.createElement('div');
    div.className='task-row';
    div.onclick=()=>toggleTarefa(t.id);
    div.innerHTML=`
      <div class="task-check ${t.feita?'done':''}">${t.feita?'✓':''}</div>
      <span class="task-texto ${t.feita?'done':''}">${t.texto}</span>
      <span class="task-pri ${t.prioridade}">${t.prioridade.toUpperCase()}</span>`;
    list.appendChild(div);
  });
  const feitas=ts.filter(x=>x.feita).length;
  document.getElementById('taskStats').textContent=feitas+'/'+ts.length;
}

function toggleTarefa(id){
  if(!_dados)return;
  const t=_dados.tarefas.find(x=>x.id===id);
  if(t)t.feita=!t.feita;
  renderTarefas();
  salvarDados();
}

function addTarefa(){
  const inp=document.getElementById('taskInp');
  const txt=inp.value.trim();
  if(!txt||!_dados)return;
  const newId=Math.max(0,..._dados.tarefas.map(x=>x.id))+1;
  _dados.tarefas.push({id:newId,texto:txt,feita:false,prioridade:'normal'});
  inp.value='';
  renderTarefas();
  salvarDados();
}
document.addEventListener('DOMContentLoaded',()=>{
  const ti=document.getElementById('taskInp');
  if(ti)ti.addEventListener('keydown',e=>{if(e.key==='Enter')addTarefa()});
  const ei=document.getElementById('eventInp');
  if(ei)ei.addEventListener('keydown',e=>{if(e.key==='Enter')addEvento()});
});

// ── EVENTOS ─────────────────────────────────────────
const EVENT_CORES=['#ff9a1f','#00b4ff','#a855f7','#00e5a0','#ff3d3d'];
function renderEventos(){
  if(!_dados)return;
  const list=document.getElementById('eventList');
  const evs=_dados.eventos.sort((a,b)=>a.hora.localeCompare(b.hora));
  if(!evs.length){
    list.innerHTML='<div class="event-empty">Nenhum evento hoje</div>';
    return;
  }
  list.innerHTML='';
  evs.forEach(ev=>{
    const div=document.createElement('div');
    div.className='event-row';
    div.innerHTML=`
      <div class="event-dot" style="background:${ev.cor}"></div>
      <div class="event-info">
        <div class="event-titulo">${ev.titulo}</div>
        <div class="event-hora mono">${ev.hora}</div>
      </div>
      <span class="event-del" onclick="delEvento(${ev.id})">✕</span>`;
    list.appendChild(div);
  });
}

function addEvento(){
  const inp=document.getElementById('eventInp');
  const hora=document.getElementById('eventHora');
  const titulo=inp.value.trim();
  if(!titulo||!_dados)return;
  const newId=Math.max(0,..._dados.eventos.map(x=>x.id))+1;
  const cor=EVENT_CORES[newId % EVENT_CORES.length];
  _dados.eventos.push({id:newId,titulo,hora:hora.value||'--:--',cor});
  inp.value='';hora.value='';
  renderEventos();
  salvarDados();
}

function delEvento(id){
  if(!_dados)return;
  _dados.eventos=_dados.eventos.filter(x=>x.id!==id);
  renderEventos();
  salvarDados();
}

// ── HÁBITOS ─────────────────────────────────────────
function renderHabitos(){
  if(!_dados)return;
  const grid=document.getElementById('habitosGrid');
  const dots=document.getElementById('habitosDots');
  grid.innerHTML='';dots.innerHTML='';
  _dados.habitos.forEach(h=>{
    const card=document.createElement('div');
    card.className='habito-card'+(h.feito_hoje?' done':'');
    card.onclick=()=>toggleHabito(h.id);
    card.innerHTML=`
      <span class="habito-done-ico">✓</span>
      <div class="habito-ico">${h.icone}</div>
      <div class="habito-nome">${h.nome}</div>
      <div class="habito-streak"><span class="fire">🔥</span>${h.streak}</div>`;
    grid.appendChild(card);
    const dot=document.createElement('div');
    dot.className='hdot'+(h.feito_hoje?' on':'');
    dots.appendChild(dot);
  });
}

function toggleHabito(id){
  if(!_dados)return;
  const h=_dados.habitos.find(x=>x.id===id);
  if(!h)return;
  h.feito_hoje=!h.feito_hoje;
  h.streak=h.feito_hoje?h.streak+1:Math.max(0,h.streak-1);
  renderHabitos();
  salvarDados();
}

// ── WebSocket ────────────────────────────────────────
function connect(){
  ws=new WebSocket(`ws://${location.host}/ws`);
  ws.onopen=()=>{
    document.getElementById('dot').classList.add('on');
    document.getElementById('connLabel').textContent='ONLINE';
  };
  ws.onclose=()=>{
    document.getElementById('dot').classList.remove('on');
    document.getElementById('connLabel').textContent='OFFLINE';
    clearTimeout(reconTmr);
    reconTmr=setTimeout(connect,3000);
  };
  ws.onmessage=e=>{
    const d=JSON.parse(e.data);
    if(d.type==='state')   onState(d);
    if(d.type==='history') onHistory(d);
    if(d.type==='metrics') onMetrics(d);
    if(d.type==='init')    onInit(d);
  };
}

function setOrbColor(c){
  orbColor=c;
  document.getElementById('arcA').setAttribute('stroke',c);
  document.getElementById('ringP').setAttribute('stroke',c);
  document.getElementById('coreT').setAttribute('fill',c);
  document.getElementById('coreC').setAttribute('stroke',c);
}

function onState(d){
  const c=rc(d.cor);
  setOrbColor(c);
  const lbl=document.getElementById('statusLabel');
  const msg=document.getElementById('statusMsg');
  lbl.textContent=d.status;
  lbl.style.color=c;
  lbl.style.textShadow=`0 0 16px ${c}55`;
  if(d.msg)msg.textContent=d.msg;
  waveOn=['ativo','ia','discord','true','True','alerta','foco'].includes(d.cor);
}

function onHistory(d){addHist(d.cmd,d.ts)}

function onInit(d){
  if(d.history){
    document.getElementById('histList').innerHTML='';
    [...d.history].reverse().forEach(h=>addHist(h.cmd,h.ts));
  }
  if(d.state)onState(d.state);
}

function addHist(c,ts){
  const list=document.getElementById('histList');
  const ph=list.querySelector('.hist-item span[style*="t3"]');
  if(ph)list.innerHTML='';
  const el=document.createElement('div');
  el.className='hist-item';
  const safe=c.replace(/'/g,"\\'");
  el.innerHTML=`
    <span class="hist-ts mono">${ts}</span>
    <span class="hist-cmd">${c}</span>
    <span class="hist-replay" onclick="cmd('${safe}')">↩</span>`;
  list.insertBefore(el,list.firstChild);
  while(list.children.length>20)list.removeChild(list.lastChild);
}

function onMetrics(d){
  // CPU
  const cv=document.getElementById('cpuVal');
  const cb=document.getElementById('cpuBar');
  cv.textContent=d.cpu;
  cv.className='metric-val'+(d.cpu>85?' danger':d.cpu>60?' warn':'');
  cb.style.width=d.cpu+'%';
  cb.style.background=d.cpu>85?'var(--red)':d.cpu>60?'var(--orange)':'var(--a)';

  // RAM
  const rv=document.getElementById('ramVal');
  const rb=document.getElementById('ramBar');
  rv.textContent=d.ram;
  rv.className='metric-val'+(d.ram>90?' danger':d.ram>70?' warn':'');
  rb.style.width=d.ram+'%';
  rb.style.background=d.ram>90?'var(--red)':d.ram>70?'var(--orange)':'var(--green)';

  // Battery
  if(d.bat!=null){
    document.getElementById('batVal').innerHTML=d.bat+'<span style="font-size:12px">%</span>';
    const bb=document.getElementById('batBar');
    bb.style.width=d.bat+'%';
    bb.style.background=d.bat<15?'var(--red)':d.bat<30?'var(--orange)':'var(--a)';
    document.getElementById('batIco').textContent=d.bat<15?'🪫':'🔋';
    document.getElementById('batSt').textContent=d.bat_plug?'⚡ CARREGANDO':'🔌 NA BATERIA';
  }else{
    document.getElementById('batVal').textContent='N/A';
    document.getElementById('batSt').textContent='SEM SENSOR';
  }

  // Net
  document.getElementById('netVal').textContent=d.net_kbps.toFixed(1)+' KB/s';

  // Clock
  document.getElementById('clockTime').textContent=d.hora;
  document.getElementById('clockDate').textContent=d.data;

  // CPU history
  cpuH.push(d.cpu);cpuH.shift();
  drawChart();

  // Procs
  renderProcs(d.procs||[]);
}

function renderProcs(procs){
  const list=document.getElementById('procList');
  if(!procs.length)return;
  list.innerHTML='';
  const mx=Math.max(...procs.map(p=>p.cpu),1);
  procs.forEach(p=>{
    const pct=Math.min((p.cpu/mx)*100,100);
    const cor=p.cpu>50?'var(--red)':p.cpu>20?'var(--orange)':'var(--a)';
    const row=document.createElement('div');
    row.className='proc-row';
    row.innerHTML=`
      <span class="proc-name">${p.name}</span>
      <div class="proc-bar-bg"><div class="proc-bar-fill" style="width:${pct}%;background:${cor}"></div></div>
      <span class="proc-pct mono" style="color:${cor}">${p.cpu}%</span>`;
    list.appendChild(row);
  });
}

// CPU chart
function drawChart(){
  const canvas=document.getElementById('cpuCanvas');
  const c=canvas.parentElement;
  canvas.width=c.clientWidth;canvas.height=c.clientHeight;
  const ctx=canvas.getContext('2d');
  const W=canvas.width,H=canvas.height;
  ctx.clearRect(0,0,W,H);
  const step=W/(cpuH.length-1);

  // grid
  ctx.strokeStyle='rgba(0,180,255,0.06)';ctx.lineWidth=1;
  for(let i=0;i<=3;i++){const y=(H/3)*i;ctx.beginPath();ctx.moveTo(0,y);ctx.lineTo(W,y);ctx.stroke()}

  // fill
  const g=ctx.createLinearGradient(0,0,0,H);
  g.addColorStop(0,'rgba(0,180,255,0.22)');
  g.addColorStop(1,'rgba(0,180,255,0)');
  ctx.beginPath();
  cpuH.forEach((v,i)=>{const x=i*step,y=H-(v/100)*H;i===0?ctx.moveTo(x,y):ctx.lineTo(x,y)});
  ctx.lineTo(W,H);ctx.lineTo(0,H);ctx.closePath();
  ctx.fillStyle=g;ctx.fill();

  // line
  ctx.beginPath();ctx.strokeStyle='#00b4ff';ctx.lineWidth=1.5;
  cpuH.forEach((v,i)=>{const x=i*step,y=H-(v/100)*H;i===0?ctx.moveTo(x,y):ctx.lineTo(x,y)});
  ctx.stroke();
}

// Orb animation
function arcPath(cx,cy,r,s,ext){
  const a1=(s*Math.PI)/180,a2=((s+ext)*Math.PI)/180;
  const x1=cx+r*Math.cos(a1),y1=cy+r*Math.sin(a1);
  const x2=cx+r*Math.cos(a2),y2=cy+r*Math.sin(a2);
  return `M${x1} ${y1} A${r} ${r} 0 ${ext>180?1:0} 1 ${x2} ${y2}`;
}
function animOrb(){
  ang=(ang+1.8)%360;ang2=(ang2+0.7)%360;
  document.getElementById('arcA').setAttribute('d',arcPath(90,90,58,ang,72));
  document.getElementById('arcB').setAttribute('d',arcPath(90,90,58,ang+180,72));
  document.getElementById('arcC').setAttribute('d',arcPath(90,90,44,ang+90,52));
  document.getElementById('arcD').setAttribute('d',arcPath(90,90,76,-ang2,22));
  document.getElementById('arcE').setAttribute('d',arcPath(90,90,76,-ang2+180,22));
  pulseR+=pulseDir*0.14;
  if(pulseR>46)pulseDir=-1;
  if(pulseR<34)pulseDir=1;
  document.getElementById('ringP').setAttribute('r',pulseR.toFixed(1));
  requestAnimationFrame(animOrb);
}

// Waveform
const wbs=Array.from({length:9},(_,i)=>document.getElementById('wb'+i));
const wAlts=new Array(9).fill(4);
function animWave(){
  wavePhase+=0.18;
  wbs.forEach((b,i)=>{
    const t=waveOn?4+13*Math.abs(Math.sin(wavePhase+i*.85)):4;
    wAlts[i]+=(t-wAlts[i])*.22;
    const h=Math.max(4,wAlts[i]);
    b.style.height=h+'px';
    b.style.background=waveOn?orbColor:'rgba(0,180,255,0.15)';
  });
  setTimeout(animWave,40);
}

// Commands
function sendCmd(){
  const inp=document.getElementById('cmdIn');
  const t=inp.value.trim();
  if(!t)return;
  if(ws&&ws.readyState===WebSocket.OPEN){
    ws.send(JSON.stringify({type:'cmd',text:t}));
    inp.value='';
  }else alert('Sem conexão com JARVIS');
}
function cmd(t){if(ws&&ws.readyState===WebSocket.OPEN)ws.send(JSON.stringify({type:'cmd',text:t}))}

document.getElementById('cmdIn').addEventListener('keydown',e=>{if(e.key==='Enter')sendCmd()});

document.getElementById('footerIP').textContent=location.hostname+':'+location.port;

connect();
carregarDados();
requestAnimationFrame(animOrb);
animWave();
drawChart();
</script>
</body>
</html>"""


# ═══════════════════════════════════════════════════════════
#  FASTAPI
# ═══════════════════════════════════════════════════════════
from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(application: FastAPI):
    global _loop
    _loop = asyncio.get_event_loop()
    asyncio.create_task(_metrics_loop())
    log.info("JARVIS Web HUD Mark XIV iniciado.")
    yield

app = FastAPI(title="JARVIS Web HUD XIV", lifespan=lifespan)

@app.get("/", response_class=HTMLResponse)
async def get_root():
    return HTML

@app.websocket("/ws")
async def ws_endpoint(websocket: WebSocket):
    await websocket.accept()
    state.clientes.append(websocket)
    log.info(f"Cliente conectado: {websocket.client}")

    init_payload = {
        "type": "init",
        "state": {"cor": str(state.cor), "status": state.status, "msg": state.msg},
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
                    def _exec(t=texto):
                        if _CORE_OK and _cmd_ref:
                            _cmd_ref(t, web_hud)
                        elif _CORE_OK:
                            from jarvis_core import processar_comando as _pc
                            _pc(t, web_hud)
                        else:
                            state.update(False, "STANDBY", f"Cmd: {t[:40]}")
                    threading.Thread(target=_exec, daemon=True).start()
    except WebSocketDisconnect:
        log.info("Cliente desconectado.")
    except Exception as e:
        log.error(f"WS erro: {e}")
    finally:
        if websocket in state.clientes:
            state.clientes.remove(websocket)

from fastapi import Request
from fastapi.responses import JSONResponse

@app.get("/api/dados")
async def get_dados():
    return JSONResponse(_carregar_dados())

@app.post("/api/dados")
async def post_dados(request: Request):
    try:
        data = await request.json()
        _salvar_dados(data)
        return JSONResponse({"ok": True})
    except Exception as e:
        return JSONResponse({"ok": False, "erro": str(e)}, status_code=400)


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
#  API PÚBLICA
# ═══════════════════════════════════════════════════════════
def iniciar_servidor_web(hud=None, falar_fn=None, cmd_fn=None,
                          host: str = "0.0.0.0", port: int = 8765):
    global _hud_ref, _falar_ref, _cmd_ref, _loop

    _hud_ref   = hud
    _falar_ref = falar_fn
    _cmd_ref   = cmd_fn

    def _run():
        global _loop
        loop = asyncio.new_event_loop()
        _loop = loop
        asyncio.set_event_loop(loop)
        config = uvicorn.Config(app, host=host, port=port,
                                log_level="warning", loop="asyncio")
        server = uvicorn.Server(config)
        loop.run_until_complete(server.serve())

    t = threading.Thread(target=_run, daemon=True, name="JarvisWebHUD")
    t.start()

    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
    except Exception:
        ip = "localhost"

    log.info(f"Web HUD Mark XIV: http://{ip}:{port}")
    if falar_fn:
        falar_fn(f"Web HUD ativo. Acesse: {ip} porta {port}.")
    print(f"\n🌐 JARVIS Web HUD Mark XIV → http://{ip}:{port}\n")
    return t


# ═══════════════════════════════════════════════════════════
#  STANDALONE
# ═══════════════════════════════════════════════════════════
if __name__ == "__main__":
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
    except Exception:
        ip = "localhost"

    print("""
╔══════════════════════════════════════════════════════════╗
║         J.A.R.V.I.S  —  WEB HUD MARK XIV                ║
╚══════════════════════════════════════════════════════════╝""")
    print(f"  🌐 PC:      http://localhost:8765")
    print(f"  📱 Celular: http://{ip}:8765\n")

    def _demo():
        import random
        time.sleep(3)
        demos = [
            ("ativo","ESCUTANDO","Aguardando wake word..."),
            ("ia","CONSULTANDO","Groq llama-3.3-70b..."),
            (False,"STANDBY","Aguardando comando..."),
            ("foco","BRIEFING","Gerando briefing matinal..."),
            ("ativo","TTS","Reproduzindo resposta..."),
            (False,"STANDBY","Pronto."),
        ]
        i=0
        while True:
            if state.clientes:
                state.update(*demos[i%len(demos)])
                if i%3==0:
                    state.push_cmd(random.choice([
                        "briefing","que horas são","clima aracaju",
                        "minha agenda","status sistema","minhas tarefas"
                    ]))
            i+=1;time.sleep(4)

    threading.Thread(target=_demo, daemon=True).start()

    loop = asyncio.new_event_loop()
    _loop = loop
    asyncio.set_event_loop(loop)
    config = uvicorn.Config(app, host="0.0.0.0", port=8765,
                             log_level="info", loop="asyncio")
    server = uvicorn.Server(config)
    loop.run_until_complete(server.serve())