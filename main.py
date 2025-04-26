# === FULL FINAL main.py (Real chatbot fully restored) ===

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

# === FLASK & FIREBASE INIT ===
app = Flask(__name__)
app.secret_key = FLASK_SECRET_KEY

cred = credentials.Certificate(json.loads(FIREBASE_CREDENTIALS_JSON))
initialize_app(cred, {'databaseURL': DATABASE_URL})

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

def generate_ai_response(prompt):
    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json"
    }
    payload = {
        "messages": [{"role": "user", "content": prompt}],
        "model": "mixtral-8x7b-32768"
    }
    async def call_groq():
        async with aiohttp.ClientSession() as session:
            async with session.post("https://api.groq.com/openai/v1/chat/completions", headers=headers, json=payload) as resp:
                result = await resp.json()
                return result['choices'][0]['message']['content']
    loop = asyncio.get_event_loop()
    return loop.run_until_complete(call_groq())

# === ROUTES ===
@app.route('/')
def welcome():
    theme = session.get('theme', 'dark')
    return render_template('welcome.html', theme=theme)

@app.route('/chat', methods=['GET', 'POST'])
def chat():
    theme = session.get('theme', 'dark')
    user_id = session.get('user_email')
    history = []

    if user_id:
        history = load_user_history(user_id)
    else:
        history = session.get('history', [])

    if request.method == 'POST':
        message = request.form.get('message')
        if message:
            history.append({'role': 'user', 'content': message})
            ai_reply = generate_ai_response(message)
            history.append({'role': 'assistant', 'content': ai_reply})

            if user_id:
                save_user_history(user_id, history)
            else:
                session['history'] = history

        return redirect(url_for('chat'))

    return render_template('chat.html', theme=theme, history=history)

@app.route('/conversations')
def conversations():
    theme = session.get('theme', 'dark')
    user_id = session.get('user_email')
    history = []

    if user_id:
        history = load_user_history(user_id)
    return render_template('conversations.html', theme=theme, history=history)

@app.route('/settings', methods=['GET', 'POST'])
def settings():
    user_id = session.get('user_email')

    if request.method == 'POST':
        selected_theme = request.form.get('theme')
        if selected_theme:
            session['theme'] = selected_theme
        if user_id:
            save_settings(user_id, {"theme": selected_theme})
        session.permanent = True
        return redirect(url_for('settings'))

    theme = session.get('theme', 'dark')
    return render_template('settings.html', theme=theme)

@app.route('/continue_as_guest', methods=['POST'])
def continue_as_guest():
    return redirect(url_for('chat'))

@app.route('/login')
def login():
    flow = Flow.from_client_config(
        json.loads(CLIENT_SECRET_JSON),
        scopes=["openid", "email", "profile"],
        redirect_uri=url_for('callback', _external=True)
    )
    auth_url, _ = flow.authorization_url(prompt='consent')
    return redirect(auth_url)

@app.route('/login/callback')
def callback():
    flow = Flow.from_client_config(
        json.loads(CLIENT_SECRET_JSON),
        scopes=["openid", "email", "profile"],
        redirect_uri=url_for('callback', _external=True)
    )
    flow.fetch_token(authorization_response=request.url)

    credentials = flow.credentials
    request_session = grequests.Request()
    id_info = id_token.verify_oauth2_token(credentials._id_token, request_session)

    session['user_email'] = id_info.get('email')
    session['theme'] = get_settings(session['user_email']).get('theme', 'dark')
    return redirect(url_for('chat'))

@app.route('/logout', methods=['POST'])
def logout():
    session.clear()
    return redirect(url_for('welcome'))

@app.route('/healthz')
def healthcheck():
    return 'OK', 200

# === RUN ===
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080, debug=True)
