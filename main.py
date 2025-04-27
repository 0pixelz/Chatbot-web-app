import os
import json
import uuid
import asyncio
import aiohttp
import nest_asyncio
from flask import Flask, request, render_template, redirect, session, url_for, jsonify
from firebase_admin import credentials, db, initialize_app
from datetime import datetime
from pytz import timezone
from google_auth_oauthlib.flow import Flow
from google.oauth2 import id_token
from google.auth.transport import requests as grequests

# === CONFIG ===
GROQ_API_KEY               = os.getenv("GROQ_API_KEY")
FIREBASE_CREDENTIALS_JSON  = os.getenv("FIREBASE_CREDENTIALS_JSON")
DATABASE_URL               = os.getenv("DATABASE_URL")
LOCAL_TIMEZONE             = os.getenv("LOCAL_TIMEZONE", "America/Toronto")
CLIENT_SECRET_JSON         = os.getenv("GOOGLE_CLIENT_SECRET_JSON")
FLASK_SECRET_KEY           = os.getenv("FLASK_SECRET_KEY")

# === INIT ===
app = Flask(__name__)
app.secret_key = FLASK_SECRET_KEY

cred = credentials.Certificate(json.loads(FIREBASE_CREDENTIALS_JSON))
initialize_app(cred, {'databaseURL': DATABASE_URL})

nest_asyncio.apply()

# === HELPERS ===
def clean_uid(uid):
    return uid.replace('.', '_')

def load_user_history(uid, convo_id):
    path = f'chat_memory/{clean_uid(uid)}/{convo_id}'
    return db.reference(path).get() or []

def save_user_history(uid, convo_id, data):
    path = f'chat_memory/{clean_uid(uid)}/{convo_id}'
    db.reference(path).set(data)

def get_settings(uid):
    ref = db.reference(f'settings/{clean_uid(uid)}')
    return ref.get() or {}

def save_settings(uid, data):
    db.reference(f'settings/{clean_uid(uid)}').set(data)

def delete_conversation(uid, convo_id):
    db.reference(f'chat_memory/{clean_uid(uid)}/{convo_id}').delete()
    db.reference(f'conversations/{clean_uid(uid)}/{convo_id}').delete()

def list_conversations(uid):
    ref = db.reference(f'conversations/{clean_uid(uid)}')
    return ref.get() or {}

# === AI FUNCTIONS ===
async def generate_response(prompt, memory=[]):
    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"}
    data = {
        "model": "llama3-70b-8192",
        "messages": [{"role": "system", "content": "You're a helpful assistant."}] + memory + [{"role": "user", "content": prompt}]
    }
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers, json=data) as resp:
                result = await resp.json()
                return result['choices'][0]['message']['content']
    except Exception as e:
        return f"❌ AI Error: {str(e)}"

async def generate_title(prompt):
    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"}
    data = {
        "model": "llama3-70b-8192",
        "messages": [{"role": "system", "content": "Summarize this message into 3-5 word title."}, {"role": "user", "content": prompt}],
        "temperature": 0.5,
        "max_tokens": 15
    }
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers, json=data) as resp:
                result = await resp.json()
                return result['choices'][0]['message']['content'].strip()
    except:
        return None

# === AUTH ===
@app.route("/login")
def login():
    flow = Flow.from_client_config(
        json.loads(CLIENT_SECRET_JSON),
        scopes=["openid", "https://www.googleapis.com/auth/userinfo.email", "https://www.googleapis.com/auth/userinfo.profile"],
        redirect_uri=url_for('oauth_callback', _external=True, _scheme="https")
    )
    auth_url, state = flow.authorization_url()
    session["state"] = state
    return redirect(auth_url)

@app.route("/oauth_callback")
def oauth_callback():
    flow = Flow.from_client_config(
        json.loads(CLIENT_SECRET_JSON),
        scopes=["openid", "https://www.googleapis.com/auth/userinfo.email", "https://www.googleapis.com/auth/userinfo.profile"],
        redirect_uri=url_for('oauth_callback', _external=True, _scheme="https")
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

# === CHAT ===
@app.route("/")
def home():
    return redirect("/chat")

@app.route("/chat")
def redirect_chat():
    return redirect("/start_new_chat")

@app.route("/start_new_chat")
def start_new_chat():
    convo_id = str(uuid.uuid4())
    uid = session.get("user_email", "guest")
    if uid != "guest":
        db.reference(f'conversations/{clean_uid(uid)}/{convo_id}').set({'title': None})
    return redirect(f"/chat/{convo_id}")

@app.route("/chat/<convo_id>", methods=["GET", "POST"])
def chat(convo_id):
    uid = session.get("user_email", "guest")
    tz = timezone(LOCAL_TIMEZONE)
    history = load_user_history(uid, convo_id)
    conversations = list_conversations(uid) if uid != "guest" else {}
    settings = get_settings(uid)

    if request.method == "POST":
        message = request.form["message"]
        now = datetime.now(tz).strftime("%I:%M %p")
        history.append({"role": "user", "content": message, "time": now})

        trimmed = [{"role": m["role"], "content": m["content"]} for m in history[-10:]]
        reply = asyncio.run(generate_response(message, trimmed))

        history.append({"role": "assistant", "content": reply, "time": now})
        save_user_history(uid, convo_id, history)

        if uid != "guest":
            convo_ref = db.reference(f'conversations/{clean_uid(uid)}/{convo_id}')
            if not convo_ref.child('title').get():
                title = asyncio.run(generate_title(message)) or (message[:27] + "..." if len(message) > 30 else message)
                convo_ref.child('title').set(title)

        return redirect(f"/chat/{convo_id}")

    return render_template("chat.html", uid=uid, history=history, settings=settings, conversations=conversations, convo_id=convo_id)

@app.route("/delete_conversation/<convo_id>", methods=["POST"])
def delete_convo(convo_id):
    uid = session.get("user_email", "guest")
    delete_conversation(uid, convo_id)
    return redirect("/chat")

# === CALENDAR ===
@app.route("/calendar")
def calendar():
    if not session.get("user_email"):
        return redirect("/chat")
    return render_template("calendar.html")

@app.route("/get_events")
def get_events():
    uid = session.get("user_email")
    if not uid:
        return jsonify([])
    events = db.reference(f'events/{clean_uid(uid)}').get() or {}
    formatted = [{"title": v["title"], "start": v["date"]} for v in events.values()]
    return jsonify(formatted)

@app.route("/add_event", methods=["POST"])
def add_event():
    uid = session.get("user_email")
    if not uid:
        return "Unauthorized", 401
    data = request.json
    event_id = str(uuid.uuid4())
    db.reference(f'events/{clean_uid(uid)}/{event_id}').set({
        "title": data["title"],
        "date": data["date"]
    })
    return "OK"

# === CLEAR CHAT ===
@app.route("/clear", methods=["POST"])
def clear():
    uid = session.get("user_email", "guest")
    db.reference(f'chat_memory/{clean_uid(uid)}').delete()
    return redirect("/chat")

# === START SERVER ===
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
