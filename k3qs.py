import streamlit as st
import random
from openai import OpenAI
import threading
import io
import time

# --- Core Quiz Logic (Thread-Safe) ---

MODEL = "llama-3.1-sonar-small-128k-online"


def load_verbs(uploaded_file):
    """Load verbs from an uploaded file. This runs in the main thread."""
    try:
        stringio = io.StringIO(uploaded_file.getvalue().decode("utf-8"))
        verbs = []
        for line in stringio:
            if '[' in line and ']' in line:
                verb, translation = line.split('[', 1)
                translation = translation.split(']')[0].strip()
                verbs.append({"Verb": verb.strip(), "Translation": translation})
        return verbs
    except Exception as e:
        st.error(f"Error reading or parsing the file: {e}")
        return None


def generate_context_sentence(verb, api_key):
    """API call function. Can be called from any thread."""
    if not api_key:
        return "[API Key not provided]"
    try:
        client = OpenAI(api_key=api_key, base_url="https://api.perplexity.ai")
        messages = [
            {"role": "system",
             "content": "You are a German language assistant. Create a simple A2 level sentence using the given verb."},
            {"role": "user",
             "content": f"Create a simple A1 level German sentence using the verb '{verb}'. Use it as a verb not as noun or adverb. Use different Personalpronomen, not just ich. Use different Tempus for sentence, either Präsens or Präteritum or Perfekt. Don't make the verb ternnbar if it is not such already. Under any circumstances, do not provide an English translation for the sentence. Create only one sentence."}
        ]
        response = client.chat.completions.create(model=MODEL, messages=messages)
        return response.choices[0].message.content
    except Exception as e:
        return f"[Sentence generation failed for '{verb}': {e}]"


def prepare_question_data(verb_entry, all_verbs, api_key):
    """Prepares data for one question. Can be called from any thread."""
    current_verb = verb_entry["Verb"]
    correct_translation = verb_entry["Translation"]
    context_sentence = generate_context_sentence(current_verb, api_key)

    other_verbs = [v for v in all_verbs if v["Translation"] != correct_translation]
    translations = [v["Translation"] for v in random.sample(other_verbs, 4)]
    translations.append(correct_translation)
    random.shuffle(translations)

    return {
        "current_verb": current_verb,
        "correct_translation": correct_translation,
        "context_sentence": context_sentence,
        "translations": translations
    }


def worker_prepare_question(verb_entry, all_verbs, api_key, result_holder):
    """THREAD WORKER: Prepares a question. No access to st.session_state."""
    q_data = prepare_question_data(verb_entry, all_verbs, api_key)
    result_holder['data'] = q_data


# --- Streamlit UI and State Management ---

def launch_next_question_job():
    """MAIN THREAD: Starts a background job to prepare the next question."""
    if st.session_state.unused_verbs:
        next_verb_entry = st.session_state.unused_verbs.pop()
        result_holder = {'data': None}
        thread = threading.Thread(
            target=worker_prepare_question,
            args=(next_verb_entry, st.session_state.all_verbs, st.session_state.api_key, result_holder)
        )
        thread.start()
        st.session_state.next_question_job = {'thread': thread, 'result': result_holder}
    else:
        st.session_state.next_question_job = None


def initialize_quiz(uploaded_file, api_key):
    """Sets up the initial state for the quiz. MAIN THREAD ONLY."""
    verbs = load_verbs(uploaded_file)
    if not verbs or len(verbs) < 5:
        st.error("File must contain at least 5 verbs to create multiple-choice questions.")
        return

    random.shuffle(verbs)
    st.session_state.all_verbs = verbs
    st.session_state.total_verbs = len(verbs)
    st.session_state.unused_verbs = verbs.copy()
    st.session_state.incorrect_answers = []
    st.session_state.question_number = 1
    st.session_state.api_key = api_key
    st.session_state.quiz_running = True
    st.session_state.show_feedback = False

    q1_verb = st.session_state.unused_verbs.pop()
    st.session_state.current_question_data = prepare_question_data(
        q1_verb, st.session_state.all_verbs, st.session_state.api_key
    )
    launch_next_question_job()


def handle_answer(user_choice):
    """Callback for answer buttons. MAIN THREAD ONLY."""
    q = st.session_state.current_question_data
    st.session_state.last_answer_was_correct = (user_choice == q['correct_translation'])
    if not st.session_state.last_answer_was_correct:
        st.session_state.incorrect_answers.append({
            "Verb": q['current_verb'],
            "Correct Translation": q['correct_translation'],
            "User Choice": user_choice
        })
    st.session_state.show_feedback = True


def next_question():
    """Callback for 'Next' button. MAIN THREAD ONLY."""
    job = st.session_state.next_question_job
    if job:
        with st.spinner("Loading next question..."):
            job['thread'].join()
            result_data = job['result']['data']

        st.session_state.current_question_data = result_data
        st.session_state.question_number += 1
        st.session_state.show_feedback = False
        launch_next_question_job()


# --- Main App UI ---
st.set_page_config(page_title="Klug3 Verb Quiz", layout="centered")
st.title("🇩🇪 Klug3 German Verb Quiz")

if 'quiz_running' not in st.session_state:
    st.session_state.quiz_running = False

with st.sidebar:
    st.header("Setup")
    api_key_input = st.text_input("Enter your Perplexity API Key", type="password", key="api_key_input")
    uploaded_file = st.file_uploader("Upload your verb file (.txt)", type="txt")

    if st.button("Start Quiz", disabled=(not uploaded_file or not api_key_input)):
        initialize_quiz(uploaded_file, api_key_input)
        st.rerun()

    # --- [NEW FEATURE 1] STOP QUIZ BUTTON ---
    # This button is only shown when the quiz is active
    if st.session_state.get('quiz_running', False):
        st.write("---")
        if st.button("End Quiz Now", type="secondary", use_container_width=True):
            st.session_state.quiz_running = False
            st.rerun()

# --- App Logic Flow ---
if not st.session_state.quiz_running:
    # This block now serves as the landing page AND the end-of-quiz summary page
    if 'total_verbs' in st.session_state:  # This checks if a quiz was ever started
        st.balloons()
        st.success("🎉 Quiz Finished! 🎉")

        # --- [NEW FEATURE 2] MISTAKE SUMMARY ---
        incorrect = st.session_state.incorrect_answers
        if incorrect:
            st.subheader("Items to review:")
            for item in incorrect:
                # Displays the German verb and the correct translation side-by-side
                st.warning(
                    f"**{item['Verb']}** = **{item['Correct Translation']}** (You chose: *{item['User Choice']}*)")
        else:
            # Only show this if they actually answered at least one question
            if st.session_state.question_number > 1 or st.session_state.show_feedback:
                st.info("Excellent! You had no incorrect answers.")

        if st.button("Start Over"):
            # Clear all session state keys to reset the app completely
            for key in list(st.session_state.keys()):
                del st.session_state[key]
            st.rerun()
    else:
        st.info("Please provide your API key and upload a verb file in the sidebar to begin.")

elif st.session_state.quiz_running:
    # --- Display Question and Options ---
    q = st.session_state.current_question_data
    st.progress(st.session_state.question_number / st.session_state.total_verbs,
                text=f"Question {st.session_state.question_number} / {st.session_state.total_verbs}")
    st.subheader(f"What is the meaning of: `{q['current_verb']}`?")
    st.markdown(f"**Context:** *{q['context_sentence']}*")
    st.write("---")

    if not st.session_state.show_feedback:
        cols = st.columns(2)
        for i, translation in enumerate(q['translations']):
            with cols[i % 2]:
                st.button(translation, key=f"opt_{i}", use_container_width=True, on_click=handle_answer,
                          args=(translation,))
    else:  # Show feedback and Next button
        if st.session_state.last_answer_was_correct:
            st.success(f"**Correct!** `{q['current_verb']}` means **'{q['correct_translation']}'**.")
        else:
            st.error(
                f"**Incorrect.** The correct translation for `{q['current_verb']}` is **'{q['correct_translation']}'**.")

        if st.session_state.next_question_job:
            st.button("Next Question →", use_container_width=True, type="primary", on_click=next_question)
        else:
            if st.button("Finish Quiz", use_container_width=True, type="primary"):
                st.session_state.quiz_running = False
                st.rerun()