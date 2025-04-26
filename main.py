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
import uuid

# === CONFIG FROM ENV ===
GROQ_API_KEY               = os.getenv("GROQ_API_KEY")
FIREBASE_CREDENTIALS_JSON  = os.getenv("FIREBASE_CREDENTIALS_JSON")
DATABASE_URL               = os.getenv("DATABASE_URL")
LOCAL_TIMEZONE             = os.getenv("LOCAL_TIMEZONE", "America/Toronto")
CLIENT_SECRET_JSON         = os.getenv("GOOGLE_CLIENT_SECRET_JSON")
FLASK_SECRET_KEY           = os.getenv("FLASK_SECRET_KEY")

print("DATABASE_URL from ENV:", DATABASE_URL)

# Validate presence of critical env vars
missing = [k for k,v in {
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

def user_ref(uid): 
    return db.reference(f'users/{clean_uid(uid)}')

def create_new_conversation(uid):
    cid = str(uuid.uuid4())
    convo = {
        "title": "New Conversation",
        "created_at": datetime.now(timezone(LOCAL_TIMEZONE)).strftime("%Y-%m-%d %H:%M:%S"),
        "messages": []
    }
    user_ref(uid).child("conversations").child(cid).set(convo)
    return cid

def list_chats(uid):
    ref = user_ref(uid).child("conversations").get()
    return ref if ref else {}

def load_conversation(uid, cid):
    data = user_ref(uid).child(f"conversations/{cid}/messages").get()
    return data if data else []

def save_conversation(uid, cid, messages):
    user_ref(uid).child(f"conversations/{cid}/messages").set(messages)

async def generate_response(prompt, memory=[]):
    url     = "https://api.groq.com/openai/v1/chat/completions"
    headers = {"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"}
    messages = [{"role": "system", "content": "You're a helpful assistant."}] + memory + [{"role": "user", "content": prompt}]
    data    = {"model": "llama3-70b-8192", "messages": messages}
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
        redirect_uri=url_for("oauth_callback", _external=True)
    )
    auth_url, state = flow.authorization_url()
    session["state"] = state
    return redirect(auth_url)

@app.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return redirect("/chat")

@app.route("/oauth_callback")
def oauth_callback():
    flow = Flow.from_client_config(
        json.loads(CLIENT_SECRET_JSON),
        scopes=[
            "openid",
            "https://www.googleapis.com/auth/userinfo.email",
            "https://www.googleapis.com/auth/userinfo.profile"
        ],
        redirect_uri=url_for("oauth_callback", _external=True)
    )
    flow.fetch_token(code=request.args["code"])
    creds           = flow.credentials
    request_session = grequests.Request()
    idinfo          = id_token.verify_oauth2_token(creds._id_token, request_session)
    session["user_email"]   = idinfo["email"]
    session["user_picture"] = idinfo.get("picture")
    session["user_name"]    = idinfo.get("name", idinfo["email"])
    return redirect("/chat")

@app.route("/chat", methods=["GET", "POST"])
def chat():
    uid = session.get("user_email", None)
    if not uid:
        return render_template("welcome.html")  # New user page if not logged in

    conversation_id = request.args.get("conversation")

    if not conversation_id:
        # Auto-create first conversation
        conversation_id = create_new_conversation(uid)
        return redirect(f"/chat?conversation={conversation_id}")

    history = load_conversation(uid, conversation_id)
    tz      = timezone(LOCAL_TIMEZONE)
    message, reply = "", ""

    if request.method == "POST":
        message = request.form["message"]
        now = datetime.now(tz).strftime("%I:%M %p")
        history.append({"role": "user", "content": message, "time": now})
        trimmed = [{"role": m["role"], "content": m["content"]} for m in history[-10:]]
        reply   = asyncio.run(generate_response(message, trimmed))
        history.append({"role": "assistant", "content": reply, "time": now})
        save_conversation(uid, conversation_id, history)

    return render_template("chat.html", uid=uid, message=message, reply=reply, history=history, chats=list_chats(uid), current_conversation=conversation_id)

@app.route("/conversations")
def conversations():
    uid = session.get("user_email", None)
    if not uid:
        return redirect("/chat")
    conversations = list_chats(uid)
    return render_template("conversations.html", conversations=conversations)

@app.route("/new_conversation", methods=["POST"])
def new_conversation():
    uid = session.get("user_email", None)
    if not uid:
        return redirect("/chat")
    cid = create_new_conversation(uid)
    return redirect(f"/chat?conversation={cid}")

@app.route("/clear", methods=["POST"])
def clear():
    uid = session.get("user_email", None)
    if uid:
        db.reference(f'users/{clean_uid(uid)}/conversations').delete()
    return '', 204

@app.route("/settings", methods=["GET", "POST"])
def settings():
    uid = session.get("user_email", None)
    if not uid:
        return redirect("/chat")
    if request.method == "POST":
        data = {
            "theme":       request.form.get("theme", "dark"),
            "font_size":   request.form.get("font_size", "base"),
            "personality": request.form.get("personality", ""),
            "length":      request.form.get("length", "medium")
        }
        user_ref(uid).child("settings").set(data)
        return redirect("/settings")
    settings = user_ref(uid).child("settings").get() or {}
    return render_template("settings.html", settings=settings)

@app.route("/delete_account", methods=["POST"])
def delete_account():
    uid = session.get("user_email", None)
    if uid:
        user_ref(uid).delete()
        session.clear()
    return redirect("/")

# === RUN ===
if __name__ == "__main__":
    nest_asyncio.apply()
    app.run(host="0.0.0.0", port=8080)
