"""
jarvis_wakeword.py
Detecção de wake word offline usando Vosk.
Roda em thread separada e notifica o core via callback quando "jarvis" é detectado.

Instalação:
    pip install vosk sounddevice --break-system-packages
    # Baixar modelo pequeno em português:
    # https://alphacephei.com/vosk/models  →  vosk-model-small-pt-0.3
    # Extrair na mesma pasta do projeto: ./vosk-model-small-pt-0.3/
"""

import threading
import queue
import json
import os
import sys

# ─── Imports opcionais — falha silenciosa se não instalado ───
try:
    import sounddevice as sd
    from vosk import Model, KaldiRecognizer
    VOSK_DISPONIVEL = True
except ImportError:
    VOSK_DISPONIVEL = False


# ─────────────────────────────────────────────────────────────
#  Detector principal
# ─────────────────────────────────────────────────────────────

class WakeWordDetector:
    """
    Escuta o microfone continuamente em background.
    Quando detecta a wake word, chama on_detectado().

    Uso:
        detector = WakeWordDetector(
            wake_word="jarvis",
            on_detectado=minha_funcao,
            caminho_modelo="./vosk-model-small-pt-0.3"
        )
        detector.iniciar()
        ...
        detector.parar()
    """

    def __init__(self, wake_word: str, on_detectado, caminho_modelo: str = None,
                 taxa_amostragem: int = 16000):
        self.wake_word = wake_word.lower().strip()
        self.on_detectado = on_detectado
        self.taxa = taxa_amostragem
        self.caminho_modelo = caminho_modelo or self._detectar_modelo()
        self._parar = threading.Event()
        self._thread = None
        self._fila = queue.Queue()
        self._ativo = True           # False = detectou e está esperando o core terminar

    # ── Localiza automaticamente a pasta do modelo ──────────
    def _detectar_modelo(self) -> str:
        pastas_candidatas = [
            "./vosk-model-small-pt-0.3",
            "./vosk-model-pt",
            os.path.expanduser("~/vosk-model-small-pt-0.3"),
            "/opt/vosk/model-pt",
        ]
        for p in pastas_candidatas:
            if os.path.isdir(p):
                return p
        return "./vosk-model-small-pt-0.3"   # padrão — erro claro se não existir

    # ── Verifica dependências antes de iniciar ───────────────
    def _verificar(self) -> bool:
        if not VOSK_DISPONIVEL:
            print("[WakeWord] ERRO: vosk ou sounddevice não instalado.")
            print("           Execute: pip install vosk sounddevice --break-system-packages")
            print("           Depois baixe o modelo em: https://alphacephei.com/vosk/models")
            return False

        if not os.path.isdir(self.caminho_modelo):
            print(f"[WakeWord] ERRO: modelo Vosk não encontrado em '{self.caminho_modelo}'")
            print("           Baixe vosk-model-small-pt-0.3 e extraia nesta pasta.")
            return False

        return True

    # ── Thread de escuta ─────────────────────────────────────
    def _loop(self):
        print(f"[WakeWord] Carregando modelo: {self.caminho_modelo}")
        try:
            modelo = Model(self.caminho_modelo)
            rec = KaldiRecognizer(modelo, self.taxa)
            rec.SetWords(True)
        except Exception as e:
            print(f"[WakeWord] Falha ao carregar modelo: {e}")
            return

        print(f"[WakeWord] Pronto. Aguardando '{self.wake_word}'...")

        def callback_audio(dados, frames, tempo, status):
            if status:
                pass   # ignora overflows silenciosamente
            self._fila.put(bytes(dados))

        with sd.RawInputStream(
            samplerate=self.taxa,
            blocksize=4000,
            dtype="int16",
            channels=1,
            callback=callback_audio
        ):
            while not self._parar.is_set():
                try:
                    chunk = self._fila.get(timeout=0.5)
                except queue.Empty:
                    continue

                if not self._ativo:
                    continue    # core ocupado — descarta áudio

                if rec.AcceptWaveform(chunk):
                    resultado = json.loads(rec.Result())
                    texto = resultado.get("text", "").lower()
                else:
                    # Resultado parcial — verifica em tempo real
                    parcial = json.loads(rec.PartialResult())
                    texto = parcial.get("partial", "").lower()

                if self.wake_word in texto:
                    print(f"[WakeWord] Detectado: '{texto}'")
                    self._ativo = False          # bloqueia novas detecções
                    rec.Reset()                  # limpa buffer de áudio
                    self.on_detectado()

    # ── API pública ──────────────────────────────────────────
    def iniciar(self):
        """Inicia a detecção em thread daemon."""
        if not self._verificar():
            return False

        self._thread = threading.Thread(target=self._loop, daemon=True, name="WakeWord")
        self._thread.start()
        return True

    def parar(self):
        """Para a detecção."""
        self._parar.set()

    def reativar(self):
        """
        Chame após o core terminar de processar o comando.
        Permite que o detector volte a escutar.
        """
        self._ativo = True
        print("[WakeWord] Retomando escuta...")


# ─────────────────────────────────────────────────────────────
#  Fallback: detector simples com SpeechRecognition
#  Usado quando Vosk não está disponível
# ─────────────────────────────────────────────────────────────

class WakeWordSimples:
    """
    Fallback que usa speech_recognition (online, Google API).
    Mesmo comportamento de API que o WakeWordDetector.
    """

    def __init__(self, wake_word: str, on_detectado,
                 timeout: int = 4, limite: int = 5, **kwargs):
        self.wake_word = wake_word.lower()
        self.on_detectado = on_detectado
        self.timeout = timeout
        self.limite = limite
        self._parar = threading.Event()
        self._ativo = True
        self._thread = None

    def _loop(self):
        import speech_recognition as sr
        rec = sr.Recognizer()
        rec.dynamic_energy_threshold = True
        mic = sr.Microphone()

        print(f"[WakeWord Simples] Calibrando microfone...")
        with mic as fonte:
            rec.adjust_for_ambient_noise(fonte, duration=1.5)
        print(f"[WakeWord Simples] Pronto. Aguardando '{self.wake_word}'...")

        while not self._parar.is_set():
            if not self._ativo:
                import time; import time as t; t.sleep(0.2)
                continue
            try:
                with mic as fonte:
                    audio = rec.listen(fonte, timeout=self.timeout,
                                       phrase_time_limit=self.limite)
                texto = rec.recognize_google(audio, language="pt-BR").lower()
                print(f"[WakeWord Simples] Ouviu: '{texto}'")
                if self.wake_word in texto:
                    self._ativo = False
                    self.on_detectado()
            except Exception:
                pass   # timeout, ruído, sem internet — continua

    def iniciar(self):
        self._thread = threading.Thread(target=self._loop, daemon=True, name="WakeWordSimples")
        self._thread.start()
        return True

    def parar(self):
        self._parar.set()

    def reativar(self):
        self._ativo = True
        print("[WakeWord Simples] Retomando escuta...")


# ─────────────────────────────────────────────────────────────
#  Fábrica — escolhe o detector certo automaticamente
# ─────────────────────────────────────────────────────────────

def criar_detector(cfg: dict, on_detectado) -> object:
    """
    Retorna WakeWordDetector (Vosk) se disponível,
    caso contrário WakeWordSimples (Google STT).
    """
    ww_cfg = cfg.get("wake_word", {})
    palavra = ww_cfg.get("palavra", "jarvis")
    engine = ww_cfg.get("engine", "simples")
    modelo = ww_cfg.get("caminho_modelo", None)

    if engine == "vosk" and VOSK_DISPONIVEL:
        print("[WakeWord] Usando motor: Vosk (offline)")
        return WakeWordDetector(
            wake_word=palavra,
            on_detectado=on_detectado,
            caminho_modelo=modelo
        )
    else:
        if engine == "vosk" and not VOSK_DISPONIVEL:
            print("[WakeWord] Vosk não disponível — usando fallback Google STT")
        else:
            print("[WakeWord] Usando motor: Google STT (online)")
        return WakeWordSimples(
            wake_word=palavra,
            on_detectado=on_detectado
        )
