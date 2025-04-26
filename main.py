# === FULL main.py (FINAL corrected with working theme switching) ===

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

# === ROUTES ===

@app.route('/')
def welcome():
    theme = session.get('theme', 'dark')
    return render_template('welcome.html', theme=theme)

@app.route('/chat')
def chat():
    theme = session.get('theme', 'dark')
    return render_template('chat.html', theme=theme)

@app.route('/conversations')
def conversations():
    theme = session.get('theme', 'dark')
    return render_template('conversations.html', theme=theme)

@app.route('/settings', methods=['GET', 'POST'])
def settings():
    if request.method == 'POST':
        selected_theme = request.form.get('theme')
        print("Selected theme:", selected_theme)  # Debugging print
        if selected_theme:
            session['theme'] = selected_theme
            session.permanent = True  # 🔥 Keep the theme in session across page reloads
            print("Theme now saved in session:", session.get('theme'))
        return redirect(url_for('settings'))

    theme = session.get('theme', 'dark')
    print("Rendering settings page with theme:", theme)  # Debugging print
    return render_template('settings.html', theme=theme)

@app.route('/login')
def login_prompt():
    theme = session.get('theme', 'dark')
    return render_template('login_prompt.html', theme=theme)

# === YOUR OTHER LOGIC (AI, REMINDERS, GMAIL, ETC.) ===
# Keep all your existing AI chat handlers, /connectgmail routes, webhook listeners, self-ping functions etc here.
# No changes needed for those to support the theme fix!

# === RUN ===
if __name__ == '__main__':
    app.run(debug=True, port=8080)
