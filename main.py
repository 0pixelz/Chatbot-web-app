import os
import json
import asyncio
import aiohttp
import nest_asyncio
from flask import Flask, render_template, redirect, request, session, url_for
from firebase_admin import credentials, db, initialize_app
from datetime import datetime, timedelta
from pytz import timezone
from google_auth_oauthlib.flow import Flow
from google.oauth2 import id_token
from google.auth.transport import requests as grequests
import uuid
import re

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

# === Utilities ===
def clean_uid(uid): return uid.replace(".", "_")
def load_user_history(uid, convo_id): return db.reference(f"chat_memory/{clean_uid(uid)}/{convo_id}").get() or []
def save_user_history(uid, convo_id, data): db.reference(f"chat_memory/{clean_uid(uid)}/{convo_id}").set(data)
def list_conversations(uid): return db.reference(f"conversations/{clean_uid(uid)}").get() or {}
def save_conversation_title(uid, convo_id, title): db.reference(f"conversations/{clean_uid(uid)}/{convo_id}").update({"title": title})
def get_settings(uid): return db.reference(f"settings/{clean_uid(uid)}").get() or {}
def save_settings(uid, data): db.reference(f"settings/{clean_uid(uid)}").set(data)
def load_events(uid): return db.reference(f"events/{clean_uid(uid)}").get() or {}
def save_event(uid, event_id, event_data): db.reference(f"events/{clean_uid(uid)}/{event_id}").set(event_data)
def delete_event(uid, event_id): db.reference(f"events/{clean_uid(uid)}/{event_id}").delete()

# === AI Functions ===
async def generate_response(prompt, memory=[]):
    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"}
    messages = [{"role": "system", "content": "You're a helpful assistant."}] + memory + [{"role": "user", "content": prompt}]
    data = {"model": "llama3-70b-8192", "messages": messages}
    async with aiohttp.ClientSession() as session:
        async with session.post(url, headers=headers, json=data) as resp:
            result = await resp.json()
            return result['choices'][0]['message']['content']

async def generate_title_from_message(message):
    return await generate_response(f"Summarize this into a 3-word event title: {message}")

# === Natural Language Parsing ===
def extract_datetime_and_title(message):
    now = datetime.now(timezone(LOCAL_TIMEZONE))
    future_date = None
    time_match = re.search(r'at\s+(\d{1,2}(:\d{2})?\s*(am|pm)?)', message, re.IGNORECASE)
    date_match = re.search(r'\b(?:on\s+)?(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\s+\d{1,2}', message, re.IGNORECASE)
    in_days_match = re.search(r'in\s+(\d+)\s+(day|days)', message, re.IGNORECASE)

    if in_days_match:
        days = int(in_days_match.group(1))
        future_date = now + timedelta(days=days)
    elif date_match:
        try:
            parsed = datetime.strptime(f"{date_match.group(0)} {now.year}", "%b %d %Y")
            future_date = parsed
        except: pass

    event_time = ""
    if time_match:
        try:
            parsed = datetime.strptime(time_match.group(1), "%I:%M %p") if ":" in time_match.group(1) else datetime.strptime(time_match.group(1), "%I %p")
            event_time = parsed.strftime("%H:%M")
        except: pass

    all_day = not bool(event_time)
    date_str = future_date.strftime("%Y-%m-%d") if future_date else None
    return {"date": date_str, "time": event_time, "allDay": all_day}

# === Routes ===
@app.route("/")
def home(): return redirect("/chat")

@app.route("/login")
def login():
    flow = Flow.from_client_config(json.loads(CLIENT_SECRET_JSON),
        scopes=["openid", "https://www.googleapis.com/auth/userinfo.email", "https://www.googleapis.com/auth/userinfo.profile"],
        redirect_uri=url_for("oauth_callback", _external=True, _scheme="https"))
    auth_url, state = flow.authorization_url()
    session["state"] = state
    return redirect(auth_url)

@app.route("/oauth_callback")
def oauth_callback():
    flow = Flow.from_client_config(json.loads(CLIENT_SECRET_JSON),
        scopes=["openid", "https://www.googleapis.com/auth/userinfo.email", "https://www.googleapis.com/auth/userinfo.profile"],
        redirect_uri=url_for("oauth_callback", _external=True, _scheme="https"))
    flow.fetch_token(code=request.args["code"])
    creds = flow.credentials
    idinfo = id_token.verify_oauth2_token(creds._id_token, grequests.Request())
    session["user_email"] = idinfo["email"]
    session["user_picture"] = idinfo.get("picture")
    session["user_name"] = idinfo.get("name", idinfo["email"])
    return redirect("/chat")

@app.route("/logout", methods=["POST"])
def logout(): session.clear(); return redirect("/")

@app.route("/chat")
def chat_redirect(): return redirect("/start_new_chat")

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
    settings = get_settings(uid)
    conversations = list_conversations(uid) if uid != "guest" else {}
    history = load_user_history(uid, convo_id)

    if request.method == "POST":
        message = request.form["message"]
        now = datetime.now(tz).strftime("%I:%M %p")
        history.append({"role": "user", "content": message, "time": now})

        trimmed = [{"role": m["role"], "content": m["content"]} for m in history[-10:]]
        reply = asyncio.run(generate_response(message, trimmed))

        # Auto-calendar logic
        if uid != "guest" and ("remind me" in message.lower() or "add to calendar" in message.lower()):
            details = extract_datetime_and_title(message)
            if details["date"]:
                title = asyncio.run(generate_title_from_message(message)) or "Untitled Event"
                save_event(uid, str(uuid.uuid4()), {
                    "title": title,
                    "description": message,
                    "date": details["date"],
                    "time": details["time"],
                    "allDay": details["allDay"],
                    "repeat": "none",
                    "parentId": str(uuid.uuid4())
                })

        history.append({"role": "assistant", "content": reply, "time": now})
        save_user_history(uid, convo_id, history)

        if uid != "guest":
            current_title = db.reference(f"conversations/{clean_uid(uid)}/{convo_id}/title").get()
            if not current_title:
                title = asyncio.run(generate_title_from_message(message))
                save_conversation_title(uid, convo_id, title or message[:30] + "..." if len(message) > 30 else message)

        return redirect(f"/chat/{convo_id}")

    return render_template("chat.html", uid=uid, history=history, conversations=conversations, convo_id=convo_id, settings=settings)

@app.route("/delete_conversation/<convo_id>", methods=["POST"])
def delete_conversation(convo_id):
    uid = session.get("user_email", "guest")
    if uid != "guest":
        db.reference(f"chat_memory/{clean_uid(uid)}/{convo_id}").delete()
        db.reference(f"conversations/{clean_uid(uid)}/{convo_id}").delete()
    return redirect("/chat")

@app.route("/settings", methods=["GET", "POST"])
def settings_page():
    uid = session.get("user_email", "guest")
    if request.method == "POST":
        save_settings(uid, {
            "theme": request.form.get("theme", "dark"),
            "font_size": request.form.get("font_size", "base"),
            "personality": request.form.get("personality", ""),
            "length": request.form.get("length", "medium")
        })
        return redirect("/chat")
    return render_template("settings.html", settings=get_settings(uid))

@app.route("/calendar")
def calendar_page():
    uid = session.get("user_email")
    return render_template("calendar.html", events=load_events(uid) if uid else {})

@app.route("/save_event/<event_id>", methods=["POST"])
def save_event_route(event_id):
    uid = session.get("user_email")
    if not uid: return redirect("/chat")
    data = request.get_json()
    event_data = {
        "title": data["title"],
        "description": data.get("description", ""),
        "time": data.get("time", ""),
        "allDay": data.get("allDay", False),
        "repeat": data.get("repeat", "none"),
        "parentId": data.get("parentId", str(uuid.uuid4())),
        "date": data["date"]
    }
    save_event(uid, event_id, event_data)
    return "", 204

@app.route("/delete_event/<event_id>", methods=["POST"])
def delete_event_route(event_id):
    uid = session.get("user_email")
    if not uid: return redirect("/chat")
    event = db.reference(f"events/{clean_uid(uid)}/{event_id}").get()
    if event and "parentId" in event:
        for eid, evt in (db.reference(f"events/{clean_uid(uid)}").get() or {}).items():
            if evt.get("parentId") == event["parentId"]:
                delete_event(uid, eid)
    else:
        delete_event(uid, event_id)
    return "", 204

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
