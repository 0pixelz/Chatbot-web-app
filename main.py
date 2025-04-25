from flask import Flask, request, render_template, redirect, session, url_for
import asyncio, aiohttp, os
from firebase_admin import credentials, db, initialize_app
from datetime import datetime
from pytz import timezone
from google_auth_oauthlib.flow import Flow
from google.oauth2 import id_token
from google.auth.transport import requests as grequests
import nest_asyncio
import re

GROQ_API_KEY = 'your_groq_api_key_here'
FIREBASE_JSON = 'opixelz-dgqoph-firebase-adminsdk-zxxqz-4d576b374a.json'
DATABASE_URL = 'https://opixelz-dgqoph.firebaseio.com/'
LOCAL_TIMEZONE = 'America/Toronto'
CLIENT_SECRET_FILE = 'your_google_client_secret_file.json'

app = Flask(__name__)
app.secret_key = "supersecret"
cred = credentials.Certificate(FIREBASE_JSON)
initialize_app(cred, {'databaseURL': DATABASE_URL})

def clean_uid(uid):
    return re.sub(r'[.#$/]', '_', uid)

def load_user_history(uid):
    return db.reference(f'chat_memory/{clean_uid(uid)}').get() or []

def save_user_history(uid, data):
    db.reference(f'chat_memory/{clean_uid(uid)}').set(data)

def load_user_settings(uid):
    return db.reference(f'user_settings/{clean_uid(uid)}').get() or {}

def save_user_settings(uid, settings):
    db.reference(f'user_settings/{clean_uid(uid)}').set(settings)

def delete_user(uid):
    db.reference(f'chat_memory/{clean_uid(uid)}').delete()
    db.reference(f'user_settings/{clean_uid(uid)}').delete()

async def generate_response(prompt, memory=[]):
    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"}
    messages = [{"role": "system", "content": "You're a helpful assistant."}] + memory + [{"role": "user", "content": prompt}]
    data = {"model": "llama3-70b-8192", "messages": messages}
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers, json=data) as resp:
                result = await resp.json()
                return result['choices'][0]['message']['content']
    except Exception as e:
        return f"❌ Groq error: {str(e)}"

@app.route("/")
def index():
    return redirect("/chat")

@app.route("/login")
def login():
    flow = Flow.from_client_secrets_file(
        CLIENT_SECRET_FILE,
        scopes=['openid', 'https://www.googleapis.com/auth/userinfo.email', 'https://www.googleapis.com/auth/userinfo.profile'],
        redirect_uri=url_for('oauth_callback', _external=True)
    )
    auth_url, state = flow.authorization_url()
    session["state"] = state
    return redirect(auth_url)

@app.route("/logout")
def logout():
    session.clear()
    return redirect("/chat")

@app.route("/oauth_callback")
def oauth_callback():
    flow = Flow.from_client_secrets_file(
        CLIENT_SECRET_FILE,
        scopes=['openid', 'https://www.googleapis.com/auth/userinfo.email', 'https://www.googleapis.com/auth/userinfo.profile'],
        redirect_uri=url_for('oauth_callback', _external=True)
    )
    flow.fetch_token(code=request.args['code'])
    credentials = flow.credentials
    request_session = grequests.Request()
    idinfo = id_token.verify_oauth2_token(credentials._id_token, request_session)
    session["user_email"] = idinfo["email"]
    session["user_picture"] = idinfo.get("picture")
    return redirect("/chat")

@app.route("/chat", methods=["GET", "POST"])
def chat():
    uid = session.get("user_email", "guest")
    tz = timezone(LOCAL_TIMEZONE)
    history = load_user_history(uid)
    message, reply = "", ""
    if request.method == "POST":
        message = request.form["message"]
        now = datetime.now(tz).strftime("%I:%M %p")
        history.append({"role": "user", "content": message, "time": now})
        trimmed = [{"role": m["role"], "content": m["content"]} for m in history[-10:]]
        reply = asyncio.run(generate_response(message, trimmed))
        history.append({"role": "assistant", "content": reply, "time": now})
        save_user_history(uid, history)
    return render_template("chat.html", uid=uid, message=message, reply=reply, history=history)

@app.route("/clear", methods=["POST"])
def clear():
    uid = session.get("user_email", "guest")
    db.reference(f'chat_memory/{clean_uid(uid)}').delete()
    return '', 204

@app.route("/settings", methods=["GET", "POST"])
def settings():
    uid = session.get("user_email", "guest")
    settings = load_user_settings(uid)
    if request.method == "POST":
        settings = {
            "appearance": request.form.get("appearance", ""),
            "font_size": request.form.get("font_size", ""),
            "personality": request.form.get("personality", ""),
            "response_length": request.form.get("response_length", "")
        }
        save_user_settings(uid, settings)
        return redirect("/settings")
    return render_template("settings.html", uid=uid, settings=settings)

@app.route("/delete_account", methods=["POST"])
def delete_account():
    uid = session.get("user_email", "guest")
    delete_user(uid)
    session.clear()
    return redirect("/chat")

if __name__ == "__main__":
    nest_asyncio.apply()
    app.run(host="0.0.0.0", port=8080)
