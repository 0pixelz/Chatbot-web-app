
from flask import Flask, request, render_template
import asyncio, aiohttp, threading
from firebase_admin import credentials, db, initialize_app
from datetime import datetime
from pytz import timezone, utc
import nest_asyncio

# === CONFIG ===
GROQ_API_KEY = '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'
FIREBASE_JSON = 'opixelz-dgqoph-firebase-adminsdk-zxxqz-4770fd3f5a.json'
DATABASE_URL = 'https://opixelz-dgqoph.firebaseio.com/'
LOCAL_TIMEZONE = 'America/Toronto'

cred = credentials.Certificate(FIREBASE_JSON)
initialize_app(cred, {'databaseURL': DATABASE_URL})
def load_user_context(uid): return db.reference(f'chat_context/{uid}').get() or []
def save_user_context(uid, data): db.reference(f'chat_context/{uid}').set(data)

# === AI ===
async def generate_response(prompt, memory=[]):
    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"}
    messages = [{"role": "system", "content": "You're a helpful assistant."}] +                [{"role": "user", "content": m} for m in memory[-5:]] +                [{"role": "user", "content": prompt}]
    data = {"model": "llama3-70b-8192", "messages": messages}

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers, json=data) as resp:
                print("[Groq status]", resp.status)
                result = await resp.json()
                print("[Groq body]", result)
                return result.get("choices", [{}])[0].get("message", {}).get("content", "⚠️ AI: no reply received.")
    except Exception as e:
        print("[Groq error]", e)
        return "❌ Error generating response."

# === FLASK ===
app = Flask(__name__)

@app.route("/")
def index():
    return "✅ Bot is live"

@app.route("/chat", methods=["GET", "POST"])
def chat():
    uid, message, reply, time = "", "", "", ""
    if request.method == "POST":
        uid = request.form["uid"]
        message = request.form["message"]
        memory = load_user_context(uid)
        memory.append(message)
        save_user_context(uid, memory)
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        reply = loop.run_until_complete(generate_response(message, memory))
        time = datetime.now().strftime("%I:%M %p")
    return render_template("chat.html", uid=uid, message=message, reply=reply, time=time)

if __name__ == "__main__":
    nest_asyncio.apply()
    threading.Thread(target=lambda: app.run(host="0.0.0.0", port=8080)).start()
