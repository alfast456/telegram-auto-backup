# GitHub Webhook & MySQL Auto-Backup Bot 🐙 🗄️ ➡️ 📱

Sebuah bot Telegram serbaguna berbasis Python (Flask) yang memiliki dua fungsi utama:
1. Menerima notifikasi webhook dari GitHub ketika ada interaksi pada **Pull Request (PR)**, lalu meneruskannya secara otomatis ke bot Telegram.
2. Mengelola database MySQL (lihat daftar, backup manual, dan penjadwalan auto-backup interaktif) langsung dari Telegram!

## ✨ Fitur Utama

### 🐙 Integrasi GitHub Webhook
- Mendengarkan webhook dari GitHub (Payload `application/json`).
- Validasi keamanan menggunakan HMAC SHA-256 (`X-Hub-Signature-256`).
- Mengirim pesan dengan tampilan HTML yang informatif (termasuk tag repo, link PR, author, branch, dan status Merge/Close).

### 🗄️ Manajemen Database & Auto-Backup
- **Cek Database**: Gunakan perintah `/dbs` di Telegram untuk melihat daftar database MySQL yang tersedia.
- **Backup Manual**: Ketik `/backup [nama_database]` untuk membackup database secara instan. Bot akan mengirimkan progres dan hasil file `.sql` langsung ke chat.
- **Auto-Backup Terjadwal**: 
  - Gunakan `/autobackup` untuk memunculkan antarmuka (UI) **Inline Keyboard** di Telegram. Klik tombol untuk mencentang (✅) atau menghapus (❌) database yang ingin dibackup otomatis.
  - Gunakan `/interval [menit]` untuk mengatur seberapa sering auto-backup berjalan (misalnya `/interval 120` untuk 2 jam sekali).
  - Pengaturan akan disimpan di `config.json` sehingga tidak hilang saat bot di-restart.

## 📋 Persyaratan (Prerequisites)

- Python 3.x
- MySQL Server (`mysqldump` harus terinstall dan masuk ke dalam System PATH)
- Bot Telegram (Dapatkan `TELEGRAM_TOKEN` dari [BotFather](https://t.me/botfather))
- Telegram `CHAT_ID` (Hanya Anda yang bisa mengakses perintah bot ini demi keamanan)

## 🚀 Cara Instalasi

1. **Clone/Download** repository ini.
2. **Buka terminal** di dalam folder proyek ini.
3. **Instal library/dependency** yang dibutuhkan:
   ```bash
   pip install -r requirements.txt
   ```
4. **Buat file `.env`** (bisa copy dari `.env.example` jika ada) dan isi dengan konfigurasi Anda.

## ⚙️ Konfigurasi `.env`

Buat file bernama `.env` di direktori yang sama dengan `bot.py` dan isi dengan:

```env
TELEGRAM_TOKEN=123456789:ABCdefGHIjklMNOpqrsTUVwxyz
CHAT_ID=12345678
GITHUB_WEBHOOK_SECRET=rahasia_webhook_anda

DB_HOST=127.0.0.1
DB_USER=root
DB_PASS=password_database_anda
```

## ▶️ Cara Menjalankan

### Menjalankan Bot
Buka terminal dan jalankan file `bot.py`:
```bash
python bot.py
```
*Server webhook akan berjalan secara lokal di port `5000`.*

### Perintah Telegram
Kirimkan pesan berikut ke bot Telegram Anda:
- `/dbs` - Melihat daftar database MySQL.
- `/backup [nama_database]` - Melakukan backup sekarang juga.
- `/autobackup` - Membuka menu pemilihan database untuk jadwal otomatis.
- `/interval [menit]` - Mengubah jeda waktu auto-backup.

## 🌐 Konfigurasi Webhook di GitHub

1. Buka halaman **Repository GitHub** Anda.
2. Pergi ke tab **Settings** ➡️ **Webhooks** ➡️ **Add webhook**.
3. Isi form:
   - **Payload URL:** `https://domain-anda.com/webhook` *(Gunakan layanan seperti Ngrok/Cloudflare Tunnels jika dijalankan di lokal)*
   - **Content type:** `application/json`
   - **Secret:** Isi sesuai dengan `GITHUB_WEBHOOK_SECRET` di file `.env`.
4. Pada event, pilih **"Let me select individual events."**, lalu centang **Pull requests**.
5. Klik **Add webhook**.

---
*Dibuat menggunakan Python 🐍, Flask 🌶️, dan APScheduler.*
