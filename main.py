# === FULL FINAL main.py (HTTPS-ready, Google login, Start New Chat support) ===

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
GROQ_API_KEY               = os.getenv("GROQ_API_KEY")
FIREBASE_CREDENTIALS_JSON  = os.getenv("FIREBASE_CREDENTIALS_JSON")
DATABASE_URL               = os.getenv("DATABASE_URL")
LOCAL_TIMEZONE             = os.getenv("LOCAL_TIMEZONE", "America/Toronto")
CLIENT_SECRET_JSON         = os.getenv("GOOGLE_CLIENT_SECRET_JSON")
FLASK_SECRET_KEY           = os.getenv("FLASK_SECRET_KEY")
OAUTH_REDIRECT_URI         = os.getenv("OAUTH_REDIRECT_URI")  # 🔥 Important for HTTPS!!

# === FLASK & FIREBASE INIT ===
app = Flask(__name__)
app.secret_key = FLASK_SECRET_KEY

cred = credentials.Certificate(json.loads(FIREBASE_CREDENTIALS_JSON))
initialize_app(cred, {'databaseURL': DATABASE_URL})

nest_asyncio.apply()

# === UTILITIES ===
def clean_uid(uid):
    return uid.replace('.', '_')

def load_user_history(uid):
    return db.reference(f'chat_memory/{clean_uid(uid)}').get() or []

def save_user_history(uid, data):
    db.reference(f'chat_memory/{clean_uid(uid)}').set(data)

def get_settings(uid):
    return db.reference(f'settings/{clean_uid(uid)}').get() or {}

def save_settings(uid, data):
    db.reference(f'settings/{clean_uid(uid)}').set(data)

def delete_user(uid):
    db.reference(f'chat_memory/{clean_uid(uid)}').delete()
    db.reference(f'settings/{clean_uid(uid)}').delete()

# === AI RESPONSE (async) ===
async def generate_response(prompt, memory=[]):
    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"}
    messages = [{"role": "system", "content": "You are a helpful assistant."}] + memory + [{"role": "user", "content": prompt}]
    data = {
        "model": "llama3-70b-8192",
        "messages": messages,
        "temperature": 0.7,
        "top_p": 1,
        "stream": False,
        "max_tokens": 1024
    }
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers, json=data) as resp:
                if resp.status != 200:
                    print("Groq API error:", await resp.text())
                    return "❌ AI is unavailable."
                result = await resp.json()
                return result['choices'][0]['message']['content']
    except Exception as e:
        print("Groq connection error:", str(e))
        return "❌ Connection error to AI."

# === ROUTES ===

@app.route("/")
def welcome():
    return render_template("welcome.html")

@app.route("/login")
def login():
    flow = Flow.from_client_config(
        json.loads(CLIENT_SECRET_JSON),
        scopes=["openid", "https://www.googleapis.com/auth/userinfo.email", "https://www.googleapis.com/auth/userinfo.profile"],
        redirect_uri=OAUTH_REDIRECT_URI  # 🔥 Use HTTPS callback
    )
    auth_url, state = flow.authorization_url(prompt='consent')
    session["state"] = state
    return redirect(auth_url)

@app.route("/oauth_callback")
def oauth_callback():
    flow = Flow.from_client_config(
        json.loads(CLIENT_SECRET_JSON),
        scopes=["openid", "https://www.googleapis.com/auth/userinfo.email", "https://www.googleapis.com/auth/userinfo.profile"],
        redirect_uri=OAUTH_REDIRECT_URI  # 🔥 Match login
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
    return redirect("/")

@app.route("/continue_as_guest", methods=["POST"])
def continue_as_guest():
    session.clear()
    session['guest'] = True
    return redirect("/chat")

@app.route("/chat", methods=["GET", "POST"])
def chat():
    uid = session.get("user_email", "guest")
    message = ""
    reply = ""
    tz = timezone(LOCAL_TIMEZONE)
    history = load_user_history(uid)
    settings = get_settings(uid)
    theme = settings.get("theme", "dark") if settings else "dark"

    if request.method == "POST":
        message = request.form["message"]
        now = datetime.now(tz).strftime("%I:%M %p")
        history.append({"role": "user", "content": message, "time": now})
        trimmed = [{"role": m["role"], "content": m["content"]} for m in history[-10:]]  # Last 10 messages only
        reply = asyncio.run(generate_response(message, trimmed))
        history.append({"role": "assistant", "content": reply, "time": now})
        save_user_history(uid, history)

    return render_template("chat.html", uid=uid, message=message, reply=reply, history=history, settings=settings, theme=theme)

@app.route("/conversations")
def conversations():
    uid = session.get("user_email", "guest")
    history = load_user_history(uid)
    settings = get_settings(uid)
    theme = settings.get("theme", "dark") if settings else "dark"
    return render_template("conversations.html", history=history, settings=settings, theme=theme)

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
    theme = settings.get("theme", "dark") if settings else "dark"
    return render_template("settings.html", settings=settings, theme=theme)

@app.route("/clear_and_restart", methods=["POST"])
def clear_and_restart():
    uid = session.get("user_email", "guest")
    if uid == "guest":
        session.pop('history', None)
    else:
        db.reference(f'chat_memory/{clean_uid(uid)}').delete()
    return redirect("/chat")

@app.route("/delete_account", methods=["POST"])
def delete_account():
    uid = session.get("user_email", "guest")
    delete_user(uid)
    session.clear()
    return redirect("/")

@app.route("/healthz")
def healthcheck():
    return "OK", 200

# === RUN ===
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080, debug=True)
