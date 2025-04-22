# Web Chatbot with Dashboard

This is a fully web-based chatbot powered by Groq (LLaMA 3), integrated with Firebase for user context and reminders, and built using Flask.

## Features

- Chat with an AI assistant (`/chat`)
- View reminders dashboard (`/dashboard?user=YOUR_USER_ID`)
- AI memory per user (stored in Firebase)
- Natural language reminder parsing and scheduling
- Background reminder trigger loop

## Requirements

- Python 3.10+
- Firebase Realtime Database
- Groq API key
- Render or other web hosting service

## Setup

1. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

2. **Add your Firebase admin SDK JSON file**:
   - Place it in the root and update the `FIREBASE_JSON` path in `main.py`.

3. **Update your config** in `main.py`:
   ```python
   GROQ_API_KEY = 'your-groq-api-key'
   FIREBASE_JSON = 'your-firebase-adminsdk.json'
   DATABASE_URL = 'your-firebase-db-url'
   LOCAL_TIMEZONE = 'America/Toronto'  # or your timezone
   ```

4. **Run the app**:
   ```bash
   python main.py
   ```

5. **Deploy on Render**:
   - Create a new Web Service
   - Use `python main.py` as start command
   - Port: 8080

## URLs

- **Chatbot UI**: `/chat`
- **Reminders Dashboard**: `/dashboard?user=123456`

## Example Reminder

To create a reminder, type a message like:
> Remind me to drink water every day at 8am

The bot will detect and schedule it automatically.

---

Built by Jonathan with love and TailwindCSS.
