"""
╔══════════════════════════════════════════════════════════╗
║      J.A.R.V.I.S  —  FUNCTION CALLING (Groq tools)       ║
║  Substitui o parsing manual por tool use real do LLM      ║
╚══════════════════════════════════════════════════════════╝

COMO FUNCIONA
─────────────
Em vez de um novo elif na cadeia legada, este módulo dá pro Groq
uma lista de ferramentas (tools) e deixa o próprio modelo decidir
se deve só conversar ou chamar uma função real do JARVIS.

USADO ONDE
──────────
No `else` final de `processar_comando` (jarvis_core.py), onde hoje
cai em `consultar_ia(...)`. Troque essa chamada por
`consultar_ia_com_tools(...)` — ver instruções no fim do arquivo.

Isso NÃO substitui a cadeia de elif nem os plugins existentes.
Comandos que já têm handler dedicado continuam batendo antes e
nunca chegam aqui. Este módulo só entra quando nada mais tratou
o comando — ou seja, ele vira um fallback mais esperto que o
"consultar_ia" puro, capaz de agir e não só falar.
"""

import json
import logging

log = logging.getLogger("JARVIS.Tools")

# Reaproveita o cliente Groq e o usuário já configurados no core
# (import de nome "privado" é só convenção em Python, funciona normal)
from jarvis_core import (
    _cliente_ia as cliente_ia,
    USUARIO,
    abrir_app,
    tirar_screenshot,
    fechar_app,
    listar_processos,
    mover_janela,
    executar_script,
    calcular,
    obter_clima,
    discord_enviar,
)

# Módulos opcionais — nem toda instalação tem calendário/whatsapp configurados
try:
    from jarvis_gcalendar import interpretar_e_criar_evento, falar_proximos_eventos
    _GCAL_OK = True
except Exception as e:
    _GCAL_OK = False
    log.warning(f"jarvis_gcalendar indisponível para tools: {e}")

try:
    from jarvis_whatsapp import enviar_whatsapp as _enviar_whatsapp_real
    _WA_OK = True
except Exception as e:
    _WA_OK = False
    log.warning(f"jarvis_whatsapp indisponível para tools: {e}")


# ═══════════════════════════════════════════════════════════
#  1. SCHEMA DAS FERRAMENTAS (o que o modelo enxerga)
# ═══════════════════════════════════════════════════════════
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "abrir_aplicativo",
            "description": "Abre um aplicativo no computador do usuário (spotify, code, firefox, chrome, terminal, discord, etc).",
            "parameters": {
                "type": "object",
                "properties": {
                    "nome_app": {"type": "string", "description": "Nome do aplicativo, ex: 'spotify', 'code', 'firefox'"}
                },
                "required": ["nome_app"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "fechar_aplicativo",
            "description": "Fecha/mata um processo em execução pelo nome.",
            "parameters": {
                "type": "object",
                "properties": {
                    "nome_processo": {"type": "string", "description": "Nome do processo a fechar"}
                },
                "required": ["nome_processo"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "listar_processos_ativos",
            "description": "Lista os processos que mais estão consumindo CPU no momento.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "tirar_screenshot",
            "description": "Captura a tela atual e salva um arquivo de imagem.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "mover_janela_ativa",
            "description": "Move/redimensiona a janela ativa na tela.",
            "parameters": {
                "type": "object",
                "properties": {
                    "direcao": {
                        "type": "string",
                        "enum": ["esquerda", "direita", "cima", "baixo", "maximizar"],
                        "description": "Para onde mover a janela ativa",
                    }
                },
                "required": ["direcao"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "executar_script_bash",
            "description": "Executa um script bash existente no disco e retorna a saída.",
            "parameters": {
                "type": "object",
                "properties": {
                    "caminho": {"type": "string", "description": "Caminho absoluto do script .sh"}
                },
                "required": ["caminho"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "calcular_expressao",
            "description": "Calcula uma expressão matemática simples (ex: '12 * (3 + 4)').",
            "parameters": {
                "type": "object",
                "properties": {
                    "expressao": {"type": "string", "description": "Expressão matemática em texto"}
                },
                "required": ["expressao"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "consultar_clima",
            "description": "Consulta o clima atual de uma cidade.",
            "parameters": {
                "type": "object",
                "properties": {
                    "cidade": {"type": "string", "description": "Nome da cidade, ex: 'Aracaju', 'São Paulo'"}
                },
                "required": ["cidade"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "enviar_mensagem_discord",
            "description": "Envia uma mensagem de texto para o canal do Discord configurado.",
            "parameters": {
                "type": "object",
                "properties": {
                    "mensagem": {"type": "string", "description": "Texto a enviar"}
                },
                "required": ["mensagem"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "criar_evento_agenda",
            "description": (
                "Cria um evento ou tarefa no Google Calendar a partir de uma frase em "
                "linguagem natural, incluindo data/hora quando mencionada. "
                "Ex: 'reunião amanhã às 14h', 'prova de Cálculo dia 20 de maio às 8h'."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "descricao_evento": {
                        "type": "string",
                        "description": "Frase completa descrevendo o evento, incluindo data/hora se souber",
                    }
                },
                "required": ["descricao_evento"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "consultar_proximos_eventos",
            "description": "Retorna os próximos eventos da agenda dentro de um número de horas.",
            "parameters": {
                "type": "object",
                "properties": {
                    "horas": {"type": "integer", "description": "Janela de horas a consultar (padrão 3)"}
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "enviar_whatsapp",
            "description": "Envia uma mensagem de WhatsApp para o usuário ou um destinatário específico.",
            "parameters": {
                "type": "object",
                "properties": {
                    "mensagem": {"type": "string", "description": "Texto da mensagem"},
                    "destinatario": {
                        "type": "string",
                        "description": "Número do destinatário (opcional, padrão é o próprio usuário)",
                    },
                },
                "required": ["mensagem"],
            },
        },
    },
]


# ═══════════════════════════════════════════════════════════
#  2. IMPLEMENTAÇÃO REAL DE CADA FERRAMENTA
#     (wrappers finos em cima do que já existe no core/módulos)
# ═══════════════════════════════════════════════════════════
def _t_abrir_aplicativo(nome_app: str) -> str:
    return abrir_app(nome_app.lower())


def _t_fechar_aplicativo(nome_processo: str) -> str:
    ok = fechar_app(nome_processo)
    return f"Fechei o {nome_processo}." if ok else f"Não encontrei o processo {nome_processo} rodando."


def _t_listar_processos_ativos() -> str:
    return listar_processos()


def _t_tirar_screenshot() -> str:
    caminho = tirar_screenshot()
    return f"Screenshot salvo em {caminho}." if caminho else "Não consegui tirar o screenshot."


def _t_mover_janela_ativa(direcao: str) -> str:
    mover_janela(direcao)
    return f"Janela movida para {direcao}."


def _t_executar_script_bash(caminho: str) -> str:
    return executar_script(caminho)


def _t_calcular_expressao(expressao: str) -> str:
    resultado = calcular(expressao)
    return f"O resultado é {resultado}." if resultado is not None else "Não consegui calcular essa expressão."


def _t_consultar_clima(cidade: str) -> str:
    return obter_clima(cidade)


def _t_enviar_mensagem_discord(mensagem: str) -> str:
    return discord_enviar(mensagem)


def _t_criar_evento_agenda(descricao_evento: str) -> str:
    if not _GCAL_OK:
        return "Calendário não está configurado neste momento."
    return interpretar_e_criar_evento(descricao_evento)


def _t_consultar_proximos_eventos(horas: int = 3) -> str:
    if not _GCAL_OK:
        return "Calendário não está configurado neste momento."
    return falar_proximos_eventos(horas=horas)


def _t_enviar_whatsapp(mensagem: str, destinatario: str = None) -> str:
    if not _WA_OK:
        return "WhatsApp não está configurado neste momento."
    ok = _enviar_whatsapp_real(mensagem, destinatario)
    return "Mensagem enviada pelo WhatsApp." if ok else "Falha ao enviar a mensagem pelo WhatsApp."


# Nome da tool (schema) -> função real que executa
_FUNCOES_DISPONIVEIS = {
    "abrir_aplicativo": _t_abrir_aplicativo,
    "fechar_aplicativo": _t_fechar_aplicativo,
    "listar_processos_ativos": _t_listar_processos_ativos,
    "tirar_screenshot": _t_tirar_screenshot,
    "mover_janela_ativa": _t_mover_janela_ativa,
    "executar_script_bash": _t_executar_script_bash,
    "calcular_expressao": _t_calcular_expressao,
    "consultar_clima": _t_consultar_clima,
    "enviar_mensagem_discord": _t_enviar_mensagem_discord,
    "criar_evento_agenda": _t_criar_evento_agenda,
    "consultar_proximos_eventos": _t_consultar_proximos_eventos,
    "enviar_whatsapp": _t_enviar_whatsapp,
}

_SISTEMA_TOOLS = (
    f"Você é o J.A.R.V.I.S, assistente pessoal de {USUARIO}. "
    "Quando o pedido do usuário corresponder claramente a uma das ferramentas "
    "disponíveis, chame a ferramenta em vez de apenas responder em texto. "
    "Se não houver ferramenta adequada, responda normalmente, em no máximo 2 frases curtas."
)

# Mesma cascata de modelos do consultar_ia, mas só com modelos que
# suportam tool calling de forma confiável na Groq.
_MODELOS_TOOLS = ["llama-3.3-70b-versatile", "llama-3.1-8b-instant"]


def consultar_ia_com_tools(prompt: str) -> str:
    """
    Substituto "esperto" de consultar_ia(): dá pro modelo a opção de
    chamar uma ferramenta real do JARVIS, ou só responder em texto.
    Retorna sempre uma string pronta pra ser falada.
    """
    if not cliente_ia:
        return f"IA não configurada, {USUARIO}."

    messages = [
        {"role": "system", "content": _SISTEMA_TOOLS},
        {"role": "user", "content": prompt},
    ]

    for modelo in _MODELOS_TOOLS:
        try:
            resposta = cliente_ia.chat.completions.create(
                model=modelo,
                messages=messages,
                tools=TOOLS,
                tool_choice="auto",
                max_tokens=500,
            )
            msg = resposta.choices[0].message

            if not msg.tool_calls:
                return (msg.content or f"Não entendi, {USUARIO}.").strip()

            # O modelo quis chamar 1+ ferramentas: executa de verdade
            messages.append(msg)
            for tool_call in msg.tool_calls:
                nome_funcao = tool_call.function.name
                try:
                    argumentos = json.loads(tool_call.function.arguments or "{}")
                except json.JSONDecodeError:
                    argumentos = {}

                funcao = _FUNCOES_DISPONIVEIS.get(nome_funcao)
                if not funcao:
                    resultado = f"Ferramenta desconhecida: {nome_funcao}"
                    log.warning(resultado)
                else:
                    try:
                        resultado = funcao(**argumentos)
                    except Exception as e:
                        log.error(f"Erro executando tool '{nome_funcao}': {e}")
                        resultado = f"Erro ao executar {nome_funcao}: {e}"

                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": str(resultado),
                })

            # Pede pro modelo transformar o resultado em resposta falada
            resposta_final = cliente_ia.chat.completions.create(
                model=modelo,
                messages=messages,
                max_tokens=300,
            )
            return resposta_final.choices[0].message.content.strip()

        except Exception as e:
            log.warning(f"Groq tools [{modelo}] falhou: {e}")
            continue

    return f"Todos os modelos com tools indisponíveis agora, {USUARIO}."


# ═══════════════════════════════════════════════════════════
#  COMO INTEGRAR NO jarvis_core.py
# ═══════════════════════════════════════════════════════════
# No final de processar_comando(), no "else:" (fallback de IA livre),
# troque:
#
#     resposta = consultar_ia(prompt_enriquecido, curto=True)
#     falar(resposta.replace("*", "").replace("#", ""))
#
# por:
#
#     from jarvis_tools import consultar_ia_com_tools
#     resposta = consultar_ia_com_tools(prompt_enriquecido)
#     falar(resposta.replace("*", "").replace("#", ""))
#
# O import fica DENTRO do else (import local), igual o padrão que
# vocês já usam pro jarvis_web_hud — evita import circular, já que
# jarvis_tools importa de jarvis_core.
