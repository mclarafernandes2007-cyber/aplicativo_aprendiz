"""
DocGartic - Jogo multiplayer estilo Gartic para Documentos Técnicos e Administrativos
======================================================================================
NOVA MECÂNICA: o jogador "desenhista" da rodada posiciona emojis num quadro branco
interativo (canvas HTML via st.components.v1.html).

Arquitetura de sincronização:
- @st.cache_resource -> dicionário único compartilhado entre TODAS as sessões.
- st.session_state   -> dados locais de cada sessão (nome, session_id).
- threading.Lock     -> escrita segura com múltiplos usuários simultâneos.
- time.sleep + rerun -> loop de auto-refresh para sincronizar clientes.
"""

import streamlit as st
import streamlit.components.v1 as components
import time
import unicodedata
import threading
import random
import json
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
        "jogadores": {},           # {sid: {nome, pontos, ultimo_ping}}
        "desenhista_sid": None,    # quem está posicionando emojis nesta rodada
        "acertaram": [],
        "chat": [],
        "emojis_quadro": [],       # [{emoji, x, y, id}]
        "jogo_iniciado": False,
        "rodada_encerrada": False,
        "hora_inicio_rodada": None,
        "duracao_rodada": 120,
    }

@st.cache_resource
def get_lock():
    return threading.Lock()

# ─────────────────────────────────────────────
# DADOS DOS DOCUMENTOS
# ─────────────────────────────────────────────

MANAGER_PASSWORD = "admin123"  # ← Altere para a senha desejada

DOCUMENTOS = {
    "Ata": {
        "descricao": "Documento que registra formalmente as ocorrências, deliberações e decisões tomadas em reuniões, assembleias ou sessões. Deve ser redigida em linguagem clara, com verbos no pretérito perfeito, e assinada pelos presentes.",
        "dicas": ["Registra decisões de reuniões","Não pode ter rasuras","Verbos no pretérito perfeito","Assinada por secretário e presidente"],
    },
    "Memorando": {
        "descricao": "Correspondência interna de uso rotineiro entre setores ou departamentos de uma mesma organização. Caracteriza-se pela linguagem objetiva e identificação do remetente pelo cargo.",
        "dicas": ["Comunicação interna entre setores","Linguagem objetiva e direta","Identifica remetente pelo cargo","Muito usado em órgãos públicos"],
    },
    "E-mail corporativo": {
        "descricao": "Mensagem eletrônica formal utilizada no ambiente profissional. Deve conter assunto claro, saudação, corpo do texto objetivo, assinatura com dados do remetente, e respeitar normas de etiqueta digital.",
        "dicas": ["Comunicação eletrônica formal","Deve ter assunto, saudação e assinatura","Evita gírias e abreviações","Pode incluir CC e CCO"],
    },
    "Recibo": {
        "descricao": "Documento que comprova o recebimento de dinheiro, bens ou serviços. Deve conter o valor por extenso, a data, a identificação de quem recebe e de quem paga, e ter validade jurídica.",
        "dicas": ["Comprova recebimento de dinheiro ou bens","Deve conter valor por extenso e data","Tem validade jurídica","Assinado por quem RECEBE"],
    },
    "Ofício": {
        "descricao": "Documento de comunicação oficial utilizado entre órgãos públicos ou entre estes e entidades privadas. Segue rigoroso padrão formal com numeração sequencial anual, vocativo e fecho padronizado.",
        "dicas": ["Comunicação oficial entre órgãos públicos","Numeração sequencial por ano","Segue padrão oficial com vocativo e fecho","Usado para comunicação EXTERNA"],
    },
    "Relatório Técnico": {
        "descricao": "Documento elaborado por profissional habilitado que descreve, analisa e apresenta conclusões sobre uma atividade, pesquisa ou inspeção. Estrutura-se em introdução, desenvolvimento e conclusão, podendo conter tabelas e referências.",
        "dicas": ["Descreve atividade ou pesquisa realizada","Estrutura: introdução, desenvolvimento, conclusão","Pode ter tabelas e referências","Emitido por profissional habilitado"],
    },
    "Procuração": {
        "descricao": "Instrumento pelo qual uma pessoa (outorgante) concede poderes a outra (outorgado) para agir em seu nome em atos jurídicos específicos. Pode ser pública (lavrada em cartório) ou particular, com prazo determinado ou indeterminado.",
        "dicas": ["Concede poderes de representação","Pode ser pública (cartório) ou particular","Especifica atos autorizados","Pode ter prazo ou ser indeterminada"],
    },
    "Contrato": {
        "descricao": "Acordo de vontades entre duas ou mais partes que cria, modifica ou extingue direitos e obrigações. Requer agente capaz, objeto lícito e forma prescrita em lei. Deve ser assinado pelas partes e por testemunhas.",
        "dicas": ["Acordo de vontades entre partes","Precisa de agente capaz e objeto lícito","Cláusulas de obrigações e penalidades","Assinado por ambas as partes e testemunhas"],
    },
    "Declaração": {
        "descricao": "Documento em que uma pessoa afirma ou confirma determinado fato, situação ou condição. Usa a fórmula 'Declaro para os devidos fins' e pode ser de residência, renda, estado civil, entre outros. Pode exigir reconhecimento de firma.",
        "dicas": ["Afirma ou confirma um fato","Usa fórmula: Declaro para os devidos fins","Pode ser de residência ou renda","Pode exigir reconhecimento de firma"],
    },
    "Requerimento": {
        "descricao": "Pedido formal dirigido a uma autoridade ou órgão público solicitando alguma providência, direito ou serviço. Estrutura-se em identificação do requerente, exposição dos fatos e pedido, encerrando com 'Nestes termos, pede deferimento'.",
        "dicas": ["Pedido formal a uma autoridade","Estrutura: identificação, fatos e pedido","Termina com: Nestes termos, pede deferimento","Usado em processos administrativos"],
    },
    "Circular": {
        "descricao": "Comunicação interna ou externa enviada simultaneamente a múltiplos destinatários, contendo o mesmo conteúdo para todos. Usada para transmitir normas, informações coletivas ou comunicar mudanças de política.",
        "dicas": ["Enviada a múltiplos destinatários","Conteúdo idêntico para todos","Transmite normas ou informações coletivas","Comum para comunicar mudanças de política"],
    },
    "Edital": {
        "descricao": "Ato público oficial que convoca interessados ou dá ciência a todos sobre determinado fato, condição ou procedimento. Amplamente utilizado em concursos públicos e licitações, deve ser publicado em veículo de ampla divulgação e definir regras e critérios claros.",
        "dicas": ["Ato público que convoca interessados","Usado em concursos e licitações","Publicado em veículo de ampla divulgação","Define regras e critérios de seleção"],
    },
}

TOTAL_RODADAS = 12

PALETA_EMOJIS = [
    "📝","📄","📃","📋","📊","📈","📉","🗂️","🗃️","📁","📂",
    "✉️","📧","📨","📩","📬","📭","📯","📢","📣","💬","🗣️","📞","☎️",
    "👤","👥","🤝","👔","👩‍💼","👨‍💼","🏛️","🏢","🏦","🏫",
    "⚖️","🔏","🔐","🔑","🖊️","✍️","📜","📑","🖋️","🔖",
    "⏰","⌛","⏳","📅","📆","🗓️","⏱️","🔔",
    "💰","💵","💳","🧾","💸","💹",
    "✅","❌","⚠️","ℹ️","🚨","🔴","🟡","🟢","🔵","⭕","❓","❗",
    "🔬","🔭","⚙️","🔧","🛠️","📐","📏","💡","🖥️","💻",
    "🎯","🏆","🥇","🌐","🔗","📌","📍","🚩",
]

# ─────────────────────────────────────────────
# UTILITÁRIOS
# ─────────────────────────────────────────────

def normalizar(t):
    nfkd = unicodedata.normalize("NFKD", t)
    return "".join(c for c in nfkd if not unicodedata.combining(c)).lower().strip()

def documento_da_rodada(gs):
    if gs["rodada_atual"] < 1 or gs["rodada_atual"] > TOTAL_RODADAS:
        return None
    return gs["documentos_sorteados"][gs["rodada_atual"] - 1] if gs["documentos_sorteados"] else None

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

def avancar_rodada(gs):
    gs["rodada_atual"] += 1
    gs["dicas_liberadas"] = 1
    gs["acertaram"] = []
    gs["rodada_encerrada"] = False
    gs["hora_inicio_rodada"] = time.time()
    gs["emojis_quadro"] = []
    if gs["rodada_atual"] > TOTAL_RODADAS:
        gs["jogo_iniciado"] = False
        add_chat(gs, "🏆 Sistema", "Jogo encerrado! Veja o ranking final.", "sistema")
    else:
        gs["desenhista_sid"] = escolher_desenhista(gs)
        nome_des = gs["jogadores"].get(gs["desenhista_sid"], {}).get("nome", "?")
        add_chat(gs, "🎮 Sistema", f"Rodada {gs['rodada_atual']}/{TOTAL_RODADAS} — {nome_des} esta dando dicas! 🎨", "sistema")

def iniciar_jogo(gs):
    docs = list(DOCUMENTOS.keys())
    random.shuffle(docs)
    gs["documentos_sorteados"] = docs
    gs["rodada_atual"] = 0
    gs["chat"] = []
    gs["acertaram"] = []
    gs["emojis_quadro"] = []
    gs["rodada_encerrada"] = False
    for s in gs["jogadores"]:
        gs["jogadores"][s]["pontos"] = 0
    gs["jogo_iniciado"] = True
    add_chat(gs, "🎮 Sistema", "Jogo iniciado! Boa sorte! 🚀", "sistema")
    avancar_rodada(gs)

# ─────────────────────────────────────────────
# PÁGINA
# ─────────────────────────────────────────────

st.set_page_config(page_title="DocGartic 📝", page_icon="📝", layout="wide", initial_sidebar_state="expanded")

st.markdown("""
<style>
.dica-card{background:linear-gradient(135deg,#1e2a3a,#253347);border-left:4px solid #4e9af1;
  border-radius:8px;padding:10px 14px;margin:5px 0;color:#e0e6f0;font-size:1rem}
.timer-box{background:#1e2a3a;border-radius:10px;padding:8px 18px;text-align:center;
  font-size:1.7rem;font-weight:bold;color:#4e9af1;border:2px solid #2d4a6a;margin-bottom:10px}
.timer-box.urgente{color:#e74c3c;border-color:#6a2d2d}
.chat-msg-acerto{background:linear-gradient(90deg,#1a3a1a,#1e4a1e);border-left:4px solid #2ecc71;
  border-radius:6px;padding:7px 11px;margin:3px 0;color:#a8f0c0;font-weight:bold}
.chat-msg-sistema{background:#1a1a2e;border-left:4px solid #9b59b6;border-radius:6px;
  padding:7px 11px;margin:3px 0;color:#c9a0f0;font-style:italic}
.chat-msg-normal{background:#16213e;border-radius:6px;padding:7px 11px;margin:3px 0;color:#cdd6e8}
.rank-item{display:flex;justify-content:space-between;background:#1a2332;border-radius:6px;
  padding:7px 11px;margin:3px 0;color:#cdd6e8}
.rodada-badge{background:linear-gradient(135deg,#2d5a8e,#1a3a6e);border-radius:20px;
  padding:5px 18px;display:inline-block;color:#a0c4f8;font-size:.9rem;font-weight:bold;margin-bottom:8px}
.des-tag{background:#2d1a4e;border-radius:8px;padding:8px 14px;color:#c9a0f0;font-weight:bold;
  margin-bottom:10px;border-left:4px solid #9b59b6}
.watch-tag{background:#1a2d4e;border-radius:8px;padding:8px 14px;color:#a0c4f8;
  margin-bottom:10px;border-left:4px solid #4e9af1}
</style>
""", unsafe_allow_html=True)

# ─────────────────────────────────────────────
# SESSÃO LOCAL
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

# ─────────────────────────────────────────────
# MANUTENÇÃO GLOBAL
# ─────────────────────────────────────────────

with lock:
    if st.session_state.ja_no_jogo:
        ping(gs, sid)
    if gs["jogo_iniciado"] and not gs["rodada_encerrada"] and gs["hora_inicio_rodada"]:
        if tempo_restante(gs) == 0:
            gs["rodada_encerrada"] = True
            doc = documento_da_rodada(gs)
            if doc:
                add_chat(gs, "⏰ Sistema", f"Tempo! O documento era: {doc}", "sistema")
        else:
            elapsed = time.time() - gs["hora_inicio_rodada"]
            devidas = min(4, 1 + int(elapsed // 25))
            if devidas > gs["dicas_liberadas"]:
                gs["dicas_liberadas"] = devidas

# ─────────────────────────────────────────────
# SIDEBAR
# ─────────────────────────────────────────────

with st.sidebar:
    st.markdown("## 📝 DocGartic")
    st.caption("Jogo de Documentos Técnicos")
    st.divider()

    # ── Navegação entre abas ──
    col_a, col_b = st.columns(2)
    with col_a:
        if st.button("🎮 Jogo", use_container_width=True,
                     type="primary" if st.session_state.aba_ativa == "jogo" else "secondary"):
            st.session_state.aba_ativa = "jogo"
            st.rerun()
    with col_b:
        if st.button("🛠️ Gerenciar", use_container_width=True,
                     type="primary" if st.session_state.aba_ativa == "gerenciador" else "secondary"):
            st.session_state.aba_ativa = "gerenciador"
            st.rerun()

    st.divider()

    if st.session_state.aba_ativa == "jogo":
        # ── Área do jogador ──
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

        st.divider()
        st.caption("🔄 Sync a cada 3s")

    else:
        # ── Área do gerenciador ──
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
            st.divider()
            st.caption("Os controles do jogo estão na tela principal →")

# ─────────────────────────────────────────────
# QUADRO DE EMOJIS — componente HTML
# ─────────────────────────────────────────────

def build_canvas_html(emojis_atuais, pode_editar, paleta):
    emojis_json = json.dumps(emojis_atuais, ensure_ascii=False)
    paleta_json = json.dumps(paleta, ensure_ascii=False)
    edit_js = "true" if pode_editar else "false"

    paleta_bloco = ""
    if pode_editar:
        paleta_bloco = """
<div style="margin-top:12px">
  <div style="color:#aaa;font-size:0.82rem;margin-bottom:6px">
    1. Clique em um emoji abaixo &nbsp;➜&nbsp; 2. Clique no quadro para posicionar &nbsp;|&nbsp;
    Arraste para reposicionar &nbsp;|&nbsp; Duplo clique para remover
  </div>
  <div id="palette" style="display:flex;flex-wrap:wrap;gap:4px;max-height:130px;overflow-y:auto;
    background:#111;padding:8px 10px;border-radius:10px;border:1px solid #333"></div>
  <div style="margin-top:8px;display:flex;gap:8px;align-items:center;flex-wrap:wrap">
    <button onclick="clearBoard()" style="padding:5px 14px;border-radius:6px;border:1px solid #444;
      background:#1a1a1a;color:#e0e0e0;cursor:pointer;font-size:0.9rem">🗑️ Limpar tudo</button>
    <span id="sel-info" style="color:#aaa;font-size:0.82rem">Nenhum emoji selecionado</span>
  </div>
</div>"""

    return f"""
<div style="font-family:sans-serif">

<div id="board-wrap" style="position:relative;width:100%;padding-bottom:55%;
  border:2px solid #334;border-radius:12px;background:#f8f8f8;overflow:hidden;
  cursor:{'crosshair' if pode_editar else 'default'}">
  <div id="board" style="position:absolute;inset:0"></div>
  <div id="empty-hint" style="position:absolute;inset:0;display:flex;align-items:center;
    justify-content:center;pointer-events:none;color:#bbb;font-size:1rem">
    {'Clique na paleta e depois no quadro para adicionar emojis' if pode_editar else 'Aguardando o desenhista posicionar emojis...'}
  </div>
</div>

{paleta_bloco}

<script>
const CAN_EDIT = {edit_js};
const PALETA   = {paleta_json};
let emojis     = {emojis_json};
let selected   = null;
let dragEl     = null, dragId = null, offX = 0, offY = 0;
let nextId     = (emojis.length ? Math.max(...emojis.map(e=>e.id))+1 : 1);

const board   = document.getElementById('board');
const wrap    = document.getElementById('board-wrap');
const hint    = document.getElementById('empty-hint');
const selInfo = document.getElementById('sel-info');

function updateHint() {{
  hint.style.display = emojis.length ? 'none' : 'flex';
}}

function sendState() {{
  window.parent.postMessage({{type:'streamlit:setComponentValue', value: JSON.stringify(emojis)}}, '*');
}}

function pct(el, axis) {{
  return parseFloat(el.style[axis === 'x' ? 'left' : 'top']);
}}

function makeEl(item) {{
  const el = document.createElement('div');
  el.dataset.id = item.id;
  el.textContent = item.emoji;
  el.style.cssText = `position:absolute;left:${{item.x}}%;top:${{item.y}}%;
    transform:translate(-50%,-50%);font-size:2.4rem;line-height:1;
    user-select:none;cursor:${{CAN_EDIT?'grab':'default'}};z-index:10;
    filter:drop-shadow(0 1px 3px rgba(0,0,0,.25));transition:filter .1s`;
  if (CAN_EDIT) {{
    el.addEventListener('mousedown',  onDragStart);
    el.addEventListener('touchstart', onTouchStart, {{passive:false}});
    el.addEventListener('dblclick', () => removeEmoji(item.id));
    el.title = 'Arraste para mover · Duplo clique para remover';
  }}
  return el;
}}

function renderAll() {{
  board.querySelectorAll('[data-id]').forEach(e => e.remove());
  emojis.forEach(item => board.appendChild(makeEl(item)));
  updateHint();
}}

/* ── Adicionar ao clicar no quadro ── */
wrap.addEventListener('click', function(e) {{
  if (!CAN_EDIT || !selected) return;
  if (e.target !== wrap && e.target !== board && !e.target.classList.contains('board-bg')) return;
  const r = wrap.getBoundingClientRect();
  const x = +((e.clientX - r.left) / r.width  * 100).toFixed(1);
  const y = +((e.clientY - r.top)  / r.height * 100).toFixed(1);
  const id = nextId++;
  emojis.push({{emoji: selected, x, y, id}});
  renderAll();
}});

/* ── Drag mouse ── */
function onDragStart(e) {{
  e.stopPropagation();
  dragEl = e.currentTarget;
  dragId = +dragEl.dataset.id;
  dragEl.style.cursor = 'grabbing';
  dragEl.style.zIndex = '999';
  const r = wrap.getBoundingClientRect();
  const item = emojis.find(i => i.id === dragId);
  offX = e.clientX - r.left - (item.x / 100) * r.width;
  offY = e.clientY - r.top  - (item.y / 100) * r.height;
}}
function onTouchStart(e) {{
  e.preventDefault();
  const t = e.touches[0];
  const fake = {{stopPropagation:()=>{{}}, currentTarget:e.currentTarget, clientX:t.clientX, clientY:t.clientY}};
  onDragStart(fake);
}}

function onMove(cx, cy) {{
  if (!dragEl) return;
  const r = wrap.getBoundingClientRect();
  const x = Math.min(97, Math.max(3, (cx - r.left - offX) / r.width  * 100));
  const y = Math.min(93, Math.max(7, (cy - r.top  - offY) / r.height * 100));
  dragEl.style.left = x + '%';
  dragEl.style.top  = y + '%';
}}
document.addEventListener('mousemove', e => onMove(e.clientX, e.clientY));
document.addEventListener('touchmove', e => {{ onMove(e.touches[0].clientX, e.touches[0].clientY); }}, {{passive:false}});

function onEnd() {{
  if (!dragEl) return;
  const item = emojis.find(i => i.id === dragId);
  if (item) {{ item.x = parseFloat(dragEl.style.left); item.y = parseFloat(dragEl.style.top); }}
  dragEl.style.cursor = 'grab';
  dragEl.style.zIndex = '10';
  dragEl = null; dragId = null;
}}
document.addEventListener('mouseup',  onEnd);
document.addEventListener('touchend', onEnd);

function removeEmoji(id) {{
  emojis = emojis.filter(i => i.id !== id);
  renderAll();
}}

function clearBoard() {{
  emojis = [];
  selected = null;
  if (selInfo) selInfo.textContent = 'Nenhum emoji selecionado';
  document.querySelectorAll('.pal-btn').forEach(b => b.style.outline = 'none');
  renderAll();
}}

/* ── Paleta ── */
if (CAN_EDIT) {{
  const palette = document.getElementById('palette');
  PALETA.forEach(em => {{
    const btn = document.createElement('button');
    btn.className = 'pal-btn';
    btn.textContent = em;
    btn.title = 'Clique para selecionar';
    btn.style.cssText = 'font-size:1.6rem;padding:2px 5px;border-radius:6px;border:1px solid #555;background:#1e1e1e;cursor:pointer;transition:outline .1s';
    btn.addEventListener('click', () => {{
      selected = (selected === em) ? null : em;
      document.querySelectorAll('.pal-btn').forEach(b => b.style.outline = 'none');
      if (selected) {{
        btn.style.outline = '2px solid #ffd700';
        if (selInfo) selInfo.textContent = 'Selecionado: ' + selected + ' — clique no quadro para posicionar';
      }} else {{
        if (selInfo) selInfo.textContent = 'Nenhum emoji selecionado';
      }}
    }});
    palette.appendChild(btn);
  }});
}}

renderAll();
</script>
</div>
"""

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

        # Status atual
        col_s1, col_s2, col_s3 = st.columns(3)
        with col_s1:
            status_txt = "🟢 Em andamento" if gs["jogo_iniciado"] else "🔴 Parado"
            st.metric("Status do Jogo", status_txt)
        with col_s2:
            st.metric("Jogadores na sala", len(gs["jogadores"]))
        with col_s3:
            rodada_txt = f"{gs['rodada_atual']}/{TOTAL_RODADAS}" if gs["jogo_iniciado"] else "—"
            st.metric("Rodada atual", rodada_txt)

        st.divider()
        st.markdown("### 🎛️ Controles")

        if not gs["jogo_iniciado"]:
            if len(gs["jogadores"]) == 0:
                st.warning("⚠️ Nenhum jogador na sala ainda.")
            col_c1, col_c2 = st.columns(2)
            with col_c1:
                if st.button("▶️ Iniciar Jogo", use_container_width=True,
                             type="primary", disabled=len(gs["jogadores"]) < 1):
                    with lock:
                        iniciar_jogo(gs)
                    st.rerun()
            with col_c2:
                st.caption(f"{len(gs['jogadores'])} jogador(es) na sala")
        else:
            doc_atual_mgr = documento_da_rodada(gs)
            if doc_atual_mgr:
                info_mgr = DOCUMENTOS.get(doc_atual_mgr, {})
                descricao_mgr = info_mgr.get("descricao", "")

                # Documento + descrição em destaque
                st.markdown(
                    f'<div style="background:linear-gradient(135deg,#1a2a1a,#1e3a1e);border-left:4px solid #2ecc71;'
                    f'border-radius:10px;padding:14px 18px;margin-bottom:14px">'
                    f'<div style="color:#a8f0c0;font-size:0.85rem;font-weight:bold;margin-bottom:4px">📄 DOCUMENTO DESTA RODADA</div>'
                    f'<div style="color:#ffffff;font-size:1.3rem;font-weight:bold;margin-bottom:8px">{doc_atual_mgr}</div>'
                    f'<div style="color:#cde8cd;font-size:0.95rem;line-height:1.5">{descricao_mgr}</div>'
                    f'</div>',
                    unsafe_allow_html=True,
                )

            col_c1, col_c2, col_c3 = st.columns(3)
            with col_c1:
                if not gs["rodada_encerrada"]:
                    if st.button("⏩ Encerrar Rodada", use_container_width=True, type="secondary"):
                        with lock:
                            gs["rodada_encerrada"] = True
                            doc = documento_da_rodada(gs)
                            if doc:
                                add_chat(gs, "⏰ Sistema", f"Encerrado pelo gerenciador! Era: {doc}", "sistema")
                        st.rerun()
                else:
                    st.success("✅ Rodada encerrada")
            with col_c2:
                if gs["rodada_encerrada"] and gs["rodada_atual"] <= TOTAL_RODADAS:
                    if st.button("⏭️ Próxima Rodada", use_container_width=True, type="primary"):
                        with lock:
                            avancar_rodada(gs)
                        st.rerun()
            with col_c3:
                if st.button("🔄 Reiniciar Jogo", use_container_width=True, type="secondary"):
                    with lock:
                        iniciar_jogo(gs)
                    st.rerun()

        st.divider()
        st.markdown("### 💬 Chat ao Vivo")
        chat_html_mgr = ""
        for m in gs["chat"][-50:]:
            h, a, txt, t = m.get("hora",""), m["autor"], m["msg"], m["tipo"]
            if t == "acerto":
                chat_html_mgr += f'<div class="chat-msg-acerto"><span style="opacity:.5">{h}</span> <b>{a}</b>: {txt}</div>'
            elif t == "sistema":
                chat_html_mgr += f'<div class="chat-msg-sistema"><span style="opacity:.5">{h}</span> {txt}</div>'
            else:
                chat_html_mgr += f'<div class="chat-msg-normal"><span style="opacity:.5">{h}</span> <b>{a}</b>: {txt}</div>'
        st.markdown(
            f'<div style="height:300px;overflow-y:auto;padding:8px;background:#0e1117;border-radius:10px;border:1px solid #2d3a4f">{chat_html_mgr}</div>',
            unsafe_allow_html=True,
        )
        # Auto-refresh no painel do gerenciador
        time.sleep(3)
        st.rerun()

# ═══════════════════════════════════════════════
# ABA JOGO
# ═══════════════════════════════════════════════
elif st.session_state.aba_ativa == "jogo":
    if not st.session_state.ja_no_jogo:
        st.info("👈 Digite seu apelido na barra lateral e clique em **Entrar na Sala**!")
        st.markdown("""
        ### 🎯 Como Jogar
        - Cada rodada, um jogador vira o **desenhista**: ele vê o documento e posiciona emojis no quadro para dar pistas.
        - Os outros tentam **adivinhar** qual documento é pelo quadro de emojis + dicas textuais.
        - **10 pts** para o primeiro a acertar, **5 pts** para os demais.
        - Dicas textuais são reveladas automaticamente a cada 25 segundos.
        - São **12 rodadas** — uma por tipo de documento!
        """)

    elif not gs["jogo_iniciado"] and gs["rodada_atual"] == 0:
        st.markdown("### 🏠 Sala de Espera")
        st.info(f"**{len(gs['jogadores'])} jogador(es)** na sala. Aguarde o Gerenciador iniciar o jogo!")

    elif not gs["jogo_iniciado"] and gs["rodada_atual"] > TOTAL_RODADAS:
        st.markdown("## 🏆 Jogo Encerrado — Ranking Final")
        medals = ["🥇","🥈","🥉"]
        for i,(_, d) in enumerate(sorted(gs["jogadores"].items(), key=lambda x:x[1]["pontos"], reverse=True)):
            m = medals[i] if i < 3 else f"#{i+1}"
            st.markdown(f'<div class="rank-item" style="font-size:1.2rem;padding:12px"><span>{m} {d["nome"]}</span><span>⭐ {d["pontos"]} pts</span></div>', unsafe_allow_html=True)

    else:
        doc_atual       = documento_da_rodada(gs)
        info_doc        = DOCUMENTOS.get(doc_atual, {})
        eh_desenhista   = (sid == gs["desenhista_sid"])
        nome_desenhista = gs["jogadores"].get(gs["desenhista_sid"], {}).get("nome", "?")

        col_jogo, col_chat = st.columns([3, 2], gap="large")

        with col_jogo:
            st.markdown(f'<div class="rodada-badge">🎮 Rodada {gs["rodada_atual"]}/{TOTAL_RODADAS}</div>', unsafe_allow_html=True)

            if eh_desenhista:
                st.markdown(f'<div class="des-tag">🎨 Você é o desenhista!  &nbsp;|&nbsp; Documento: <b>{doc_atual}</b><br><small>Posicione emojis no quadro para dar pistas — sem revelar o nome!</small></div>', unsafe_allow_html=True)
            else:
                st.markdown(f'<div class="watch-tag">🖼️ <b>{nome_desenhista}</b> está posicionando emojis como dicas...</div>', unsafe_allow_html=True)

            # ── Descrição do documento (exibida ao encerrar a rodada) ──
            if gs["rodada_encerrada"] and doc_atual:
                descricao_doc = info_doc.get("descricao", "")
                if descricao_doc:
                    st.markdown(
                        f'<div class="dica-card" style="border-left-color:#f39c12;background:linear-gradient(135deg,#2a1e0a,#3a2a0a);margin-bottom:10px">'
                        f'<b>📖 Sobre este documento:</b><br>{descricao_doc}</div>',
                        unsafe_allow_html=True,
                    )

            # Cronômetro
            restante = tempo_restante(gs)
            tc = "timer-box urgente" if restante <= 15 else "timer-box"
            mins, secs = divmod(restante, 60)
            st.markdown(f'<div class="{tc}">⏱️ {mins:02d}:{secs:02d}</div>', unsafe_allow_html=True)

            # ── QUADRO DE EMOJIS ──
            # Para espectadores: o hash dos emojis é embutido como comentário no HTML.
            # Quando o quadro muda, o HTML muda → Streamlit recria o iframe automaticamente.
            canvas_html = build_canvas_html(
                emojis_atuais=gs["emojis_quadro"],
                pode_editar=eh_desenhista and not gs["rodada_encerrada"],
                paleta=PALETA_EMOJIS,
            )
            if not eh_desenhista:
                emojis_hash = hash(json.dumps(gs["emojis_quadro"], sort_keys=True))
                canvas_html = f"<!-- h:{emojis_hash} -->\n" + canvas_html
            altura_canvas = 620 if (eh_desenhista and not gs["rodada_encerrada"]) else 380
            resultado = components.html(canvas_html, height=altura_canvas, scrolling=False)

            # Salva o estado local do canvas a cada rerun (para não perder posições)
            if eh_desenhista and resultado is not None:
                try:
                    parsed = json.loads(resultado) if isinstance(resultado, str) else resultado
                    if isinstance(parsed, list):
                        st.session_state["canvas_pendente"] = parsed
                except Exception:
                    pass

            # Botão Streamlit de envio — força rerun e salva no estado global
            if eh_desenhista and not gs["rodada_encerrada"]:
                if st.button("📤 Enviar quadro para todos", use_container_width=True, type="primary"):
                    pendente = st.session_state.get("canvas_pendente")
                    if pendente is not None:
                        with lock:
                            gs["emojis_quadro"] = pendente
                    st.rerun()

            # Dicas textuais
            st.markdown(f"**💡 Dicas textuais: {gs['dicas_liberadas']}/4**")
            dicas = info_doc.get("dicas", [])
            for i, dica in enumerate(dicas):
                if i < gs["dicas_liberadas"]:
                    st.markdown(f'<div class="dica-card">📌 Dica {i+1}: {dica}</div>', unsafe_allow_html=True)
                else:
                    st.markdown(f'<div class="dica-card" style="opacity:.2;filter:blur(3px)">📌 Dica {i+1}: ???</div>', unsafe_allow_html=True)

            if gs["rodada_encerrada"]:
                st.success(f"📄 O documento era: **{doc_atual}**")

            # Campo de palpite (apenas para quem NÃO é desenhista)
            st.markdown("---")
            if not eh_desenhista and not gs["rodada_encerrada"]:
                if sid in gs["acertaram"]:
                    st.success("✅ Você acertou! Aguarde os outros jogadores.")
                else:
                    with st.form("form_palpite", clear_on_submit=True):
                        palpite = st.text_input("🎯 Seu palpite:", placeholder="Nome do documento...", max_chars=50, label_visibility="collapsed")
                        enviado = st.form_submit_button("📨 Enviar Palpite", use_container_width=True)
                    if enviado and palpite.strip():
                        nome_jog = st.session_state.nome_jogador
                        with lock:
                            if normalizar(palpite) == normalizar(doc_atual):
                                pts = 10 if not gs["acertaram"] else 5
                                gs["jogadores"][sid]["pontos"] += pts
                                gs["acertaram"].append(sid)
                                add_chat(gs, nome_jog, f"🎉 ACERTOU e ganhou {pts} pts!", "acerto")
                            else:
                                add_chat(gs, nome_jog, palpite, "normal")
                        st.rerun()
            elif gs["rodada_encerrada"]:
                st.info("⏳ Rodada encerrada. Aguarde o Gerenciador avançar para a próxima rodada.")
            elif eh_desenhista:
                st.info("🎨 Você é o desenhista — posicione os emojis no quadro acima!")

        # ── CHAT + PLACAR ──
        with col_chat:
            st.markdown("### 💬 Chat da Rodada")
            chat_html = ""
            for m in gs["chat"][-35:]:
                h, a, txt, t = m.get("hora",""), m["autor"], m["msg"], m["tipo"]
                if t == "acerto":
                    chat_html += f'<div class="chat-msg-acerto"><span style="opacity:.5">{h}</span> <b>{a}</b>: {txt}</div>'
                elif t == "sistema":
                    chat_html += f'<div class="chat-msg-sistema"><span style="opacity:.5">{h}</span> {txt}</div>'
                else:
                    chat_html += f'<div class="chat-msg-normal"><span style="opacity:.5">{h}</span> <b>{a}</b>: {txt}</div>'
            st.markdown(
                f'<div style="height:380px;overflow-y:auto;padding:8px;background:#0e1117;border-radius:10px;border:1px solid #2d3a4f">{chat_html}</div>',
                unsafe_allow_html=True,
            )

            st.markdown("### 📊 Placar")
            medals = ["🥇","🥈","🥉"]
            for i,(s, d) in enumerate(sorted(gs["jogadores"].items(), key=lambda x:x[1]["pontos"], reverse=True)[:6]):
                m = medals[i] if i < 3 else f"#{i+1}"
                icon = " 🎨" if s == gs["desenhista_sid"] else ""
                st.markdown(f'<div class="rank-item"><span>{m} {d["nome"]}{icon}</span><span>⭐ {d["pontos"]}</span></div>', unsafe_allow_html=True)

# ─────────────────────────────────────────────
# AUTO-REFRESH
# ─────────────────────────────────────────────
if st.session_state.aba_ativa == "jogo" and st.session_state.ja_no_jogo:
    if gs["jogo_iniciado"]:
        intervalo = 2 if not gs["rodada_encerrada"] else 4
        time.sleep(intervalo)
        st.rerun()
