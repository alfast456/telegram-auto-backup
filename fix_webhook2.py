import requests
import os
from dotenv import load_dotenv
import json

load_dotenv()
token = os.environ.get("TELEGRAM_TOKEN")
url = f"https://api.telegram.org/bot{token}/setWebhook"
data = {
    "url": "https://corgi-suitable-opossum.ngrok-free.app/telegram",
    "allowed_updates": json.dumps(["message", "edited_message", "callback_query"])
}
response = requests.post(url, data=data)
print("setWebhook response:", response.json())

url2 = f"https://api.telegram.org/bot{token}/getWebhookInfo"
response2 = requests.post(url2)
print("getWebhookInfo response:", response2.json())
