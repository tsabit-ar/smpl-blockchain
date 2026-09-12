import copy
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import os
import subprocess
import sys
import threading
import time
import requests
from blockchain import Blockchain

NODE1_URL = "http://127.0.0.1:5000"
NODE2_URL = "http://127.0.0.1:5001"
ROGUE_PORT = 5002
ROGUE_URL = f"http://127.0.0.1:{ROGUE_PORT}"


def wait_for_node(url, timeout=15):
    """Menunggu hingga node siap merespons permintaan HTTP."""
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


def run_tests():
    print("==================================================================")
    print("   MEMULAI PENGUJIAN OTOMATIS: MINIMAL 2-NODE BLOCKCHAIN          ")
    print("==================================================================\n")

    p1 = None
    p2 = None
    rogue_server = None

    try:
        # Menjalankan Node 1 (Port 5000) dan Node 2 (Port 5001) via subprocess
        script_path = os.path.abspath("blockchain.py")
        print("[1/7] Menjalankan Node 1 (Port 5000) & Node 2 (Port 5001)...")
        p1 = subprocess.Popen(
            [sys.executable, script_path, "5000"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
        p2 = subprocess.Popen(
            [sys.executable, script_path, "5001"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )

        # Health check
        print("      Menunggu inisialisasi jaringan node...")
        if not wait_for_node(NODE1_URL) or not wait_for_node(NODE2_URL):
            raise RuntimeError("Gagal menginisialisasi salah satu atau kedua node!")
        print("      [+] Kedua node berhasil berjalan dan merespons.\n")

        # Ambil identifier masing-masing node
        node1_id = requests.get(f"{NODE1_URL}/node/id").json()["node_identifier"]
        node2_id = requests.get(f"{NODE2_URL}/node/id").json()["node_identifier"]
        print(f"      [i] Node 1 Identifier: {node1_id}")
        print(f"      [i] Node 2 Identifier: {node2_id}\n")

        # ----------------------------------------------------------------------
        # Skenario 1: Uji Isolasi
        # ----------------------------------------------------------------------
        print("[2/7] Menjalankan Skenario 1: UJI ISOLASI")
        r1 = requests.get(f"{NODE1_URL}/chain")
        r2 = requests.get(f"{NODE2_URL}/chain")
        assert r1.status_code == 200, f"Node 1 /chain return code {r1.status_code}"
        assert r2.status_code == 200, f"Node 2 /chain return code {r2.status_code}"

        d1 = r1.json()
        d2 = r2.json()
        assert d1["length"] == 1, f"Panjang rantai Node 1 harus 1, didapat {d1['length']}"
        assert d2["length"] == 1, f"Panjang rantai Node 2 harus 1, didapat {d2['length']}"

        genesis1 = d1["chain"][0]
        genesis2 = d2["chain"][0]
        assert genesis1["previous_hash"] == "1", "Genesis previous_hash harus '1'"
        assert genesis1["proof"] == 100, "Genesis proof harus 100"
        assert genesis2["previous_hash"] == "1", "Genesis previous_hash harus '1'"
        assert genesis2["proof"] == 100, "Genesis proof harus 100"

        print("      [+] Node 1 & Node 2 masing-masing memiliki 1 Genesis block identik.")
        print("      [PASSED] Skenario 1: Uji Isolasi berhasil.\n")

        # ----------------------------------------------------------------------
        # Skenario 2: Uji Peering
        # ----------------------------------------------------------------------
        print("[3/7] Menjalankan Skenario 2: UJI PEERING")
        # Daftarkan Node 2 ke Node 1
        reg1 = requests.post(f"{NODE1_URL}/nodes/register", json={"nodes": [NODE2_URL]})
        assert reg1.status_code == 201, f"Gagal registrasi peer di Node 1: {reg1.text}"
        assert NODE2_URL in reg1.json()["total_nodes"]

        # Daftarkan Node 1 ke Node 2
        reg2 = requests.post(f"{NODE2_URL}/nodes/register", json={"nodes": [NODE1_URL]})
        assert reg2.status_code == 201, f"Gagal registrasi peer di Node 2: {reg2.text}"
        assert NODE1_URL in reg2.json()["total_nodes"]

        # Uji idempoten / tanpa duplikasi
        reg1_dup = requests.post(f"{NODE1_URL}/nodes/register", json={"nodes": [NODE2_URL]})
        assert len(reg1_dup.json()["total_nodes"]) == 1, "Struktur data set harus mencegah duplikasi"

        print(f"      [+] Node 1 peers: {reg1.json()['total_nodes']}")
        print(f"      [+] Node 2 peers: {reg2.json()['total_nodes']}")
        print("      [PASSED] Skenario 2: Uji Peering berhasil tanpa duplikasi.\n")

        # ----------------------------------------------------------------------
        # Skenario 3: Uji Divergensi
        # ----------------------------------------------------------------------
        print("[4/7] Menjalankan Skenario 3: UJI DIVERGENSI")
        # Mine Blok 2 di Node 1 untuk memperoleh saldo reward pertama (1 koin ke node1_id)
        print("      Mining Blok 2 di Node 1 (Coinbase Reward)...")
        m1 = requests.get(f"{NODE1_URL}/mine")
        assert m1.status_code == 200, f"Gagal mining Blok 2: {m1.text}"
        b2 = m1.json()
        print(f"      -> Blok 2 ditempa | Index: {b2['index']}, Proof: {b2['proof']}")

        # Saldo node1_id sekarang 1 koin, transfer 1 koin ke "Dave"
        tx_dave = requests.post(
            f"{NODE1_URL}/transactions/new",
            json={"sender": node1_id, "recipient": "Dave", "amount": 1}
        )
        assert tx_dave.status_code == 201, f"Gagal transfer ke Dave: {tx_dave.text}"
        print("      [+] Transfer 1 koin dari Node 1 ke Dave berhasil masuk mempool.")

        # Mine Blok 3 di Node 1
        print("      Mining Blok 3 di Node 1 (Konfirmasi transfer Dave)...")
        m2 = requests.get(f"{NODE1_URL}/mine")
        assert m2.status_code == 200, f"Gagal mining Blok 3: {m2.text}"
        b3 = m2.json()
        print(f"      -> Blok 3 ditempa | Index: {b3['index']}, Proof: {b3['proof']}")

        # Verifikasi Divergensi panjang rantai
        c1 = requests.get(f"{NODE1_URL}/chain").json()
        c2 = requests.get(f"{NODE2_URL}/chain").json()

        assert c1["length"] == 3, f"Panjang Node 1 harus 3, didapat {c1['length']}"
        assert c2["length"] == 1, f"Panjang Node 2 harus tetap 1, didapat {c2['length']}"

        print(f"      [+] Node 1 Chain Length: {c1['length']}")
        print(f"      [+] Node 2 Chain Length: {c2['length']}")
        print("      [PASSED] Skenario 3: Uji Divergensi berhasil (Node 1 mendahului Node 2).\n")

        # ----------------------------------------------------------------------
        # Skenario 4: Uji Konsensus (Longest Chain Rule)
        # ----------------------------------------------------------------------
        print("[5/7] Menjalankan Skenario 4: UJI KONSENSUS (LONGEST CHAIN RULE)")
        resolve_res = requests.get(f"{NODE2_URL}/nodes/resolve")
        assert resolve_res.status_code == 200, f"Gagal resolve konsensus: {resolve_res.text}"
        resolve_data = resolve_res.json()

        print(f"      Response Node 2 /nodes/resolve: {resolve_data.get('message')}")
        assert resolve_data["message"] == "Our chain was replaced", "Rantai Node 2 wajib diganti"

        # Verifikasi panjang dan integritas rantai Node 2 setelah konsensus
        c2_after = requests.get(f"{NODE2_URL}/chain").json()
        assert c2_after["length"] == 3, f"Panjang rantai Node 2 harus menjadi 3, didapat {c2_after['length']}"
        assert c2_after["chain"] == c1["chain"], "Rantai Node 2 harus identik dengan rantai Node 1"

        # Verifikasi saldo Dave di Node 2 juga tercermin sebesar 1 koin
        bal_dave_n2 = requests.get(f"{NODE2_URL}/balance/Dave").json()["balance"]
        assert bal_dave_n2 == 1, f"Saldo Dave di Node 2 harus 1, didapat {bal_dave_n2}"

        print(f"      [+] Node 2 Chain Length setelah resolve: {c2_after['length']}")
        print(f"      [+] Saldo Dave tersinkronisasi di Node 2: {bal_dave_n2} koin")
        print("      [PASSED] Skenario 4: Uji Konsensus berhasil.\n")

        # ----------------------------------------------------------------------
        # Skenario 5: Uji Integritas / Tamper Detection & Mempool Reconciliation
        # ----------------------------------------------------------------------
        print("[6/7] Menjalankan Skenario 5: UJI INTEGRITAS / TAMPER DETECTION")
        print("      --- Bagian A: Uji Penolakan Rantai Korup ---")

        # a. Ambil salinan rantai dari Node 1 dan buat payload tiruan yang lebih panjang & dimanipulasi
        chain1_current = requests.get(f"{NODE1_URL}/chain").json()["chain"]
        corrupted_chain = copy.deepcopy(chain1_current)

        # Manipulasi transaksi non-reward pada Blok index 2 tanpa mengubah 'proof'
        corrupted_chain[2]["transactions"][0]["amount"] = 999999

        # Tambahkan blok ke-4 tiruan agar rantai tampak lebih panjang (panjang = 4 vs Node 2 = 3)
        fake_block_4 = {
            "index": 4,
            "timestamp": time.time(),
            "transactions": [{"sender": "Malicious", "recipient": "Attacker", "amount": 1000}],
            "proof": 12345,
            "previous_hash": Blockchain.hash(corrupted_chain[-1])
        }
        corrupted_chain.append(fake_block_4)
        assert len(corrupted_chain) == 4

        # b. Verifikasi langsung bahwa valid_chain() mengembalikan False
        bc_validator = Blockchain()
        assert bc_validator.valid_chain(corrupted_chain) is False, (
            "valid_chain() WAJIB mengembalikan False untuk rantai yang termanipulasi!"
        )
        print("      [+] valid_chain() langsung mengembalikan False pada payload manipulasi.")

        # c. Simulasikan kondisi resolusi: Node 2 tidak mengganti rantai lokalnya
        class RogueNodeHandler(BaseHTTPRequestHandler):
            def do_GET(self):
                if self.path == '/chain':
                    self.send_response(200)
                    self.send_header('Content-Type', 'application/json')
                    self.end_headers()
                    payload = json.dumps({"chain": corrupted_chain, "length": len(corrupted_chain)})
                    self.wfile.write(payload.encode())
                else:
                    self.send_response(404)
                    self.end_headers()

            def log_message(self, format, *args):
                pass

        rogue_server = HTTPServer(('127.0.0.1', ROGUE_PORT), RogueNodeHandler)
        rogue_thread = threading.Thread(target=rogue_server.serve_forever, daemon=True)
        rogue_thread.start()

        # Daftarkan rogue node ke Node 2
        requests.post(f"{NODE2_URL}/nodes/register", json={"nodes": [ROGUE_URL]})

        # Panggil resolve pada Node 2
        resolve_tamper = requests.get(f"{NODE2_URL}/nodes/resolve").json()
        assert resolve_tamper["message"] == "Our chain is authoritative", (
            f"Node 2 seharusnya menolak rantai korup, pesan: {resolve_tamper['message']}"
        )

        c2_check = requests.get(f"{NODE2_URL}/chain").json()
        assert c2_check["length"] == 3, f"Panjang rantai Node 2 harus tetap 3, didapat {c2_check['length']}"
        print("      [+] Node 2 berhasil menolak rantai terkorupsi dari rogue peer.")

        # Hentikan rogue server
        rogue_server.shutdown()
        rogue_server.server_close()
        rogue_server = None

        print("\n      --- Bagian B: Uji Ketahanan Mempool Saat Reorganisasi ---")
        # a. Masukkan transaksi baru ke Node 2 (Dave mentransfer 1 koin ke Eve)
        test_tx = {"sender": "Dave", "recipient": "Eve", "amount": 1}
        tx_res = requests.post(f"{NODE2_URL}/transactions/new", json=test_tx)
        assert tx_res.status_code == 201

        mp2_before = requests.get(f"{NODE2_URL}/mempool").json()
        assert mp2_before["length"] == 1, f"Mempool Node 2 harus berisi 1 transaksi, didapat {mp2_before['length']}"
        print(f"      [+] Transaksi Dave -> Eve (1 koin) masuk ke antrean mempool Node 2.")

        # b. Buat transaksi identik di Node 1 lalu tambang di Node 1
        requests.post(f"{NODE1_URL}/transactions/new", json=test_tx)
        mine_n1 = requests.get(f"{NODE1_URL}/mine")
        assert mine_n1.status_code == 200
        c1_now = requests.get(f"{NODE1_URL}/chain").json()
        assert c1_now["length"] == 4, f"Panjang rantai Node 1 harus 4, didapat {c1_now['length']}"
        print("      [+] Transaksi identik berhasil di-mine ke Blok 4 di Node 1.")

        # c. Jalankan /nodes/resolve pada Node 2
        res_sync = requests.get(f"{NODE2_URL}/nodes/resolve").json()
        assert res_sync["message"] == "Our chain was replaced"

        c2_now = requests.get(f"{NODE2_URL}/chain").json()
        assert c2_now["length"] == 4, f"Panjang rantai Node 2 harus menjadi 4, didapat {c2_now['length']}"

        # d. Pastikan transaksi tersebut otomatis terhapus dari mempool Node 2
        mp2_after = requests.get(f"{NODE2_URL}/mempool").json()
        assert mp2_after["length"] == 0, f"Mempool Node 2 harus kosong setelah rekonsiliasi, didapat {mp2_after['length']}"
        print("      [+] Rekonsiliasi mempool terbukti: Transaksi Dave -> Eve otomatis dibersihkan dari mempool Node 2.")
        print("      [PASSED] Skenario 5: Uji Integritas / Tamper Detection berhasil.\n")

        # ----------------------------------------------------------------------
        # Skenario 6: Uji Saldo & Double-Spending
        # ----------------------------------------------------------------------
        print("[7/7] Menjalankan Skenario 6: UJI SALDO & DOUBLE-SPENDING")

        # a. Uji Penolakan Saldo Nol:
        # Dave telah menghabiskan 1 koinnya ke Eve di Blok 4. Saldo Dave kini 0.
        bal_dave_zero = requests.get(f"{NODE1_URL}/balance/Dave").json()["balance"]
        assert bal_dave_zero == 0, f"Saldo Dave harus 0, didapat {bal_dave_zero}"

        tx_zero = requests.post(
            f"{NODE1_URL}/transactions/new",
            json={"sender": "Dave", "recipient": "Eve", "amount": 50}
        )
        assert tx_zero.status_code == 400, f"Harus return 400, didapat {tx_zero.status_code}"
        assert tx_zero.json()["message"] == "Saldo tidak mencukupi"
        print("      [+] Uji Penolakan Saldo Nol: Transaksi 50 koin dari Dave (saldo 0) sukses ditolak HTTP 400.")

        # b. Uji Transfer Valid:
        # Kuras saldo lama Node 1 terlebih dahulu (jika ada) agar saldo Node 1 tepat 1 setelah menambang
        current_bal = requests.get(f"{NODE1_URL}/balance/{node1_id}").json()["balance"]
        if current_bal > 0:
            requests.post(
                f"{NODE1_URL}/transactions/new",
                json={"sender": node1_id, "recipient": "Vault", "amount": current_bal}
            )

        # Node 1 menambang 1 blok untuk mendapatkan reward koin baru (saldo Node 1 = 1)
        mine_for_funds = requests.get(f"{NODE1_URL}/mine")
        assert mine_for_funds.status_code == 200
        bal_n1 = requests.get(f"{NODE1_URL}/balance/{node1_id}").json()["balance"]
        assert bal_n1 == 1, f"Saldo Node 1 harus tepat 1, didapat {bal_n1}"
        print(f"      [+] Node 1 berhasil menambang blok baru. Saldo Node 1 saat ini: {bal_n1} koin.")

        # Node 1 mengirim 1 koin ke "Alice"
        tx_alice = requests.post(
            f"{NODE1_URL}/transactions/new",
            json={"sender": node1_id, "recipient": "Alice", "amount": 1}
        )
        assert tx_alice.status_code == 201, f"Transfer 1 koin ke Alice harus berhasil, didapat {tx_alice.text}"
        print("      [+] Uji Transfer Valid: Node 1 berhasil mengirim 1 koin ke Alice (HTTP 201).")

        # c. Uji Double-Spending di Mempool:
        # Dalam kondisi transaksi 1 koin ke Alice masih mengantre di mempool,
        # Node 1 mencoba mengirim lagi 1 koin ke "Bob".
        # Karena seluruh sisa saldo Node 1 sudah terikat di mempool (pending_spent), transaksi ini wajib ditolak!
        tx_double_spend = requests.post(
            f"{NODE1_URL}/transactions/new",
            json={"sender": node1_id, "recipient": "Bob", "amount": 1}
        )
        assert tx_double_spend.status_code == 400, f"Double-spend harus ditolak 400, didapat {tx_double_spend.status_code}"
        assert tx_double_spend.json()["message"] == "Saldo tidak mencukupi"
        print("      [+] Uji Double-Spending di Mempool: Percobaan pengiriman ganda ke Bob sukses ditolak HTTP 400 ('Saldo tidak mencukupi').")

        # Tambang blok agar transaksi Alice terkonfirmasi
        requests.get(f"{NODE1_URL}/mine")

        # Sinkronkan Node 2 dengan rantai terbaru Node 1 terlebih dahulu
        sync_res = requests.get(f"{NODE2_URL}/nodes/resolve")
        assert sync_res.status_code == 200
        c2_sync = requests.get(f"{NODE2_URL}/chain").json()
        c1_sync = requests.get(f"{NODE1_URL}/chain").json()
        assert c2_sync["length"] == c1_sync["length"]

        # d. Uji Penolakan Rantai Saldo Negatif:
        # Rogue peer menyajikan rantai yang memiliki PoW valid tetapi memuat transaksi dengan saldo defisit
        chain_latest = requests.get(f"{NODE1_URL}/chain").json()["chain"]
        rogue_deficit_chain = copy.deepcopy(chain_latest)

        # Buat blok kandidat baru yang memuat transaksi penipuan (Defisit / Tanpa Saldo)
        deficit_candidate_block = {
            "index": len(rogue_deficit_chain) + 1,
            "timestamp": time.time(),
            "transactions": [
                {"sender": "0", "recipient": "Hacker", "amount": 1},
                {"sender": "ZeroBalanceVictim", "recipient": "Hacker", "amount": 500}
            ],
            "proof": 0,
            "previous_hash": Blockchain.hash(rogue_deficit_chain[-1])
        }

        # Jalankan Proof of Work yang sah secara matematis (4 leading zeros)
        bc_validator.proof_of_work(deficit_candidate_block)
        assert Blockchain.valid_proof(deficit_candidate_block) is True, "PoW pada blok palsu harus valid secara matematis"
        rogue_deficit_chain.append(deficit_candidate_block)

        # Verifikasi langsung valid_chain() menolak rantai ini karena transaksi defisit
        assert bc_validator.valid_chain(rogue_deficit_chain) is False, (
            "valid_chain() WAJIB menolak rantai dengan transaksi defisit saldo meskipun PoW valid!"
        )
        print("      [+] valid_chain() menolak rantai ber-PoW valid yang memiliki transaksi defisit saldo.")

        # Simulasikan kondisi resolusi pada Node 2 melalui rogue server
        class RogueDeficitHandler(BaseHTTPRequestHandler):
            def do_GET(self):
                if self.path == '/chain':
                    self.send_response(200)
                    self.send_header('Content-Type', 'application/json')
                    self.end_headers()
                    payload = json.dumps({"chain": rogue_deficit_chain, "length": len(rogue_deficit_chain)})
                    self.wfile.write(payload.encode())
                else:
                    self.send_response(404)
                    self.end_headers()

            def log_message(self, format, *args):
                pass

        rogue_server = HTTPServer(('127.0.0.1', ROGUE_PORT), RogueDeficitHandler)
        rogue_thread = threading.Thread(target=rogue_server.serve_forever, daemon=True)
        rogue_thread.start()

        # Daftarkan rogue server ke Node 2 (jika belum)
        requests.post(f"{NODE2_URL}/nodes/register", json={"nodes": [ROGUE_URL]})

        # Panggil resolve pada Node 2
        res_resolve_deficit = requests.get(f"{NODE2_URL}/nodes/resolve").json()
        assert res_resolve_deficit["message"] == "Our chain is authoritative", (
            f"Node 2 tidak boleh mengadopsi rantai defisit, respons: {res_resolve_deficit['message']}"
        )

        c2_final = requests.get(f"{NODE2_URL}/chain").json()
        assert c2_final["length"] < len(rogue_deficit_chain), "Node 2 tidak boleh mengganti rantainya ke rantai defisit"
        print("      [+] Uji Konsensus: Node 2 menolak rantai defisit dari rogue peer dan mempertahankan rantai authoritative.")
        print("      [PASSED] Skenario 6: Uji Saldo & Double-Spending berhasil.\n")

        # Hentikan rogue server
        rogue_server.shutdown()
        rogue_server.server_close()
        rogue_server = None

        print("==================================================================")
        print("   SELURUH SKENARIO PENGUJIAN PENERIMAAN (100%) SUKSES!           ")
        print("==================================================================")

    finally:
        # Membersihkan rogue server jika masih aktif
        if rogue_server:
            try:
                rogue_server.shutdown()
                rogue_server.server_close()
            except Exception:
                pass

        # Membersihkan proses latar belakang agar tidak ada port terkunci di Windows
        print("\n[CLEANUP] Menghentikan proses Node 1 & Node 2...")
        for p, name in [(p1, "Node 1"), (p2, "Node 2")]:
            if p and p.poll() is None:
                p.terminate()
                try:
                    p.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    p.kill()
                print(f"          Proses {name} berhasil dimatikan.")


if __name__ == "__main__":
    run_tests()
