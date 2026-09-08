# Walkthrough: Fitur List Database via Telegram 🗄️

Fitur pengecekan database lokal Anda sekarang telah terintegrasi langsung dengan Telegram Bot!

## Apa yang Berubah?
1. **PyMySQL Terinstal:** Bot sekarang bisa berkomunikasi langsung dengan MySQL bawaan Laragon Anda menggunakan *environment variable* dari `.env`.
2. **Keamanan Ekstra:** Bot hanya akan membalas jika pesan `/dbs` dikirim dari `CHAT_ID` milik Anda (mencegah orang lain mengecek database Anda).
3. **Endpoint Telegram:** Saya menambahkan route baru di `bot.py` yaitu `POST /telegram` yang berfungsi mendengarkan pesan chat masuk secara real-time.

---

## 🚀 Cara Menghubungkan Telegram ke Bot Lokal (Via Ngrok)

Karena bot Anda berjalan di `localhost`, server Telegram di internet tidak bisa mengirim pesan secara langsung ke komputer Anda. Anda butuh "terowongan" (tunnel) bernama **Ngrok**.

### Langkah 1: Jalankan Bot
Pastikan `bot.py` Anda sudah dijalankan ulang agar memuat kode terbaru:
```bash
python bot.py
```

### Langkah 2: Jalankan Ngrok
Buka terminal **baru** dan jalankan Ngrok ke port 5000 (port bawaan Flask):
```bash
ngrok http 5000
```
*Anda akan melihat layar hitam dengan tulisan **Forwarding** (misal: `https://abcd-123.ngrok.app -> http://localhost:5000`). Salin URL `https://...` tersebut.*

### Langkah 3: Beri Tahu Telegram (Set Webhook)
Buka browser Anda dan jalankan URL di bawah ini. Pastikan Anda mengganti bagian `<TOKEN_BOT>` dengan token asli Anda, dan `<URL_NGROK>` dengan URL Ngrok yang baru saja disalin.

```text
https://api.telegram.org/bot<TOKEN_BOT>/setWebhook?url=<URL_NGROK>/telegram
```

*Contoh:*
`https://api.telegram.org/bot8645148929:AAG0CzsnJV.../setWebhook?url=https://abcd-123.ngrok.app/telegram`

> [!TIP]
> Jika berhasil, browser akan menampilkan: `{"ok":true,"result":true,"description":"Webhook was set"}`

### Langkah 4: Uji Coba!
1. Buka aplikasi Telegram.
2. Buka chat dengan bot Anda.
3. Ketik perintah: `/dbs` lalu kirim.
4. Bot akan otomatis membalas dengan daftar cantik berisi nama-nama database MySQL di Laragon Anda! 🎉
