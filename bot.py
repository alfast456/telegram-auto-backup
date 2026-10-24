import os
import hmac
import hashlib
import logging
import json
import re
import html
import time
import shutil
import glob
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
BACKUP_BASE_DIR = "backup"

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

# --- Telegram API & Helper Functions (Rate Limiting & Truncation) ---

def safe_truncate(text, max_len=4000):
    """
    Memotong string jika melebihi batas karakter agar tidak melebihi limit Telegram (4096 char).
    """
    if not text:
        return ""
    if len(text) <= max_len:
        return text
    return text[:max_len - 30] + "\n...[Dipotong karena terlalu panjang]"

def telegram_api_request(method, endpoint, max_retries=3, **kwargs):
    """
    Helper untuk mengirim request ke Telegram Bot API dengan penanganan 
    rate limit (HTTP 429) dan retry otomatis.
    """
    if not TELEGRAM_TOKEN:
        logger.error("TELEGRAM_TOKEN is not configured.")
        return None

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/{endpoint}"
    
    for attempt in range(max_retries):
        try:
            response = requests.request(method, url, **kwargs)
            if response.status_code == 429:
                retry_after = 1
                try:
                    err_data = response.json()
                    retry_after = err_data.get("parameters", {}).get("retry_after", 1)
                except Exception:
                    pass
                logger.warning(f"Telegram Rate Limit (HTTP 429)! Retrying after {retry_after}s (attempt {attempt + 1}/{max_retries})")
                time.sleep(retry_after)
                continue

            response.raise_for_status()
            return response.json()
        except requests.exceptions.HTTPError as he:
            logger.error(f"HTTP error calling Telegram {endpoint}: {he}")
            break
        except Exception as e:
            logger.error(f"Error calling Telegram {endpoint}: {e}")
            break
            
    return None

def send_telegram_notification(pesan, reply_markup=None):
    """
    Mengirimkan pesan ke Telegram menggunakan REST API.
    """
    if not TELEGRAM_TOKEN or not CHAT_ID:
        raise ValueError("Missing Telegram credentials.")

    payload = {
        'chat_id': CHAT_ID, 
        'text': safe_truncate(pesan, 4000),
        'parse_mode': 'HTML',
        'disable_web_page_preview': True
    }
    
    if reply_markup:
        payload['reply_markup'] = reply_markup
    
    return telegram_api_request('POST', 'sendMessage', json=payload, timeout=15)

def edit_telegram_message(message_id, text, reply_markup=None, chat_id=None):
    if not TELEGRAM_TOKEN:
        return None
    
    target_chat_id = chat_id if chat_id else CHAT_ID
    if not target_chat_id:
        return None
        
    payload = {
        'chat_id': target_chat_id,
        'message_id': message_id,
        'text': safe_truncate(text, 4000),
        'parse_mode': 'HTML',
        'disable_web_page_preview': True
    }
    if reply_markup:
        payload['reply_markup'] = reply_markup
        
    return telegram_api_request('POST', 'editMessageText', json=payload, timeout=15)

def send_telegram_document(file_path, caption=""):
    if not TELEGRAM_TOKEN or not CHAT_ID:
        return None
        
    # Batas caption Telegram adalah 1024 karakter
    clean_caption = safe_truncate(caption, 1000)
    data = {
        'chat_id': CHAT_ID,
        'caption': clean_caption,
        'parse_mode': 'HTML'
    }
    try:
        with open(file_path, 'rb') as f:
            files = {'document': f}
            return telegram_api_request('POST', 'sendDocument', data=data, files=files, timeout=90)
    except Exception as e:
        logger.error(f"Failed to read/send document: {e}")
        return None

def build_message(action, pull_request, repo_name):
    """
    Membuat format pesan Telegram berdasarkan status Pull Request.
    Mendukung event 'opened', 'reopened', dan 'closed' (termasuk merged).
    Semua field dinamis di-escape agar tidak merusak tag HTML Telegram.
    """
    pr_title = html.escape(str(pull_request.get('title', 'Unknown PR')))
    pr_url = html.escape(str(pull_request.get('html_url', 'No URL')), quote=True)
    is_merged = pull_request.get('merged', False)
    pr_author = html.escape(str(pull_request.get('user', {}).get('login', 'Unknown Author')))
    pr_number = html.escape(str(pull_request.get('number', '??')))
    head_branch = html.escape(str(pull_request.get('head', {}).get('ref', 'unknown')))
    base_branch = html.escape(str(pull_request.get('base', {}).get('ref', 'unknown')))
    safe_repo = html.escape(str(repo_name))

    # Desain UI Telegram yang kreatif, terstruktur, dan informatif
    base_message = (
        f"<b>🔔 GITHUB PULL REQUEST</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"<b>Repo:</b> <code>{safe_repo}</code>\n\n"
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

# --- Manajemen Folder & File Backup ---

def organize_existing_backups():
    """
    Memindahkan file backup lama di root folder ke struktur rapi:
    backup/<db_name>/<tanggal_backup>/<filename>
    """
    try:
        root_files = glob.glob("backup_*.sql") + glob.glob("backup_*.sql.gz")
        pattern = re.compile(r"^backup_(.+)_(?P<year>\d{4})(?P<month>\d{2})(?P<day>\d{2})_\d{6}\.sql(?:\.gz)?$")
        moved_count = 0
        for f in root_files:
            basename = os.path.basename(f)
            m = pattern.match(basename)
            if m:
                db = m.group(1)
                date_str = f"{m.group('year')}-{m.group('month')}-{m.group('day')}"
                dest_dir = os.path.join(BACKUP_BASE_DIR, db, date_str)
                os.makedirs(dest_dir, exist_ok=True)
                shutil.move(f, os.path.join(dest_dir, basename))
                moved_count += 1
        if moved_count > 0:
            logger.info(f"Berhasil merapikan {moved_count} file backup lama ke dalam folder '{BACKUP_BASE_DIR}/'.")
    except Exception as e:
        logger.error(f"Error saat merapikan file backup lama: {e}")

def get_all_backup_files():
    """
    Mengambil daftar semua file backup yang ada secara terstruktur.
    Format return: {hash_id: {"path": rel_path, "db": db_name, "date": date_str, "size_mb": size, "name": basename}}
    """
    files = glob.glob(f"{BACKUP_BASE_DIR}/**/*.sql*", recursive=True) + glob.glob("backup_*.sql*")
    result = {}
    for f in sorted(files, key=os.path.getmtime, reverse=True):
        if not os.path.isfile(f):
            continue
        rel_path = os.path.normpath(f)
        # Gunakan hash 16 karakter untuk callback data Telegram agar tidak melebihi 64 bytes
        hash_id = hashlib.md5(rel_path.encode()).hexdigest()[:16]
        size_mb = os.path.getsize(rel_path) / (1024 * 1024)
        basename = os.path.basename(rel_path)
        
        parts = rel_path.split(os.sep)
        if len(parts) >= 3 and parts[0] == BACKUP_BASE_DIR:
            db_name = parts[1]
            date_str = parts[2]
        else:
            db_name = "lainnya"
            date_str = "root"
            
        result[hash_id] = {
            "path": rel_path,
            "db": db_name,
            "date": date_str,
            "size_mb": size_mb,
            "name": basename
        }
    return result

# Rapikan file backup lama saat bot pertama kali load
organize_existing_backups()

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
        safe_db = html.escape(db)
        # Kirim notif awal ke telegram
        res = send_telegram_notification(f"🔄 <b>Auto-Backup Terjadwal</b>\nMenyiapkan backup untuk database: <code>{safe_db}</code>")
        message_id = res.get('result', {}).get('message_id') if res else None
        
        # Eksekusi backup sinkronous karena kita sudah di background thread APScheduler
        backup_database(db, message_id)
        # Jeda 2 detik antar database untuk mencegah rate limit Telegram
        time.sleep(2)

# Konfigurasi Scheduler
scheduler = BackgroundScheduler()
initial_config = load_config()
interval = initial_config.get("interval_minutes", 120)

scheduler.add_job(
    id='auto_backup_job',
    func=scheduled_auto_backup,
    trigger='interval',
    minutes=interval,
    replace_existing=True
)
scheduler.start()

# --- Keyboard Helper Functions ---

def get_autobackup_keyboard():
    all_dbs = get_databases()
    config_data = load_config()
    selected_dbs = config_data.get("databases", [])
    
    keyboard = []
    if all_dbs:
        for db in all_dbs:
            icon = "✅" if db in selected_dbs else "❌"
            keyboard.append([{"text": f"{icon} {db}", "callback_data": f"toggle_{db}"}])
            
    keyboard.append([
        {"text": "🔄 Refresh", "callback_data": "refresh_db"},
        {"text": "✖️ Tutup", "callback_data": "close_kb"}
    ])
    
    return {"inline_keyboard": keyboard}

def get_delbackup_main_keyboard():
    """Menu Utama /delbackup: Menampilkan daftar database yang memiliki file backup."""
    backups = get_all_backup_files()
    dbs = {}
    for _, info in backups.items():
        db_key = info['db']
        dbs[db_key] = dbs.get(db_key, 0) + 1
        
    keyboard = []
    if dbs:
        for db, count in sorted(dbs.items()):
            keyboard.append([{"text": f"📁 {db} ({count} file)", "callback_data": f"deldb_{db}"[:64]}])
    else:
        keyboard.append([{"text": "Tidak ada file backup tersimpan", "callback_data": "noop"}])
        
    keyboard.append([
        {"text": "🔄 Refresh", "callback_data": "refresh_del_kb"},
        {"text": "✖️ Tutup", "callback_data": "close_del_kb"}
    ])
    
    return {"inline_keyboard": keyboard}

def get_delbackup_db_keyboard(db_name):
    """Sub-Menu /delbackup: Menampilkan file backup spesifik di dalam folder database yang dipilih."""
    backups = get_all_backup_files()
    filtered = [(h, info) for h, info in backups.items() if info['db'] == db_name]
    
    keyboard = []
    if filtered:
        # Tampilkan maksimal 12 file terbaru agar tombol tidak membludak
        for h, info in filtered[:12]:
            # Contoh tampilan: 🗑️ 2026-10-24 | 11:37 (178.5 MB)
            time_part = info['name'].split('_')[-1].replace('.sql.gz', '').replace('.sql', '')
            if len(time_part) == 6:
                formatted_time = f"{time_part[:2]}:{time_part[2:4]}"
            else:
                formatted_time = time_part
                
            btn_text = f"🗑️ {info['date']} {formatted_time} ({info['size_mb']:.1f} MB)"
            keyboard.append([{"text": btn_text, "callback_data": f"rmf_{h}"}])
            
        if len(filtered) > 12:
            keyboard.append([{"text": f"ℹ️ Menampilkan 12 dari {len(filtered)} file terbaru", "callback_data": "noop"}])
            
        # Tombol untuk menghapus seluruh backup database ini
        keyboard.append([{"text": f"💥 Hapus Semua Backup ({db_name})", "callback_data": f"rmall_{db_name}"[:64]}])
    else:
        keyboard.append([{"text": "Tidak ada file backup untuk database ini", "callback_data": "noop"}])
        
    keyboard.append([
        {"text": "⬅️ Kembali", "callback_data": "refresh_del_kb"},
        {"text": "🔄 Refresh", "callback_data": f"deldb_{db_name}"[:64]},
        {"text": "✖️ Tutup", "callback_data": "close_del_kb"}
    ])
    
    return {"inline_keyboard": keyboard}

def backup_database(db_name, message_id=None):
    """
    Melakukan mysqldump dan menyimpan hasil kompresi di folder terstruktur:
    backup/<db_name>/<tanggal_backup>/backup_<db_name>_<timestamp>.sql.gz
    """
    if not re.match(r'^[a-zA-Z0-9_\-]+$', db_name):
        logger.warning(f"Invalid database name attempted: {db_name}")
        if message_id:
            edit_telegram_message(message_id, "❌ <b>Nama database tidak valid!</b> Hanya karakter huruf, angka, _ dan - yang diizinkan.")
        return False

    safe_db_name = html.escape(db_name)
    now = datetime.now()
    date_str = now.strftime("%Y-%m-%d")
    timestamp = now.strftime("%Y%m%d_%H%M%S")
    
    # Struktur folder rapi: backup/<db_name>/<tanggal_backup>/
    target_dir = os.path.join(BACKUP_BASE_DIR, db_name, date_str)
    os.makedirs(target_dir, exist_ok=True)
    
    backup_file = os.path.join(target_dir, f"backup_{db_name}_{timestamp}.sql")
    gz_file = backup_file + ".gz"
    
    if message_id:
        edit_telegram_message(message_id, f"⏳ <b>Memulai backup database</b> <code>{safe_db_name}</code>...\n📁 Lokasi: <code>{target_dir}/</code>")
        
    cmd = [
        "mysqldump",
        f"-h{DB_HOST}",
        f"-u{DB_USER}",
        db_name
    ]
    
    env = os.environ.copy()
    if DB_PASS:
        env["MYSQL_PWD"] = DB_PASS
    
    if message_id:
        edit_telegram_message(message_id, f"⚙️ <b>Membuat file backup SQL...</b>\nDatabase: <code>{safe_db_name}</code>\nTarget: <code>{backup_file}</code>")
        
    try:
        with open(backup_file, "w", encoding="utf-8") as f:
            result = subprocess.run(cmd, stdout=f, stderr=subprocess.PIPE, text=True, env=env)
            
        if result.returncode != 0:
            logger.error(f"mysqldump error: {result.stderr}")
            if message_id:
                safe_err = html.escape(safe_truncate(result.stderr, 3000))
                edit_telegram_message(message_id, f"❌ <b>Gagal melakukan backup!</b>\nError:\n<code>{safe_err}</code>")
            if os.path.exists(backup_file):
                os.remove(backup_file)
            return False
            
        import gzip
        if message_id:
            edit_telegram_message(message_id, "🗜️ <b>Mengkompresi file backup ke .gz...</b>")
            
        with open(backup_file, 'rb') as f_in:
            with gzip.open(gz_file, 'wb') as f_out:
                shutil.copyfileobj(f_in, f_out)
                
        # Hapus file .sql mentah setelah terkompresi
        if os.path.exists(backup_file):
            os.remove(backup_file)
            
        file_size_mb = os.path.getsize(gz_file) / (1024 * 1024)
        
        # Kirim dokumen jika ukuran file di bawah 50MB (batas Telegram Bot API)
        if file_size_mb > 49.0:
            logger.warning(f"File {gz_file} is {file_size_mb:.2f}MB, skipping Telegram upload.")
            if message_id:
                edit_telegram_message(message_id, 
                    f"⚠️ <b>Backup Berhasil Dibuat!</b>\n"
                    f"Database: <code>{safe_db_name}</code>\n"
                    f"🗜️ Ukuran: <b>{file_size_mb:.1f} MB</b> (Melebihi limit Telegram 50MB)\n"
                    f"📁 <b>Tersimpan lokal di:</b> <code>{gz_file}</code>")
            return True
            
        if message_id:
            edit_telegram_message(message_id, f"📤 <b>Mengirim file backup</b> ke Telegram...\nUkuran: {file_size_mb:.1f} MB")
            
        caption = f"📦 <b>Backup Database:</b> <code>{safe_db_name}</code>\n📅 <b>Waktu:</b> {timestamp}\n📁 <b>Path:</b> <code>{gz_file}</code>\n🗜️ <b>Ukuran:</b> {file_size_mb:.1f} MB"
        send_result = send_telegram_document(gz_file, caption=caption)
        
        if send_result:
            if message_id:
                edit_telegram_message(message_id, 
                    f"✅ <b>Backup selesai dan file berhasil dikirim!</b>\n"
                    f"Database: <code>{safe_db_name}</code>\n"
                    f"📁 <b>Tersimpan lokal di:</b> <code>{gz_file}</code>")
        else:
            if message_id:
                edit_telegram_message(message_id, 
                    f"⚠️ <b>Backup berhasil dibuat</b>, tapi gagal dikirim ke Telegram!\n"
                    f"📁 <b>Tersimpan lokal di:</b> <code>{gz_file}</code>")
                
        return True
    except Exception as e:
        logger.error(f"Backup process error: {e}")
        if message_id:
            safe_err = html.escape(str(e))
            edit_telegram_message(message_id, f"❌ <b>Terjadi kesalahan pada sistem saat backup!</b>\nError: <code>{safe_err}</code>")
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
    logger.info(f"RAW PAYLOAD: {data}")
    
    # 1. Handle Callback Query (Klik tombol inline keyboard)
    if 'callback_query' in data:
        callback = data['callback_query']
        callback_data = callback.get('data')
        message = callback.get('message', {})
        message_id = message.get('message_id')
        callback_chat_id = str(message.get('chat', {}).get('id', ''))
        callback_id = callback.get('id')
        
        logger.info(f"Received callback: data={callback_data}, chat_id={callback_chat_id}, msg_id={message_id}")
        
        # Verifikasi sender berdasarkan Chat ID
        if callback_chat_id != CHAT_ID:
            logger.warning(f"Callback Unauthorized: callback_chat_id={callback_chat_id}, CHAT_ID={CHAT_ID}")
            telegram_api_request('POST', 'answerCallbackQuery', json={"callback_query_id": callback_id, "text": "Unauthorized Chat ID!", "show_alert": True})
            return jsonify({"message": "Unauthorized"}), 200
            
        config_data = load_config()
        selected_dbs = config_data.get("databases", [])
        
        # --- Handler Auto-Backup Checklist ---
        if callback_data and callback_data.startswith("toggle_"):
            db_name = callback_data.replace("toggle_", "", 1)
            if db_name in selected_dbs:
                selected_dbs.remove(db_name)
            else:
                selected_dbs.append(db_name)
                
            config_data['databases'] = selected_dbs
            save_config(config_data)
            
            text = "🗄️ <b>Pengaturan Auto-Backup Database</b>\nKlik untuk mencentang (✅) atau menghapus (❌):"
            edit_telegram_message(message_id, text, reply_markup=get_autobackup_keyboard(), chat_id=callback_chat_id)
            
        elif callback_data == "refresh_db":
            text = "🗄️ <b>Pengaturan Auto-Backup Database</b>\nKlik untuk mencentang (✅) atau menghapus (❌):"
            edit_telegram_message(message_id, text, reply_markup=get_autobackup_keyboard(), chat_id=callback_chat_id)
            
        elif callback_data == "close_kb":
            text = "✅ <b>Pengaturan Auto-Backup Ditutup</b>\nDatabase yang dipilih telah disimpan."
            edit_telegram_message(message_id, text, reply_markup={"inline_keyboard": []}, chat_id=callback_chat_id)
            
        # --- Handler Navigasi & Hapus Backup (/delbackup) ---
        elif callback_data and callback_data.startswith("deldb_"):
            # Buka daftar file untuk database tertentu
            db_target = callback_data.replace("deldb_", "", 1)
            text = (
                f"🗄️ <b>Kelola File Backup Database:</b> <code>{html.escape(db_target)}</code>\n"
                f"📁 Folder: <code>{BACKUP_BASE_DIR}/{db_target}/</code>\n\n"
                f"Klik tombol file di bawah untuk menghapusnya secara permanen:"
            )
            edit_telegram_message(message_id, text, reply_markup=get_delbackup_db_keyboard(db_target), chat_id=callback_chat_id)
            
        elif callback_data and callback_data.startswith("rmf_"):
            # Hapus 1 file spesifik berdasarkan hash ID
            file_hash = callback_data.replace("rmf_", "", 1)
            backups = get_all_backup_files()
            info = backups.get(file_hash)
            
            if info:
                target_file = info["path"]
                db_parent = info["db"]
                real_file = os.path.realpath(target_file)
                cwd = os.path.realpath(".")
                
                # Keamanan: Pastikan file berada di dalam folder project
                if real_file.startswith(cwd) and os.path.exists(target_file):
                    try:
                        os.remove(target_file)
                        logger.info(f"Deleted backup file: {target_file}")
                        
                        # Bersihkan folder tanggal jika sudah kosong
                        parent_dir = os.path.dirname(target_file)
                        if os.path.exists(parent_dir) and not os.listdir(parent_dir):
                            os.rmdir(parent_dir)
                            # Bersihkan folder database jika sudah kosong
                            db_dir = os.path.dirname(parent_dir)
                            if os.path.exists(db_dir) and not os.listdir(db_dir):
                                os.rmdir(db_dir)
                                
                        telegram_api_request('POST', 'answerCallbackQuery', 
                                              json={"callback_query_id": callback_id, "text": f"✅ File {info['name']} berhasil dihapus!"})
                    except Exception as e:
                        logger.error(f"Gagal menghapus file {target_file}: {e}")
                        telegram_api_request('POST', 'answerCallbackQuery', 
                                              json={"callback_query_id": callback_id, "text": "❌ Gagal menghapus file!"})
                else:
                    telegram_api_request('POST', 'answerCallbackQuery', 
                                          json={"callback_query_id": callback_id, "text": "File tidak ditemukan!"})
                                          
                # Update tampilan keyboard
                text = (
                    f"🗄️ <b>Kelola File Backup Database:</b> <code>{html.escape(db_parent)}</code>\n"
                    f"📁 Folder: <code>{BACKUP_BASE_DIR}/{db_parent}/</code>\n\n"
                    f"Klik tombol file di bawah untuk menghapusnya secara permanen:"
                )
                edit_telegram_message(message_id, text, reply_markup=get_delbackup_db_keyboard(db_parent), chat_id=callback_chat_id)
                return jsonify({"message": "File deleted"}), 200
            else:
                telegram_api_request('POST', 'answerCallbackQuery', 
                                      json={"callback_query_id": callback_id, "text": "File sudah tidak ada atau sudah dihapus."})
                                      
        elif callback_data and callback_data.startswith("rmall_"):
            # Konfirmasi hapus seluruh backup untuk suatu database
            db_target = callback_data.replace("rmall_", "", 1)
            text = (
                f"⚠️ <b>KONFIRMASI HAPUS SEMUA BACKUP</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"Apakah Anda yakin ingin menghapus <b>SEMUA</b> file backup untuk database <code>{html.escape(db_target)}</code>?\n\n"
                f"<i>Tindakan ini tidak dapat dibatalkan!</i>"
            )
            confirm_kb = {
                "inline_keyboard": [
                    [{"text": f"⚠️ Ya, Hapus Semua ({db_target})", "callback_data": f"dormall_{db_target}"[:64]}],
                    [{"text": "❌ Batal", "callback_data": f"deldb_{db_target}"[:64]}]
                ]
            }
            edit_telegram_message(message_id, text, reply_markup=confirm_kb, chat_id=callback_chat_id)
            
        elif callback_data and callback_data.startswith("dormall_"):
            # Eksekusi hapus semua file backup DB
            db_target = callback_data.replace("dormall_", "", 1)
            db_dir = os.path.join(BACKUP_BASE_DIR, db_target)
            real_db_dir = os.path.realpath(db_dir)
            cwd = os.path.realpath(".")
            
            if real_db_dir.startswith(cwd) and os.path.exists(db_dir):
                shutil.rmtree(db_dir)
                logger.info(f"Semua backup untuk database {db_target} telah dihapus ({db_dir}).")
                
            telegram_api_request('POST', 'answerCallbackQuery', 
                                  json={"callback_query_id": callback_id, "text": f"✅ Semua backup {db_target} berhasil dibersihkan!"})
                                  
            text = "🗑️ <b>Hapus File Backup</b>\nPilih database untuk mengelola file backup:"
            edit_telegram_message(message_id, text, reply_markup=get_delbackup_main_keyboard(), chat_id=callback_chat_id)
            return jsonify({"message": "All DB files deleted"}), 200
            
        elif callback_data == "refresh_del_kb":
            text = "🗑️ <b>Hapus File Backup</b>\nPilih database untuk mengelola file backup:"
            edit_telegram_message(message_id, text, reply_markup=get_delbackup_main_keyboard(), chat_id=callback_chat_id)
            
        elif callback_data == "close_del_kb":
            text = "✅ <b>Menu Hapus Backup Ditutup</b>."
            edit_telegram_message(message_id, text, reply_markup={"inline_keyboard": []}, chat_id=callback_chat_id)
            
        # Balas callback API jika belum di-return sebelumnya
        telegram_api_request('POST', 'answerCallbackQuery', json={"callback_query_id": callback_id})
        return jsonify({"message": "Callback processed"}), 200

    # 2. Handle Pesan / Command Normal
    message = data.get('message', {})
    text = message.get('text', '')
    chat = message.get('chat', {})
    sender_chat_id = str(chat.get('id', ''))
    
    if sender_chat_id != CHAT_ID:
        logger.warning(f"Akses tidak sah ke perintah bot dari Chat ID: {sender_chat_id}")
        return jsonify({"message": "Unauthorized"}), 200

    # Respon terhadap perintah /dbs
    if text.startswith('/dbs'):
        databases = get_databases()
        
        if databases is None:
            pesan = "❌ <b>Gagal!</b> Tidak dapat terhubung ke database MySQL. Pastikan MySQL menyala."
            send_telegram_notification(pesan)
        elif len(databases) == 0:
            pesan = "🗄️ <b>Database List:</b>\n<i>Tidak ada database yang ditemukan.</i>"
            send_telegram_notification(pesan)
        else:
            header = "🗄️ <b>MySQL Database List:</b>\n━━━━━━━━━━━━━━━━━━━━\n"
            current_chunk = header
            for db in databases:
                line = f"• <code>{html.escape(db)}</code>\n"
                if len(current_chunk) + len(line) > 3800:
                    send_telegram_notification(current_chunk)
                    time.sleep(1)
                    current_chunk = line
                else:
                    current_chunk += line
            if current_chunk:
                send_telegram_notification(current_chunk)
            
    # Respon terhadap perintah /backup
    elif text.startswith('/backup'):
        parts = text.split()
        if len(parts) < 2:
            try:
                send_telegram_notification(
                    "⚠️ <b>Format salah!</b>\n"
                    "Gunakan: <code>/backup [nama_database]</code>\n"
                    "Contoh: <code>/backup capacity_system</code>\n\n"
                    "💡 <i>Ketik /dbs untuk melihat daftar database yang tersedia.</i>"
                )
            except Exception as e:
                logger.error(f"Gagal mengirim pesan error format backup: {e}")
        else:
            db_name = parts[1]
            if not re.match(r'^[a-zA-Z0-9_\-]+$', db_name):
                send_telegram_notification("⚠️ <b>Nama database tidak valid!</b>\nHanya karakter huruf, angka, _ dan - yang diizinkan.")
            else:
                try:
                    safe_db_name = html.escape(db_name)
                    res = send_telegram_notification(f"🔄 <b>Menyiapkan backup...</b>\nDatabase: <code>{safe_db_name}</code>")
                    message_id = res.get('result', {}).get('message_id') if res else None
                    
                    # Jalankan proses backup di thread terpisah agar webhook tidak timeout
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
            
    # Respon perintah /delbackup
    elif text.startswith('/delbackup'):
        pesan = "🗑️ <b>Hapus File Backup</b>\nPilih database untuk mengelola file backup:"
        keyboard = get_delbackup_main_keyboard()
        send_telegram_notification(pesan, reply_markup=keyboard)
            
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
    app.run(host='0.0.0.0', port=5000)