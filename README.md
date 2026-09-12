# Minimal 2-Node Native Blockchain (Proof of Work)

Implementasi blockchain native terdistribusi (Layer 1) minimal 2-node berbasis Python, Flask, dan Proof of Work (PoW) dengan proteksi *Thread Safety*, *Account-Based State Engine*, serta pencegahan *Double-Spending*.

---

## 🚀 Fitur Utama

- **Genesis Block**: Diinisialisasi secara otomatis (`index: 1`, `previous_hash: "1"`, `proof: 100`).
- **Thread Safety**: Menggunakan `threading.Lock()` untuk memproteksi setiap operasi baca/tulis ke state lokal (`chain`, `current_transactions`, `nodes`).
- **Sistem Saldo Berbasis Akun (Account-Based State Engine)**:
  - Pelacakan saldo dinamis kumulatif via `get_balance(address)`.
  - Transaksi coinbase (`sender: "0"`) menambah saldo penerima.
  - Endpoint publik `GET /balance/<address>` untuk cek saldo real-time.
- **Pencegahan Double-Spending**:
  - Penolakan transaksi jika `get_balance(sender) - pending_spent < amount` dengan HTTP 400 (`"Saldo tidak mencukupi"`).
  - Validasi ketat pada `valid_chain()`: simulasi saldo akun dari blok ke blok. Rantai yang memuat transaksi defisit saldo otomatis ditolak meskipun nilai Proof of Work-nya valid secara matematis.
- **Proof of Work (PoW) Dinamis**: Algoritma PoW memvariasikan field `proof` pada kandidat blok secara *in-place* hingga hash SHA-256 blok memenuhi target kesulitan (`0000`). Komputasi berat dieksekusi di luar lock.
- **Coinbase Mining Reward**: Menyisipkan transaksi reward sistem (`sender: "0"`, `recipient: node_identifier`, `amount: 1`) ke dalam setiap blok yang berhasil di-mine.
- **Mempool Reorganization & Reconciliation**: Saat reorganisasi rantai (*chain reorganization*), transaksi pada mempool lokal disaring: transaksi yang sudah dicatat pada `new_chain` otomatis dibuang, sedangkan transaksi yatim dari rantai lama lokal yang terbuang dipulihkan kembali ke antrean mempool.
- **Peer Discovery & Peering**: Registrasi node tetangga menggunakan struktur data set unik untuk mencegah duplikasi URL.
- **Validasi Rantai & Tamper Detection**: Mengimplementasikan *Longest Chain Rule* dan verifikasi integritas rantai. Rantai terkorupsi/termanipulasi akan ditolak secara otomatis.
- **Deterministic Hashing**: Serialisasi JSON selalu menggunakan `sort_keys=True` untuk memastikan hash blok konsisten di seluruh platform.
- **Konfigurasi Port Dinamis**: Mendukung port fleksibel via terminal CLI (`python blockchain.py 5000` / `python blockchain.py 5001`).

---

## 📁 Struktur Direktori

```text
smpl-blockchain/
├── blockchain.py       # Core Blockchain logic & Flask REST API Server
├── test_network.py     # Automated End-to-End Acceptance Test script (6 skenario)
├── requirements.txt    # Dependensi esensial (Flask, requests)
└── README.md           # Dokumentasi teknis & panduan penggunaan
```

---

## 🛠️ Instalasi & Persiapan

Pastikan Python 3.10+ telah terinstal di sistem Anda.

1. **Clone / Buka Direktori Proyek**:
   ```bash
   cd "c:\Me\BLOCKCHAIN PROJECT\smpl-blockchain"
   ```

2. **Instal Dependensi**:
   ```bash
   python -m pip install -r requirements.txt
   ```

---

## ⚡ Menjalankan Pengujian Otomatis (Acceptance Test)

Skrip `test_network.py` mengorkestrasikan Node 1 (port 5000) dan Node 2 (port 5001) secara terprogram menggunakan `subprocess.Popen` dengan pembersihan proses otomatis (`terminate`/`kill` pada blok `finally`).

Jalankan:
```bash
python test_network.py
```

Skrip ini menguji 6 skenario pengujian:
1. **Uji Isolasi**: Memvalidasi kedua node memiliki 1 Genesis Block identik.
2. **Uji Peering**: Mendaftarkan node secara mutual dan memverifikasi pencegahan duplikasi.
3. **Uji Divergensi**: Mengirim transaksi dan menambang 2 blok baru di Node 1 (panjang rantai Node 1 = 3, Node 2 = 1).
4. **Uji Konsensus**: Menjalankan `/nodes/resolve` pada Node 2 dan memastikan rantai Node 2 otomatis mengadopsi rantai Node 1 (panjang rantai menjadi 3).
5. **Uji Integritas / Tamper Detection & Mempool Reconciliation**:
   - Menolak rantai manipulasi/korup dari rogue peer (`valid_chain()` mengembalikan `False` dan `/nodes/resolve` mempertahankan status authoritative).
   - Memvalidasi pembersihan transaksi identik dari mempool Node 2 setelah sinkronisasi blok baru dari Node 1.
6. **Uji Saldo & Double-Spending**:
   - Penolakan transfer dari saldo 0 (HTTP 400).
   - Transfer valid dengan saldo yang mencukupi (HTTP 201).
   - Penolakan percobaan double-spending saat saldo terikat di mempool (HTTP 400).
   - Penolakan rantai rogue peer yang memiliki PoW valid tetapi memuat transaksi dengan saldo defisit saat konsensus.

---

## 🌐 Menjalankan Node Secara Manual

Buka dua jendela terminal terpisah:

### Terminal 1 (Node 1 - Port 5000)
```bash
python blockchain.py 5000
```

### Terminal 2 (Node 2 - Port 5001)
```bash
python blockchain.py 5001
```

---

## 📡 Dokumentasi REST API

| Method | Endpoint | Deskripsi | Input JSON | Output Sukses |
| :--- | :--- | :--- | :--- | :--- |
| `GET` | `/chain` | Mengambil seluruh salinan rantai lokal | *None* | `{ "chain": [...], "length": n }` (200) |
| `GET` | `/balance/<address>` | Mengambil saldo akun dari rantai lokal | *None* | `{ "address": "...", "balance": n }` (200) |
| `GET` | `/mempool` | Mengambil transaksi yang antre di mempool | *None* | `{ "mempool": [...], "length": n }` (200) |
| `GET` | `/node/id` | Mengambil identifier unik node | *None* | `{ "node_identifier": "..." }` (200) |
| `POST` | `/transactions/new` | Menambahkan transaksi baru ke mempool | `{"sender": "Alice", "recipient": "Bob", "amount": 1}` | `{ "message": "Transaction will be added to Block X" }` (201) / Gagal: `{ "message": "Saldo tidak mencukupi" }` (400) |
| `GET` | `/mine` | Menjalankan PoW dan menambang blok baru | *None* | Metadata blok baru (200) |
| `POST` | `/nodes/register` | Mendaftarkan URL node tetangga | `{"nodes": ["http://127.0.0.1:5001"]}` | `{ "message": "New nodes have been added", "total_nodes": [...] }` (201) |
| `GET` | `/nodes/resolve` | Memicu konsensus *Longest Chain Rule* | *None* | Status konsensus & rantai aktif (200) |
