"""Junior no WhatsApp: um amigo que te ensina inglês conversando.

Servidor que recebe suas mensagens pelo WhatsApp (Meta Cloud API), responde como o Junior e, nos
horários configurados, puxa conversa com você por conta própria.

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
# Only these numbers talk to Junior (digits only, with country code: 5511999999999).
STUDENT_PHONES = {p.strip().lstrip("+") for p in os.environ["STUDENT_PHONE"].split(",") if p.strip()}
# Times of day when Junior starts a conversation on his own ("" disables it).
CHECKIN_TIMES = sorted(t.strip() for t in os.environ.get("CHECKIN_TIMES", "09:00,12:30,19:30").split(",") if t.strip())
# Don't interrupt: skip a check-in if the student wrote within this many minutes.
QUIET_MINUTES = int(os.environ.get("QUIET_MINUTES", "120"))
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

CHECKIN_PROMPT = """\
[Mensagem automática] Faz um tempinho que vocês não conversam e agora é {moment}. Mande uma
mensagem puxando papo, como um amigo faria: pergunte de algo que ele te contou, comente algo do
dia, ou traga um assunto dos interesses dele — e encaixe algo de inglês de forma natural (uma
expressão nova, retomar uma palavra ou erro antigo, um mini desafio). Uma mensagem curta só."""

REPLY_TO_TEMPLATE_NOTE = """\
[Contexto] Ele está respondendo ao lembrete automático que o WhatsApp manda quando vocês ficam mais
de 24 h sem conversar. Retome a amizade com naturalidade a partir do que ele respondeu."""
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
    return {"history": [], "last_student_message_at": None, "last_junior_message_at": None,
            "last_checkin_slot": None, "template_pending": False}


def save_chat(phone: str, chat: dict) -> None:
    chat["history"] = chat["history"][-HISTORY_TURNS:]
    # Keep the history starting on a student turn.
    while chat["history"] and chat["history"][0]["role"] != "user":
        chat["history"].pop(0)
    (student_dir(phone) / "chat.json").write_text(json.dumps(chat, ensure_ascii=False, indent=2), encoding="utf-8")


def since(timestamp: str | None) -> timedelta | None:
    return None if timestamp is None else datetime.now(TIMEZONE) - datetime.fromisoformat(timestamp)


def window_open(chat: dict) -> bool:
    elapsed = since(chat["last_student_message_at"])
    return elapsed is not None and elapsed < WINDOW - timedelta(minutes=5)


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


# --- Junior --------------------------------------------------------------------------------

def ask_junior(phone: str, chat: dict, student_text: str) -> str:
    """Send one student message (or automatic instruction) to Junior and return the reply."""
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
        return "Opa, essa eu não consigo responder 😅 Bora falar de outra coisa?"

    chat["history"] += [{"role": "user", "content": student_text}, {"role": "assistant", "content": reply}]
    chat["last_junior_message_at"] = datetime.now(TIMEZONE).isoformat()
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
        if chat.get("template_pending"):
            text = f"{REPLY_TO_TEMPLATE_NOTE}\n\n{text}"
            chat["template_pending"] = False

        try:
            reply = ask_junior(phone, chat, text)
        except anthropic.APIError:
            app.logger.exception("Anthropic API error")
            reply = "Eita, deu um probleminha aqui do meu lado 😅 Me manda de novo daqui a pouco?"
        save_chat(phone, chat)
        send_text(phone, reply)


def moment_of_day(now: datetime) -> str:
    if now.hour < 12:
        return "de manhã"
    return "à tarde" if now.hour < 18 else "à noite"


def send_checkin(phone: str, slot: str) -> None:
    with student_lock(phone):
        chat = load_chat(phone)
        if chat["last_checkin_slot"] == slot:
            return
        chat["last_checkin_slot"] = slot
        save_chat(phone, chat)

        student_gap = since(chat["last_student_message_at"])
        junior_gap = since(chat["last_junior_message_at"])
        if student_gap is not None and student_gap < timedelta(minutes=QUIET_MINUTES):
            return  # you're already chatting; don't interrupt
        unanswered = junior_gap is not None and (student_gap is None or junior_gap < student_gap)
        if unanswered and junior_gap < timedelta(hours=12):
            return  # he already sent something you haven't answered; don't double-text

        if not window_open(chat):
            # Outside the 24h window WhatsApp only allows approved templates; send it at most
            # once per silence, and pick up the conversation when you answer.
            if not chat["template_pending"]:
                chat["template_pending"] = True
                chat["last_junior_message_at"] = datetime.now(TIMEZONE).isoformat()
                save_chat(phone, chat)
                send_template(phone)
            return

        reply = ask_junior(phone, chat, CHECKIN_PROMPT.format(moment=moment_of_day(datetime.now(TIMEZONE))))
        save_chat(phone, chat)
        send_text(phone, reply)


def current_slot(now: datetime) -> str | None:
    """The check-in time that just passed (within the last hour), as 'YYYY-MM-DD HH:MM'."""
    for t in reversed(CHECKIN_TIMES):
        hour, minute = map(int, t.split(":"))
        at = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if at <= now < at + timedelta(hours=1):
            return f"{now.date().isoformat()} {t}"
    return None


def scheduler() -> None:
    while True:
        slot = current_slot(datetime.now(TIMEZONE))
        if slot:
            for phone in STUDENT_PHONES:
                try:
                    send_checkin(phone, slot)
                except Exception:
                    app.logger.exception("Check-in failed for %s", phone)
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
                # Answer Meta right away; Junior replies in the background.
                threading.Thread(target=handle_student_message, args=(phone, message), daemon=True).start()
    return "ok"


@app.get("/")
def health():
    return "Junior is running"


if __name__ == "__main__":
    if not APP_SECRET:
        app.logger.warning("WHATSAPP_APP_SECRET not set: webhook signatures are not being checked.")
    if CHECKIN_TIMES:
        threading.Thread(target=scheduler, daemon=True).start()
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))
