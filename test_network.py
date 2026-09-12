import os
import subprocess
import sys
import time
import requests

NODE1_URL = "http://127.0.0.1:5000"
NODE2_URL = "http://127.0.0.1:5001"


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
    print("================================================================")
    print("   MEMULAI PENGUJIAN OTOMATIS: MINIMAL 2-NODE BLOCKCHAIN        ")
    print("================================================================\n")

    p1 = None
    p2 = None

    try:
        # Menjalankan Node 1 (Port 5000) dan Node 2 (Port 5001) via subprocess
        script_path = os.path.abspath("blockchain.py")
        print("[1/5] Menjalankan Node 1 (Port 5000) & Node 2 (Port 5001)...")
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

        # ----------------------------------------------------------------------
        # Skenario 1: Uji Isolasi
        # ----------------------------------------------------------------------
        print("[2/5] Menjalankan Skenario 1: UJI ISOLASI")
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
        print("[3/5] Menjalankan Skenario 2: UJI PEERING")
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
        print("[4/5] Menjalankan Skenario 3: UJI DIVERGENSI")
        # Kirim transaksi 1 ke Node 1
        tx1 = requests.post(
            f"{NODE1_URL}/transactions/new",
            json={"sender": "Alice", "recipient": "Bob", "amount": 50}
        )
        assert tx1.status_code == 201, f"Gagal menambah transaksi 1: {tx1.text}"

        # Mine Blok 2 di Node 1
        print("      Mining Blok 2 di Node 1...")
        m1 = requests.get(f"{NODE1_URL}/mine")
        assert m1.status_code == 200, f"Gagal mining Blok 2: {m1.text}"
        b2 = m1.json()
        print(f"      -> Blok 2 ditempa | Index: {b2['index']}, Proof: {b2['proof']}")

        # Kirim transaksi 2 ke Node 1
        tx2 = requests.post(
            f"{NODE1_URL}/transactions/new",
            json={"sender": "Bob", "recipient": "Charlie", "amount": 20}
        )
        assert tx2.status_code == 201, f"Gagal menambah transaksi 2: {tx2.text}"

        # Mine Blok 3 di Node 1
        print("      Mining Blok 3 di Node 1...")
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
        print("[5/5] Menjalankan Skenario 4: UJI KONSENSUS (LONGEST CHAIN RULE)")
        resolve_res = requests.get(f"{NODE2_URL}/nodes/resolve")
        assert resolve_res.status_code == 200, f"Gagal resolve konsensus: {resolve_res.text}"
        resolve_data = resolve_res.json()

        print(f"      Response Node 2 /nodes/resolve: {resolve_data.get('message')}")
        assert resolve_data["message"] == "Our chain was replaced", "Rantai Node 2 wajib diganti"

        # Verifikasi panjang dan integritas rantai Node 2 setelah konsensus
        c2_after = requests.get(f"{NODE2_URL}/chain").json()
        assert c2_after["length"] == 3, f"Panjang rantai Node 2 harus menjadi 3, didapat {c2_after['length']}"
        assert c2_after["chain"] == c1["chain"], "Rantai Node 2 harus identik dengan rantai Node 1"

        print(f"      [+] Node 2 Chain Length setelah resolve: {c2_after['length']}")
        print("      [+] Rantai Node 2 tersinkronisasi sempurna dengan Node 1.")
        print("      [PASSED] Skenario 4: Uji Konsensus berhasil.\n")

        print("================================================================")
        print("   SELURUH SKENARIO PENGUJIAN PENERIMAAN (100%) SUKSES!         ")
        print("================================================================")

    finally:
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
