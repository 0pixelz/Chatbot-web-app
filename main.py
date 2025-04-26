import os
import json
import asyncio
import aiohttp
import nest_asyncio
import uuid
from flask import Flask, request, render_template, redirect, session, url_for
from firebase_admin import credentials, db, initialize_app
from datetime import datetime
from pytz import timezone
from google_auth_oauthlib.flow import Flow
from google.oauth2 import id_token
from google.auth.transport import requests as grequests
from werkzeug.middleware.proxy_fix import ProxyFix

# === CONFIG FROM ENV ===
GROQ_API_KEY               = os.getenv("GROQ_API_KEY")
FIREBASE_CREDENTIALS_JSON  = os.getenv("FIREBASE_CREDENTIALS_JSON")
DATABASE_URL               = os.getenv("DATABASE_URL")
LOCAL_TIMEZONE             = os.getenv("LOCAL_TIMEZONE", "America/Toronto")
CLIENT_SECRET_JSON         = os.getenv("GOOGLE_CLIENT_SECRET_JSON")
FLASK_SECRET_KEY           = os.getenv("FLASK_SECRET_KEY")

# === FLASK & FIREBASE INIT ===
app = Flask(__name__)
app.secret_key = FLASK_SECRET_KEY
app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)

cred = credentials.Certificate(json.loads(FIREBASE_CREDENTIALS_JSON))
initialize_app(cred, {'databaseURL': DATABASE_URL})

nest_asyncio.apply()

# === UTILITIES ===
def clean_uid(uid):
    return uid.replace('.', '_')

def get_conversations(uid):
    ref = db.reference(f'chat_memory/{clean_uid(uid)}')
    return ref.get() or {}

def load_user_history(uid, convo_id):
    messages = db.reference(f'chat_memory/{clean_uid(uid)}/{convo_id}/messages').get()
    return messages or []

def save_user_history(uid, convo_id, messages):
    db.reference(f'chat_memory/{clean_uid(uid)}/{convo_id}/messages').set(messages)

def get_settings(uid):
    return db.reference(f'settings/{clean_uid(uid)}').get() or {}

def save_settings(uid, data):
    db.reference(f'settings/{clean_uid(uid)}').set(data)

def delete_user(uid):
    db.reference(f'chat_memory/{clean_uid(uid)}').delete()
    db.reference(f'settings/{clean_uid(uid)}').delete()

async def generate_response(prompt, memory=[]):
    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"}
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

async def summarize_title(messages):
    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"}
    prompt = "Summarize this conversation into a short title, maximum 5 words."

    data = {
        "model": "llama3-70b-8192",
        "messages": [{"role": "system", "content": prompt}] + messages
    }
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers, json=data) as resp:
                if resp.status != 200:
                    return "New Chat"
                result = await resp.json()
                return result['choices'][0]['message']['content'].strip()
    except Exception:
        return "New Chat"

# === ROUTES ===

@app.route("/")
def index():
    return redirect("/start_new_chat")

@app.route("/login")
def login():
    flow = Flow.from_client_config(
        json.loads(CLIENT_SECRET_JSON),
        scopes=["openid", "https://www.googleapis.com/auth/userinfo.email", "https://www.googleapis.com/auth/userinfo.profile"],
        redirect_uri=url_for("oauth_callback", _external=True)
    )
    auth_url, state = flow.authorization_url()
    session["state"] = state
    return redirect(auth_url)

@app.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return redirect("/")

@app.route("/oauth_callback")
def oauth_callback():
    flow = Flow.from_client_config(
        json.loads(CLIENT_SECRET_JSON),
        scopes=["openid", "https://www.googleapis.com/auth/userinfo.email", "https://www.googleapis.com/auth/userinfo.profile"],
        redirect_uri=url_for("oauth_callback", _external=True)
    )
    flow.fetch_token(code=request.args["code"])
    creds = flow.credentials
    request_session = grequests.Request()
    idinfo = id_token.verify_oauth2_token(creds._id_token, request_session)
    session["user_email"] = idinfo["email"]
    session["user_picture"] = idinfo.get("picture")
    session["user_name"] = idinfo.get("name", idinfo["email"])
    return redirect("/start_new_chat")

@app.route("/chat/<convo_id>", methods=["GET", "POST"])
def chat(convo_id):
    uid = session.get("user_email", "guest")
    message = ""
    reply = ""
    tz = timezone(LOCAL_TIMEZONE)
    history = load_user_history(uid, convo_id)
    settings = get_settings(uid)
    conversations = get_conversations(uid)

    if request.method == "POST":
        message = request.form["message"]
        now = datetime.now(tz).strftime("%I:%M %p")
        history.append({"role": "user", "content": message, "time": now})
        trimmed = [{"role": m["role"], "content": m["content"]} for m in history[-10:]]
        reply = asyncio.run(generate_response(message, trimmed))
        history.append({"role": "assistant", "content": reply, "time": now})
        save_user_history(uid, convo_id, history)

        # Refresh title after first message or every 10 messages
        if len(history) == 2 or (len(history) > 2 and len(history) % 10 == 0):
            summary = asyncio.run(summarize_title(history))
            db.reference(f'chat_memory/{clean_uid(uid)}/{convo_id}/title').set(summary)

    return render_template("chat.html", uid=uid, message=message, reply=reply, history=history, settings=settings, conversations=conversations, convo_id=convo_id)

@app.route("/start_new_chat")
def start_new_chat():
    convo_id = str(uuid.uuid4())
    uid = session.get("user_email", "guest")
    db.reference(f'chat_memory/{clean_uid(uid)}/{convo_id}/messages').set([])
    return redirect(f"/chat/{convo_id}")

@app.route("/delete_conversation/<convo_id>", methods=["POST"])
def delete_conversation(convo_id):
    uid = session.get("user_email", "guest")
    db.reference(f'chat_memory/{clean_uid(uid)}/{convo_id}').delete()
    return redirect("/start_new_chat")

@app.route("/settings", methods=["GET", "POST"])
def settings():
    uid = session.get("user_email", "guest")
    if request.method == "POST":
        data = {
            "theme": request.form.get("theme", "dark"),
            "font_size": request.form.get("font_size", "base"),
            "personality": request.form.get("personality", ""),
            "length": request.form.get("length", "medium")
        }
        save_settings(uid, data)
        return redirect("/start_new_chat")
    settings = get_settings(uid)
    return render_template("settings.html", settings=settings)

@app.route("/delete_account", methods=["POST"])
def delete_account():
    uid = session.get("user_email", "guest")
    delete_user(uid)
    session.clear()
    return redirect("/")

# === RUN ===
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
