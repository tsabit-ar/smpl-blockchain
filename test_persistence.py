import json
import os
import subprocess
import sys
import time
from eth_account import Account
import requests
from web3 import Web3

PORT = 5555
NODE_URL = f"http://127.0.0.1:{PORT}"
STORAGE_FILE = f"chain_{PORT}.json"


def wait_for_node(url, timeout=15):
    """Menunggu hingga node siap merespons permintaan HTTP/RPC."""
    start_time = time.time()
    while time.time() - start_time < timeout:
        try:
            res = requests.get(f"{url}/chain", timeout=1)
            if res.status_code == 200:
                return True
        except requests.RequestException:
            pass
        time.sleep(0.3)
    return False


def rpc_call(method, params=None, req_id=1):
    """Fungsi pembantu untuk memanggil Ethereum JSON-RPC 2.0."""
    payload = {
        "jsonrpc": "2.0",
        "method": method,
        "params": params if params is not None else [],
        "id": req_id
    }
    response = requests.post(NODE_URL, json=payload, timeout=5)
    assert response.status_code == 200, f"HTTP Error {response.status_code}: {response.text}"
    data = response.json()
    if "error" in data:
        raise RuntimeError(f"RPC Error [{data['error'].get('code')}]: {data['error'].get('message')}")
    return data.get("result")


def run_persistence_tests():
    print("==================================================================")
    print("   MEMULAI PENGUJIAN OTOMATIS: JSON DISK PERSISTENCE              ")
    print("==================================================================\n")

    # Bersihkan file persistensi sebelum pengujian dimulai
    if os.path.exists(STORAGE_FILE):
        try:
            os.remove(STORAGE_FILE)
        except OSError:
            pass

    script_path = os.path.abspath("blockchain.py")
    p = None

    try:
        # ----------------------------------------------------------------------
        # Skenario 1: Boot Awal Node dan Pembuatan Storage File
        # ----------------------------------------------------------------------
        print(f"[1/6] Menjalankan Node Blockchain baru pada Port {PORT}...")
        p = subprocess.Popen(
            [sys.executable, script_path, str(PORT)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )

        if not wait_for_node(NODE_URL):
            raise RuntimeError(f"Gagal menginisialisasi node pada port {PORT}!")
        print(f"      [+] Node berhasil aktif pada port {PORT}.")

        # Verifikasi storage file dibuat saat boot awal (Genesis Block disimpan)
        time.sleep(0.5)
        assert os.path.exists(STORAGE_FILE), f"File persistensi {STORAGE_FILE} harus dibuat saat inisialisasi!"
        with open(STORAGE_FILE, "r", encoding="utf-8") as f:
            disk_chain = json.load(f)
        assert len(disk_chain) == 1, f"Chain awal di disk harus berisi 1 genesis block, got {len(disk_chain)}"
        assert disk_chain[0]["index"] == 1
        print(f"      [+] File persistensi {STORAGE_FILE} terkonfirmasi ada dengan 1 Genesis Block.")
        print("      [PASSED] Skenario 1: Boot awal dan inisialisasi storage berhasil.\n")

        # ----------------------------------------------------------------------
        # Skenario 2: Transaksi, Mining, dan Mutasi State (Balance & Nonce)
        # ----------------------------------------------------------------------
        print("[2/6] Mempersiapkan akun & melakukan transaksi berantai...")
        alice = Account.create()
        bob = Account.create()
        print(f"      [i] Alice Address: {alice.address}")
        print(f"      [i] Bob Address:   {bob.address}")

        # Klaim faucet untuk Alice (10 SMPL)
        res_faucet = requests.get(f"{NODE_URL}/faucet/{alice.address}").json()
        assert res_faucet["balance"] == 10
        print(f"      [+] Faucet 10 SMPL berhasil dikirim ke Alice. Blok baru di-mine.")

        # Buat raw transaction: Alice mengirim 3 SMPL ke Bob (Chain ID: 1337)
        tx = {
            'nonce': 0,
            'gasPrice': Web3.to_wei('1', 'gwei'),
            'gas': 21000,
            'to': bob.address,
            'value': Web3.to_wei(3, 'ether'),
            'data': b'',
            'chainId': 1337
        }
        signed_tx = alice.sign_transaction(tx)
        tx_hash = rpc_call("eth_sendRawTransaction", [signed_tx.raw_transaction.hex()])
        print(f"      [+] Transaksi 3 SMPL dikirim & di-auto-mine. Hash: {tx_hash}")

        # Snapshot state sebelum shutdown
        chain_data = requests.get(f"{NODE_URL}/chain").json()
        pre_height = chain_data["length"]
        pre_chain = chain_data["chain"]

        alice_bal_pre = requests.get(f"{NODE_URL}/balance/{alice.address}").json()["balance"]
        bob_bal_pre = requests.get(f"{NODE_URL}/balance/{bob.address}").json()["balance"]
        alice_nonce_pre = int(rpc_call("eth_getTransactionCount", [alice.address, "latest"]), 16)

        assert pre_height == 3, f"Tinggi rantai sebelum shutdown harus 3, got {pre_height}"
        assert alice_bal_pre == 7, f"Saldo Alice sebelum shutdown harus 7, got {alice_bal_pre}"
        assert bob_bal_pre == 3, f"Saldo Bob sebelum shutdown harus 3, got {bob_bal_pre}"
        assert alice_nonce_pre == 1, f"Nonce Alice sebelum shutdown harus 1, got {alice_nonce_pre}"

        print(f"      [i] State Sebelum Shutdown: Tinggi={pre_height}, Saldo Alice={alice_bal_pre}, Saldo Bob={bob_bal_pre}, Nonce Alice={alice_nonce_pre}")
        print("      [PASSED] Skenario 2: Mutasi state dan auto-mining berhasil.\n")

        # ----------------------------------------------------------------------
        # Skenario 3: Verifikasi Integritas File JSON di Disk Sebelum Shutdown
        # ----------------------------------------------------------------------
        print(f"[3/6] Memeriksa isi berkas {STORAGE_FILE} sebelum node dimatikan...")
        with open(STORAGE_FILE, "r", encoding="utf-8") as f:
            disk_data = json.load(f)
        assert len(disk_data) == 3, f"Berkas {STORAGE_FILE} harus berisi 3 blok, got {len(disk_data)}"
        assert disk_data[-1]["index"] == 3
        print(f"      [+] Berkas {STORAGE_FILE} konsisten dengan 3 blok tersimpan.")
        print("      [PASSED] Skenario 3: Sinkronisasi storage otomatis terverifikasi.\n")

        # ----------------------------------------------------------------------
        # Skenario 4: Shutdown Node (Terminasi Proses)
        # ----------------------------------------------------------------------
        print("[4/6] Mematikan (shutdown) proses Node...")
        p.terminate()
        try:
            p.wait(timeout=3)
        except subprocess.TimeoutExpired:
            p.kill()
            p.wait(timeout=2)
        p = None

        # Pastikan node benar-benar offline
        node_offline = False
        try:
            requests.get(f"{NODE_URL}/chain", timeout=1)
        except requests.RequestException:
            node_offline = True
        assert node_offline, "Node harus offline setelah proses dimatikan!"
        print("      [+] Node berhasil dimatikan secara bersih. Server offline.")
        print("      [PASSED] Skenario 4: Node shutdown berhasil.\n")

        # ----------------------------------------------------------------------
        # Skenario 5: Restart Node & Verifikasi 100% Persistensi State
        # ----------------------------------------------------------------------
        print(f"[5/6] Me-restart Node pada port yang sama ({PORT})...")
        p = subprocess.Popen(
            [sys.executable, script_path, str(PORT)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )

        if not wait_for_node(NODE_URL):
            raise RuntimeError(f"Gagal me-restart node pada port {PORT}!")
        print("      [+] Node berhasil di-restart dan aktif kembali.")

        # Ambil state pasca-restart
        post_chain_data = requests.get(f"{NODE_URL}/chain").json()
        post_height = post_chain_data["length"]
        post_chain = post_chain_data["chain"]

        alice_bal_post = requests.get(f"{NODE_URL}/balance/{alice.address}").json()["balance"]
        bob_bal_post = requests.get(f"{NODE_URL}/balance/{bob.address}").json()["balance"]
        alice_nonce_post = int(rpc_call("eth_getTransactionCount", [alice.address, "latest"]), 16)

        # Verifikasi tinggi rantai
        assert post_height == pre_height == 3, (
            f"Tinggi rantai harus tetap {pre_height}, got {post_height}"
        )
        # Verifikasi integritas setiap blok
        for idx in range(post_height):
            b_pre = pre_chain[idx]
            b_post = post_chain[idx]
            assert b_pre["index"] == b_post["index"], f"Block index mismatch pada index {idx}"
            assert b_pre["previous_hash"] == b_post["previous_hash"], f"previous_hash mismatch pada index {idx}"
            assert b_pre["proof"] == b_post["proof"], f"proof mismatch pada index {idx}"
            assert b_pre["transactions"] == b_post["transactions"], f"transactions mismatch pada index {idx}"

        # Verifikasi saldo dan nonce
        assert alice_bal_post == alice_bal_pre == 7, (
            f"Saldo Alice harus tetap 7, got {alice_bal_post}"
        )
        assert bob_bal_post == bob_bal_pre == 3, (
            f"Saldo Bob harus tetap 3, got {bob_bal_post}"
        )
        assert alice_nonce_post == alice_nonce_pre == 1, (
            f"Nonce Alice harus tetap 1, got {alice_nonce_post}"
        )

        print(f"      [+] Tinggi Rantai: {post_height} (Persisten 100%)")
        print(f"      [+] Saldo Alice:   {alice_bal_post} SMPL (Persisten 100%)")
        print(f"      [+] Saldo Bob:     {bob_bal_post} SMPL (Persisten 100%)")
        print(f"      [+] Nonce Alice:   {alice_nonce_post} (Persisten 100%)")
        print("      [PASSED] Skenario 5: Seluruh state terestorasi sempurna pasca-restart.\n")

        # ----------------------------------------------------------------------
        # Skenario 6: Kelanjutan Operasi Rantai Pasca-Restart
        # ----------------------------------------------------------------------
        print("[6/6] Menguji kelanjutan transaksi & auto-mining pada node yang direstart...")
        tx2 = {
            'nonce': 1,  # Nonce kedua Alice
            'gasPrice': Web3.to_wei('1', 'gwei'),
            'gas': 21000,
            'to': bob.address,
            'value': Web3.to_wei(2, 'ether'),
            'data': b'',
            'chainId': 1337
        }
        signed_tx2 = alice.sign_transaction(tx2)
        tx_hash2 = rpc_call("eth_sendRawTransaction", [signed_tx2.raw_transaction.hex()])
        print(f"      [+] Transaksi kedua dikirim dengan nonce 1. Hash: {tx_hash2}")

        alice_bal_final = requests.get(f"{NODE_URL}/balance/{alice.address}").json()["balance"]
        bob_bal_final = requests.get(f"{NODE_URL}/balance/{bob.address}").json()["balance"]
        alice_nonce_final = int(rpc_call("eth_getTransactionCount", [alice.address, "latest"]), 16)
        chain_final = requests.get(f"{NODE_URL}/chain").json()

        assert chain_final["length"] == 4, f"Chain length harus bertambah menjadi 4, got {chain_final['length']}"
        assert alice_bal_final == 5, f"Saldo akhir Alice harus 5 SMPL, got {alice_bal_final}"
        assert bob_bal_final == 5, f"Saldo akhir Bob harus 5 SMPL, got {bob_bal_final}"
        assert alice_nonce_final == 2, f"Nonce akhir Alice harus 2, got {alice_nonce_final}"

        # Verifikasi file di disk juga terupdate ke 4 blok
        with open(STORAGE_FILE, "r", encoding="utf-8") as f:
            disk_final = json.load(f)
        assert len(disk_final) == 4, f"File persistensi di disk harus memuat 4 blok, got {len(disk_final)}"

        print(f"      [+] Blok ke-4 berhasil di-mine dan disimpan ke {STORAGE_FILE}.")
        print(f"      [+] Saldo Akhir: Alice={alice_bal_final} SMPL, Bob={bob_bal_final} SMPL, Nonce Alice={alice_nonce_final}")
        print("      [PASSED] Skenario 6: Operasi lanjutan pasca-restart sukses.\n")

        print("==================================================================")
        print("   SELURUH PENGUJIAN JSON DISK PERSISTENCE (100%) SUKSES!         ")
        print("==================================================================")

    finally:
        if p and p.poll() is None:
            print("\n[CLEANUP] Menghentikan proses node...")
            p.terminate()
            try:
                p.wait(timeout=3)
            except subprocess.TimeoutExpired:
                p.kill()
            print("          Node berhasil dimatikan.")

        if os.path.exists(STORAGE_FILE):
            try:
                os.remove(STORAGE_FILE)
                print(f"          Berkas pengujian {STORAGE_FILE} berhasil dibersihkan.")
            except OSError:
                pass


if __name__ == "__main__":
    run_persistence_tests()
