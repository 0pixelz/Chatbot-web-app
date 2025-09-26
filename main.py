import os
from dotenv import load_dotenv
load_dotenv()
from flask import Flask, request, jsonify
from firebase_admin import credentials, initialize_app, db
from google.oauth2 import id_token
from google.auth.transport import requests as grequests
#testing comment


app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('FLASK_SECRET_KEY', 'default-secret-key')

# Initialize Firebase Admin SDK
cred = credentials.Certificate(os.getenv("FIREBASE_CREDENTIALS_PATH"))
initialize_app(cred, {
    'databaseURL': os.environ.get('DATABASE_URL')
})

# Endpoint for Google OAuth token verification
@app.route('/verify-token', methods=['POST'])
def verify_token():
    token = request.json.get('token')
    try:
        idinfo = id_token.verify_oauth2_token(token, grequests.Request(), os.environ.get('GOOGLE_CLIENT_ID'))
        userid = idinfo['sub']
        return jsonify({'user_id': userid}), 200
    except ValueError:
        return jsonify({'error': 'Invalid token'}), 400

# Endpoint to interact with GROQ API
@app.route('/groq-query', methods=['POST'])
def groq_query():
    query = request.json.get('query')
    api_key = os.environ.get('GROQ_API_KEY')
    # Here you would add code to interact with the GROQ API using the query and api_key
    # For now, just return the query for demonstration
    return jsonify({'query': query}), 200

if __name__ == '__main__':
    app.run(debug=True)