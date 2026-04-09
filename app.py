"""
Streamlit UI for the Teaching Agent.

Run:
    streamlit run app.py
"""

from __future__ import annotations

import os
from pathlib import Path

import streamlit as st

from providers import get_provider, PROVIDERS, ENV_KEYS
from agent import TeachingAgent

# ---------------------------------------------------------------------------
# Page config
# ---------------------------------------------------------------------------

st.set_page_config(
    page_title="Teaching Agent",
    page_icon="🎓",
    layout="centered",
    initial_sidebar_state="expanded",
)

# ---------------------------------------------------------------------------
# Custom CSS
# ---------------------------------------------------------------------------

st.markdown("""
<style>
    /* Clean, modern feel */
    .block-container { max-width: 820px; padding-top: 2rem; }

    /* Sidebar styling */
    [data-testid="stSidebar"] {
        background: linear-gradient(180deg, #1a1a2e 0%, #16213e 100%);
    }
    [data-testid="stSidebar"] * {
        color: #e0e0e0 !important;
    }
    [data-testid="stSidebar"] .stSelectbox label,
    [data-testid="stSidebar"] .stRadio label {
        font-weight: 600;
        font-size: 0.85rem;
        text-transform: uppercase;
        letter-spacing: 0.05em;
    }

    /* Header area */
    .app-header {
        text-align: center;
        padding: 1rem 0 0.5rem;
    }
    .app-header h1 {
        font-size: 1.8rem;
        font-weight: 700;
        margin-bottom: 0.2rem;
    }
    .app-header p {
        color: #888;
        font-size: 0.95rem;
        margin-top: 0;
    }

    /* Theory badge */
    .theory-badge {
        display: inline-block;
        background: linear-gradient(135deg, #667eea, #764ba2);
        color: white !important;
        padding: 0.3rem 1rem;
        border-radius: 2rem;
        font-size: 0.85rem;
        font-weight: 600;
        letter-spacing: 0.03em;
        margin-bottom: 1rem;
    }

    /* Chat messages */
    [data-testid="stChatMessage"] {
        border-radius: 12px;
        margin-bottom: 0.5rem;
    }

    /* Status bar */
    .status-bar {
        display: flex;
        justify-content: space-between;
        align-items: center;
        padding: 0.5rem 1rem;
        background: #f8f9fa;
        border-radius: 8px;
        margin-bottom: 1rem;
        font-size: 0.8rem;
        color: #666;
    }
    .status-dot {
        display: inline-block;
        width: 8px;
        height: 8px;
        border-radius: 50%;
        background: #22c55e;
        margin-right: 6px;
        vertical-align: middle;
    }
</style>
""", unsafe_allow_html=True)

# ---------------------------------------------------------------------------
# Discover available prompts
# ---------------------------------------------------------------------------

PROMPTS_DIR = Path("prompts")


def discover_prompts() -> dict[str, Path]:
    """Find all system_prompt.md files under prompts/."""
    prompts = {}
    if PROMPTS_DIR.is_dir():
        for p in sorted(PROMPTS_DIR.rglob("system_prompt.md")):
            theory_name = p.parent.name.replace("_", " ").title()
            prompts[theory_name] = p
    return prompts


# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------

with st.sidebar:
    st.markdown("## 🎓 Teaching Agent")
    st.markdown("---")

    # Discover prompts
    available_prompts = discover_prompts()

    if not available_prompts:
        st.error(
            "No prompts found. Run `script.py` first to generate prompts from your corpus."
        )
        st.stop()

    # Theory selector
    st.markdown("#### Pedagogical Theory")
    selected_theory = st.selectbox(
        "Theory",
        options=list(available_prompts.keys()),
        label_visibility="collapsed",
    )

    st.markdown("---")

    # Provider selector
    st.markdown("#### LLM Provider")

    available_providers = []
    for name, env_var in ENV_KEYS.items():
        if os.environ.get(env_var):
            available_providers.append(name)

    if not available_providers:
        st.error("No API keys found in .env")
        st.stop()

    selected_provider = st.radio(
        "Provider",
        options=available_providers,
        format_func=lambda x: {"claude": "Anthropic Claude", "openai": "OpenAI GPT"}[x],
        label_visibility="collapsed",
    )

    # Model override
    default_models = {"claude": "claude-sonnet-4-20250514", "openai": "gpt-4.1"}
    model_override = st.text_input(
        "Model override",
        placeholder=default_models[selected_provider],
        help="Leave blank for default model",
    )

    st.markdown("---")

    # New conversation button
    if st.button("🔄  New conversation", use_container_width=True):
        st.session_state.pop("messages", None)
        st.session_state.pop("agent_key", None)
        st.rerun()

    # Info
    st.markdown("---")
    msg_count = len(st.session_state.get("messages", []))
    st.caption(f"Messages: {msg_count}  ·  Theory: {selected_theory}")

# ---------------------------------------------------------------------------
# Build / cache agent
# ---------------------------------------------------------------------------

prompt_path = available_prompts[selected_theory]
model = model_override.strip() or None
agent_key = f"{selected_theory}|{selected_provider}|{model}"

# Reset agent if config changed
if st.session_state.get("agent_key") != agent_key:
    st.session_state["agent_key"] = agent_key
    st.session_state["messages"] = []
    system_prompt = prompt_path.read_text(encoding="utf-8")
    provider = get_provider(selected_provider, model)
    st.session_state["agent"] = TeachingAgent(system_prompt, provider)

agent: TeachingAgent = st.session_state["agent"]

# ---------------------------------------------------------------------------
# Header
# ---------------------------------------------------------------------------

st.markdown(f"""
<div class="app-header">
    <h1>🎓 Teaching Agent</h1>
    <p>AI tutor constrained by pedagogical theory</p>
    <span class="theory-badge">{selected_theory}</span>
</div>
""", unsafe_allow_html=True)

# Status bar
provider_label = {"claude": "Claude", "openai": "GPT"}[selected_provider]
model_label = model or default_models[selected_provider]
st.markdown(f"""
<div class="status-bar">
    <span><span class="status-dot"></span> Active</span>
    <span>{provider_label} · {model_label}</span>
</div>
""", unsafe_allow_html=True)

# ---------------------------------------------------------------------------
# Chat history
# ---------------------------------------------------------------------------

if "messages" not in st.session_state:
    st.session_state["messages"] = []

# Display chat history
for msg in st.session_state["messages"]:
    avatar = "🎓" if msg["role"] == "assistant" else "👤"
    with st.chat_message(msg["role"], avatar=avatar):
        st.markdown(msg["content"])

# ---------------------------------------------------------------------------
# Chat input
# ---------------------------------------------------------------------------

if prompt := st.chat_input("Ask a question or describe what you're learning..."):
    # Show user message
    with st.chat_message("user", avatar="👤"):
        st.markdown(prompt)
    st.session_state["messages"].append({"role": "user", "content": prompt})

    # Stream assistant response
    with st.chat_message("assistant", avatar="🎓"):
        response = st.write_stream(agent.stream(prompt))

    st.session_state["messages"].append({"role": "assistant", "content": response})
