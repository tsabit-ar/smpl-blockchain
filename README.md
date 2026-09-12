# Minimal 2-Node Native Blockchain (Proof of Work)

Implementasi blockchain native terdistribusi (Layer 1) minimal 2-node berbasis Python, Flask, dan Proof of Work (PoW) sesuai spesifikasi PRD.

---

## 🚀 Fitur Utama

- **Genesis Block**: Diinisialisasi secara otomatis (`index: 1`, `previous_hash: "1"`, `proof: 100`).
- **Mempool Transaksi**: Penampungan transaksi sementara berbasis memori sebelum dibungkus ke dalam blok baru.
- **Proof of Work (PoW) Dinamis**: Algoritma PoW memvariasikan field `proof` pada kandidat blok hingga hash SHA-256 blok memenuhi target kesulitan (`0000`).
- **Coinbase Mining Reward**: Menyisipkan transaksi reward sistem (`sender: "0"`, `recipient: node_identifier`, `amount: 1`) ke dalam setiap blok yang berhasil di-mine.
- **Peer Discovery & Peering**: Registrasi node tetangga menggunakan struktur data set unik untuk mencegah duplikasi URL.
- **Validasi Rantai & Konsensus Terdistribusi**: Mengimplementasikan *Longest Chain Rule* untuk menangani percabangan dan divergensi rantai antar-node.
- **Deterministic Hashing**: Serialisasi JSON selalu menggunakan `sort_keys=True` untuk memastikan hash blok konsisten di seluruh platform.
- **Konfigurasi Port Dinamis**: Mendukung port fleksibel via terminal CLI (`python blockchain.py 5000` / `python blockchain.py 5001`).

---

## 📁 Struktur Direktori

```text
smpl-blockchain/
├── blockchain.py       # Core Blockchain logic & Flask REST API Server
├── test_network.py     # Automated End-to-End Acceptance Test script
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

Skrip `test_network.py` akan mengorkestrasikan Node 1 (port 5000) dan Node 2 (port 5001) secara terprogram menggunakan `subprocess.Popen` dengan pembersihan proses otomatis (`terminate`/`kill` pada blok `finally`).

Jalankan:
```bash
python test_network.py
```

Skrip ini menguji 4 skenario acceptance criteria:
1. **Uji Isolasi**: Memvalidasi kedua node memiliki 1 Genesis Block identik.
2. **Uji Peering**: Mendaftarkan node secara mutual dan memverifikasi pencegahan duplikasi.
3. **Uji Divergensi**: Mengirim transaksi dan menambang 2 blok baru di Node 1 (panjang rantai Node 1 = 3, Node 2 = 1).
4. **Uji Konsensus**: Menjalankan `/nodes/resolve` pada Node 2 dan memastikan rantai Node 2 otomatis mengadopsi rantai Node 1 (panjang rantai menjadi 3).

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
| `POST` | `/transactions/new` | Menambahkan transaksi baru ke mempool | `{"sender": "Alice", "recipient": "Bob", "amount": 50}` | `{ "message": "Transaction will be added to Block X" }` (201) |
| `GET` | `/mine` | Menjalankan PoW dan menambang blok baru | *None* | Metadata blok baru (200) |
| `POST` | `/nodes/register` | Mendaftarkan URL node tetangga | `{"nodes": ["http://127.0.0.1:5001"]}` | `{ "message": "New nodes have been added", "total_nodes": [...] }` (201) |
| `GET` | `/nodes/resolve` | Memicu konsensus *Longest Chain Rule* | *None* | Status konsensus & rantai aktif (200) |

### Contoh Pemanggilan API (cURL / PowerShell)

1. **Lihat Rantai**:
   ```bash
   curl -X GET http://127.0.0.1:5000/chain
   ```

2. **Daftarkan Peer**:
   ```bash
   curl -X POST http://127.0.0.1:5000/nodes/register \
     -H "Content-Type: application/json" \
     -d '{"nodes": ["http://127.0.0.1:5001"]}'
   ```

3. **Kirim Transaksi**:
   ```bash
   curl -X POST http://127.0.0.1:5000/transactions/new \
     -H "Content-Type: application/json" \
     -d '{"sender": "Alice", "recipient": "Bob", "amount": 100}'
   ```

4. **Mining Blok Baru**:
   ```bash
   curl -X GET http://127.0.0.1:5000/mine
   ```

5. **Resolusi Konsensus**:
   ```bash
   curl -X GET http://127.0.0.1:5001/nodes/resolve
   ```
