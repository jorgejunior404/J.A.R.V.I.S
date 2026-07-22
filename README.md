# J.A.R.V.I.S. 🤖

> Assistente pessoal de IA para desktop Linux — modular, orientado a plugins e com HUD próprio.

Projeto pessoal em desenvolvimento contínuo, construído em Python, rodando como serviço de sistema no Linux Mint. O objetivo é ter um assistente real de produtividade — não um brinquedo de terminal — com voz, interface visual, automações e módulos de estudo integrados à rotina acadêmica.

---

## ✨ Funcionalidades

- **Backend LLM via Groq** — motor de linguagem principal do assistente (substituiu o Gemini após esgotamento de cota)
- **Function calling** — o modelo aciona ferramentas reais do sistema através de `jarvis_tools.py`
- **Sistema de plugins** — arquitetura de registro (*plugin registry pattern*) para adicionar novas capacidades sem tocar no core
- **HUD visual (desktop + web)** — painel com bolhas de chat roláveis, níveis de exibição configuráveis
- **Modo "pato de borracha"** — debugging conversacional, pensando em voz alta junto com o assistente
- **Insights cruzados** — módulo que correlaciona dados de diferentes fontes/plugins
- **Briefing via WhatsApp** — integração com Evolution API (Docker) para receber resumos diretamente no WhatsApp
- **Módulo de estudos (`jarvis_estudos.py`)** — quizzes ativados por voz e acompanhamento de provas para as disciplinas da graduação
- **Texto-para-voz via edge-tts** — após testes com Kokoro-82M, a escolha final priorizou estabilidade e latência

---

## 🧱 Arquitetura

```
J.A.R.V.I.S/
├── jarvis_core.py        # núcleo: orquestração, contexto, ciclo principal
├── jarvis_hud.py          # interface HUD desktop
├── jarvis_web_hud.py       # interface HUD web
├── jarvis_launcher.py      # ponto de entrada / inicialização
├── jarvis_tools.py         # function calling / ferramentas expostas ao LLM
├── jarvis_estudos.py       # módulo de estudos e quizzes por voz
├── jarvis_plugins/         # plugins registrados dinamicamente
└── .venv/                  # ambiente virtual Python
```

## 🛠️ Stack técnica

| Camada | Tecnologia |
|---|---|
| Linguagem | Python |
| LLM | Groq API |
| TTS | edge-tts |
| Mensageria | Evolution API (Docker) |
| Execução | systemd (user service) + autostart XDG |
| SO alvo | Linux Mint (Cinnamon) |

---

## ⚙️ Instalação

```bash
git clone https://github.com/jorgejunior404/J.A.R.V.I.S.git
cd J.A.R.V.I.S
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Configure as chaves de API necessárias (Groq, Evolution API) em um arquivo `.env` na raiz do projeto (não versionado).

### Rodando como serviço (systemd)

```bash
systemctl --user enable jarvis.service
systemctl --user start jarvis.service
```

---

## ⌨️ Atalhos

| Atalho | Ação |
|---|---|
| `Ctrl+Alt+J` | Ativa/desativa o J.A.R.V.I.S. |
| `Ctrl+Shift+1` | HUD nível 1 |
| `Ctrl+Shift+2` | HUD nível 2 |
| `Ctrl+Shift+3` | HUD nível 3 |

---

## 🗺️ Roadmap

- [ ] Expandir cobertura de plugins
- [ ] Melhorar precisão do módulo de insights cruzados
- [ ] Explorar novos modelos de TTS conforme necessidade
- [ ] Ampliar integrações de automação de desktop

---

## 📄 Licença

Projeto pessoal — uso e estudo livres. Licença a definir.