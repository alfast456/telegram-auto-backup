import requests
import os
from dotenv import load_dotenv

load_dotenv()
token = os.environ.get("TELEGRAM_TOKEN")
url = f"https://api.telegram.org/bot{token}/setMyCommands"
data = {
    "commands": [
        {"command": "start", "description": "Mulai bot & tampilkan bantuan"},
        {"command": "dbs", "description": "Lihat daftar database MySQL"},
        {"command": "backup", "description": "Backup manual (contoh: /backup db_name)"},
        {"command": "autobackup", "description": "Pengaturan checklist database auto-backup"},
        {"command": "interval", "description": "Ubah interval auto-backup (contoh: /interval 120)"},
        {"command": "delbackup", "description": "Hapus file backup lokal di server"}
    ]
}
response = requests.post(url, json=data)
print(response.json())
