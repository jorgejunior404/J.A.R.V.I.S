"""
╔══════════════════════════════════════════════════════════╗
║         J.A.R.V.I.S  —  MARK XII  ·  CORE               ║
║  Microfone · TTS · IA · Automações · Integrações         ║
║  + Análise Contextual de Tela com Sugestões Proativas    ║
╚══════════════════════════════════════════════════════════╝

Não execute este arquivo diretamente.
Execute: python jarvis_hud.py

Variáveis no .env:
    GEMINI_API_KEY         = sua_chave
    VOZ                    = pt-BR-AntonioNeural
    PITCH                  = 0.91
    WAKE_WORD              = jarvis
    WEATHER_API_KEY        = chave_openweathermap
    DISCORD_TOKEN          = token_do_bot
    DISCORD_CHANNEL_ID     = id_do_canal
    EMAIL_USER             = seu@email.com
    EMAIL_PASS             = sua_senha
    EMAIL_IMAP             = imap.gmail.com
    TELA_MONITOR_INTERVALO = 120   (segundos entre análises automáticas, 0=desativa)
    TELA_MONITOR_ATIVO     = true  (false para desativar monitor automático)
"""

# ═══════════════════════════════════════════════════════════
#  IMPORTS
# ═══════════════════════════════════════════════════════════
import os, re, json, math, time, datetime
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


# ═══════════════════════════════════════════════════════════
#  CONFIGURAÇÃO
# ═══════════════════════════════════════════════════════════
load_dotenv()

GEMINI_KEY             = os.getenv("GEMINI_API_KEY", "")
VOZ                    = os.getenv("VOZ",        "pt-BR-AntonioNeural")
PITCH                  = os.getenv("PITCH",      "0.91")
WAKE_WORD              = os.getenv("WAKE_WORD",  "jarvis")
WEATHER_KEY            = os.getenv("WEATHER_API_KEY", "")
DISCORD_TOKEN          = os.getenv("DISCORD_TOKEN", "")
DISCORD_CHANNEL_ID     = int(os.getenv("DISCORD_CHANNEL_ID", "0") or "0")
EMAIL_USER             = os.getenv("EMAIL_USER", "")
EMAIL_PASS             = os.getenv("EMAIL_PASS", "")
EMAIL_IMAP             = os.getenv("EMAIL_IMAP", "imap.gmail.com")
TELA_MONITOR_INTERVALO = int(os.getenv("TELA_MONITOR_INTERVALO", "120"))
TELA_MONITOR_ATIVO     = os.getenv("TELA_MONITOR_ATIVO", "true").lower() == "true"

logging.basicConfig(
    filename="jarvis.log", level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
log = logging.getLogger("JARVIS")


# ═══════════════════════════════════════════════════════════
#  MICROFONE
# ═══════════════════════════════════════════════════════════
rec = sr.Recognizer()
rec.pause_threshold          = 0.5   # ⚡ era 0.8 — detecta fim de fala mais rápido
rec.non_speaking_duration    = 0.4   # ⚡ corta silêncio antes de enviar
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
#  TTS  (edge-tts → ffmpeg em pipeline → mpg123)
#  ⚡ Otimizado: edge-tts e ffmpeg em pipe direto, sem disco
# ═══════════════════════════════════════════════════════════
_fala_thread = None
_fala_proc   = None

def _gerar_audio(texto: str):
    """Gera áudio com pitch: edge-tts → ffmpeg em pipe (sem arquivo intermediário)."""
    ts    = int(time.time() * 1000)
    grave = f"/tmp/jv_{ts}_g.mp3"
    try:
        # edge-tts escreve para stdout, ffmpeg lê do stdin — elimina 1 disco I/O
        p1 = subprocess.Popen(
            ["edge-tts", "--voice", VOZ, "--text", texto, "--write-media", "/dev/stdout"],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL
        )
        p2 = subprocess.Popen(
            ["ffmpeg", "-y", "-i", "pipe:0", "-af", f"rubberband=pitch={PITCH}", grave],
            stdin=p1.stdout, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
        p1.stdout.close()
        p2.wait()
        p1.wait()
        return grave
    except Exception as e:
        log.error(f"TTS: {e}")
        if os.path.exists(grave): os.remove(grave)
        return None

def parar_fala():
    global _fala_proc
    if _fala_proc and _fala_proc.poll() is None:
        _fala_proc.terminate()

def falar(texto: str):
    """Fala de forma assíncrona (não bloqueia o loop principal)."""
    global _fala_thread
    def _run():
        global _fala_proc
        grave = _gerar_audio(texto)
        if not grave:
            print(f"[JARVIS] {texto}"); return
        try:
            _fala_proc = subprocess.Popen(["mpg123", "-q", grave])
            _fala_proc.wait()
        finally:
            if grave and os.path.exists(grave): os.remove(grave)
    if _fala_thread and _fala_thread.is_alive():
        _fala_thread.join(timeout=15)
    _fala_thread = threading.Thread(target=_run, daemon=True)
    _fala_thread.start()

def falar_sync(texto: str):
    """Fala de forma síncrona (bloqueia até terminar)."""
    global _fala_proc
    grave = _gerar_audio(texto)
    if not grave:
        print(f"[JARVIS] {texto}"); return
    try:
        _fala_proc = subprocess.Popen(["mpg123", "-q", grave])
        _fala_proc.wait()
    finally:
        if grave and os.path.exists(grave): os.remove(grave)


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
    modelos  = ["gemini-2.5-flash", "gemini-2.0-flash", "gemini-1.5-flash"]
    modo     = "muito curto, máximo 2 frases" if curto else "detalhado mas objetivo"
    conteudo = f"Responda como o JARVIS, {modo}: {prompt}"
    for modelo in modelos:
        for tentativa in range(2):
            try:
                resp = _cliente_ia.models.generate_content(model=modelo, contents=conteudo)
                return resp.text.strip() if resp and resp.text else "Sem resposta."
            except Exception as e:
                log.warning(f"IA [{modelo}] tentativa {tentativa+1}: {e}")
                time.sleep(2)
    return "Todos os modelos indisponíveis no momento, senhor."

def consultar_ia_com_imagem(prompt: str, imagem_path: str) -> str:
    """Envia imagem + prompt para o Gemini Vision e retorna a resposta."""
    if not _cliente_ia:
        return "Gemini não configurado, senhor."
    if not os.path.exists(imagem_path):
        return "Imagem não encontrada para análise."
    try:
        with open(imagem_path, "rb") as f:
            img_bytes = f.read()

        from google.genai import types as gtypes
        image_part = gtypes.Part.from_bytes(data=img_bytes, mime_type="image/png")
        text_part  = gtypes.Part.from_text(text=prompt)

        modelos = ["gemini-2.5-flash", "gemini-2.0-flash", "gemini-1.5-flash"]
        for modelo in modelos:
            for tentativa in range(2):
                try:
                    resp = _cliente_ia.models.generate_content(
                        model=modelo,
                        contents=[gtypes.Content(parts=[image_part, text_part])]
                    )
                    return resp.text.strip() if resp and resp.text else "Sem resposta da IA."
                except Exception as e:
                    log.warning(f"IA imagem [{modelo}] tentativa {tentativa+1}: {e}")
                    time.sleep(2)
        return "Todos os modelos indisponíveis para visão, senhor."
    except Exception as e:
        log.error(f"IA com imagem erro: {e}")
        return "Falha na análise visual, senhor."


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
    """Análise simples (legado) — descreve o que está na tela."""
    if not _PIL_OK:
        return "Pillow não instalado para captura de tela."
    try:
        path = f"/tmp/screen_{int(time.time())}.png"
        ImageGrab.grab().save(path)
        resp = consultar_ia_com_imagem(
            "Descreva o que está na tela e identifique o que o usuário está fazendo.",
            path
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
        key=lambda p: p.info["cpu_percent"] or 0, reverse=True)[:5]
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
        log.error(f"clima: {e}"); return "Não consegui obter o clima agora."

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
        log.error(f"Discord: {e}"); return "Falha ao enviar no Discord."

def notificar(titulo: str, corpo: str):
    try:
        subprocess.run(["notify-send", "-t", "5000", titulo, corpo], capture_output=True)
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
        return "E-mail não configurado. Adicione EMAIL_USER e EMAIL_PASS no .env, senhor."
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
            return (f"Não encontrei e-mails de {filtro_remetente}, senhor."
                    if filtro_remetente else
                    "Não encontrei e-mails na caixa de entrada, senhor.")
        ids = dados[0].split()
        recentes = ids[-quantidade:][::-1]
        linhas = []
        for uid in recentes:
            status, msg_data = imap.fetch(uid, "(BODY.PEEK[HEADER.FIELDS (FROM SUBJECT DATE)])")
            if status != "OK": continue
            msg = email.message_from_bytes(msg_data[0][1])
            remetente  = _decodificar_header(msg.get("From", "desconhecido"))
            assunto    = _decodificar_header(msg.get("Subject", "sem assunto"))
            nome_email = re.sub(r"\s*<[^>]+>", "", remetente).strip() or remetente
            linhas.append(f"{nome_email}: {assunto}")
        imap.logout()
        if not linhas:
            return "Não consegui ler os e-mails agora, senhor."
        intro = (f"Senhor, encontrei {len(linhas)} e-mail(s) de {filtro_remetente}. "
                 if filtro_remetente else
                 f"Senhor, aqui estão os {len(linhas)} e-mails mais recentes. ")
        return intro + ". ".join(linhas) + "."
    except imaplib.IMAP4.error as e:
        log.error(f"IMAP auth: {e}")
        return "Falha de autenticação no e-mail. Verifique suas credenciais, senhor."
    except Exception as e:
        log.error(f"ler_emails: {e}")
        return "Não consegui acessar o e-mail agora, senhor."


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
    log.info(f"Evento adicionado: {nome} {dia}/{mes}/{ano}")

def ev_remover(nome: str) -> bool:
    eventos = _ev_carregar()
    if nome.lower() in eventos:
        del eventos[nome.lower()]
        _ev_salvar(eventos)
        log.info(f"Evento removido: {nome}")
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
    if faltam == 0:   return f"Hoje é o dia de {nome}, senhor!"
    elif faltam == 1: return f"Falta apenas 1 dia para {nome}, senhor."
    elif faltam < 0:  return f"{nome} já passou há {abs(faltam)} dias, senhor."
    else:             return f"Faltam {faltam} dias para {nome}, senhor."

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
    eventos = ev_listar()
    if not eventos: return
    hud.safe_update("foco", "AGENDA", f"{len(eventos)} eventos")
    for ev in eventos:
        falar_fn(ev_frase(ev["nome"], ev["faltam"]))

def ev_buscar_por_voz(comando: str, eventos: list) -> dict:
    for ev in eventos:
        if ev["nome"] in comando: return ev
    return None


# ═══════════════════════════════════════════════════════════
#  ANÁLISE CONTEXTUAL DE TELA  ← SISTEMA INTELIGENTE
# ═══════════════════════════════════════════════════════════

# Estado do monitor de tela
_monitor_ativo   = False
_ultimo_hash     = ""
_ultima_analise  = 0.0
_sugestoes_cache = []
_ultimo_contexto = {}   # guarda o último contexto rico para comparação

# ── Prompt de extração de contexto rico ─────────────────
# Primeira passagem: extrair FATOS concretos da tela
_PROMPT_EXTRACAO = """
Você é um sistema de visão computacional preciso. Analise esta captura de tela e extraia
APENAS fatos concretos e observáveis. Seja extremamente específico — leia textos, nomes de
arquivos, URLs, mensagens de erro, nomes de funções, qualquer texto visível.

Responda SOMENTE em JSON válido, sem markdown.

{
  "app": "nome exato do aplicativo em foco (ex: VS Code, Firefox, Terminal, Spotify)",
  "aba_titulo": "título exato da aba ou janela ativa",
  "url": "URL visível na barra de endereço, ou null",
  "arquivo_aberto": "nome e extensão do arquivo aberto, ou null (ex: main.py, index.js)",
  "linguagem": "linguagem de programação detectada, ou null (ex: Python, JavaScript)",
  "erro_visivel": "mensagem de erro exata se houver alguma visível na tela, ou null",
  "texto_selecionado": "texto que parece estar selecionado ou em foco, ou null",
  "ultimo_comando": "último comando digitado no terminal se visível, ou null",
  "conteudo_resumo": "resumo de 1 frase do que está na tela — específico, com nomes reais",
  "intencao_provavel": "o que o usuário provavelmente está tentando fazer agora — específico"
}

Exemplos de BOAS respostas:
- arquivo_aberto: "jarvis_core.py" (não "um arquivo python")
- erro_visivel: "NameError: name 'falar' is not defined on line 42" (não "tem um erro")
- aba_titulo: "GitHub - anthropics/anthropic-sdk-python" (não "GitHub")
- ultimo_comando: "pip install google-genai" (não "um comando pip")
- intencao_provavel: "corrigir o TypeError na função processar_comando" (não "editar código")
"""

# ── Prompt de geração de sugestões baseado nos fatos ────
# Segunda passagem: gera sugestões cirúrgicas usando o contexto extraído
_PROMPT_SUGESTOES = """
Você é o J.A.R.V.I.S. Com base no contexto concreto abaixo, gere 3 sugestões de ação
CIRÚRGICAS e ESPECÍFICAS para o que o usuário está fazendo AGORA.

CONTEXTO REAL DA TELA:
{contexto}

REGRAS ABSOLUTAS:
1. Cada sugestão deve mencionar detalhes REAIS da tela (nome do arquivo, erro específico,
   URL, função, pacote, etc). NUNCA sugira algo genérico como "rode o código" ou "debug o código".
2. Se há um erro visível → a sugestão #1 DEVE ser sobre aquele erro específico.
3. Se há um arquivo aberto → mencione o nome do arquivo na sugestão.
4. Se há uma URL → sugira algo relacionado àquele site/conteúdo específico.
5. comando_voz deve ser uma frase natural em português que o JARVIS já sabe executar:
   pesquisar X, abrir terminal, tirar screenshot, volume 50, pausar música,
   abrir spotify, abrir chrome, modo foco, etc.

Responda SOMENTE em JSON válido, sem markdown:
{
  "contexto": "frase curta e específica do que está acontecendo (máx 60 chars)",
  "sugestoes": [
    {
      "titulo": "ação específica com detalhe real (máx 45 chars)",
      "descricao": "o que exatamente será feito — mencione nomes reais (máx 90 chars)",
      "comando_voz": "comando natural em português para o JARVIS executar"
    }
  ],
  "frase_jarvis": "frase do JARVIS mencionando detalhes reais da tela (máx 110 chars)"
}

EXEMPLOS DE SUGESTÕES BOAS vs RUINS:

Contexto: VS Code com erro "ModuleNotFoundError: No module named 'psutil'" em jarvis_core.py
  RUIM: {"titulo": "Instalar dependência", "comando_voz": "abrir terminal"}
  BOM:  {"titulo": "Instalar psutil no terminal", "descricao": "Abrir terminal e rodar pip install psutil para resolver o erro em jarvis_core.py", "comando_voz": "abrir terminal"}

Contexto: YouTube com vídeo "Curso Python - Decorators" pausado em 14:32
  RUIM: {"titulo": "Pesquisar sobre o vídeo", "comando_voz": "pesquisar python"}
  BOM:  {"titulo": "Pesquisar exemplos de decorators", "descricao": "Buscar 'python decorators exemplos práticos' para complementar o que está assistindo", "comando_voz": "pesquisar python decorators exemplos práticos"}

Contexto: Terminal com último comando 'git push' retornando erro de autenticação
  RUIM: {"titulo": "Verificar terminal", "comando_voz": "abrir terminal"}
  BOM:  {"titulo": "Pesquisar erro de auth no Git", "descricao": "Buscar solução para o erro de autenticação do git push que apareceu no terminal", "comando_voz": "pesquisar git push authentication failed solução"}
"""

def _hash_tela(img) -> str:
    """Hash da imagem reduzida — detecta mudanças visuais reais (não só pixels)."""
    try:
        # Usa resolução maior para não confundir mudanças pequenas com grandes
        small = img.resize((128, 72))
        return hashlib.md5(small.tobytes()).hexdigest()
    except Exception:
        return ""

def _tela_mudou_significativamente(hash_novo: str, hash_anterior: str) -> bool:
    """
    Compara dois hashes. Retorna True se a mudança for considerável.
    Usa comparação direta — hashes md5 são binários, qualquer diff = mudança.
    """
    return hash_novo != hash_anterior

def _capturar_tela_para_analise() -> tuple:
    """Captura tela, retorna (path, hash). Mantém alta qualidade para leitura de texto."""
    if not _PIL_OK:
        return None, ""
    try:
        img = ImageGrab.grab()
        h   = _hash_tela(img)
        path = f"/tmp/jarvis_ctx_{int(time.time())}.png"
        # Mantém 1280px de largura — suficiente para ler texto, econômico em tokens
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
    """Parseia JSON da resposta, tolerando markdown residual."""
    limpo = re.sub(r"```(?:json)?", "", raw).strip().rstrip("`").strip()
    # Tenta extrair JSON de dentro de um bloco maior
    m = re.search(r"\{[\s\S]+\}", limpo)
    if m:
        limpo = m.group(0)
    return json.loads(limpo)

def _extrair_contexto_da_tela(path: str) -> dict:
    """
    Passagem 1: Lê fatos concretos da tela — textos, erros, URLs, nomes de arquivo.
    Retorna dict com os fatos extraídos.
    """
    raw = consultar_ia_com_imagem(_PROMPT_EXTRACAO, path)
    try:
        return _parsear_json(raw)
    except Exception as e:
        log.error(f"Extração de contexto falhou: {e} | raw: {raw[:300]}")
        # Fallback mínimo
        return {
            "app": "desconhecido",
            "conteudo_resumo": "tela atual",
            "intencao_provavel": "uso geral do computador",
        }

def _gerar_sugestoes_do_contexto(ctx: dict) -> dict:
    """
    Passagem 2: Usa os fatos extraídos para gerar sugestões cirúrgicas.
    Recebe o dict de contexto, injeta no prompt e chama a IA (só texto, sem imagem).
    """
    # Formata o contexto de forma legível para o prompt
    linhas = []
    mapa = {
        "app":              "Aplicativo",
        "aba_titulo":       "Título da janela",
        "url":              "URL",
        "arquivo_aberto":   "Arquivo aberto",
        "linguagem":        "Linguagem",
        "erro_visivel":     "ERRO VISÍVEL",
        "texto_selecionado":"Texto selecionado",
        "ultimo_comando":   "Último comando terminal",
        "conteudo_resumo":  "O que está na tela",
        "intencao_provavel":"Intenção provável",
    }
    for chave, label in mapa.items():
        val = ctx.get(chave)
        if val and val != "null" and val is not None:
            linhas.append(f"- {label}: {val}")

    contexto_str = "\n".join(linhas) if linhas else "- Tela não identificada claramente"
    prompt = _PROMPT_SUGESTOES.replace("{contexto}", contexto_str)

    raw = consultar_ia(prompt, curto=False)
    try:
        return _parsear_json(raw)
    except Exception as e:
        log.error(f"Geração de sugestões falhou: {e} | raw: {raw[:300]}")
        return {"erro": "Não consegui gerar sugestões específicas desta vez."}

def analisar_tela_contextual(forcar=False) -> dict:
    """
    Análise em 2 passagens:
      1) Gemini Vision lê os fatos concretos da tela (texto, erros, URLs, arquivos)
      2) Gemini texto gera sugestões cirúrgicas baseadas nesses fatos reais

    Se a tela não mudou, retorna cache sem chamar a API.
    """
    global _ultimo_hash, _ultima_analise, _sugestoes_cache, _ultimo_contexto

    path, novo_hash = _capturar_tela_para_analise()
    if not path:
        return {"erro": "Pillow não disponível ou falha na captura."}

    # Cache: só re-analisa se a tela mudou de verdade
    if not forcar and not _tela_mudou_significativamente(novo_hash, _ultimo_hash) and _sugestoes_cache:
        os.remove(path)
        log.info("Tela sem mudança significativa — retornando cache.")
        return {
            "cache":    True,
            "contexto": _ultimo_contexto.get("contexto", "última análise"),
            "sugestoes": _sugestoes_cache,
            "frase_jarvis": "Aqui estão as sugestões da última análise, senhor.",
        }

    log.info("Passagem 1: extraindo contexto real da tela...")
    ctx = _extrair_contexto_da_tela(path)
    os.remove(path)

    log.info(f"Contexto extraído: app={ctx.get('app')} | "
             f"erro={ctx.get('erro_visivel')} | arquivo={ctx.get('arquivo_aberto')}")

    log.info("Passagem 2: gerando sugestões cirúrgicas...")
    dados = _gerar_sugestoes_do_contexto(ctx)

    if "erro" not in dados:
        _ultimo_hash     = novo_hash
        _ultima_analise  = time.time()
        _sugestoes_cache = dados.get("sugestoes", [])
        _ultimo_contexto = dados

        log.info(f"Sugestões geradas: {[s.get('titulo','?') for s in _sugestoes_cache]}")

    return dados

def falar_sugestoes(dados: dict, hud=None):
    """
    Fala as sugestões do JARVIS e exibe no HUD.
    """
    if "erro" in dados:
        falar(f"Não consegui analisar a tela agora, senhor. {dados['erro'][:60]}")
        return

    sugestoes = dados.get("sugestoes", [])
    contexto  = dados.get("contexto", "tela atual")
    frase     = dados.get("frase_jarvis", f"Senhor, analisei a {contexto}.")

    if hud:
        hud.safe_update("ia", "ANÁLISE", contexto[:20])

    falar_sync(frase)

    if not sugestoes:
        falar("Não identifiquei sugestões específicas para este contexto, senhor.")
        return

    falar_sync(f"Tenho {len(sugestoes)} sugestão{'ões' if len(sugestoes) > 1 else ''} para você.")

    for i, s in enumerate(sugestoes, 1):
        titulo   = s.get("titulo", f"Opção {i}")
        descricao = s.get("descricao", "")
        if hud:
            hud.safe_update("ia", f"SUGESTÃO {i}", titulo[:20])
        falar_sync(f"Opção {i}: {titulo}. {descricao}")

    falar_sync("Deseja executar alguma dessas opções? Diga o número ou o comando diretamente.")

    # Aguarda resposta por até 8 segundos
    resposta = ouvir_pergunta(timeout=8, limite=10)
    if not resposta:
        falar("Certo, fico à disposição, senhor.")
        return

    _executar_sugestao_por_voz(resposta, sugestoes, hud)

def _executar_sugestao_por_voz(resposta: str, sugestoes: list, hud=None):
    """Interpreta a resposta do usuário e executa a sugestão escolhida."""
    # Detecta número (um, dois, três / 1, 2, 3)
    mapa_nums = {
        "um": 1, "uma": 1, "primeiro": 1, "primeira": 1, "1": 1,
        "dois": 2, "duas": 2, "segundo": 2, "segunda": 2, "2": 2,
        "três": 3, "tres": 3, "terceiro": 3, "terceira": 3, "3": 3,
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
    # Se não reconheceu número, tenta como comando direto
    falar_sync("Entendido, processando seu comando.")
    if hud:
        processar_comando(resposta, hud)


# ── Monitor Proativo de Tela ─────────────────────────────
_monitor_thread  = None
_monitor_pausado = False

def iniciar_monitor_tela(hud, intervalo: int = None):
    """
    Inicia thread que monitora a tela periodicamente
    e faz sugestões automáticas quando o contexto muda.
    """
    global _monitor_ativo, _monitor_thread

    if not TELA_MONITOR_ATIVO:
        log.info("Monitor de tela desativado via .env")
        return

    if intervalo is None:
        intervalo = TELA_MONITOR_INTERVALO

    if intervalo <= 0:
        log.info("Intervalo=0 → monitor de tela desativado.")
        return

    if _monitor_ativo:
        log.info("Monitor de tela já está rodando.")
        return

    _monitor_ativo = True
    log.info(f"Monitor de tela iniciado. Intervalo: {intervalo}s")

    def _loop():
        global _monitor_ativo, _monitor_pausado, _ultimo_hash, _ultimo_contexto
        _app_anterior   = ""
        _erro_anterior  = ""

        # Espera inicial para o sistema estabilizar
        time.sleep(30)

        while _monitor_ativo:
            try:
                if not _monitor_pausado and _PIL_OK:
                    img      = ImageGrab.grab()
                    h_novo   = _hash_tela(img)

                    if not _tela_mudou_significativamente(h_novo, _ultimo_hash):
                        # Tela praticamente igual — não gasta API
                        log.info("Monitor: tela sem mudança relevante, pulando análise.")
                    else:
                        log.info("Monitor: mudança detectada, extraindo contexto...")
                        hud.safe_update("ia", "MONITORANDO", "Lendo tela...")

                        # Passagem 1 rápida: só extrai contexto (sem gerar sugestões ainda)
                        path, _ = _capturar_tela_para_analise()
                        if path:
                            ctx = _extrair_contexto_da_tela(path)
                            os.remove(path)

                            app_atual  = ctx.get("app", "")
                            erro_atual = ctx.get("erro_visivel") or ""

                            # Notifica só quando o app mudou OU apareceu um erro novo
                            app_mudou  = app_atual and app_atual != _app_anterior
                            erro_novo  = erro_atual and erro_atual != _erro_anterior

                            if app_mudou or erro_novo:
                                log.info(f"Monitor: contexto relevante mudou "
                                         f"(app={app_atual}, erro={erro_atual[:40] if erro_atual else 'nenhum'})")

                                # Passagem 2: gera sugestões só quando vale a pena
                                hud.safe_update("ia", "MONITORANDO", "Gerando sugestões...")
                                dados = _gerar_sugestoes_do_contexto(ctx)

                                if "erro" not in dados and dados.get("sugestoes"):
                                    _ultimo_hash     = h_novo
                                    _sugestoes_cache[:] = dados["sugestoes"]
                                    _ultimo_contexto.update(dados)

                                    contexto = dados.get("contexto", app_atual)

                                    # Notificação com detalhe real
                                    if erro_novo:
                                        corpo_notif = (
                                            f"Erro detectado em {app_atual}: "
                                            f"{erro_atual[:60]}... "
                                            f"· Diga 'Jarvis, o que você sugere?'"
                                        )
                                    else:
                                        corpo_notif = (
                                            f"{contexto} · "
                                            f"Diga 'Jarvis, o que você sugere?'"
                                        )
                                    notificar("JARVIS — Sugestões prontas", corpo_notif)
                                    hud.safe_update("foco", "SUGESTÃO", contexto[:20])

                                _app_anterior  = app_atual
                                _erro_anterior = erro_atual
                            else:
                                log.info("Monitor: mudança visual mas contexto igual, ignorando.")
                                _ultimo_hash = h_novo
                                hud.safe_update(False, "STANDBY", "Aguardando comando...")

            except Exception as e:
                log.error(f"Monitor tela loop: {e}")

            # Aguarda o intervalo configurado
            for _ in range(intervalo):
                if not _monitor_ativo:
                    break
                time.sleep(1)

    _monitor_thread = threading.Thread(target=_loop, daemon=True)
    _monitor_thread.start()

def pausar_monitor_tela():
    global _monitor_pausado
    _monitor_pausado = True
    log.info("Monitor de tela pausado.")

def retomar_monitor_tela():
    global _monitor_pausado
    _monitor_pausado = False
    log.info("Monitor de tela retomado.")

def parar_monitor_tela():
    global _monitor_ativo
    _monitor_ativo = False
    log.info("Monitor de tela encerrado.")


# ═══════════════════════════════════════════════════════════
#  NLU — RESOLUÇÃO DE INTENÇÃO NATURAL
#  Converte frases livres em intenções normalizadas antes
#  de processar. Ex: "quero ouvir música" → "abrir spotify"
# ═══════════════════════════════════════════════════════════

# Mapa de intenções: (padrões regex) → comando normalizado
_INTENCOES = [
    # 🎵 Música / Spotify
    (r"(quero|vou|bota|coloca|toca|ouvir|escutar|liga|abre?).*(m[úu]sica|spotify|som|faixa|playlist|álbum|album)",
     "abrir spotify"),
    (r"(para|pausa|silencia|silenciar|para a m[úu]sica|para o som)",
     "pausar"),
    (r"(próxima|pula|avança|skip|próxima faixa|pular faixa)",
     "proxima"),
    (r"(volta|anterior|faixa anterior|música anterior)",
     "voltar"),

    # 🌐 Navegador
    (r"(abre?|liga|inicia?|entra no?|vai pro?|quero usar).*(firefox|navegador|browser|internet|chrome)",
     "abrir firefox"),
    (r"(pesquisa|busca|procura|googl[ea]|quero saber|me fala sobre|o que [eé])\s+(.+)",
     "pesquisar \\2"),

    # 💻 Apps comuns
    (r"(abre?|liga|inicia?|quero usar|entra no?).*(terminal|bash|shell|linha de comando)",
     "abrir terminal"),
    (r"(abre?|liga|inicia?|quero usar|entra no?).*(vscode|vs code|visual studio|editor|código)",
     "abrir code"),
    (r"(abre?|liga|inicia?|quero usar|entra no?).*(calculadora|calcular|conta)",
     "abrir calculadora"),
    (r"(abre?|liga|inicia?|quero usar|entra no?).*(gerenciador|arquivos|pasta|explorador)",
     "abrir gerenciador"),

    # 🕐 Hora / Data
    (r"(que horas|que hora|horas s[aã]o|me diz as horas|quanto[s]? horas)",
     "que horas são"),
    (r"(que dia|qual a data|data de hoje|hoje [eé] dia)",
     "data de hoje"),

    # 🌤 Clima
    (r"(como (t[aá]|est[aá]) o (tempo|clima)|vai chover|t[aá] frio|t[aá] calor|previs[aã]o do tempo)",
     "clima"),

    # 🔇 Parar fala
    (r"(cala|cala a boca|para de falar|silêncio|chega|cancelar|para jarvis)",
     "cala boca"),

    # 📸 Tela
    (r"(tira|faz|captura|salva).*(screenshot|print|printscreen|captura de tela)",
     "screenshot"),
    (r"(analisa|descreve|o que (tem|t[aá]|aparece|vê)|me conta).*(tela|screen)",
     "analisar tela"),

    # 🔋 Sistema
    (r"(quanto[s]? (t[eê]m|t[aá]|est[aá]).*(bateria|carga)|bateria)",
     "bateria"),
    (r"(cpu|processador|mem[oó]ria|ram|uso do sistema|como (t[aá]|est[aá]) o (pc|computador|sistema))",
     "status sistema"),
]

def _resolver_intencao(comando: str) -> str:
    """
    Tenta mapear uma frase natural para um comando normalizado.
    Retorna o comando original se nenhuma intenção for encontrada.
    """
    for padrao, intencao in _INTENCOES:
        m = re.search(padrao, comando)
        if m:
            # Suporte a backreference no intencao (ex: "pesquisar \\2")
            try:
                resultado = m.expand(intencao)
            except re.error:
                resultado = intencao
            log.info(f"NLU: '{comando}' → '{resultado}'")
            return resultado
    return comando  # sem mapeamento, passa direto


# ═══════════════════════════════════════════════════════════
#  PROCESSADOR DE COMANDOS
# ═══════════════════════════════════════════════════════════
def processar_comando(comando: str, hud):
    """Recebe um comando em texto puro (minúsculas) e executa a ação."""
    comando = _resolver_intencao(comando)   # ⚡ NLU: normaliza intenção antes de processar
    log.info(f"CMD: {comando}")
    hud.safe_update("ativo", "ATIVADO", comando[:32])
    hud.push_historico(re.sub(WAKE_WORD, "", comando).strip())

    # ── Parar fala ────────────────────────────────────────
    if any(p in comando for p in ["para de falar", "cala boca", "silencio", "cancelar fala"]):
        parar_fala()

    # ── Análise contextual: o que você sugere ────────────
    elif any(p in comando for p in [
        "o que você sugere", "o que voce sugere",
        "me ajuda com o que estou fazendo",
        "sugestões", "sugestoes", "analisar contexto",
        "o que posso fazer", "me dá uma ideia", "me da uma ideia",
        "o que está na tela", "me sugere algo",
    ]):
        hud.safe_update("ia", "ANALISANDO", "Contexto da tela...")
        falar_sync("Analisando o contexto da tela, um momento, senhor.")
        dados = analisar_tela_contextual(forcar=True)
        falar_sugestoes(dados, hud)

    # ── Análise contextual: ver sugestões do cache ───────
    elif any(p in comando for p in [
        "repetir sugestões", "repetir sugestoes",
        "quais são as sugestões", "quais sao as sugestoes",
    ]):
        if _sugestoes_cache:
            hud.safe_update("ia", "SUGESTÕES", "Do cache...")
            dados = {
                "contexto":    "última análise",
                "sugestoes":   _sugestoes_cache,
                "frase_jarvis": "Aqui estão as sugestões da última análise, senhor.",
            }
            falar_sugestoes(dados, hud)
        else:
            falar("Não há sugestões em cache, senhor. Diga: Jarvis, o que você sugere?")

    # ── Monitor de tela: ligar/desligar ─────────────────
    elif any(p in comando for p in ["ativar monitor", "ligar monitor de tela", "monitorar tela"]):
        retomar_monitor_tela()
        hud.safe_update("ia", "MONITOR", "Ativo")
        falar("Monitor de tela ativado, senhor. Vou notificá-lo quando o contexto mudar.")

    elif any(p in comando for p in ["desativar monitor", "pausar monitor", "parar monitor"]):
        pausar_monitor_tela()
        hud.safe_update(False, "MONITOR", "Pausado")
        falar("Monitor de tela pausado, senhor.")

    # ── Eventos: cadastrar ────────────────────────────────
    elif any(p in comando for p in ["lembre", "adicionar evento", "cadastrar evento", "salvar data"]):
        resultado = ev_extrair_data_e_nome(comando)
        if not resultado:
            hud.safe_update("foco", "EVENTO", "Aguardando data...")
            falar_sync("Pode falar a data e o nome do evento, senhor. Por exemplo: dia 24 de junho como São João.")
            detalhe   = ouvir_pergunta(timeout=12, limite=40)
            resultado = ev_extrair_data_e_nome(detalhe) if detalhe else None
        if resultado:
            dia, mes, ano, nome = resultado
            ev_adicionar(nome, dia, mes, ano)
            ano_str = f" de {ano}" if ano else ""
            hud.safe_update("foco", "EVENTO", f"Salvo: {nome[:20]}")
            falar(f"Evento {nome} cadastrado para dia {dia} de {mes}{ano_str}, senhor.")
        else:
            falar("Não entendi a data ou o nome do evento, senhor. Tente novamente.")

    elif any(p in comando for p in ["quantos dias faltam", "quanto tempo falta",
                                     "quando é", "quando sera", "falta para"]):
        eventos    = ev_listar()
        encontrado = ev_buscar_por_voz(comando, eventos)
        if encontrado:
            hud.safe_update("foco", "CONTAGEM", encontrado["nome"][:20])
            falar(ev_frase(encontrado["nome"], encontrado["faltam"]))
        elif eventos:
            hud.safe_update("foco", "AGENDA", "Todos os eventos")
            for ev in eventos[:5]: falar(ev_frase(ev["nome"], ev["faltam"]))
        else:
            falar("Não há eventos cadastrados, senhor. Diga: lembre dia X de mês como nome do evento.")

    elif any(p in comando for p in ["listar eventos", "quais eventos", "minha agenda"]):
        eventos = ev_listar()
        if not eventos:
            falar("Agenda vazia, senhor.")
        else:
            qtd = len(eventos)
            falar(f"Você tem {qtd} evento{'s' if qtd > 1 else ''} cadastrado{'s' if qtd > 1 else ''}.")
            for ev in eventos: falar(ev_frase(ev["nome"], ev["faltam"]))
        hud.safe_update("foco", "AGENDA", f"{len(eventos)} eventos")

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

    # ── Fechar processo ───────────────────────────────────
    elif "fechar" in comando or "matar processo" in comando:
        alvo = re.sub(r"jarvis|fechar|matar processo", "", comando).strip()
        ok   = fechar_app(alvo) if alvo else False
        falar("Processo encerrado." if ok else "Não encontrei o processo, senhor.")

    elif any(p in comando for p in ["processos", "cpu alta", "o que está rodando"]):
        hud.safe_update("ia", "PROCESSOS", "Top CPU...")
        falar(f"Processos com mais CPU: {listar_processos()}.")

    elif "mover janela" in comando or "janela para" in comando:
        for d in ["esquerda", "direita", "cima", "baixo", "maximizar"]:
            if d in comando:
                mover_janela(d); falar(f"Janela movida para {d}."); break
        else:
            falar("Para onde, senhor? Esquerda, direita, cima, baixo ou maximizar.")

    elif any(p in comando for p in ["executar script", "rodar script"]):
        hud.safe_update("ia", "SCRIPT", "Aguardando...")
        falar_sync("Qual o caminho do script, senhor?")
        caminho = ouvir_pergunta(timeout=8, limite=20)
        if caminho: falar(f"Script concluído. {executar_script(caminho)[:100]}")
        else:       falar("Não captei o caminho.")

    # ── Analisar tela (legado, genérico) ─────────────────
    elif any(p in comando for p in ["analisar tela", "descrever tela"]):
        hud.safe_update("ia", "VISÃO", "Processando...")
        falar_sync("Analisando a tela, um momento.")
        falar(analisar_tela())

    elif any(p in comando for p in ["digitar", "escrever no teclado"]):
        txt = re.sub(r"jarvis|digitar|escrever no teclado", "", comando).strip()
        if txt:
            digitar_texto(txt); falar("Digitado.")
        else:
            falar_sync("O que deseja digitar?")
            resp = ouvir_pergunta(timeout=6, limite=15)
            if resp: digitar_texto(resp)

    elif any(p in comando for p in ["screenshot", "captura de tela", "printscreen"]):
        dest = tirar_screenshot()
        falar("Screenshot salvo." if dest else "Não consegui tirar o screenshot.")
        if dest: notificar("Screenshot", dest)

    elif any(p in comando for p in ["mensagem no discord", "enviar discord"]):
        hud.safe_update("discord", "DISCORD", "Aguardando...")
        falar_sync("O que devo enviar, senhor?")
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
        if nums: qtd = min(nums[0], 10)
        if filtro:
            falar_sync(f"Buscando e-mails de {filtro}, um momento.")
            hud.safe_update("ia", "E-MAIL", filtro[:15])
        else:
            falar_sync("Verificando sua caixa de entrada, um momento.")
        resultado = ler_emails(quantidade=qtd, filtro_remetente=filtro)
        hud.safe_update("ia", "E-MAIL", f"{qtd} lidos")
        falar(resultado)

    elif any(p in comando for p in ["pausar", "parar musica"]):
        subprocess.run(["playerctl", "pause"], capture_output=True)
        falar("Música pausada.")

    elif any(p in comando for p in ["proxima", "pular"]):
        subprocess.run(["playerctl", "next"], capture_output=True)
        falar("Pulando faixa.")

    elif any(p in comando for p in ["voltar", "anterior"]):
        subprocess.run(["playerctl", "previous"], capture_output=True)
        falar("Faixa anterior.")

    elif "volume" in comando:
        nums = [w for w in comando.split() if w.isdigit()]
        if nums:
            vol = min(int(nums[0]), 100)
            subprocess.run(["pactl", "set-sink-volume", "@DEFAULT_SINK@", f"{vol}%"],
                           capture_output=True)
            falar(f"Volume em {vol} por cento.")
        else:
            falar("Qual porcentagem, senhor?")

    elif any(p in comando for p in ["abrir", "iniciar"]):
        hud.safe_update(False, "ABRINDO", "App")
        falar(abrir_app(comando))

    elif any(p in comando for p in ["pesquisa", "pesquisar", "buscar"]):
        termo = re.sub(r"jarvis|pesquisa[r]?|buscar", "", comando).strip()
        if termo:
            subprocess.Popen(["xdg-open",
                               f"https://www.google.com/search?q={urllib.parse.quote(termo)}"])
            falar(f"Pesquisando {termo}.")
        else:
            falar("O que pesquisar, senhor?")

    elif "clima" in comando or "tempo" in comando:
        cidade = re.sub(r"jarvis|clima|tempo|em", "", comando).strip() or "Aracaju"
        hud.safe_update("ia", "CLIMA", cidade[:20])
        falar(obter_clima(cidade))

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

    elif any(p in comando for p in ["horas", "que horas"]):
        falar(f"São {datetime.datetime.now().strftime('%H:%M')}, senhor.")

    elif "data" in comando or "dia" in comando:
        falar(f"Hoje é {datetime.datetime.now().strftime('%d de %B de %Y')}.")

    elif any(p in comando for p in ["quanto e", "quanto é", "calcular", "calcula"]):
        expr = re.sub(r"jarvis|quanto [eé]|calcul[ae]r?", "", comando).replace("x", "*").strip()
        r    = calcular(expr)
        falar(f"Resultado: {r}." if r is not None
              else consultar_ia(f"Calcule: {expr}", curto=True))

    elif any(p in comando for p in ["foco", "estudar", "produtividade"]):
        hud.safe_update("foco", "MODO FOCO", "Produtividade ativa")
        pausar_monitor_tela()   # Pausa o monitor no modo foco para não interromper
        notificar("JARVIS", "Modo foco ativo. Monitor de tela pausado.")
        falar("Protocolo de foco iniciado. Monitor de tela pausado para não te interromper, senhor.")

    elif any(p in comando for p in ["limpar memoria", "nova conversa", "resetar ia"]):
        limpar_historico()
        falar("Memória de conversa limpa.")

    elif any(p in comando for p in ["desligar", "encerrar", "sair"]):
        parar_monitor_tela()
        falar_sync("Desligando sistemas Mark XII. Até logo, senhor.")
        hud.animacao_shutdown()

    elif any(p in comando for p in ["ativar ia", "modo ia", "tenho uma pergunta", "preciso de ajuda"]):
        hud.safe_update("ia", "IA ATIVA", "Aguardando...")
        falar_sync("Pode falar, senhor.")
        pergunta = ouvir_pergunta(timeout=10, limite=35)
        if pergunta:
            hud.safe_update("ia", "PROCESSANDO", "Gemini...")
            falar(consultar_ia(pergunta).replace("*", "").replace("#", ""))
        else:
            falar("Não captei sua pergunta.")

    # ── Fallback: resposta rápida da IA ──────────────────
    else:
        hud.safe_update("ia", "CONSULTANDO", "Gemini...")
        clean = re.sub(WAKE_WORD, "", comando).strip()
        falar(consultar_ia(clean, curto=True).replace("*", "").replace("#", ""))

    time.sleep(0.4)
    hud.safe_update(False, "STANDBY", "Aguardando comando...")


# ═══════════════════════════════════════════════════════════
#  LOOP PRINCIPAL  (chamado pela thread do HUD)
# ═══════════════════════════════════════════════════════════
def rodar_jarvis(hud):
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
    ev_anunciar_iniciais(hud, falar_sync)

    # Inicia o monitor de tela em background
    iniciar_monitor_tela(hud, intervalo=TELA_MONITOR_INTERVALO)
    if TELA_MONITOR_ATIVO and TELA_MONITOR_INTERVALO > 0:
        falar_sync(
            f"Monitor de tela ativo. Vou sugerir ações a cada "
            f"{TELA_MONITOR_INTERVALO} segundos quando o contexto mudar. "
            f"Você também pode dizer: Jarvis, o que você sugere?"
        )

    while True:
        hud.safe_update(False, "ESCUTANDO")
        comando = ouvir(timeout=4, limite=10)
        if not comando or not contem_wake_word(comando):
            continue
        processar_comando(comando, hud)