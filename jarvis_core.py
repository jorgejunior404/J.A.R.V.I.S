"""
╔══════════════════════════════════════════════════════════╗
║         J.A.R.V.I.S  —  MARK XII  ·  CORE               ║
║  Microfone · TTS · IA · Automações · Integrações         ║
╚══════════════════════════════════════════════════════════╝

Não execute este arquivo diretamente.
Execute: python jarvis_hud.py

Variáveis no .env:
    GEMINI_API_KEY     = sua_chave
    VOZ                = pt-BR-AntonioNeural
    PITCH              = 0.91
    WAKE_WORD          = jarvis
    WEATHER_API_KEY    = chave_openweathermap
    DISCORD_TOKEN      = token_do_bot
    DISCORD_CHANNEL_ID = id_do_canal
    EMAIL_USER         = seu@email.com
    EMAIL_PASS         = sua_senha
    EMAIL_IMAP         = imap.gmail.com
"""

# ═══════════════════════════════════════════════════════════
#  IMPORTS
# ═══════════════════════════════════════════════════════════
import os, re, json, math, time, datetime
import logging, subprocess, threading, urllib.request, urllib.parse
import imaplib, email
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
EMAIL_USER         = os.getenv("EMAIL_USER", "")
EMAIL_PASS         = os.getenv("EMAIL_PASS", "")
EMAIL_IMAP         = os.getenv("EMAIL_IMAP", "imap.gmail.com")

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
            model="gemini-2.5-flash", contents=conteudo)
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
            imagem_path=path)
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
#  PROCESSADOR DE COMANDOS
# ═══════════════════════════════════════════════════════════
def processar_comando(comando: str, hud):
    """Recebe um comando em texto puro (minúsculas) e executa a ação."""
    log.info(f"CMD: {comando}")
    hud.safe_update("ativo", "ATIVADO", comando[:32])
    hud.push_historico(re.sub(WAKE_WORD, "", comando).strip())

    if any(p in comando for p in ["para de falar", "cala boca", "silencio", "cancelar fala"]):
        parar_fala()

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

    elif any(p in comando for p in ["analisar tela", "o que tem na tela", "descrever tela"]):
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
        import subprocess as _sp
        _sp.run(["playerctl", "pause"], capture_output=True)
        falar("Música pausada.")

    elif any(p in comando for p in ["proxima", "pular"]):
        import subprocess as _sp
        _sp.run(["playerctl", "next"], capture_output=True)
        falar("Pulando faixa.")

    elif any(p in comando for p in ["voltar", "anterior"]):
        import subprocess as _sp
        _sp.run(["playerctl", "previous"], capture_output=True)
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
        notificar("JARVIS", "Modo foco ativo.")
        falar("Protocolo de foco iniciado. Notificações silenciadas.")

    elif any(p in comando for p in ["limpar memoria", "nova conversa", "resetar ia"]):
        limpar_historico()
        falar("Memória de conversa limpa.")

    elif any(p in comando for p in ["desligar", "encerrar", "sair"]):
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

    while True:
        hud.safe_update(False, "ESCUTANDO")
        comando = ouvir(timeout=4, limite=10)
        if not comando or not contem_wake_word(comando):
            continue
        processar_comando(comando, hud)