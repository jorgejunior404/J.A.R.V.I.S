"""
jarvis_core.py — MARK X
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Recursos implementados:
  ✓ Wake word offline (Vosk) ou fallback Google STT
  ✓ Memória de conversa (histórico enviado ao Gemini)
  ✓ Classificação de intenção via IA (sem if/elif infinito)
  ✓ Streaming da resposta — fala frase por frase
  ✓ Config externa via config.yaml
  ✓ Sistema de plugins desacoplado
  ✓ Log persistente em arquivo
  ✓ Modo silencioso (HUD sem voz)

Dependências:
    pip install customtkinter google-genai SpeechRecognition \
                pyyaml psutil requests pyaudio --break-system-packages
    # Opcional (wake word offline):
    pip install vosk sounddevice --break-system-packages
"""

import os
import sys
import time
import json
import queue
import logging
import threading
import datetime
import subprocess

import yaml
import customtkinter as ctk
import speech_recognition as sr

try:
    from google import genai
    GENAI_OK = True
except ImportError:
    GENAI_OK = False
    print("[AVISO] google-genai não instalado.")

from jarvis_wakeword import criar_detector
from jarvis_plugins import PLUGINS, plugin_sistema


# ═══════════════════════════════════════════════════════════
#  CONFIG
# ═══════════════════════════════════════════════════════════

def carregar_config(caminho: str = "config.yaml") -> dict:
    with open(caminho, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)

CFG = carregar_config()

# ─── Logger ─────────────────────────────────────────────────
log_cfg = CFG.get("log", {})
logging.basicConfig(
    level=getattr(logging, log_cfg.get("nivel", "INFO")),
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        *(
            [logging.FileHandler(log_cfg.get("arquivo", "jarvis.log"), encoding="utf-8")]
            if log_cfg.get("ativo", True) else []
        ),
    ],
)
log = logging.getLogger("JARVIS")

# ─── Gemini ──────────────────────────────────────────────────
chave_api = CFG["api"]["gemini_key"]
cliente_ia = None
if GENAI_OK and chave_api and chave_api != "SUA_CHAVE_AQUI":
    try:
        cliente_ia = genai.Client(api_key=chave_api)
        log.info("Gemini conectado.")
    except Exception as e:
        log.warning(f"Gemini falhou: {e}")

# ─── Estado compartilhado ────────────────────────────────────
estado = {
    "silencioso": CFG["voz"].get("silencioso", False),
    "historico": [],          # lista de {"role": "user"|"model", "parts": [{"text": "..."}]}
    "ocupado": False,         # True enquanto processa um comando
}


# ═══════════════════════════════════════════════════════════
#  HUD
# ═══════════════════════════════════════════════════════════

class JarvisHUD(ctk.CTk):
    def __init__(self):
        super().__init__()
        h = CFG["hud"]
        self.geometry(f"{h['largura']}x{h['altura']}")
        self.overrideredirect(True)
        self.attributes("-topmost", True)
        self.attributes("-alpha", h["opacidade"])
        self.configure(fg_color="#1a1a1a")

        self.bind("<ButtonPress-1>", self.start_move)
        self.bind("<B1-Motion>",     self.do_move)

        self.canvas = ctk.CTkCanvas(self, width=140, height=140,
                                    bg="#1a1a1a", highlightthickness=0)
        self.canvas.pack(pady=8)

        self.ring = self.canvas.create_oval(5,  5,  135, 135, outline=h["cor_primaria"], width=3)
        self.glow = self.canvas.create_oval(25, 25, 115, 115, outline="#004444",         width=2)
        self.core = self.canvas.create_oval(50, 50, 90,  90,  fill="#002222",            outline=h["cor_primaria"])

        self.lbl_status = ctk.CTkLabel(self, text="MARK X",
                                       font=(h["fonte_titulo"], 10, "bold"),
                                       text_color=h["cor_primaria"])
        self.lbl_status.pack()

        self.lbl_log = ctk.CTkLabel(self, text="INICIANDO",
                                    font=("Consolas", 8),
                                    text_color="#55FFFF")
        self.lbl_log.pack()

        self.barra_bat = ctk.CTkProgressBar(self, width=120, height=4,
                                            progress_color=h["cor_primaria"])
        self.barra_bat.set(0)
        self.barra_bat.pack(pady=6)

        self.lbl_modo = ctk.CTkLabel(self, text="",
                                     font=("Consolas", 7),
                                     text_color="#446666")
        self.lbl_modo.pack()

    def start_move(self, e): self.x = e.x; self.y = e.y
    def do_move(self, e):
        self.geometry(f"+{self.winfo_x()+(e.x-self.x)}+{self.winfo_y()+(e.y-self.y)}")

    def safe_update(self, cor, acao, log_txt=""):
        self.after(0, lambda: self._update(cor, acao, log_txt))

    def _update(self, cor, acao, log_txt):
        if cor is True:  cor = CFG["hud"]["cor_erro"]
        if cor is False: cor = CFG["hud"]["cor_primaria"]
        self.canvas.itemconfig(self.ring, outline=cor)
        self.canvas.itemconfig(self.core, outline=cor)
        self.lbl_status.configure(text=acao.upper(), text_color=cor)
        if log_txt:
            self.lbl_log.configure(text=log_txt[:22].upper())
        modo = "[ SEM VOZ ]" if estado["silencioso"] else ""
        self.lbl_modo.configure(text=modo)

    def animacao_shutdown(self):
        self.safe_update(CFG["hud"]["cor_erro"], "OFFLINE", "Encerrando...")
        for _ in range(10):
            a = self.attributes("-alpha") - 0.08
            if a > 0: self.attributes("-alpha", a)
            self.canvas.scale("all", 75, 75, 0.9, 0.9)
            self.update()
            time.sleep(0.05)
        os._exit(0)


# ═══════════════════════════════════════════════════════════
#  TTS  (edge-tts + mpg123)
# ═══════════════════════════════════════════════════════════

_fila_tts: queue.Queue = queue.Queue()
_worker_tts_iniciado = False

def _worker_tts():
    """Thread única que consome a fila de falas em ordem."""
    while True:
        texto = _fila_tts.get()
        if texto is None:
            break
        _sintetizar(texto)
        _fila_tts.task_done()

def _sintetizar(texto: str):
    arquivo = f"/tmp/jarvis_{int(time.time()*1000)}.mp3"
    voz = CFG["voz"]["voz_id"]
    try:
        subprocess.run(
            ["edge-tts", "--voice", voz, "--text", texto, "--write-media", arquivo],
            check=True, capture_output=True, timeout=15
        )
        subprocess.run(["mpg123", "-q", arquivo], check=True, timeout=30)
    except Exception as e:
        log.warning(f"TTS falhou: {e} | Texto: {texto[:60]}")
    finally:
        if os.path.exists(arquivo):
            os.remove(arquivo)

def falar(texto: str):
    """Enfileira fala. Retorna imediatamente."""
    if estado["silencioso"]:
        log.info(f"[SILENCIOSO] {texto}")
        return
    log.info(f"JARVIS fala: {texto[:80]}")
    _fila_tts.put(texto)

def falar_sync(texto: str):
    """Fala e aguarda terminar (para shutdown e inicialização)."""
    if estado["silencioso"]:
        log.info(f"[SILENCIOSO] {texto}")
        return
    _fila_tts.put(texto)
    _fila_tts.join()


# ═══════════════════════════════════════════════════════════
#  STT  (speech_recognition — só para capturar o comando)
# ═══════════════════════════════════════════════════════════

_rec = sr.Recognizer()
_rec.dynamic_energy_threshold = True
_mic = sr.Microphone()

def calibrar():
    log.info("Calibrando microfone...")
    with _mic as f:
        _rec.adjust_for_ambient_noise(f, duration=1.5)
    log.info(f"Threshold: {_rec.energy_threshold:.0f}")

def ouvir_comando(timeout=5, limite=7) -> str:
    """Captura o comando após wake word ser detectada."""
    try:
        with _mic as f:
            _rec.adjust_for_ambient_noise(f, duration=0.3)
            audio = _rec.listen(f, timeout=timeout, phrase_time_limit=limite)
        texto = _rec.recognize_google(audio, language="pt-BR").lower()
        log.info(f"Comando ouvido: '{texto}'")
        return texto
    except sr.WaitTimeoutError:
        return ""
    except sr.UnknownValueError:
        return ""
    except Exception as e:
        log.warning(f"STT erro: {e}")
        return ""

def ouvir_pergunta() -> str:
    mic_cfg = CFG.get("mic", {})
    timeout = mic_cfg.get("timeout_pergunta", 10)
    limite  = mic_cfg.get("limite_pergunta", 30)
    try:
        with _mic as f:
            _rec.adjust_for_ambient_noise(f, duration=0.4)
            _rec.pause_threshold = 2.0
            audio = _rec.listen(f, timeout=timeout, phrase_time_limit=limite)
        _rec.pause_threshold = 0.8
        texto = _rec.recognize_google(audio, language="pt-BR").lower()
        log.info(f"Pergunta: '{texto}'")
        return texto
    except Exception:
        return ""


# ═══════════════════════════════════════════════════════════
#  IA  (Gemini — intenção + resposta)
# ═══════════════════════════════════════════════════════════

def classificar_intencao(comando: str) -> dict:
    """
    Pede ao Gemini para classificar o comando em JSON.
    Retorna {"intencao": "...", "confianca": 0-1}
    Intenções possíveis: media, apps, foco, clima, hora, data,
                         bateria, desligar, silencio, voz, ia, desconhecido
    """
    if not cliente_ia:
        return {"intencao": "desconhecido", "confianca": 0}

    prompt = f"""Classifique o comando de voz abaixo em uma das intenções.
Responda APENAS com JSON válido, sem markdown, sem explicação.

Intenções disponíveis:
- media       → pausar, tocar, pular, voltar música
- apps        → abrir spotify, firefox, vscode, telegram etc
- foco        → modo foco, pomodoro, estudar
- clima       → tempo, temperatura, vai chover
- hora        → que horas são
- data        → que dia é hoje
- bateria     → nível de bateria
- ia          → perguntas, explicações, consultas à IA
- desligar    → encerrar, desligar o sistema
- silencio    → modo silencioso, calar
- voz         → ativar voz novamente
- desconhecido → nenhuma das anteriores

Comando: "{comando}"

Resposta (somente JSON):
{{"intencao": "<nome>", "confianca": <0.0 a 1.0>}}"""

    try:
        res = cliente_ia.models.generate_content(
            model=CFG["api"]["gemini_model"],
            contents=prompt
        )
        texto = res.text.strip().replace("```json", "").replace("```", "").strip()
        return json.loads(texto)
    except Exception as e:
        log.warning(f"Classificação falhou: {e}")
        return {"intencao": "desconhecido", "confianca": 0}


def responder_ia(pergunta: str, hud: JarvisHUD):
    """
    Consulta o Gemini com histórico de conversa.
    Usa streaming: fala frase por frase assim que chegam.
    """
    if not cliente_ia:
        falar("A chave de API não está configurada, senhor.")
        return

    # Adiciona ao histórico
    max_hist = CFG["api"].get("historico_max", 10)
    estado["historico"].append({"role": "user", "parts": [{"text": pergunta}]})
    if len(estado["historico"]) > max_hist * 2:
        estado["historico"] = estado["historico"][-(max_hist * 2):]

    hud.safe_update(CFG["hud"]["cor_ia"], "PROCESSANDO", "Gemini...")
    log.info(f"Enviando ao Gemini com {len(estado['historico'])} msgs no histórico")

    sistema = (
        "Você é JARVIS, assistente de IA do Tony Stark. "
        "Responda sempre em português brasileiro. "
        "Seja direto, inteligente e levemente formal. "
        "Nunca use markdown, asteriscos ou formatação especial — apenas texto simples."
    )

    try:
        # ── Streaming: recebe chunks e vai falando por sentenças ──
        buffer = ""
        terminadores = {".", "!", "?", "..."}

        stream = cliente_ia.models.generate_content_stream(
            model=CFG["api"]["gemini_model"],
            contents=estado["historico"],
            config={"system_instruction": sistema,
                    "max_output_tokens": CFG["api"].get("max_tokens", 1024)}
        )

        resposta_completa = ""
        for chunk in stream:
            if not chunk.text:
                continue
            buffer += chunk.text
            resposta_completa += chunk.text

            # Fala quando encontra fim de frase
            while True:
                pos = -1
                for term in terminadores:
                    idx = buffer.find(term)
                    if idx != -1 and (pos == -1 or idx < pos):
                        pos = idx + len(term)

                if pos == -1:
                    break

                frase = buffer[:pos].strip()
                buffer = buffer[pos:].strip()

                if len(frase) > 3:
                    falar(frase)

        # Fala o que sobrou no buffer
        if buffer.strip() and len(buffer.strip()) > 3:
            falar(buffer.strip())

        # Adiciona resposta ao histórico
        if resposta_completa:
            estado["historico"].append({
                "role": "model",
                "parts": [{"text": resposta_completa}]
            })
            log.debug(f"Resposta IA: {resposta_completa[:120]}...")

    except Exception as e:
        log.error(f"Erro Gemini stream: {e}")
        falar("Houve uma falha na conexão com o Gemini, senhor.")


# ═══════════════════════════════════════════════════════════
#  CORE — processa um comando após wake word
# ═══════════════════════════════════════════════════════════

def processar_comando(hud: JarvisHUD, detector):
    """Chamado pelo detector de wake word quando 'jarvis' é detectado."""

    if estado["ocupado"]:
        log.debug("Já ocupado — ignorando wake word duplicada")
        detector.reativar()
        return

    estado["ocupado"] = True
    hud.safe_update(CFG["hud"]["cor_ok"], "ATIVADO", "Ouvindo...")

    # Pequena pausa para eco da própria fala do Jarvis não confundir
    time.sleep(0.3)

    comando = ouvir_comando(
        timeout=CFG["mic"].get("timeout_standby", 5),
        limite=CFG["mic"].get("limite_frase", 7)
    )

    if not comando:
        falar("Não captei o comando, senhor.")
        hud.safe_update(CFG["hud"]["cor_primaria"], "STANDBY", "Aguardando")
        estado["ocupado"] = False
        detector.reativar()
        return

    log.info(f"Processando: '{comando}'")
    hud.safe_update(CFG["hud"]["cor_ok"], "PENSANDO", comando[:18])

    # ── 1. Plugin sistema (tem assinatura diferente) ──────────
    if plugin_sistema(comando, CFG, hud, falar, falar_sync, estado):
        estado["ocupado"] = False
        detector.reativar()
        return

    # ── 2. Classificação por IA ───────────────────────────────
    intencao_info = classificar_intencao(comando)
    intencao = intencao_info.get("intencao", "desconhecido")
    log.info(f"Intenção: {intencao} (confiança: {intencao_info.get('confianca', 0):.2f})")

    # ── 3. Despacha para plugin correspondente ────────────────
    tratado = False

    mapa_intencao_plugin = {
        "media":   "plugin_media",
        "apps":    "plugin_apps",
        "foco":    "plugin_foco",
        "clima":   "plugin_clima",
        "hora":    "plugin_hora_data",
        "data":    "plugin_hora_data",
        "bateria": "plugin_bateria",
    }

    if intencao in mapa_intencao_plugin:
        for plugin_fn in PLUGINS:
            if plugin_fn.__name__ == mapa_intencao_plugin[intencao]:
                tratado = plugin_fn(comando, CFG, hud, falar)
                break

    # ── 4. Intenção IA → pergunta longa ──────────────────────
    if not tratado and intencao == "ia":
        hud.safe_update(CFG["hud"]["cor_ia"], "IA ATIVA", "Fale sua pergunta")
        falar("Pode perguntar, senhor.")
        time.sleep(0.4)
        pergunta = ouvir_pergunta()
        if pergunta:
            responder_ia(pergunta, hud)
        else:
            falar("Não captei sua pergunta, senhor.")
        tratado = True

    # ── 5. Fallback: resposta rápida da IA ───────────────────
    if not tratado:
        hud.safe_update(CFG["hud"]["cor_ia"], "CONSULTANDO", "Gemini...")
        responder_ia(comando, hud)

    # ── Volta ao standby ─────────────────────────────────────
    time.sleep(0.5)
    hud.safe_update(CFG["hud"]["cor_primaria"], "STANDBY", "Aguardando")
    estado["ocupado"] = False
    detector.reativar()


# ═══════════════════════════════════════════════════════════
#  INICIALIZAÇÃO
# ═══════════════════════════════════════════════════════════

def iniciar(hud: JarvisHUD):
    time.sleep(1)
 
    # Worker TTS em background
    global _worker_tts_iniciado
    if not _worker_tts_iniciado:
        t = threading.Thread(target=_worker_tts, daemon=True, name="TTS-Worker")
        t.start()
        _worker_tts_iniciado = True
 
    # Calibração
    hud.safe_update(CFG["hud"]["cor_primaria"], "CALIBRANDO", "Mic...")
    calibrar()
 
    # Bateria
    try:
        import psutil
        bat = psutil.sensors_battery()
        nivel = int(bat.percent) if bat else 100
        hud.barra_bat.set(nivel / 100)
    except Exception:
        nivel = "estável"
 
    # Saudação
    agora = datetime.datetime.now()
    hora  = agora.hour
    sauda = "Bom dia" if 5 <= hora < 12 else "Boa tarde" if hora < 18 else "Boa noite"
    hud.safe_update(CFG["hud"]["cor_ok"], "ONLINE", f"BAT: {nivel}%")
    falar_sync(f"{sauda}, senhor. Sistemas operacionais. Bateria em {nivel} por cento. "
               f"Aguardando palavra de ativação.")
 
    # ── CORREÇÃO: cria o detector uma única vez com um container mutável ──
    # O container resolve o problema de referência circular (detector precisa
    # de si mesmo dentro do callback, mas ainda não existe quando o callback
    # é definido).
    ref = {}   # container mutável — preenchido logo abaixo
 
    def ao_detectar():
        threading.Thread(
            target=processar_comando,
            args=(hud, ref["detector"]),   # usa ref, não closure direta
            daemon=True,
            name="Cmd-Handler"
        ).start()
 
    detector = criar_detector(cfg=CFG, on_detectado=ao_detectar)
    ref["detector"] = detector   # agora o callback consegue acessá-lo
 
    ok = detector.iniciar()
 
    if not ok:
        log.error("Wake word não iniciou. Verifique dependências.")
        falar("Falha ao iniciar detector de voz, senhor.")
        return
 
    hud.safe_update(CFG["hud"]["cor_primaria"], "STANDBY", "Aguardando")
    log.info(f"Sistema pronto. Wake word: '{CFG['wake_word']['palavra']}'")

if __name__ == "__main__":
    app = JarvisHUD()
    t = threading.Thread(target=iniciar, args=(app,), daemon=True, name="Jarvis-Init")
    t.start()
    app.mainloop()
