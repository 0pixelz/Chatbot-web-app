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

# === CONFIG FROM ENV ===
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
FIREBASE_CREDENTIALS_JSON = os.getenv("FIREBASE_CREDENTIALS_JSON")
DATABASE_URL = os.getenv("DATABASE_URL")
LOCAL_TIMEZONE = os.getenv("LOCAL_TIMEZONE", "America/Toronto")
CLIENT_SECRET_JSON = os.getenv("GOOGLE_CLIENT_SECRET_JSON")
FLASK_SECRET_KEY = os.getenv("FLASK_SECRET_KEY")

# Debugging
print("DATABASE_URL from ENV:", DATABASE_URL)

missing = [k for k, v in {
    "GROQ_API_KEY": GROQ_API_KEY,
    "FIREBASE_CREDENTIALS_JSON": FIREBASE_CREDENTIALS_JSON,
    "DATABASE_URL": DATABASE_URL,
    "GOOGLE_CLIENT_SECRET_JSON": CLIENT_SECRET_JSON,
    "FLASK_SECRET_KEY": FLASK_SECRET_KEY
}.items() if not v]
if missing:
    raise ValueError(f"Missing environment variables: {', '.join(missing)}")

# === FLASK & FIREBASE INIT ===
app = Flask(__name__)
app.secret_key = FLASK_SECRET_KEY

cred = credentials.Certificate(json.loads(FIREBASE_CREDENTIALS_JSON))
initialize_app(cred, {'databaseURL': DATABASE_URL})

def clean_uid(uid):
    return uid.replace('.', '_')

def load_user_history(uid, chat_id):
    ref = db.reference(f'chat_memory/{clean_uid(uid)}/{chat_id}')
    return ref.get() or []

def save_user_history(uid, chat_id, data):
    ref = db.reference(f'chat_memory/{clean_uid(uid)}/{chat_id}')
    ref.set(data)

def list_chats(uid):
    ref = db.reference(f'chat_memory/{clean_uid(uid)}')
    return ref.get() or {}

def new_chat(uid):
    ref = db.reference(f'chat_memory/{clean_uid(uid)}')
    new_id = str(int(datetime.utcnow().timestamp()))
    ref.child(new_id).set([])
    return new_id

def delete_user(uid):
    db.reference(f'chat_memory/{clean_uid(uid)}').delete()
    db.reference(f'settings/{clean_uid(uid)}').delete()

# === AI RESPONSE ===
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

# === ROUTES ===
@app.route("/")
def index():
    if "user_email" not in session:
        return render_template("welcome.html")
    else:
        return redirect("/chat")

@app.route("/continue_as_guest", methods=["POST"])
def continue_as_guest():
    session["user_email"] = "guest"
    session["user_name"] = "Guest"
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
        redirect_uri=request.url_root[:-1] + url_for("oauth_callback")  # Force HTTPS
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
        scopes=[
            "openid",
            "https://www.googleapis.com/auth/userinfo.email",
            "https://www.googleapis.com/auth/userinfo.profile"
        ],
        redirect_uri=request.url_root[:-1] + url_for("oauth_callback")
    )
    flow.fetch_token(code=request.args["code"])
    creds = flow.credentials
    request_session = grequests.Request()
    idinfo = id_token.verify_oauth2_token(creds._id_token, request_session)
    session["user_email"] = idinfo["email"]
    session["user_picture"] = idinfo.get("picture")
    session["user_name"] = idinfo.get("name", idinfo["email"])
    return redirect("/chat")

@app.route("/chat", methods=["GET", "POST"])
def chat():
    if "user_email" not in session:
        return redirect("/")

    uid = session.get("user_email")
    chat_id = session.get("current_chat_id")

    if not chat_id:
        chat_id = new_chat(uid)
        session["current_chat_id"] = chat_id

    tz = timezone(LOCAL_TIMEZONE)
    message = ""
    reply = ""
    history = load_user_history(uid, chat_id)

    if request.method == "POST":
        message = request.form["message"]
        now = datetime.now(tz).strftime("%I:%M %p")
        history.append({"role": "user", "content": message, "time": now})
        trimmed = [{"role": m["role"], "content": m["content"]} for m in history[-10:]]
        reply = asyncio.run(generate_response(message, trimmed))
        history.append({"role": "assistant", "content": reply, "time": now})
        save_user_history(uid, chat_id, history)

    chats = list_chats(uid)
    return render_template("chat.html", uid=uid, message=message, reply=reply, history=history, chats=chats)

@app.route("/new_chat", methods=["POST"])
def new_chat_route():
    if "user_email" not in session:
        return redirect("/")
    uid = session.get("user_email")
    new_id = new_chat(uid)
    session["current_chat_id"] = new_id
    return redirect("/chat")

@app.route("/clear", methods=["POST"])
def clear():
    if "user_email" not in session:
        return redirect("/")
    uid = session.get("user_email")
    chat_id = session.get("current_chat_id")
    if chat_id:
        db.reference(f'chat_memory/{clean_uid(uid)}/{chat_id}').delete()
    return '', 204

@app.route("/delete_account", methods=["POST"])
def delete_account():
    if "user_email" not in session:
        return redirect("/")
    uid = session.get("user_email")
    delete_user(uid)
    session.clear()
    return redirect("/")

# === RUN ===
if __name__ == "__main__":
    nest_asyncio.apply()
    app.run(host="0.0.0.0", port=8080)
