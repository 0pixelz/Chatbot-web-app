# === FULL FINAL main.py (Groq fixed + All functional) ===

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

# === FLASK & FIREBASE INIT ===
app = Flask(__name__)
app.secret_key = FLASK_SECRET_KEY

cred = credentials.Certificate(json.loads(FIREBASE_CREDENTIALS_JSON))
initialize_app(cred, {'databaseURL': DATABASE_URL})

nest_asyncio.apply()  # 🔥 Needed for asyncio inside Flask!

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
            async with session.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers=headers,
                json=payload
            ) as resp:
                result = await resp.json()
                if 'choices' not in result:
                    print("Groq API Error:", result)  # Print error
                    return "I'm thinking... Please try again later!"
                return result['choices'][0]['message']['content']

    return asyncio.run(call_groq())

# === ROUTES ===

@app.route('/')
def welcome():
    theme = session.get('theme', 'dark')
    return render_template('welcome.html', theme=theme)

@app.route('/chat', methods=['GET', 'POST'])
def chat():
    theme = session.get('theme', 'dark')
    user_id = session.get('user_id')
    is_guest = session.get('guest', False)

    if user_id and not is_guest:
        history = load_user_history(user_id)
    else:
        history = session.get('history', [])

    if request.method == 'POST':
        message = request.form.get('message')
        if message:
            history.append({'role': 'user', 'content': message})
            ai_reply = generate_ai_response(message)
            history.append({'role': 'assistant', 'content': ai_reply})

        if user_id and not is_guest:
            save_user_history(user_id, history)
        else:
            session['history'] = history

        return redirect(url_for('chat'))

    return render_template('chat.html', theme=theme, history=history)

@app.route('/conversations')
def conversations():
    theme = session.get('theme', 'dark')
    user_id = session.get('user_id')
    if not user_id:
        return redirect(url_for('welcome'))

    history = load_user_history(user_id)
    return render_template('conversations.html', theme=theme, history=history)

@app.route('/settings', methods=['GET', 'POST'])
def settings():
    user_id = session.get('user_id')
    theme = session.get('theme', 'dark')

    if request.method == 'POST':
        selected_theme = request.form.get('theme')
        font_size = request.form.get('font_size')
        personality = request.form.get('personality')

        if selected_theme:
            session['theme'] = selected_theme
            session.permanent = True

        if user_id:
            settings_data = {
                'theme': selected_theme,
                'font_size': font_size,
                'personality': personality
            }
            save_settings(user_id, settings_data)

        return redirect(url_for('settings'))

    return render_template('settings.html', theme=theme)

@app.route('/login')
def login_prompt():
    theme = session.get('theme', 'dark')

    flow = Flow.from_client_config(
        json.loads(CLIENT_SECRET_JSON),
        scopes=['https://www.googleapis.com/auth/userinfo.email', 'openid'],
        redirect_uri=url_for('callback', _external=True)
    )
    auth_url, _ = flow.authorization_url(prompt='consent')
    return redirect(auth_url)

@app.route('/login/callback')
def callback():
    flow = Flow.from_client_config(
        json.loads(CLIENT_SECRET_JSON),
        scopes=['https://www.googleapis.com/auth/userinfo.email', 'openid'],
        redirect_uri=url_for('callback', _external=True)
    )

    flow.fetch_token(authorization_response=request.url)

    credentials = flow.credentials
    request_session = grequests.Request()
    id_info = id_token.verify_oauth2_token(credentials._id_token, request_session)

    email = id_info.get('email')
    if email:
        session['user_id'] = clean_uid(email)
        session['guest'] = False
        return redirect(url_for('chat'))

    return redirect(url_for('welcome'))

@app.route('/logout', methods=['POST'])
def logout():
    session.clear()
    return redirect(url_for('welcome'))

@app.route('/continue_as_guest', methods=['POST'])
def continue_as_guest():
    session.clear()
    session['guest'] = True
    return redirect(url_for('chat'))

# === Health Check for Render ===
@app.route('/healthz')
def healthcheck():
    return 'OK', 200

# === RUN ===
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080, debug=True)
