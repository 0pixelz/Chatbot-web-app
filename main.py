
from flask import Flask, request, render_template
import asyncio, aiohttp, threading
from firebase_admin import credentials, db, initialize_app
from datetime import datetime
from pytz import timezone, utc
import nest_asyncio

GROQ_API_KEY = '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'
FIREBASE_JSON = 'opixelz-dgqoph-firebase-adminsdk-zxxqz-4770fd3f5a.json'
DATABASE_URL = 'https://opixelz-dgqoph.firebaseio.com/'
LOCAL_TIMEZONE = 'America/Toronto'

cred = credentials.Certificate(FIREBASE_JSON)
initialize_app(cred, {'databaseURL': DATABASE_URL})
def load_user_history(uid): return db.reference(f'chat_memory/{uid}').get() or []
def save_user_history(uid, data): db.reference(f'chat_memory/{uid}').set(data)

async def generate_response(prompt, memory=[]):
    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"}
    messages = [{"role": "system", "content": "You're a helpful assistant."}] + memory + [{"role": "user", "content": prompt}]
    data = {"model": "llama3-70b-8192", "messages": messages}
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers, json=data) as resp:
                text = await resp.text()
                if resp.status != 200:
                    return f"❌ Groq API error {resp.status}: {text}"
                result = await resp.json()
                return result['choices'][0]['message']['content']
    except Exception as e:
        return f"❌ Groq connection error: {str(e)}"

app = Flask(__name__)

@app.route("/")
def index():
    return "✅ Bot is live"

@app.route("/chat", methods=["GET", "POST"])
def chat():
    uid, message, reply = "", "", ""
    tz = timezone(LOCAL_TIMEZONE)
    history = []
    if request.method == "POST":
        uid = request.form["uid"]
        message = request.form["message"]
        history = load_user_history(uid)
        now = datetime.now(tz).strftime("%I:%M %p")
        history.append({"role": "user", "content": message, "time": now})
        trimmed = [{"role": m["role"], "content": m["content"]} for m in history[-10:]]
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        reply = loop.run_until_complete(generate_response(message, trimmed))
        history.append({"role": "assistant", "content": reply, "time": now})
        save_user_history(uid, history)
    return render_template("chat.html", uid=uid, message=message, reply=reply, history=history)

if __name__ == "__main__":
    nest_asyncio.apply()
    threading.Thread(target=lambda: app.run(host="0.0.0.0", port=8080)).start()
