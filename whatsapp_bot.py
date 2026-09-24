"""Junior Teacher no WhatsApp.

Servidor que recebe suas mensagens pelo WhatsApp (Meta Cloud API), responde como seu professor
de inglês e, todo dia no horário configurado, manda a aula do dia por conta própria.

Uso:
    python whatsapp_bot.py        # sobe o servidor na porta $PORT (padrão 8000)

Veja o README para configurar as variáveis de ambiente e o webhook na Meta.
"""

import hashlib
import hmac
import json
import os
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import anthropic
import requests
from flask import Flask, abort, request

import teacher

GRAPH_API_VERSION = os.environ.get("GRAPH_API_VERSION", "v23.0")
WHATSAPP_TOKEN = os.environ["WHATSAPP_TOKEN"]
PHONE_NUMBER_ID = os.environ["WHATSAPP_PHONE_NUMBER_ID"]
VERIFY_TOKEN = os.environ["WHATSAPP_VERIFY_TOKEN"]
APP_SECRET = os.environ.get("WHATSAPP_APP_SECRET", "")
# Only these numbers talk to the teacher (digits only, with country code: 5511999999999).
STUDENT_PHONES = {p.strip().lstrip("+") for p in os.environ["STUDENT_PHONE"].split(",") if p.strip()}
DAILY_LESSON_TIME = os.environ.get("DAILY_LESSON_TIME", "19:00")  # "" disables the daily lesson
TIMEZONE = ZoneInfo(os.environ.get("TIMEZONE", "America/Sao_Paulo"))
# Template sent when the 24h customer-service window is closed (WhatsApp rule for business-initiated chats).
TEMPLATE_NAME = os.environ.get("WHATSAPP_TEMPLATE", "hello_world")
TEMPLATE_LANG = os.environ.get("WHATSAPP_TEMPLATE_LANG", "en_US")
DATA_DIR = Path(os.environ.get("DATA_DIR", Path(__file__).with_name("data")))
HISTORY_TURNS = 40  # messages of chat history kept per student
WINDOW = timedelta(hours=24)

WHATSAPP_NOTE = """\
[Canal: WhatsApp] Você está conversando com o aluno pelo WhatsApp. Escreva como numa conversa de
WhatsApp: mensagens curtas (idealmente até 3 parágrafos curtos), sem tabelas nem títulos Markdown.
Formatação do WhatsApp: *negrito*, _itálico_, ~riscado~. Emojis com moderação são bem-vindos."""

DAILY_PROMPT = """\
[Aula diária automática] Agora é o horário da aula diária. Mande a mensagem de abertura da aula de
hoje: cumprimente o aluno, retome algo das aulas anteriores (vocabulário ou erro recorrente) e
proponha uma atividade curta e interessante, terminando com uma pergunta ou tarefa."""

app = Flask(__name__)
client = anthropic.Anthropic()
seen_message_ids: set[str] = set()
locks: dict[str, threading.Lock] = {}
locks_guard = threading.Lock()


# --- Student storage -----------------------------------------------------------------------

def student_dir(phone: str) -> Path:
    path = DATA_DIR / phone
    path.mkdir(parents=True, exist_ok=True)
    return path


def student_lock(phone: str) -> threading.Lock:
    with locks_guard:
        return locks.setdefault(phone, threading.Lock())


def load_chat(phone: str) -> dict:
    path = student_dir(phone) / "chat.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {"history": [], "last_student_message_at": None, "last_daily_lesson": None, "lesson_pending": False}


def save_chat(phone: str, chat: dict) -> None:
    chat["history"] = chat["history"][-HISTORY_TURNS:]
    # Keep the history starting on a student turn.
    while chat["history"] and chat["history"][0]["role"] != "user":
        chat["history"].pop(0)
    (student_dir(phone) / "chat.json").write_text(json.dumps(chat, ensure_ascii=False, indent=2), encoding="utf-8")


def window_open(chat: dict) -> bool:
    last = chat["last_student_message_at"]
    return last is not None and datetime.now(TIMEZONE) - datetime.fromisoformat(last) < WINDOW - timedelta(minutes=5)


# --- WhatsApp API --------------------------------------------------------------------------

def graph_post(payload: dict) -> None:
    resp = requests.post(
        f"https://graph.facebook.com/{GRAPH_API_VERSION}/{PHONE_NUMBER_ID}/messages",
        headers={"Authorization": f"Bearer {WHATSAPP_TOKEN}"},
        json={"messaging_product": "whatsapp", **payload},
        timeout=30,
    )
    if not resp.ok:
        app.logger.error("WhatsApp API error %s: %s", resp.status_code, resp.text)
    resp.raise_for_status()


def send_text(phone: str, text: str) -> None:
    # WhatsApp caps text messages at 4096 characters; split on paragraphs when longer.
    chunks, current = [], ""
    for para in text.split("\n\n"):
        if current and len(current) + len(para) + 2 > 4000:
            chunks.append(current)
            current = ""
        current = f"{current}\n\n{para}" if current else para
    chunks.append(current)
    for chunk in chunks:
        graph_post({"to": phone, "type": "text", "text": {"body": chunk[:4096]}})


def send_template(phone: str) -> None:
    graph_post({"to": phone, "type": "template", "template": {"name": TEMPLATE_NAME, "language": {"code": TEMPLATE_LANG}}})


def mark_read(message_id: str) -> None:
    try:
        graph_post({"status": "read", "message_id": message_id})
    except requests.RequestException:
        pass


# --- Teacher -------------------------------------------------------------------------------

def ask_teacher(phone: str, chat: dict, student_text: str) -> str:
    """Send one student message (or automatic instruction) to the teacher and return the reply."""
    progress_path = student_dir(phone) / "progress.json"
    progress = teacher.load_progress(progress_path)
    # The saved-progress summary rides on the newest message, so the older history stays a
    # stable, cacheable prefix.
    context = f"[Contexto do sistema]\n{WHATSAPP_NOTE}\n{teacher.student_context(progress)}"
    messages = [*chat["history"], {"role": "user", "content": f"{context}\n\n[Mensagem]\n{student_text}"}]

    reply = teacher.teacher_turn(
        client, messages, progress,
        on_text=lambda _: None,
        save=lambda p: teacher.save_progress(p, progress_path),
    )
    if reply is None:
        return "Desculpe, não consegui responder a isso. Pode reformular? 🙏"

    chat["history"] += [{"role": "user", "content": student_text}, {"role": "assistant", "content": reply}]
    return reply


def handle_student_message(phone: str, message: dict) -> None:
    with student_lock(phone):
        chat = load_chat(phone)
        chat["last_student_message_at"] = datetime.now(TIMEZONE).isoformat()
        mark_read(message["id"])

        if message["type"] == "text":
            text = message["text"]["body"]
        elif message["type"] == "button":
            text = message["button"]["text"]
        else:
            text = f"(o aluno enviou uma mensagem do tipo '{message['type']}', que ainda não consigo ler; peça para ele escrever em texto)"
        if chat.get("lesson_pending"):
            # The daily lesson went out as a template; start it now that the student answered.
            text = f"{DAILY_PROMPT}\nO aluno acabou de responder ao lembrete da aula com:\n{text}"
            chat["lesson_pending"] = False

        try:
            reply = ask_teacher(phone, chat, text)
        except anthropic.APIError:
            app.logger.exception("Anthropic API error")
            reply = "Tive um probleminha técnico agora. Tenta de novo daqui a pouco? 🙏"
        save_chat(phone, chat)
        send_text(phone, reply)


def send_daily_lesson(phone: str) -> None:
    with student_lock(phone):
        chat = load_chat(phone)
        today = datetime.now(TIMEZONE).date().isoformat()
        if chat["last_daily_lesson"] == today:
            return
        chat["last_daily_lesson"] = today

        progress_path = student_dir(phone) / "progress.json"
        progress = teacher.load_progress(progress_path)
        progress["sessions"] += 1
        teacher.save_progress(progress, progress_path)

        if not window_open(chat):
            # Outside the 24h window WhatsApp only allows approved templates. Send it; the lesson
            # starts as soon as the student replies.
            chat["lesson_pending"] = True
            save_chat(phone, chat)
            send_template(phone)
            return

        reply = ask_teacher(phone, chat, DAILY_PROMPT)
        save_chat(phone, chat)
        send_text(phone, reply)


def scheduler() -> None:
    hour, minute = map(int, DAILY_LESSON_TIME.split(":"))
    while True:
        now = datetime.now(TIMEZONE)
        if (now.hour, now.minute) >= (hour, minute):
            for phone in STUDENT_PHONES:
                try:
                    send_daily_lesson(phone)
                except Exception:
                    app.logger.exception("Daily lesson failed for %s", phone)
        time.sleep(30)


# --- Webhook -------------------------------------------------------------------------------

@app.get("/webhook")
def verify():
    if request.args.get("hub.mode") == "subscribe" and request.args.get("hub.verify_token") == VERIFY_TOKEN:
        return request.args.get("hub.challenge", "")
    abort(403)


@app.post("/webhook")
def receive():
    if APP_SECRET:
        expected = "sha256=" + hmac.new(APP_SECRET.encode(), request.get_data(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, request.headers.get("X-Hub-Signature-256", "")):
            abort(403)

    body = request.get_json(silent=True) or {}
    for entry in body.get("entry", []):
        for change in entry.get("changes", []):
            for message in change.get("value", {}).get("messages", []):
                phone = message.get("from", "")
                if phone not in STUDENT_PHONES or message["id"] in seen_message_ids:
                    continue
                seen_message_ids.add(message["id"])
                # Answer Meta right away; the teacher replies in the background.
                threading.Thread(target=handle_student_message, args=(phone, message), daemon=True).start()
    return "ok"


@app.get("/")
def health():
    return "Junior Teacher is running"


if __name__ == "__main__":
    if not APP_SECRET:
        app.logger.warning("WHATSAPP_APP_SECRET not set: webhook signatures are not being checked.")
    if DAILY_LESSON_TIME:
        threading.Thread(target=scheduler, daemon=True).start()
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))
