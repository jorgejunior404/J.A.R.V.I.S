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
import math
from dotenv import load_dotenv


load_dotenv()
CHAVE_API = os.getenv("GEMINI_API_KEY")

try:
    cliente = genai.Client(api_key=CHAVE_API)
except Exception as e:
    print(f"Alerta: API nao configurada. Erro: {e}")

rec = sr.Recognizer()
rec.pause_threshold = 0.8
rec.dynamic_energy_threshold = True
mic = sr.Microphone()

def calibrar_microfone():
    with mic as fonte:
        rec.adjust_for_ambient_noise(fonte, duration=1.5)
    print(f"[Calibrado] Threshold: {rec.energy_threshold:.0f}")


class JarvisHUD(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.W, self.H = 220, 380
        self.geometry(f"{self.W}x{self.H}")
        self.overrideredirect(True)
        self.attributes("-topmost", True)
        self.attributes("-alpha", 0.92)
        self.configure(fg_color="#050d1a")

        sw = self.winfo_screenwidth()
        sh = self.winfo_screenheight()
        self.geometry(f"{self.W}x{self.H}+{sw - self.W - 20}+{sh - self.H - 60}")

        self.bind("<ButtonPress-1>", self.start_move)
        self.bind("<B1-Motion>", self.do_move)

        self.cv = ctk.CTkCanvas(self, width=self.W, height=self.H,
                                 bg="#050d1a", highlightthickness=0)
        self.cv.place(x=0, y=0)

        self._angulo_spin = 0
        self._bat_atual = 0.0
        self._visivel = True

        self._build_ui()
        self._animar_arcos()
        self._loop_metricas()

    def _build_ui(self):
        cx, cy = self.W // 2, 118

        self.cv.create_text(self.W // 2, 16, text="J.A.R.V.I.S",
                             font=("Courier", 11, "bold"), fill="#00BFFF")
        self.cv.create_text(self.W // 2, 30, text="MARK  X  -  SISTEMAS ATIVOS",
                             font=("Courier", 6), fill="#1a4a6b")
        self.cv.create_line(10, 40, self.W - 10, 40, fill="#0d2a3a", width=1)

        self.cv.create_arc(cx-90, cy-90, cx+90, cy+90,
                            start=200, extent=140, style="arc", outline="#0d2a3a", width=2)
        self.cv.create_arc(cx-90, cy-90, cx+90, cy+90,
                            start=20,  extent=140, style="arc", outline="#0d2a3a", width=2)

        self.arco_spin1 = self.cv.create_arc(cx-80, cy-80, cx+80, cy+80,
                                              start=0, extent=60, style="arc",
                                              outline="#00BFFF", width=2)
        self.arco_spin2 = self.cv.create_arc(cx-80, cy-80, cx+80, cy+80,
                                              start=180, extent=60, style="arc",
                                              outline="#003a5c", width=2)

        self.anel_medio = self.cv.create_oval(cx-58, cy-58, cx+58, cy+58,
                                               outline="#00BFFF", width=1)
        self.pulso = self.cv.create_oval(cx-30, cy-30, cx+30, cy+30,
                                          fill="#001a2e", outline="#00BFFF", width=2)
        self.letra_central = self.cv.create_text(cx, cy, text="AI",
                                                   font=("Courier", 14, "bold"), fill="#00BFFF")

        for frac in [0.3, 0.5, 0.7]:
            y = int(cy - 90 + frac * 180)
            self.cv.create_line(10, y, 28, y, fill="#0a2840", width=1)
            self.cv.create_line(self.W-28, y, self.W-10, y, fill="#0a2840", width=1)

        self.cv.create_line(10, 215, self.W-10, 215, fill="#0d2a3a", width=1)
        self.tag_status = self.cv.create_text(self.W//2, 229, text="STANDBY",
                                               font=("Courier", 11, "bold"), fill="#00BFFF")
        self.tag_log = self.cv.create_text(self.W//2, 245, text="Aguardando comando...",
                                            font=("Courier", 7), fill="#1a5c7a")
        self.cv.create_line(10, 256, self.W-10, 256, fill="#0d2a3a", width=1)

        self.cv.create_text(14, 268, text="SYS", font=("Courier", 7, "bold"),
                             fill="#1a4a6b", anchor="w")
        self.tag_hora = self.cv.create_text(self.W-14, 268, text="--:--",
                                             font=("Courier", 7), fill="#00BFFF", anchor="e")

        self.cv.create_text(14, 285, text="PWR", font=("Courier", 7, "bold"),
                             fill="#1a4a6b", anchor="w")
        self.cv.create_rectangle(50, 279, self.W-14, 291, outline="#0d2a3a", fill="#050d1a")
        self.bat_fill = self.cv.create_rectangle(50, 279, 50, 291, outline="", fill="#00BFFF")
        self.bat_txt  = self.cv.create_text(self.W-14, 285, text="--",
                                             font=("Courier", 7), fill="#00BFFF", anchor="e")

        self.cv.create_text(14, 303, text="CPU", font=("Courier", 7, "bold"),
                             fill="#1a4a6b", anchor="w")
        self.cv.create_rectangle(50, 297, self.W-14, 309, outline="#0d2a3a", fill="#050d1a")
        self.cpu_fill = self.cv.create_rectangle(50, 297, 50, 309, outline="", fill="#003a5c")
        self.cpu_txt  = self.cv.create_text(self.W-14, 303, text="--",
                                             font=("Courier", 7), fill="#00BFFF", anchor="e")

        self.cv.create_line(10, 318, self.W-10, 318, fill="#0d2a3a", width=1)
        self.cv.create_text(self.W//2, 330, text="CTRL+SHIFT+J  -  MOSTRAR / OCULTAR",
                             font=("Courier", 6), fill="#0d3a52")

        L = 12
        for x1,y1,x2,y2 in [(0,0,L,0),(0,0,0,L),(self.W-L,0,self.W,0),(self.W,0,self.W,L),
                              (0,self.H-L,0,self.H),(0,self.H,L,self.H),
                              (self.W-L,self.H,self.W,self.H),(self.W,self.H-L,self.W,self.H)]:
            self.cv.create_line(x1, y1, x2, y2, fill="#00BFFF", width=1)

    def _animar_arcos(self):
        self._angulo_spin = (self._angulo_spin + 2) % 360
        a = self._angulo_spin
        cx, cy = self.W // 2, 118
        self.cv.itemconfig(self.arco_spin1, start=a, extent=70)
        self.cv.itemconfig(self.arco_spin2, start=a+180, extent=70)
        escala = 1 + 0.04 * math.sin(a * math.pi / 60)
        r = int(58 * escala)
        self.cv.coords(self.anel_medio, cx-r, cy-r, cx+r, cy+r)
        self.after(30, self._animar_arcos)

    def _loop_metricas(self):
        self.cv.itemconfig(self.tag_hora, text=datetime.datetime.now().strftime("%H:%M"))
        try:
            bat = psutil.sensors_battery()
            pct = bat.percent / 100 if bat else 0.8
        except:
            pct = 0.8
        self._bat_atual += (pct - self._bat_atual) * 0.1
        larg = int((self.W - 64) * self._bat_atual)
        self.cv.coords(self.bat_fill, 50, 279, 50+larg, 291)
        self.cv.itemconfig(self.bat_fill, fill="#00BFFF" if pct > 0.3 else "#FF4444")
        self.cv.itemconfig(self.bat_txt, text=f"{int(pct*100)}%")

        cpu = psutil.cpu_percent(interval=None) / 100
        larg_cpu = int((self.W - 64) * cpu)
        self.cv.coords(self.cpu_fill, 50, 297, 50+larg_cpu, 309)
        self.cv.itemconfig(self.cpu_fill, fill="#003a5c" if cpu < 0.7 else "#FF4444")
        self.cv.itemconfig(self.cpu_txt, text=f"{int(cpu*100)}%")
        self.after(1000, self._loop_metricas)

    def safe_update(self, cor, acao, log=""):
        self.after(0, lambda: self._update_ui(cor, acao, log))

    def _update_ui(self, cor, acao, log=""):
        CORES = {True:"#FF3333", False:"#00BFFF", "ativo":"#00FF88",
                 "ia":"#BF5FFF", "foco":"#FF9900", "alerta":"#FF3333"}
        c = CORES.get(cor, cor)
        self.cv.itemconfig(self.arco_spin1,    outline=c)
        self.cv.itemconfig(self.anel_medio,    outline=c)
        self.cv.itemconfig(self.pulso,         outline=c)
        self.cv.itemconfig(self.letra_central, fill=c)
        self.cv.itemconfig(self.tag_status,    text=acao.upper(), fill=c)
        if log:
            self.cv.itemconfig(self.tag_log, text=log[:30].upper())

    def toggle_visibilidade(self):
        self.after(0, self._toggle_vis)

    def _toggle_vis(self):
        self._visivel = not self._visivel
        if self._visivel:
            self.deiconify()
            self.attributes("-alpha", 0.92)
        else:
            self.attributes("-alpha", 0.0)
            self.withdraw()

    def animacao_shutdown(self):
        self.safe_update(True, "OFFLINE", "Desativando nucleo...")
        def _fade():
            for _ in range(12):
                a = max(0, self.attributes("-alpha") - 0.07)
                self.attributes("-alpha", a)
                self.update()
                time.sleep(0.05)
            os._exit(0)
        threading.Thread(target=_fade, daemon=True).start()

    def start_move(self, e): self._dx, self._dy = e.x, e.y
    def do_move(self, e):
        x = self.winfo_x() + (e.x - self._dx)
        y = self.winfo_y() + (e.y - self._dy)
        self.geometry(f"+{x}+{y}")

def registrar_atalho(hud):
    import signal
    def handler(sig, frame):
        hud.toggle_visibilidade()
    signal.signal(signal.SIGUSR1, handler)
    


_fala_thread = None

def falar(texto):
    global _fala_thread
    def _falar():
        arq = f"/tmp/voz_{int(time.time())}.mp3"
        try:
            subprocess.run(["edge-tts","--voice","pt-BR-FranciscaNeural",
                            "--text",texto,"--write-media",arq], check=True, capture_output=True)
            subprocess.run(["mpg123","-q",arq], check=True)
        except Exception as e:
            print(f"JARVIS: {texto} | TTS: {e}")
        finally:
            if os.path.exists(arq): os.remove(arq)
    if _fala_thread and _fala_thread.is_alive():
        _fala_thread.join(timeout=15)
    _fala_thread = threading.Thread(target=_falar, daemon=True)
    _fala_thread.start()

def falar_sync(texto):
    arq = f"/tmp/voz_{int(time.time())}.mp3"
    try:
        subprocess.run(["edge-tts","--voice","pt-BR-FranciscaNeural",
                        "--text",texto,"--write-media",arq], check=True, capture_output=True)
        subprocess.run(["mpg123","-q",arq], check=True)
    except:
        print(f"JARVIS: {texto}")
    finally:
        if os.path.exists(arq): os.remove(arq)


def ouvir(timeout=4, limite=5):
    try:
        with mic as f:
            audio = rec.listen(f, timeout=timeout, phrase_time_limit=limite)
        return rec.recognize_google(audio, language="pt-BR").lower()
    except (sr.WaitTimeoutError, sr.UnknownValueError):
        return ""
    except Exception as e:
        print(f"[Erro ouvir]: {e}"); return ""

def ouvir_pergunta(timeout=8, limite=25):
    try:
        with mic as f:
            rec.adjust_for_ambient_noise(f, duration=0.3)
            audio = rec.listen(f, timeout=timeout, phrase_time_limit=limite)
        return rec.recognize_google(audio, language="pt-BR").lower()
    except (sr.WaitTimeoutError, sr.UnknownValueError):
        return ""
    except Exception as e:
        print(f"[Erro ouvir_pergunta]: {e}"); return ""


def consultar_ia(prompt, curto=False):
    try:
        if not CHAVE_API:
            return "Chave de API nao configurada, senhor."
        instrucao = "muito curto, maximo 2 frases" if curto else "detalhado mas objetivo"
        resposta = cliente.models.generate_content(
            model="gemini-2.5-flash",
            contents=f"Responda como o JARVIS, {instrucao}: {prompt}"
        )
        return resposta.text.strip() if resposta and resposta.text else "Sem resposta do nucleo."
    except Exception as e:
        print(f"[Erro IA DETALHADO]: {type(e).__name__}: {e}")
        return "Falha na conexao com o Gemini, senhor."


def rodar_jarvis(hud):
    time.sleep(1)
    hud.safe_update(False, "CALIBRANDO", "Ajustando microfone...")
    calibrar_microfone()

    agora = datetime.datetime.now()
    saudacao = ("Bom dia" if 5 <= agora.hour < 12
                else "Boa tarde" if 12 <= agora.hour < 18
                else "Boa noite")
    try:
        bat = psutil.sensors_battery().percent
    except:
        bat = "estavel"

    hud.safe_update(False, "ONLINE", f"BAT: {bat}%")
    falar_sync(f"{saudacao}, senhor. Sistemas operacionais. Bateria em {bat} por cento.")

    while True:
        hud.safe_update(False, "ESCUTANDO")
        comando = ouvir(timeout=4, limite=10)
        if not comando or "jarvis" not in comando:
            continue

        hud.safe_update("ativo", "ATIVADO", comando[:28])

        if any(p in comando for p in ["pausar", "parar musica"]):
            os.system("playerctl pause")
            falar("Musica pausada, senhor.")
            hud.safe_update(False, "PAUSADO", "Playerctl")

        elif any(p in comando for p in ["proxima", "pular"]):
            os.system("playerctl next"); falar("Pulando faixa.")

        elif any(p in comando for p in ["voltar", "anterior"]):
            os.system("playerctl previous"); falar("Retornando a faixa anterior.")

        elif any(p in comando for p in ["abrir", "iniciar"]):
            if any(p in comando for p in ["spotify", "musica"]):
                subprocess.Popen(["spotify"]); falar("Iniciando Spotify.")
            elif any(p in comando for p in ["code", "visual studio"]):
                subprocess.Popen(["code"]); falar("Abrindo ambiente de desenvolvimento.")
            elif any(p in comando for p in ["navegador", "firefox"]):
                subprocess.Popen(["firefox"]); falar("Abrindo navegador.")
            else:
                falar("Nao reconheci qual aplicativo abrir, senhor.")
            hud.safe_update(False, "ABRINDO", "App")

        elif any(p in comando for p in ["foco", "estudar"]):
            hud.safe_update("foco", "MODO FOCO", "Produtividade ativa")
            falar("Protocolo de foco iniciado. Estarei em prontidao.")

        elif any(p in comando for p in ["horas", "que horas"]):
            falar(f"Sao exatamente {datetime.datetime.now().strftime('%H:%M')}, senhor.")

        elif "data" in comando or "dia" in comando:
            falar(f"Hoje e {datetime.datetime.now().strftime('%d de %B de %Y')}, senhor.")

        elif any(p in comando for p in ["desligar", "encerrar", "sair"]):
            falar_sync("Desligando sistemas. Tenha um bom dia, senhor.")
            hud.animacao_shutdown()

        elif any(p in comando for p in ["ativar ia", "modo ia", "tenho uma pergunta"]):
            hud.safe_update("ia", "IA ATIVA", "Aguardando pergunta...")
            falar_sync("Estou ouvindo, senhor. Pode falar.")
            pergunta = ouvir_pergunta(timeout=8, limite=25)
            if pergunta:
                hud.safe_update("ia", "PROCESSANDO", "Gemini...")
                resposta = consultar_ia(pergunta, curto=False)
                falar(resposta.replace("*", "").replace("#", ""))
            else:
                falar("Nao captei sua pergunta, senhor.")

        else:
            hud.safe_update("ia", "CONSULTANDO", "Gemini...")
            comando_limpo = comando.replace("jarvis", "").strip()
            resposta = consultar_ia(comando_limpo, curto=True)
            falar(resposta.replace("*", "").replace("#", ""))

        time.sleep(0.5)
        hud.safe_update(False, "STANDBY", "Aguardando comando...")


if __name__ == "__main__":
    app = JarvisHUD()
    registrar_atalho(app)
    threading.Thread(target=rodar_jarvis, args=(app,), daemon=True).start()
    app.mainloop()
