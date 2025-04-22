# === IMPORTS ===
import asyncio, aiohttp, re, threading
from flask import Flask, request, render_template_string
from datetime import datetime, timedelta
from pytz import timezone, utc
from firebase_admin import credentials, db, initialize_app
import nest_asyncio

# === CONFIG ===
GROQ_API_KEY = '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'
FIREBASE_JSON = 'opixelz-dgqoph-firebase-adminsdk-zxxqz-4770fd3f5a.json'
DATABASE_URL = 'https://opixelz-dgqoph.firebaseio.com/'
LOCAL_TIMEZONE = 'America/Toronto'

# === FIREBASE ===
cred = credentials.Certificate(FIREBASE_JSON)
initialize_app(cred, {'databaseURL': DATABASE_URL})
def load_user_reminders(uid): return db.reference(f'reminders/{uid}').get() or []
def save_user_reminders(uid, data): db.reference(f'reminders/{uid}').set(data)
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
                result = await resp.json()
                return result['choices'][0]['message']['content']
    except Exception as e:
        print(f"[Groq error] {e}")
        return "Error generating response."

# === TIME UTILS ===
DAY_MAP = {"monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
    "friday": 4, "saturday": 5, "sunday": 6,
    "lundi": 0, "mardi": 1, "mercredi": 2, "jeudi": 3,
    "vendredi": 4, "samedi": 5, "dimanche": 6}

def next_weekday_time(day, hour, minute):
    now = datetime.now(timezone(LOCAL_TIMEZONE))
    d = day.lower()
    if d in ["everyday", "every day", "chaque jour", "jour", "day"]:
        return now.replace(hour=hour, minute=minute, second=0, microsecond=0).astimezone(utc) + timedelta(days=1)
    if d in ["weekday", "weekdays", "chaque jour de semaine"]:
        while now.weekday() >= 5 or (now.hour, now.minute) >= (hour, minute): now += timedelta(days=1)
    elif d in ["weekend", "fin de semaine", "chaque fin de semaine"]:
        while now.weekday() < 5 or (now.hour, now.minute) >= (hour, minute): now += timedelta(days=1)
    else:
        target = DAY_MAP.get(d, 0)
        delta = (target - now.weekday()) % 7
        if delta == 0 and (now.hour, now.minute) >= (hour, minute): delta = 7
        now += timedelta(days=delta)
    return now.replace(hour=hour, minute=minute, second=0, microsecond=0).astimezone(utc)

# === REMINDERS ===
async def check_reminders():
    all_users = db.reference('reminders').get()
    if not all_users or not isinstance(all_users, dict): return
    for uid, reminder_list in all_users.items():
        changed = False
        for r in reminder_list[:]:
            try:
                dt = datetime.fromisoformat(r['next'])
                if dt.tzinfo is None: dt = dt.replace(tzinfo=utc)
                if dt <= datetime.now(utc):
                    content = await generate_response(r['task']) if r['ai'] else r['task']
                    print(f"[Reminder for {uid}] {content}")
                    if r.get("repeat"):
                        r["next"] = (datetime.now(utc) + timedelta(seconds=r["every"])).isoformat()
                    else:
                        reminder_list.remove(r)
                    changed = True
            except Exception as e:
                print(f"[Reminder Error] {e}")
        if changed: save_user_reminders(uid, reminder_list)

async def check_loop():
    while True:
        await check_reminders()
        await asyncio.sleep(10)

# === FLASK SERVER ===
flask_app = Flask(__name__)

@flask_app.route('/')
def index(): return '✅ Web Chatbot is Live'

@flask_app.route('/chat', methods=['GET', 'POST'])
def chat_ui():
    if request.method == 'POST':
        uid = request.form['uid']
        msg = request.form['message']
        memory = load_user_context(uid)
        memory.append(msg)
        save_user_context(uid, memory)
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        reply = loop.run_until_complete(generate_response(msg, memory))
        return render_template_string(chat_template, uid=uid, message=msg, reply=reply)
    return render_template_string(chat_template, uid='', message='', reply='')

chat_template = """
<!DOCTYPE html>
<html>
<head><title>AI Chat</title><script src=\"https://cdn.tailwindcss.com\"></script></head>
<body class=\"bg-gray-100 p-4 text-gray-900\">
<div class=\"max-w-xl mx-auto\">
    <h2 class=\"text-xl font-bold mb-4\">💬 Chat with AI</h2>
    <form method=\"POST\">
        <input name=\"uid\" value=\"{{ uid }}\" class=\"mb-2 w-full p-2 border rounded\" placeholder=\"User ID\">
        <textarea name=\"message\" class=\"w-full p-2 border rounded\" rows=\"3\" placeholder=\"Your message...\">{{ message }}</textarea>
        <button type=\"submit\" class=\"mt-2 bg-blue-500 text-white px-4 py-2 rounded\">Send</button>
    </form>
    {% if reply %}<div class=\"mt-4 p-4 bg-white rounded shadow\"><strong>AI:</strong> {{ reply }}</div>{% endif %}
</div>
</body>
</html>
"""

@flask_app.route('/dashboard')
def dashboard():
    uid = request.args.get("user")
    if not uid: return "Missing user ID (?user=123456)", 400
    reminders = load_user_reminders(uid)
    if not reminders: return f"No reminders found for user {uid}."
    tz = timezone(LOCAL_TIMEZONE)
    for r in reminders:
        dt = datetime.fromisoformat(r['next'])
        if dt.tzinfo is None: dt = dt.replace(tzinfo=utc)
        r['next_local'] = dt.astimezone(tz).strftime("%Y-%m-%d %H:%M")
    html = """
    <!DOCTYPE html>
    <html>
    <head><title>Reminder Dashboard</title><script src='https://cdn.tailwindcss.com'></script></head>
    <body class='bg-gray-100 p-4 text-gray-800'>
    <div class='max-w-xl mx-auto'>
        <h1 class='text-2xl font-bold mb-4'>⏰ Reminders for User {{ uid }}</h1>
        {% for r in reminders %}
            <div class='bg-white p-4 rounded-xl shadow-md mb-4'>
                <div class='text-lg font-semibold'>{{ r.task }}</div>
                <div class='text-sm text-gray-600'>Next: {{ r.next_local }}</div>
                <div class='text-sm'>Repeat: <span class='font-medium'>{{ 'Yes' if r.repeat else 'No' }}</span></div>
            </div>
        {% endfor %}
    </div>
    </body>
    </html>
    """
    return render_template_string(html, uid=uid, reminders=reminders)

# === RUN ===
if __name__ == '__main__':
    nest_asyncio.apply()
    threading.Thread(target=lambda: flask_app.run(host="0.0.0.0", port=8080)).start()
    asyncio.run(check_loop())
