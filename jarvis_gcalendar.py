"""
╔══════════════════════════════════════════════════════════╗
║      J.A.R.V.I.S  —  MÓDULO GOOGLE CALENDAR/TASKS       ║
║  Briefing matinal · Aulas UFS · Metas de corrida         ║
╚══════════════════════════════════════════════════════════╝

Dependências adicionais:
    pip install google-auth google-auth-oauthlib google-auth-httplib2
               google-api-python-client

Variáveis no .env:
    GCAL_CREDENTIALS_FILE = credentials.json  (OAuth 2.0 do Google Cloud Console)
    GCAL_TOKEN_FILE       = token.json        (gerado automaticamente no 1º login)
    CORRIDA_PACE_META     = 5:00              (pace alvo em min/km, opcional)
    CORRIDA_KM_META       = 5                 (km alvo por treino, opcional)
    CORRIDA_CALENDAR_ID   = primary           (ID do calendário de treinos, opcional)
    UFS_CALENDAR_ID       = primary           (ID do calendário da UFS, opcional)

Como obter credentials.json:
    1. Acesse console.cloud.google.com
    2. Crie um projeto → Ative Google Calendar API e Tasks API
    3. Credenciais → Criar credencial → ID do cliente OAuth 2.0 → Aplicativo para Desktop
    4. Baixe o JSON e salve como credentials.json
    5. Na 1ª execução o JARVIS abrirá o navegador para autenticar
"""

import os
import json
import re
import datetime
import logging
import threading
import time

from dotenv import load_dotenv

load_dotenv()

log = logging.getLogger("JARVIS.GCal")

# ── Configurações ────────────────────────────────────────────
CREDENTIALS_FILE  = os.getenv("GCAL_CREDENTIALS_FILE", "credentials.json")
TOKEN_FILE        = os.getenv("GCAL_TOKEN_FILE",        "token.json")
PACE_META         = os.getenv("CORRIDA_PACE_META",      "5:00")
KM_META           = int(os.getenv("CORRIDA_KM_META",    "5"))
CORRIDA_CAL_ID    = os.getenv("CORRIDA_CALENDAR_ID",    "primary")
UFS_CAL_ID        = os.getenv("UFS_CAL_ID",             "primary")

# Escopos necessários (leitura + escrita)
SCOPES = [
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/tasks",
]

# ── Palavras-chave para detectar aulas/eventos UFS ──────────
_PALAVRAS_UFS = [
    "cálculo", "calculo", "algebra", "álgebra", "física", "fisica",
    "programação", "programacao", "estrutura", "algoritmo", "circuito",
    "eletromagnetismo", "vetorial", "diferencial", "integral",
    "laboratório", "laboratorio", "seminário", "seminario",
    "aula", "prova", "trabalho", "entrega", "apresentação",
    "monitoria", "tutoria", "ufs", "universidade",
]

# ── Palavras-chave para detectar treinos de corrida ─────────
_PALAVRAS_CORRIDA = [
    "corrida", "correr", "treino", "running", "pace", "km",
    "maratona", "meia maratona", "5k", "10k", "intervalado",
    "fartlek", "tiro", "rodagem", "recuperação",
]


# ═══════════════════════════════════════════════════════════
#  AUTENTICAÇÃO GOOGLE
# ═══════════════════════════════════════════════════════════
_servicos = {}  # cache dos serviços autenticados

def _autenticar():
    """
    Autentica via OAuth 2.0. Na primeira vez abre o navegador.
    Retorna (calendar_service, tasks_service) ou (None, None) em caso de erro.
    """
    global _servicos
    if "calendar" in _servicos and "tasks" in _servicos:
        return _servicos["calendar"], _servicos["tasks"]

    try:
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
        from google.auth.transport.requests import Request
        from googleapiclient.discovery import build

        creds = None

        # Tenta carregar token salvo
        if os.path.exists(TOKEN_FILE):
            creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)

        # Se não há token válido, autentica
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                if not os.path.exists(CREDENTIALS_FILE):
                    log.error("credentials.json não encontrado. Veja as instruções no topo do módulo.")
                    return None, None
                flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_FILE, SCOPES)
                creds = flow.run_local_server(port=0)

            # Salva o token para próximas execuções
            with open(TOKEN_FILE, "w") as f:
                f.write(creds.to_json())

        cal_service   = build("calendar", "v3", credentials=creds)
        tasks_service = build("tasks",    "v1", credentials=creds)

        _servicos["calendar"] = cal_service
        _servicos["tasks"]    = tasks_service
        log.info("Google Calendar/Tasks autenticado com sucesso.")
        return cal_service, tasks_service

    except ImportError:
        log.error("Bibliotecas Google não instaladas. Execute: pip install google-auth google-auth-oauthlib google-auth-httplib2 google-api-python-client")
        return None, None
    except Exception as e:
        log.error(f"Erro de autenticação Google: {e}")
        return None, None


# ═══════════════════════════════════════════════════════════
#  BUSCA DE EVENTOS
# ═══════════════════════════════════════════════════════════

def _parse_datetime(evento: dict) -> datetime.datetime | None:
    """Converte o campo start do evento em datetime."""
    start = evento.get("start", {})
    dt_str = start.get("dateTime") or start.get("date")
    if not dt_str:
        return None
    try:
        # Remove o fuso horário para simplificar comparações locais
        dt_str = re.sub(r"([+-]\d{2}:\d{2}|Z)$", "", dt_str)
        if "T" in dt_str:
            return datetime.datetime.fromisoformat(dt_str)
        else:
            d = datetime.date.fromisoformat(dt_str)
            return datetime.datetime(d.year, d.month, d.day)
    except Exception:
        return None


def buscar_eventos_hoje(calendar_id: str = "primary", max_results: int = 20) -> list[dict]:
    """
    Retorna lista de eventos do dia atual ordenados por horário.
    Cada item: {"titulo", "hora", "hora_fim", "descricao", "local"}
    """
    cal, _ = _autenticar()
    if not cal:
        return []

    try:
        hoje = datetime.date.today()
        inicio = datetime.datetime(hoje.year, hoje.month, hoje.day, 0, 0, 0).isoformat() + "Z"
        fim    = datetime.datetime(hoje.year, hoje.month, hoje.day, 23, 59, 59).isoformat() + "Z"

        result = cal.events().list(
            calendarId=calendar_id,
            timeMin=inicio,
            timeMax=fim,
            maxResults=max_results,
            singleEvents=True,
            orderBy="startTime",
        ).execute()

        eventos = []
        for ev in result.get("items", []):
            dt_inicio = _parse_datetime(ev)
            dt_fim_raw = ev.get("end", {})
            dt_fim_str = dt_fim_raw.get("dateTime") or dt_fim_raw.get("date") or ""
            dt_fim_str = re.sub(r"([+-]\d{2}:\d{2}|Z)$", "", dt_fim_str)
            try:
                dt_fim = datetime.datetime.fromisoformat(dt_fim_str) if "T" in dt_fim_str else None
            except Exception:
                dt_fim = None

            eventos.append({
                "titulo":    ev.get("summary", "Sem título"),
                "hora":      dt_inicio.strftime("%H:%M") if dt_inicio and "T" in ev.get("start", {}).get("dateTime", "") else "Dia todo",
                "hora_fim":  dt_fim.strftime("%H:%M") if dt_fim else "",
                "descricao": ev.get("description", ""),
                "local":     ev.get("location", ""),
                "dt":        dt_inicio,
            })
        return eventos

    except Exception as e:
        log.error(f"buscar_eventos_hoje: {e}")
        return []


def buscar_proximos_eventos(calendar_id: str = "primary", horas: int = 4, max_results: int = 5) -> list[dict]:
    """Retorna eventos nas próximas N horas a partir de agora."""
    cal, _ = _autenticar()
    if not cal:
        return []

    try:
        agora = datetime.datetime.utcnow()
        fim   = agora + datetime.timedelta(hours=horas)

        result = cal.events().list(
            calendarId=calendar_id,
            timeMin=agora.isoformat() + "Z",
            timeMax=fim.isoformat()   + "Z",
            maxResults=max_results,
            singleEvents=True,
            orderBy="startTime",
        ).execute()

        eventos = []
        for ev in result.get("items", []):
            dt = _parse_datetime(ev)
            hora_str = dt.strftime("%H:%M") if dt and "T" in ev.get("start", {}).get("dateTime", "") else "Dia todo"
            eventos.append({
                "titulo": ev.get("summary", "Sem título"),
                "hora":   hora_str,
                "dt":     dt,
            })
        return eventos

    except Exception as e:
        log.error(f"buscar_proximos_eventos: {e}")
        return []


# ═══════════════════════════════════════════════════════════
#  BUSCA DE TAREFAS
# ═══════════════════════════════════════════════════════════

def buscar_tarefas_pendentes(max_results: int = 10) -> list[dict]:
    """
    Retorna tarefas pendentes do Google Tasks.
    Prioriza tarefas com due date = hoje.
    """
    _, tasks = _autenticar()
    if not tasks:
        return []

    try:
        listas_resp = tasks.tasklists().list(maxResults=10).execute()
        listas = listas_resp.get("items", [])

        hoje_str = datetime.date.today().isoformat()
        tarefas_hoje    = []
        tarefas_outras  = []

        for lista in listas:
            lid = lista["id"]
            resp = tasks.tasks().list(
                tasklist=lid,
                showCompleted=False,
                showHidden=False,
                maxResults=max_results,
            ).execute()

            for t in resp.get("items", []):
                due = t.get("due", "")[:10] if t.get("due") else ""
                item = {
                    "titulo": t.get("title", "Sem título"),
                    "due":    due,
                    "lista":  lista.get("title", ""),
                    "notas":  t.get("notes", ""),
                }
                if due == hoje_str:
                    tarefas_hoje.append(item)
                else:
                    tarefas_outras.append(item)

        return tarefas_hoje + tarefas_outras[:max(0, max_results - len(tarefas_hoje))]

    except Exception as e:
        log.error(f"buscar_tarefas: {e}")
        return []


# ═══════════════════════════════════════════════════════════
#  CLASSIFICAÇÃO: UFS / CORRIDA / GERAL
# ═══════════════════════════════════════════════════════════

def _e_aula_ufs(titulo: str, descricao: str = "") -> bool:
    texto = (titulo + " " + descricao).lower()
    return any(p in texto for p in _PALAVRAS_UFS)

def _e_treino_corrida(titulo: str, descricao: str = "") -> bool:
    texto = (titulo + " " + descricao).lower()
    return any(p in texto for p in _PALAVRAS_CORRIDA)


# ═══════════════════════════════════════════════════════════
#  BRIEFING MATINAL
# ═══════════════════════════════════════════════════════════

def gerar_briefing_matinal(nome: str = "senhor") -> str:
    """
    Gera o briefing matinal completo para o JARVIS falar.
    Inclui: saudação personalizada, aulas UFS, treinos de corrida,
    outros eventos, tarefas pendentes e dica motivacional.
    """
    agora    = datetime.datetime.now()
    hora_str = agora.strftime("%H:%M")
    dia_semana = ["segunda-feira", "terça-feira", "quarta-feira", "quinta-feira",
                  "sexta-feira", "sábado", "domingo"][agora.weekday()]

    partes = []

    # ── Saudação ──────────────────────────────────────────
    partes.append(f"Bom dia, {nome}. São {hora_str}, {dia_semana}, "
                  f"{agora.day} de {_mes_pt(agora.month)} de {agora.year}.")

    # ── Busca dados ───────────────────────────────────────
    eventos_ufs     = []
    eventos_corrida = []
    eventos_gerais  = []

    # Tenta calendário primário
    todos = buscar_eventos_hoje(calendar_id="primary")

    # Se o usuário configurou calendários separados, busca também
    if UFS_CAL_ID and UFS_CAL_ID != "primary":
        todos += buscar_eventos_hoje(calendar_id=UFS_CAL_ID)
    if CORRIDA_CAL_ID and CORRIDA_CAL_ID != "primary":
        todos += buscar_eventos_hoje(calendar_id=CORRIDA_CAL_ID)

    for ev in todos:
        if _e_aula_ufs(ev["titulo"], ev.get("descricao", "")):
            eventos_ufs.append(ev)
        elif _e_treino_corrida(ev["titulo"], ev.get("descricao", "")):
            eventos_corrida.append(ev)
        else:
            eventos_gerais.append(ev)

    # ── Aulas UFS ─────────────────────────────────────────
    if not todos:
        partes.append("Não consegui acessar seu calendário agora. Verifique a autenticação.")
    elif not eventos_ufs and not eventos_corrida and not eventos_gerais:
        partes.append("Sua agenda está livre hoje.")
    else:
        if eventos_ufs:
            if len(eventos_ufs) == 1:
                ev = eventos_ufs[0]
                partes.append(f"Você tem {ev['titulo']} às {ev['hora']}.")
            else:
                aulas_str = "; ".join(
                    f"{ev['titulo']} às {ev['hora']}" for ev in eventos_ufs
                )
                partes.append(f"Suas aulas de hoje: {aulas_str}.")

        # ── Treinos de corrida ─────────────────────────────
        if eventos_corrida:
            ev = eventos_corrida[0]
            partes.append(
                f"Seu treino de corrida está marcado para as {ev['hora']}. "
                f"Meta de hoje: {KM_META} km com pace de {PACE_META} minutos por quilômetro."
            )

        # ── Outros eventos ────────────────────────────────
        if eventos_gerais:
            outros_str = "; ".join(
                f"{ev['titulo']} às {ev['hora']}" if ev['hora'] != "Dia todo"
                else ev['titulo']
                for ev in eventos_gerais[:3]
            )
            partes.append(f"Outros compromissos: {outros_str}.")

    # ── Tarefas pendentes ─────────────────────────────────
    tarefas = buscar_tarefas_pendentes(max_results=5)
    tarefas_hoje = [t for t in tarefas if t["due"] == datetime.date.today().isoformat()]

    if tarefas_hoje:
        if len(tarefas_hoje) == 1:
            partes.append(f"Você tem uma tarefa para hoje: {tarefas_hoje[0]['titulo']}.")
        else:
            t_str = ", ".join(t["titulo"] for t in tarefas_hoje[:3])
            partes.append(f"Tarefas para hoje: {t_str}.")
    elif tarefas:
        partes.append(f"Tarefa pendente mais próxima: {tarefas[0]['titulo']}.")

    # ── Encerramento ──────────────────────────────────────
    partes.append("Tenha um ótimo dia, senhor. Sistemas prontos.")

    return " ".join(partes)


# ═══════════════════════════════════════════════════════════
#  PRÓXIMOS EVENTOS  (comando de voz)
# ═══════════════════════════════════════════════════════════

def falar_proximos_eventos(horas: int = 3) -> str:
    """Retorna frase com os próximos eventos nas próximas N horas."""
    eventos = buscar_proximos_eventos(horas=horas)
    if not eventos:
        return f"Não há eventos nas próximas {horas} horas, senhor."

    partes = [f"Nas próximas {horas} horas:"]
    for ev in eventos:
        partes.append(f"{ev['titulo']} às {ev['hora']}")
    return " ".join(partes) + "."


def falar_agenda_hoje() -> str:
    """Retorna frase com todos os eventos do dia."""
    eventos = buscar_eventos_hoje()
    if not eventos:
        return "Sua agenda está limpa hoje, senhor."

    partes = [f"Você tem {len(eventos)} evento{'s' if len(eventos) > 1 else ''} hoje."]
    for ev in eventos:
        hora = f" às {ev['hora']}" if ev["hora"] != "Dia todo" else ""
        partes.append(f"{ev['titulo']}{hora}.")
    return " ".join(partes)


def falar_tarefas() -> str:
    """Retorna frase com as tarefas pendentes."""
    tarefas = buscar_tarefas_pendentes(max_results=5)
    if not tarefas:
        return "Sem tarefas pendentes, senhor."

    hoje = datetime.date.today().isoformat()
    hoje_t = [t for t in tarefas if t["due"] == hoje]
    outras = [t for t in tarefas if t["due"] != hoje]

    partes = []
    if hoje_t:
        t_str = ", ".join(t["titulo"] for t in hoje_t)
        partes.append(f"Tarefas de hoje: {t_str}.")
    if outras:
        t_str = ", ".join(t["titulo"] for t in outras[:3])
        partes.append(f"Outras pendências: {t_str}.")

    return " ".join(partes)


# ═══════════════════════════════════════════════════════════
#  BRIEFING AUTOMÁTICO AGENDADO
# ═══════════════════════════════════════════════════════════

def iniciar_briefing_automatico(hud, falar_fn, nome: str = "senhor",
                                  horario: str = "07:00"):
    """
    Inicia uma thread que dispara o briefing matinal automaticamente
    todo dia no horário configurado.

    Args:
        hud:       instância do JarvisHUD
        falar_fn:  função falar_sync do JARVIS
        nome:      nome do usuário
        horario:   horário no formato "HH:MM"
    """
    hora_alvo, min_alvo = map(int, horario.split(":"))

    def _loop():
        ultimo_dia = None
        while True:
            agora = datetime.datetime.now()
            hoje  = agora.date()

            if (agora.hour == hora_alvo and agora.minute == min_alvo
                    and ultimo_dia != hoje):
                ultimo_dia = hoje
                try:
                    hud.safe_update("foco", "BRIEFING", "Matinal...")
                    briefing = gerar_briefing_matinal(nome)
                    falar_fn(briefing)
                    hud.safe_update(False, "STANDBY", "Aguardando...")
                    log.info("Briefing matinal executado.")
                except Exception as e:
                    log.error(f"Erro no briefing automático: {e}")

            time.sleep(30)  # Checa a cada 30 segundos

    t = threading.Thread(target=_loop, daemon=True, name="BriefingMatinal")
    t.start()
    log.info(f"Briefing automático agendado para {horario} todos os dias.")


# ═══════════════════════════════════════════════════════════
#  CRIAÇÃO DE EVENTOS  (escrita no Calendar)
# ═══════════════════════════════════════════════════════════

# Mapa de palavras relativas para calcular datas
_DIAS_SEMANA = {
    "segunda": 0, "terça": 1, "terca": 1, "quarta": 2,
    "quinta": 3, "sexta": 4, "sábado": 5, "sabado": 5, "domingo": 6,
}

def _interpretar_data_hora(frase: str) -> tuple[datetime.datetime | None, bool]:
    """
    Tenta extrair data e hora de uma frase em português.
    Retorna (datetime, dia_inteiro).
    Exemplos aceitos:
      'amanhã às 14h'
      'hoje às 8 da manhã'
      'dia 20 de maio às 10:30'
      'próxima sexta às 15h'
      'dia 15 às 9'
    """
    frase = frase.lower().strip()
    agora = datetime.datetime.now()
    hoje  = agora.date()

    data_alvo  = None
    hora_alvo  = None
    dia_inteiro = False

    # ── Data relativa ────────────────────────────────────
    if "hoje" in frase:
        data_alvo = hoje
    elif "amanhã" in frase or "amanha" in frase:
        data_alvo = hoje + datetime.timedelta(days=1)
    elif "depois de amanhã" in frase or "depois de amanha" in frase:
        data_alvo = hoje + datetime.timedelta(days=2)
    else:
        # Próximo dia da semana
        for nome, wd in _DIAS_SEMANA.items():
            if nome in frase:
                delta = (wd - hoje.weekday()) % 7 or 7
                data_alvo = hoje + datetime.timedelta(days=delta)
                break

    # ── Data absoluta: "dia 20 de maio" ou "20/05" ───────
    if not data_alvo:
        m = re.search(r"dia\s+(\d{1,2})\s+de\s+(\w+)", frase)
        if m:
            dia_num = int(m.group(1))
            mes_str = m.group(2)
            mes_num = _MESES_PT_NUM.get(mes_str)
            if mes_num:
                ano = agora.year if (mes_num >= agora.month) else agora.year + 1
                try:
                    data_alvo = datetime.date(ano, mes_num, dia_num)
                except ValueError:
                    pass

        if not data_alvo:
            m = re.search(r"(\d{1,2})[/\-](\d{1,2})(?:[/\-](\d{2,4}))?", frase)
            if m:
                dia_num = int(m.group(1))
                mes_num = int(m.group(2))
                ano = int(m.group(3)) if m.group(3) else agora.year
                if ano < 100:
                    ano += 2000
                try:
                    data_alvo = datetime.date(ano, mes_num, dia_num)
                except ValueError:
                    pass

    # ── Hora ─────────────────────────────────────────────
    # "14h", "14:30", "14 horas", "2 da tarde", "8 da manhã"
    m = re.search(r"(\d{1,2})h(\d{2})?", frase)
    if m:
        hora_alvo = datetime.time(int(m.group(1)), int(m.group(2) or 0))
    else:
        m = re.search(r"(\d{1,2}):(\d{2})", frase)
        if m:
            hora_alvo = datetime.time(int(m.group(1)), int(m.group(2)))
        else:
            m = re.search(r"(\d{1,2})\s+(?:horas?|da manhã|da tarde|da noite|ao meio)", frase)
            if m:
                h = int(m.group(1))
                if "tarde" in frase and h < 12:
                    h += 12
                elif "noite" in frase and h < 12:
                    h += 12
                hora_alvo = datetime.time(h, 0)

    if not data_alvo and not hora_alvo:
        return None, False

    if not data_alvo:
        data_alvo = hoje

    if not hora_alvo:
        dia_inteiro = True
        return datetime.datetime.combine(data_alvo, datetime.time(0, 0)), True

    return datetime.datetime.combine(data_alvo, hora_alvo), False


def _extrair_titulo(frase: str) -> str:
    """
    Remove as partes de data/hora da frase para sobrar o título do evento.
    """
    limpar = [
        r"jarvis[,]?\s*", r"adiciona[r]?\s*(na agenda|no calendar[io]?|um evento|evento)?",
        r"marca[r]?\s*(na agenda|no calendar[io]?|um evento|evento)?",
        r"cria[r]?\s*(na agenda|no calendar[io]?|um evento|evento)?",
        r"coloca[r]?\s*(na agenda|no calendar[io]?|um evento|evento)?",
        r"agenda[r]?\s*",
        r"(próxim[ao]?\s+)?(segunda|terça|terca|quarta|quinta|sexta|sábado|sabado|domingo)(\s*-\s*feira)?",
        r"(amanhã|amanha|hoje|depois de amanhã|depois de amanha)",
        r"dia\s+\d{1,2}\s+de\s+\w+",
        r"\d{1,2}[/\-]\d{1,2}([/\-]\d{2,4})?",
        r"\d{1,2}h\d{0,2}",
        r"\d{1,2}:\d{2}",
        r"\d{1,2}\s+(horas?|da manhã|da tarde|da noite)",
        r"às?\s*",
        r"para\s*",
        r"no\s+dia\s*",
    ]
    titulo = frase
    for p in limpar:
        titulo = re.sub(p, " ", titulo, flags=re.IGNORECASE)
    titulo = re.sub(r"\s{2,}", " ", titulo).strip(" ,.")
    return titulo.capitalize() or "Evento JARVIS"


_MESES_PT_NUM = {
    "janeiro": 1, "fevereiro": 2, "março": 3, "marco": 3,
    "abril": 4, "maio": 5, "junho": 6, "julho": 7,
    "agosto": 8, "setembro": 9, "outubro": 10,
    "novembro": 11, "dezembro": 12,
}


def criar_evento(titulo: str, dt_inicio: datetime.datetime,
                 duracao_min: int = 60,
                 dia_inteiro: bool = False,
                 calendar_id: str = "primary",
                 descricao: str = "") -> str:
    """
    Cria um evento no Google Calendar.
    Retorna mensagem de confirmação ou erro.
    """
    cal, _ = _autenticar()
    if not cal:
        return "Não consegui conectar ao Google Calendar, senhor."

    try:
        if dia_inteiro:
            data_str = dt_inicio.date().isoformat()
            evento_body = {
                "summary": titulo,
                "description": descricao,
                "start": {"date": data_str},
                "end":   {"date": (dt_inicio.date() + datetime.timedelta(days=1)).isoformat()},
            }
        else:
            tz = "America/Recife"  # UTC-3, Sergipe
            dt_fim = dt_inicio + datetime.timedelta(minutes=duracao_min)
            evento_body = {
                "summary": titulo,
                "description": descricao,
                "start": {"dateTime": dt_inicio.isoformat(), "timeZone": tz},
                "end":   {"dateTime": dt_fim.isoformat(),    "timeZone": tz},
            }

        result = cal.events().insert(calendarId=calendar_id, body=evento_body).execute()
        log.info(f"Evento criado: {titulo} — {result.get('htmlLink')}")

        if dia_inteiro:
            data_fmt = dt_inicio.strftime("%d/%m")
            return f"Evento '{titulo}' criado para o dia {data_fmt}, senhor."
        else:
            data_fmt = dt_inicio.strftime("%d/%m às %H:%M")
            return f"Evento '{titulo}' criado para {data_fmt}, senhor."

    except Exception as e:
        log.error(f"criar_evento: {e}")
        return f"Não consegui criar o evento, senhor. Erro: {e}"


def criar_tarefa(titulo: str, due: datetime.date | None = None,
                 notas: str = "") -> str:
    """
    Cria uma tarefa no Google Tasks (lista padrão).
    """
    _, tasks = _autenticar()
    if not tasks:
        return "Não consegui conectar ao Google Tasks, senhor."

    try:
        listas = tasks.tasklists().list(maxResults=1).execute()
        lista_id = listas["items"][0]["id"]

        body = {"title": titulo, "notes": notas}
        if due:
            body["due"] = datetime.datetime(due.year, due.month, due.day,
                                            12, 0, 0).isoformat() + "Z"

        tasks.tasks().insert(tasklist=lista_id, body=body).execute()
        log.info(f"Tarefa criada: {titulo}")

        if due:
            return f"Tarefa '{titulo}' criada para {due.strftime('%d/%m')}, senhor."
        return f"Tarefa '{titulo}' adicionada à sua lista, senhor."

    except Exception as e:
        log.error(f"criar_tarefa: {e}")
        return f"Não consegui criar a tarefa, senhor. Erro: {e}"


def interpretar_e_criar_evento(frase_completa: str) -> str:
    """
    Ponto de entrada principal: recebe a frase do JARVIS e cria o evento.
    Exemplos:
      "adiciona reunião amanhã às 14h"
      "marca prova de Cálculo dia 20 de maio às 8h"
      "agenda corrida sexta às 6h"
    """
    dt, dia_inteiro = _interpretar_data_hora(frase_completa)
    titulo = _extrair_titulo(frase_completa)

    if not titulo:
        return "Não entendi o título do evento. Pode repetir, senhor?"

    if dt is None:
        # Sem data → cria como tarefa sem prazo
        return criar_tarefa(titulo)

    return criar_evento(titulo, dt, dia_inteiro=dia_inteiro)


# ═══════════════════════════════════════════════════════════
#  AUXILIARES
# ═══════════════════════════════════════════════════════════

def _mes_pt(mes: int) -> str:
    meses = ["janeiro", "fevereiro", "março", "abril", "maio", "junho",
             "julho", "agosto", "setembro", "outubro", "novembro", "dezembro"]
    return meses[mes - 1]