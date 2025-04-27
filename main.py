import os
import json
import asyncio
import aiohttp
import nest_asyncio
from flask import Flask, request, render_template, redirect, session, url_for
from firebase_admin import credentials, db, initialize_app
from datetime import datetime
from pytz import timezone
from google_auth_oauthlib.flow import Flow
from google.oauth2 import id_token
from google.auth.transport import requests as grequests
import uuid

# === CONFIG FROM ENV ===
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
FIREBASE_CREDENTIALS_JSON = os.getenv("FIREBASE_CREDENTIALS_JSON")
DATABASE_URL = os.getenv("DATABASE_URL")
LOCAL_TIMEZONE = os.getenv("LOCAL_TIMEZONE", "America/Toronto")
CLIENT_SECRET_JSON = os.getenv("GOOGLE_CLIENT_SECRET_JSON")
FLASK_SECRET_KEY = os.getenv("FLASK_SECRET_KEY")

# === FLASK & FIREBASE INIT ===
app = Flask(__name__)
app.secret_key = FLASK_SECRET_KEY
cred = credentials.Certificate(json.loads(FIREBASE_CREDENTIALS_JSON))
initialize_app(cred, {'databaseURL': DATABASE_URL})

nest_asyncio.apply()

# === UTILITIES ===
def clean_uid(uid):
    return uid.replace('.', '_')

def load_user_history(uid, convo_id):
    return db.reference(f'chat_memory/{clean_uid(uid)}/{convo_id}').get() or []

def save_user_history(uid, convo_id, data):
    db.reference(f'chat_memory/{clean_uid(uid)}/{convo_id}').set(data)

def get_settings(uid):
    return db.reference(f'settings/{clean_uid(uid)}').get() or {}

def save_settings(uid, data):
    db.reference(f'settings/{clean_uid(uid)}').set(data)

def delete_user(uid):
    db.reference(f'chat_memory/{clean_uid(uid)}').delete()
    db.reference(f'settings/{clean_uid(uid)}').delete()

def list_conversations(uid):
    return db.reference(f'conversations/{clean_uid(uid)}').get() or {}

# === AI RESPONSE ===
async def generate_response(prompt, memory=[]):
    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json"
    }
    messages = [{"role": "system", "content": "You're a helpful assistant."}] + memory + [{"role": "user", "content": prompt}]
    data = {"model": "llama3-70b-8192", "messages": messages}

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers, json=data) as resp:
                if resp.status != 200:
                    return f"❌ Groq API error {resp.status}"
                result = await resp.json()
                return result['choices'][0]['message']['content']
    except Exception as e:
        return f"❌ Groq connection error: {str(e)}"

async def generate_title_from_message(message):
    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json"
    }
    data = {
        "model": "llama3-70b-8192",
        "messages": [
            {"role": "system", "content": "Summarize the user's message into a 3-5 word title, no punctuation."},
            {"role": "user", "content": message}
        ],
        "temperature": 0.5,
        "max_tokens": 15
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers, json=data) as resp:
                if resp.status != 200:
                    return None
                result = await resp.json()
                return result['choices'][0]['message']['content'].strip()
    except Exception as e:
        return None

# === ROUTES ===

@app.route("/")
def home():
    return redirect("/chat")

@app.route("/login")
def login():
    flow = Flow.from_client_config(
        json.loads(CLIENT_SECRET_JSON),
        scopes=[
            "openid",
            "https://www.googleapis.com/auth/userinfo.email",
            "https://www.googleapis.com/auth/userinfo.profile"
        ],
        redirect_uri=url_for("oauth_callback", _external=True, _scheme="https")
    )
    auth_url, state = flow.authorization_url()
    session["state"] = state
    return redirect(auth_url)

@app.route("/oauth_callback")
def oauth_callback():
    flow = Flow.from_client_config(
        json.loads(CLIENT_SECRET_JSON),
        scopes=[
            "openid",
            "https://www.googleapis.com/auth/userinfo.email",
            "https://www.googleapis.com/auth/userinfo.profile"
        ],
        redirect_uri=url_for("oauth_callback", _external=True, _scheme="https")
    )
    flow.fetch_token(code=request.args["code"])
    creds = flow.credentials
    request_session = grequests.Request()
    idinfo = id_token.verify_oauth2_token(creds._id_token, request_session)
    session["user_email"] = idinfo["email"]
    session["user_picture"] = idinfo.get("picture")
    session["user_name"] = idinfo.get("name", idinfo["email"])
    return redirect("/chat")

@app.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return redirect("/chat")

@app.route("/chat", methods=["GET"])
def chat_redirect():
    return redirect("/start_new_chat")

@app.route("/chat/<convo_id>", methods=["GET", "POST"])
def chat(convo_id):
    uid = session.get("user_email", f"guest_{session.get('guest_id')}")
    tz = timezone(LOCAL_TIMEZONE)
    settings = get_settings(uid)
    conversations = list_conversations(uid)
    history = load_user_history(uid, convo_id)

    if request.method == "POST":
        message = request.form["message"]
        now = datetime.now(tz).strftime("%I:%M %p")
        history.append({"role": "user", "content": message, "time": now})

        trimmed = [{"role": m["role"], "content": m["content"]} for m in history[-10:]]
        reply = asyncio.run(generate_response(message, trimmed))

        history.append({"role": "assistant", "content": reply, "time": now})
        save_user_history(uid, convo_id, history)

        # Title generation
        convo_ref = db.reference(f'conversations/{clean_uid(uid)}/{convo_id}')
        current_title = convo_ref.child('title').get()
        if not current_title:
            title = asyncio.run(generate_title_from_message(message))
            convo_ref.child('title').set(title if title else message[:30])

        return redirect(f"/chat/{convo_id}")

    return render_template("chat.html",
                           uid=uid,
                           history=history,
                           conversations=conversations,
                           convo_id=convo_id,
                           settings=settings)

@app.route("/start_new_chat")
def start_new_chat():
    convo_id = str(uuid.uuid4())
    if "user_email" not in session:
        session["guest_id"] = str(uuid.uuid4())

    uid = session.get("user_email", f"guest_{session.get('guest_id')}")
    if not uid.startswith("guest_"):
        db.reference(f'conversations/{clean_uid(uid)}/{convo_id}').set({"title": None})
    return redirect(f"/chat/{convo_id}")

@app.route("/delete_conversation/<convo_id>", methods=["POST"])
def delete_conversation(convo_id):
    uid = session.get("user_email", f"guest_{session.get('guest_id')}")
    db.reference(f'chat_memory/{clean_uid(uid)}/{convo_id}').delete()
    db.reference(f'conversations/{clean_uid(uid)}/{convo_id}').delete()
    return redirect("/chat")

@app.route("/settings", methods=["GET", "POST"])
def settings_page():
    uid = session.get("user_email", "guest")
    if request.method == "POST":
        data = {
            "theme": request.form.get("theme", "dark"),
            "font_size": request.form.get("font_size", "base"),
            "personality": request.form.get("personality", ""),
            "length": request.form.get("length", "medium")
        }
        save_settings(uid, data)
        return redirect("/chat")

    settings = get_settings(uid)
    return render_template("settings.html", settings=settings)

@app.route("/calendar")
def calendar():
    uid = session.get("user_email", "guest")
    events = db.reference(f'calendar/{clean_uid(uid)}').get() or {}
    return render_template("calendar.html", events=events)

# === RUN ===
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
