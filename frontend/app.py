"""
Streamlit frontend for the University Student Support Assistant.

Provides a simple chat-style interface that:
  - sends student questions to the FastAPI backend's /ask endpoint
  - shows a loading spinner while waiting for a response
  - handles every error case required by the assignment (backend down,
    model down, empty question, slow response, unexpected errors)
  - lets the student rate each answer Good / Average / Poor, sent to the
    backend's /feedback endpoint (bonus Task 10, Option E)

Run with:
    streamlit run frontend/app.py
"""

import os
from typing import Optional

import requests
import streamlit as st
from dotenv import load_dotenv

load_dotenv()

BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8000")
FRONTEND_REQUEST_TIMEOUT = 310  # slightly above the backend's own LLM timeout

PAGE_TITLE = "University Student Support Assistant"
SUPPORTED_TOPICS = [
    "Course registration",
    "Examination rules",
    "Library services",
    "ICT support",
    "Hostel application",
    "Fee payment",
    "Academic calendar",
    "Student conduct",
]


def init_session_state() -> None:
    """Initialize the chat history in Streamlit's session state, once."""
    if "history" not in st.session_state:
        # Each entry: {"question": str, "answer": str, "rating": Optional[str]}
        st.session_state.history = []
    if "selected_topic" not in st.session_state:
        st.session_state.selected_topic = None


def call_ask_endpoint(question: str) -> tuple[Optional[dict], Optional[str]]:
    """Call the backend's /ask endpoint.

    Returns:
        (data, error_message) - exactly one of the two will be non-None.
    """
    try:
        response = requests.post(
            f"{BACKEND_URL}/ask",
            json={"question": question},
            timeout=FRONTEND_REQUEST_TIMEOUT,
        )
    except requests.exceptions.ConnectionError:
        return None, (
            "**Connection error:** Could not reach the backend API at "
            f"`{BACKEND_URL}`. Is the FastAPI server running?"
        )
    except requests.exceptions.Timeout:
        return None, "**Timeout:** The backend took too long to respond. Please try again."

    if response.status_code == 200:
        return response.json(), None

    # Map known backend error shapes to friendly messages.
    try:
        body = response.json()
        detail = body.get("detail", "An unknown error occurred.")
    except ValueError:
        detail = "An unknown error occurred."

    status_messages = {
        422: f"**Invalid question:** {detail}",
        502: f"**Model error:** {detail}",
        503: f"**Model unavailable:** {detail}",
        504: f"**Model timeout:** {detail}",
        500: f"**Server error:** {detail}",
    }
    return None, status_messages.get(response.status_code, f"**Error {response.status_code}:** {detail}")


def send_feedback(question: str, answer: str, rating: str) -> bool:
    """Send a rating to the backend's /feedback endpoint. Returns success flag."""
    try:
        response = requests.post(
            f"{BACKEND_URL}/feedback",
            json={"question": question, "answer": answer, "rating": rating},
            timeout=10,
        )
        return response.status_code == 200
    except requests.exceptions.RequestException:
        return False


def render_sidebar() -> None:
    """Render the sidebar with scope info and backend connection status."""
    with st.sidebar:
        st.header("About this assistant")
        st.write("I can help with:")
        
        # Display topics in responsive columns
        cols = st.columns(2)
        for idx, topic in enumerate(SUPPORTED_TOPICS):
            with cols[idx % 2]:
                if st.button(topic, use_container_width=True, key=f"topic-{topic}"):
                    st.session_state.selected_topic = topic
                    st.rerun()

        st.divider()
        st.subheader("Backend status")
        try:
            resp = requests.get(f"{BACKEND_URL}/health", timeout=5)
            if resp.status_code == 200:
                data = resp.json()
                if data.get("ollama_reachable"):
                    st.success(f"API up · Model `{data.get('model')}` reachable")
                else:
                    st.warning(f"API up · Model `{data.get('model')}` NOT reachable")
            else:
                st.error("API reachable but reported an error.")
        except requests.exceptions.RequestException:
            st.error("Backend API is not reachable.")


def render_history() -> None:
    """Render the conversation history, including feedback buttons."""
    for index, entry in enumerate(st.session_state.history):
        with st.chat_message("user"):
            st.write(entry["question"])
        with st.chat_message("assistant"):
            st.write(entry["answer"])

            if entry["rating"] is None:
                cols = st.columns(3)
                labels = ["Good", "Average", "Poor"]
                for col, label in zip(cols, labels):
                    if col.button(label, key=f"rate-{index}-{label}"):
                        success = send_feedback(entry["question"], entry["answer"], label)
                        if success:
                            st.session_state.history[index]["rating"] = label
                            st.rerun()
                        else:
                            st.warning("Could not save feedback right now.")
            else:
                st.caption(f"You rated this answer: **{entry['rating']}**")


def main() -> None:
    st.set_page_config(page_title=PAGE_TITLE, page_icon="🎓")
    st.title(f"🎓 {PAGE_TITLE}")
    st.caption(
        "Ask me about course registration, exams, the library, ICT support, "
        "hostels, fees, the academic calendar, or student conduct."
    )

    init_session_state()
    render_sidebar()
    render_history()

    # Show selected topic prompt
    if st.session_state.selected_topic:
        st.info(f"📌 You selected: **{st.session_state.selected_topic}** - Ask your question below")
        placeholder_text = f"Ask about {st.session_state.selected_topic.lower()}..."
    else:
        placeholder_text = "Type your question here..."

    question = st.chat_input(placeholder_text)

    if question is not None:
        if not question.strip():
            st.warning("Please enter a question before submitting.")
        else:
            with st.spinner("Thinking... this may take a few seconds."):
                data, error = call_ask_endpoint(question.strip())

            if error:
                st.error(error)
            else:
                st.session_state.history.append(
                    {
                        "question": data["question"],
                        "answer": data["answer"],
                        "rating": None,
                    }
                )
                st.session_state.selected_topic = None  # Clear selection after answering
                st.rerun()


if __name__ == "__main__":
    main()
