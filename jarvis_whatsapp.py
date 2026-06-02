"""
╔══════════════════════════════════════════════════════════╗
║      J.A.R.V.I.S  —  MÓDULO WHATSAPP                    ║
║  Briefing diário via Evolution API (gratuito)            ║
╚══════════════════════════════════════════════════════════╝

SETUP RÁPIDO (5 minutos):
─────────────────────────
1. Instale o Docker se não tiver:
       https://docs.docker.com/engine/install/

2. Suba a Evolution API:
       docker run -d \
         --name evolution-api \
         -p 8080:8080 \
         -e AUTHENTICATION_API_KEY=jarvis-secret \
         atendai/evolution-api:latest

3. Crie uma instância e conecte seu WhatsApp:
       http://localhost:8080   → use a chave "jarvis-secret"
       → Criar instância → nome: "jarvis"
       → Escanear QR Code com seu WhatsApp

4. Adicione ao .env:
       WA_API_URL       = http://localhost:8080
       WA_API_KEY       = jarvis-secret
       WA_INSTANCE      = jarvis
       WA_DESTINATARIO  = 5579999999999   ← seu número com DDI+DDD, sem +
       BRIEFING_WA_HORA = 07:00           ← horário do envio diário

5. Adicione ao jarvis_core.py (PATCH abaixo)

Variáveis no .env:
    WA_API_URL       = http://localhost:8080
    WA_API_KEY       = jarvis-secret
    WA_INSTANCE      = jarvis
    WA_DESTINATARIO  = 5579999999999
    BRIEFING_WA_HORA = 07:00
"""

import os
import json
import time
import logging
import threading
import datetime
import urllib.request
import urllib.error

from dotenv import load_dotenv

load_dotenv()

log = logging.getLogger("JARVIS.WhatsApp")

# ── Configurações ─────────────────────────────────────────
WA_API_URL      = os.getenv("WA_API_URL",      "http://localhost:8080").rstrip("/")
WA_API_KEY      = os.getenv("WA_API_KEY",      "")
WA_INSTANCE     = os.getenv("WA_INSTANCE",     "jarvis")
WA_DESTINATARIO = os.getenv("WA_DESTINATARIO", "")   # ex: 5579999999999
BRIEFING_WA_HORA = os.getenv("BRIEFING_WA_HORA", "07:00")


# ═══════════════════════════════════════════════════════════
#  ENVIO DE MENSAGEM
# ═══════════════════════════════════════════════════════════

def _formatar_numero(numero: str) -> str:
    """Garante formato correto: só dígitos + @s.whatsapp.net"""
    digitos = "".join(c for c in numero if c.isdigit())
    if not digitos:
        raise ValueError("Número de WhatsApp inválido ou não configurado no .env (WA_DESTINATARIO).")
    return f"{digitos}@c.us"


def enviar_whatsapp(mensagem: str, destinatario: str = None) -> bool:
    """
    Envia uma mensagem de texto pelo WhatsApp via Evolution API.

    Args:
        mensagem:     Texto a ser enviado.
        destinatario: Número destino. Se None, usa WA_DESTINATARIO do .env.

    Returns:
        True se enviado com sucesso, False caso contrário.
    """
    numero = destinatario or WA_DESTINATARIO
    if not numero:
        log.error("WA_DESTINATARIO não configurado no .env.")
        return False
    if not WA_API_KEY:
        log.error("WA_API_KEY não configurado no .env.")
        return False

    try:
        numero_fmt = _formatar_numero(numero)
        url        = f"{WA_API_URL}/message/sendText/{WA_INSTANCE}"
        payload    = json.dumps({
            "number":      numero_fmt,
            "textMessage": {"text": mensagem},
            "delay":       0,
        }).encode("utf-8")

        req = urllib.request.Request(
            url,
            data=payload,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "apikey":       WA_API_KEY,
            },
        )

        with urllib.request.urlopen(req, timeout=10) as resp:
            body = json.loads(resp.read())
            if body.get("key") or body.get("status") == "PENDING":
                log.info(f"WhatsApp enviado para {numero}.")
                return True
            log.warning(f"Resposta inesperada da API: {body}")
            return False

    except urllib.error.URLError as e:
        log.error(f"WhatsApp — erro de conexão: {e}. Evolution API está rodando?")
        return False
    except Exception as e:
        log.error(f"WhatsApp — erro ao enviar: {e}")
        return False


# ═══════════════════════════════════════════════════════════
#  FORMATAÇÃO DO BRIEFING PARA WHATSAPP
# ═══════════════════════════════════════════════════════════

def _formatar_briefing_wa(briefing_texto: str, nome: str = "senhor") -> str:
    """
    Adapta o texto do briefing (feito para voz) para WhatsApp,
    adicionando emojis e formatação mais visual.
    """
    agora     = datetime.datetime.now()
    hora_str  = agora.strftime("%H:%M")
    data_str  = agora.strftime("%d/%m/%Y")
    dia_semana = ["Segunda", "Terça", "Quarta", "Quinta",
                  "Sexta", "Sábado", "Domingo"][agora.weekday()]

    linhas = [
        "╔══════════════════════╗",
        f"║  🤖 J.A.R.V.I.S  —  MARK XIII  ║",
        "╚══════════════════════╝",
        "",
        f"☀️  *Bom dia, {nome}!*",
        f"📅  *{dia_semana}, {data_str}*  •  🕐 {hora_str}",
        "",
        "─────────────────────────",
        "",
    ]

    # Processa o texto de voz e converte em seções formatadas
    texto = briefing_texto

    # Remove saudação duplicada (já adicionada acima)
    import re
    texto = re.sub(
        r"^Bom dia[^.]+\.\s*", "", texto, flags=re.IGNORECASE
    ).strip()

    # Detecta e formata seções
    secoes = {
        r"(sula[s]? de hoje|você tem .*(cálculo|álgebra|física|programação|aula))": "📚 *AULAS*",
        r"(treino de corrida|corrida|running|km com pace)": "🏃 *TREINO*",
        r"(tarefa[s]? para hoje|tarefa pendente)": "✅ *TAREFAS*",
        r"(compromiss[o|os]|evento[s]? de hoje|agenda)": "📋 *AGENDA*",
        r"(não consegui acessar|agenda (está )?(limpa|livre))": "📭 *AGENDA*",
    }

    # Divide o texto em frases
    frases = [f.strip() for f in re.split(r'(?<=[.!?])\s+', texto) if f.strip()]

    categoria_atual = None
    buffer = []
    secoes_formatadas = {}

    for frase in frases:
        categoria = None
        for padrao, titulo in secoes.items():
            if re.search(padrao, frase, re.IGNORECASE):
                categoria = titulo
                break

        if categoria:
            if buffer and categoria_atual:
                secoes_formatadas.setdefault(categoria_atual, []).extend(buffer)
            if categoria != categoria_atual:
                buffer = [frase]
                categoria_atual = categoria
            else:
                buffer.append(frase)
        else:
            if categoria_atual:
                buffer.append(frase)
            # Frases sem categoria ficam em "outros"
            elif not categoria_atual:
                secoes_formatadas.setdefault("📌 *DESTAQUE*", []).append(frase)

    if buffer and categoria_atual:
        secoes_formatadas.setdefault(categoria_atual, []).extend(buffer)

    # Monta o corpo
    if secoes_formatadas:
        for titulo, fs in secoes_formatadas.items():
            linhas.append(titulo)
            for f in fs:
                linhas.append(f"  • {f}")
            linhas.append("")
    else:
        # Fallback: inclui o texto completo sem formatação especial
        linhas.append("📌 *RESUMO DO DIA*")
        for f in frases:
            linhas.append(f"  • {f}")
        linhas.append("")

    linhas += [
        "─────────────────────────",
        "💬 _Diga_ *Jarvis, briefing* _para mais detalhes por voz._",
        "",
        f"🤖 JARVIS Mark XIII  •  {hora_str}",
    ]

    return "\n".join(linhas)


# ═══════════════════════════════════════════════════════════
#  ENVIO DO BRIEFING
# ═══════════════════════════════════════════════════════════

def enviar_briefing_whatsapp(nome: str = "senhor",
                              destinatario: str = None) -> bool:
    """
    Gera e envia o briefing matinal pelo WhatsApp.
    Importa o gerador de briefing do módulo Google Calendar se disponível,
    caso contrário usa um briefing básico de sistema.
    """
    try:
        from jarvis_gcalendar import gerar_briefing_matinal
        briefing_texto = gerar_briefing_matinal(nome)
    except ImportError:
        # Fallback sem Google Calendar
        agora = datetime.datetime.now()
        briefing_texto = (
            f"Bom dia, {nome}. São {agora.strftime('%H:%M')}. "
            f"Sistemas JARVIS operacionais. "
            f"Google Calendar não configurado — instale jarvis_gcalendar.py para agenda completa."
        )
    except Exception as e:
        log.error(f"Erro ao gerar briefing do GCal: {e}")
        agora = datetime.datetime.now()
        briefing_texto = (
            f"Bom dia, {nome}. São {agora.strftime('%H:%M')}. "
            f"Não consegui acessar o Google Calendar agora, mas sistemas JARVIS estão operacionais."
        )

    mensagem = _formatar_briefing_wa(briefing_texto, nome)
    sucesso  = enviar_whatsapp(mensagem, destinatario)

    if sucesso:
        log.info("Briefing WhatsApp enviado com sucesso.")
    else:
        log.warning("Falha ao enviar briefing pelo WhatsApp.")

    return sucesso


# ═══════════════════════════════════════════════════════════
#  AGENDADOR DIÁRIO
# ═══════════════════════════════════════════════════════════

def iniciar_briefing_whatsapp(nome: str = "senhor",
                               horario: str = None,
                               destinatario: str = None):
    """
    Inicia uma thread que envia o briefing automaticamente
    todo dia no horário configurado.

    Args:
        nome:         Nome do usuário para personalização.
        horario:      "HH:MM". Se None, usa BRIEFING_WA_HORA do .env.
        destinatario: Número destino. Se None, usa WA_DESTINATARIO do .env.
    """
    horario     = horario or BRIEFING_WA_HORA
    destinatario = destinatario or WA_DESTINATARIO

    try:
        hora_alvo, min_alvo = map(int, horario.split(":"))
    except Exception:
        log.error(f"Horário inválido: '{horario}'. Use formato HH:MM.")
        return

    def _loop():
        ultimo_dia = None
        log.info(f"Agendador WhatsApp briefing iniciado → {horario} todos os dias.")
        while True:
            agora = datetime.datetime.now()
            hoje  = agora.date()

            if (agora.hour   == hora_alvo
                    and agora.minute == min_alvo
                    and ultimo_dia   != hoje):
                ultimo_dia = hoje
                log.info("Disparando briefing WhatsApp...")
                try:
                    enviar_briefing_whatsapp(nome=nome, destinatario=destinatario)
                except Exception as e:
                    log.error(f"Erro no briefing WhatsApp agendado: {e}")

            time.sleep(30)  # verifica a cada 30s

    t = threading.Thread(target=_loop, daemon=True, name="BriefingWhatsApp")
    t.start()


# ═══════════════════════════════════════════════════════════
#  TESTE RÁPIDO (rode direto para testar)
# ═══════════════════════════════════════════════════════════

if __name__ == "__main__":
    import sys

    print("╔══════════════════════════════════════════════╗")
    print("║   JARVIS WhatsApp — Teste de envio           ║")
    print("╚══════════════════════════════════════════════╝")
    print()

    if not WA_API_KEY:
        print("❌ WA_API_KEY não configurado no .env")
        sys.exit(1)
    if not WA_DESTINATARIO:
        print("❌ WA_DESTINATARIO não configurado no .env")
        sys.exit(1)

    print(f"📡 API:         {WA_API_URL}")
    print(f"📱 Instância:   {WA_INSTANCE}")
    print(f"📞 Destino:     {WA_DESTINATARIO}")
    print(f"⏰ Horário:     {BRIEFING_WA_HORA}")
    print()
    print("Enviando briefing de teste...")

    ok = enviar_briefing_whatsapp(nome="Jorge")
    if ok:
        print("✅ Briefing enviado com sucesso! Verifique seu WhatsApp.")
    else:
        print("❌ Falha no envio. Verifique o log e se a Evolution API está rodando.")
        print("   Teste: curl http://localhost:8080  (deve responder)")