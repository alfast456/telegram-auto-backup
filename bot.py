import os
import hmac
import hashlib
import logging
import json
from flask import Flask, request, jsonify, abort
import requests
import pymysql
from dotenv import load_dotenv
import subprocess
import threading
from datetime import datetime
from apscheduler.schedulers.background import BackgroundScheduler

# Load environment variables from .env file
load_dotenv()

app = Flask(__name__)

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Load configurations from environment variables
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = os.environ.get("CHAT_ID")
GITHUB_WEBHOOK_SECRET = os.environ.get("GITHUB_WEBHOOK_SECRET")

# Database configurations
DB_HOST = os.environ.get("DB_HOST", "127.0.0.1")
DB_USER = os.environ.get("DB_USER", "root")
DB_PASS = os.environ.get("DB_PASS", "")

if not TELEGRAM_TOKEN or not CHAT_ID:
    logger.error("TELEGRAM_TOKEN or CHAT_ID is not set in environment variables! Please check your .env file.")

CONFIG_FILE = "config.json"

def load_config():
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Error reading config: {e}")
    # Default config
    return {
        "interval_minutes": 120,
        "databases": []
    }

def save_config(config_data):
    try:
        with open(CONFIG_FILE, 'w') as f:
            json.dump(config_data, f, indent=4)
    except Exception as e:
        logger.error(f"Error saving config: {e}")

def get_databases():
    """Mengambil daftar database dari MySQL lokal."""
    try:
        connection = pymysql.connect(
            host=DB_HOST,
            user=DB_USER,
            password=DB_PASS
        )
        with connection.cursor() as cursor:
            cursor.execute("SHOW DATABASES;")
            databases = cursor.fetchall()
            
        # Filter system databases agar list lebih bersih
        system_dbs = ['information_schema', 'mysql', 'performance_schema', 'sys']
        db_list = [db[0] for db in databases if db[0] not in system_dbs]
        
        return db_list
    except Exception as e:
        logger.error(f"Error querying databases: {e}")
        return None

def verify_signature(req):
    """
    Memverifikasi HMAC SHA-256 signature dari GitHub webhook.
    Jika secret tidak dikonfigurasi, lewati validasi (tidak disarankan untuk produksi).
    """
    if not GITHUB_WEBHOOK_SECRET:
        logger.warning("GITHUB_WEBHOOK_SECRET is not set. Skipping signature validation.")
        return True

    signature_header = req.headers.get('X-Hub-Signature-256')
    if not signature_header:
        logger.warning("Missing X-Hub-Signature-256 header")
        return False
        
    try:
        # Expected header format: sha256=....
        algo, signature = signature_header.split('=', 1)
        if algo != 'sha256':
            return False
            
        mac = hmac.new(
            GITHUB_WEBHOOK_SECRET.encode('utf-8'), 
            msg=req.get_data(), 
            digestmod=hashlib.sha256
        )
        return hmac.compare_digest(mac.hexdigest(), signature)
    except Exception as e:
        logger.error(f"Error validating signature: {e}")
        return False

def build_message(action, pull_request, repo_name):
    """
    Membuat format pesan Telegram berdasarkan status Pull Request.
    Mendukung event 'opened', 'reopened', dan 'closed' (termasuk merged).
    """
    pr_title = pull_request.get('title', 'Unknown PR')
    pr_url = pull_request.get('html_url', 'No URL')
    is_merged = pull_request.get('merged', False)
    pr_author = pull_request.get('user', {}).get('login', 'Unknown Author')
    pr_number = pull_request.get('number', '??')
    head_branch = pull_request.get('head', {}).get('ref', 'unknown')
    base_branch = pull_request.get('base', {}).get('ref', 'unknown')

    # Desain UI Telegram yang kreatif, terstruktur, dan informatif
    base_message = (
        f"<b>🔔 GITHUB PULL REQUEST</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"<b>Repo:</b> <code>{repo_name}</code>\n\n"
        f"📌 <b><a href='{pr_url}'>#{pr_number} {pr_title}</a></b>\n"
        f"┣ 👤 <b>By:</b> <i>{pr_author}</i>\n"
        f"┣ 🌿 <b>From:</b> <code>{head_branch}</code>\n"
        f"┣ 🎯 <b>To:</b> <code>{base_branch}</code>\n"
        f"┗ 🚥 <b>Status:</b> "
    )

    if action == "opened":
        return base_message + "🆕 <b>OPENED</b>"
    
    elif action == "reopened":
        return base_message + "🔄 <b>REOPENED</b>"
        
    elif action == "closed" and is_merged:
        return base_message + "✅ <b>MERGED</b>"
        
    elif action == "closed":
        return base_message + "❌ <b>CLOSED</b> <i>(Not Merged)</i>"
        
    return None

def scheduled_auto_backup():
    """Fungsi yang dijalankan oleh scheduler secara background."""
    logger.info("Mulai mengeksekusi Auto-Backup terjadwal...")
    config_data = load_config()
    dbs_to_backup = config_data.get("databases", [])
    
    if not dbs_to_backup:
        logger.info("Auto-backup di-skip karena tidak ada database yang di-checklist.")
        return
        
    for db in dbs_to_backup:
        logger.info(f"Auto-backup untuk database: {db}")
        # Kirim notif awal ke telegram
        res = send_telegram_notification(f"🔄 <b>Auto-Backup Terjadwal</b>\nMenyiapkan backup untuk database: <code>{db}</code>")
        message_id = res.get('result', {}).get('message_id') if res else None
        
        # Eksekusi backup sinkronous karena kita sudah di background thread APScheduler
        backup_database(db, message_id)

# Konfigurasi Scheduler
scheduler = BackgroundScheduler()
# Baca interval dari config
initial_config = load_config()
interval = initial_config.get("interval_minutes", 120)

# Tambahkan job auto-backup
scheduler.add_job(
    id='auto_backup_job',
    func=scheduled_auto_backup,
    trigger='interval',
    minutes=interval,
    replace_existing=True
)
scheduler.start()

# --- Modifikasi fungsi notifikasi untuk mendukung inline keyboard ---

def send_telegram_notification(pesan, reply_markup=None):
    """
    Mengirimkan pesan ke Telegram menggunakan REST API.
    """
    if not TELEGRAM_TOKEN or not CHAT_ID:
        raise ValueError("Missing Telegram credentials.")

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        'chat_id': CHAT_ID, 
        'text': pesan,
        'parse_mode': 'HTML',
        'disable_web_page_preview': True
    }
    
    if reply_markup:
        payload['reply_markup'] = reply_markup
    
    try:
        response = requests.post(url, json=payload, timeout=10)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        logger.error(f"Gagal kirim notif: {e}")
        return None

def edit_telegram_message(message_id, text, reply_markup=None):
    if not TELEGRAM_TOKEN or not CHAT_ID:
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/editMessageText"
    payload = {
        'chat_id': CHAT_ID,
        'message_id': message_id,
        'text': text,
        'parse_mode': 'HTML',
        'disable_web_page_preview': True
    }
    if reply_markup:
        payload['reply_markup'] = reply_markup
        
    try:
        response = requests.post(url, json=payload, timeout=10)
        response.raise_for_status()
    except Exception as e:
        logger.error(f"Failed to edit message: {e}")

# Fungsi helper untuk membuat keyboard checklist
def get_autobackup_keyboard():
    all_dbs = get_databases()
    config_data = load_config()
    selected_dbs = config_data.get("databases", [])
    
    keyboard = []
    if all_dbs:
        for db in all_dbs:
            icon = "✅" if db in selected_dbs else "❌"
            # Callback data akan menjadi "toggle_dbname"
            keyboard.append([{"text": f"{icon} {db}", "callback_data": f"toggle_{db}"}])
            
    # Tombol Refresh dan Tutup
    keyboard.append([
        {"text": "🔄 Refresh", "callback_data": "refresh_db"},
        {"text": "✖️ Tutup", "callback_data": "close_kb"}
    ])
    
    return {"inline_keyboard": keyboard}

def send_telegram_document(file_path, caption=""):
    if not TELEGRAM_TOKEN or not CHAT_ID:
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendDocument"
    data = {
        'chat_id': CHAT_ID,
        'caption': caption,
        'parse_mode': 'HTML'
    }
    try:
        with open(file_path, 'rb') as f:
            files = {'document': f}
            response = requests.post(url, data=data, files=files, timeout=60)
            response.raise_for_status()
            return response.json()
    except Exception as e:
        logger.error(f"Failed to send document: {e}")
        return None

def backup_database(db_name, message_id=None):
    if message_id:
        edit_telegram_message(message_id, f"⏳ <b>Memulai backup database</b> <code>{db_name}</code>...")
        
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_file = f"backup_{db_name}_{timestamp}.sql"
    
    cmd = [
        "mysqldump",
        f"-h{DB_HOST}",
        f"-u{DB_USER}",
    ]
    if DB_PASS:
        cmd.append(f"-p{DB_PASS}")
    cmd.append(db_name)
    
    if message_id:
        edit_telegram_message(message_id, f"⚙️ <b>Membuat file backup</b> <code>{backup_file}</code>...\nProses ini mungkin memakan waktu beberapa saat tergantung ukuran database.")
        
    try:
        with open(backup_file, "w", encoding="utf-8") as f:
            result = subprocess.run(cmd, stdout=f, stderr=subprocess.PIPE, text=True)
            
        if result.returncode != 0:
            logger.error(f"mysqldump error: {result.stderr}")
            if message_id:
                edit_telegram_message(message_id, f"❌ <b>Gagal melakukan backup!</b>\nError:\n<code>{result.stderr}</code>")
            if os.path.exists(backup_file):
                os.remove(backup_file)
            return False
            
        if message_id:
            edit_telegram_message(message_id, f"📤 <b>Mengirim file backup</b> <code>{backup_file}</code> ke Telegram...")
            
        send_result = send_telegram_document(backup_file, caption=f"📦 <b>Backup Database:</b> <code>{db_name}</code>\n📅 <b>Waktu:</b> {timestamp}")
        
        if send_result:
            if message_id:
                edit_telegram_message(message_id, f"✅ <b>Backup selesai dan file berhasil dikirim!</b>\nDatabase: <code>{db_name}</code>")
        else:
            if message_id:
                edit_telegram_message(message_id, f"⚠️ <b>Backup berhasil dibuat, tapi gagal dikirim ke Telegram!</b>\nFile tersimpan lokal: <code>{backup_file}</code>")
                
        if os.path.exists(backup_file):
            os.remove(backup_file)
            
        return True
    except Exception as e:
        logger.error(f"Backup process error: {e}")
        if message_id:
            edit_telegram_message(message_id, f"❌ <b>Terjadi kesalahan pada sistem saat backup!</b>\nError: <code>{str(e)}</code>")
        if os.path.exists(backup_file):
            os.remove(backup_file)
        return False

@app.route('/telegram', methods=['POST'])
def telegram_webhook():
    """
    Endpoint untuk menerima update langsung dari Telegram.
    """
    if not request.is_json:
        return jsonify({"error": "Request payload must be JSON"}), 400
        
    data = request.json
    
    # Handle Callback Query (klik tombol inline)
    if 'callback_query' in data:
        callback = data['callback_query']
        callback_data = callback.get('data')
        message = callback.get('message', {})
        message_id = message.get('message_id')
        sender_id = str(callback.get('from', {}).get('id', ''))
        
        # Verifikasi sender
        if sender_id != CHAT_ID:
            return jsonify({"message": "Unauthorized"}), 403
            
        config_data = load_config()
        selected_dbs = config_data.get("databases", [])
        
        if callback_data.startswith("toggle_"):
            db_name = callback_data.replace("toggle_", "", 1)
            if db_name in selected_dbs:
                selected_dbs.remove(db_name)
            else:
                selected_dbs.append(db_name)
                
            config_data['databases'] = selected_dbs
            save_config(config_data)
            
            # Update pesan dengan keyboard baru
            text = "🗄️ <b>Pengaturan Auto-Backup Database</b>\nKlik untuk mencentang (✅) atau menghapus (❌):"
            edit_telegram_message(message_id, text, reply_markup=get_autobackup_keyboard())
            
        elif callback_data == "refresh_db":
            text = "🗄️ <b>Pengaturan Auto-Backup Database</b>\nKlik untuk mencentang (✅) atau menghapus (❌):"
            edit_telegram_message(message_id, text, reply_markup=get_autobackup_keyboard())
            
        elif callback_data == "close_kb":
            text = "✅ <b>Pengaturan Auto-Backup Ditutup</b>\nDatabase yang dipilih telah disimpan."
            edit_telegram_message(message_id, text, reply_markup={"inline_keyboard": []})
            
        # Balas callback API agar tombol tidak loading terus
        callback_id = callback.get('id')
        requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/answerCallbackQuery", 
                      json={"callback_query_id": callback_id})
        return jsonify({"message": "Callback processed"}), 200

    # Handle Normal Message
    message = data.get('message', {})
    text = message.get('text', '')
    chat = message.get('chat', {})
    sender_chat_id = str(chat.get('id', ''))
    
    if sender_chat_id != CHAT_ID:
        logger.warning(f"Akses tidak sah ke perintah bot dari Chat ID: {sender_chat_id}")
        return jsonify({"message": "Unauthorized"}), 403

    # Respon terhadap perintah /dbs
    if text.startswith('/dbs'):
        databases = get_databases()
        
        if databases is None:
            pesan = "❌ <b>Gagal!</b> Tidak dapat terhubung ke database MySQL. Pastikan MySQL menyala."
        elif len(databases) == 0:
            pesan = "🗄️ <b>Database List:</b>\n<i>Tidak ada database yang ditemukan.</i>"
        else:
            db_bullets = "\n".join([f"• <code>{db}</code>" for db in databases])
            pesan = f"🗄️ <b>MySQL Database List:</b>\n━━━━━━━━━━━━━━━━━━━━\n{db_bullets}"
            
        try:
            send_telegram_notification(pesan)
        except Exception as e:
            logger.error(f"Gagal mengirim list DB ke Telegram: {e}")
            
    # Respon terhadap perintah /backup
    elif text.startswith('/backup'):
        parts = text.split()
        if len(parts) < 2:
            try:
                send_telegram_notification("⚠️ <b>Format salah!</b>\nGunakan: <code>/backup [nama_database]</code>\nContoh: <code>/backup my_database</code>")
            except Exception as e:
                logger.error(f"Gagal mengirim pesan error format backup: {e}")
        else:
            db_name = parts[1]
            try:
                # Kirim pesan awal dan dapatkan ID pesannya untuk di-edit nanti
                res = send_telegram_notification(f"🔄 <b>Menyiapkan backup...</b>\nDatabase: <code>{db_name}</code>")
                message_id = res.get('result', {}).get('message_id') if res else None
                
                # Jalankan backup di thread terpisah agar webhook tidak timeout
                thread = threading.Thread(target=backup_database, args=(db_name, message_id))
                thread.start()
            except Exception as e:
                logger.error(f"Gagal memproses request backup: {e}")
                
    # Respon perintah /autobackup
    elif text.startswith('/autobackup'):
        pesan = "🗄️ <b>Pengaturan Auto-Backup Database</b>\nKlik untuk mencentang (✅) atau menghapus (❌) database dari jadwal backup otomatis:"
        keyboard = get_autobackup_keyboard()
        send_telegram_notification(pesan, reply_markup=keyboard)
        
    # Respon perintah /interval
    elif text.startswith('/interval'):
        parts = text.split()
        if len(parts) < 2 or not parts[1].isdigit():
            pesan = "⚠️ <b>Format salah!</b>\nGunakan: <code>/interval [menit]</code>\nContoh: <code>/interval 120</code> (untuk 2 jam)"
            send_telegram_notification(pesan)
        else:
            new_interval = int(parts[1])
            config_data = load_config()
            config_data['interval_minutes'] = new_interval
            save_config(config_data)
            
            # Reschedule job
            scheduler.reschedule_job('auto_backup_job', trigger='interval', minutes=new_interval)
            
            send_telegram_notification(f"✅ <b>Interval Diperbarui!</b>\nAuto-backup sekarang akan berjalan setiap <b>{new_interval} menit</b>.")
            
    return jsonify({"message": "OK"}), 200

@app.route('/webhook', methods=['POST'])
def handle_webhook():
    # 1. Validasi Keamanan (Signature)
    if not verify_signature(request):
        abort(403, description="Forbidden: Invalid GitHub signature")

    # 2. Validasi Payload JSON
    if not request.is_json:
        return jsonify({"error": "Request payload must be JSON"}), 400

    data = request.json
    
    # 3. Ekstraksi Data
    action = data.get('action')
    pull_request = data.get('pull_request')
    repo_name = data.get('repository', {}).get('full_name', 'Unknown Repo')

    if not pull_request:
        logger.info("Not a pull request event or missing 'pull_request' data.")
        return jsonify({"message": "Ignored: Not a PR event"}), 200

    # 4. Buat Pesan
    pesan = build_message(action, pull_request, repo_name)
    if not pesan:
        logger.info(f"Ignored PR action: {action}")
        return jsonify({"message": f"Ignored action: {action}"}), 200

    # 5. Kirim Notifikasi
    try:
        send_telegram_notification(pesan)
        pr_title = pull_request.get('title', '??')
        logger.info(f"Notification sent successfully for PR: '{pr_title}'")
        return jsonify({"message": "Notif dikirim!"}), 200
    except Exception as e:
        logger.error(f"Failed to send Telegram notification: {e}")
        return jsonify({"error": "Failed to send notification"}), 500

# Error Handler global untuk pesan abort
@app.errorhandler(403)
def forbidden(e):
    logger.warning(f"403 Forbidden: {e.description}")
    return jsonify(error=str(e.description)), 403

if __name__ == '__main__':
    app.run(port=5000)