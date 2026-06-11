"""
DocGartic - Jogo multiplayer estilo Gartic para Documentos Técnicos e Administrativos
======================================================================================
MECÂNICA ATUALIZADA:
- fase_preparacao (30s): desenhista monta o quadro de emojis antes da rodada começar colando/digitando
- Durante a rodada: quadro estático para todos (inclusive gerenciador)
- Gerenciador: vê todas as respostas possíveis ANTES de encerrar; só exibe a correta APÓS encerrar
"""

import streamlit as st
import time
import unicodedata
import threading
import random
from datetime import datetime

# ─────────────────────────────────────────────
# ESTADO GLOBAL COMPARTILHADO
# ─────────────────────────────────────────────

@st.cache_resource
def get_global_state():
    return {
        "rodada_atual": 0,
        "documentos_sorteados": [],
        "dicas_liberadas": 0,
        "jogadores": {},            # {sid: {nome, pontos, ultimo_ping}}
        "desenhista_sid": None,
        "acertaram": [],
        "chat": [],
        "emojis_quadro": "",        # Alterado para string (recebe o input direto)
        "jogo_iniciado": False,
        "rodada_encerrada": False,
        "hora_inicio_rodada": None,
        "duracao_rodada": 120,
        "fase_preparacao": False,   
        "hora_inicio_prep": None,   
        "duracao_prep": 30,         
    }

@st.cache_resource
def get_lock():
    return threading.Lock()

# ─────────────────────────────────────────────
# DADOS DOS DOCUMENTOS
# ─────────────────────────────────────────────

MANAGER_PASSWORD = "admin123"

DOCUMENTOS = {
    "Ata": {
        "descricao": "Documento que registra formalmente as ocorrências, deliberações e decisões tomadas em reuniões...",
        "dicas": ["Registra decisões de reuniões","Não pode ter rasuras","Verbos no pretérito perfeito","Assinada por secretário e presidente"],
    },
    "Memorando": {
        "descricao": "Correspondência interna de uso rotineiro entre setores ou departamentos de uma mesma organização...",
        "dicas": ["Comunicação interna entre setores","Linguagem objetiva e direta","Identifica remetente pelo cargo","Muito usado em órgãos públicos"],
    },
    "E-mail corporativo": {
        "descricao": "Mensagem eletrônica formal utilizada no ambiente profissional...",
        "dicas": ["Comunicação eletrônica formal","Deve ter assunto, saudação e assinatura","Evita gírias e abreviações","Pode incluir CC e CCO"],
    },
    "Recibo": {
        "descricao": "Documento que comprova o recebimento de dinheiro, bens ou serviços...",
        "dicas": ["Comprova recebimento de dinheiro ou bens","Deve conter valor por extenso e data","Tem validade jurídica","Assinado por quem RECEBE"],
    },
    "Ofício": {
        "descricao": "Documento de comunicação oficial utilizado entre órgãos públicos ou entidades privadas...",
        "dicas": ["Comunicação oficial entre órgãos públicos","Numeração sequencial por ano","Segue padrão oficial com vocativo e fecho","Usado para comunicação EXTERNA"],
    },
    "Relatório Técnico": {
        "descricao": "Documento elaborado por profissional habilitado que descreve, analisa e apresenta conclusões...",
        "dicas": ["Descreve atividade ou pesquisa realizada","Estrutura: introdução, desenvolvimento, conclusão","Pode ter tabelas e referências","Emitido por profissional habilitado"],
    },
    "Procuração": {
        "descricao": "Instrumento pelo qual uma pessoa concede poderes a outra para agir em seu nome...",
        "dicas": ["Concede poderes de representação","Pode ser pública (cartório) ou particular","Especifica atos autorizados","Pode ter prazo ou ser indeterminada"],
    },
    "Contrato": {
        "descricao": "Acordo de vontades entre duas ou mais partes que cria, modifica ou extingue direitos...",
        "dicas": ["Acordo de vontades entre partes","Precisa de agente capaz e objeto lícito","Cláusulas de obrigações e penalidades","Assinado por ambas as partes e testemunhas"],
    },
    "Declaração": {
        "descricao": "Documento em que uma pessoa afirma ou confirma determinado fato, situação ou condição...",
        "dicas": ["Afirma ou confirma um fato","Usa fórmula: Declaro para os devidos fins","Pode ser de residência ou renda","Pode exigir reconhecimento de firma"],
    },
    "Requerimento": {
        "descricao": "Pedido formal dirigido a uma autoridade ou órgão público solicitando providência...",
        "dicas": ["Pedido formal a uma autoridade","Estrutura: identificação, fatos e pedido","Termina com: Nestes termos, pede deferimento","Usado em processos administrativos"],
    },
    "Circular": {
        "descricao": "Comunicação interna ou externa enviada simultaneamente a múltiplos destinatários...",
        "dicas": ["Enviada a múltiplos destinatários","Conteúdo idêntico para todos","Transmite normas ou informações coletivas","Comum para comunicar mudanças de política"],
    },
    "Edital": {
        "descricao": "Ato público oficial que convoca interessados ou dá ciência a todos sobre determinado fato...",
        "dicas": ["Ato público que convoca interessados","Usado em concursos e licitações","Publicado em veículo de ampla divulgação","Define regras e critérios de seleção"],
    },
}

TOTAL_RODADAS = 12

# ─────────────────────────────────────────────
# UTILITÁRIOS
# ─────────────────────────────────────────────

def normalizar(t):
    nfkd = unicodedata.normalize("NFKD", str(t))
    return "".join(c for c in nfkd if not unicodedata.combining(c)).lower().strip()

def documento_da_rodada(gs):
    if gs["rodada_atual"] < 1 or gs["rodada_atual"] > TOTAL_RODADAS:
        return None
    return gs["documentos_sorteados"][gs["rodada_atual"] - 1] if gs["documentos_sorteados"] else None

def tempo_restante_prep(gs):
    if not gs["hora_inicio_prep"]:
        return gs["duracao_prep"]
    return max(0, gs["duracao_prep"] - int(time.time() - gs["hora_inicio_prep"]))

def tempo_restante(gs):
    if not gs["hora_inicio_rodada"]:
        return gs["duracao_rodada"]
    return max(0, gs["duracao_rodada"] - int(time.time() - gs["hora_inicio_rodada"]))

def add_chat(gs, autor, msg, tipo="normal"):
    gs["chat"].append({"autor": autor, "msg": msg, "tipo": tipo, "hora": datetime.now().strftime("%H:%M")})
    if len(gs["chat"]) > 100:
        gs["chat"] = gs["chat"][-100:]

def ping(gs, sid):
    if sid in gs["jogadores"]:
        gs["jogadores"][sid]["ultimo_ping"] = time.time()

def escolher_desenhista(gs):
    jogadores = list(gs["jogadores"].keys())
    if not jogadores:
        return None
    return jogadores[(gs["rodada_atual"] - 1) % len(jogadores)]

def iniciar_fase_preparacao(gs):
    gs["fase_preparacao"] = True
    gs["hora_inicio_prep"] = time.time()
    gs["emojis_quadro"] = ""
    gs["rodada_encerrada"] = False
    gs["acertaram"] = []
    gs["dicas_liberadas"] = 0
    gs["hora_inicio_rodada"] = None
    nome_des = gs["jogadores"].get(gs["desenhista_sid"], {}).get("nome", "?")
    add_chat(gs, "🎨 Sistema", f"⏳ {nome_des} tem {gs['duracao_prep']}s para montar o quadro de emojis!", "sistema")

def iniciar_fase_palpites(gs, emojis_finais):
    gs["fase_preparacao"] = False
    gs["hora_inicio_prep"] = None
    gs["emojis_quadro"] = emojis_finais
    gs["hora_inicio_rodada"] = time.time()
    gs["dicas_liberadas"] = 1
    add_chat(gs, "🎮 Sistema", f"🚀 Rodada {gs['rodada_atual']}/{TOTAL_RODADAS} começou! Adivinhe o documento! 🔍", "sistema")

def avancar_rodada(gs):
    gs["rodada_atual"] += 1
    gs["dicas_liberadas"] = 0
    gs["acertaram"] = []
    gs["rodada_encerrada"] = False
    gs["hora_inicio_rodada"] = None
    gs["emojis_quadro"] = ""
    gs["fase_preparacao"] = False
    gs["hora_inicio_prep"] = None
    if gs["rodada_atual"] > TOTAL_RODADAS:
        gs["jogo_iniciado"] = False
        add_chat(gs, "🏆 Sistema", "Jogo encerrado! Veja o ranking final.", "sistema")
    else:
        gs["desenhista_sid"] = escolher_desenhista(gs)
        iniciar_fase_preparacao(gs)

def iniciar_jogo(gs):
    docs = list(DOCUMENTOS.keys())
    random.shuffle(docs)
    gs["documentos_sorteados"] = docs
    gs["rodada_atual"] = 0
    gs["chat"] = []
    gs["acertaram"] = []
    gs["emojis_quadro"] = ""
    gs["rodada_encerrada"] = False
    gs["fase_preparacao"] = False
    gs["hora_inicio_prep"] = None
    gs["hora_inicio_rodada"] = None
    for s in gs["jogadores"]:
        gs["jogadores"][s]["pontos"] = 0
    gs["jogo_iniciado"] = True
    add_chat(gs, "🎮 Sistema", "Jogo iniciado! Boa sorte! 🚀", "sistema")
    avancar_rodada(gs)

# ─────────────────────────────────────────────
# PÁGINA E CSS
# ─────────────────────────────────────────────

st.set_page_config(page_title="DocGartic 📝", page_icon="📝", layout="wide", initial_sidebar_state="expanded")

st.markdown("""
<style>
.dica-card{background:linear-gradient(135deg,#1e2a3a,#253347);border-left:4px solid #4e9af1;border-radius:8px;padding:10px 14px;margin:5px 0;color:#e0e6f0;font-size:1rem}
.timer-box{background:#1e2a3a;border-radius:10px;padding:8px 18px;text-align:center;font-size:1.7rem;font-weight:bold;color:#4e9af1;border:2px solid #2d4a6a;margin-bottom:10px}
.timer-prep{background:linear-gradient(135deg,#1a2a1a,#1e3a1a);border-radius:10px;padding:8px 18px;text-align:center;font-size:1.7rem;font-weight:bold;color:#2ecc71;border:2px solid #2d6a2d;margin-bottom:10px}
.chat-msg-acerto{background:linear-gradient(90deg,#1a3a1a,#1e4a1e);border-left:4px solid #2ecc71;border-radius:6px;padding:7px 11px;margin:3px 0;color:#a8f0c0;font-weight:bold}
.chat-msg-sistema{background:#1a1a2e;border-left:4px solid #9b59b6;border-radius:6px;padding:7px 11px;margin:3px 0;color:#c9a0f0;font-style:italic}
.chat-msg-normal{background:#16213e;border-radius:6px;padding:7px 11px;margin:3px 0;color:#cdd6e8}
.rank-item{display:flex;justify-content:space-between;background:#1a2332;border-radius:6px;padding:7px 11px;margin:3px 0;color:#cdd6e8}
</style>
""", unsafe_allow_html=True)

# ─────────────────────────────────────────────
# SESSÃO LOCAL E MANUTENÇÃO GLOBAL
# ─────────────────────────────────────────────

if "session_id" not in st.session_state:
    st.session_state.session_id = f"user_{random.randint(100000,999999)}"
if "nome_jogador" not in st.session_state:
    st.session_state.nome_jogador = ""
if "ja_no_jogo" not in st.session_state:
    st.session_state.ja_no_jogo = False
if "gerenciador_logado" not in st.session_state:
    st.session_state.gerenciador_logado = False
if "aba_ativa" not in st.session_state:
    st.session_state.aba_ativa = "jogo"

gs   = get_global_state()
lock = get_lock()
sid  = st.session_state.session_id

with lock:
    if st.session_state.ja_no_jogo:
        ping(gs, sid)

    if gs["jogo_iniciado"]:
        # Fase de preparação: encerrar se o tempo esgotou sem o desenhista confirmar
        if gs["fase_preparacao"] and gs["hora_inicio_prep"]:
            if tempo_restante_prep(gs) == 0:
                iniciar_fase_palpites(gs, gs.get("emojis_quadro", "🤷‍♀️ Tempo esgotado!"))

        # Fase de palpites: controle de tempo e dicas
        if not gs["fase_preparacao"] and not gs["rodada_encerrada"] and gs["hora_inicio_rodada"]:
            if tempo_restante(gs) == 0:
                gs["rodada_encerrada"] = True
                doc = documento_da_rodada(gs)
                if doc:
                    add_chat(gs, "⏰ Sistema", f"Tempo esgotado! O documento era: **{doc}**", "sistema")
            else:
                elapsed = time.time() - gs["hora_inicio_rodada"]
                devidas = min(4, 1 + int(elapsed // (gs["duracao_rodada"] / 4)))
                if devidas > gs["dicas_liberadas"]:
                    gs["dicas_liberadas"] = devidas

# ─────────────────────────────────────────────
# SIDEBAR
# ─────────────────────────────────────────────

with st.sidebar:
    st.markdown("## 📝 DocGartic")
    st.caption("Jogo de Documentos Técnicos")
    st.divider()

    col_a, col_b = st.columns(2)
    with col_a:
        if st.button("🎮 Jogo", use_container_width=True, type="primary" if st.session_state.aba_ativa == "jogo" else "secondary"):
            st.session_state.aba_ativa = "jogo"
            st.rerun()
    with col_b:
        if st.button("🛠️ Gerenciar", use_container_width=True, type="primary" if st.session_state.aba_ativa == "gerenciador" else "secondary"):
            st.session_state.aba_ativa = "gerenciador"
            st.rerun()

    st.divider()

    if st.session_state.aba_ativa == "jogo":
        if not st.session_state.ja_no_jogo:
            st.markdown("### 👤 Entrar no Jogo")
            nome_input = st.text_input("Seu apelido:", max_chars=20, placeholder="Ex: Maria")
            if st.button("🚪 Entrar na Sala", use_container_width=True):
                nome_input = nome_input.strip()
                if not nome_input:
                    st.error("Digite um apelido!")
                elif nome_input in [d["nome"] for d in gs["jogadores"].values()]:
                    st.error("Apelido já em uso!")
                else:
                    with lock:
                        gs["jogadores"][sid] = {"nome": nome_input, "pontos": 0, "ultimo_ping": time.time()}
                        add_chat(gs, "🎮 Sistema", f"{nome_input} entrou na sala! 👋", "sistema")
                    st.session_state.nome_jogador = nome_input
                    st.session_state.ja_no_jogo = True
                    st.rerun()
        else:
            st.success(f"✅ **{st.session_state.nome_jogador}**")
            if st.button("🚪 Sair", use_container_width=True):
                with lock:
                    if sid in gs["jogadores"]:
                        nome = gs["jogadores"].pop(sid)["nome"]
                        add_chat(gs, "🔌 Sistema", f"{nome} saiu.", "sistema")
                st.session_state.ja_no_jogo = False
                st.session_state.nome_jogador = ""
                st.rerun()

        st.divider()
        st.markdown("### 👥 Jogadores")
        if gs["jogadores"]:
            for s, d in sorted(gs["jogadores"].items(), key=lambda x: x[1]["pontos"], reverse=True):
                icon = " 🎨" if s == gs.get("desenhista_sid") else ""
                st.markdown(f'<div class="rank-item"><span>👤 {d["nome"]}{icon}</span><span>⭐ {d["pontos"]}</span></div>', unsafe_allow_html=True)
        else:
            st.caption("Nenhum jogador ainda.")
    else:
        if not st.session_state.gerenciador_logado:
            st.markdown("### 🔐 Acesso Restrito")
            senha_input = st.text_input("Senha:", type="password", placeholder="Digite a senha")
            if st.button("🔓 Entrar", use_container_width=True):
                if senha_input == MANAGER_PASSWORD:
                    st.session_state.gerenciador_logado = True
                    st.rerun()
                else:
                    st.error("Senha incorreta!")
        else:
            st.markdown("### 🛠️ Painel do Gerenciador")
            st.success("✅ Gerenciador conectado")
            if st.button("🚪 Sair do Painel", use_container_width=True):
                st.session_state.gerenciador_logado = False
                st.session_state.aba_ativa = "jogo"
                st.rerun()

# ─────────────────────────────────────────────
# TELA PRINCIPAL
# ─────────────────────────────────────────────

st.markdown("# 📝 DocGartic")

# ═══════════════════════════════════════════════
# ABA GERENCIADOR
# ═══════════════════════════════════════════════
if st.session_state.aba_ativa == "gerenciador":
    if not st.session_state.gerenciador_logado:
        st.info("🔐 Faça login no painel do **Gerenciador** na barra lateral.")
    else:
        st.markdown("## 🛠️ Painel do Gerenciador")
        st.divider()

        col_s1, col_s2, col_s3 = st.columns(3)
        with col_s1:
            if not gs["jogo_iniciado"]:
                status_txt = "🔴 Parado"
            elif gs["fase_preparacao"]:
                status_txt = "🟡 Preparação"
            else:
                status_txt = "🟢 Em andamento"
            st.metric("Status do Jogo", status_txt)
        with col_s2:
            st.metric("Jogadores na sala", len(gs["jogadores"]))
        with col_s3:
            rodada_txt = f"{gs['rodada_atual']}/{TOTAL_RODADAS}" if gs["jogo_iniciado"] else "—"
            st.metric("Rodada atual", rodada_txt)

        st.divider()

        if not gs["jogo_iniciado"]:
            st.markdown("### 🎛️ Controles")
            col_c1, col_c2 = st.columns(2)
            with col_c1:
                if st.button("▶️ Iniciar Jogo", use_container_width=True, type="primary", disabled=len(gs["jogadores"]) < 1):
                    with lock:
                        iniciar_jogo(gs)
                    st.rerun()
            with col_c2:
                st.caption(f"{len(gs['jogadores'])} jogador(es) na sala")
            if len(gs["jogadores"]) == 0:
                st.warning("⚠️ Nenhum jogador na sala ainda.")
        else:
            doc_atual_mgr = documento_da_rodada(gs)
            st.success(f"O documento desta rodada é: **{doc_atual_mgr}**")
            
            if gs["fase_preparacao"]:
                st.info("🟡 O desenhista está escolhendo os emojis. O quadro aparecerá aqui assim que ele enviar.")
            else:
                st.markdown("### 🖼️ Quadro de Emojis Atual:")
                st.markdown(f"<div style='font-size: 40px; text-align: center; background: #1a1a2e; padding: 20px; border-radius: 10px; border: 1px solid #4e9af1;'>{gs['emojis_quadro']}</div>", unsafe_allow_html=True)
                
            st.divider()
            if st.button("🛑 Encerrar Rodada Forçadamente (Mostrar Resposta)"):
                with lock:
                    gs["rodada_encerrada"] = True
                st.rerun()
                
            if gs["rodada_encerrada"]:
                if st.button("⏭️ Ir para Próxima Rodada", type="primary"):
                    with lock:
                        avancar_rodada(gs)
                    st.rerun()

# ═══════════════════════════════════════════════
# ABA JOGO
# ═══════════════════════════════════════════════
elif st.session_state.aba_ativa == "jogo":
    
    if not st.session_state.ja_no_jogo:
        st.info("👈 Digite seu nome na barra lateral para entrar na sala e jogar.")
        
    else:
        if not gs["jogo_iniciado"]:
            st.info("⏳ Aguardando o gerenciador iniciar a partida...")
            
        else:
            # Layout principal: Esquerda = Quadro/Dicas, Direita = Chat
            col_game, col_chat = st.columns([6, 4])
            
            with col_game:
                st.markdown(f"### 🚀 Rodada {gs['rodada_atual']} / {TOTAL_RODADAS}")
                
                # --- TELA DO DESENHISTA (FASE PREPARAÇÃO) ---
                if gs["fase_preparacao"]:
                    if sid == gs["desenhista_sid"]:
                        doc_atual = documento_da_rodada(gs)
                        tempo_prep = tempo_restante_prep(gs)
                        
                        st.markdown(f"<div class='timer-prep'>⏳ Sua vez! Tempo para preparar: {tempo_prep}s</div>", unsafe_allow_html=True)
                        st.warning(f"O documento que você deve representar é: **{doc_atual}**")
                        
                        emojis_input = st.text_input("📝 Cole ou digite os emojis aqui (Ex: 📄✍️🧑‍⚖️):", key="input_des")
                        
                        if st.button("✅ Enviar Emojis e Iniciar Rodada", use_container_width=True, type="primary"):
                            with lock:
                                iniciar_fase_palpites(gs, emojis_input)
                            st.rerun()
                    else:
                        st.info("🟡 Aguardando o desenhista montar o quadro de emojis...")
                        
                # --- TELA DE TODOS (FASE PALPITES) ---
                else:
                    if not gs["rodada_encerrada"]:
                        st.markdown(f"<div class='timer-box'>⏳ Tempo: {tempo_restante(gs)}s</div>", unsafe_allow_html=True)
                        
                    st.markdown("### 🖼️ Quadro de Dicas:")
                    st.markdown(f"<div style='font-size: 50px; text-align: center; background: #1e2a3a; padding: 30px; border-radius: 12px; border: 2px solid #4e9af1; min-height: 120px;'>{gs['emojis_quadro']}</div>", unsafe_allow_html=True)
                    
                    if gs["rodada_encerrada"]:
                        st.success(f"🏆 O documento correto era: **{documento_da_rodada(gs)}**")
                        if sid == gs.get("desenhista_sid") or len(gs["jogadores"]) <= 1:
                            st.info("Aguardando o gerenciador iniciar a próxima rodada...")
            
            with col_chat:
                st.markdown("### 💬 Palpites e Chat")
                chat_container = st.container(height=400)
                
                with chat_container:
                    for msg in gs["chat"]:
                        if msg["tipo"] == "sistema":
                            st.markdown(f"<div class='chat-msg-sistema'>[{msg['hora']}] {msg['msg']}</div>", unsafe_allow_html=True)
                        elif msg["tipo"] == "acerto":
                            st.markdown(f"<div class='chat-msg-acerto'>[{msg['hora']}] {msg['msg']}</div>", unsafe_allow_html=True)
                        else:
                            st.markdown(f"<div class='chat-msg-normal'>[{msg['hora']}] <b>{msg['autor']}</b>: {msg['msg']}</div>", unsafe_allow_html=True)
                
                # Sistema de Input para Jogadores
                if not gs["fase_preparacao"] and not gs["rodada_encerrada"]:
                    if sid == gs["desenhista_sid"]:
                        st.info("🎨 Você é o desenhista. Acompanhe os palpites!")
                    elif sid in gs["acertaram"]:
                        st.success("✅ Você já acertou! Aguarde a rodada acabar.")
                        # Permite conversar sem pontuar de novo
                        chat_livre = st.chat_input("Converse com os outros (sua resposta está oculta)...")
                        if chat_livre:
                            with lock:
                                add_chat(gs, st.session_state.nome_jogador, chat_livre, "normal")
                            st.rerun()
                    else:
                        palpite = st.chat_input("Digite seu palpite aqui...")
                        if palpite:
                            palpite = palpite.strip()
                            if palpite:
                                doc_correto = documento_da_rodada(gs)
                                # Verifica acerto ignorando maiúsculas e acentos
                                if normalizar(palpite) == normalizar(doc_correto):
                                    with lock:
                                        gs["acertaram"].append(sid)
                                        pontos = max(1, 10 - len(gs["acertaram"]) * 2)
                                        gs["jogadores"][sid]["pontos"] += pontos
                                        
                                        # Dá ponto pro desenhista se alguém acerta
                                        if gs["desenhista_sid"] in gs["jogadores"]:
                                            gs["jogadores"][gs["desenhista_sid"]]["pontos"] += 1
                                            
                                        add_chat(gs, st.session_state.nome_jogador, f"{st.session_state.nome_jogador} ACERTOU! 🎉 (+{pontos} pts)", "acerto")
                                        
                                        # Encerra se todos que podiam acertar acertaram
                                        total_adivinhadores = len(gs["jogadores"]) - 1
                                        if total_adivinhadores > 0 and len(gs["acertaram"]) >= total_adivinhadores:
                                            gs["rodada_encerrada"] = True
                                    st.rerun()
                                else:
                                    with lock:
                                        add_chat(gs, st.session_state.nome_jogador, palpite, "normal")
                                    st.rerun()
