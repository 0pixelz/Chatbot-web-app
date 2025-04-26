# Chatbot Web App

A **simple and powerful AI Chatbot** powered by [Groq API](https://groq.com/), [Google OAuth](https://developers.google.com/identity/openid-connect/openid-connect), and [Firebase Realtime Database](https://firebase.google.com/products/realtime-database), deployed easily on **Render**.

- **Live Chatbot Interface** (ChatGPT-like)
- **User Authentication** (Login with Google)
- **Customizable Settings** (Theme, Font Size, Personality)
- **Personal Chat History** (Saved per user)
- **Account Management** (Delete account and data)
- **Environment-based Configuration** (for security)

---

## Features

- **Secure Google Login** (OAuth2)
- **AI Responses** using **LLaMA 3** model from Groq
- **Per-user Chat Memory** stored in Firebase
- **Settings** page to customize your experience
- **Delete Account** option to erase data
- **Deployable in minutes** to Render

---

## Tech Stack

- Python (Flask)
- Aiohttp
- Groq API (for AI completions)
- Google OAuth 2.0 (User Authentication)
- Firebase Admin SDK (Database)
- TailwindCSS (for frontend styling)
- Hosted on Render.com

---

## Installation

### 1. Clone the repository
```bash
git clone https://github.com/your-username/Chatbot-web-app.git
cd Chatbot-web-app
```

### 2. Install required packages
```bash
pip install -r requirements.txt
```

### 3. Set up Environment Variables
Create the following environment variables on Render:

| Variable Name               | Purpose                                       |
|------------------------------|-----------------------------------------------|
| `GROQ_API_KEY`               | Your Groq.com API key                        |
| `FIREBASE_CREDENTIALS_JSON`  | Full JSON content of Firebase credentials    |
| `DATABASE_URL`               | Your Firebase Realtime Database URL          |
| `GOOGLE_CLIENT_SECRET_JSON`  | Full JSON content of Google OAuth credentials|
| `FLASK_SECRET_KEY`           | Random string for Flask sessions             |
| `LOCAL_TIMEZONE`             | (optional) Default: `America/Toronto`         |

### 4. Deploy
- Deploy to [Render.com](https://render.com/) as a **Web Service**
- Use Python 3.11 environment
- Start command:
```bash
python main.py
```

---

## Usage

- Visit `/chat` to start chatting.
- Use `/login` to connect your Google account.
- Access `/settings` to customize theme, font size, and assistant behavior.
- `/clear` your conversation history.
- `/delete_account` to erase your account data from Firebase.

---

## Screenshots

*(You can add screenshots here if you want!)*

---

## License

This project is licensed under the **MIT License**.

---

## Credits

- Developed by [0pixelz](https://github.com/0pixelz)
- AI by [Groq](https://groq.com/)
- Hosting by [Render](https://render.com/)

