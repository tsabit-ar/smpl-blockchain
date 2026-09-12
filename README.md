# Minimal 2-Node Native Blockchain (Proof of Work & Ethereum JSON-RPC Bridge)

Implementasi blockchain native terdistribusi (Layer 1) minimal 2-node berbasis Python, Flask, dan Proof of Work (PoW) dengan proteksi *Thread Safety*, *Account-Based State Engine*, pencegahan *Double-Spending*, serta **Ethereum JSON-RPC 2.0 Bridge** untuk integrasi langsung ke **MetaMask**.

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
- **Ethereum JSON-RPC 2.0 Bridge (MetaMask Compatible)**:
  - Endpoint `POST /` menangani spesifikasi Ethereum JSON-RPC 2.0.
  - Mendukung `eth_chainId` (1337 / `0x539`), `net_version` (`1337`), `eth_blockNumber`, `eth_getBalance` (format hex Wei), `eth_getTransactionCount` (nonce), `eth_estimateGas` (`0x5208`), `eth_gasPrice` (`0x0`), `eth_sendRawTransaction`, `eth_getBlockByNumber`, `eth_getTransactionReceipt`, dsb.
  - Mendukung decoding transaksi kriptografis secp256k1 offline (Legacy RLP & EIP-1559/EIP-2718 Typed Transactions) via `eth-account`.
- **Persistensi Berkas JSON (Disk Persistence)**:
  - Penyimpanan dinamis per port (`chain_<port>.json`) dengan format terstruktur rapi (`indent=2`).
  - Sinkronisasi otomatis ke disk setiap kali ada blok baru yang ditambahkan (`append_block`) atau saat terjadi reorganisasi konsensus rantai (`resolve_conflicts`).
  - Restorasi state penuh saat node di-shutdown dan dihidupkan kembali (tinggi blok, saldo akun, dan nonce terpulihkan 100%).
- **Proof of Work (PoW) Dinamis**: Algoritma PoW memvariasikan field `proof` pada kandidat blok secara *in-place* hingga hash SHA-256 blok memenuhi target kesulitan (`0000`). Komputasi berat dieksekusi di luar lock.
- **Coinbase Mining Reward**: Menyisipkan transaksi reward sistem (`sender: "0"`, `recipient: node_identifier`, `amount: 1`) ke dalam setiap blok yang berhasil di-mine.
- **Mempool Reorganization & Reconciliation**: Saat reorganisasi rantai (*chain reorganization*), transaksi pada mempool lokal disaring: transaksi yang sudah dicatat pada `new_chain` otomatis dibuang, sedangkan transaksi yatim dari rantai lama lokal yang terbuang dipulihkan kembali ke antrean mempool.
- **Peer Discovery & Peering**: Registrasi node tetangga menggunakan struktur data set unik untuk mencegah duplikasi URL.
- **Validasi Rantai & Tamper Detection**: Mengimplementasikan *Longest Chain Rule* dan verifikasi integritas rantai. Rantai terkorupsi/termanipulasi akan ditolak secara otomatis.
- **Konfigurasi Port Dinamis**: Mendukung port fleksibel via terminal CLI (`python blockchain.py 5000` / `python blockchain.py 5001`).

---

## 🦊 Konfigurasi Jaringan di MetaMask (Add Network Manually)

Untuk menghubungkan MetaMask ke node blockchain lokal ini, buka MetaMask > **Add a network manually**, lalu masukkan parameter berikut:

| Parameter | Nilai |
| :--- | :--- |
| **Network Name** | `SMPL Local Blockchain` |
| **New RPC URL** | `http://127.0.0.1:5000` |
| **Chain ID** | `1337` (Hex: `0x539`) |
| **Currency Symbol** | `SMPL` |
| **Block Explorer URL** | *(Kosongkan)* |

---

## 📁 Struktur Direktori

```text
smpl-blockchain/
├── blockchain.py         # Core Blockchain logic, REST API, & Ethereum JSON-RPC 2.0 Bridge
├── test_persistence.py   # Automated Test untuk JSON Disk Persistence (shutdown & restart)
├── test_network.py       # Automated End-to-End Acceptance Test (6 skenario jaringan terdistribusi)
├── test_metamask_rpc.py  # Automated Test untuk JSON-RPC Bridge & MetaMask compatibility
├── requirements.txt      # Dependensi (Flask, flask-cors, requests, eth-account, web3)
└── README.md             # Dokumentasi teknis & panduan penggunaan
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

## ⚡ Menjalankan Pengujian Otomatis

### 1. Pengujian JSON Disk Persistence (Shutdown & Restart Node)
Menguji inisialisasi file storage, transaksi antar-akun, shutdown node (SIGTERM), restart node pada port yang sama, verifikasi keutuhan rantai, saldo, dan nonce 100%, serta kelanjutan operasi pasca-reboot:
```bash
python test_persistence.py
```

### 2. Pengujian Integrasi MetaMask JSON-RPC 2.0
Menguji kompatibilitas JSON-RPC 2.0, verifikasi Chain ID (1337), pembuatan wallet secp256k1, query saldo hex Wei, signing raw transaction offline, CORS, dan auto-mining:
```bash
python test_metamask_rpc.py
```

### 3. Pengujian Jaringan Terdistribusi & Konsensus (6 Skenario)
Menguji isolasi, peering, divergensi, konsensus terdistribusi, tamper detection, dan double-spending:
```bash
python test_network.py
```

---

## 🌐 Menjalankan Node Secara Manual

Buka terminal:

### Node 1 (Port 5000 - RPC Endpoint MetaMask)
```bash
python blockchain.py 5000
```

### Node 2 (Port 5001 - Peer Node)
```bash
python blockchain.py 5001
```

---

## 📡 Dokumentasi Antarmuka API

### A. Ethereum JSON-RPC 2.0 (`POST /`)
Endpoint tunggal yang memproses format JSON-RPC 2.0 standar:
```json
{
  "jsonrpc": "2.0",
  "method": "eth_getBalance",
  "params": ["0x1FD2dd51b50E5763c6A183818dcc9b97199DaDcA", "latest"],
  "id": 1
}
```

### B. REST API Standar

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
