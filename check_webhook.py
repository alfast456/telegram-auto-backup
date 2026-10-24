import requests
import os
from dotenv import load_dotenv

load_dotenv()
token = os.environ.get("TELEGRAM_TOKEN")
url = f"https://api.telegram.org/bot{token}/getWebhookInfo"
response = requests.post(url)
print(response.json())
