"""Web page for the regulatory assistant.

Run it with:  uv run streamlit run src/regrag/ui/app.py

Streamlit re-runs this whole file on every click, so anything slow to build (database
connection, Bedrock clients) is cached once per search setup with st.cache_resource.
"""

import threading

import streamlit as st

from regrag.query.pipeline import DISCLAIMER, answer_question, build_pipeline
from regrag.types import PipelineConfig
from regrag.ui.view import (
    CONFIG_LABELS,
    EXAMPLE_QUESTIONS,
    abstain_explanation,
    source_cards,
    stats,
)


@st.cache_resource
def get_parts(config_name: str):
    return build_pipeline(PipelineConfig(name=config_name))


@st.cache_resource
def question_lock() -> threading.Lock:
    # One question at a time: the parts share one database connection, and the
    # account's rerank quota (2 per minute) would only throttle parallel questions.
    return threading.Lock()


def ask(question: str, config_name: str):
    config = PipelineConfig(name=config_name)
    with question_lock():
        return answer_question(question, config=config, parts=get_parts(config_name))


def show_result(result) -> None:
    if result.abstained:
        st.warning("**No answer given.** " + abstain_explanation(result.abstain_reason))
    st.markdown(result.answer)

    for note in result.supersession_notes:
        st.info("**Rule changed:** " + note)

    cards = source_cards(result)
    if cards:
        st.subheader("Sources")
        for card in cards:
            with st.container(border=True):
                badge = " :orange-badge[superseded]" if card.outdated else ""
                st.markdown(f"**[{card.marker}] {card.title}**{badge}")
                st.caption(card.location)
                if card.url:
                    st.markdown(f"[Open the official document]({card.url})")

    pairs = stats(result)
    for col, (label, value) in zip(st.columns(len(pairs)), pairs, strict=True):
        col.metric(label, value)


st.set_page_config(page_title="Regulatory RAG: RBI + GST", page_icon="📘", layout="centered")
st.title("RBI + GST regulatory assistant")
st.caption(
    "Answers from 25 RBI Master Directions and 40 CBIC GST circulars, with the section and "
    "page of every source. It says so when a rule has changed, and refuses when the "
    "documents do not support an answer."
)

with st.sidebar:
    config_name = st.selectbox(
        "Search setup",
        options=list(CONFIG_LABELS),
        format_func=CONFIG_LABELS.get,
        help="The four setups compared in the evaluation. Rerank is the most accurate, but "
        "this account allows only 2 rerank calls a minute, so it can take ~30 s.",
    )

# Examples live on the main page (not the sidebar), which narrow screens collapse.
# They must run before the text box is drawn: Streamlit only lets code set a widget's
# value before that widget appears in the run.
with st.expander("Try an example"):
    for example in EXAMPLE_QUESTIONS:
        if st.button(example, width="stretch"):
            st.session_state.question = example

with st.form("ask"):
    question = st.text_area(
        "Your question", key="question", height=90, placeholder=EXAMPLE_QUESTIONS[0]
    )
    submitted = st.form_submit_button("Ask", type="primary")

if submitted and question.strip():
    with st.spinner("Searching the documents and writing a cited answer..."):
        try:
            st.session_state.result = ask(question.strip(), config_name)
        except Exception as error:  # show the problem on the page instead of a stack trace
            st.session_state.pop("result", None)
            st.error(f"Something went wrong: {error}")

if "result" in st.session_state:
    show_result(st.session_state.result)

st.divider()
st.caption(DISCLAIMER)
