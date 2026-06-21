"""
╔══════════════════════════════════════════════════════════╗
║         J.A.R.V.I.S  —  MARK XIII  ·  CORE              ║
║  Mais humano · Proativo · NLU flexível · Com humor       ║
╚══════════════════════════════════════════════════════════╝

Execute: python jarvis_hud.py (com venv ativa)

Variáveis no .env:
    GEMINI_API_KEY          = sua_chave
    VOZ                     = pt-BR-AntonioNeural   (fallback edge-tts)
    VOZ_KOKORO              = pm_alex               (voz kokoro: pm_alex, pm_santa, pm_pedro)
    PITCH                   = 0.91                  (só usado no fallback edge-tts)
    WAKE_WORD               = jarvis
    WEATHER_API_KEY         = chave_openweathermap
    DISCORD_TOKEN           = token_do_bot
    DISCORD_CHANNEL_ID      = id_do_canal
    EMAIL_USER              = seu@email.com
    EMAIL_PASS              = sua_senha
    EMAIL_IMAP              = imap.gmail.com
    TELA_MONITOR_INTERVALO  = 90    (segundos entre análises, 0=desativa)
    TELA_MONITOR_ATIVO      = true
    JARVIS_NOME_USUARIO     = senhor  (como o JARVIS te chama)
    JARVIS_HUMOR            = true    (respostas com personalidade)
"""

# ═══════════════════════════════════════════════════════════
#  IMPORTS
# ═══════════════════════════════════════════════════════════
import os, re, json, math, time, datetime, random
import logging, subprocess, threading, urllib.request, urllib.parse
import imaplib, email, base64, hashlib
from email.header import decode_header
from collections import deque
from difflib import SequenceMatcher

import psutil
import speech_recognition as sr
from dotenv import load_dotenv
from google import genai

try:
    import pyautogui
    pyautogui.FAILSAFE = False
    _PYAUTO_OK = True
except ImportError:
    _PYAUTO_OK = False

try:
    from PIL import ImageGrab, Image
    _PIL_OK = True
except ImportError:
    _PIL_OK = False

# ── WhatsApp (opcional) ──────────────────────────────────
try:
    from jarvis_whatsapp import (
        enviar_whatsapp,
        enviar_briefing_whatsapp,
        iniciar_briefing_whatsapp,
    )
    _WA_OK = True
except ImportError:
    _WA_OK = False

# ── Kokoro TTS (opcional) ────────────────────────────────
try:
    from kokoro import KPipeline
    import soundfile as sf
    import numpy as np
    _kokoro_pipe = KPipeline(lang_code="p")
    _KOKORO_OK   = True
except Exception:
    _KOKORO_OK   = False
    _kokoro_pipe = None
    sf           = None
    np           = None

# ── Sistema de Plugins ───────────────────────────────────
import jarvis_insights  # noqa: F401  (registra os comandos via plugin)
import jarvis_rubberduck   # noqa: F401  (registra os comandos via plugin)
from jarvis_plugins import processar_via_plugins
from jarvis_plugins.jarvis_context import JarvisContext


# ═══════════════════════════════════════════════════════════
#  CONFIGURAÇÃO
# ═══════════════════════════════════════════════════════════
load_dotenv()

GEMINI_KEY             = os.getenv("GEMINI_API_KEY", "")
VOZ                    = os.getenv("VOZ",        "pt-BR-AntonioNeural")
VOZ_KOKORO             = os.getenv("VOZ_KOKORO", "pm_alex")
PITCH                  = os.getenv("PITCH",      "0.91")
RATE                   = os.getenv("RATE",       "-5%")
WAKE_WORD              = os.getenv("WAKE_WORD",  "jarvis")
WEATHER_KEY            = os.getenv("WEATHER_API_KEY", "")
DISCORD_TOKEN          = os.getenv("DISCORD_TOKEN", "")
DISCORD_CHANNEL_ID     = int(os.getenv("DISCORD_CHANNEL_ID", "0") or "0")
EMAIL_USER             = os.getenv("EMAIL_USER", "")
EMAIL_PASS             = os.getenv("EMAIL_PASS", "")
EMAIL_IMAP             = os.getenv("EMAIL_IMAP", "imap.gmail.com")
TELA_MONITOR_INTERVALO = int(os.getenv("TELA_MONITOR_INTERVALO", "90"))
TELA_MONITOR_ATIVO     = os.getenv("TELA_MONITOR_ATIVO", "true").lower() == "true"
USUARIO                = os.getenv("JARVIS_NOME_USUARIO", "senhor")
HUMOR_ATIVO            = os.getenv("JARVIS_HUMOR", "true").lower() == "true"

logging.basicConfig(
    filename="jarvis.log", level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
log = logging.getLogger("JARVIS")


# ═══════════════════════════════════════════════════════════
#  PERSONALIDADE
# ═══════════════════════════════════════════════════════════
_REACOES = {
    "erro_codigo": [
        f"Ah, um erro. A vida de desenvolvedor, {USUARIO}.",
        f"Clássico. Linha errada, mundo errado.",
        f"Esse erro e eu já nos conhecemos bem. Quer que eu ajude a resolver?",
        f"Interessante escolha de bug, {USUARIO}. Posso sugerir uma solução?",
    ],
    "youtube": [
        f"Pausa produtiva ou procrastinação estratégica, {USUARIO}?",
        f"YouTube detectado. Relógio também ligado, por precaução.",
        f"Conteúdo técnico ou entretenimento puro? Curiosidade profissional minha.",
    ],
    "terminal": [
        f"Terminal aberto. Vou ficar de olho por se precisar de algo.",
        f"Ah, o ambiente natural do desenvolvedor. Me avise se travar.",
        f"Terminal ativo. Se der um erro bizarro, é só chamar.",
    ],
    "spotify": [
        f"Boa escolha de trilha sonora, {USUARIO}.",
        f"Música ativada. Produtividade tende a subir agora.",
        f"Spotify detectado. Posso pausar se você precisar focar.",
    ],
    "github": [
        f"Commitando ou só olhando o trabalho dos outros, {USUARIO}?",
        f"GitHub aberto. Boas contribuições por aí?",
    ],
    "inatividade": [
        f"Tudo bem por aí, {USUARIO}? Posso fazer algo enquanto você pensa.",
        f"Silêncio estratégico ou pausa para o café? Estou disponível.",
        f"Aqui no standby, {USUARIO}. Me chame quando precisar.",
    ],
    "cpu_alta": [
        f"CPU acima de 85%, {USUARIO}. Algo pesado está rodando — quer verificar?",
        f"O processador está trabalhando mais que eu. Posso verificar o que está consumindo?",
    ],
    "bateria_baixa": [
        f"Bateria em 15%, {USUARIO}. Seria prudente conectar o carregador.",
        f"Alerta de bateria. Já vi esse filme antes — nem sempre termina bem.",
    ],
}

def _frase_reacao(tipo: str) -> str:
    opcoes = _REACOES.get(tipo, [])
    if not opcoes:
        return ""
    return random.choice(opcoes)

_CONFIRMACOES = [
    f"Feito, {USUARIO}.",
    f"Considerado.",
    f"Imediatamente.",
    f"Executando.",
    f"Pronto.",
    f"Claro, {USUARIO}.",
    f"Já providencio.",
]

def _confirmar() -> str:
    return random.choice(_CONFIRMACOES)

_SYSTEM_PROMPT = (
    f"Você é J.A.R.V.I.S, assistente pessoal inteligente e sofisticado. "
    f"Responda sempre em português brasileiro, de forma direta, clara e com personalidade. "
    f"Seja conciso mas completo. Chame o usuário de {USUARIO}. "
    f"Evite markdown, asteriscos ou formatação especial nas respostas — fale como se estivesse conversando."
)

# ── Canal de chat broadcast ──────────────────────────────
_chat_callbacks: list = []

def registrar_chat_callback(fn):
    """Registra uma função fn(role, texto) para receber mensagens do chat."""
    if fn not in _chat_callbacks:
        _chat_callbacks.append(fn)

def _broadcast_chat(role: str, texto: str):
    """Envia texto para todos os callbacks registrados (web HUD, etc)."""
    for fn in _chat_callbacks:
        try:
            fn(role, texto)
        except Exception as e:
            log.warning(f"chat_callback erro: {e}")


# ═══════════════════════════════════════════════════════════
#  MICROFONE
# ═══════════════════════════════════════════════════════════
rec = sr.Recognizer()
rec.pause_threshold          = 0.8   # FIX: era 0.6, aumentado para frases mais longas
rec.non_speaking_duration    = 0.5   # FIX: era 0.4
rec.dynamic_energy_threshold = False  # FIX: DESATIVADO — impedia detecção do wake word
rec.energy_threshold         = 300   # FIX: valor fixo estável (ajuste conforme ambiente)
mic = sr.Microphone()

# Lock para evitar dois ouvir() simultâneos (TTS vs microfone)
_mic_lock = threading.Lock()

def calibrar_microfone():
    """Calibra o threshold de energia uma única vez na inicialização."""
    with _mic_lock:
        with mic as f:
            rec.adjust_for_ambient_noise(f, duration=2.0)
        # FIX: trava o threshold após calibração para não subir indefinidamente
        rec.dynamic_energy_threshold = False
    log.info(f"Mic calibrado. Threshold fixado em {rec.energy_threshold:.0f}")

def ouvir(timeout=5, limite=12) -> str:
    """Escuta o microfone e retorna o texto reconhecido (lowercase)."""
    # FIX: não tenta capturar áudio se o TTS ainda está tocando
    if _fala_proc and _fala_proc.poll() is None:
        return ""
    if not _mic_lock.acquire(blocking=False):
        return ""
    try:
        with mic as f:
            audio = rec.listen(f, timeout=timeout, phrase_time_limit=limite)
        return rec.recognize_google(audio, language="pt-BR").lower()
    except (sr.WaitTimeoutError, sr.UnknownValueError):
        return ""
    except Exception as e:
        log.error(f"ouvir: {e}"); return ""
    finally:
        _mic_lock.release()

def ouvir_pergunta(timeout=10, limite=30) -> str:
    """Escuta uma pergunta/resposta do usuário (bloqueante)."""
    if not _mic_lock.acquire(blocking=True, timeout=15):
        return ""
    try:
        with mic as f:
            rec.adjust_for_ambient_noise(f, duration=0.3)
            audio = rec.listen(f, timeout=timeout, phrase_time_limit=limite)
        return rec.recognize_google(audio, language="pt-BR").lower()
    except (sr.WaitTimeoutError, sr.UnknownValueError):
        return ""
    except Exception as e:
        log.error(f"ouvir_pergunta: {e}"); return ""
    finally:
        _mic_lock.release()

def contem_wake_word(texto: str, limiar=0.72) -> bool:
    palavras = texto.split()
    for w in palavras:
        if SequenceMatcher(None, WAKE_WORD, w).ratio() > limiar:
            return True
    if WAKE_WORD in texto:
        return True
    return False


# ═══════════════════════════════════════════════════════════
#  TTS  — Kokoro (principal) + edge-tts (fallback)
# ═══════════════════════════════════════════════════════════
_fala_thread = None
_fala_proc   = None

# FIX: fila de TTS para evitar falas sobrepostas
_fala_queue: deque = deque()
_fala_queue_lock   = threading.Lock()
_fala_queue_event  = threading.Event()
_fala_worker_ativo = False


def _gerar_audio_kokoro(texto: str, dest: str) -> str | None:
    """Gera áudio via Kokoro TTS local. Retorna path .wav ou None."""
    try:
        chunks = []
        for _, _, chunk in _kokoro_pipe(texto, voice=VOZ_KOKORO, speed=0.95):
            chunks.append(chunk)
        if not chunks:
            return None
        sf.write(dest, np.concatenate(chunks), 24000)
        return dest
    except Exception as e:
        log.error(f"Kokoro TTS: {e}")
        return None


def _gerar_audio_edge(texto: str, dest: str) -> str | None:
    """Gera áudio via edge-tts + ffmpeg. Retorna path .mp3 ou None."""
    try:
        p1 = subprocess.Popen(
            ["edge-tts", "--voice", VOZ, "--rate", RATE,
             "--text", texto, "--write-media", "/dev/stdout"],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL
        )
        p2 = subprocess.Popen(
            ["ffmpeg", "-y", "-i", "pipe:0",
             "-af", f"rubberband=pitch={PITCH}", dest],
            stdin=p1.stdout,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
        p1.stdout.close()
        p2.wait(); p1.wait()
        return dest if os.path.exists(dest) else None
    except Exception as e:
        log.error(f"TTS edge: {e}")
        return None


def _gerar_audio(texto: str) -> str | None:
    """
    Tenta Kokoro primeiro. Se falhar, cai no edge-tts.
    Retorna o caminho do arquivo gerado (.wav ou .mp3).
    """
    ts = int(time.time() * 1000)
    if _KOKORO_OK:
        dest = f"/tmp/jv_{ts}.wav"
        resultado = _gerar_audio_kokoro(texto, dest)
        if resultado:
            return resultado
        log.warning("Kokoro falhou, tentando edge-tts...")
    # Fallback
    dest = f"/tmp/jv_{ts}.mp3"
    return _gerar_audio_edge(texto, dest)


def _player_para(path: str) -> list:
    """Escolhe o player certo pelo formato do arquivo."""
    return ["aplay", "-D", "pulse"] if path.endswith(".wav") else ["mpg123", "-o", "pulse"]


def parar_fala():
    global _fala_proc
    if _fala_proc and _fala_proc.poll() is None:
        _fala_proc.terminate()
    # FIX: também limpa a fila ao parar
    with _fala_queue_lock:
        _fala_queue.clear()


def _reproduzir_audio(texto: str, sincrono: bool = False):
    """
    Núcleo de reprodução — gera e toca o áudio.
    Chamado pelo worker da fila (assíncrono) ou diretamente (síncrono).
    """
    global _fala_proc
    grave = _gerar_audio(texto)
    if not grave:
        print(f"[JARVIS] {texto}"); return
    try:
        _fala_proc = subprocess.Popen(_player_para(grave) + ["-q", grave])
        _fala_proc.wait()
    finally:
        if grave and os.path.exists(grave):
            os.remove(grave)


def _fila_worker():
    """
    FIX: Worker único que consome a fila de TTS em série,
    garantindo que nenhuma fala sobreponha outra.
    """
    global _fala_worker_ativo
    _fala_worker_ativo = True
    while True:
        _fala_queue_event.wait()
        _fala_queue_event.clear()
        while True:
            with _fala_queue_lock:
                if not _fala_queue:
                    break
                texto = _fala_queue.popleft()
            _reproduzir_audio(texto)
    # nunca chega aqui, mas por segurança:
    _fala_worker_ativo = False


# Inicia o worker de fila na importação do módulo
_fila_thread = threading.Thread(target=_fila_worker, daemon=True, name="TTSWorker")
_fila_thread.start()


def falar(texto: str):
    """Enfileira fala assíncrona e transmite para o chat."""
    _broadcast_chat("jarvis", texto)
    with _fala_queue_lock:
        _fala_queue.append(texto)
    _fala_queue_event.set()


def falar_sync(texto: str):
    """
    Fala síncrona: enfileira e bloqueia até esta frase ser reproduzida.
    FIX: usa o mesmo worker, evitando sobreposição com chamadas assíncronas.
    """
    _broadcast_chat("jarvis", texto)
    done = threading.Event()

    def _item_com_callback():
        _reproduzir_audio(texto)
        done.set()

    # Injeta diretamente no worker via flag especial na fila
    # Simples: só enfileira e aguarda esvaziamento desta entrada
    with _fala_queue_lock:
        _fala_queue.append(("__SYNC__", texto, done))
    _fala_queue_event.set()
    done.wait(timeout=60)


def _fila_worker():  # noqa: F811 — redefine com suporte a sync
    """
    Worker de fila com suporte a itens síncronos.
    Itens normais: str
    Itens síncronos: ("__SYNC__", texto, Event)
    """
    while True:
        _fala_queue_event.wait()
        _fala_queue_event.clear()
        while True:
            with _fala_queue_lock:
                if not _fala_queue:
                    break
                item = _fala_queue.popleft()
            if isinstance(item, tuple) and item[0] == "__SYNC__":
                _, texto, done_event = item
                _reproduzir_audio(texto)
                done_event.set()
            else:
                _reproduzir_audio(item)


# Reinicia o worker com a versão final
_fila_thread = threading.Thread(target=_fila_worker, daemon=True, name="TTSWorker")
_fila_thread.start()


# ═══════════════════════════════════════════════════════════
#  IA  (Groq) — com memória de conversa e personalidade
# ═══════════════════════════════════════════════════════════
_cliente_ia  = None
_historico = deque(maxlen=12)

try:
    from groq import Groq
    _cliente_ia = Groq(api_key=os.getenv("GROQ_API_KEY", ""))
    log.info("Groq inicializado.")
except Exception as e:
    _cliente_ia = None
    log.warning(f"Groq offline: {e}")

def limpar_historico():
    _historico.clear()

def consultar_ia(prompt: str, curto=False, sistema: str = None) -> str:
    if not _cliente_ia:
        return f"IA não configurada, {USUARIO}."
    sys_text = sistema or _SYSTEM_PROMPT
    if curto:
        sys_text += "\nREGRA: resposta em no máximo 2 frases curtas."

    msgs = [{"role": "system", "content": sys_text}]
    for entrada, saida in _historico:
        msgs.append({"role": "user",      "content": entrada})
        msgs.append({"role": "assistant", "content": saida})
    msgs.append({"role": "user", "content": prompt})

    modelos = ["llama-3.3-70b-versatile", "llama3-8b-8192", "gemma2-9b-it"]
    for modelo in modelos:
        for tentativa in range(2):
            try:
                resp = _cliente_ia.chat.completions.create(
                    model=modelo,
                    messages=msgs,
                    max_tokens=500,
                )
                texto = resp.choices[0].message.content.strip()
                if texto:
                    _historico.append((prompt, texto))
                    return texto
            except Exception as e:
                log.warning(f"Groq [{modelo}] tentativa {tentativa+1}: {e}")
                time.sleep(1)
    return f"Todos os modelos indisponíveis agora, {USUARIO}."

def consultar_ia_com_imagem(prompt: str, imagem_path: str) -> str:
    if not _cliente_ia:
        return f"IA não configurada, {USUARIO}."
    if not os.path.exists(imagem_path):
        return "Imagem não encontrada."
    try:
        import base64
        with open(imagem_path, "rb") as f:
            img_b64 = base64.b64encode(f.read()).decode()
        resp = _cliente_ia.chat.completions.create(
            model="meta-llama/llama-4-scout-17b-16e-instruct",
            messages=[{
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {
                        "url": f"data:image/png;base64,{img_b64}"
                    }},
                ],
            }],
            max_tokens=500,
        )
        return resp.choices[0].message.content.strip()
    except Exception as e:
        log.error(f"Groq visão: {e}")
        return f"Falha na análise visual, {USUARIO}."


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
    "discord":       ["discord"],
    "telegram":      ["telegram-desktop"],
    "slack":         ["slack"],
    "obs":           ["obs"],
    "gimp":          ["gimp"],
    "vlc":           ["vlc"],
}

def abrir_app(comando: str) -> str:
    for nome, cmd in APPS.items():
        if nome in comando:
            subprocess.Popen(cmd)
            reacao = _frase_reacao(nome) if nome in _REACOES else f"Abrindo {nome}."
            return reacao or f"Abrindo {nome}."
    return f"Não reconheci o aplicativo, {USUARIO}. Pode falar o nome exato?"

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
        key=lambda p: p.info["cpu_percent"] or 0, reverse=True)[:5]
    return ", ".join(
        f"{p.info['name']}({p.info['cpu_percent']:.0f}%)" for p in procs)

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
        limpo = re.sub(r"[^0-9 +\-*/().%^]", "", expr)
        if not limpo.strip():
            return None
        return eval(limpo.replace("^", "**"), {"__builtins__": {}})
    except Exception:
        return None


# ═══════════════════════════════════════════════════════════
#  INTEGRAÇÕES EXTERNAS
# ═══════════════════════════════════════════════════════════
def obter_clima(cidade: str) -> str:
    if not WEATHER_KEY:
        return consultar_ia(
            f"Como está o clima em {cidade} hoje? Responda em 1 frase.", curto=True)
    try:
        url = (f"https://api.openweathermap.org/data/2.5/weather"
               f"?q={urllib.parse.quote(cidade)}&appid={WEATHER_KEY}"
               f"&units=metric&lang=pt_br")
        with urllib.request.urlopen(url, timeout=5) as r:
            d = json.loads(r.read())
        desc = d["weather"][0]["description"]
        temp = d["main"]["temp"]
        umid = d["main"]["humidity"]
        return f"Em {cidade}: {desc}, {temp:.0f} graus, umidade {umid}%."
    except Exception as e:
        log.error(f"clima: {e}")
        return f"Não consegui o clima agora, {USUARIO}."

def discord_enviar(mensagem: str) -> str:
    if not (DISCORD_TOKEN and DISCORD_CHANNEL_ID):
        return "Discord não configurado no .env."
    try:
        url  = f"https://discord.com/api/v10/channels/{DISCORD_CHANNEL_ID}/messages"
        data = json.dumps({"content": mensagem}).encode()
        req  = urllib.request.Request(url, data=data, method="POST", headers={
            "Authorization": f"Bot {DISCORD_TOKEN}",
            "Content-Type":  "application/json",
        })
        urllib.request.urlopen(req, timeout=5)
        return f"Enviado no Discord, {USUARIO}."
    except Exception as e:
        log.error(f"Discord: {e}")
        return "Falha ao enviar no Discord."

def notificar(titulo: str, corpo: str):
    try:
        subprocess.run(["notify-send", "-t", "6000", titulo, corpo], capture_output=True)
    except Exception:
        pass


# ═══════════════════════════════════════════════════════════
#  E-MAIL  (IMAP)
# ═══════════════════════════════════════════════════════════
def _decodificar_header(valor: str) -> str:
    partes = decode_header(valor or "")
    resultado = []
    for parte, charset in partes:
        if isinstance(parte, bytes):
            resultado.append(parte.decode(charset or "utf-8", errors="replace"))
        else:
            resultado.append(parte)
    return " ".join(resultado)

def ler_emails(quantidade: int = 5, pasta: str = "INBOX",
               filtro_remetente: str = None) -> str:
    if not EMAIL_USER or not EMAIL_PASS:
        return f"E-mail não configurado no .env, {USUARIO}."
    try:
        imap = imaplib.IMAP4_SSL(EMAIL_IMAP, timeout=10)
        imap.login(EMAIL_USER, EMAIL_PASS)
        imap.select(pasta)
        if filtro_remetente:
            status, dados = imap.search(None, f'FROM "{filtro_remetente}"')
        else:
            status, dados = imap.search(None, "ALL")
        if status != "OK" or not dados[0]:
            imap.logout()
            return (f"Nada de {filtro_remetente} por aqui, {USUARIO}."
                    if filtro_remetente else
                    f"Caixa de entrada vazia, {USUARIO}.")
        ids      = dados[0].split()
        recentes = ids[-quantidade:][::-1]
        linhas   = []
        for uid in recentes:
            status, msg_data = imap.fetch(uid, "(BODY.PEEK[HEADER.FIELDS (FROM SUBJECT DATE)])")
            if status != "OK": continue
            msg       = email.message_from_bytes(msg_data[0][1])
            remetente = _decodificar_header(msg.get("From", "desconhecido"))
            assunto   = _decodificar_header(msg.get("Subject", "sem assunto"))
            nome_email = re.sub(r"\s*<[^>]+>", "", remetente).strip() or remetente
            linhas.append(f"{nome_email}: {assunto}")
        imap.logout()
        if not linhas:
            return f"Não consegui ler os e-mails agora, {USUARIO}."
        intro = (f"Encontrei {len(linhas)} e-mail(s) de {filtro_remetente}. "
                 if filtro_remetente else
                 f"Aqui estão os {len(linhas)} e-mails mais recentes. ")
        return intro + ". ".join(linhas) + "."
    except imaplib.IMAP4.error as e:
        log.error(f"IMAP auth: {e}")
        return f"Falha de autenticação no e-mail, {USUARIO}. Credenciais no .env corretas?"
    except Exception as e:
        log.error(f"ler_emails: {e}")
        return f"Não consegui acessar o e-mail agora, {USUARIO}."


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
    hoje = datetime.date.today()
    for delta_ano in range(3):
        try:
            alvo = datetime.date(hoje.year + delta_ano, mes, dia)
            if alvo >= hoje:
                return (alvo - hoje).days, alvo
        except ValueError:
            continue
    return 999, hoje

def ev_adicionar(nome: str, dia: int, mes: int, ano: int = None):
    eventos = _ev_carregar()
    eventos[nome.lower()] = {"dia": dia, "mes": mes, "ano": ano}
    _ev_salvar(eventos)

def ev_remover(nome: str) -> bool:
    eventos = _ev_carregar()
    if nome.lower() in eventos:
        del eventos[nome.lower()]
        _ev_salvar(eventos)
        return True
    return False

def ev_listar() -> list:
    eventos = _ev_carregar()
    resultado = []
    hoje = datetime.date.today()
    for nome, info in eventos.items():
        dia, mes, ano = info["dia"], info["mes"], info.get("ano")
        if ano:
            try:
                alvo     = datetime.date(ano, mes, dia)
                faltam   = (alvo - hoje).days
                data_str = alvo.strftime("%d/%m/%Y")
            except ValueError:
                continue
        else:
            faltam, alvo = _ev_proxima_ocorrencia(dia, mes)
            data_str     = alvo.strftime("%d/%m")
        resultado.append({"nome": nome, "faltam": faltam, "data": data_str})
    return sorted(resultado, key=lambda x: x["faltam"])

def ev_frase(nome: str, faltam: int) -> str:
    if faltam == 0:
        return random.choice([
            f"Hoje é o dia de {nome}, {USUARIO}!",
            f"{nome.title()} é hoje! Não esquece.",
        ])
    elif faltam == 1:
        return f"Amanhã é {nome}, {USUARIO}. Aviso dado."
    elif faltam < 0:
        return f"{nome.title()} já passou faz {abs(faltam)} dias."
    elif faltam <= 7:
        return f"{nome.title()} em {faltam} dias — semana que vem basicamente."
    else:
        return f"Faltam {faltam} dias para {nome}."

def ev_extrair_data_e_nome(comando: str):
    m_dia = re.search(r"\bdia\s+(\d{1,2})\b", comando)
    if not m_dia: return None
    dia = int(m_dia.group(1))
    mes = next((n for nm, n in MESES_PT.items() if nm in comando), None)
    if not mes: return None
    m_ano  = re.search(r"\b(20\d{2}|19\d{2})\b", comando)
    ano    = int(m_ano.group(1)) if m_ano else None
    m_nome = re.search(r"\bcomo\s+(.+)$", comando)
    if not m_nome: return None
    return dia, mes, ano, m_nome.group(1).strip()

def ev_anunciar_iniciais(hud, falar_fn):
    """
    FIX: usa falar_fn (que já é falar_sync) — a serialização é garantida
    pelo worker de fila, não precisamos de sleep aqui.
    """
    eventos = ev_listar()
    if not eventos:
        return
    hud.safe_update("foco", "AGENDA", f"{len(eventos)} eventos")
    urgentes = [e for e in eventos if 0 <= e["faltam"] <= 7]
    if urgentes:
        falar_fn(f"Agenda: {len(urgentes)} evento(s) na próxima semana.")
        for ev in urgentes:
            falar_fn(ev_frase(ev["nome"], ev["faltam"]))
        demais = [e for e in eventos if e["faltam"] > 7]
        if demais:
            falar_fn(f"Além disso, {len(demais)} evento(s) mais pra frente na agenda.")
    else:
        falar_fn(f"Agenda: {len(eventos)} evento(s) cadastrado(s).")
        for ev in eventos:
            falar_fn(ev_frase(ev["nome"], ev["faltam"]))

def ev_buscar_por_voz(comando: str, eventos: list) -> dict:
    for ev in eventos:
        if ev["nome"] in comando:
            return ev
    return None


# ═══════════════════════════════════════════════════════════
#  GUIA PASSO A PASSO
# ═══════════════════════════════════════════════════════════
_tarefa_ativa = None

def iniciar_guia(titulo: str, descricao_tarefa: str, hud) -> str:
    global _tarefa_ativa
    prompt = (
        f"O usuário quer: '{descricao_tarefa}'. "
        f"Crie um guia de no máximo 6 passos numerados, em português natural. "
        f"Cada passo deve ser uma instrução clara em 1 frase. "
        f"Responda APENAS os passos numerados, sem introdução."
    )
    guia_texto = consultar_ia(prompt, curto=False)
    passos = re.findall(r"\d+[\.\)]\s*(.+)", guia_texto)
    if not passos:
        passos = [l.strip() for l in guia_texto.split("\n") if l.strip()]
    if not passos:
        return f"Não consegui montar um guia para essa tarefa, {USUARIO}."
    _tarefa_ativa = {
        "titulo":      titulo or descricao_tarefa[:30],
        "passos":      passos,
        "passo_atual": 0,
        "contexto":    descricao_tarefa,
    }
    hud.safe_update("foco", "GUIA ATIVO", _tarefa_ativa["titulo"][:20])
    total = len(passos)
    falar_sync(f"Montei um guia de {total} passos para {titulo or 'essa tarefa'}.")
    _falar_proximo_passo(hud)
    return ""

def _falar_proximo_passo(hud):
    global _tarefa_ativa
    if not _tarefa_ativa:
        return
    i      = _tarefa_ativa["passo_atual"]
    passos = _tarefa_ativa["passos"]
    total  = len(passos)
    if i >= total:
        _tarefa_ativa = None
        hud.safe_update(False, "STANDBY", "Tarefa concluída")
        falar(f"Guia concluído, {USUARIO}. Todos os passos executados.")
        return
    passo = passos[i]
    hud.safe_update("foco", f"PASSO {i+1}/{total}", passo[:25])
    falar_sync(f"Passo {i+1} de {total}: {passo}")
    falar_sync("Me avise quando terminar ou se precisar de ajuda.")

def avancar_passo(hud):
    global _tarefa_ativa
    if not _tarefa_ativa:
        falar(f"Não há guia ativo no momento, {USUARIO}.")
        return
    _tarefa_ativa["passo_atual"] += 1
    _falar_proximo_passo(hud)

def cancelar_guia(hud):
    global _tarefa_ativa
    _tarefa_ativa = None
    hud.safe_update(False, "STANDBY", "Guia cancelado")
    falar(f"Guia cancelado, {USUARIO}.")

def status_guia() -> str:
    if not _tarefa_ativa:
        return ""
    i     = _tarefa_ativa["passo_atual"]
    total = len(_tarefa_ativa["passos"])
    return f"Passo {i+1} de {total}: {_tarefa_ativa['passos'][i]}"


# ═══════════════════════════════════════════════════════════
#  ANÁLISE CONTEXTUAL DE TELA
# ═══════════════════════════════════════════════════════════
_monitor_ativo    = False
_ultimo_hash      = ""
_ultima_analise   = 0.0
_sugestoes_cache  = []
_ultimo_contexto  = {}
_app_em_foco      = ""
_ultimo_erro_visto = ""

_PROMPT_EXTRACAO = """
Você é um sistema de visão computacional. Analise esta captura de tela e extraia APENAS fatos
concretos e observáveis. Leia textos, nomes de arquivos, URLs, erros, nomes de funções visíveis.

Responda SOMENTE em JSON válido, sem markdown.

{
  "app": "nome exato do aplicativo em foco",
  "aba_titulo": "título exato da aba ou janela",
  "url": "URL visível ou null",
  "arquivo_aberto": "nome e extensão do arquivo ou null",
  "linguagem": "linguagem de programação detectada ou null",
  "erro_visivel": "mensagem de erro exata se houver ou null",
  "texto_selecionado": "texto selecionado ou null",
  "ultimo_comando": "último comando no terminal se visível ou null",
  "conteudo_resumo": "resumo em 1 frase — específico, com nomes reais",
  "intencao_provavel": "o que o usuário provavelmente está fazendo — específico"
}
"""

_PROMPT_SUGESTOES = f"""Você é o J.A.R.V.I.S com personalidade — inteligente, direto e levemente bem-humorado.
Com base no contexto real abaixo, gere 3 sugestões ESPECÍFICAS para o que o usuário está fazendo AGORA.

CONTEXTO REAL DA TELA:
{{contexto}}

REGRAS:
1. Mencione detalhes REAIS (nome do arquivo, erro específico, URL, função, pacote).
2. Se há erro visível → sugestão 1 DEVE ser sobre aquele erro.
3. frase_jarvis deve ter personalidade — pode ter um toque de humor leve se o contexto permitir.
4. comando_voz em português natural que o JARVIS já sabe executar.

JSON válido, sem markdown:
{{
  "contexto": "frase curta e específica (máx 60 chars)",
  "sugestoes": [
    {{
      "titulo": "ação específica com detalhe real (máx 45 chars)",
      "descricao": "o que exatamente será feito — nomes reais (máx 90 chars)",
      "comando_voz": "comando natural em português"
    }}
  ],
  "frase_jarvis": "frase com personalidade mencionando o que está na tela (máx 120 chars)"
}}"""

def _hash_tela(img) -> str:
    try:
        small = img.resize((128, 72))
        return hashlib.md5(small.tobytes()).hexdigest()
    except Exception:
        return ""

def _capturar_tela_para_analise() -> tuple:
    if not _PIL_OK:
        return None, ""
    try:
        img  = ImageGrab.grab()
        h    = _hash_tela(img)
        path = f"/tmp/jarvis_ctx_{int(time.time())}.png"
        w, ht = img.size
        if w > 1280:
            nova_altura = int(ht * 1280 / w)
            img = img.resize((1280, nova_altura), Image.LANCZOS)
        img.save(path, optimize=True)
        return path, h
    except Exception as e:
        log.error(f"capturar_tela: {e}")
        return None, ""

def _parsear_json(raw: str) -> dict:
    limpo = re.sub(r"```(?:json)?", "", raw).strip().rstrip("`").strip()
    m = re.search(r"\{[\s\S]+\}", limpo)
    if m:
        limpo = m.group(0)
    return json.loads(limpo)

def _extrair_contexto_da_tela(path: str) -> dict:
    raw = consultar_ia_com_imagem(_PROMPT_EXTRACAO, path)
    try:
        return _parsear_json(raw)
    except Exception as e:
        log.error(f"Extração de contexto falhou: {e}")
        return {"app": "desconhecido", "conteudo_resumo": "tela atual",
                "intencao_provavel": "uso geral"}

def _gerar_sugestoes_do_contexto(ctx: dict) -> dict:
    linhas = []
    mapa = {
        "app": "Aplicativo", "aba_titulo": "Título da janela",
        "url": "URL", "arquivo_aberto": "Arquivo aberto",
        "linguagem": "Linguagem", "erro_visivel": "ERRO VISÍVEL",
        "texto_selecionado": "Texto selecionado",
        "ultimo_comando": "Último comando terminal",
        "conteudo_resumo": "O que está na tela",
        "intencao_provavel": "Intenção provável",
    }
    for chave, label in mapa.items():
        val = ctx.get(chave)
        if val and val != "null" and val is not None:
            linhas.append(f"- {label}: {val}")
    contexto_str = "\n".join(linhas) if linhas else "- Tela não identificada"
    prompt = _PROMPT_SUGESTOES.replace("{contexto}", contexto_str)
    raw    = consultar_ia(prompt, curto=False)
    try:
        return _parsear_json(raw)
    except Exception as e:
        log.error(f"Geração de sugestões falhou: {e}")
        return {"erro": "Não consegui gerar sugestões desta vez."}

def analisar_tela_contextual(forcar=False) -> dict:
    global _ultimo_hash, _ultima_analise, _sugestoes_cache, _ultimo_contexto
    path, novo_hash = _capturar_tela_para_analise()
    if not path:
        return {"erro": "Pillow não disponível ou falha na captura."}
    if (not forcar and novo_hash == _ultimo_hash and _sugestoes_cache):
        os.remove(path)
        return {
            "cache":        True,
            "contexto":     _ultimo_contexto.get("contexto", "última análise"),
            "sugestoes":    _sugestoes_cache,
            "frase_jarvis": f"Mesma tela de antes, {USUARIO}. Sugestões ainda válidas.",
        }
    ctx   = _extrair_contexto_da_tela(path)
    os.remove(path)
    dados = _gerar_sugestoes_do_contexto(ctx)
    if "erro" not in dados:
        _ultimo_hash     = novo_hash
        _ultima_analise  = time.time()
        _sugestoes_cache = dados.get("sugestoes", [])
        _ultimo_contexto = dados
    return dados

def falar_sugestoes(dados: dict, hud=None):
    if "erro" in dados:
        falar(f"Não consegui analisar a tela agora. {dados['erro'][:60]}")
        return
    sugestoes = dados.get("sugestoes", [])
    frase     = dados.get("frase_jarvis", f"Analisei a tela, {USUARIO}.")
    if hud:
        hud.safe_update("ia", "ANÁLISE", dados.get("contexto", "tela")[:20])
    falar_sync(frase)
    if not sugestoes:
        falar(f"Não vi sugestões óbvias para esse contexto, {USUARIO}.")
        return
    falar_sync(f"Tenho {len(sugestoes)} sugestão{'ões' if len(sugestoes) > 1 else ''}.")
    for i, s in enumerate(sugestoes, 1):
        falar_sync(f"Opção {i}: {s.get('titulo', '')}. {s.get('descricao', '')}")
    falar_sync("Qual delas quer executar? Diga o número ou o comando.")
    resposta = ouvir_pergunta(timeout=8, limite=10)
    if not resposta:
        falar(f"Certo, fico por aqui, {USUARIO}.")
        return
    _executar_sugestao_por_voz(resposta, sugestoes, hud)

def _executar_sugestao_por_voz(resposta: str, sugestoes: list, hud=None):
    mapa_nums = {
        "um": 1, "uma": 1, "primeiro": 1, "1": 1,
        "dois": 2, "duas": 2, "segundo": 2, "2": 2,
        "três": 3, "tres": 3, "terceiro": 3, "3": 3,
    }
    for palavra, idx in mapa_nums.items():
        if palavra in resposta:
            if idx <= len(sugestoes):
                s   = sugestoes[idx - 1]
                cmd = s.get("comando_voz", "")
                falar_sync(f"Executando: {s.get('titulo', cmd)}.")
                if hud and cmd:
                    processar_comando(cmd, hud)
                return
    falar_sync(f"Entendido.")
    if hud:
        processar_comando(resposta, hud)


# ═══════════════════════════════════════════════════════════
#  MONITOR PROATIVO DE TELA
# ═══════════════════════════════════════════════════════════
_monitor_thread  = None
_monitor_pausado = False

_ultima_reacao_espontanea = 0.0
_ultima_reacao_erro       = 0.0
_INTERVALO_MIN_REACAO     = 120
_INTERVALO_MIN_ERRO       = 30
_INTERVALO_INATIVIDADE    = 180

def iniciar_monitor_tela(hud, intervalo: int = None):
    global _monitor_ativo, _monitor_thread
    if not TELA_MONITOR_ATIVO:
        return
    if intervalo is None:
        intervalo = TELA_MONITOR_INTERVALO
    if intervalo <= 0 or _monitor_ativo:
        return
    _monitor_ativo = True
    log.info(f"Monitor de tela iniciado. Intervalo: {intervalo}s")

    def _loop():
        global _monitor_ativo, _monitor_pausado, _ultimo_hash
        global _app_em_foco, _ultimo_erro_visto
        global _ultima_reacao_espontanea, _ultima_reacao_erro
        app_anterior  = ""
        erro_anterior = ""
        time.sleep(15)
        while _monitor_ativo:
            try:
                if not _monitor_pausado and _PIL_OK:
                    img    = ImageGrab.grab()
                    h_novo = _hash_tela(img)
                    agora  = time.time()
                    if h_novo == _ultimo_hash:
                        if (agora - _ultima_reacao_espontanea > _INTERVALO_MIN_REACAO
                                and agora - _ultima_analise > _INTERVALO_INATIVIDADE):
                            reacao = _frase_reacao("inatividade")
                            if reacao:
                                falar(reacao)
                                _ultima_reacao_espontanea = agora
                    else:
                        path, _ = _capturar_tela_para_analise()
                        if path:
                            ctx = _extrair_contexto_da_tela(path)
                            os.remove(path)
                            app_atual  = ctx.get("app", "")
                            erro_atual = ctx.get("erro_visivel") or ""
                            _app_em_foco = app_atual
                            app_mudou = app_atual and app_atual != app_anterior
                            erro_novo = erro_atual and erro_atual != erro_anterior
                            if erro_novo:
                                _ultimo_erro_visto = erro_atual
                                if agora - _ultima_reacao_erro > _INTERVALO_MIN_ERRO:
                                    reacao = _frase_reacao("erro_codigo")
                                    if reacao:
                                        falar(reacao)
                                        _ultima_reacao_erro = agora
                                dados = _gerar_sugestoes_do_contexto(ctx)
                                if "erro" not in dados and dados.get("sugestoes"):
                                    _sugestoes_cache[:] = dados["sugestoes"]
                                    _ultimo_contexto.update(dados)
                                    notificar(
                                        "JARVIS — Erro detectado",
                                        f"{erro_atual[:70]} · Diga 'Jarvis, me ajuda'"
                                    )
                                    hud.safe_update("alerta", "ERRO DETECTADO", app_atual[:20])
                            elif app_mudou:
                                if agora - _ultima_reacao_espontanea > _INTERVALO_MIN_REACAO:
                                    app_lower   = app_atual.lower()
                                    tipo_reacao = None
                                    for chave in ["spotify", "youtube", "terminal", "github"]:
                                        if chave in app_lower:
                                            tipo_reacao = chave if chave in _REACOES else None
                                            break
                                    if tipo_reacao:
                                        reacao = _frase_reacao(tipo_reacao)
                                        if reacao:
                                            falar(reacao)
                                            _ultima_reacao_espontanea = agora
                                    else:
                                        falar(f"{app_atual} aberto, {USUARIO}. Pode chamar se precisar.")
                                        _ultima_reacao_espontanea = agora
                                hud.safe_update(False, "MONITORANDO", app_atual[:20])
                            app_anterior  = app_atual
                            erro_anterior = erro_atual
                            _ultimo_hash  = h_novo
                _verificar_alertas_sistema(hud)
            except Exception as e:
                log.error(f"Monitor loop: {e}")
            time.sleep(intervalo)

    _monitor_thread = threading.Thread(target=_loop, daemon=True)
    _monitor_thread.start()

def _verificar_alertas_sistema(hud):
    global _ultima_reacao_espontanea
    agora = time.time()
    if agora - _ultima_reacao_espontanea < _INTERVALO_MIN_REACAO:
        return
    cpu = psutil.cpu_percent(interval=None)
    if cpu > 85:
        falar(_frase_reacao("cpu_alta"))
        hud.safe_update("alerta", "CPU ALTA", f"{cpu:.0f}%")
        _ultima_reacao_espontanea = agora
        return
    try:
        bat = psutil.sensors_battery()
        if bat and not bat.power_plugged and bat.percent < 15:
            falar(_frase_reacao("bateria_baixa"))
            hud.safe_update("alerta", "BATERIA BAIXA", f"{bat.percent:.0f}%")
            _ultima_reacao_espontanea = agora
    except Exception:
        pass

def pausar_monitor_tela():
    global _monitor_pausado
    _monitor_pausado = True

def retomar_monitor_tela():
    global _monitor_pausado
    _monitor_pausado = False

def parar_monitor_tela():
    global _monitor_ativo
    _monitor_ativo = False


# ═══════════════════════════════════════════════════════════
#  NLU — RESOLUÇÃO DE INTENÇÃO NATURAL
# ═══════════════════════════════════════════════════════════
_INTENCOES = [
    (r"(quero|bota|coloca|toca|ouvir|escutar|liga|abre?|inicia?).*(música|spotify|som|faixa|playlist)",
     "abrir spotify"),
    (r"(para|pausa|silencia|para a música|para o som|chega de música)",
     "pausar"),
    (r"(próxima|pula|avança|skip|outra faixa|pular)",
     "proxima"),
    (r"(volta|anterior|faixa anterior|de novo essa)",
     "voltar"),
    (r"(aumenta|sobe).*(volume|som)",
     "volume 80"),
    (r"(diminui|baixa|abaixa).*(volume|som)",
     "volume 30"),
    (r"(abre?|liga|vai|entra).*(firefox|navegador|browser|internet|chrome|web)",
     "abrir firefox"),
    (r"(pesquisa|busca|procura|googl[ea]|quero saber|me fala sobre|o que [eé]|como funciona)\s+(.+)",
     "pesquisar \\2"),
    (r"(abre?|vai).*(youtube)",
     "pesquisar youtube"),
    (r"(abre?|vai).*(github)",
     "pesquisar github"),
    (r"(abre?|liga|inicia?|quero usar|entra).*(terminal|bash|shell|linha de comando|cmd)",
     "abrir terminal"),
    (r"(abre?|liga|inicia?|quero usar).*(vscode|vs code|visual studio|editor|código|code)",
     "abrir code"),
    (r"(abre?|liga).*(calculadora|calcular)",
     "abrir calculadora"),
    (r"(abre?|liga).*(gerenciador|arquivos|pasta|explorador|files)",
     "abrir gerenciador"),
    (r"(abre?|liga).*(discord)",
     "abrir discord"),
    (r"(abre?|liga).*(spotify)",
     "abrir spotify"),
    (r"(que horas|que hora|horas são|quanto[s]? hora[s]?|me diz as horas)",
     "que horas são"),
    (r"(que dia|qual.*data|data de hoje|hoje.*dia|dia de hoje)",
     "data de hoje"),
    (r"(como.*tempo|como.*clima|vai chover|tá frio|tá calor|previsão|como.*tá lá fora)",
     "clima"),
    (r"(cala|para de falar|silêncio|chega|cancela[r]?|para jarvis|esquece)",
     "cala boca"),
    (r"(tira|faz|captura|salva).*(screenshot|print|printscreen|foto da tela|captura de tela)",
     "screenshot"),
    (r"(me ajuda|o que fazer|o que você sugere|como resolv|tá travado|não sei o que fazer|me dá uma ideia)",
     "me ajuda com o que estou fazendo"),
    (r"(explica|me explica|como faz|como funciona|me ensina).+",
     "me ajuda com o que estou fazendo"),
    (r"(me guia|me ajuda a fazer|quero fazer|preciso fazer|como (eu )?faço).+",
     "guiar \\0"),
    (r"(bateria|quanto.*bateria|tá carregando)",
     "bateria"),
    (r"(cpu|processador|memória|ram|uso do sistema|como.*pc|como.*computador|tá lento)",
     "status sistema"),
    (r"(tudo bem|como você (tá|está)|você (tá|está) bem|e aí)",
     "conversa"),
    (r"(obrigado|valeu|muito obrigado|ótimo|perfeito|que bom)",
     "conversa"),
]

def _resolver_intencao(comando: str) -> str:
    for padrao, intencao in _INTENCOES:
        m = re.search(padrao, comando, re.IGNORECASE)
        if m:
            try:
                resultado = m.expand(intencao)
            except re.error:
                resultado = intencao
            log.info(f"NLU: '{comando[:40]}' → '{resultado[:40]}'")
            return resultado
    return comando


# ═══════════════════════════════════════════════════════════
#  PROCESSADOR DE COMANDOS
# ═══════════════════════════════════════════════════════════
def processar_comando(comando: str, hud):
    comando = _resolver_intencao(comando)
    log.info(f"CMD: {comando}")
    hud.safe_update("ativo", "ATIVADO", comando[:32])
    hud.push_historico(re.sub(WAKE_WORD, "", comando).strip())
    _broadcast_chat("user", re.sub(WAKE_WORD, "", comando).strip())

    # ── Tenta resolver via sistema de plugins ────────────
    ctx = JarvisContext(
        hud=hud,
        falar_fn=falar,
        falar_sync_fn=falar_sync,
        ouvir_pergunta_fn=ouvir_pergunta,
        consultar_ia_fn=consultar_ia,
        usuario=USUARIO,
        confirmar_fn=_confirmar,
        notificar_fn=notificar,
        processar_comando_fn=lambda c: processar_comando(c, hud),
    )
    if processar_via_plugins(comando, ctx):
        time.sleep(0.3)
        hud.safe_update(False, "STANDBY", "Aguardando comando...")
        return

    if any(p in comando for p in ["para de falar", "cala boca", "silencio", "cancela"]):
        parar_fala()
        falar(f"Certo, {USUARIO}.")

    elif "conversa" == comando:
        clean = re.sub(WAKE_WORD, "", comando).strip()
        if any(p in clean for p in ["obrigado", "valeu", "ótimo", "perfeito"]):
            falar(random.choice([
                f"De nada, {USUARIO}.",
                f"Disponha.",
                f"É para isso que estou aqui, {USUARIO}.",
                f"Quando precisar.",
            ]))
        else:
            falar(random.choice([
                f"Tudo ótimo por aqui, {USUARIO}. Sistemas rodando, sem erros até agora.",
                f"Bem, obrigado. Você que manda.",
                f"Tudo nos conformes, {USUARIO}. Pronto para o que precisar.",
            ]))

    elif any(p in comando for p in [
        "me ajuda com o que estou fazendo", "o que você sugere",
        "o que voce sugere", "sugestões", "sugestoes",
        "analisar contexto", "o que posso fazer",
        "me dá uma ideia", "tá travado", "não sei o que fazer",
    ]):
        hud.safe_update("ia", "ANALISANDO", "Contexto da tela...")
        falar_sync(f"Deixa eu dar uma olhada no que você tem na tela, {USUARIO}.")
        dados = analisar_tela_contextual(forcar=True)
        falar_sugestoes(dados, hud)

    elif any(p in comando for p in ["repetir sugestões", "quais são as sugestões"]):
        if _sugestoes_cache:
            dados = {
                "contexto":     "última análise",
                "sugestoes":    _sugestoes_cache,
                "frase_jarvis": f"Sugestões da última análise, {USUARIO}.",
            }
            falar_sugestoes(dados, hud)
        else:
            falar(f"Nenhuma sugestão em cache. Diga: Jarvis, me ajuda.")

    elif any(p in comando for p in [
        "me guia", "quero fazer", "preciso fazer",
        "me ajuda a fazer", "como faço", "como eu faço",
    ]):
        tarefa = re.sub(
            r"jarvis|me guia|quero fazer|preciso fazer|me ajuda a fazer|como faço|como eu faço",
            "", comando).strip()
        if tarefa:
            hud.safe_update("foco", "GUIA", "Montando...")
            falar_sync(f"Vou montar um passo a passo para {tarefa}, um segundo.")
            iniciar_guia(tarefa[:30], tarefa, hud)
        else:
            falar_sync(f"O que você quer fazer, {USUARIO}?")
            resp = ouvir_pergunta(timeout=10, limite=30)
            if resp:
                iniciar_guia(resp[:30], resp, hud)

    elif any(p in comando for p in ["próximo passo", "feito", "próxima etapa", "pode continuar", "avança"]):
        if _tarefa_ativa:
            avancar_passo(hud)
        else:
            falar(f"Não há guia ativo no momento, {USUARIO}.")

    elif any(p in comando for p in ["cancelar guia", "para o guia", "não precisa mais"]):
        cancelar_guia(hud)

    elif "status do guia" in comando or "em que passo" in comando:
        s = status_guia()
        falar(s if s else f"Nenhum guia ativo, {USUARIO}.")

    elif any(p in comando for p in ["ativar monitor", "ligar monitor", "monitorar tela"]):
        retomar_monitor_tela()
        hud.safe_update("ia", "MONITOR", "Ativo")
        falar(f"Monitor ativo, {USUARIO}. Vou falar se notar algo.")

    elif any(p in comando for p in ["desativar monitor", "pausar monitor", "para de monitorar"]):
        pausar_monitor_tela()
        hud.safe_update(False, "MONITOR", "Pausado")
        falar(f"Monitor pausado, {USUARIO}.")

    elif any(p in comando for p in ["lembre", "adicionar evento", "cadastrar evento", "salvar data"]):
        resultado = ev_extrair_data_e_nome(comando)
        if not resultado:
            hud.safe_update("foco", "EVENTO", "Aguardando...")
            falar_sync(f"Fala a data e o nome, {USUARIO}. Por exemplo: dia 24 de junho como São João.")
            detalhe   = ouvir_pergunta(timeout=12, limite=40)
            resultado = ev_extrair_data_e_nome(detalhe) if detalhe else None
        if resultado:
            dia, mes, ano, nome = resultado
            ev_adicionar(nome, dia, mes, ano)
            ano_str = f" de {ano}" if ano else ""
            hud.safe_update("foco", "EVENTO", f"Salvo: {nome[:20]}")
            falar(f"Anotado — {nome} no dia {dia}/{mes}{ano_str}.")
        else:
            falar(f"Não entendi a data, {USUARIO}. Tenta de novo.")

    elif any(p in comando for p in [
        "quantos dias faltam", "quando é", "falta para",
        "quanto falta", "falta quanto", "quando vai ser",
    ]):
        eventos    = ev_listar()
        encontrado = ev_buscar_por_voz(comando, eventos)
        if encontrado:
            hud.safe_update("foco", "CONTAGEM", encontrado["nome"][:20])
            falar(ev_frase(encontrado["nome"], encontrado["faltam"]))
        elif eventos:
            for ev in eventos[:5]:
                falar(ev_frase(ev["nome"], ev["faltam"]))
        else:
            falar(f"Agenda vazia, {USUARIO}.")

    elif any(p in comando for p in [
        "listar eventos", "quais eventos", "minha agenda",
        "ver agenda", "o que tenho na agenda", "próximos eventos",
        "proximos eventos", "me fala a agenda", "o que tem marcado",
    ]):
        eventos = ev_listar()
        if not eventos:
            falar(f"Agenda limpa, {USUARIO}. Sem nada marcado.")
        else:
            qtd = len(eventos)
            falar(f"Você tem {qtd} evento{'s' if qtd > 1 else ''} na agenda.")
            for ev in eventos:
                falar(ev_frase(ev["nome"], ev["faltam"]))
        hud.safe_update("foco", "AGENDA", f"{len(eventos)} eventos")

    elif any(p in comando for p in ["remover evento", "deletar evento", "apagar evento"]):
        m = re.search(r"(?:remover|deletar|apagar)\s+evento\s+(.+)", comando)
        if m:
            nome_alvo = m.group(1).strip()
            if ev_remover(nome_alvo):
                falar(f"Evento {nome_alvo} removido.")
            else:
                falar(f"Não achei nenhum evento chamado {nome_alvo}.")
        else:
            falar(f"Qual evento remover, {USUARIO}?")

    elif "fechar" in comando or "matar processo" in comando:
        alvo = re.sub(r"jarvis|fechar|matar processo", "", comando).strip()
        ok   = fechar_app(alvo) if alvo else False
        falar("Processo encerrado." if ok
              else f"Não achei o processo, {USUARIO}.")

    elif any(p in comando for p in ["processos", "cpu alta", "o que está rodando", "status sistema"]):
        hud.safe_update("ia", "PROCESSOS", "Top CPU...")
        cpu  = psutil.cpu_percent(interval=1)
        ram  = psutil.virtual_memory().percent
        resp = f"CPU em {cpu:.0f}%, memória em {ram:.0f}%."
        top  = listar_processos()
        if cpu > 70:
            resp += f" Mais pesados: {top}."
        falar(resp)

    elif "bateria" in comando:
        try:
            bat = psutil.sensors_battery()
            if bat:
                plugged = "carregando" if bat.power_plugged else "na bateria"
                falar(f"Bateria em {bat.percent:.0f}%, {plugged}.")
            else:
                falar(f"Não consegui ler a bateria, {USUARIO}.")
        except Exception:
            falar(f"Sem sensor de bateria disponível.")

    elif "mover janela" in comando or "janela para" in comando:
        for d in ["esquerda", "direita", "cima", "baixo", "maximizar"]:
            if d in comando:
                mover_janela(d)
                falar(f"Janela para {d}.")
                break
        else:
            falar(f"Para onde? Esquerda, direita, cima, baixo ou maximizar.")

    elif any(p in comando for p in ["executar script", "rodar script", "executa o script"]):
        hud.safe_update("ia", "SCRIPT", "Aguardando...")
        falar_sync(f"Qual o caminho do script, {USUARIO}?")
        caminho = ouvir_pergunta(timeout=8, limite=20)
        if caminho:
            resultado = executar_script(caminho)
            falar(f"Script concluído. {resultado[:100]}")
        else:
            falar("Não captei o caminho.")

    elif any(p in comando for p in ["analisar tela", "descrever tela", "o que está na tela"]):
        hud.safe_update("ia", "VISÃO", "Processando...")
        falar_sync(f"Um segundo, {USUARIO}.")
        ctx  = None
        path, _ = _capturar_tela_para_analise()
        if path:
            ctx = _extrair_contexto_da_tela(path)
            os.remove(path)
        if ctx:
            falar(ctx.get("conteudo_resumo", "Não consegui descrever a tela."))
        else:
            falar(f"Não consegui capturar a tela, {USUARIO}.")

    elif any(p in comando for p in ["digitar", "escrever no teclado"]):
        txt = re.sub(r"jarvis|digitar|escrever no teclado", "", comando).strip()
        if txt:
            digitar_texto(txt)
            falar(_confirmar())
        else:
            falar_sync(f"O que devo digitar, {USUARIO}?")
            resp = ouvir_pergunta(timeout=6, limite=15)
            if resp:
                digitar_texto(resp)
                falar(_confirmar())

    elif any(p in comando for p in ["screenshot", "captura de tela", "printscreen", "print da tela"]):
        dest = tirar_screenshot()
        if dest:
            falar(f"Screenshot salvo em {os.path.basename(dest)}.")
            notificar("Screenshot", dest)
        else:
            falar(f"Não consegui tirar o screenshot, {USUARIO}.")

    elif any(p in comando for p in ["mensagem no discord", "enviar discord", "manda no discord"]):
        hud.safe_update("discord", "DISCORD", "Aguardando...")
        falar_sync(f"O que mando, {USUARIO}?")
        msg = ouvir_pergunta(timeout=8, limite=30)
        falar(discord_enviar(msg) if msg else "Não captei a mensagem.")

    elif any(p in comando for p in ["ler email", "checar email", "verificar email",
                                     "novos emails", "meus emails", "caixa de entrada"]):
        hud.safe_update("ia", "E-MAIL", "Conectando...")
        filtro   = None
        m_filtro = re.search(r"\b(?:do|da|de)\s+(.+)$", comando)
        if m_filtro:
            filtro = re.sub(
                r"jarvis|ler|checar|verificar|novos|meus|email[s]?|caixa de entrada",
                "", m_filtro.group(1)).strip()
        qtd  = 5
        nums = [int(w) for w in comando.split() if w.isdigit()]
        if nums:
            qtd = min(nums[0], 10)
        falar_sync("Verificando e-mail, um segundo." if not filtro
                   else f"Buscando e-mails de {filtro}.")
        falar(ler_emails(quantidade=qtd, filtro_remetente=filtro))

    elif any(p in comando for p in ["pausar", "parar musica", "pause"]):
        subprocess.run(["playerctl", "pause"], capture_output=True)
        falar("Pausado.")

    elif any(p in comando for p in ["proxima", "pular", "skip"]):
        subprocess.run(["playerctl", "next"], capture_output=True)
        falar("Próxima faixa.")

    elif any(p in comando for p in ["voltar", "anterior", "volta a"]):
        subprocess.run(["playerctl", "previous"], capture_output=True)
        falar("Voltando.")

    elif "volume" in comando:
        nums = [w for w in comando.split() if w.isdigit()]
        if nums:
            vol = min(int(nums[0]), 100)
            subprocess.run(["pactl", "set-sink-volume", "@DEFAULT_SINK@", f"{vol}%"],
                           capture_output=True)
            falar(f"Volume em {vol}%.")
        else:
            falar(f"Qual porcentagem, {USUARIO}?")

    elif any(p in comando for p in ["abrir", "iniciar", "abre", "liga"]):
        hud.safe_update(False, "ABRINDO", "App")
        falar(abrir_app(comando))

    elif any(p in comando for p in ["pesquisa", "pesquisar", "buscar", "busca", "procura"]):
        termo = re.sub(r"jarvis|pesquisa[r]?|buscar?|procura[r]?", "", comando).strip()
        if termo:
            subprocess.Popen(["xdg-open",
                               f"https://www.google.com/search?q={urllib.parse.quote(termo)}"])
            falar(f"Pesquisando {termo}.")
        else:
            falar(f"O que pesquisar, {USUARIO}?")

    # ── Briefing no WhatsApp (manual por voz) ────────────
    elif any(p in comando for p in [
        "manda briefing no whatsapp", "envia briefing whatsapp",
        "briefing pelo whatsapp", "briefing no whatsapp",
    ]):
        if _WA_OK:
            hud.safe_update("foco", "WHATSAPP", "Enviando...")
            falar_sync("Preparando e enviando briefing pelo WhatsApp.")
            ok = enviar_briefing_whatsapp(nome=USUARIO)
            falar("Briefing enviado com sucesso." if ok
                  else f"Não consegui enviar pelo WhatsApp agora, {USUARIO}.")
        else:
            falar(f"Módulo WhatsApp não instalado, {USUARIO}.")

    # ── Mensagem livre no WhatsApp ────────────────────────
    elif any(p in comando for p in [
        "mensagem no whatsapp", "manda mensagem no whatsapp", "envia whatsapp",
    ]):
        if _WA_OK:
            hud.safe_update("foco", "WHATSAPP", "Aguardando...")
            falar_sync(f"O que mando pelo WhatsApp, {USUARIO}?")
            msg = ouvir_pergunta(timeout=10, limite=40)
            if msg:
                ok = enviar_whatsapp(msg)
                falar("Enviado." if ok else "Falha no envio, verifique a conexão.")
            else:
                falar("Não captei a mensagem.")
        else:
            falar(f"Módulo WhatsApp não instalado, {USUARIO}.")

    elif "clima" in comando or "tempo" in comando or "chuva" in comando:
        cidade = re.sub(r"jarvis|clima|tempo|em|como.*tá|como.*está|previsão", "",
                        comando).strip() or "Aracaju"
        hud.safe_update("ia", "CLIMA", cidade[:20])
        falar(obter_clima(cidade))

    elif "lembrete" in comando:
        nums = [int(w) for w in comando.split() if w.isdigit()]
        if nums:
            m = nums[0]
            falar(f"Lembrete em {m} minuto{'s' if m > 1 else ''}. Pode trabalhar.")
            def _lembrete(mins=m):
                time.sleep(mins * 60)
                hud.safe_update("alerta", "LEMBRETE", f"{mins}min")
                notificar("JARVIS – Lembrete", f"{mins} minutos se passaram.")
                falar(f"{USUARIO}, seu lembrete de {mins} minuto{'s' if mins > 1 else ''} chegou.")
            threading.Thread(target=_lembrete, daemon=True).start()
        else:
            falar_sync(f"Em quantos minutos, {USUARIO}?")
            resp = ouvir_pergunta(timeout=6, limite=5)
            nums2 = [int(w) for w in (resp or "").split() if w.isdigit()]
            if nums2:
                processar_comando(f"lembrete {nums2[0]} minutos", hud)

    elif any(p in comando for p in ["horas", "que horas", "hora certa"]):
        agora = datetime.datetime.now()
        falar(f"São {agora.strftime('%H:%M')}, {USUARIO}.")

    elif any(p in comando for p in ["data de hoje", "que dia é hoje", "qual a data", "dia de hoje"]):
        falar(f"Hoje é {datetime.datetime.now().strftime('%d de %B de %Y')}.")

    elif any(p in comando for p in ["quanto é", "quanto e", "calcular", "calcula", "me calcula"]):
        expr = re.sub(r"jarvis|quanto [eé]|calcul[ae]r?|me calcula", "",
                      comando).replace("x", "*").replace("vezes", "*").replace(
                      "mais", "+").replace("menos", "-").strip()
        r    = calcular(expr)
        if r is not None:
            falar(f"{expr} = {r}.")
        else:
            falar(consultar_ia(f"Calcule: {expr}", curto=True))

    elif any(p in comando for p in ["foco", "estudar", "produtividade", "modo foco"]):
        hud.safe_update("foco", "MODO FOCO", "Ativo")
        pausar_monitor_tela()
        notificar("JARVIS", "Modo foco ativo.")
        falar(f"Modo foco ativado, {USUARIO}. Monitor pausado para não te interromper. Bom trabalho.")

    elif any(p in comando for p in ["limpar memória", "nova conversa", "resetar", "limpar histórico"]):
        limpar_historico()
        falar(f"Memória de conversa limpa, {USUARIO}. Começando do zero.")

    elif any(p in comando for p in ["desligar", "encerrar", "sair", "desativa"]):
        parar_monitor_tela()
        falar_sync(random.choice([
            f"Desligando sistemas Mark XIII. Até logo, {USUARIO}.",
            f"Encerrando. Foi um prazer trabalhar com você hoje, {USUARIO}.",
            f"Sistemas offline. Descanse bem, {USUARIO}.",
        ]))
        hud.animacao_shutdown()

    else:
        hud.safe_update("ia", "CONSULTANDO", "Gemini...")
        clean = re.sub(WAKE_WORD, "", comando).strip()
        contexto_guia = ""
        if _tarefa_ativa:
            contexto_guia = (
                f"\n[CONTEXTO: o usuário está no passo "
                f"{_tarefa_ativa['passo_atual']+1} de "
                f"'{_tarefa_ativa['titulo']}'. "
                f"Responda levando isso em conta.]"
            )
        contexto_tela = ""
        if _app_em_foco:
            contexto_tela = f"\n[TELA ATUAL: {_app_em_foco}]"
        prompt_enriquecido = clean + contexto_guia + contexto_tela
        resposta = consultar_ia(prompt_enriquecido, curto=True)
        falar(resposta.replace("*", "").replace("#", ""))

    time.sleep(0.3)
    hud.safe_update(False, "STANDBY", "Aguardando comando...")


# ═══════════════════════════════════════════════════════════
#  LOOP PRINCIPAL
# ═══════════════════════════════════════════════════════════
def rodar_jarvis(hud):
    """
    FIX: Inicialização totalmente sequencial — zero falas sobrepostas.
    Toda fala usa falar_sync durante o boot para garantir ordem correta.
    O Web HUD e monitor só iniciam DEPOIS das falas de boot.
    """
    time.sleep(1)
    hud.safe_update(False, "CALIBRANDO", "Ajustando microfone...")

    # FIX: calibração antes de qualquer fala
    calibrar_microfone()

    agora    = datetime.datetime.now()
    hora     = agora.hour
    saudacao = ("Bom dia" if 5 <= hora < 12
           else "Boa tarde" if 12 <= hora < 18
           else "Boa noite")

    try:
        bat = int(psutil.sensors_battery().percent)
        bat_str = f"Bateria em {bat}%."
    except Exception:
        bat_str = ""

    engine_str = "Kokoro ativo." if _KOKORO_OK else "Edge TTS ativo."
    hud.safe_update(False, "ONLINE", "Mark XIII")

    # FIX: saudação via falar_sync — bloqueia até terminar
    falar_sync(random.choice([
        f"{saudacao}, {USUARIO}. Sistemas Mark XIII operacionais. {bat_str} {engine_str} Pronto quando você quiser.",
        f"{saudacao}. Mark XIII online. {bat_str} O que a gente vai fazer hoje?",
        f"{saudacao}, {USUARIO}. Tudo operacional. {bat_str} Pode começar.",
    ]))

    notificar("JARVIS Online", f"{saudacao}, {USUARIO}.")

    # FIX: agenda anunciada SEQUENCIALMENTE (ainda bloqueando com falar_sync)
    # Não usa thread aqui para não sobrepor com o Web HUD
    ev_anunciar_iniciais(hud, falar_sync)

    # FIX: só DEPOIS das falas de boot iniciamos o Web HUD e monitor
    from jarvis_web_hud import iniciar_servidor_web
    iniciar_servidor_web(hud, falar_sync, processar_comando)

    iniciar_monitor_tela(hud, intervalo=TELA_MONITOR_INTERVALO)
    if TELA_MONITOR_ATIVO and TELA_MONITOR_INTERVALO > 0:
        falar_sync("Monitor de tela ativo. Vou comentar quando notar algo relevante.")

    # ── Briefing automático WhatsApp ─────────────────────
    if _WA_OK:
        iniciar_briefing_whatsapp(
            nome=USUARIO,
            horario=os.getenv("BRIEFING_WA_HORA", "07:00"),
        )
        log.info("Briefing automático WhatsApp agendado.")

    # ── Loop de escuta ────────────────────────────────────
    while True:
        hud.safe_update(False, "ESCUTANDO")
        comando = ouvir(timeout=5, limite=12)
        if not comando or not contem_wake_word(comando):
            continue
        processar_comando(comando, hud)