"""
╔══════════════════════════════════════════════════════════╗
║      J.A.R.V.I.S  —  CONTEXTO DE EXECUÇÃO               ║
║  Ponte entre plugins e jarvis_core                       ║
╚══════════════════════════════════════════════════════════╝

O JarvisContext empacota tudo que um plugin pode precisar,
sem que o plugin precise importar jarvis_core diretamente
(evita import circular, já que jarvis_core importa os plugins).

USO NO jarvis_core.py
──────────────────────
    from jarvis_context import JarvisContext
    from jarvis_plugins import processar_via_plugins

    def processar_comando(comando, hud):
        comando = _resolver_intencao(comando)
        ctx = JarvisContext(hud, falar, falar_sync, ouvir_pergunta,
                             consultar_ia, USUARIO, _confirmar)

        if processar_via_plugins(comando, ctx):
            time.sleep(0.3)
            hud.safe_update(False, "STANDBY", "Aguardando comando...")
            return

        # ... cadeia de elif legada continua normalmente ...
"""


class JarvisContext:
    """Empacota as dependências que os plugins podem chamar."""

    def __init__(self, hud, falar_fn, falar_sync_fn, ouvir_pergunta_fn,
                 consultar_ia_fn=None, usuario: str = "senhor",
                 confirmar_fn=None, notificar_fn=None,
                 processar_comando_fn=None):
        self.hud = hud
        self.falar = falar_fn
        self.falar_sync = falar_sync_fn
        self.ouvir_pergunta = ouvir_pergunta_fn
        self.consultar_ia = consultar_ia_fn
        self.usuario = usuario
        self._confirmar = confirmar_fn
        self.notificar = notificar_fn or (lambda *a, **k: None)
        # Permite que um plugin dispare outro comando programaticamente
        # (ex: "lembrete" reenviando "lembrete 5 minutos")
        self.processar_comando = processar_comando_fn

    def confirmar(self) -> str:
        """Retorna uma frase de confirmação curta e variada."""
        if self._confirmar:
            return self._confirmar()
        return f"Feito, {self.usuario}."
