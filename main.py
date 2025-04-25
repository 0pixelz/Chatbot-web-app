from flask import Flask, request, render_template, redirect, session, url_for
import asyncio, aiohttp, os, json, tempfile
from firebase_admin import credentials, db, initialize_app
from datetime import datetime
from pytz import timezone
from google_auth_oauthlib.flow import Flow
from google.oauth2 import id_token
from google.auth.transport import requests as grequests
import nest_asyncio

# === CONFIG ===
GROQ_API_KEY = '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'
DATABASE_URL = 'https://opixelz-dgqoph.firebaseio.com/'
LOCAL_TIMEZONE = 'America/Toronto'
CLIENT_SECRET_FILE = 'client_secret_475746497039-4ofjje6ds8jr30jr9d2eb3crr0529j81.apps.googleusercontent.com.json'

# === FLASK & FIREBASE ===
app = Flask(__name__)
app.secret_key = "supersecret"

# Load Firebase credentials from ENV variable
firebase_json_raw = os.environ.get("FIREBASE_CREDENTIALS_JSON")
firebase_json_dict = json.loads(firebase_json_raw)
with tempfile.NamedTemporaryFile(mode='w+', delete=False) as temp_file:
    json.dump(firebase_json_dict, temp_file)
    temp_file.flush()
    cred = credentials.Certificate(temp_file.name)

initialize_app(cred, {'databaseURL': DATABASE_URL})

# === DB UTILS ===
def clean_uid(uid): return uid.replace('.', '_')
def load_user_history(uid): return db.reference(f'chat_memory/{clean_uid(uid)}').get() or []
def save_user_history(uid, data): db.reference(f'chat_memory/{clean_uid(uid)}').set(data)
def get_settings(uid): return db.reference(f'settings/{clean_uid(uid)}').get() or {}
def save_settings(uid, data): db.reference(f'settings/{clean_uid(uid)}').set(data)
def delete_user(uid): db.reference(f'chat_memory/{clean_uid(uid)}').delete(); db.reference(f'settings/{clean_uid(uid)}').delete()

# === AI ===
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

@app.route("/logout", methods=["POST"])
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
    message, reply = "", ""
    tz = timezone(LOCAL_TIMEZONE)
    history = load_user_history(uid)
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
    if request.method == "POST":
        data = {
            "theme": request.form.get("theme", "dark"),
            "font_size": request.form.get("font_size", "base"),
            "personality": request.form.get("personality", ""),
            "length": request.form.get("length", "medium")
        }
        save_settings(uid, data)
        return redirect("/settings")
    settings = get_settings(uid)
    return render_template("settings.html", settings=settings)

@app.route("/delete_account", methods=["POST"])
def delete_account():
    uid = session.get("user_email", "guest")
    delete_user(uid)
    session.clear()
    return redirect("/")

# === RUN ===
if __name__ == "__main__":
    nest_asyncio.apply()
    app.run(host="0.0.0.0", port=8080)
