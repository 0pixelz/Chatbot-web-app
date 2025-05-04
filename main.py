import os
import json
import asyncio
import aiohttp
import nest_asyncio
from flask import Flask, render_template, redirect, request, session, url_for, flash
from firebase_admin import credentials, db, initialize_app
from datetime import datetime
from pytz import timezone
from google_auth_oauthlib.flow import Flow
from google.oauth2 import id_token
from google.auth.transport import requests as grequests
import uuid
import re
from dateutil import parser as dateparser

# === CONFIG ===
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
FIREBASE_CREDENTIALS_JSON = os.getenv("FIREBASE_CREDENTIALS_JSON")
DATABASE_URL = os.getenv("DATABASE_URL")
CLIENT_SECRET_JSON = os.getenv("GOOGLE_CLIENT_SECRET_JSON")
LOCAL_TIMEZONE = os.getenv("LOCAL_TIMEZONE", "America/Toronto")
FLASK_SECRET_KEY = os.getenv("FLASK_SECRET_KEY")

# === INIT ===
app = Flask(__name__)
app.secret_key = FLASK_SECRET_KEY

cred = credentials.Certificate(json.loads(FIREBASE_CREDENTIALS_JSON))
initialize_app(cred, {"databaseURL": DATABASE_URL})
nest_asyncio.apply()

# === UTILITIES ===

def clean_uid(uid):
    return uid.replace(".", "_")

def sanitize(text):
    return text.strip().strip('"').strip("'") if text else ""

def load_user_history(uid, convo_id):
    return db.reference(f"chat_memory/{clean_uid(uid)}/{convo_id}").get() or []

def save_user_history(uid, convo_id, data):
    db.reference(f"chat_memory/{clean_uid(uid)}/{convo_id}").set(data)

def list_conversations(uid):
    return db.reference(f"conversations/{clean_uid(uid)}").get() or {}

def save_conversation_title(uid, convo_id, title):
    db.reference(f"conversations/{clean_uid(uid)}/{convo_id}").update({"title": title})

def get_settings(uid):
    return db.reference(f"settings/{clean_uid(uid)}").get() or {}

def load_events(uid):
    return db.reference(f"events/{clean_uid(uid)}").get() or {}

def save_event(uid, event_id, event_data):
    db.reference(f"events/{clean_uid(uid)}/{event_id}").set(event_data)

def delete_event(uid, event_id):
    db.reference(f"events/{clean_uid(uid)}/{event_id}").delete()

# === AI FUNCTION ===

async def generate_ai(prompt):
    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"}
    data = {
        "model": "llama3-70b-8192",
        "messages": [
            {"role": "system", "content": "You are a calendar assistant. Extract event info like Title, Date, Description when user says 'add to calendar' or 'remind me'. Format: Title: ..., Date: ..., Description: ..."},
            {"role": "user", "content": prompt}
        ]
    }
    async with aiohttp.ClientSession() as session:
        async with session.post(url, headers=headers, json=data) as resp:
            result = await resp.json()
            return result['choices'][0]['message']['content'].strip()

def extract_event(ai_response):
    title = re.search(r"Title:\s*(.*)", ai_response, re.IGNORECASE)
    date = re.search(r"Date:\s*(.*)", ai_response, re.IGNORECASE)
    desc = re.search(r"Description:\s*(.*)", ai_response, re.IGNORECASE)
    return (
        title.group(1).strip() if title else "",
        date.group(1).strip() if date else "",
        desc.group(1).strip() if desc else ""
    )

def parse_date(date_text):
    try:
        dt = dateparser.parse(date_text, fuzzy=True)
        if dt.year == 1900:
            dt = dt.replace(year=datetime.now().year)
        return dt.strftime("%Y-%m-%d")
    except:
        return None

# === ROUTES ===

@app.route("/")
def home():
    return redirect("/chat")

@app.route("/login")
def login():
    flow = Flow.from_client_config(
        json.loads(CLIENT_SECRET_JSON),
        scopes=["openid", "https://www.googleapis.com/auth/userinfo.email", "https://www.googleapis.com/auth/userinfo.profile"],
        redirect_uri=url_for("oauth_callback", _external=True, _scheme="https")
    )
    auth_url, state = flow.authorization_url()
    session["state"] = state
    return redirect(auth_url)

@app.route("/oauth_callback")
def oauth_callback():
    flow = Flow.from_client_config(
        json.loads(CLIENT_SECRET_JSON),
        scopes=["openid", "https://www.googleapis.com/auth/userinfo.email", "https://www.googleapis.com/auth/userinfo.profile"],
        redirect_uri=url_for("oauth_callback", _external=True, _scheme="https")
    )
    flow.fetch_token(code=request.args["code"])
    creds = flow.credentials
    idinfo = id_token.verify_oauth2_token(creds._id_token, grequests.Request())
    session["user_email"] = idinfo["email"]
    session["user_picture"] = idinfo.get("picture")
    session["user_name"] = idinfo.get("name", idinfo["email"])
    return redirect("/chat")

@app.route("/logout", methods=["POST", "GET"])
def logout():
    session.clear()
    return render_template("logged_out.html")

@app.route("/chat")
def chat_redirect():
    return redirect("/start_new_chat")

@app.route("/start_new_chat")
def start_new_chat():
    convo_id = str(uuid.uuid4())
    uid = session.get("user_email", "guest")
    if uid != "guest":
        db.reference(f"conversations/{clean_uid(uid)}/{convo_id}").set({"title": None})
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

        reply = asyncio.run(generate_ai(message))

        title, date_text, description = extract_event(reply)
        event_date = parse_date(date_text)

        if title and event_date:
            event_id = str(uuid.uuid4())
            save_event(uid, event_id, {
                "title": sanitize(title),
                "description": sanitize(description),
                "time": "",
                "allDay": True,
                "repeat": "none",
                "parentId": event_id,
                "date": event_date
            })

        history.append({"role": "assistant", "content": reply, "time": now})
        save_user_history(uid, convo_id, history)

        if uid != "guest":
            current_title = db.reference(f"conversations/{clean_uid(uid)}/{convo_id}/title").get()
            if not current_title:
                save_conversation_title(uid, convo_id, message[:30] + "..." if len(message) > 30 else message)

        return redirect(f"/chat/{convo_id}")

    return render_template("chat.html", uid=uid, history=history, conversations=conversations, convo_id=convo_id, settings=settings)

@app.route("/delete_conversation/<convo_id>", methods=["POST"])
def delete_conversation(convo_id):
    uid = session.get("user_email")
    if not uid:
        return "Unauthorized", 401
    db.reference(f"conversations/{clean_uid(uid)}/{convo_id}").delete()
    db.reference(f"chat_memory/{clean_uid(uid)}/{convo_id}").delete()
    return redirect("/chat?sidebar=open")

@app.route("/calendar")
def calendar_page():
    uid = session.get("user_email")
    if not uid:
        return redirect("/chat")
    return render_template("calendar.html", events=load_events(uid), uid=uid)

@app.route("/save_event/<event_id>", methods=["POST"])
def save_event_route(event_id):
    uid = session.get("user_email")
    if not uid:
        return "Unauthorized", 401
    data = request.get_json()
    if not data:
        return "No data", 400
    save_event(uid, event_id, {
        "title": sanitize(data.get("title", "")),
        "description": sanitize(data.get("description", "")),
        "date": data.get("date"),
        "time": data.get("time", ""),
        "allDay": data.get("allDay", True),
        "repeat": data.get("repeat", "none"),
        "parentId": data.get("parentId") or event_id
    })
    return "Saved", 200

@app.route("/delete_event/<event_id>", methods=["POST"])
def delete_event_route(event_id):
    uid = session.get("user_email")
    if not uid:
        return "Unauthorized", 401
    delete_event(uid, event_id)
    return "Deleted", 200

@app.route("/settings", methods=["GET", "POST"])
def settings_page():
    uid = session.get("user_email", "guest")
    if request.method == "POST":
        db.reference(f"settings/{clean_uid(uid)}").set({
            "theme": request.form.get("theme"),
            "font_size": request.form.get("font_size"),
            "personality": request.form.get("personality"),
            "length": request.form.get("length")
        })
        flash("Settings saved!")
        return redirect("/settings")
    return render_template("settings.html", settings=get_settings(uid))

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
