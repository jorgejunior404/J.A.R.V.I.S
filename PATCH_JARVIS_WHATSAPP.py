"""
╔══════════════════════════════════════════════════════════╗
║   JARVIS.PY  —  PATCH DE INTEGRAÇÃO WHATSAPP            ║
║   Aplique as 3 alterações abaixo no jarvis_core.py      ║
╚══════════════════════════════════════════════════════════╝

═══════════════════════════════════════════════════════════
 PATCH 1 — IMPORTS  (adicione após os imports do GCal,
           por volta da linha 37)
═══════════════════════════════════════════════════════════

from jarvis_whatsapp import (
    enviar_whatsapp,
    enviar_briefing_whatsapp,
    iniciar_briefing_whatsapp,
)


═══════════════════════════════════════════════════════════
 PATCH 2 — NOVOS COMANDOS  (adicione em processar_comando,
           ANTES do bloco "elif 'clima' in comando")
═══════════════════════════════════════════════════════════

    # ── Briefing no WhatsApp (manual por voz) ────────────
    elif any(p in comando for p in [
        "manda briefing no whatsapp", "envia briefing whatsapp",
        "briefing pelo whatsapp", "manda no whatsapp",
    ]):
        hud.safe_update("foco", "WHATSAPP", "Enviando...")
        falar_sync("Preparando e enviando briefing pelo WhatsApp.")
        ok = enviar_briefing_whatsapp(nome=SEU_NOME)
        falar("Briefing enviado com sucesso." if ok
              else f"Não consegui enviar pelo WhatsApp agora, {USUARIO}.")

    # ── Mensagem livre no WhatsApp ────────────────────────
    elif any(p in comando for p in [
        "mensagem no whatsapp", "manda no whatsapp", "envia whatsapp",
    ]):
        hud.safe_update("foco", "WHATSAPP", "Aguardando...")
        falar_sync(f"O que mando pelo WhatsApp, {USUARIO}?")
        msg = ouvir_pergunta(timeout=10, limite=40)
        if msg:
            ok = enviar_whatsapp(msg)
            falar("Enviado." if ok else "Falha no envio, verifique a conexão.")
        else:
            falar("Não captei a mensagem.")


═══════════════════════════════════════════════════════════
 PATCH 3 — INICIALIZAÇÃO  (adicione em rodar_jarvis,
           logo após o iniciar_briefing_automatico do GCal,
           por volta da linha 1355)
═══════════════════════════════════════════════════════════

    # ── Inicia briefing automático pelo WhatsApp ─────────
    iniciar_briefing_whatsapp(
        nome=SEU_NOME,
        horario=os.getenv("BRIEFING_WA_HORA", "07:00"),
    )


═══════════════════════════════════════════════════════════
 ARQUIVO .env ATUALIZADO  (adicione ao seu .env existente)
═══════════════════════════════════════════════════════════

# WhatsApp via Evolution API
WA_API_URL       = http://localhost:8080
WA_API_KEY       = jarvis-secret
WA_INSTANCE      = jarvis
WA_DESTINATARIO  = 5579999999999
BRIEFING_WA_HORA = 07:00


═══════════════════════════════════════════════════════════
 SETUP COMPLETO — PASSO A PASSO
═══════════════════════════════════════════════════════════

── ETAPA 1: Instalar Docker (se não tiver) ───────────────

  curl -fsSL https://get.docker.com | sh
  sudo usermod -aG docker $USER
  (reinicie o terminal ou faça logout/login)


── ETAPA 2: Subir a Evolution API ────────────────────────

  docker run -d \
    --name evolution-api \
    --restart always \
    -p 8080:8080 \
    -e AUTHENTICATION_API_KEY=jarvis-secret \
    -e DATABASE_ENABLED=false \
    atendai/evolution-api:latest

  Confirmar que está rodando:
    docker ps
    curl http://localhost:8080
    (deve retornar {"status":"ok"} ou similar)


── ETAPA 3: Criar instância e conectar WhatsApp ──────────

  # Criar instância:
  curl -X POST http://localhost:8080/instance/create \
    -H "Content-Type: application/json" \
    -H "apikey: jarvis-secret" \
    -d '{"instanceName":"jarvis","qrcode":true}'

  # Pegar QR Code para escanear:
  Abra no navegador:
    http://localhost:8080/instance/connect/jarvis
  (Header: apikey: jarvis-secret)

  OU use o Swagger UI:
    http://localhost:8080/docs

  Escaneie o QR Code com seu WhatsApp
  (igual ao WhatsApp Web)


── ETAPA 4: Testar o envio ───────────────────────────────

  # Coloque o número no .env primeiro, depois:
  python jarvis_whatsapp.py

  # Deve aparecer: ✅ Briefing enviado com sucesso!


── ETAPA 5: Aplicar os patches e reiniciar o JARVIS ──────

  Edite jarvis_core.py com os 3 patches acima e reinicie.


═══════════════════════════════════════════════════════════
 EXEMPLOS DE COMANDOS DE VOZ
═══════════════════════════════════════════════════════════

"Jarvis, manda briefing no WhatsApp"
→ Envia imediatamente o briefing formatado.

"Jarvis, manda no WhatsApp"
→ Pergunta o que você quer enviar e manda a mensagem.

Automático às 07:00 todos os dias:
→ JARVIS envia sozinho sem você precisar pedir.


═══════════════════════════════════════════════════════════
 EXEMPLO DE MENSAGEM ENVIADA
═══════════════════════════════════════════════════════════

╔══════════════════════╗
║  🤖 J.A.R.V.I.S  —  MARK XIII  ║
╚══════════════════════╝

☀️  *Bom dia, Jorge!*
📅  *Quinta, 24/05/2026*  •  🕐 07:00

─────────────────────────

📚 *AULAS*
  • Você tem Cálculo Diferencial às 08:00.
  • Álgebra Linear às 10:00.

🏃 *TREINO*
  • Seu treino de corrida está marcado para as 18:00.
  • Meta de hoje: 5 km com pace de 5:00 min/km.

✅ *TAREFAS*
  • Você tem uma tarefa para hoje: Entregar relatório de Física.

─────────────────────────
💬 _Diga_ *Jarvis, briefing* _para mais detalhes por voz._

🤖 JARVIS Mark XIII  •  07:00


═══════════════════════════════════════════════════════════
 TROUBLESHOOTING
═══════════════════════════════════════════════════════════

Erro: "Connection refused" ao enviar
  → Evolution API não está rodando.
  → Verifique: docker ps | grep evolution
  → Inicie: docker start evolution-api

Erro: "Unauthorized" / 401
  → WA_API_KEY incorreta no .env.
  → Deve ser igual ao AUTHENTICATION_API_KEY do docker run.

Erro: "instance not found"
  → WA_INSTANCE incorreto ou instância não criada.
  → Refaça a Etapa 3.

WhatsApp desconectou (sessão expirou):
  → Escaneie o QR Code novamente (Etapa 3).
  → Isso acontece se o WhatsApp ficar sem internet por muito tempo.

Formato do número (WA_DESTINATARIO):
  → Deve ser: código do país + DDD + número, SEM o +
  → Exemplo Brasil: 5579912345678
  → NÃO use: +55 79 9 1234-5678
"""
