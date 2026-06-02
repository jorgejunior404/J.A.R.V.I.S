"""
╔══════════════════════════════════════════════════════════╗
║      J.A.R.V.I.S  —  MÓDULO DE ESTUDOS UFS              ║
║  Plano de estudos · Questionar conteúdo · Provas         ║
╚══════════════════════════════════════════════════════════╝

Como usar:
  1. Copie este arquivo para a pasta do JARVIS
  2. Aplique o PATCH abaixo no jarvis_core.py
  3. Fale: "Jarvis, plano de estudos" ou "Jarvis, me questiona cálculo"

Comandos de voz disponíveis:
  "Jarvis, plano de estudos"
  "Jarvis, o que estudar hoje"
  "Jarvis, me questiona [matéria]"
  "Jarvis, adicionar prova de [matéria] dia [X] de [mês]"
  "Jarvis, próximas provas"
  "Jarvis, marcar [matéria] como estudada"
  "Jarvis, progresso de hoje"
  "Jarvis, quanto estudei essa semana"
"""

import os
import json
import datetime
import random
import logging
import threading
import time
from dotenv import load_dotenv

load_dotenv()
log = logging.getLogger("JARVIS.Estudos")

# ═══════════════════════════════════════════════════════════
#  CONFIGURAÇÃO DAS MATÉRIAS
# ═══════════════════════════════════════════════════════════

MATERIAS = {
    "programacao": {
        "nome":     "Programação A",
        "apelidos": ["programação", "programacao", "python", "prog"],
        "cor":      "🟦",
        "peso":     3,   # prioridade (1-5)
        "topicos": [
            "variáveis e tipos de dados",
            "condicionais if/else",
            "loops for e while",
            "funções e parâmetros",
            "listas e tuplas",
            "dicionários",
            "strings e manipulação",
            "arquivos e I/O",
            "exceções e try/except",
            "orientação a objetos",
            "módulos e imports",
            "recursão",
        ],
        "perguntas": [
            ("O que é uma lista em Python e como ela difere de uma tupla?",
             "Lista é mutável e usa [], tupla é imutável e usa (). Listas permitem adicionar, remover e alterar elementos. Tuplas não."),
            ("Como funciona o loop for com range()?",
             "range(n) gera números de 0 a n-1. range(a,b) de a até b-1. range(a,b,passo) com incremento definido."),
            ("O que é uma função e para que serve?",
             "Bloco de código reutilizável definido com def. Recebe parâmetros, executa uma tarefa e pode retornar valores."),
            ("Qual a diferença entre == e is em Python?",
             "== compara valores. is compara identidade (se são o mesmo objeto na memória)."),
            ("O que é um dicionário em Python?",
             "Estrutura de dados que armazena pares chave:valor. Chaves são únicas. Acesso por chave: dict['chave']."),
            ("O que é herança em orientação a objetos?",
             "Mecanismo onde uma classe filha herda atributos e métodos da classe pai. Usa class Filha(Pai)."),
            ("Para que serve try/except?",
             "Para tratar erros sem travar o programa. O bloco try tenta executar, except captura a exceção se ocorrer."),
            ("O que é recursão?",
             "Quando uma função chama a si mesma. Precisa de um caso base para parar. Útil para problemas como fatorial e Fibonacci."),
            ("Como abrir e ler um arquivo em Python?",
             "Com open('arquivo.txt', 'r') e read() ou readlines(). Melhor usar with open() para fechar automaticamente."),
            ("O que são módulos e como importar?",
             "Arquivos .py com funções reutilizáveis. Importa com import modulo ou from modulo import funcao."),
        ],
    },

    "vetores": {
        "nome":     "Vetores e Geometria Analítica",
        "apelidos": ["vetores", "geometria", "vga", "vetorial"],
        "cor":      "🟩",
        "peso":     4,
        "topicos": [
            "sistemas de coordenadas",
            "vetores no plano e no espaço",
            "operações com vetores",
            "produto escalar",
            "produto vetorial",
            "produto misto",
            "retas no espaço",
            "planos",
            "distâncias e ângulos",
            "cônicas: elipse, parábola, hipérbole",
            "quadráticas",
        ],
        "perguntas": [
            ("O que é o produto escalar e o que significa quando é zero?",
             "É a soma dos produtos das componentes: a·b = ax*bx + ay*by + az*bz. Quando é zero, os vetores são perpendiculares."),
            ("Qual a diferença entre produto escalar e produto vetorial?",
             "Escalar retorna um número. Vetorial retorna um vetor perpendicular aos dois vetores originais."),
            ("Como calcular o módulo de um vetor?",
             "Raiz quadrada da soma dos quadrados das componentes. |v| = √(x² + y² + z²)."),
            ("O que é um vetor unitário?",
             "Vetor com módulo igual a 1. Obtido dividindo o vetor pelo seu módulo: û = v/|v|."),
            ("Como determinar a equação de um plano?",
             "Com um ponto P e um vetor normal n=(a,b,c): a(x-x0) + b(y-y0) + c(z-z0) = 0."),
            ("O que é o produto misto e para que serve?",
             "É o determinante 3x3 formado pelos três vetores. Seu valor absoluto é o volume do paralelepípedo formado por eles. Se for zero, os vetores são coplanares."),
            ("Como achar o ângulo entre dois vetores?",
             "cos(θ) = (a·b) / (|a| * |b|). Aplica arccos para obter o ângulo."),
            ("O que define uma elipse?",
             "Lugar geométrico dos pontos cuja soma das distâncias a dois focos é constante. Equação: x²/a² + y²/b² = 1."),
        ],
    },

    "calculo": {
        "nome":     "Cálculo A",
        "apelidos": ["cálculo", "calculo", "calc"],
        "cor":      "🟥",
        "peso":     5,
        "topicos": [
            "limites",
            "continuidade",
            "derivadas — definição",
            "regras de derivação",
            "regra da cadeia",
            "derivadas de funções trigonométricas",
            "derivadas implícitas",
            "máximos e mínimos",
            "teorema de Rolle e valor médio",
            "integrais indefinidas",
            "integrais definidas",
            "teorema fundamental do cálculo",
            "técnicas de integração",
        ],
        "perguntas": [
            ("O que é a derivada geometricamente?",
             "É o coeficiente angular da reta tangente à curva num ponto. Representa a taxa de variação instantânea da função."),
            ("Qual a regra do produto para derivadas?",
             "(f·g)' = f'·g + f·g'. Deriva a primeira vezes a segunda, mais a primeira vezes a derivada da segunda."),
            ("O que é um limite e quando ele não existe?",
             "É o valor que a função se aproxima quando x tende a um ponto. Não existe se os limites laterais forem diferentes ou se for infinito."),
            ("Qual a diferença entre máximo local e global?",
             "Local: maior valor na vizinhança do ponto. Global: maior valor em todo o domínio."),
            ("Como identificar máximos e mínimos com derivadas?",
             "Onde f'=0 são pontos críticos. Se f''>0 é mínimo, f''<0 é máximo. Teste da segunda derivada."),
            ("O que é a integral de Riemann?",
             "Limite da soma de retângulos sob a curva quando a largura tende a zero. Calcula a área sob a curva."),
            ("Enuncia o Teorema Fundamental do Cálculo.",
             "Se F é primitiva de f, então ∫(a,b) f(x)dx = F(b) - F(a). Liga derivação e integração."),
            ("O que é a regra da cadeia?",
             "Para f(g(x)), a derivada é f'(g(x)) · g'(x). Deriva a função externa mantendo a interna, multiplica pela derivada da interna."),
            ("Quando uma função é contínua num ponto?",
             "Quando: 1) f(a) existe, 2) lim f(x) existe quando x→a, 3) o limite é igual a f(a)."),
        ],
    },

    "fem": {
        "nome":     "FEM",
        "apelidos": ["fem", "eletromagnetismo", "eletricidade", "física"],
        "cor":      "🟨",
        "peso":     4,
        "topicos": [
            "carga elétrica e lei de Coulomb",
            "campo elétrico",
            "lei de Gauss",
            "potencial elétrico",
            "capacitância e capacitores",
            "corrente e resistência",
            "circuitos DC",
            "lei de Ohm",
            "campo magnético",
            "lei de Faraday",
            "indutância",
        ],
        "perguntas": [
            ("Enuncia a Lei de Coulomb.",
             "A força entre duas cargas é F = kq1q2/r². Proporcional ao produto das cargas e inversamente proporcional ao quadrado da distância."),
            ("O que é campo elétrico?",
             "Força por unidade de carga: E = F/q. Aponta para onde uma carga positiva de teste seria empurrada."),
            ("O que diz a Lei de Gauss?",
             "O fluxo elétrico total através de uma superfície fechada é igual à carga total interna dividida por ε0."),
            ("Qual a diferença entre potencial e campo elétrico?",
             "Campo é vetorial (força por carga). Potencial é escalar (energia por carga). E = -∇V."),
            ("O que é capacitância?",
             "Capacidade de armazenar carga: C = Q/V. Medida em Farads. Depende da geometria do capacitor."),
            ("Enuncia a Lei de Ohm.",
             "V = R·I. A tensão é proporcional à corrente. R é a resistência em Ohms."),
            ("Como calcular resistências em série e paralelo?",
             "Série: Req = R1+R2+... — mesma corrente. Paralelo: 1/Req = 1/R1+1/R2+... — mesma tensão."),
            ("O que é indução eletromagnética?",
             "Variação do fluxo magnético gera força eletromotriz. Lei de Faraday: EMF = -dΦ/dt."),
        ],
    },

    "ia": {
        "nome":     "Fundamentos de Inteligência Artificial",
        "apelidos": ["ia", "inteligência artificial", "inteligencia artificial", "fai", "fundamentos de ia"],
        "cor":      "🟪",
        "peso":     3,
        "topicos": [
            "história da IA",
            "agentes inteligentes",
            "busca cega: BFS e DFS",
            "busca heurística: A*",
            "lógica proposicional",
            "lógica de predicados",
            "redes bayesianas",
            "aprendizado de máquina — conceitos",
            "classificação e regressão",
            "redes neurais — introdução",
            "processamento de linguagem natural",
        ],
        "perguntas": [
            ("O que é um agente inteligente?",
             "Entidade que percebe o ambiente via sensores e age via atuadores para maximizar uma medida de desempenho."),
            ("Qual a diferença entre BFS e DFS?",
             "BFS (busca em largura) explora nível por nível, garante caminho mais curto. DFS (profundidade) vai fundo primeiro, usa menos memória mas pode não achar o ótimo."),
            ("O que é a heurística no algoritmo A*?",
             "Estimativa do custo do nó atual até o objetivo. A* usa f(n) = g(n) + h(n). Se h for admissível (nunca superestima), A* é ótimo."),
            ("O que é aprendizado supervisionado?",
             "O modelo aprende com exemplos rotulados (entrada + saída esperada). Exemplos: classificação de spam, previsão de preços."),
            ("Qual a diferença entre classificação e regressão?",
             "Classificação prevê categorias discretas (spam/não-spam). Regressão prevê valores contínuos (preço de imóvel)."),
            ("O que é overfitting?",
             "Quando o modelo aprende demais os dados de treino e vai mal em dados novos. Solução: mais dados, regularização, validação cruzada."),
            ("Para que serve uma rede neural?",
             "Aproximar funções complexas a partir de dados. Camadas de neurônios com pesos ajustados por backpropagation para minimizar o erro."),
            ("O que é lógica proposicional?",
             "Sistema formal com proposições verdadeiras ou falsas e operadores: E (∧), OU (∨), NÃO (¬), implica (→), bicondicional (↔)."),
        ],
    },
}

# ═══════════════════════════════════════════════════════════
#  ARQUIVOS DE DADOS
# ═══════════════════════════════════════════════════════════

ARQUIVO_PROVAS    = os.path.expanduser("~/.jarvis_provas.json")
ARQUIVO_PROGRESSO = os.path.expanduser("~/.jarvis_progresso.json")
ARQUIVO_PLANO     = os.path.expanduser("~/.jarvis_plano.json")

def _carregar(arquivo: str) -> dict:
    if os.path.exists(arquivo):
        try:
            with open(arquivo, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}

def _salvar(arquivo: str, dados: dict):
    try:
        with open(arquivo, "w", encoding="utf-8") as f:
            json.dump(dados, f, ensure_ascii=False, indent=2)
    except Exception as e:
        log.error(f"Erro ao salvar {arquivo}: {e}")


# ═══════════════════════════════════════════════════════════
#  BUSCA DE MATÉRIA POR VOZ
# ═══════════════════════════════════════════════════════════

def _identificar_materia(comando: str) -> tuple[str, dict] | tuple[None, None]:
    """Identifica qual matéria foi mencionada no comando."""
    cmd = comando.lower()
    for chave, info in MATERIAS.items():
        for apelido in info["apelidos"]:
            if apelido in cmd:
                return chave, info
    return None, None


# ═══════════════════════════════════════════════════════════
#  PLANO DE ESTUDOS
# ═══════════════════════════════════════════════════════════

def gerar_plano_hoje() -> str:
    """
    Gera um plano de estudos para hoje baseado em:
    - Proximidade de provas
    - Progresso recente (evita repetir o que foi estudado ontem)
    - Peso/prioridade de cada matéria
    """
    hoje      = datetime.date.today().isoformat()
    provas    = _carregar(ARQUIVO_PROVAS)
    progresso = _carregar(ARQUIVO_PROGRESSO)

    # Calcula urgência de cada matéria
    urgencias = {}
    for chave, info in MATERIAS.items():
        urgencia = info["peso"]

        # Aumenta urgência se tem prova próxima
        if chave in provas:
            for prova in provas[chave]:
                try:
                    data_prova = datetime.date.fromisoformat(prova["data"])
                    dias       = (data_prova - datetime.date.today()).days
                    if 0 <= dias <= 3:
                        urgencia += 5
                    elif 0 <= dias <= 7:
                        urgencia += 3
                    elif 0 <= dias <= 14:
                        urgencia += 1
                except Exception:
                    pass

        # Reduz urgência se estudou hoje ou ontem
        ontem = (datetime.date.today() - datetime.timedelta(days=1)).isoformat()
        prog  = progresso.get(chave, {})
        if hoje in prog.get("datas", []):
            urgencia -= 2
        elif ontem in prog.get("datas", []):
            urgencia -= 1

        urgencias[chave] = max(1, urgencia)

    # Ordena por urgência e pega as top 3
    ordenadas = sorted(urgencias.items(), key=lambda x: x[1], reverse=True)
    top3      = ordenadas[:3]

    partes = ["Seu plano de estudos para hoje:"]
    for i, (chave, urg) in enumerate(top3, 1):
        info   = MATERIAS[chave]
        topico = _proximo_topico(chave)

        # Verifica se tem prova próxima
        alerta = ""
        if chave in provas:
            for prova in provas[chave]:
                try:
                    dias = (datetime.date.fromisoformat(prova["data"]) - datetime.date.today()).days
                    if 0 <= dias <= 7:
                        alerta = f" — PROVA em {dias} dia{'s' if dias != 1 else ''}!"
                except Exception:
                    pass

        partes.append(
            f"Prioridade {i}: {info['nome']}{alerta}. "
            f"Sugestão de tópico: {topico}."
        )

    # Salva o plano do dia
    plano = {"data": hoje, "materias": [c for c, _ in top3]}
    _salvar(ARQUIVO_PLANO, plano)

    return " ".join(partes)


def _proximo_topico(chave: str) -> str:
    """Sugere o próximo tópico a estudar baseado no progresso."""
    info      = MATERIAS.get(chave, {})
    topicos   = info.get("topicos", [])
    progresso = _carregar(ARQUIVO_PROGRESSO)
    estudados = progresso.get(chave, {}).get("topicos_vistos", [])

    # Pega o primeiro tópico ainda não estudado
    for t in topicos:
        if t not in estudados:
            return t

    # Se todos foram vistos, recomeça
    return topicos[0] if topicos else "revisão geral"


# ═══════════════════════════════════════════════════════════
#  QUESTIONAMENTO DE CONTEÚDO
# ═══════════════════════════════════════════════════════════

_sessao_questoes = {}  # estado da sessão de questões ativa

def iniciar_sessao_questoes(chave: str, falar_fn, ouvir_fn, hud=None) -> str:
    """
    Inicia uma sessão de perguntas e respostas sobre uma matéria.
    Faz 5 perguntas aleatórias e avalia as respostas.
    """
    global _sessao_questoes

    info     = MATERIAS.get(chave)
    if not info:
        return f"Matéria não encontrada."

    perguntas = info.get("perguntas", [])
    if not perguntas:
        return f"Sem perguntas cadastradas para {info['nome']} ainda."

    # Sorteia até 5 perguntas
    selecionadas = random.sample(perguntas, min(5, len(perguntas)))

    falar_fn(f"Iniciando sessão de {info['nome']}. {len(selecionadas)} perguntas. Pode responder em voz alta ou dizer 'não sei' para pular.")

    acertos   = 0
    erros     = 0
    puladas   = 0

    for i, (pergunta, gabarito) in enumerate(selecionadas, 1):
        if hud:
            hud.safe_update("foco", f"QUESTÃO {i}/{len(selecionadas)}", info["nome"][:20])

        falar_fn(f"Pergunta {i}: {pergunta}")
        time.sleep(0.5)

        resposta = ouvir_fn(timeout=20, limite=60)

        if not resposta:
            falar_fn("Não ouvi sua resposta. Vou mostrar o gabarito.")
            falar_fn(f"Resposta: {gabarito}")
            puladas += 1
            continue

        if any(p in resposta for p in ["não sei", "nao sei", "pular", "próxima", "skip"]):
            falar_fn(f"Tudo bem. A resposta é: {gabarito}")
            puladas += 1
            continue

        # Avalia a resposta usando palavras-chave do gabarito
        palavras_chave = _extrair_palavras_chave(gabarito)
        acertou        = _avaliar_resposta(resposta, palavras_chave)

        if acertou:
            acertos += 1
            falar_fn(random.choice([
                "Correto! Muito bem.",
                "Isso mesmo! Boa resposta.",
                "Exato. Você acertou.",
                "Perfeito. Está dominando esse conteúdo.",
            ]))
        else:
            erros += 1
            falar_fn(f"Não exatamente. A resposta completa é: {gabarito}")

        time.sleep(0.3)

    # Resultado final
    total = len(selecionadas)
    pct   = int((acertos / total) * 100)

    if pct >= 80:
        avaliacao = "Excelente! Está bem preparado nesse conteúdo."
    elif pct >= 60:
        avaliacao = "Bom progresso. Revise os pontos que errou."
    elif pct >= 40:
        avaliacao = "Precisa revisar mais. Foque nos tópicos que errou."
    else:
        avaliacao = "Esse conteúdo precisa de mais atenção. Recomendo rever desde o início."

    # Registra progresso
    _registrar_sessao(chave, acertos, total)

    resultado = (
        f"Sessão concluída. {acertos} de {total} corretas, {pct}%. "
        f"{avaliacao}"
    )

    if hud:
        hud.safe_update("foco", "SESSÃO OK", f"{pct}%")

    return resultado


def _extrair_palavras_chave(gabarito: str) -> list:
    """Extrai palavras importantes do gabarito para avaliação."""
    stopwords = {"é", "um", "uma", "de", "do", "da", "em", "que", "com",
                 "para", "por", "se", "os", "as", "no", "na", "ao", "quando",
                 "como", "mais", "mas", "ou", "e", "o", "a"}
    palavras = gabarito.lower().split()
    return [p.strip(".,;:()") for p in palavras
            if len(p) > 3 and p not in stopwords]


def _avaliar_resposta(resposta: str, palavras_chave: list) -> bool:
    """Avalia se a resposta contém pelo menos 30% das palavras-chave."""
    if not palavras_chave:
        return True
    resp_lower = resposta.lower()
    acertos    = sum(1 for p in palavras_chave if p in resp_lower)
    return (acertos / len(palavras_chave)) >= 0.30


# ═══════════════════════════════════════════════════════════
#  PROVAS E ENTREGAS
# ═══════════════════════════════════════════════════════════

MESES_PT = {
    "janeiro": 1, "fevereiro": 2, "março": 3, "marco": 3,
    "abril": 4, "maio": 5, "junho": 6, "julho": 7,
    "agosto": 8, "setembro": 9, "outubro": 10,
    "novembro": 11, "dezembro": 12,
}

def adicionar_prova(chave: str, dia: int, mes: int, ano: int = None,
                    tipo: str = "prova") -> str:
    """Adiciona uma prova ou entrega para uma matéria."""
    provas = _carregar(ARQUIVO_PROVAS)
    if chave not in provas:
        provas[chave] = []

    if not ano:
        ano = datetime.date.today().year

    try:
        data = datetime.date(ano, mes, dia)
    except ValueError:
        return "Data inválida."

    provas[chave].append({
        "data": data.isoformat(),
        "tipo": tipo,
    })

    # Ordena por data
    provas[chave].sort(key=lambda x: x["data"])
    _salvar(ARQUIVO_PROVAS, provas)

    info  = MATERIAS.get(chave, {})
    nome  = info.get("nome", chave)
    dias  = (data - datetime.date.today()).days

    if dias == 0:
        return f"{tipo.capitalize()} de {nome} registrada para hoje!"
    elif dias == 1:
        return f"{tipo.capitalize()} de {nome} registrada para amanhã."
    else:
        return f"{tipo.capitalize()} de {nome} registrada. Faltam {dias} dias."


def listar_provas() -> str:
    """Lista todas as provas futuras ordenadas por data."""
    provas = _carregar(ARQUIVO_PROVAS)
    hoje   = datetime.date.today()
    itens  = []

    for chave, lista in provas.items():
        info = MATERIAS.get(chave, {})
        nome = info.get("nome", chave)
        for prova in lista:
            try:
                data = datetime.date.fromisoformat(prova["data"])
                if data >= hoje:
                    dias = (data - hoje).days
                    itens.append((dias, nome, prova["tipo"], data))
            except Exception:
                pass

    if not itens:
        return "Nenhuma prova cadastrada, senhor."

    itens.sort(key=lambda x: x[0])
    partes = [f"Você tem {len(itens)} prova{'s' if len(itens) > 1 else ''} agendada{'s' if len(itens) > 1 else ''}:"]

    for dias, nome, tipo, data in itens:
        data_fmt = data.strftime("%d/%m")
        if dias == 0:
            partes.append(f"{tipo.capitalize()} de {nome} é HOJE!")
        elif dias == 1:
            partes.append(f"{tipo.capitalize()} de {nome} é amanhã, dia {data_fmt}.")
        elif dias <= 7:
            partes.append(f"{tipo.capitalize()} de {nome} em {dias} dias, dia {data_fmt}.")
        else:
            partes.append(f"{tipo.capitalize()} de {nome} dia {data_fmt}, faltam {dias} dias.")

    return " ".join(partes)


def verificar_provas_proximas() -> str:
    """Retorna alerta se houver provas nos próximos 3 dias."""
    provas = _carregar(ARQUIVO_PROVAS)
    hoje   = datetime.date.today()
    alertas = []

    for chave, lista in provas.items():
        info = MATERIAS.get(chave, {})
        nome = info.get("nome", chave)
        for prova in lista:
            try:
                data = datetime.date.fromisoformat(prova["data"])
                dias = (data - hoje).days
                if 0 <= dias <= 3:
                    alertas.append((dias, nome, prova["tipo"]))
            except Exception:
                pass

    if not alertas:
        return ""

    alertas.sort()
    partes = []
    for dias, nome, tipo in alertas:
        if dias == 0:
            partes.append(f"ATENÇÃO: {tipo} de {nome} é hoje!")
        elif dias == 1:
            partes.append(f"Amanhã tem {tipo} de {nome}.")
        else:
            partes.append(f"{tipo.capitalize()} de {nome} em {dias} dias.")

    return " ".join(partes)


# ═══════════════════════════════════════════════════════════
#  REGISTRO DE PROGRESSO
# ═══════════════════════════════════════════════════════════

def marcar_estudada(chave: str, topico: str = None) -> str:
    """Marca que o usuário estudou uma matéria hoje."""
    progresso = _carregar(ARQUIVO_PROGRESSO)
    hoje      = datetime.date.today().isoformat()

    if chave not in progresso:
        progresso[chave] = {"datas": [], "topicos_vistos": [], "sessoes": []}

    if hoje not in progresso[chave]["datas"]:
        progresso[chave]["datas"].append(hoje)

    if topico and topico not in progresso[chave]["topicos_vistos"]:
        progresso[chave]["topicos_vistos"].append(topico)

    _salvar(ARQUIVO_PROGRESSO, progresso)
    info = MATERIAS.get(chave, {})
    nome = info.get("nome", chave)
    return f"{nome} marcada como estudada hoje."


def _registrar_sessao(chave: str, acertos: int, total: int):
    """Registra resultado de uma sessão de questões."""
    progresso = _carregar(ARQUIVO_PROGRESSO)
    hoje      = datetime.date.today().isoformat()

    if chave not in progresso:
        progresso[chave] = {"datas": [], "topicos_vistos": [], "sessoes": []}

    if hoje not in progresso[chave]["datas"]:
        progresso[chave]["datas"].append(hoje)

    progresso[chave]["sessoes"].append({
        "data":    hoje,
        "acertos": acertos,
        "total":   total,
    })

    _salvar(ARQUIVO_PROGRESSO, progresso)


def relatorio_progresso() -> str:
    """Gera relatório do progresso de estudos da semana."""
    progresso = _carregar(ARQUIVO_PROGRESSO)
    hoje      = datetime.date.today()
    semana    = [(hoje - datetime.timedelta(days=i)).isoformat() for i in range(7)]

    partes = ["Relatório da semana:"]
    total_dias = 0

    for chave, info in MATERIAS.items():
        prog  = progresso.get(chave, {})
        datas = prog.get("datas", [])
        dias_semana = [d for d in datas if d in semana]
        sessoes     = prog.get("sessoes", [])
        sess_semana = [s for s in sessoes if s["data"] in semana]

        if dias_semana:
            total_dias += len(dias_semana)
            media = ""
            if sess_semana:
                total_ac  = sum(s["acertos"] for s in sess_semana)
                total_tot = sum(s["total"]   for s in sess_semana)
                pct       = int((total_ac / total_tot) * 100) if total_tot > 0 else 0
                media     = f", média de {pct}% nas questões"
            partes.append(
                f"{info['nome']}: {len(dias_semana)} dia{'s' if len(dias_semana) > 1 else ''} estudado{'s' if len(dias_semana) > 1 else ''}{media}."
            )

    if total_dias == 0:
        return "Nenhum estudo registrado essa semana ainda."

    # Matérias não estudadas
    nao_estudadas = [
        MATERIAS[c]["nome"]
        for c in MATERIAS
        if not any(d in semana for d in progresso.get(c, {}).get("datas", []))
    ]
    if nao_estudadas:
        partes.append(f"Matérias sem estudo essa semana: {', '.join(nao_estudadas)}.")

    return " ".join(partes)


def progresso_hoje() -> str:
    """Retorna o que foi estudado hoje."""
    progresso = _carregar(ARQUIVO_PROGRESSO)
    hoje      = datetime.date.today().isoformat()
    estudadas = []

    for chave, prog in progresso.items():
        if hoje in prog.get("datas", []):
            info = MATERIAS.get(chave, {})
            estudadas.append(info.get("nome", chave))

    if not estudadas:
        return "Nenhuma matéria estudada ainda hoje."

    return f"Hoje você estudou: {', '.join(estudadas)}."


# ═══════════════════════════════════════════════════════════
#  ALERTAS AUTOMÁTICOS
# ═══════════════════════════════════════════════════════════

def iniciar_alertas_provas(falar_fn, hud=None):
    """
    Thread que verifica provas próximas a cada hora
    e alerta se houver prova nos próximos 3 dias.
    """
    ultimo_alerta = None

    def _loop():
        nonlocal ultimo_alerta
        time.sleep(30)  # Espera o JARVIS inicializar
        while True:
            hoje = datetime.date.today().isoformat()
            if ultimo_alerta != hoje:
                alerta = verificar_provas_proximas()
                if alerta:
                    ultimo_alerta = hoje
                    if hud:
                        hud.safe_update("alerta", "PROVA PRÓXIMA", "")
                    falar_fn(f"Atenção, {alerta}")
            time.sleep(3600)  # Verifica a cada hora

    t = threading.Thread(target=_loop, daemon=True, name="AlertasProvas")
    t.start()
    log.info("Alertas de provas iniciados.")


"""
═══════════════════════════════════════════════════════════
 PATCH PARA jarvis_core.py
 Adicione os imports e comandos abaixo no arquivo principal
═══════════════════════════════════════════════════════════

── PATCH 1: IMPORTS (após os imports existentes) ──────────

from jarvis_estudos import (
    gerar_plano_hoje,
    iniciar_sessao_questoes,
    adicionar_prova,
    listar_provas,
    marcar_estudada,
    relatorio_progresso,
    progresso_hoje,
    iniciar_alertas_provas,
    _identificar_materia,
    MESES_PT as MESES_ESTUDOS,
)


── PATCH 2: COMANDOS (adicione em processar_comando,
   ANTES do bloco elif 'clima' in comando) ────────────────

    # ── Plano de estudos ──────────────────────────────────
    elif any(p in comando for p in [
        "plano de estudos", "o que estudar hoje",
        "o que estudar", "me dá um plano", "planejar estudos",
    ]):
        hud.safe_update("foco", "ESTUDOS", "Montando plano...")
        falar(gerar_plano_hoje())

    # ── Questionar conteúdo ───────────────────────────────
    elif any(p in comando for p in [
        "me questiona", "me pergunta", "questionar",
        "quiz de", "testar meu conhecimento", "me testa",
    ]):
        chave, info = _identificar_materia(comando)
        if not chave:
            falar_sync("Qual matéria? Pode falar: cálculo, vetores, programação, FEM ou IA.")
            resp  = ouvir_pergunta(timeout=8, limite=10)
            chave, info = _identificar_materia(resp) if resp else (None, None)
        if chave:
            hud.safe_update("foco", "QUESTÕES", info["nome"][:20])
            threading.Thread(
                target=lambda: falar(
                    iniciar_sessao_questoes(chave, falar_sync, ouvir_pergunta, hud)
                ),
                daemon=True
            ).start()
        else:
            falar("Não identifiquei a matéria. Tente novamente.")

    # ── Adicionar prova ───────────────────────────────────
    elif any(p in comando for p in [
        "adicionar prova", "marcar prova", "tenho prova",
        "adicionar entrega", "marcar entrega", "tenho entrega",
    ]):
        chave, info = _identificar_materia(comando)
        tipo = "entrega" if "entrega" in comando else "prova"
        if not chave:
            falar_sync(f"Prova de qual matéria?")
            resp  = ouvir_pergunta(timeout=8, limite=10)
            chave, info = _identificar_materia(resp) if resp else (None, None)
        if chave:
            import re as _re
            m_dia = _re.search(r"dia\s+(\d{1,2})", comando)
            mes   = next((n for nm, n in MESES_ESTUDOS.items() if nm in comando), None)
            if m_dia and mes:
                falar(adicionar_prova(chave, int(m_dia.group(1)), mes, tipo=tipo))
            else:
                falar_sync(f"Qual a data? Fale: dia 15 de junho.")
                resp = ouvir_pergunta(timeout=10, limite=15)
                if resp:
                    m_dia2 = _re.search(r"dia\s+(\d{1,2})", resp)
                    mes2   = next((n for nm, n in MESES_ESTUDOS.items() if nm in resp), None)
                    if m_dia2 and mes2:
                        falar(adicionar_prova(chave, int(m_dia2.group(1)), mes2, tipo=tipo))
                    else:
                        falar("Não entendi a data. Tente novamente.")

    # ── Listar provas ─────────────────────────────────────
    elif any(p in comando for p in [
        "próximas provas", "proximas provas", "minhas provas",
        "provas agendadas", "quando são as provas", "ver provas",
    ]):
        hud.safe_update("foco", "PROVAS", "Carregando...")
        falar(listar_provas())

    # ── Marcar matéria como estudada ──────────────────────
    elif any(p in comando for p in [
        "marcar como estudada", "estudei", "terminei de estudar",
        "acabei de estudar",
    ]):
        chave, info = _identificar_materia(comando)
        if chave:
            falar(marcar_estudada(chave))
        else:
            falar_sync("Qual matéria você estudou?")
            resp  = ouvir_pergunta(timeout=8, limite=10)
            chave, info = _identificar_materia(resp) if resp else (None, None)
            if chave:
                falar(marcar_estudada(chave))

    # ── Progresso ─────────────────────────────────────────
    elif any(p in comando for p in [
        "progresso de hoje", "o que estudei hoje", "estudei hoje",
    ]):
        falar(progresso_hoje())

    elif any(p in comando for p in [
        "quanto estudei essa semana", "progresso da semana",
        "relatório de estudos", "relatorio de estudos",
    ]):
        hud.safe_update("foco", "RELATÓRIO", "Calculando...")
        falar(relatorio_progresso())


── PATCH 3: INICIALIZAÇÃO (em rodar_jarvis, após ev_anunciar_iniciais) ──

    # Inicia alertas de provas
    iniciar_alertas_provas(falar_sync, hud)
"""
