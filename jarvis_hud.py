"""
╔══════════════════════════════════════════════════════════╗
║         J.A.R.V.I.S  —  MARK XII  ·  HUD v2             ║
║  3 Níveis de tamanho · Design limpo · Atalhos de teclado ║
╚══════════════════════════════════════════════════════════╝

Execute:
    python jarvis_hud.py

Atalhos globais:
    Ctrl+Shift+J  →  mostrar / esconder HUD
    Ctrl+Shift+1  →  Nível 1 (só a bola)
    Ctrl+Shift+2  →  Nível 2 (bola + métricas)
    Ctrl+Shift+3  →  Nível 3 (completo)
"""

import os, sys, math, time, datetime, threading, random
from collections import deque

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import psutil
import customtkinter as ctk

from jarvis_core import (
    processar_comando, rodar_jarvis,
    falar_sync, notificar, log, WAKE_WORD
)

# ═══════════════════════════════════════════════════════════
#  CORES DE ESTADO
# ═══════════════════════════════════════════════════════════
CORES = {
    False:     "#00BFFF",
    True:      "#FF3333",
    "ativo":   "#00FF88",
    "ia":      "#BF5FFF",
    "foco":    "#FF9900",
    "alerta":  "#FF3333",
    "discord": "#7289DA",
}

# Cores base da UI
BG        = "#030810"
BG2       = "#071020"
ACCENT    = "#00D4FF"
ACCENT2   = "#00FF88"
RING_DIM  = "#081828"
RING_MED  = "#0d3a50"
TEXT_OFF  = "#0c2235"
TEXT_DIM  = "#1a5070"
TEXT_MED  = "#2a7a9a"


# ═══════════════════════════════════════════════════════════
#  UTILITÁRIOS
# ═══════════════════════════════════════════════════════════
def _hex_blend(hex_color: str, alpha: float, bg: int = 5) -> str:
    """Simula transparência misturando hex_color com fundo escuro."""
    h = hex_color.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    ri = int(bg + (r - bg) * alpha)
    gi = int(bg + (g - bg) * alpha)
    bi = int(bg + (b - bg) * alpha)
    return f"#{ri:02x}{gi:02x}{bi:02x}"


def _round_rect(canvas, x1, y1, x2, y2, r=12, **kw):
    pts = [
        x1+r, y1,   x2-r, y1,
        x2,   y1+r, x2,   y2-r,
        x2,   y2,   x2-r, y2,
        x1+r, y2,   x1,   y2-r,
        x1,   y1+r, x1+r, y1,
    ]
    return canvas.create_polygon(pts, smooth=True, **kw)


# ═══════════════════════════════════════════════════════════
#  NÍVEIS DE TAMANHO
#
#  1 → só o núcleo animado  (140 × 160)
#  2 → núcleo + métricas    (200 × 320)
#  3 → completo             (200 × 480)
# ═══════════════════════════════════════════════════════════
NIVEIS = {
    1: {"W": 140, "H": 160,  "CX": 70, "CY": 74},
    2: {"W": 200, "H": 316,  "CX": 100, "CY": 100},
    3: {"W": 200, "H": 480,  "CX": 100, "CY": 100},
}


class JarvisHUD(ctk.CTk):

    def __init__(self, nivel_inicial: int = 1):
        super().__init__()
        self._nivel     = nivel_inicial
        self._visivel   = True
        self._ang       = 0.0
        self._ang2      = 90.0
        self._pulso_r   = 24.0
        self._pulso_dir = 1
        self._pulso_glow  = 0.0
        self._pulso_gdir  = 1
        self._onda_fase   = 0.0
        self._onda_ativa  = False
        self._onda_alts   = [2.0] * 7
        self._estado_atual = False
        self._cor_atual    = ACCENT
        self._hist_cmds    = deque(maxlen=4)
        self._bat_suave    = 0.8
        self._cpu_hist     = deque([0.0] * 30, maxlen=30)
        self._net_hist     = deque([0.0] * 30, maxlen=30)
        self._net_bytes    = sum(psutil.net_io_counters()[:2])
        self._grafico_its  = []
        self._particulas   = []
        self._painel       = None
           # Chat em memória (para o painel lateral)
        self._chat_msgs = deque(maxlen=100)
        self._chat_frame = None  # ref ao frame de bolhas
 
        # Registra callback para receber mensagens do core
        try:
            from jarvis_core import registrar_chat_callback
            registrar_chat_callback(self._on_chat_msg)
        except Exception:
            pass

        # setup janela raiz
        self.overrideredirect(True)
        self.attributes("-topmost", True)
        self.attributes("-alpha", 0.0)
        self.configure(fg_color=BG)

        import tkinter as tk
        self._tk = tk

        # Canvas único — resizado via _set_nivel
        self.cv = ctk.CTkCanvas(self, bg=BG, highlightthickness=0)
        self.cv.place(x=0, y=0)
        self.cv.configure(takefocus=False)

        self.bind("<ButtonPress-1>",   self._start_move)
        self.bind("<B1-Motion>",       self._do_move)

        self.after(200, self._desativar_im)

        # Sinal do launcher para trocar nível (SIGUSR2)
        import signal as _sig
        _sig.signal(_sig.SIGUSR2, lambda s, f: self.after(0, self._ler_nivel_externo))

        # Aplica nível inicial e constrói UI
        self._set_nivel(nivel_inicial, boot=True)

        # Ticks de animação
        self._tick_anim()
        self._tick_metricas()
        self._tick_onda()
        self._init_particulas()

        self.after(100, self._animacao_boot)

    # ─────────────────────────────────────────────────────
    #  NÍVEIS
    # ─────────────────────────────────────────────────────
    def _set_nivel(self, nivel: int, boot=False):
        nivel = max(1, min(3, nivel))
        self._nivel = nivel
        cfg = NIVEIS[nivel]
        self.W, self.H, self.CX, self.CY = (
            cfg["W"], cfg["H"], cfg["CX"], cfg["CY"])

        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        x = sw - self.W - 18
        y = sh - self.H - 55
        self.geometry(f"{self.W}x{self.H}+{x}+{y}")
        self.cv.configure(width=self.W, height=self.H)

        self.cv.delete("all")
        self._grafico_its.clear()
        self._onda_bs    = []
        self._hist_tags  = []
        self._lbl_ids    = {}  # ids de textos dinâmicos por nível

        self._build_nivel()

        if not boot and self._visivel:
            self.after(0, lambda: self.attributes("-alpha", 0.93))

    def set_nivel(self, nivel: int):
        """API pública — pode ser chamada de qualquer thread."""
        self.after(0, lambda: self._set_nivel(nivel))

    def _build_nivel(self):
        """Reconstrói o canvas completo para o nível atual."""
        self._draw_frame()
        self._draw_core()
        if self._nivel >= 1:
            self._draw_nivel1_extras()
        if self._nivel >= 2:
            self._draw_nivel2()
        if self._nivel >= 3:
            self._draw_nivel3()

    # ── Moldura / fundo ──────────────────────────────────
    def _draw_frame(self):
        W, H = self.W, self.H
        # Fundo com gradiente simulado (3 retângulos)
        self.cv.create_rectangle(0, 0, W, H, fill=BG, outline="")
        # Borda externa limpa
        _round_rect(self.cv, 1, 1, W-1, H-1, r=14,
                    fill="", outline=RING_MED, width=1)
        # Borda interna sutil
        _round_rect(self.cv, 3, 3, W-3, H-3, r=12,
                    fill="", outline=RING_DIM, width=1)
        # Cantos brilhantes em L
        cl = 16
        for (x1,y1,x2,y2) in [
            (5,5, 5+cl,5), (5,5, 5,5+cl),
            (W-5-cl,5, W-5,5), (W-5,5, W-5,5+cl),
            (5,H-5, 5+cl,H-5), (5,H-5, 5,H-5-cl),
            (W-5-cl,H-5, W-5,H-5), (W-5,H-5-cl, W-5,H-5),
        ]:
            self.cv.create_line(x1,y1,x2,y2, fill=ACCENT, width=1, capstyle="round")

    # ── Núcleo central (igual em todos os níveis) ────────
    def _draw_core(self):
        cx, cy = self.CX, self.CY

        # Halo externo — mais camadas, glow mais pronunciado
        for r, alpha in [(78, 0.03), (70, 0.05), (62, 0.09), (54, 0.14), (46, 0.18)]:
            cor = _hex_blend(ACCENT, alpha)
            self.cv.create_oval(cx-r, cy-r, cx+r, cy+r,
                                 outline=cor, fill="", width=1)

        # Anel externo sólido brilhante
        self.cv.create_oval(cx-56, cy-56, cx+56, cy+56,
                             outline=_hex_blend(ACCENT, 0.25), fill="", width=1)

        # Anéis animados principais
        self.arc_a = self.cv.create_arc(cx-54, cy-54, cx+54, cy+54,
                                         start=0, extent=80, style="arc",
                                         outline=ACCENT, width=2)
        self.arc_b = self.cv.create_arc(cx-54, cy-54, cx+54, cy+54,
                                         start=180, extent=80, style="arc",
                                         outline=_hex_blend(ACCENT, 0.35), width=2)
        self.arc_c = self.cv.create_arc(cx-42, cy-42, cx+42, cy+42,
                                         start=90, extent=55, style="arc",
                                         outline=_hex_blend(ACCENT, 0.28), width=1)
        # Anel externo lento (sentido oposto)
        self.arc_d = self.cv.create_arc(cx-66, cy-66, cx+66, cy+66,
                                         start=45, extent=30, style="arc",
                                         outline=_hex_blend(ACCENT, 0.18), width=1)
        self.arc_e = self.cv.create_arc(cx-66, cy-66, cx+66, cy+66,
                                         start=225, extent=30, style="arc",
                                         outline=_hex_blend(ACCENT, 0.18), width=1)
        # Anel verde girando na direcao oposta
        self.arc_f = self.cv.create_arc(cx-48, cy-48, cx+48, cy+48,
                                         start=20, extent=40, style="arc",
                                         outline=_hex_blend("#00FF88", 0.22), width=1)

        # Anel medio pulsante
        self.anel = self.cv.create_oval(cx-36, cy-36, cx+36, cy+36,
                                         outline=ACCENT, fill="", width=1)

        # Nucleo solido maior
        self.pulso = self.cv.create_oval(cx-22, cy-22, cx+22, cy+22,
                                          fill=BG2, outline=ACCENT, width=2)

        # Texto AI centralizado
        self.letra = self.cv.create_text(cx, cy, text="AI",
                                          font=("Courier", 12, "bold"), fill=ACCENT)

        # Marcacoes cardinais com traco duplo
        for angd in [0, 90, 180, 270]:
            rad = math.radians(angd)
            x1 = cx + 72 * math.cos(rad); y1 = cy + 72 * math.sin(rad)
            x2 = cx + 80 * math.cos(rad); y2 = cy + 80 * math.sin(rad)
            self.cv.create_line(x1, y1, x2, y2, fill=RING_MED, width=2, capstyle="round")
        # Marcacoes diagonais menores
        for angd in [45, 135, 225, 315]:
            rad = math.radians(angd)
            x1 = cx + 70 * math.cos(rad); y1 = cy + 70 * math.sin(rad)
            x2 = cx + 76 * math.cos(rad); y2 = cy + 76 * math.sin(rad)
            self.cv.create_line(x1, y1, x2, y2,
                                fill=_hex_blend(ACCENT, 0.2), width=1)

    # ── Nível 1 extras: título + status + waveform ───────
    def _draw_nivel1_extras(self):
        W, H, cx, cy = self.W, self.H, self.CX, self.CY

        # Titulo topo modernizado
        self.cv.create_text(W//2, 13, text="J.A.R.V.I.S",
                             font=("Courier", 10, "bold"), fill=ACCENT)
        self.cv.create_text(W//2, 25, text="·  M K  X I V  ·",
                             font=("Courier", 6), fill=TEXT_MED)

        # Divisor topo
        self._div_topo = W//2
        self.cv.create_line(20, 31, W-20, 31, fill=RING_DIM, width=1)

        # Status + log (abaixo do núcleo)
        sep = cy + 62
        self.cv.create_line(20, sep, W-20, sep, fill=RING_DIM, width=1)

        self.tag_status = self.cv.create_text(
            W//2, sep+13, text="STANDBY",
            font=("Courier", 9, "bold"), fill=ACCENT)
        self.tag_log = self.cv.create_text(
            W//2, sep+25, text="Aguardando...",
            font=("Courier", 6), fill=TEXT_MED)

        # Waveform — 7 barrinhas
        y_w = sep + 44
        for i in range(7):
            x = cx - 24 + i * 8
            b = self.cv.create_rectangle(x, y_w-2, x+5, y_w+2,
                                          fill=RING_MED, outline="")
            self._onda_bs.append((b, x, y_w))

        self.cv.create_line(20, y_w+14, W-20, y_w+14, fill=RING_DIM, width=1)

    # ── Nível 2: métricas (sem histórico nem botão) ──────
    def _draw_nivel2(self):
        W, H, cx, cy = self.W, self.H, self.CX, self.CY

        # Obtém y base logo após a waveform
        # (sep = cy+62, y_w = sep+44 = cy+106, linha = cy+120)
        y0 = cy + 128

        # Labels SYS / hora
        self.cv.create_text(14, y0, text="SYS",
                             font=("Courier", 6, "bold"), fill=TEXT_DIM, anchor="w")
        self.tag_hora = self.cv.create_text(
            W-14, y0, text="--:--:--",
            font=("Courier", 6), fill=ACCENT, anchor="e")

        # Barras
        bar_h  = 10
        bar_gap = 15
        BX, BW = 36, W - 50   # início e largura das barras

        def _barra(label, y, fill_cor):
            self.cv.create_text(14, y + bar_h//2, text=label,
                                 font=("Courier", 6, "bold"), fill=TEXT_MED, anchor="w")
            # fundo da barra com borda levemente visivel
            self.cv.create_rectangle(BX, y, BX+BW, y+bar_h,
                                      outline=RING_MED, fill=BG)
            f = self.cv.create_rectangle(BX, y, BX, y+bar_h,
                                          outline="", fill=fill_cor)
            v = self.cv.create_text(W-15, y + bar_h//2, text="--",
                                     font=("Courier", 6, "bold"), fill=ACCENT, anchor="e")
            return f, v, BX, BX+BW, y, y+bar_h

        self._pwr = _barra("⚡", y0+12,          "#006090")
        self._cpu = _barra("⬡", y0+12+bar_gap,   "#003a9a")
        self._ram = _barra("▣", y0+12+bar_gap*2, "#005a4a")
        self._net = _barra("↕", y0+12+bar_gap*3, "#004a7a")

        # Linha divisória final nível 2
        ly = y0 + 12 + bar_gap*4 + 6
        self.cv.create_line(14, ly, W-14, ly, fill=RING_DIM, width=1)

        # Gráfico CPU simples
        self._gy0 = ly + 14
        self._gx1, self._gx2 = 14, W-14

    # ── Nível 3: histórico + botão digitar ───────────────
    def _draw_nivel3(self):
        W, H = self.W, self.H

        # Histórico
        # gy0 = cy + 128 + 12 + 15*4 + 6 + 14 = cy + 220 = 320
        hy = self.CY + 224
        self.cv.create_line(14, hy, W-14, hy, fill=RING_DIM, width=1)
        self.cv.create_text(14, hy+8, text="HISTÓRICO",
                             font=("Courier", 5, "bold"), fill=TEXT_DIM, anchor="w")
        self._hist_tags = [
            self.cv.create_text(14, hy+18+i*11, text="",
                                 font=("Courier", 5), fill=TEXT_OFF, anchor="w")
            for i in range(4)
        ]

        # Botão DIGITAR
        btn_y1 = H - 52
        btn_y2 = H - 26
        self.cv.create_line(14, btn_y1-4, W-14, btn_y1-4, fill=RING_DIM, width=1)
        self._btn_r = _round_rect(self.cv, 10, btn_y1, W-10, btn_y2, r=8,
                                   fill=RING_DIM, outline=ACCENT)
        self._btn_t = self.cv.create_text(
            W//2, (btn_y1+btn_y2)//2, text="⌨  DIGITAR",
            font=("Courier", 8, "bold"), fill=ACCENT)
        for _t in (self._btn_r, self._btn_t):
            self.cv.tag_bind(_t, "<ButtonPress-1>", lambda e: self._toggle_painel())
            self.cv.tag_bind(_t, "<Enter>",  lambda e: self.cv.itemconfig(self._btn_r, fill=RING_MED))
            self.cv.tag_bind(_t, "<Leave>",  lambda e: self.cv.itemconfig(self._btn_r, fill=RING_DIM))

        # Rodapé
        self.cv.create_line(14, H-16, W-14, H-16, fill=RING_DIM, width=1)
        self.cv.create_text(W//2, H-8, text="CTRL+SHIFT+1/2/3  ·  DRAG ✥",
                             font=("Courier", 4), fill=TEXT_OFF)

    # ─────────────────────────────────────────────────────
    #  ANIMAÇÃO DE BOOT
    # ─────────────────────────────────────────────────────
    def _animacao_boot(self):
        etapas = [
            ("#004488", "INICIALIZANDO", "Mark XIV..."),
            ("#0055aa", "CARREGANDO",    "Módulos IA..."),
            ("#0066cc", "CONECTANDO",    "Groq LLM..."),
            ("#0088dd", "CALIBRANDO",    "Microfone..."),
            (ACCENT,    "ONLINE",        "Sistemas OK"),
        ]

        def _fade(a=0.0):
            a = min(a + 0.06, 0.93)
            self.attributes("-alpha", a)
            if a < 0.93:
                self.after(22, lambda: _fade(a))
            else:
                _scan(0)

        def _scan(i):
            if i >= len(etapas):
                self.safe_update(False, "STANDBY", "Aguardando comando...")
                return
            cor, status, msg = etapas[i]
            self._aplicar_cor(cor)
            if hasattr(self, "tag_status"):
                self.cv.itemconfig(self.tag_status, text=status, fill=cor)
            if hasattr(self, "tag_log"):
                self.cv.itemconfig(self.tag_log, text=msg.upper())
            self.after(340, lambda: _scan(i + 1))

        _fade()

    def _aplicar_cor(self, cor: str):
        self._cor_atual = cor
        for attr in ("arc_a", "anel", "pulso", "letra"):
            if hasattr(self, attr):
                field = "fill" if attr == "letra" else "outline"
                self.cv.itemconfig(getattr(self, attr), **{field: cor})
        # arc_f sempre verde, independente do estado
        if hasattr(self, "arc_f"):
            self.cv.itemconfig(self.arc_f,
                               outline=_hex_blend("#00FF88", 0.22))

    # ─────────────────────────────────────────────────────
    #  PARTÍCULAS (nível 1 — só ao redor do núcleo)
    # ─────────────────────────────────────────────────────
    def _init_particulas(self):
        for _ in range(6):
            self._spawn_particula()
        self._tick_particulas()

    def _spawn_particula(self):
        cx, cy = self.CX, self.CY
        ang = random.uniform(0, 2 * math.pi)
        r   = random.uniform(22, 42)
        x   = cx + r * math.cos(ang)
        y   = cy + r * math.sin(ang)
        vx  = random.uniform(-0.3, 0.3)
        vy  = random.uniform(-0.5, -0.1)
        vm  = random.randint(50, 100)
        pid = self.cv.create_oval(x-1, y-1, x+1, y+1,
                                   fill=RING_MED, outline="")
        self._particulas.append([x, y, vx, vy, vm, vm, pid])

    def _tick_particulas(self):
        mortas = []
        for i, p in enumerate(self._particulas):
            p[0] += p[2]; p[1] += p[3]; p[4] -= 1
            if p[4] <= 0:
                self.cv.delete(p[6]); mortas.append(i)
            else:
                alpha = p[4] / p[5] * 0.35
                cor   = _hex_blend(self._cor_atual, alpha)
                self.cv.coords(p[6], p[0]-1, p[1]-1, p[0]+1, p[1]+1)
                self.cv.itemconfig(p[6], fill=cor)
        for i in reversed(mortas):
            self._particulas.pop(i)
            self._spawn_particula()
        self.after(55, self._tick_particulas)

    # ─────────────────────────────────────────────────────
    #  ANIMAÇÃO 30fps
    # ─────────────────────────────────────────────────────
    def _tick_anim(self):
        self._ang  = (self._ang  + 1.8) % 360
        self._ang2 = (self._ang2 + 0.8) % 360
        cx, cy = self.CX, self.CY
        a, a2  = self._ang, self._ang2

        if hasattr(self, "arc_a"):
            self.cv.itemconfig(self.arc_a, start=a,       extent=80)
            self.cv.itemconfig(self.arc_b, start=a+180,   extent=80)
            self.cv.itemconfig(self.arc_c, start=a+90,    extent=55)
            self.cv.itemconfig(self.arc_d, start=-a2,     extent=30)
            self.cv.itemconfig(self.arc_e, start=-a2+180, extent=30)
        if hasattr(self, "arc_f"):
            self.cv.itemconfig(self.arc_f, start=a*1.3+20, extent=40)

        # Anel pulsante
        if hasattr(self, "anel"):
            r = int(32 * (1 + 0.05 * math.sin(a * math.pi / 60)))
            self.cv.coords(self.anel, cx-r, cy-r, cx+r, cy+r)

        # Núcleo respirando
        if hasattr(self, "pulso"):
            self._pulso_r    += self._pulso_dir * 0.2
            self._pulso_glow += self._pulso_gdir * 0.02
            if self._pulso_r    > 23: self._pulso_dir  = -1
            if self._pulso_r    < 17: self._pulso_dir  =  1
            if self._pulso_glow > 1:  self._pulso_gdir = -1
            if self._pulso_glow < 0:  self._pulso_gdir =  1
            pr  = int(self._pulso_r)
            cor = _hex_blend(self._cor_atual, 0.08 + self._pulso_glow * 0.08)
            self.cv.coords(self.pulso, cx-pr, cy-pr, cx+pr, cy+pr)
            self.cv.itemconfig(self.pulso, fill=cor)

        self.after(33, self._tick_anim)

    # ─────────────────────────────────────────────────────
    #  WAVEFORM
    # ─────────────────────────────────────────────────────
    def _tick_onda(self):
        self._onda_fase += 0.22
        cor = CORES.get(self._estado_atual, ACCENT)
        for i, (bid, bx, by) in enumerate(self._onda_bs):
            if self._onda_ativa:
                alvo = 2 + 10 * abs(math.sin(self._onda_fase + i * 0.9))
            else:
                alvo = 2.0
            self._onda_alts[i] += (alvo - self._onda_alts[i]) * 0.25
            h = max(2, int(self._onda_alts[i]))
            self.cv.coords(bid, bx, by-h, bx+5, by+h)
            self.cv.itemconfig(bid, fill=cor if self._onda_ativa else RING_MED)
        self.after(40, self._tick_onda)

    # ─────────────────────────────────────────────────────
    #  MÉTRICAS 1Hz
    # ─────────────────────────────────────────────────────
    def _tick_metricas(self):
        if self._nivel < 2 or not hasattr(self, "tag_hora"):
            self.after(1000, self._tick_metricas)
            return

        self.cv.itemconfig(self.tag_hora,
                           text=datetime.datetime.now().strftime("%H:%M:%S"))

        def _bar(meta, pct, cor_ok, limiar=0.75):
            fill, val, x0, x1, y0, y1 = meta
            l = int((x1 - x0) * min(pct, 1.0))
            self.cv.coords(fill, x0, y0, x0+l, y1)
            cor = "#FF4444" if pct > limiar else cor_ok
            self.cv.itemconfig(fill, fill=cor)
            self.cv.itemconfig(val,  text=f"{int(pct*100)}%")

        # Bateria
        try:
            bat = psutil.sensors_battery()
            pct = (bat.percent / 100) if bat else 0.8
        except Exception:
            pct = 0.8
        self._bat_suave += (pct - self._bat_suave) * 0.15
        f, v, x0, x1, y0, y1 = self._pwr
        l = int((x1-x0) * self._bat_suave)
        self.cv.coords(f, x0, y0, x0+l, y1)
        self.cv.itemconfig(f, fill="#FF4444" if pct<0.2 else "#FF9900" if pct<0.3 else "#005080")
        self.cv.itemconfig(v, text=f"{int(pct*100)}%")

        cpu = psutil.cpu_percent(interval=None) / 100
        self._cpu_hist.append(cpu)
        _bar(self._cpu, cpu, "#00387a")

        ram = psutil.virtual_memory().percent / 100
        _bar(self._ram, ram, "#004a3a", 0.85)

        try:
            nb    = psutil.net_io_counters()
            total = nb.bytes_sent + nb.bytes_recv
            kbps  = max(0, total - self._net_bytes) / 1024
            self._net_bytes = total
        except Exception:
            kbps = 0
        self._net_hist.append(kbps)
        mx = max(max(self._net_hist), 1)
        f, v, x0, x1, y0, y1 = self._net
        l = int((x1-x0) * min(kbps/mx, 1.0))
        self.cv.coords(f, x0, y0, x0+l, y1)
        self.cv.itemconfig(f, fill="#003a5a")
        self.cv.itemconfig(v, text=f"{kbps:.0f}KB/s")

        # Gráfico CPU
        for it in self._grafico_its:
            self.cv.delete(it)
        self._grafico_its.clear()
        hist = list(self._cpu_hist)
        pw   = (self._gx2 - self._gx1) / max(len(hist), 1)
        pts  = [c for i, v2 in enumerate(hist)
                for c in (self._gx1 + i*pw, self._gy0 - int(v2 * 10))]
        if len(pts) >= 4:
            it = self.cv.create_line(*pts, fill=ACCENT, width=1, smooth=True)
            self._grafico_its.append(it)

        self.after(1000, self._tick_metricas)

    # ─────────────────────────────────────────────────────
    #  API PÚBLICA
    # ─────────────────────────────────────────────────────
    def safe_update(self, cor, acao: str, msg: str = ""):
        self.after(0, lambda: self._update_ui(cor, acao, msg))

    def _update_ui(self, cor, acao: str, msg: str = ""):
        self._estado_atual = cor
        c = CORES.get(cor, str(cor) if cor else ACCENT)
        self._aplicar_cor(c)
        if hasattr(self, "arc_a"):
            self.cv.itemconfig(self.arc_a, outline=c)
        if hasattr(self, "tag_status"):
            self.cv.itemconfig(self.tag_status, text=acao.upper(), fill=c)
        if msg and hasattr(self, "tag_log"):
            self.cv.itemconfig(self.tag_log, text=msg[:36].upper())
        self._onda_ativa = cor in ("ativo", "ia", "discord", True, "alerta", "foco")

    def push_historico(self, cmd: str):
        self._hist_cmds.appendleft(cmd[:32])
        if self._nivel >= 3 and self._hist_tags:
            cmds = list(self._hist_cmds)
            for i, tag in enumerate(self._hist_tags):
                txt = f"› {cmds[i]}" if i < len(cmds) else ""
                bri = TEXT_MED if i == 0 else TEXT_OFF
                self.cv.itemconfig(tag, text=txt, fill=bri)

    def toggle_visibilidade(self):
        self.after(0, self._toggle_vis)

    def _toggle_vis(self):
        self._visivel = not self._visivel
        if self._visivel:
            self.deiconify(); self.attributes("-alpha", 0.93)
        else:
            self.attributes("-alpha", 0.0); self.withdraw()

    def _ler_nivel_externo(self):
        """Lê /tmp/jarvis_nivel e troca o nível (chamado via SIGUSR2 pelo launcher)."""
        try:
            from pathlib import Path
            n = int(Path("/tmp/jarvis_nivel").read_text().strip())
            self.set_nivel(n)
        except Exception:
            pass

    def set_processador(self, fn):
        self._processador = fn

    # ─────────────────────────────────────────────────────
    #  SHUTDOWN
    # ─────────────────────────────────────────────────────
    def animacao_shutdown(self):
        def _run():
            self.after(0, lambda: self._update_ui(True, "OFFLINE", "Desativando..."))
            time.sleep(0.35)
            for _ in range(3):
                for alpha in [0.25, 0.93]:
                    self.after(0, lambda a=alpha: self.attributes("-alpha", a))
                    time.sleep(0.11)
            h = self.H
            while h > 40:
                h = max(40, h - 20)
                self.after(0, lambda hh=h: self.geometry(f"{self.W}x{hh}"))
                time.sleep(0.016)
            a = 0.93
            while a > 0:
                a = max(0.0, a - 0.06)
                self.after(0, lambda aa=a: self.attributes("-alpha", aa))
                time.sleep(0.03)
            time.sleep(0.06)
            os._exit(0)
        threading.Thread(target=_run, daemon=True).start()

    # ─────────────────────────────────────────────────────
    #  MOVIMENTAÇÃO
    # ─────────────────────────────────────────────────────
    def _start_move(self, e): self._dx, self._dy = e.x, e.y
    def _do_move(self, e):
        self.geometry(f"+{self.winfo_x()+(e.x-self._dx)}+{self.winfo_y()+(e.y-self._dy)}")

    def _desativar_im(self):
        try:
            import subprocess as _sp
            wid = hex(self.winfo_id())
            _sp.run(["xprop", "-id", wid, "-f", "WM_HINTS", "32i",
                     "-set", "WM_HINTS", "0"], capture_output=True)
        except Exception:
            pass

    # ─────────────────────────────────────────────────────
    #  PAINEL DE DIGITAÇÃO (nível 3)
    # ─────────────────────────────────────────────────────
    def _toggle_painel(self):
        tk = self._tk
        if self._painel and self._painel.winfo_exists():
            self._painel.destroy()
            self._painel = None
            if hasattr(self, "_btn_t"):
                self.cv.itemconfig(self._btn_t, text="⌨  DIGITAR")
                self.cv.itemconfig(self._btn_r, fill=RING_DIM, outline=ACCENT)
            return

        if hasattr(self, "_btn_t"):
            self.cv.itemconfig(self._btn_t, text="✕  FECHAR")
            self.cv.itemconfig(self._btn_r, fill="#1a0010", outline="#FF4444")

        hx, hy = self.winfo_x(), self.winfo_y()
        pw, ph  = 360, self.H
        px = hx - pw - 8
        if px < 0: px = hx + self.W + 8

        p = tk.Toplevel()
        self._painel = p
        p.overrideredirect(True)
        p.attributes("-topmost", True)
        p.configure(bg=ACCENT)
        p.geometry(f"{pw}x{ph}+{px}+{hy}")

        inner = tk.Frame(p, bg=BG)
        inner.pack(fill="both", expand=True, padx=1, pady=1)

        # Cabecalho
        hdr = tk.Frame(inner, bg=BG2)
        hdr.pack(fill="x")
        tk.Label(hdr, text="J.A.R.V.I.S  ·  CHAT",
                 bg=BG2, fg=ACCENT, font=("Courier", 9, "bold")).pack(
                 side="left", padx=12, pady=8)
        tk.Button(hdr, text="✕", bg=BG2, fg="#FF4444",
                  relief="flat", bd=0, font=("Courier", 11, "bold"),
                  cursor="hand2", activebackground="#1a0010",
                  command=self._toggle_painel).pack(side="right", padx=8)
        tk.Frame(inner, bg=RING_MED, height=1).pack(fill="x")

        # Area de chat com scroll
        chat_outer = tk.Frame(inner, bg=BG)
        chat_outer.pack(fill="both", expand=True, padx=0, pady=0)

        self._chat_canvas = tk.Canvas(chat_outer, bg=BG, highlightthickness=0)
        scrollbar = tk.Scrollbar(chat_outer, orient="vertical",
                                  command=self._chat_canvas.yview,
                                  bg=BG, troughcolor=BG2, width=6)
        self._chat_canvas.configure(yscrollcommand=scrollbar.set)

        scrollbar.pack(side="right", fill="y")
        self._chat_canvas.pack(side="left", fill="both", expand=True)

        self._chat_frame = tk.Frame(self._chat_canvas, bg=BG)
        self._chat_canvas_window = self._chat_canvas.create_window(
            (0, 0), window=self._chat_frame, anchor="nw"
        )

        def _on_frame_configure(e):
            self._chat_canvas.configure(
                scrollregion=self._chat_canvas.bbox("all"))
        def _on_canvas_configure(e):
            self._chat_canvas.itemconfig(
                self._chat_canvas_window, width=e.width)

        self._chat_frame.bind("<Configure>", _on_frame_configure)
        self._chat_canvas.bind("<Configure>", _on_canvas_configure)

        # Recarrega historico de mensagens
        for role, msg in list(self._chat_msgs):
            self._append_bolha(role, msg)

        # Scroll ate o fim
        self._chat_canvas.update_idletasks()
        self._chat_canvas.yview_moveto(1.0)

        tk.Frame(inner, bg=RING_MED, height=1).pack(fill="x")
        tk.Label(inner, text="  Enter envia  ·  Esc fecha",
                 bg=BG, fg=TEXT_OFF, font=("Courier", 6)).pack(
                 anchor="w", padx=8, pady=(4, 2))
        tk.Frame(inner, bg=RING_DIM, height=1).pack(fill="x", padx=8)

        # Input
        fr = tk.Frame(inner, bg=BG)
        fr.pack(fill="x", padx=10, pady=10)
        tk.Label(fr, text="›", bg=BG, fg=ACCENT,
                 font=("Courier", 13, "bold")).pack(side="left", padx=(0,6))
        self._pvar   = tk.StringVar()
        self._pentry = tk.Entry(
            fr, textvariable=self._pvar,
            bg="#040c18", fg=ACCENT,
            insertbackground=ACCENT,
            selectbackground=RING_MED,
            relief="flat", highlightthickness=1,
            highlightcolor=ACCENT,
            highlightbackground=RING_MED,
            font=("Courier", 10))
        self._pentry.pack(side="left", fill="x", expand=True, ipady=7)
        self._pentry.bind("<Return>", lambda e: self._enviar_texto())
        self._pentry.bind("<Escape>", lambda e: self._toggle_painel())
        tk.Button(fr, text="►", bg=RING_MED, fg=ACCENT,
                  activebackground=ACCENT, activeforeground=BG,
                  relief="flat", bd=0, font=("Courier", 11, "bold"),
                  cursor="hand2", command=self._enviar_texto
                  ).pack(side="left", padx=(6,0), ipady=7)

        p.update_idletasks(); p.lift()
        self._pentry.focus_force()
        try:
            import subprocess as _sp
            _sp.Popen(["xdotool", "windowfocus", "--sync", str(p.winfo_id())],
                      stdout=_sp.DEVNULL, stderr=_sp.DEVNULL)
        except Exception:
            pass

    def _enviar_texto(self):
        try:
            texto = self._pvar.get().strip().lower()
        except Exception:
            return
        if not texto: return
        self._pvar.set("")
 
        # Adiciona bolha do usuário imediatamente
        self._chat_msgs.append(("user", texto))
        self._append_bolha("user", texto)
 
        self.push_historico(texto)
        self.safe_update("ativo", "TEXTO", texto[:32])
        log.info(f"TEXTO: {texto}")
        try:
            self._pentry.focus_force()
        except Exception:
            pass
        if hasattr(self, "_processador"):
            threading.Thread(
                target=self._processador,
                args=(texto,), daemon=True
            ).start()
            
    def _on_chat_msg(self, role: str, texto: str):
        """Callback chamado por falar/falar_sync do core."""
        self._chat_msgs.append((role, texto))
        self.after(0, lambda: self._append_bolha(role, texto))

    def _append_bolha(self, role: str, texto: str):
        """Adiciona uma bolha ao frame de chat se o painel estiver aberto."""
        if not self._chat_frame:
            return
        tk = self._tk
        try:
            if not self._chat_frame.winfo_exists():
                return
        except Exception:
            return
 
        is_jarvis = role == "jarvis"
 
        # Container da bolha (alinha esquerda ou direita)
        row = tk.Frame(self._chat_frame, bg=BG)
        row.pack(fill="x", padx=6, pady=2, anchor="w" if is_jarvis else "e")
 
        if is_jarvis:
            # Prefixo J.
            tk.Label(row, text="J.", bg=BG, fg=ACCENT,
                     font=("Courier", 7, "bold")).pack(side="left", anchor="n", pady=2)
 
        # Bolha
        bolha_bg = "#0a1e35" if is_jarvis else "#0a2a1a"
        bolha_fg = ACCENT    if is_jarvis else "#00FF88"
        bolha_border = RING_MED if is_jarvis else "#004a2a"
 
        bolha = tk.Frame(row, bg=bolha_bg,
                         highlightbackground=bolha_border,
                         highlightthickness=1)
        bolha.pack(side="left" if is_jarvis else "right",
                   anchor="w" if is_jarvis else "e")
 
        # Texto com quebra de linha automática
        tk.Label(bolha, text=texto, bg=bolha_bg, fg=bolha_fg,
                 font=("Courier", 8), wraplength=240,
                 justify="left", padx=8, pady=5).pack()
 
        if not is_jarvis:
            tk.Label(row, text="›", bg=BG, fg="#00FF88",
                     font=("Courier", 7, "bold")).pack(side="right", anchor="n", pady=2)
 
        # Scroll automático para o fim
        try:
            self._chat_canvas.update_idletasks()
            self._chat_canvas.yview_moveto(1.0)
        except Exception:
            pass

# ═══════════════════════════════════════════════════════════
#  ATALHOS GLOBAIS DE TECLADO
#
#  Ctrl+Shift+J  → mostrar/esconder HUD
#  Ctrl+Shift+1  → Nível 1 (só bola)
#  Ctrl+Shift+2  → Nível 2 (bola + métricas)
#  Ctrl+Shift+3  → Nível 3 (completo)
# ═══════════════════════════════════════════════════════════
def registrar_atalho(hud: JarvisHUD):
    import signal
    signal.signal(signal.SIGUSR1, lambda s, f: hud.toggle_visibilidade())

    def _listener():
        try:
            from pynput import keyboard as kb

            combinacoes = {
                frozenset([kb.Key.ctrl_l, kb.Key.shift, kb.KeyCode.from_char('j')]): hud.toggle_visibilidade,
                frozenset([kb.Key.ctrl_l, kb.Key.shift, kb.KeyCode.from_char('1')]): lambda: hud.set_nivel(1),
                frozenset([kb.Key.ctrl_l, kb.Key.shift, kb.KeyCode.from_char('2')]): lambda: hud.set_nivel(2),
                frozenset([kb.Key.ctrl_l, kb.Key.shift, kb.KeyCode.from_char('3')]): lambda: hud.set_nivel(3),
            }

            pressionadas = set()

            def on_press(key):
                pressionadas.add(key)
                for combo, fn in combinacoes.items():
                    if combo.issubset(pressionadas):
                        fn()

            def on_release(key):
                pressionadas.discard(key)

            with kb.Listener(on_press=on_press, on_release=on_release) as l:
                log.info("Atalhos registrados: Ctrl+Shift+J/1/2/3")
                l.join()
        except Exception as e:
            log.warning(f"Hotkey indisponível: {e}")

    threading.Thread(target=_listener, daemon=True).start()


# ═══════════════════════════════════════════════════════════
#  ENTRY POINT
# ═══════════════════════════════════════════════════════════
if __name__ == "__main__":
    import os
    app = JarvisHUD(nivel_inicial=1)   # ← começa no nível 1 (só a bola)
    registrar_atalho(app)
    app.set_processador(lambda cmd: processar_comando(cmd, app))
    threading.Thread(target=rodar_jarvis, args=(app,), daemon=True).start()
    app.mainloop()