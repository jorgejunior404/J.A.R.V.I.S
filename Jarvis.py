import speech_recognition as sr
import os
import subprocess
import threading
import customtkinter as ctk
from google import genai
import time
import datetime
import psutil
import requests
from dotenv import load_dotenv

# --- CARREGA O .env ---
load_dotenv()
CHAVE_API = os.getenv("GEMINI_API_KEY")  # ← corrigido: nome da variável

try:
    cliente = genai.Client(api_key=CHAVE_API)
except Exception as e:
    print(f"Alerta: API não configurada. Erro: {e}")

# --- OTIMIZAÇÃO 1: Reconhecedor criado UMA VEZ, fora do loop ---
rec = sr.Recognizer()
rec.pause_threshold = 0.8
rec.dynamic_energy_threshold = True
mic = sr.Microphone()

def calibrar_microfone():
    with mic as fonte:
        rec.adjust_for_ambient_noise(fonte, duration=1.5)
    print(f"[Calibrado] Threshold de energia: {rec.energy_threshold:.0f}")

class JarvisCircleHUD(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.geometry("160x250")
        self.overrideredirect(True)
        self.attributes("-topmost", True)
        self.attributes("-alpha", 0.85)
        self.configure(fg_color="#1a1a1a")

        self.bind("<ButtonPress-1>", self.start_move)
        self.bind("<B1-Motion>", self.do_move)

        self.canvas = ctk.CTkCanvas(self, width=140, height=140,
                                    bg="#1a1a1a", highlightthickness=0)
        self.canvas.pack(pady=10)

        self.ring = self.canvas.create_oval(5, 5, 135, 135, outline="#00FFFF", width=3)
        self.glow = self.canvas.create_oval(25, 25, 115, 115, outline="#004444", width=2)
        self.core = self.canvas.create_oval(50, 50, 90, 90, fill="#002222", outline="#00FFFF")

        self.label_status = ctk.CTkLabel(self, text="MARK X",
                                         font=("Orbitron", 10, "bold"), text_color="#00FFFF")
        self.label_status.pack()

        self.label_log = ctk.CTkLabel(self, text="ONLINE",
                                      font=("Consolas", 8), text_color="#55FFFF")
        self.label_log.pack()

        self.barra_bat = ctk.CTkProgressBar(self, width=120, height=4, progress_color="#00FFFF")
        self.barra_bat.pack(pady=10)

    def start_move(self, event): self.x = event.x; self.y = event.y
    def do_move(self, event):
        x = self.winfo_x() + (event.x - self.x)
        y = self.winfo_y() + (event.y - self.y)
        self.geometry(f"+{x}+{y}")

    def safe_update(self, cor, acao, log=""):
        self.after(0, lambda: self._update_ui(cor, acao, log))

    def _update_ui(self, cor, acao, log=""):
        if cor is True: cor = "#FF0000"
        elif cor is False: cor = "#00FFFF"

        self.canvas.itemconfig(self.ring, outline=cor)
        self.canvas.itemconfig(self.core, outline=cor)
        self.label_status.configure(text=acao.upper(), text_color=cor)
        if log:
            self.label_log.configure(text=log[:20].upper())

    def animacao_shutdown(self):
        self.safe_update("#FF0000", "OFFLINE", "Desativando núcleo...")
        for i in range(10):
            nova_alpha = self.attributes("-alpha") - 0.08
            if nova_alpha > 0:
                self.attributes("-alpha", nova_alpha)
            self.canvas.scale("all", 75, 75, 0.9, 0.9)
            self.update()
            time.sleep(0.05)
        os._exit(0)


# --- OTIMIZAÇÃO 2: TTS assíncrono ---
_fala_thread = None

def falar(texto):
    global _fala_thread

    def _falar():
        arquivo_audio = f"/tmp/voz_{int(time.time())}.mp3"
        try:
            subprocess.run(
                ["edge-tts", "--voice", "pt-BR-FranciscaNeural",
                 "--text", texto, "--write-media", arquivo_audio],
                check=True, capture_output=True
            )
            subprocess.run(["mpg123", "-q", arquivo_audio], check=True)
        except Exception as e:
            print(f"JARVIS: {texto} | Erro TTS: {e}")
        finally:
            if os.path.exists(arquivo_audio):
                os.remove(arquivo_audio)

    if _fala_thread and _fala_thread.is_alive():
        _fala_thread.join(timeout=15)

    _fala_thread = threading.Thread(target=_falar, daemon=True)
    _fala_thread.start()


def falar_sync(texto):
    arquivo_audio = f"/tmp/voz_{int(time.time())}.mp3"
    try:
        subprocess.run(
            ["edge-tts", "--voice", "pt-BR-FranciscaNeural",
             "--text", texto, "--write-media", arquivo_audio],
            check=True, capture_output=True
        )
        subprocess.run(["mpg123", "-q", arquivo_audio], check=True)
    except Exception as e:
        print(f"JARVIS: {texto}")
    finally:
        if os.path.exists(arquivo_audio):
            os.remove(arquivo_audio)


def ouvir(timeout=4, limite=5):
    try:
        with mic as fonte:
            audio = rec.listen(fonte, timeout=timeout, phrase_time_limit=limite)
        return rec.recognize_google(audio, language="pt-BR").lower()
    except sr.WaitTimeoutError:
        return ""
    except sr.UnknownValueError:
        return ""
    except Exception as e:
        print(f"[Erro ouvir]: {e}")
        return ""


def ouvir_pergunta(timeout=8, limite=25):
    try:
        with mic as fonte:
            rec.adjust_for_ambient_noise(fonte, duration=0.3)
            audio = rec.listen(fonte, timeout=timeout, phrase_time_limit=limite)
        return rec.recognize_google(audio, language="pt-BR").lower()
    except sr.WaitTimeoutError:
        return ""
    except sr.UnknownValueError:
        return ""
    except Exception as e:
        print(f"[Erro ouvir_pergunta]: {e}")
        return ""


def obter_clima():
    try:
        r = requests.get("http://wttr.in/Sao_Paulo?format=%t", timeout=3)
        return r.text.strip()
    except:
        return "N/A"


def consultar_ia(prompt, curto=False):
    try:
        if not CHAVE_API:
            return "Chave de API não configurada, senhor."

        instrucao = "muito curto, máximo 2 frases" if curto else "detalhado mas objetivo"
        resposta = cliente.models.generate_content(
            model="gemini-2.0-flash",
            contents=f"Responda como o JARVIS, {instrucao}: {prompt}"
        )

        if resposta and resposta.text:
            return resposta.text.strip()
        else:
            return "Senhor, não obtive resposta do núcleo de IA."

    except Exception as e:
        print(f"[Erro IA]: {e}")
        return "Houve uma falha na conexão com o Gemini, senhor."


def rodar_jarvis(hud):
    time.sleep(1)

    hud.safe_update(False, "CALIBRANDO", "Ajustando mic...")
    calibrar_microfone()

    agora = datetime.datetime.now()
    saudacao = "Bom dia" if 5 <= agora.hour < 12 else "Boa tarde" if 12 <= agora.hour < 18 else "Boa noite"
    try:
        bat = psutil.sensors_battery().percent
        hud.barra_bat.set(bat / 100)
    except:
        bat = "estável"

    hud.safe_update(False, "ONLINE", f"BAT: {bat}%")
    falar_sync(f"{saudacao}, senhor. Sistemas operacionais. Bateria em {bat} por cento.")

    while True:
        hud.safe_update(False, "ESCUTANDO")
        comando = ouvir()

        if not comando or "jarvis" not in comando:
            continue

        hud.safe_update("#00FF88", "ATIVADO", comando[:20])

        if any(p in comando for p in ["pergunta", "ia", "ajuda", "explique", "o que é", "como funciona"]):
            hud.safe_update("#A020F0", "IA ATIVA", "Aguardando...")
            falar_sync("Estou ouvindo, senhor. Pode falar.")

            pergunta = ouvir_pergunta()

            if pergunta:
                hud.safe_update("#A020F0", "PROCESSANDO", "Gemini...")
                print(f"[Pergunta]: {pergunta}")
                resposta = consultar_ia(pergunta, curto=False)
                print(f"[Resposta]: {resposta[:80]}...")
                falar(resposta)
            else:
                falar("Não captei sua pergunta, senhor. O áudio estava degradado.")

        elif any(p in comando for p in ["pausar", "parar música"]):
            os.system("playerctl pause")
            falar("Música pausada, senhor.")
            hud.safe_update(False, "PAUSADO", "Playerctl")

        elif any(p in comando for p in ["próxima", "pular"]):
            os.system("playerctl next")
            falar("Pulando faixa.")

        elif any(p in comando for p in ["voltar", "anterior"]):
            os.system("playerctl previous")
            falar("Retornando faixa.")

        elif any(p in comando for p in ["abrir", "iniciar"]):
            if any(p in comando for p in ["spotify", "música"]):
                subprocess.Popen(["spotify"])
                falar("Iniciando Spotify.")
            elif any(p in comando for p in ["code", "visual studio"]):
                subprocess.Popen(["code"])
                falar("Abrindo ambiente de desenvolvimento.")
            elif any(p in comando for p in ["navegador", "firefox"]):
                subprocess.Popen(["firefox"])
                falar("Abrindo navegador.")
            else:
                falar("Não reconheci qual aplicativo abrir, senhor.")
            hud.safe_update(False, "ABRINDO APP", "")

        elif any(p in comando for p in ["foco", "estudar"]):
            hud.safe_update("#FFA500", "MODO FOCO", "Produtividade")
            falar("Protocolo de foco iniciado. Estarei em prontidão.")

        elif any(p in comando for p in ["horas", "que horas"]):
            hora_atual = datetime.datetime.now().strftime("%H:%M")
            falar(f"São exatamente {hora_atual}, senhor.")

        elif "data" in comando or "dia" in comando:
            hoje = datetime.datetime.now().strftime("%d de %B de %Y")
            falar(f"Hoje é {hoje}, senhor.")

        elif any(p in comando for p in ["desligar", "encerrar", "sair"]):
            falar_sync("Desligando sistemas. Tenha um bom dia, senhor.")
            hud.animacao_shutdown()

        else:
            hud.safe_update("#A020F0", "CONSULTANDO", "Gemini...")
            resposta = consultar_ia(comando, curto=True)
            falar(resposta)

        time.sleep(0.5)
        hud.safe_update(False, "STANDBY", "Aguardando...")


if __name__ == "__main__":
    app = JarvisCircleHUD()
    thread = threading.Thread(target=rodar_jarvis, args=(app,), daemon=True)
    thread.start()
    app.mainloop()