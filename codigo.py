"""
DocGartic - Jogo multiplayer estilo Gartic para Documentos Técnicos e Administrativos
======================================================================================
Arquitetura de sincronização:
- st.cache_resource cria um único dicionário compartilhado em memória para TODOS os usuários.
- Cada sessão individual usa st.session_state apenas para dados locais (nome do jogador, etc).
- st.rerun() é chamado periodicamente (via auto-refresh) para sincronizar o estado global.
- Um lock de threading garante escrita segura quando múltiplos usuários interagem ao mesmo tempo.
"""

import streamlit as st
import time
import unicodedata
import threading
import random
from datetime import datetime

# ─────────────────────────────────────────────
# ESTADO GLOBAL COMPARTILHADO (uma única instância para todos os usuários)
# ─────────────────────────────────────────────

@st.cache_resource
def get_global_state():
    """
    Retorna o estado global do jogo. Por ser decorado com @st.cache_resource,
    esta função retorna SEMPRE o mesmo objeto para todas as sessões simultâneas.
    É o equivalente a um 'singleton' compartilhado entre todos os jogadores.
    """
    return {
        "rodada_atual": 0,          # 0 = lobby, 1-12 = rodadas ativas
        "documentos_sorteados": [],  # ordem das rodadas já embaralhada
        "dicas_liberadas": 0,        # quantas dicas foram reveladas (0-4)
        "jogadores": {},             # {session_id: {"nome": str, "pontos": int, "ultimo_ping": float}}
        "acertaram": [],             # lista de session_ids que acertaram na rodada atual
        "chat": [],                  # [{"autor": str, "msg": str, "tipo": "normal"|"acerto"|"sistema"}]
        "jogo_iniciado": False,
        "rodada_encerrada": False,
        "hora_inicio_rodada": None,
        "duracao_rodada": 90,        # segundos por rodada
    }

@st.cache_resource
def get_lock():
    """Lock de threading para operações de escrita no estado global."""
    return threading.Lock()


# ─────────────────────────────────────────────
# DADOS DOS DOCUMENTOS (12 tipos)
# ─────────────────────────────────────────────

DOCUMENTOS = {
    "Ata": {
        "emojis": "📝🤝⏰📋",
        "dicas": [
            "📌 Dica 1: Registra formalmente as decisões tomadas em reuniões e assembleias.",
            "📌 Dica 2: Não pode ter rasuras, emendas ou espaços em branco.",
            "📌 Dica 3: Utiliza verbos predominantemente no pretérito perfeito do indicativo.",
            "📌 Dica 4: Geralmente assinada por um secretário e pelo presidente da reunião.",
        ],
    },
    "Memorando": {
        "emojis": "📨🏢↔️💼",
        "dicas": [
            "📌 Dica 1: Comunicação interna entre setores ou departamentos de uma mesma instituição.",
            "📌 Dica 2: Possui linguagem objetiva e direta, com texto geralmente curto.",
            "📌 Dica 3: Identifica o remetente e o destinatário pelo cargo, não pelo nome completo.",
            "📌 Dica 4: Muito usado em órgãos públicos para despachos e encaminhamentos rápidos.",
        ],
    },
    "E-mail corporativo": {
        "emojis": "📧💻🌐🔔",
        "dicas": [
            "📌 Dica 1: Comunicação eletrônica formal utilizada no ambiente profissional.",
            "📌 Dica 2: Deve ter assunto claro, saudação, corpo e assinatura com dados do remetente.",
            "📌 Dica 3: Evita gírias, emojis e abreviações informais.",
            "📌 Dica 4: Pode incluir 'CC' (cópia) e 'CCO' (cópia oculta) para múltiplos destinatários.",
        ],
    },
    "Recibo": {
        "emojis": "🧾💰✅📄",
        "dicas": [
            "📌 Dica 1: Comprova o recebimento de dinheiro, bens ou serviços.",
            "📌 Dica 2: Deve conter valor (por extenso), data, identificação do pagador e do recebedor.",
            "📌 Dica 3: Tem validade jurídica como prova de quitação de uma obrigação.",
            "📌 Dica 4: Geralmente assinado apenas por quem RECEBE o pagamento ou o bem.",
        ],
    },
    "Ofício": {
        "emojis": "🏛️📜✉️🖊️",
        "dicas": [
            "📌 Dica 1: Comunicação oficial entre órgãos públicos ou entre o poder público e cidadãos.",
            "📌 Dica 2: Possui numeração sequencial por ano (ex: Ofício nº 042/2024).",
            "📌 Dica 3: Segue o padrão oficial de redação com vocativo, corpo e fecho.",
            "📌 Dica 4: Diferente do Memorando, ele é usado para comunicação EXTERNA à instituição.",
        ],
    },
    "Relatório Técnico": {
        "emojis": "📊🔬📈🗂️",
        "dicas": [
            "📌 Dica 1: Descreve metodicamente uma atividade, pesquisa ou inspeção realizada.",
            "📌 Dica 2: Possui estrutura formal: introdução, desenvolvimento, conclusão e recomendações.",
            "📌 Dica 3: Pode incluir tabelas, gráficos, anexos e referências bibliográficas.",
            "📌 Dica 4: Emitido por profissional habilitado, muitas vezes com responsabilidade técnica (ART).",
        ],
    },
    "Procuração": {
        "emojis": "🤲⚖️📜🔑",
        "dicas": [
            "📌 Dica 1: Documento pelo qual uma pessoa (outorgante) concede poderes a outra (outorgado).",
            "📌 Dica 2: Pode ser pública (lavrada em cartório) ou particular (assinada entre as partes).",
            "📌 Dica 3: Especifica quais atos o representante está autorizado a praticar.",
            "📌 Dica 4: Pode ter prazo determinado ou ser por tempo indeterminado até revogação.",
        ],
    },
    "Contrato": {
        "emojis": "🤝📃✍️⚖️",
        "dicas": [
            "📌 Dica 1: Acordo de vontades entre duas ou mais partes para criar, modificar ou extinguir direitos.",
            "📌 Dica 2: Para ter validade, precisa de agente capaz, objeto lícito e forma prescrita em lei.",
            "📌 Dica 3: Deve conter cláusulas sobre obrigações, prazos, valores e penalidades.",
            "📌 Dica 4: Geralmente assinado por ambas as partes e duas testemunhas.",
        ],
    },
    "Declaração": {
        "emojis": "🗣️📋✔️🏅",
        "dicas": [
            "📌 Dica 1: Afirma ou confirma um fato ou situação, assumindo responsabilidade pela veracidade.",
            "📌 Dica 2: Usa a fórmula 'Declaro para os devidos fins que...'.",
            "📌 Dica 3: Pode ser de residência, de renda, de hipossuficiência, entre outras.",
            "📌 Dica 4: Geralmente assinada pelo declarante e pode exigir reconhecimento de firma.",
        ],
    },
    "Requerimento": {
        "emojis": "🙏📩🏢📝",
        "dicas": [
            "📌 Dica 1: Pedido formal feito por um cidadão ou parte interessada a uma autoridade.",
            "📌 Dica 2: Segue a estrutura: identificação do requerente, exposição dos fatos e pedido.",
            "📌 Dica 3: Termina com a fórmula 'Nestes termos, pede deferimento'.",
            "📌 Dica 4: Muito utilizado em processos administrativos, matrículas e solicitações em órgãos públicos.",
        ],
    },
    "Circular": {
        "emojis": "🔄📢👥📬",
        "dicas": [
            "📌 Dica 1: Comunicação enviada simultaneamente para múltiplos destinatários.",
            "📌 Dica 2: Seu conteúdo é idêntico para todos que a recebem (daí o nome 'circular').",
            "📌 Dica 3: Usada para transmitir normas, instruções ou informações de interesse coletivo.",
            "📌 Dica 4: Comum em empresas para comunicar mudanças de política ou avisos gerais.",
        ],
    },
    "Edital": {
        "emojis": "📣🏆📰🔍",
        "dicas": [
            "📌 Dica 1: Ato público que convoca interessados ou torna pública uma informação oficial.",
            "📌 Dica 2: Usado em concursos públicos, licitações, seleções e processos seletivos.",
            "📌 Dica 3: Deve ser publicado em veículo de ampla divulgação (Diário Oficial, sites, murais).",
            "📌 Dica 4: Define regras, prazos, requisitos e critérios de seleção de forma vinculante.",
        ],
    },
}

TOTAL_RODADAS = 12


# ─────────────────────────────────────────────
# FUNÇÕES UTILITÁRIAS
# ─────────────────────────────────────────────

def normalizar(texto: str) -> str:
    """Remove acentos e converte para minúsculas para comparação flexível."""
    nfkd = unicodedata.normalize("NFKD", texto)
    sem_acento = "".join(c for c in nfkd if not unicodedata.combining(c))
    return sem_acento.lower().strip()


def documento_da_rodada(gs) -> str | None:
    """Retorna o nome do documento da rodada atual, ou None se fora de jogo."""
    if gs["rodada_atual"] < 1 or gs["rodada_atual"] > TOTAL_RODADAS:
        return None
    if not gs["documentos_sorteados"]:
        return None
    return gs["documentos_sorteados"][gs["rodada_atual"] - 1]


def tempo_restante(gs) -> int:
    """Calcula segundos restantes na rodada atual."""
    if not gs["hora_inicio_rodada"]:
        return gs["duracao_rodada"]
    elapsed = time.time() - gs["hora_inicio_rodada"]
    remaining = gs["duracao_rodada"] - int(elapsed)
    return max(0, remaining)


def adicionar_mensagem_chat(gs, autor: str, msg: str, tipo: str = "normal"):
    """Adiciona uma mensagem ao chat global. Mantém no máximo 80 mensagens."""
    gs["chat"].append({
        "autor": autor,
        "msg": msg,
        "tipo": tipo,
        "hora": datetime.now().strftime("%H:%M"),
    })
    if len(gs["chat"]) > 80:
        gs["chat"] = gs["chat"][-80:]


def registrar_ping(gs, session_id: str):
    """Atualiza o timestamp do jogador para indicar que está ativo (evitar fantasmas)."""
    if session_id in gs["jogadores"]:
        gs["jogadores"][session_id]["ultimo_ping"] = time.time()


def limpar_jogadores_inativos(gs):
    """Remove jogadores sem ping nos últimos 30 segundos (sessões fechadas)."""
    agora = time.time()
    inativos = [
        sid for sid, dados in gs["jogadores"].items()
        if agora - dados.get("ultimo_ping", 0) > 30
    ]
    for sid in inativos:
        nome = gs["jogadores"][sid]["nome"]
        del gs["jogadores"][sid]
        # Remove também da lista de acertaram caso esteja
        if sid in gs["acertaram"]:
            gs["acertaram"].remove(sid)
        adicionar_mensagem_chat(gs, "🔌 Sistema", f"{nome} saiu do jogo.", "sistema")


def avancar_rodada(gs):
    """Avança para a próxima rodada ou encerra o jogo."""
    gs["rodada_atual"] += 1
    gs["dicas_liberadas"] = 1          # Começa com a dica 1 já visível
    gs["acertaram"] = []
    gs["rodada_encerrada"] = False
    gs["hora_inicio_rodada"] = time.time()

    if gs["rodada_atual"] > TOTAL_RODADAS:
        gs["jogo_iniciado"] = False
        adicionar_mensagem_chat(gs, "🏆 Sistema", "Jogo encerrado! Veja o ranking final.", "sistema")
    else:
        doc = documento_da_rodada(gs)
        adicionar_mensagem_chat(
            gs, "🎮 Sistema",
            f"Rodada {gs['rodada_atual']}/{TOTAL_RODADAS} começou! Adivinhe o documento! ⏱️",
            "sistema",
        )
        # Revela automaticamente dicas a cada 20s — a lógica de revelação é feita no render
        _ = doc  # doc referenciado na função de render


def iniciar_jogo(gs):
    """Embaralha os documentos e começa a rodada 0 → 1."""
    docs = list(DOCUMENTOS.keys())
    random.shuffle(docs)
    gs["documentos_sorteados"] = docs
    gs["rodada_atual"] = 0
    gs["chat"] = []
    gs["acertaram"] = []
    gs["rodada_encerrada"] = False
    # Zera pontos de todos os jogadores
    for sid in gs["jogadores"]:
        gs["jogadores"][sid]["pontos"] = 0
    gs["jogo_iniciado"] = True
    adicionar_mensagem_chat(gs, "🎮 Sistema", "Jogo iniciado! Boa sorte a todos! 🚀", "sistema")
    avancar_rodada(gs)


# ─────────────────────────────────────────────
# CONFIGURAÇÃO DA PÁGINA
# ─────────────────────────────────────────────

st.set_page_config(
    page_title="DocGartic 📝",
    page_icon="📝",
    layout="wide",
    initial_sidebar_state="expanded",
)

# CSS customizado para visual mais atraente
st.markdown("""
<style>
/* Fundo e tipografia geral */
.main { background-color: #0f1117; }

/* Card de dica */
.dica-card {
    background: linear-gradient(135deg, #1e2a3a, #253347);
    border-left: 4px solid #4e9af1;
    border-radius: 8px;
    padding: 12px 16px;
    margin: 6px 0;
    color: #e0e6f0;
    font-size: 1.05rem;
}

/* Emojis da rodada */
.emoji-box {
    background: #1a1f2e;
    border-radius: 16px;
    padding: 20px;
    text-align: center;
    font-size: 3rem;
    letter-spacing: 10px;
    margin-bottom: 16px;
    border: 1px solid #2d3a4f;
}

/* Mensagens do chat */
.chat-msg-acerto {
    background: linear-gradient(90deg, #1a3a1a, #1e4a1e);
    border-left: 4px solid #2ecc71;
    border-radius: 6px;
    padding: 8px 12px;
    margin: 4px 0;
    color: #a8f0c0;
    font-weight: bold;
}
.chat-msg-sistema {
    background: #1a1a2e;
    border-left: 4px solid #9b59b6;
    border-radius: 6px;
    padding: 8px 12px;
    margin: 4px 0;
    color: #c9a0f0;
    font-style: italic;
}
.chat-msg-normal {
    background: #16213e;
    border-radius: 6px;
    padding: 8px 12px;
    margin: 4px 0;
    color: #cdd6e8;
}

/* Cronômetro */
.timer-box {
    background: #1e2a3a;
    border-radius: 12px;
    padding: 10px 20px;
    text-align: center;
    font-size: 1.8rem;
    font-weight: bold;
    color: #4e9af1;
    border: 2px solid #2d4a6a;
    margin-bottom: 12px;
}
.timer-box.urgente { color: #e74c3c; border-color: #6a2d2d; }

/* Ranking */
.rank-item {
    display: flex;
    justify-content: space-between;
    background: #1a2332;
    border-radius: 6px;
    padding: 8px 12px;
    margin: 4px 0;
    color: #cdd6e8;
}

/* Badge da rodada */
.rodada-badge {
    background: linear-gradient(135deg, #2d5a8e, #1a3a6e);
    border-radius: 20px;
    padding: 6px 20px;
    display: inline-block;
    color: #a0c4f8;
    font-size: 0.9rem;
    font-weight: bold;
    margin-bottom: 10px;
}
</style>
""", unsafe_allow_html=True)


# ─────────────────────────────────────────────
# INICIALIZAÇÃO DA SESSÃO LOCAL
# ─────────────────────────────────────────────

# Gera um ID único e persistente para esta sessão do navegador
if "session_id" not in st.session_state:
    st.session_state.session_id = f"user_{random.randint(100000, 999999)}"

if "nome_jogador" not in st.session_state:
    st.session_state.nome_jogador = ""

if "ja_no_jogo" not in st.session_state:
    st.session_state.ja_no_jogo = False

# Referências globais
gs = get_global_state()
lock = get_lock()
sid = st.session_state.session_id


# ─────────────────────────────────────────────
# MANUTENÇÃO DO ESTADO GLOBAL (a cada render)
# ─────────────────────────────────────────────

with lock:
    # Pinga o jogador para marcar como ativo
    if st.session_state.ja_no_jogo:
        registrar_ping(gs, sid)

    # Verifica se a rodada expirou por tempo
    if gs["jogo_iniciado"] and not gs["rodada_encerrada"] and gs["hora_inicio_rodada"]:
        if tempo_restante(gs) == 0:
            gs["rodada_encerrada"] = True
            doc_atual = documento_da_rodada(gs)
            if doc_atual:
                adicionar_mensagem_chat(
                    gs, "⏰ Sistema",
                    f"Tempo esgotado! O documento era: **{doc_atual}** 📄",
                    "sistema",
                )

    # Revela dicas progressivamente (1 por cada 20s decorridos na rodada)
    if gs["jogo_iniciado"] and not gs["rodada_encerrada"] and gs["hora_inicio_rodada"]:
        elapsed = time.time() - gs["hora_inicio_rodada"]
        dicas_devidas = min(4, 1 + int(elapsed // 20))  # dica 1 imediata, +1 a cada 20s
        if dicas_devidas > gs["dicas_liberadas"]:
            gs["dicas_liberadas"] = dicas_devidas


# ─────────────────────────────────────────────
# BARRA LATERAL
# ─────────────────────────────────────────────

with st.sidebar:
    st.markdown("## 📝 DocGartic")
    st.caption("Jogo de Documentos Técnicos")
    st.divider()

    # ── Entrada no jogo ──
    if not st.session_state.ja_no_jogo:
        st.markdown("### 👤 Entrar no Jogo")
        nome_input = st.text_input("Seu apelido:", max_chars=20, placeholder="Ex: João123")
        if st.button("🚪 Entrar na Sala", use_container_width=True):
            nome_input = nome_input.strip()
            if not nome_input:
                st.error("Digite um apelido!")
            else:
                # Verifica duplicata de nome
                nomes_existentes = [d["nome"] for d in gs["jogadores"].values()]
                if nome_input in nomes_existentes:
                    st.error("Este apelido já está em uso! Escolha outro.")
                else:
                    with lock:
                        gs["jogadores"][sid] = {
                            "nome": nome_input,
                            "pontos": 0,
                            "ultimo_ping": time.time(),
                        }
                        adicionar_mensagem_chat(
                            gs, "🎮 Sistema",
                            f"{nome_input} entrou na sala! 👋",
                            "sistema",
                        )
                    st.session_state.nome_jogador = nome_input
                    st.session_state.ja_no_jogo = True
                    st.rerun()
    else:
        st.success(f"✅ Jogando como: **{st.session_state.nome_jogador}**")
        if st.button("🚪 Sair da Sala", use_container_width=True):
            with lock:
                if sid in gs["jogadores"]:
                    nome = gs["jogadores"][sid]["nome"]
                    del gs["jogadores"][sid]
                    adicionar_mensagem_chat(gs, "🔌 Sistema", f"{nome} saiu da sala.", "sistema")
            st.session_state.ja_no_jogo = False
            st.session_state.nome_jogador = ""
            st.rerun()

    st.divider()

    # ── Lista de jogadores ──
    st.markdown("### 👥 Jogadores na Sala")
    if gs["jogadores"]:
        for _, dados in sorted(gs["jogadores"].items(), key=lambda x: x[1]["pontos"], reverse=True):
            st.markdown(
                f'<div class="rank-item"><span>👤 {dados["nome"]}</span><span>⭐ {dados["pontos"]} pts</span></div>',
                unsafe_allow_html=True,
            )
    else:
        st.caption("Nenhum jogador na sala ainda.")

    st.divider()

    # ── Controles do jogo (qualquer jogador pode iniciar) ──
    if st.session_state.ja_no_jogo:
        st.markdown("### 🎛️ Controles")
        if not gs["jogo_iniciado"]:
            jogadores_count = len(gs["jogadores"])
            st.caption(f"Aguardando jogadores... ({jogadores_count} na sala)")
            if st.button("▶️ Iniciar Jogo", use_container_width=True, disabled=jogadores_count < 1):
                with lock:
                    iniciar_jogo(gs)
                st.rerun()
        else:
            # Botão de próxima rodada (disponível quando encerrada)
            if gs["rodada_encerrada"] and gs["rodada_atual"] <= TOTAL_RODADAS:
                if st.button("⏭️ Próxima Rodada", use_container_width=True):
                    with lock:
                        avancar_rodada(gs)
                    st.rerun()
            elif not gs["rodada_encerrada"] and gs["rodada_atual"] <= TOTAL_RODADAS:
                # Jogadores com todos os pontos possíveis podem encerrar manualmente
                if st.button("⏩ Encerrar Rodada", use_container_width=True):
                    with lock:
                        gs["rodada_encerrada"] = True
                        doc_atual = documento_da_rodada(gs)
                        if doc_atual:
                            adicionar_mensagem_chat(
                                gs, "⏰ Sistema",
                                f"Rodada encerrada! O documento era: **{doc_atual}** 📄",
                                "sistema",
                            )
                    st.rerun()

    st.divider()
    st.caption("🔄 Atualiza a cada 3s automaticamente")


# ─────────────────────────────────────────────
# PAINEL CENTRAL PRINCIPAL
# ─────────────────────────────────────────────

st.markdown("# 📝 DocGartic — Jogo de Documentos Técnicos")

if not st.session_state.ja_no_jogo:
    # ── Tela de boas-vindas ──
    st.info("👈 **Digite seu apelido na barra lateral e clique em 'Entrar na Sala' para jogar!**")
    st.markdown("""
    ### 🎯 Como Jogar
    1. Cada rodada apresenta **emojis** e **dicas** sobre um documento técnico.
    2. Digite sua resposta no campo de palpite.
    3. Quem acertar primeiro ganha **10 pontos**, os seguintes ganham **5 pontos**.
    4. As dicas vão sendo reveladas automaticamente ao longo da rodada.
    5. São **12 rodadas** no total, uma para cada tipo de documento!

    ### 📂 Documentos do Jogo
    """)
    cols = st.columns(4)
    for i, doc in enumerate(DOCUMENTOS.keys()):
        with cols[i % 4]:
            st.markdown(f"- **{doc}**")

elif not gs["jogo_iniciado"] and gs["rodada_atual"] == 0:
    # ── Lobby ──
    st.markdown("### 🏠 Sala de Espera")
    st.info(f"Aguardando o início do jogo... **{len(gs['jogadores'])} jogador(es) na sala.**")
    st.markdown("Quando todos estiverem prontos, clique em **▶️ Iniciar Jogo** na barra lateral!")

elif not gs["jogo_iniciado"] and gs["rodada_atual"] > TOTAL_RODADAS:
    # ── Tela final de ranking ──
    st.markdown("## 🏆 Jogo Encerrado! Ranking Final")
    ranking = sorted(gs["jogadores"].items(), key=lambda x: x[1]["pontos"], reverse=True)
    medals = ["🥇", "🥈", "🥉"]
    for i, (_, dados) in enumerate(ranking):
        medal = medals[i] if i < 3 else f"#{i+1}"
        st.markdown(
            f'<div class="rank-item" style="font-size:1.2rem; padding:14px">'
            f'<span>{medal} {dados["nome"]}</span>'
            f'<span>⭐ {dados["pontos"]} pontos</span>'
            f'</div>',
            unsafe_allow_html=True,
        )
    if st.session_state.ja_no_jogo:
        if st.button("🔄 Jogar Novamente", use_container_width=False):
            with lock:
                iniciar_jogo(gs)
            st.rerun()

else:
    # ── TELA DE JOGO ATIVO ──
    doc_atual = documento_da_rodada(gs)
    info_doc = DOCUMENTOS.get(doc_atual, {}) if doc_atual else {}

    col_jogo, col_chat = st.columns([3, 2], gap="large")

    with col_jogo:
        # Cabeçalho da rodada
        st.markdown(
            f'<div class="rodada-badge">🎮 Rodada {gs["rodada_atual"]} de {TOTAL_RODADAS}</div>',
            unsafe_allow_html=True,
        )

        # Cronômetro
        restante = tempo_restante(gs)
        timer_class = "timer-box urgente" if restante <= 15 else "timer-box"
        mins, secs = divmod(restante, 60)
        st.markdown(
            f'<div class="{timer_class}">⏱️ {mins:02d}:{secs:02d}</div>',
            unsafe_allow_html=True,
        )

        if doc_atual:
            # Emojis da rodada
            emojis = info_doc.get("emojis", "❓")
            st.markdown(f'<div class="emoji-box">{emojis}</div>', unsafe_allow_html=True)

            # Indicador de dicas
            total_dicas = len(info_doc.get("dicas", []))
            dicas_vis = gs["dicas_liberadas"]
            st.markdown(f"**💡 Dicas reveladas: {dicas_vis}/{total_dicas}**")

            # Dicas liberadas
            dicas = info_doc.get("dicas", [])
            for i, dica in enumerate(dicas):
                if i < gs["dicas_liberadas"]:
                    st.markdown(f'<div class="dica-card">{dica}</div>', unsafe_allow_html=True)
                else:
                    st.markdown(
                        f'<div class="dica-card" style="opacity:0.3;filter:blur(4px)">📌 Dica {i+1}: ???</div>',
                        unsafe_allow_html=True,
                    )

            # Se rodada encerrada, revela o documento
            if gs["rodada_encerrada"]:
                st.success(f"📄 O documento era: **{doc_atual}**")
                st.balloons()

        # ── Campo de palpite ──
        st.markdown("---")
        if not gs["rodada_encerrada"]:
            ja_acertou = sid in gs["acertaram"]
            if ja_acertou:
                st.success("✅ Você já acertou esta rodada! Aguarde os outros jogadores.")
            else:
                with st.form(key="form_palpite", clear_on_submit=True):
                    palpite_input = st.text_input(
                        "🎯 Seu palpite:",
                        placeholder="Digite o nome do documento...",
                        max_chars=50,
                        label_visibility="collapsed",
                    )
                    enviado = st.form_submit_button("📨 Enviar Palpite", use_container_width=True)

                if enviado and palpite_input.strip():
                    nome_jog = st.session_state.nome_jogador
                    palpite_norm = normalizar(palpite_input)
                    correto_norm = normalizar(doc_atual) if doc_atual else ""

                    with lock:
                        if palpite_norm == correto_norm:
                            # Calcula pontos: primeiro acerta 10, demais 5
                            pontos_ganhos = 10 if not gs["acertaram"] else 5
                            gs["jogadores"][sid]["pontos"] += pontos_ganhos
                            gs["acertaram"].append(sid)
                            adicionar_mensagem_chat(
                                gs,
                                nome_jog,
                                f"🎉 ACERTOU e ganhou {pontos_ganhos} pontos!",
                                "acerto",
                            )
                        else:
                            # Palpite errado vai para o chat público
                            adicionar_mensagem_chat(gs, nome_jog, palpite_input, "normal")
                    st.rerun()
        else:
            st.info("⏳ Rodada encerrada. Clique em **⏭️ Próxima Rodada** na barra lateral.")

    # ── CHAT ──
    with col_chat:
        st.markdown("### 💬 Chat da Rodada")

        # Exibe mensagens (mais recentes no final)
        chat_html = ""
        for msg in gs["chat"][-30:]:  # últimas 30 mensagens
            hora = msg.get("hora", "")
            autor = msg["autor"]
            texto = msg["msg"]
            tipo = msg["tipo"]

            if tipo == "acerto":
                chat_html += f'<div class="chat-msg-acerto"><span style="opacity:0.6">{hora}</span> <b>{autor}</b>: {texto}</div>'
            elif tipo == "sistema":
                chat_html += f'<div class="chat-msg-sistema"><span style="opacity:0.6">{hora}</span> {texto}</div>'
            else:
                chat_html += f'<div class="chat-msg-normal"><span style="opacity:0.6">{hora}</span> <b>{autor}</b>: {texto}</div>'

        st.markdown(
            f'<div style="height:420px;overflow-y:auto;padding:8px;background:#0e1117;border-radius:10px;border:1px solid #2d3a4f">{chat_html}</div>',
            unsafe_allow_html=True,
        )

        # Mini ranking durante o jogo
        st.markdown("### 📊 Placar")
        ranking_jogo = sorted(gs["jogadores"].items(), key=lambda x: x[1]["pontos"], reverse=True)
        medals = ["🥇", "🥈", "🥉"]
        for i, (_, dados) in enumerate(ranking_jogo[:5]):
            medal = medals[i] if i < 3 else f"#{i+1}"
            st.markdown(
                f'<div class="rank-item">'
                f'<span>{medal} {dados["nome"]}</span>'
                f'<span>⭐ {dados["pontos"]}</span>'
                f'</div>',
                unsafe_allow_html=True,
            )


# ─────────────────────────────────────────────
# AUTO-REFRESH (sincronização periódica entre usuários)
# ─────────────────────────────────────────────
# Usamos st.empty() + time.sleep() em combinação com st.rerun() para
# simular um refresh automático a cada 3 segundos, mantendo todos os
# usuários sincronizados com o estado global compartilhado.

if st.session_state.ja_no_jogo and gs["jogo_iniciado"] and not gs["rodada_encerrada"]:
    time.sleep(3)
    st.rerun()
elif st.session_state.ja_no_jogo and gs["jogo_iniciado"] and gs["rodada_encerrada"]:
    # Quando encerrada, ainda sincroniza (mais lento)
    time.sleep(5)
    st.rerun()
