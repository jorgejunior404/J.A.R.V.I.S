"""
╔══════════════════════════════════════════════════════════╗
║              J.A.R.V.I.S  —  MARK XII                   ║
║  IA · Automações · Integrações · HUD Avançado            ║
╚══════════════════════════════════════════════════════════╝

Dependências:
    pip install SpeechRecognition customtkinter google-genai
               python-dotenv psutil Pillow pyautogui edge-tts

Variáveis no .env:
    GEMINI_API_KEY  = sua_chave
    VOZ             = pt-BR-AntonioNeural   (opcional)
    PITCH           = 0.91                  (opcional)
    WAKE_WORD       = jarvis                (opcional)
    WEATHER_API_KEY = chave_openweathermap  (opcional)
    DISCORD_TOKEN   = token_do_bot          (opcional)
    DISCORD_CHANNEL_ID = id_do_canal        (opcional)
"""

# ═══════════════════════════════════════════════════════════
#  IMPORTS
# ═══════════════════════════════════════════════════════════
import os, re, json, base64, math, time, datetime
import logging, subprocess, threading, urllib.request, urllib.parse
from collections import deque
from difflib import SequenceMatcher

import psutil
import speech_recognition as sr
import customtkinter as ctk
from dotenv import load_dotenv
from google import genai

# Imports opcionais
try:
    import pyautogui
    pyautogui.FAILSAFE = False
    _PYAUTO_OK = True
except ImportError:
    _PYAUTO_OK = False

try:
    from PIL import ImageGrab
    _PIL_OK = True
except ImportError:
    _PIL_OK = False


# ═══════════════════════════════════════════════════════════
#  CONFIGURAÇÃO
# ═══════════════════════════════════════════════════════════
load_dotenv()

GEMINI_KEY         = os.getenv("GEMINI_API_KEY", "")
VOZ                = os.getenv("VOZ",        "pt-BR-AntonioNeural")
PITCH              = os.getenv("PITCH",      "0.91")
WAKE_WORD          = os.getenv("WAKE_WORD",  "jarvis")
WEATHER_KEY        = os.getenv("WEATHER_API_KEY", "")
DISCORD_TOKEN      = os.getenv("DISCORD_TOKEN", "")
DISCORD_CHANNEL_ID = int(os.getenv("DISCORD_CHANNEL_ID", "0") or "0")

logging.basicConfig(
    filename="jarvis.log", level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
log = logging.getLogger("JARVIS")


# ═══════════════════════════════════════════════════════════
#  MICROFONE
# ═══════════════════════════════════════════════════════════
rec = sr.Recognizer()
rec.pause_threshold          = 0.8
rec.dynamic_energy_threshold = True
mic = sr.Microphone()

def calibrar_microfone():
    with mic as f:
        rec.adjust_for_ambient_noise(f, duration=1.5)
    log.info(f"Mic calibrado. Threshold={rec.energy_threshold:.0f}")

def ouvir(timeout=4, limite=10) -> str:
    try:
        with mic as f:
            audio = rec.listen(f, timeout=timeout, phrase_time_limit=limite)
        return rec.recognize_google(audio, language="pt-BR").lower()
    except (sr.WaitTimeoutError, sr.UnknownValueError):
        return ""
    except Exception as e:
        log.error(f"ouvir: {e}"); return ""

def ouvir_pergunta(timeout=10, limite=30) -> str:
    try:
        with mic as f:
            rec.adjust_for_ambient_noise(f, duration=0.3)
            audio = rec.listen(f, timeout=timeout, phrase_time_limit=limite)
        return rec.recognize_google(audio, language="pt-BR").lower()
    except (sr.WaitTimeoutError, sr.UnknownValueError):
        return ""
    except Exception as e:
        log.error(f"ouvir_pergunta: {e}"); return ""

def contem_wake_word(texto: str, limiar=0.75) -> bool:
    return any(
        SequenceMatcher(None, WAKE_WORD, w).ratio() > limiar
        for w in texto.split()
    )


# ═══════════════════════════════════════════════════════════
#  TTS  (edge-tts + ffmpeg para pitch)
# ═══════════════════════════════════════════════════════════
_fala_thread = None
_fala_proc   = None

def _gerar_audio(texto: str):
    """Gera o áudio com pitch ajustado. Retorna (orig, grave) ou (None, None)."""
    ts    = int(time.time() * 1000)
    orig  = f"/tmp/jv_{ts}.mp3"
    grave = f"/tmp/jv_{ts}_g.mp3"
    try:
        subprocess.run(
            ["edge-tts", "--voice", VOZ, "--text", texto, "--write-media", orig],
            check=True, capture_output=True
        )
        subprocess.run(
            ["ffmpeg", "-y", "-i", orig, "-af", f"rubberband=pitch={PITCH}", grave],
            check=True, capture_output=True
        )
        return orig, grave
    except Exception as e:
        log.error(f"TTS: {e}")
        for f in (orig, grave):
            if os.path.exists(f): os.remove(f)
        return None, None

def parar_fala():
    global _fala_proc
    if _fala_proc and _fala_proc.poll() is None:
        _fala_proc.terminate()

def falar(texto: str):
    """Fala de forma assíncrona (não bloqueia)."""
    global _fala_thread
    def _run():
        global _fala_proc
        orig, grave = _gerar_audio(texto)
        if not grave:
            print(f"[JARVIS] {texto}"); return
        try:
            _fala_proc = subprocess.Popen(["mpg123", "-q", grave])
            _fala_proc.wait()
        finally:
            for f in (orig, grave):
                if f and os.path.exists(f): os.remove(f)
    if _fala_thread and _fala_thread.is_alive():
        _fala_thread.join(timeout=15)
    _fala_thread = threading.Thread(target=_run, daemon=True)
    _fala_thread.start()

def falar_sync(texto: str):
    """Fala de forma síncrona (bloqueia até terminar)."""
    global _fala_proc
    orig, grave = _gerar_audio(texto)
    if not grave:
        print(f"[JARVIS] {texto}"); return
    try:
        _fala_proc = subprocess.Popen(["mpg123", "-q", grave])
        _fala_proc.wait()
    finally:
        for f in (orig, grave):
            if f and os.path.exists(f): os.remove(f)


# ═══════════════════════════════════════════════════════════
#  IA  (Gemini)
# ═══════════════════════════════════════════════════════════
_cliente_ia = None

try:
    _cliente_ia = genai.Client(api_key=GEMINI_KEY)
    log.info("Gemini inicializado.")
except Exception as e:
    log.warning(f"Gemini offline: {e}")

def limpar_historico():
    pass  # sem histórico — cada chamada é independente

def consultar_ia(prompt: str, curto=False, imagem_path: str = None) -> str:
    if not _cliente_ia:
        return "Gemini não configurado, senhor."
    try:
        modo     = "muito curto, máximo 2 frases" if curto else "detalhado mas objetivo"
        conteudo = f"Responda como o JARVIS, {modo}: {prompt}"
        resp = _cliente_ia.models.generate_content(
            model="gemini-2.5-flash",
            contents=conteudo
        )
        return resp.text.strip() if resp and resp.text else "Sem resposta."
    except Exception as e:
        log.error(f"IA erro: {e}")
        return "Falha na IA, senhor."


# ═══════════════════════════════════════════════════════════
#  AUTOMAÇÕES DO PC
# ═══════════════════════════════════════════════════════════

APPS = {
    "spotify":       ["spotify"],
    "code":          ["code"],
    "visual studio": ["code"],
    "firefox":       ["firefox"],
    "chrome":        ["google-chrome"],
    "terminal":      ["x-terminal-emulator"],
    "gerenciador":   ["nautilus"],
    "calculadora":   ["gnome-calculator"],
}

def abrir_app(comando: str) -> str:
    for nome, cmd in APPS.items():
        if nome in comando:
            subprocess.Popen(cmd)
            return f"Abrindo {nome}."
    return "Não reconheci o aplicativo, senhor."

def tirar_screenshot() -> str:
    ts   = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    dest = os.path.expanduser(f"~/screenshot_{ts}.png")
    try:
        if _PIL_OK:
            ImageGrab.grab().save(dest)
        else:
            subprocess.run(["scrot", dest], check=True, capture_output=True)
        return dest
    except Exception as e:
        log.error(f"screenshot: {e}"); return ""

def analisar_tela() -> str:
    if not _PIL_OK:
        return "Pillow não instalado para captura de tela."
    try:
        path = f"/tmp/screen_{int(time.time())}.png"
        ImageGrab.grab().save(path)
        resp = consultar_ia(
            "Descreva o que está na tela e identifique o que o usuário está fazendo.",
            imagem_path=path
        )
        os.remove(path)
        return resp
    except Exception as e:
        log.error(f"analisar_tela: {e}")
        return "Não consegui analisar a tela, senhor."

def digitar_texto(texto: str):
    if _PYAUTO_OK:
        pyautogui.typewrite(texto, interval=0.05)

def fechar_app(nome: str) -> bool:
    morto = False
    for proc in psutil.process_iter(["name", "pid"]):
        if nome.lower() in (proc.info["name"] or "").lower():
            try:
                proc.kill(); morto = True
            except Exception:
                pass
    return morto

def listar_processos() -> str:
    procs = sorted(
        psutil.process_iter(["name", "cpu_percent"]),
        key=lambda p: p.info["cpu_percent"] or 0,
        reverse=True
    )[:5]
    return ", ".join(f"{p.info['name']}({p.info['cpu_percent']:.0f}%)" for p in procs)

def mover_janela(direcao: str):
    try:
        r    = subprocess.run(["xdpyinfo"], capture_output=True, text=True)
        w, h = 1920, 1080
        for line in r.stdout.splitlines():
            if "dimensions" in line:
                m = re.findall(r"(\d+)x(\d+)", line)
                if m: w, h = int(m[0][0]), int(m[0][1])
        pos = {
            "esquerda":  f"0,0,0,{w//2},{h}",
            "direita":   f"0,{w//2},0,{w//2},{h}",
            "cima":      f"0,0,0,{w},{h//2}",
            "baixo":     f"0,0,{h//2},{w},{h//2}",
            "maximizar": f"0,0,0,{w},{h}",
        }.get(direcao)
        if pos:
            subprocess.run(["wmctrl", "-r", ":ACTIVE:", "-e", pos])
    except Exception as e:
        log.error(f"mover_janela: {e}")

def executar_script(caminho: str) -> str:
    try:
        r = subprocess.run(["bash", caminho], capture_output=True, text=True, timeout=15)
        return ((r.stdout or r.stderr or "Sem saída").strip())[:200]
    except Exception as e:
        return f"Erro: {e}"

def calcular(expr: str):
    try:
        if not all(c in "0123456789 +-*/().%^" for c in expr):
            return None
        return eval(expr.replace("^", "**"), {"__builtins__": {}})
    except Exception:
        return None


# ═══════════════════════════════════════════════════════════
#  INTEGRAÇÕES EXTERNAS
# ═══════════════════════════════════════════════════════════

def obter_clima(cidade: str) -> str:
    if not WEATHER_KEY:
        return consultar_ia(f"Clima em {cidade} hoje? Resumido.", curto=True)
    try:
        url = (
            f"https://api.openweathermap.org/data/2.5/weather"
            f"?q={urllib.parse.quote(cidade)}&appid={WEATHER_KEY}"
            f"&units=metric&lang=pt_br"
        )
        with urllib.request.urlopen(url, timeout=5) as r:
            d = json.loads(r.read())
        desc = d["weather"][0]["description"]
        temp = d["main"]["temp"]
        umid = d["main"]["humidity"]
        return f"Em {cidade}: {desc}, {temp:.0f} graus, umidade {umid}%."
    except Exception as e:
        log.error(f"clima: {e}")
        return "Não consegui obter o clima agora."

def discord_enviar(mensagem: str) -> str:
    if not (DISCORD_TOKEN and DISCORD_CHANNEL_ID):
        return "Discord não configurado no .env"
    try:
        url  = f"https://discord.com/api/v10/channels/{DISCORD_CHANNEL_ID}/messages"
        data = json.dumps({"content": mensagem}).encode()
        req  = urllib.request.Request(url, data=data, method="POST", headers={
            "Authorization": f"Bot {DISCORD_TOKEN}",
            "Content-Type":  "application/json",
        })
        urllib.request.urlopen(req, timeout=5)
        return "Mensagem enviada no Discord, senhor."
    except Exception as e:
        log.error(f"Discord: {e}")
        return "Falha ao enviar no Discord."

def notificar(titulo: str, corpo: str):
    try:
        subprocess.run(["notify-send", "-t", "5000", titulo, corpo], capture_output=True)
    except Exception:
        pass


# ═══════════════════════════════════════════════════════════
#  EVENTOS / CONTAGEM REGRESSIVA
# ═══════════════════════════════════════════════════════════

ARQUIVO_EVENTOS = os.path.expanduser("~/.jarvis_eventos.json")

MESES_PT = {
    "janeiro": 1, "fevereiro": 2, "março": 3, "marco": 3,
    "abril": 4, "maio": 5, "junho": 6, "julho": 7,
    "agosto": 8, "setembro": 9, "outubro": 10,
    "novembro": 11, "dezembro": 12,
}

def _ev_carregar() -> dict:
    if os.path.exists(ARQUIVO_EVENTOS):
        try:
            with open(ARQUIVO_EVENTOS, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            log.error(f"eventos carregar: {e}")
    return {}

def _ev_salvar(eventos: dict):
    try:
        with open(ARQUIVO_EVENTOS, "w", encoding="utf-8") as f:
            json.dump(eventos, f, ensure_ascii=False, indent=2)
    except Exception as e:
        log.error(f"eventos salvar: {e}")

def _ev_proxima_ocorrencia(dia: int, mes: int) -> tuple:
    """Para eventos anuais, retorna (dias_restantes, date) da próxima ocorrência."""
    hoje = datetime.date.today()
    for delta_ano in range(3):
        try:
            alvo = datetime.date(hoje.year + delta_ano, mes, dia)
            if alvo >= hoje:
                return (alvo - hoje).days, alvo
        except ValueError:
            continue
    return 999, hoje  # fallback

def ev_adicionar(nome: str, dia: int, mes: int, ano: int = None):
    """Adiciona ou atualiza evento. ano=None → repetição anual."""
    eventos = _ev_carregar()
    eventos[nome.lower()] = {"dia": dia, "mes": mes, "ano": ano}
    _ev_salvar(eventos)
    log.info(f"Evento adicionado: {nome} {dia}/{mes}/{ano}")

def ev_remover(nome: str) -> bool:
    eventos = _ev_carregar()
    chave = nome.lower()
    if chave in eventos:
        del eventos[chave]
        _ev_salvar(eventos)
        log.info(f"Evento removido: {nome}")
        return True
    return False

def ev_listar() -> list:
    """Retorna lista ordenada por proximidade com dias restantes calculados."""
    eventos = _ev_carregar()
    resultado = []
    hoje = datetime.date.today()
    for nome, info in eventos.items():
        dia, mes, ano = info["dia"], info["mes"], info.get("ano")
        if ano:
            try:
                alvo = datetime.date(ano, mes, dia)
                faltam = (alvo - hoje).days
                data_str = alvo.strftime("%d/%m/%Y")
            except ValueError:
                continue
        else:
            faltam, alvo = _ev_proxima_ocorrencia(dia, mes)
            data_str = alvo.strftime("%d/%m")
        resultado.append({"nome": nome, "faltam": faltam, "data": data_str})
    return sorted(resultado, key=lambda x: x["faltam"])

def ev_frase(nome: str, faltam: int) -> str:
    if faltam == 0:
        return f"Hoje é o dia de {nome}, senhor!"
    elif faltam == 1:
        return f"Falta apenas 1 dia para {nome}, senhor."
    elif faltam < 0:
        return f"{nome} já passou há {abs(faltam)} dias, senhor."
    else:
        return f"Faltam {faltam} dias para {nome}, senhor."

def ev_extrair_data_e_nome(comando: str):
    """
    Extrai (dia, mes, ano_ou_None, nome) de um comando de voz.
    Exemplos aceitos:
      'lembre dia 24 de junho como são joão'
      'adicionar evento dia 15 de julho de 2026 como viagem'
    """
    m_dia = re.search(r"\bdia\s+(\d{1,2})\b", comando)
    if not m_dia:
        return None
    dia = int(m_dia.group(1))

    mes = next((num for nome_m, num in MESES_PT.items() if nome_m in comando), None)
    if not mes:
        return None

    m_ano = re.search(r"\b(20\d{2}|19\d{2})\b", comando)
    ano = int(m_ano.group(1)) if m_ano else None

    m_nome = re.search(r"\bcomo\s+(.+)$", comando)
    if not m_nome:
        return None
    nome = m_nome.group(1).strip()

    return dia, mes, ano, nome

def ev_anunciar_iniciais(hud, falar_fn):
    """Anuncia todos os eventos cadastrados na inicialização."""
    eventos = ev_listar()
    if not eventos:
        return
    hud.safe_update("foco", "AGENDA", f"{len(eventos)} eventos")
    for ev in eventos:
        falar_fn(ev_frase(ev["nome"], ev["faltam"]))

def ev_buscar_por_voz(comando: str, eventos: list) -> dict:
    """Tenta encontrar o evento mais mencionado no comando."""
    for ev in eventos:
        if ev["nome"] in comando:
            return ev
    return None


# ═══════════════════════════════════════════════════════════
#  HUD  —  MARK XII
# ═══════════════════════════════════════════════════════════
class JarvisHUD(ctk.CTk):
    W  = 200
    H  = 470
    CX = 100
    CY = 98

    CORES = {
        False:     "#00BFFF",
        True:      "#FF3333",
        "ativo":   "#00FF88",
        "ia":      "#BF5FFF",
        "foco":    "#FF9900",
        "alerta":  "#FF3333",
        "discord": "#7289DA",
    }

    def __init__(self):
        super().__init__()
        self.geometry(f"{self.W}x{self.H}")
        self.overrideredirect(True)
        self.attributes("-topmost", True)
        self.attributes("-alpha", 0.93)
        self.configure(fg_color="#040c18")

        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        self.geometry(f"{self.W}x{self.H}+{sw - self.W - 18}+{sh - self.H - 55}")

        self.bind("<ButtonPress-1>",   self._start_move)
        self.bind("<B1-Motion>",       self._do_move)
        self.bind("<Double-Button-1>", self._toggle_expand)

        self.cv = ctk.CTkCanvas(self, width=self.W, height=self.H,
                                 bg="#040c18", highlightthickness=0)
        self.cv.place(x=0, y=0)

        # ── Referência ao tk para uso no painel ──
        import tkinter as tk
        self._tk = tk
        self._painel = None

        # Estado interno
        self._ang         = 0
        self._bat_suave   = 0.8
        self._cpu_hist    = deque([0.0] * 30, maxlen=30)
        self._net_hist    = deque([0.0] * 30, maxlen=30)
        self._net_bytes   = sum(psutil.net_io_counters()[:2])
        self._visivel     = True
        self._expandido   = True
        self._onda_fase   = 0.0
        self._onda_ativa  = False
        self._hist_cmds   = deque(maxlen=4)
        self._pulso_r     = 24.0
        self._pulso_dir   = 1
        self._grafico_its = []

        self._build_static()
        self._tick_anim()
        self._tick_metricas()

    # ── UI Estática ───────────────────────────────────────
    def _build_static(self):
        W, H, cx, cy = self.W, self.H, self.CX, self.CY

        # Cabeçalho
        self.cv.create_text(W//2, 14, text="J.A.R.V.I.S",
                             font=("Courier", 11, "bold"), fill="#00BFFF")
        self.cv.create_text(W//2, 27, text="MARK  XII  ·  ONLINE",
                             font=("Courier", 6), fill="#1a4060")
        self.cv.create_line(8, 35, W-8, 35, fill="#0a2030", width=1)

        # Arcos decorativos fixos
        for r, a0, ext, cor in [
            (74, 200, 140, "#0a1e2e"),
            (74, 20,  140, "#0a1e2e"),
            (56, 160, 220, "#061420"),
        ]:
            self.cv.create_arc(cx-r, cy-r, cx+r, cy+r,
                                start=a0, extent=ext, style="arc",
                                outline=cor, width=1)

        # Arcos animados
        self.a1 = self.cv.create_arc(cx-64, cy-64, cx+64, cy+64,
                                      start=0,   extent=65, style="arc",
                                      outline="#00BFFF", width=2)
        self.a2 = self.cv.create_arc(cx-64, cy-64, cx+64, cy+64,
                                      start=180, extent=65, style="arc",
                                      outline="#003850", width=2)
        self.a3 = self.cv.create_arc(cx-52, cy-52, cx+52, cy+52,
                                      start=90,  extent=45, style="arc",
                                      outline="#005070", width=1)

        # Anel e núcleo
        self.anel  = self.cv.create_oval(cx-44, cy-44, cx+44, cy+44,
                                          outline="#00BFFF", width=1)
        self.pulso = self.cv.create_oval(cx-24, cy-24, cx+24, cy+24,
                                          fill="#001828", outline="#00BFFF", width=2)
        self.letra = self.cv.create_text(cx, cy, text="AI",
                                          font=("Courier", 11, "bold"), fill="#00BFFF")

        # Marcações laterais
        for frac in [0.25, 0.5, 0.75]:
            y = int(cy - 72 + frac * 144)
            self.cv.create_line(6,    y, 18,   y, fill="#0a2030", width=1)
            self.cv.create_line(W-18, y, W-6,  y, fill="#0a2030", width=1)

        # Ondas de áudio (7 barras)
        y_onda = cy + 78
        self._onda_bs = []
        for i in range(7):
            x = cx - 24 + i * 8
            b = self.cv.create_rectangle(x, y_onda-3, x+5, y_onda+3,
                                          fill="#003850", outline="")
            self._onda_bs.append((b, x, y_onda))

        # Status
        self.cv.create_line(6, 192, W-6, 192, fill="#0a2030", width=1)
        self.tag_status = self.cv.create_text(W//2, 203, text="STANDBY",
                                               font=("Courier", 10, "bold"), fill="#00BFFF")
        self.tag_log    = self.cv.create_text(W//2, 216, text="Aguardando...",
                                               font=("Courier", 6), fill="#1a5060")
        self.cv.create_line(6, 224, W-6, 224, fill="#0a2030", width=1)

        # Métricas
        y0 = 232
        self.cv.create_text(10, y0, text="SYS", font=("Courier", 6, "bold"),
                             fill="#1a4060", anchor="w")
        self.tag_hora = self.cv.create_text(W-10, y0, text="--:--:--",
                                             font=("Courier", 6), fill="#00BFFF", anchor="e")

        self.bat_fill, self.bat_txt = self._criar_barra("PWR", y0+12, "#005080")
        self.cpu_fill, self.cpu_txt = self._criar_barra("CPU", y0+25, "#003a5c")
        self.ram_fill, self.ram_txt = self._criar_barra("RAM", y0+38, "#004a3a")
        self.net_fill, self.net_txt = self._criar_barra("NET", y0+51, "#004060")

        # Gráfico CPU
        self.cv.create_line(6, y0+66, W-6, y0+66, fill="#0a2030", width=1)
        self.cv.create_text(10, y0+74, text="CPU GRAPH",
                             font=("Courier", 5, "bold"), fill="#1a4060", anchor="w")
        self._gy0 = y0 + 84

        # Histórico de comandos
        self.cv.create_line(6, y0+90, W-6, y0+90, fill="#0a2030", width=1)
        self.cv.create_text(10, y0+98, text="HISTÓRICO",
                             font=("Courier", 5, "bold"), fill="#1a4060", anchor="w")
        self._hist_tags = [
            self.cv.create_text(12, y0+108+i*11, text="",
                                 font=("Courier", 5), fill="#0d3040", anchor="w")
            for i in range(4)
        ]

        # Rodapé
        self.cv.create_line(6, H-50, W-6, H-50, fill="#0a2030", width=1)
        self._btn_r = self.cv.create_rectangle(6, H-44, W-6, H-22, fill="#001828", outline="#00BFFF")
        self._btn_t = self.cv.create_text(W//2, H-33, text="⌨  DIGITAR", font=("Courier", 8, "bold"), fill="#00BFFF")
        for _t in (self._btn_r, self._btn_t):
            self.cv.tag_bind(_t, "<ButtonPress-1>",   lambda e: self._toggle_painel())
            self.cv.tag_bind(_t, "<Enter>", lambda e: self.cv.itemconfig(self._btn_r, fill="#003850"))
            self.cv.tag_bind(_t, "<Leave>", lambda e: self.cv.itemconfig(self._btn_r, fill="#001828"))
        self.cv.create_line(6, H-14, W-6, H-14, fill="#0a2030", width=1)
        self.cv.create_text(W//2, H-6, text="DBL-CLICK EXPANDIR  ·  DRAG MOVER",
                             font=("Courier", 5), fill="#0a2535")

        # Cantos decorativos
        L = 11
        for x1,y1,x2,y2 in [
            (0,0,L,0),(0,0,0,L),(W-L,0,W,0),(W,0,W,L),
            (0,H-L,0,H),(0,H,L,H),(W-L,H,W,H),(W,H-L,W,H),
        ]:
            self.cv.create_line(x1, y1, x2, y2, fill="#00BFFF", width=1)

    def _criar_barra(self, label: str, y: int, cor: str):
        W = self.W
        self.cv.create_text(10, y+6, text=label, font=("Courier", 6, "bold"),
                             fill="#1a4060", anchor="w")
        self.cv.create_rectangle(38, y, W-10, y+11, outline="#0a2030", fill="#040c18")
        fill = self.cv.create_rectangle(38, y, 38, y+11, outline="", fill=cor)
        txt  = self.cv.create_text(W-12, y+6, text="--",
                                    font=("Courier", 6), fill="#00BFFF", anchor="e")
        return fill, txt

    # ── Animação 30fps ────────────────────────────────────
    def _tick_anim(self):
        self._ang = (self._ang + 2) % 360
        a  = self._ang
        cx, cy = self.CX, self.CY

        self.cv.itemconfig(self.a1, start=a,     extent=65)
        self.cv.itemconfig(self.a2, start=a+180, extent=65)
        self.cv.itemconfig(self.a3, start=a+90,  extent=45)

        r = int(44 * (1 + 0.05 * math.sin(a * math.pi / 60)))
        self.cv.coords(self.anel, cx-r, cy-r, cx+r, cy+r)

        self._pulso_r += self._pulso_dir * 0.3
        if self._pulso_r > 28: self._pulso_dir = -1
        if self._pulso_r < 20: self._pulso_dir =  1
        pr = int(self._pulso_r)
        self.cv.coords(self.pulso, cx-pr, cy-pr, cx+pr, cy+pr)

        self._onda_fase += 0.25
        for i, (bid, bx, by) in enumerate(self._onda_bs):
            if self._onda_ativa:
                h   = int(3 + 10 * abs(math.sin(self._onda_fase + i * 0.9)))
                cor = "#00BFFF"
            else:
                h, cor = 3, "#003850"
            self.cv.coords(bid, bx, by-h, bx+5, by+h)
            self.cv.itemconfig(bid, fill=cor)

        self.after(33, self._tick_anim)

    # ── Métricas 1Hz ─────────────────────────────────────
    def _tick_metricas(self):
        W = self.W
        self.cv.itemconfig(self.tag_hora, text=datetime.datetime.now().strftime("%H:%M:%S"))

        # Bateria
        try:
            bat = psutil.sensors_battery()
            pct = (bat.percent / 100) if bat else 0.8
        except Exception:
            pct = 0.8
        self._bat_suave += (pct - self._bat_suave) * 0.15
        l = int((W - 48) * self._bat_suave)
        self.cv.coords(self.bat_fill, 38, 244, 38+l, 255)
        self.cv.itemconfig(self.bat_fill, fill="#00BFFF" if pct > 0.3 else "#FF4444")
        self.cv.itemconfig(self.bat_txt,  text=f"{int(pct*100)}%")

        # CPU
        cpu = psutil.cpu_percent(interval=None) / 100
        self._cpu_hist.append(cpu)
        l = int((W - 48) * cpu)
        self.cv.coords(self.cpu_fill, 38, 257, 38+l, 268)
        self.cv.itemconfig(self.cpu_fill, fill="#003a5c" if cpu < 0.7 else "#FF4444")
        self.cv.itemconfig(self.cpu_txt,  text=f"{int(cpu*100)}%")

        # RAM
        ram = psutil.virtual_memory().percent / 100
        l = int((W - 48) * ram)
        self.cv.coords(self.ram_fill, 38, 270, 38+l, 281)
        self.cv.itemconfig(self.ram_fill, fill="#004a3a" if ram < 0.8 else "#FF4444")
        self.cv.itemconfig(self.ram_txt,  text=f"{int(ram*100)}%")

        # Rede
        try:
            nb    = psutil.net_io_counters()
            total = nb.bytes_sent + nb.bytes_recv
            kbps  = max(0, total - self._net_bytes) / 1024
            self._net_bytes = total
        except Exception:
            kbps = 0
        self._net_hist.append(kbps)
        mx = max(max(self._net_hist), 1)
        l  = int((W - 48) * min(kbps / mx, 1.0))
        self.cv.coords(self.net_fill, 38, 283, 38+l, 294)
        self.cv.itemconfig(self.net_txt, text=f"{kbps:.0f}KB/s")

        # Gráfico CPU
        for it in self._grafico_its:
            self.cv.delete(it)
        self._grafico_its.clear()
        hist = list(self._cpu_hist)
        pw   = (W - 16) / max(len(hist), 1)
        pts  = [coord for i, v in enumerate(hist) for coord in (8 + i*pw, self._gy0 - int(v*10))]
        if len(pts) >= 4:
            it = self.cv.create_line(*pts, fill="#00BFFF", width=1, smooth=True)
            self._grafico_its.append(it)

        self.after(1000, self._tick_metricas)

    # ── API pública ───────────────────────────────────────
    def safe_update(self, cor, acao: str, msg: str = ""):
        self.after(0, lambda: self._update_ui(cor, acao, msg))

    def _update_ui(self, cor, acao: str, msg: str = ""):
        c = self.CORES.get(cor, str(cor))
        self.cv.itemconfig(self.a1,         outline=c)
        self.cv.itemconfig(self.anel,       outline=c)
        self.cv.itemconfig(self.pulso,      outline=c)
        self.cv.itemconfig(self.letra,      fill=c)
        self.cv.itemconfig(self.tag_status, text=acao.upper(), fill=c)
        if msg:
            self.cv.itemconfig(self.tag_log, text=msg[:34].upper())
        self._onda_ativa = cor in ("ativo", "ia", "discord", True)

    def push_historico(self, cmd: str):
        self._hist_cmds.appendleft(cmd[:34])
        cmds = list(self._hist_cmds)
        for i, tag in enumerate(self._hist_tags):
            txt    = f"› {cmds[i]}" if i < len(cmds) else ""
            brilho = "#1a7090" if i == 0 else "#0d3040"
            self.cv.itemconfig(tag, text=txt, fill=brilho)

    def toggle_visibilidade(self):
        self.after(0, self._toggle_vis)

    def _toggle_vis(self):
        self._visivel = not self._visivel
        if self._visivel:
            self.deiconify()
            self.attributes("-alpha", 0.93)
        else:
            self.attributes("-alpha", 0.0)
            self.withdraw()

    def _toggle_expand(self, _e=None):
        self._expandido = not self._expandido
        self.geometry(f"{self.W}x{self.H if self._expandido else 230}")

    def animacao_shutdown(self):
        self.safe_update(True, "OFFLINE", "Desativando núcleo...")
        def _fade():
            for _ in range(14):
                a = max(0.0, float(self.attributes("-alpha")) - 0.07)
                self.attributes("-alpha", a)
                self.update()
                time.sleep(0.05)
            os._exit(0)
        threading.Thread(target=_fade, daemon=True).start()

    def _start_move(self, e): self._dx, self._dy = e.x, e.y
    def _do_move(self, e):
        self.geometry(f"+{self.winfo_x()+(e.x-self._dx)}+{self.winfo_y()+(e.y-self._dy)}")

    def set_processador(self, fn):
        """Registra a função que processa comandos de texto."""
        self._processador = fn

    def _toggle_painel(self):
        if self._painel and self._painel.winfo_exists():
            self._painel.destroy()
            self._painel = None
            self.cv.itemconfig(self._btn_t, text="⌨  DIGITAR")
            self.cv.itemconfig(self._btn_r, fill="#001828", outline="#00BFFF")
            return
        tk = self._tk
        self.cv.itemconfig(self._btn_t, text="✕  FECHAR")
        self.cv.itemconfig(self._btn_r, fill="#1a0010", outline="#FF4444")

        hx, hy = self.winfo_x(), self.winfo_y()
        pw, ph = 360, self.H
        px = hx - pw - 8
        if px < 0:
            px = hx + self.W + 8

        p = tk.Toplevel()
        self._painel = p
        p.overrideredirect(True)
        p.attributes("-topmost", True)
        p.configure(bg="#00BFFF")
        p.geometry(f"{pw}x{ph}+{px}+{hy}")

        inner = tk.Frame(p, bg="#040c18")
        inner.pack(fill="both", expand=True, padx=1, pady=1)

        tk.Label(inner, text="J.A.R.V.I.S  ·  COMANDO",
                 bg="#040c18", fg="#00BFFF", font=("Courier", 9, "bold")).pack(pady=(10,4))
        tk.Frame(inner, bg="#0a2030", height=1).pack(fill="x", padx=8)

        self._hist_lb = tk.Listbox(inner, bg="#040c18", fg="#1a7090",
                                    selectbackground="#003850", selectforeground="#00BFFF",
                                    font=("Courier", 8), relief="flat", bd=0,
                                    highlightthickness=0, activestyle="none")
        self._hist_lb.pack(fill="both", expand=True, padx=8, pady=6)
        for cmd in reversed(list(self._hist_cmds)):
            self._hist_lb.insert("end", f"  › {cmd}")

        def _reusar(e):
            sel = self._hist_lb.curselection()
            if sel:
                self._pvar.set(self._hist_lb.get(sel[0]).strip().lstrip("› ").strip())
                self._pentry.focus_force()
        self._hist_lb.bind("<Double-Button-1>", _reusar)

        tk.Frame(inner, bg="#0a2030", height=1).pack(fill="x", padx=8)
        tk.Label(inner, text="Enter envia  ·  Esc fecha",
                 bg="#040c18", fg="#1a4060", font=("Courier", 7)).pack(pady=3)

        fr = tk.Frame(inner, bg="#040c18")
        fr.pack(fill="x", padx=8, pady=(0,8))

        self._pvar = tk.StringVar()
        self._pentry = tk.Entry(fr, textvariable=self._pvar,
                                 bg="#040c18", fg="#00BFFF",
                                 insertbackground="#00BFFF",
                                 selectbackground="#003850",
                                 relief="flat", highlightthickness=1,
                                 highlightcolor="#00BFFF",
                                 highlightbackground="#003050",
                                 font=("Courier", 11))
        self._pentry.pack(side="left", fill="x", expand=True, ipady=7)
        self._pentry.bind("<Return>", lambda e: self._enviar_texto())
        self._pentry.bind("<Escape>", lambda e: self._toggle_painel())

        tk.Button(fr, text="►", bg="#003050", fg="#00BFFF",
                  activebackground="#005070", relief="flat", bd=0,
                  font=("Courier", 11, "bold"), cursor="hand2",
                  command=self._enviar_texto).pack(side="left", padx=(4,0), ipady=7)

        p.update_idletasks()
        self._pentry.focus_force()

    def _enviar_texto(self):
        try:
            texto = self._pvar.get().strip().lower()
        except Exception:
            return
        if not texto:
            return
        self._pvar.set("")
        try:
            self._hist_lb.insert("end", f"  › {texto}")
            self._hist_lb.see("end")
        except Exception:
            pass
        self.push_historico(texto)
        self.safe_update("ativo", "TEXTO", texto[:32])
        log.info(f"TEXTO: {texto}")
        if hasattr(self, "_processador"):
            threading.Thread(target=self._processador, args=(texto,), daemon=True).start()


def registrar_atalho(hud: JarvisHUD):
    import signal
    signal.signal(signal.SIGUSR1, lambda s, f: hud.toggle_visibilidade())


# ═══════════════════════════════════════════════════════════
#  PROCESSADOR DE COMANDOS  (voz e texto compartilham a mesma lógica)
# ═══════════════════════════════════════════════════════════
def processar_comando(comando: str, hud: "JarvisHUD"):
    """Recebe um comando em texto puro (já em minúsculas) e executa a ação."""
    log.info(f"CMD: {comando}")
    hud.safe_update("ativo", "ATIVADO", comando[:32])
    hud.push_historico(re.sub(WAKE_WORD, "", comando).strip())

    # ── Parar fala ────────────────────────────────────
    if any(p in comando for p in ["para de falar", "cala boca", "silencio", "cancelar fala"]):
        parar_fala()

    # ── Eventos: cadastrar ────────────────────────────
    elif any(p in comando for p in ["lembre", "adicionar evento", "cadastrar evento", "salvar data"]):
        resultado = ev_extrair_data_e_nome(comando)
        if not resultado:
            hud.safe_update("foco", "EVENTO", "Aguardando data...")
            falar_sync("Pode falar a data e o nome do evento, senhor. Por exemplo: dia 24 de junho como São João.")
            detalhe = ouvir_pergunta(timeout=12, limite=40)
            resultado = ev_extrair_data_e_nome(detalhe) if detalhe else None
        if resultado:
            dia, mes, ano, nome = resultado
            ev_adicionar(nome, dia, mes, ano)
            ano_str = f" de {ano}" if ano else ""
            hud.safe_update("foco", "EVENTO", f"Salvo: {nome[:20]}")
            falar(f"Evento {nome} cadastrado para dia {dia} de {mes}{ano_str}, senhor.")
        else:
            falar("Não entendi a data ou o nome do evento, senhor. Tente novamente.")

    # ── Eventos: consultar contagem ───────────────────
    elif any(p in comando for p in ["quantos dias faltam", "quanto tempo falta", "quando é", "quando sera", "falta para"]):
        eventos = ev_listar()
        encontrado = ev_buscar_por_voz(comando, eventos)
        if encontrado:
            hud.safe_update("foco", "CONTAGEM", encontrado["nome"][:20])
            falar(ev_frase(encontrado["nome"], encontrado["faltam"]))
        elif eventos:
            hud.safe_update("foco", "AGENDA", "Todos os eventos")
            for ev in eventos[:5]:
                falar(ev_frase(ev["nome"], ev["faltam"]))
        else:
            falar("Não há eventos cadastrados, senhor. Diga: lembre dia X de mês como nome do evento.")

    # ── Eventos: listar ───────────────────────────────
    elif any(p in comando for p in ["listar eventos", "quais eventos", "minha agenda"]):
        eventos = ev_listar()
        if not eventos:
            falar("Agenda vazia, senhor.")
        else:
            qtd = len(eventos)
            falar(f"Você tem {qtd} evento{'s' if qtd > 1 else ''} cadastrado{'s' if qtd > 1 else ''}.")
            for ev in eventos:
                falar(ev_frase(ev["nome"], ev["faltam"]))
        hud.safe_update("foco", "AGENDA", f"{len(eventos)} eventos")

    # ── Eventos: remover ──────────────────────────────
    elif any(p in comando for p in ["remover evento", "deletar evento", "apagar evento"]):
        m = re.search(r"(?:remover|deletar|apagar)\s+evento\s+(.+)", comando)
        if m:
            nome_alvo = m.group(1).strip()
            if ev_remover(nome_alvo):
                hud.safe_update("foco", "AGENDA", "Evento removido")
                falar(f"Evento {nome_alvo} removido, senhor.")
            else:
                falar(f"Não encontrei nenhum evento chamado {nome_alvo}, senhor.")
        else:
            falar("Qual evento deseja remover, senhor?")

    # ── Fechar processo ───────────────────────────────
    elif "fechar" in comando or "matar processo" in comando:
        alvo = re.sub(r"jarvis|fechar|matar processo", "", comando).strip()
        ok   = fechar_app(alvo) if alvo else False
        falar("Processo encerrado." if ok else "Não encontrei o processo, senhor.")

    # ── Processos ativos ──────────────────────────────
    elif any(p in comando for p in ["processos", "cpu alta", "o que está rodando"]):
        hud.safe_update("ia", "PROCESSOS", "Top CPU...")
        falar(f"Processos com mais CPU: {listar_processos()}.")

    # ── Mover janela ──────────────────────────────────
    elif "mover janela" in comando or "janela para" in comando:
        for d in ["esquerda", "direita", "cima", "baixo", "maximizar"]:
            if d in comando:
                mover_janela(d)
                falar(f"Janela movida para {d}."); break
        else:
            falar("Para onde, senhor? Esquerda, direita, cima, baixo ou maximizar.")

    # ── Executar script ───────────────────────────────
    elif any(p in comando for p in ["executar script", "rodar script"]):
        hud.safe_update("ia", "SCRIPT", "Aguardando...")
        falar_sync("Qual o caminho do script, senhor?")
        caminho = ouvir_pergunta(timeout=8, limite=20)
        if caminho:
            falar(f"Script concluído. {executar_script(caminho)[:100]}")
        else:
            falar("Não captei o caminho.")

    # ── Analisar tela ─────────────────────────────────
    elif any(p in comando for p in ["analisar tela", "o que tem na tela", "descrever tela"]):
        hud.safe_update("ia", "VISÃO", "Processando...")
        falar_sync("Analisando a tela, um momento.")
        falar(analisar_tela())

    # ── Digitar texto ─────────────────────────────────
    elif any(p in comando for p in ["digitar", "escrever no teclado"]):
        txt = re.sub(r"jarvis|digitar|escrever no teclado", "", comando).strip()
        if txt:
            digitar_texto(txt); falar("Digitado.")
        else:
            falar_sync("O que deseja digitar?")
            resp = ouvir_pergunta(timeout=6, limite=15)
            if resp: digitar_texto(resp)

    # ── Screenshot ────────────────────────────────────
    elif any(p in comando for p in ["screenshot", "captura de tela", "printscreen"]):
        dest = tirar_screenshot()
        falar("Screenshot salvo." if dest else "Não consegui tirar o screenshot.")
        if dest: notificar("Screenshot", dest)

    # ── Discord ───────────────────────────────────────
    elif any(p in comando for p in ["mensagem no discord", "enviar discord"]):
        hud.safe_update("discord", "DISCORD", "Aguardando...")
        falar_sync("O que devo enviar, senhor?")
        msg = ouvir_pergunta(timeout=8, limite=30)
        falar(discord_enviar(msg) if msg else "Não captei a mensagem.")

    # ── Playerctl (música) ────────────────────────────
    elif any(p in comando for p in ["pausar", "parar musica"]):
        subprocess.run(["playerctl", "pause"], capture_output=True)
        falar("Música pausada.")

    elif any(p in comando for p in ["proxima", "pular"]):
        subprocess.run(["playerctl", "next"], capture_output=True)
        falar("Pulando faixa.")

    elif any(p in comando for p in ["voltar", "anterior"]):
        subprocess.run(["playerctl", "previous"], capture_output=True)
        falar("Faixa anterior.")

    # ── Volume ────────────────────────────────────────
    elif "volume" in comando:
        nums = [w for w in comando.split() if w.isdigit()]
        if nums:
            vol = min(int(nums[0]), 100)
            subprocess.run(["pactl", "set-sink-volume", "@DEFAULT_SINK@", f"{vol}%"],
                           capture_output=True)
            falar(f"Volume em {vol} por cento.")
        else:
            falar("Qual porcentagem, senhor?")

    # ── Abrir apps ────────────────────────────────────
    elif any(p in comando for p in ["abrir", "iniciar"]):
        hud.safe_update(False, "ABRINDO", "App")
        falar(abrir_app(comando))

    # ── Pesquisa web ──────────────────────────────────
    elif any(p in comando for p in ["pesquisa", "pesquisar", "buscar"]):
        termo = re.sub(r"jarvis|pesquisa[r]?|buscar", "", comando).strip()
        if termo:
            subprocess.Popen(["xdg-open",
                               f"https://www.google.com/search?q={urllib.parse.quote(termo)}"])
            falar(f"Pesquisando {termo}.")
        else:
            falar("O que pesquisar, senhor?")

    # ── Clima ─────────────────────────────────────────
    elif "clima" in comando or "tempo" in comando:
        cidade = re.sub(r"jarvis|clima|tempo|em", "", comando).strip() or "Aracaju"
        hud.safe_update("ia", "CLIMA", cidade[:20])
        falar(obter_clima(cidade))

    # ── Lembrete ──────────────────────────────────────
    elif "lembrete" in comando:
        nums = [int(w) for w in comando.split() if w.isdigit()]
        if nums:
            m = nums[0]
            falar(f"Lembrete em {m} minuto{'s' if m > 1 else ''}.")
            def _lembrete(mins=m):
                time.sleep(mins * 60)
                hud.safe_update("alerta", "LEMBRETE", f"{mins}min")
                notificar("JARVIS – Lembrete", f"{mins} minutos passaram.")
                falar("Senhor, seu lembrete chegou.")
            threading.Thread(target=_lembrete, daemon=True).start()
        else:
            falar("Em quantos minutos, senhor?")

    # ── Data e hora ───────────────────────────────────
    elif any(p in comando for p in ["horas", "que horas"]):
        falar(f"São {datetime.datetime.now().strftime('%H:%M')}, senhor.")

    elif "data" in comando or "dia" in comando:
        falar(f"Hoje é {datetime.datetime.now().strftime('%d de %B de %Y')}.")

    # ── Cálculo ───────────────────────────────────────
    elif any(p in comando for p in ["quanto e", "quanto é", "calcular", "calcula"]):
        expr = re.sub(r"jarvis|quanto [eé]|calcul[ae]r?", "", comando).replace("x", "*").strip()
        r    = calcular(expr)
        falar(f"Resultado: {r}." if r is not None
              else consultar_ia(f"Calcule: {expr}", curto=True))

    # ── Modo foco ─────────────────────────────────────
    elif any(p in comando for p in ["foco", "estudar", "produtividade"]):
        hud.safe_update("foco", "MODO FOCO", "Produtividade ativa")
        notificar("JARVIS", "Modo foco ativo.")
        falar("Protocolo de foco iniciado. Notificações silenciadas.")

    # ── Limpar memória da IA ──────────────────────────
    elif any(p in comando for p in ["limpar memoria", "nova conversa", "resetar ia"]):
        limpar_historico()
        falar("Memória de conversa limpa.")

    # ── Desligar ──────────────────────────────────────
    elif any(p in comando for p in ["desligar", "encerrar", "sair"]):
        falar_sync("Desligando sistemas Mark XII. Até logo, senhor.")
        hud.animacao_shutdown()

    # ── IA — modo pergunta ────────────────────────────
    elif any(p in comando for p in ["ativar ia", "modo ia", "tenho uma pergunta", "preciso de ajuda"]):
        hud.safe_update("ia", "IA ATIVA", "Aguardando...")
        falar_sync("Pode falar, senhor.")
        pergunta = ouvir_pergunta(timeout=10, limite=35)
        if pergunta:
            hud.safe_update("ia", "PROCESSANDO", "Gemini...")
            falar(consultar_ia(pergunta).replace("*", "").replace("#", ""))
        else:
            falar("Não captei sua pergunta.")

    # ── Fallback: resposta rápida da IA ──────────────
    else:
        hud.safe_update("ia", "CONSULTANDO", "Gemini...")
        clean = re.sub(WAKE_WORD, "", comando).strip()
        falar(consultar_ia(clean, curto=True).replace("*", "").replace("#", ""))

    time.sleep(0.4)
    hud.safe_update(False, "STANDBY", "Aguardando comando...")


# ═══════════════════════════════════════════════════════════
#  LOOP PRINCIPAL
# ═══════════════════════════════════════════════════════════
def rodar_jarvis(hud: JarvisHUD):
    time.sleep(1)
    hud.safe_update(False, "CALIBRANDO", "Ajustando microfone...")
    calibrar_microfone()

    agora    = datetime.datetime.now()
    saudacao = ("Bom dia"   if 5  <= agora.hour < 12
           else "Boa tarde" if 12 <= agora.hour < 18
           else "Boa noite")
    try:
        bat = int(psutil.sensors_battery().percent)
    except Exception:
        bat = "estável"

    hud.safe_update(False, "ONLINE", f"BAT {bat}%")
    falar_sync(f"{saudacao}, senhor. Sistemas Mark XII operacionais. Bateria em {bat} por cento.")
    notificar("JARVIS Online", f"{saudacao}, senhor.")

    # ── Anuncia eventos cadastrados ao iniciar ──
    ev_anunciar_iniciais(hud, falar_sync)

    while True:
        hud.safe_update(False, "ESCUTANDO")
        comando = ouvir(timeout=4, limite=10)
        if not comando or not contem_wake_word(comando):
            continue
        processar_comando(comando, hud)


# ═══════════════════════════════════════════════════════════
#  ENTRY POINT
# ═══════════════════════════════════════════════════════════
if __name__ == "__main__":
    app = JarvisHUD()
    registrar_atalho(app)
    app.set_processador(lambda cmd: processar_comando(cmd, app))
    threading.Thread(target=rodar_jarvis, args=(app,), daemon=True).start()
    app.mainloop()