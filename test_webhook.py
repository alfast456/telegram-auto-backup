import os
import json
import hmac
import hashlib
import requests
from dotenv import load_dotenv

# Load secret from .env
load_dotenv()
GITHUB_WEBHOOK_SECRET = os.environ.get("GITHUB_WEBHOOK_SECRET")

url = "http://localhost:5000/webhook"

# Simulasi payload dari GitHub
payload = {
    "action": "opened", # Coba ganti jadi 'closed', 'merged', atau 'reopened'
    "pull_request": {
        "number": 123,
        "title": "Fitur Baru: Login page",
        "html_url": "https://github.com/user/repo/pull/123",
        "merged": False,
        "user": {
            "login": "johndoe"
        },
        "head": {
            "ref": "feature/login-page"
        },
        "base": {
            "ref": "main"
        }
    },
    "repository": {
        "full_name": "perusahaan/proyek-keren"
    }
}

# Convert payload to json string (tanpa spasi tambahan) for calculating HMAC
payload_bytes = json.dumps(payload, separators=(',', ':')).encode('utf-8')

# Generate HMAC Signature layaknya sistem GitHub
headers = {'Content-Type': 'application/json'}

if GITHUB_WEBHOOK_SECRET:
    mac = hmac.new(
        GITHUB_WEBHOOK_SECRET.encode('utf-8'),
        msg=payload_bytes,
        digestmod=hashlib.sha256
    )
    signature = f"sha256={mac.hexdigest()}"
    headers['X-Hub-Signature-256'] = signature

try:
    print(f"Mengirim test payload ({payload['action']}) ke webhook...")
    # Pakai data=payload_bytes agar raw byte sama persis dengan yang di-hash
    response = requests.post(url, data=payload_bytes, headers=headers)
    print(f"Status Code: {response.status_code}")
    print(f"Response Body: {response.text}")
except requests.exceptions.ConnectionError:
    print("Gagal koneksi! Pastikan 'python bot.py' sedang berjalan di terminal lain.")
