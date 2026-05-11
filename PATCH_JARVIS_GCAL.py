"""
╔══════════════════════════════════════════════════════════╗
║   JARVIS.PY  —  PATCH DE INTEGRAÇÃO GOOGLE CALENDAR     ║
║   Aplique as 4 alterações abaixo no seu Jarvis.py        ║
╚══════════════════════════════════════════════════════════╝

═══════════════════════════════════════════════════════════
 PATCH 1 — IMPORTS  (adicione logo após os imports atuais,
           por volta da linha 35)
═══════════════════════════════════════════════════════════

from jarvis_gcalendar import (
    gerar_briefing_matinal,
    falar_proximos_eventos,
    falar_agenda_hoje,
    falar_tarefas,
    iniciar_briefing_automatico,
    buscar_proximos_eventos,
    _autenticar,
)


═══════════════════════════════════════════════════════════
 PATCH 2 — VARIÁVEIS .env  (adicione em CONFIGURAÇÃO,
           por volta da linha 57)
═══════════════════════════════════════════════════════════

SEU_NOME            = os.getenv("SEU_NOME",             "Jorge")
BRIEFING_HORARIO    = os.getenv("BRIEFING_HORARIO",     "07:00")


═══════════════════════════════════════════════════════════
 PATCH 3 — NOVOS COMANDOS  (adicione em processar_comando,
           ANTES do bloco "elif 'clima' in comando",
           por volta da linha 1258)
═══════════════════════════════════════════════════════════

    # ── Briefing matinal manual ───────────────────────────
    elif any(p in comando for p in ["briefing", "resumo do dia", "como está minha agenda",
                                     "o que tenho hoje", "minha agenda"]):
        hud.safe_update("foco", "BRIEFING", "Carregando...")
        falar_sync("Preparando seu briefing, um momento.")
        texto = gerar_briefing_matinal(SEU_NOME)
        falar(texto)

    # ── Próximos eventos ──────────────────────────────────
    elif any(p in comando for p in ["próximos eventos", "proximos eventos",
                                     "o que tenho agora", "próxima aula", "proxima aula"]):
        hud.safe_update("foco", "AGENDA", "Buscando...")
        falar(falar_proximos_eventos(horas=3))

    # ── Agenda completa do dia ────────────────────────────
    elif any(p in comando for p in ["agenda de hoje", "eventos de hoje",
                                     "calendário hoje", "calendario hoje"]):
        hud.safe_update("foco", "AGENDA", "Carregando...")
        falar(falar_agenda_hoje())

    # ── Tarefas pendentes ─────────────────────────────────
    elif any(p in comando for p in ["minhas tarefas", "tarefas pendentes",
                                     "o que tenho para fazer", "lista de tarefas"]):
        hud.safe_update("foco", "TAREFAS", "Buscando...")
        falar(falar_tarefas())


═══════════════════════════════════════════════════════════
 PATCH 4 — INICIALIZAÇÃO  (adicione em rodar_jarvis,
           APÓS a linha ev_anunciar_iniciais(hud, falar_sync),
           por volta da linha 1351)
═══════════════════════════════════════════════════════════

    # ── Inicia briefing automático ───────────────────────
    iniciar_briefing_automatico(hud, falar_sync,
                                 nome=SEU_NOME,
                                 horario=BRIEFING_HORARIO)

    # ── Testa conexão Google silenciosamente ─────────────
    def _testar_gcal():
        cal, tasks = _autenticar()
        if cal and tasks:
            log.info("Google Calendar/Tasks: conexão OK.")
        else:
            log.warning("Google Calendar/Tasks: sem conexão (credentials.json ausente?).")
    threading.Thread(target=_testar_gcal, daemon=True).start()


═══════════════════════════════════════════════════════════
 ARQUIVO .env ATUALIZADO  (adicione ao seu .env existente)
═══════════════════════════════════════════════════════════

# Google Calendar / Tasks
GCAL_CREDENTIALS_FILE = credentials.json
GCAL_TOKEN_FILE       = token.json

# Dados pessoais para briefing
SEU_NOME              = Jorge
BRIEFING_HORARIO      = 07:00

# Metas de corrida
CORRIDA_PACE_META     = 5:00
CORRIDA_KM_META       = 5

# Se você usa calendários separados para UFS e corrida,
# coloque os IDs aqui (veja em calendar.google.com → Configurações do calendário)
# UFS_CAL_ID          = xxxxxxxxxx@group.calendar.google.com
# CORRIDA_CALENDAR_ID = xxxxxxxxxx@group.calendar.google.com


═══════════════════════════════════════════════════════════
 INSTALAÇÃO DAS DEPENDÊNCIAS
═══════════════════════════════════════════════════════════

pip install google-auth google-auth-oauthlib google-auth-httplib2 google-api-python-client


═══════════════════════════════════════════════════════════
 COMO CONFIGURAR O GOOGLE CLOUD (passo a passo)
═══════════════════════════════════════════════════════════

1. Acesse: https://console.cloud.google.com
2. Crie um projeto novo (ex: "JARVIS")
3. Menu lateral → APIs e serviços → Biblioteca
   → Ative: "Google Calendar API"
   → Ative: "Tasks API"
4. APIs e serviços → Credenciais
   → "+ Criar credenciais" → ID do cliente OAuth 2.0
   → Tipo: "Aplicativo para Desktop"
   → Baixe o JSON → renomeie para "credentials.json"
   → Coloque na mesma pasta do Jarvis.py
5. Tela de consentimento OAuth → adicione seu email como usuário de teste
6. Na 1ª execução do JARVIS, um navegador abrirá para você autorizar
   → O token.json é salvo automaticamente para as próximas vezes


═══════════════════════════════════════════════════════════
 EXEMPLOS DE COMANDOS DE VOZ
═══════════════════════════════════════════════════════════

"Jarvis, briefing"
→ Bom dia, Jorge. São 07:00, quinta-feira, 7 de maio de 2025.
  Você tem Cálculo Diferencial às 08:00 e Álgebra Linear às 10:00.
  Seu treino de corrida está marcado para as 18:00.
  Meta de hoje: 5 km com pace de 5:00 minutos por quilômetro.
  Tarefa para hoje: Entregar relatório de Física.
  Tenha um ótimo dia, senhor.

"Jarvis, próxima aula"
→ Nas próximas 3 horas: Cálculo às 08:00.

"Jarvis, agenda de hoje"
→ Você tem 3 eventos hoje. Cálculo às 08:00. Álgebra às 10:00. Corrida às 18:00.

"Jarvis, minhas tarefas"
→ Tarefas de hoje: Entregar relatório de Física. Outras pendências: Estudar para prova de Vetorial.
"""
