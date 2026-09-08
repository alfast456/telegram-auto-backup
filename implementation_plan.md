# Fitur Baru: List Database MySQL 🗄️

Untuk menambahkan fitur ini ke dalam bot kita, ada dua hal utama yang harus dilakukan:
1. Membuat bot Python bisa membaca database MySQL Anda.
2. Membuat "pemicu" (trigger) agar bot mengirimkan daftar tersebut ke Telegram.

## ⚠️ User Review Required

Silakan baca rancangan di bawah ini dan berikan feedback jika ada yang ingin diubah. Klik **Proceed** jika Anda setuju!

## ❓ Open Questions (Penting!)

**Bagaimana Anda ingin memicu pengiriman daftar database ini?**
- **Opsi A (Via Endpoint URL):** Anda cukup membuka `http://localhost:5000/send-dbs` di browser, lalu bot akan mengirim list database ke Telegram Anda. (Sangat mudah, tidak perlu set-up ribet).
- **Opsi B (Via Chat Telegram):** Anda mengetik `/dbs` langsung di chat Telegram, lalu bot membalas dengan daftarnya. *(Catatan: Karena bot Anda butuh URL publik untuk menerima chat masuk dari Telegram, Anda wajib menggunakan aplikasi seperti **Ngrok** atau **Cloudflare Tunnel** agar Telegram bisa menghubungi `localhost` Anda).*

*Tolong balas pesan ini dengan **Opsi A** atau **Opsi B** agar saya tahu cara mana yang Anda inginkan.*

## 🛠️ Proposed Changes

### [Component: Dependencies]

#### [MODIFY] `requirements.txt`
- Menambahkan `PyMySQL` untuk menghubungkan Python ke server MySQL lokal (Laragon).

### [Component: Konfigurasi]

#### [MODIFY] `.env` & `.env.example`
- Menambahkan konfigurasi database (Host, User, Password). Secara default untuk Laragon:
  - `DB_HOST=127.0.0.1`
  - `DB_USER=root`
  - `DB_PASS=` (kosong)

### [Component: Main Bot Script]

#### [MODIFY] `bot.py`
- Mengimpor `pymysql`.
- Menambahkan fungsi `get_databases()` yang melakukan query `SHOW DATABASES;` ke MySQL dan memformat hasilnya (menyaring database sistem seperti `information_schema`).
- **Tergantung Opsi Anda (A/B):** Menambahkan route Flask `/send-dbs` (Opsi A) atau route `/telegram` untuk webhook Telegram (Opsi B).
- Mengirim pesan ke Telegram dengan format rapi (menggunakan Markdown atau HTML) berupa list database.

---
## 🔍 Verification Plan
1. Menginstal `pymysql`.
2. Menjalankan `bot.py`.
3. Menjalankan trigger (via URL lokal atau Ngrok) untuk memastikan pesan berisi list database sukses masuk ke chat Telegram Anda!
