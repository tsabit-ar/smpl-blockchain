# Minimal 2-Node Native Blockchain with Ethereum JSON-RPC 2.0 Bridge (PoW Layer-1)

Implementasi blockchain Layer-1 independen berbasis Python dengan konsensus Proof of Work (PoW) terdistribusi (*Longest Chain Rule*), state akun berbasis nonce (*Account-Based State Engine*), persistensi disk atomik anti-korupsi, serta kompatibilitas native dompet Web3 (**MetaMask**) melalui **Ethereum JSON-RPC 2.0 Bridge**.

---

## 🏛️ Arsitektur Inti

- **Consensus**:
  - Proof of Work (PoW) menggunakan fungsi hash kriptografi SHA-256 dengan target kesulitan 4 leading zeros (`0000`).
  - Resolusi konflik rantai terdistribusi menggunakan aturan rantai terpanjang (*Longest Chain Rule*) dengan validasi integritas struktur rantai dan riwayat saldo akun.
- **Cryptography**:
  - Kurva eliptik **secp256k1** (ECDSA) untuk verifikasi tanda tangan digital transaksi offline.
  - Kompatibilitas format alamat Ethereum (Keccak-256) serta dukungan decoding transaksi *Legacy RLP* dan *EIP-2718/EIP-1559 Typed Transactions* via `eth-account`.
- **Account State & Double-Spending Prevention**:
  - Mesin saldo berbasis akun (*Account-Based State Engine*) dengan pelacakan transaksi terkonfirmasi dan nonce akun (`eth_getTransactionCount`).
  - Validasi saldo seketika di mempool dan penolakan rantai yang memuat transaksi defisit saldo pada `valid_chain()`.
- **Persistence**:
  - Penyimpanan berkas JSON disk atomik (`os.replace` & `os.fsync`) terisolasi per port node (`chain_<port>.json` dan `nodes_<port>.json`).
  - Menjamin ketahanan 100% terhadap crash mendadak tanpa risiko berkas korup, serta memulihkan tinggi blok, riwayat transaksi, saldo, nonce, dan daftar peers saat restart.
- **Networking & Propagation**:
  - Peering terdistribusi dengan auto-broadcast blok baru ke endpoint `POST /block/receive` seluruh tetangga secara real-time.
  - Mekanisme rekonsiliasi mempool otomatis saat reorganisasi rantai atau penerimaan blok baru.
  - Proteksi thread safety menggunakan `threading.Lock()` pada seluruh operasi baca/tulis state blockchain.

---

## 🛠️ Panduan Instalasi & Eksekusi

### 1. Prasyarat Sistem
Pastikan Python 3.10 atau versi yang lebih baru telah terinstal pada sistem Anda.

### 2. Persiapan Environment & Dependensi
Buka terminal dan jalankan langkah-langkah berikut:

```bash
# 1. Masuk ke direktori proyek
cd "c:\Me\BLOCKCHAIN PROJECT\smpl-blockchain"

# 2. (Opsional) Buat dan aktifkan virtual environment
python -m venv .venv
.venv\Scripts\activate  # Windows

# 3. Instal dependensi yang dibutuhkan
pip install -r requirements.txt
```

### 3. Menjalankan Node Blockchain Secara Manual

Buka dua jendela terminal terpisah untuk menjalankan minimal 2 node terdistribusi:

#### Node 1 (Port 5000 - Endpoint Utama & JSON-RPC Bridge MetaMask)
```bash
python blockchain.py 5000
```

#### Node 2 (Port 5001 - Peer Node Terdistribusi)
```bash
python blockchain.py 5001
```

---

## 🦊 Konfigurasi Dompet MetaMask

Untuk menghubungkan dompet MetaMask langsung ke node blockchain lokal ini, buka MetaMask > **Settings** > **Networks** > **Add a network manually**, lalu masukkan parameter konfigurasi berikut:

| Parameter Konfigurasi | Nilai Pengaturan |
| :--- | :--- |
| **Network Name** | `SMPL Local Blockchain` |
| **New RPC URL** | `http://127.0.0.1:5000` |
| **Chain ID** | `1337` (Hex: `0x539`) |
| **Currency Symbol** | `SMPL` |
| **Block Explorer URL** | *(Biarkan kosong)* |

### Endpoint Faucet (Klaim Koin Testnet Gratis)
Untuk mendanai akun MetaMask baru dengan 10 koin SMPL ($10 \times 10^{18}\text{ Wei}$), buka browser atau panggil via HTTP GET:
```text
http://127.0.0.1:5000/faucet/<ALAMAT_METAMASK>
```
*Contoh:*
```bash
curl http://127.0.0.1:5000/faucet/0x742d35Cc6634C0532925a3b844Bc454e4438f44e
```
*Koin akan dicetak secara instan, ditambang ke blok baru, dan saldo di dompet MetaMask Anda akan langsung bertambah.*

---

## 📡 Daftar Endpoint API Lengkap

### 1. REST Endpoints (HTTP API)

| Method | Endpoint | Deskripsi | Input JSON | Status / Output Sukses |
| :--- | :--- | :--- | :--- | :--- |
| `GET` | `/chain` | Mengambil seluruh salinan rantai blok lokal | *None* | `200` `{ "chain": [...], "length": n }` |
| `POST` | `/transactions/new` | Menambahkan transaksi baru ke mempool lokal | `{"sender": "...", "recipient": "...", "amount": n}` | `201` `{ "message": "Transaction will be added to Block X" }` |
| `GET` | `/mine` | Menjalankan algoritma PoW dan menambang blok baru | *None* | `200` Metadata blok baru yang berhasil ditempa |
| `POST` | `/block/receive` | Menerima & memvalidasi blok baru via Real-Time Broadcast | Payload Object Blok Lengkap | `201` `{ "message": "Block received and appended", "index": n, "hash": "..." }` |
| `POST` | `/nodes/register` | Mendaftarkan URL node tetangga baru ke daftar peers | `{"nodes": ["http://127.0.0.1:5001"]}` | `201` `{ "message": "New nodes have been added", "total_nodes": [...] }` |
| `POST` | `/nodes/unregister` | Menghapus URL node tetangga dari daftar peers | `{"nodes": ["http://127.0.0.1:5001"]}` | `200` `{ "message": "Nodes have been removed", "total_nodes": [...] }` |
| `GET` | `/nodes/resolve` | Memicu konsensus *Longest Chain Rule* terhadap seluruh tetangga | *None* | `200` `{ "message": "Our chain was replaced" / "Our chain is authoritative", ... }` |
| `GET` | `/balance/<address>` | Mengambil total saldo koin terkini dari alamat yang ditentukan | *None* | `200` `{ "address": "...", "balance": n }` |
| `GET` | `/faucet/<address>` | Mencetak 10 SMPL langsung ke alamat tujuan dan menambang blok | *None* | `200` `{ "message": "10 SMPL successfully minted...", "balance": n }` |
| `GET` | `/mempool` | Mengambil daftar transaksi yang sedang mengantre di mempool | *None* | `200` `{ "mempool": [...], "length": n }` |
| `GET` | `/node/id` | Mengambil identitas unik node lokal (penerima reward coinbase) | *None* | `200` `{ "node_identifier": "..." }` |

### 2. Ethereum JSON-RPC 2.0 Methods (`POST /`)

Endpoint tunggal `POST /` (mendukung preflight CORS `OPTIONS`) yang melayani spesifikasi Ethereum JSON-RPC 2.0 untuk komunikasi langsung dengan ekstensi dompet Web3:

| Method JSON-RPC 2.0 | Deskripsi & Respons |
| :--- | :--- |
| `eth_chainId` | Mengembalikan Chain ID jaringan dalam hex: `"0x539"` (Desimal: 1337). |
| `net_version` | Mengembalikan Network Version ID dalam string desimal: `"1337"`. |
| `eth_blockNumber` | Mengembalikan tinggi blok rantai saat ini dalam format hex (misal `"0x5"`). |
| `eth_getBalance` | Mengembalikan saldo akun dalam format integer hex Wei ($1\text{ SMPL} = 10^{18}\text{ Wei}$). |
| `eth_getTransactionCount` | Mengembalikan nonce akun (jumlah transaksi keluar yang telah terkonfirmasi + pending). |
| `eth_sendRawTransaction` | Mendekode transaksi secp256k1 offline, memvalidasi saldo, dan melakukan **auto-mining** instan ke blok baru. |
| `eth_getBlockByNumber` | Mengembalikan data detail blok spesifik atau blok terbaru (`"latest"`). |
| `eth_getTransactionReceipt`| Mengembalikan receipt transaksi dengan status `"0x1"` (Sukses) setelah blok di-mine. |
| `eth_estimateGas` | Mengembalikan estimasi gas dasar standar: `"0x5208"` (21.000 gas). |
| `eth_gasPrice` | Mengembalikan estimasi harga gas jaringan: `"0x0"`. |
| `eth_syncing` | Mengembalikan status sinkronisasi node: `false`. |
| `eth_feeHistory` | Mengembalikan riwayat biaya EIP-1559 dummy statis dengan `baseFeePerGas: ["0x0", "0x0"]`. |
| *(Fallback RPC)* | Seluruh method RPC lain yang belum dikenali mengembalikan `"0x0"` untuk mencegah error HTTP 500 di MetaMask. |

---

## 🧪 Panduan Pengujian Otomatis

Proyek ini dilengkapi dengan 3 berkas suite pengujian otomatis menyeluruh untuk menjamin keandalan fungsional:

### 1. Pengujian Jaringan & Konsensus Terdistribusi (8 Skenario)
Menguji isolasi, peering, divergensi, konsensus terdistribusi, tamper detection, double-spending, persistensi peers, dan propagasi real-time block broadcast:
```bash
python test_network.py
```

### 2. Pengujian Persistensi Disk Atomik (6 Skenario)
Menguji inisialisasi penyimpanan atomik, mutasi state berantai, validasi integritas file JSON di disk, penghentian proses node (*SIGTERM shutdown*), *restart* node pada port yang sama, restorasi state rantai 100%, serta kelanjutan transaksi pasca-reboot:
```bash
python test_persistence.py
```

### 3. Pengujian Integrasi MetaMask JSON-RPC 2.0 (7 Skenario)
Menguji penanganan header CORS preflight, query Chain ID (1337), pembuatan wallet secp256k1 lokal, klaim faucet, auto-mining transaksi tertanda tangan, handler fallback RPC, dan verifikasi receipt:
```bash
python test_metamask_rpc.py
```

---

## 📁 Struktur Direktori Proyek

```text
smpl-blockchain/
├── blockchain.py         # Core Blockchain engine, REST API, & Ethereum JSON-RPC 2.0 Bridge
├── test_network.py       # Automated End-to-End Acceptance Test (8 skenario jaringan terdistribusi & broadcast)
├── test_persistence.py   # Automated Test untuk JSON Disk Persistence (shutdown & restart atomik)
├── test_metamask_rpc.py  # Automated Test untuk JSON-RPC Bridge & MetaMask compatibility
├── requirements.txt      # Dependensi proyek (Flask, flask-cors, requests, eth-account, web3)
└── README.md             # Dokumentasi teknis komprehensif & panduan penggunaan
```
