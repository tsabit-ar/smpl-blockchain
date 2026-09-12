import os
import subprocess
import sys
import time
from eth_account import Account
import requests
from web3 import Web3

RPC_URL = "http://127.0.0.1:5000"


def wait_for_rpc(url, timeout=15):
    """Menunggu hingga node siap merespons permintaan RPC/HTTP."""
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
    response = requests.post(RPC_URL, json=payload, timeout=5)
    assert response.status_code == 200, f"HTTP Error {response.status_code}: {response.text}"
    data = response.json()
    if "error" in data:
        raise RuntimeError(f"RPC Error [{data['error'].get('code')}]: {data['error'].get('message')}")
    return data.get("result")


def run_metamask_rpc_tests():
    print("==================================================================")
    print("   MEMULAI PENGUJIAN ETHEREUM JSON-RPC 2.0 BRIDGE (METAMASK)     ")
    print("==================================================================\n")

    p = None
    try:
        # Jalankan Node Blockchain di port 5000
        script_path = os.path.abspath("blockchain.py")
        print("[1/5] Menjalankan Node Blockchain (Port 5000) dengan JSON-RPC Bridge...")
        p = subprocess.Popen(
            [sys.executable, script_path, "5000"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )

        if not wait_for_rpc(RPC_URL):
            raise RuntimeError("Gagal menginisialisasi node blockchain!")
        print("      [+] Node berhasil aktif dan siap melayani JSON-RPC 2.0.\n")

        # ----------------------------------------------------------------------
        # a. Query eth_chainId & net_version
        # ----------------------------------------------------------------------
        print("[2/5] (a) Query eth_chainId & net_version...")
        chain_id = rpc_call("eth_chainId", req_id=1)
        net_ver = rpc_call("net_version", req_id=2)
        block_num = rpc_call("eth_blockNumber", req_id=3)

        assert chain_id == "0x539", f"Expected 0x539 (1337), got {chain_id}"
        assert net_ver == "1337", f"Expected '1337', got {net_ver}"

        print(f"      [+] eth_chainId: {chain_id} (Decimal: {int(chain_id, 16)})")
        print(f"      [+] net_version: {net_ver}")
        print(f"      [+] eth_blockNumber: {block_num} ({int(block_num, 16)} blok)")
        print("      [PASSED] Kompatibilitas Network ID MetaMask valid.\n")

        # ----------------------------------------------------------------------
        # b. Buat Wallet Lokal dengan eth_account
        # ----------------------------------------------------------------------
        print("[3/5] (b) Membuat Wallet Lokal Akun Ethereum (secp256k1)...")
        sender_wallet = Account.create()
        recipient_wallet = Account.create()

        sender_address = sender_wallet.address
        recipient_address = recipient_wallet.address

        print(f"      [+] Sender Wallet Address   : {sender_address}")
        print(f"      [+] Recipient Wallet Address: {recipient_address}")
        print("      [PASSED] Wallet lokal berhasil dibuat.\n")

        # ----------------------------------------------------------------------
        # c. Mint / Mining Saldo ke Alamat Wallet Pengirim
        # ----------------------------------------------------------------------
        print("[4/5] (c) Minting/Mining Koin ke Alamat Pengirim...")
        node_id = requests.get(f"{RPC_URL}/node/id").json()["node_identifier"]

        # 1. Node menambang 1 blok untuk mendapatkan reward coinbase (1 koin)
        requests.get(f"{RPC_URL}/mine")

        # 2. Node mentransfer 1 koin ke alamat wallet sender_address
        tx_fund = requests.post(
            f"{RPC_URL}/transactions/new",
            json={"sender": node_id, "recipient": sender_address, "amount": 1}
        )
        assert tx_fund.status_code == 201, f"Funding gagal: {tx_fund.text}"

        # 3. Tambang blok untuk mengonfirmasi transaksi masuk
        requests.get(f"{RPC_URL}/mine")
        print(f"      [+] 1 Koin (10^18 Wei) berhasil didistribusikan ke {sender_address}.\n")

        # ----------------------------------------------------------------------
        # d. Query eth_getBalance (Verifikasi Saldo dalam Hex Wei)
        # ----------------------------------------------------------------------
        print("[5/5] (d) Query eth_getBalance...")
        sender_balance_hex = rpc_call("eth_getBalance", [sender_address, "latest"], req_id=4)
        recipient_balance_hex = rpc_call("eth_getBalance", [recipient_address, "latest"], req_id=5)

        sender_balance_wei = int(sender_balance_hex, 16)
        recipient_balance_wei = int(recipient_balance_hex, 16)

        assert sender_balance_wei == 10**18, f"Expected 10^18 Wei, got {sender_balance_wei}"
        assert recipient_balance_wei == 0, f"Expected 0 Wei, got {recipient_balance_wei}"

        print(f"      [+] Saldo Pengirim  : {sender_balance_hex} Wei ({sender_balance_wei / 10**18} Koin)")
        print(f"      [+] Saldo Penerima  : {recipient_balance_hex} Wei")
        print("      [PASSED] eth_getBalance presisi dalam format hex Wei.\n")

        # ----------------------------------------------------------------------
        # e. Tandatangani & Kirim Raw Transaction via eth_sendRawTransaction
        # ----------------------------------------------------------------------
        print("[6/5] (e) Penandatanganan Kriptografis & eth_sendRawTransaction...")
        # 1. Cek nonce
        nonce_hex = rpc_call("eth_getTransactionCount", [sender_address, "latest"], req_id=6)
        nonce = int(nonce_hex, 16)
        assert nonce == 0, f"Expected initial nonce 0, got {nonce}"
        print(f"      [+] Nonce Pengirim terkini: {nonce}")

        # 2. Susun dan tandatangani transaksi offline (0.4 koin = 4 * 10^17 Wei)
        transfer_value_wei = int(0.4 * 10**18)
        tx_dict = {
            "nonce": nonce,
            "gasPrice": 1000000000,
            "gas": 21000,
            "to": recipient_address,
            "value": transfer_value_wei,
            "chainId": 1337
        }

        signed_tx = sender_wallet.sign_transaction(tx_dict)
        raw_tx_hex = signed_tx.raw_transaction.hex()
        expected_tx_hash = f"0x{signed_tx.hash.hex()}"
        print(f"      [+] Raw Transaction Hex (RLP): {raw_tx_hex[:40]}...")
        print(f"      [+] Expected Keccak-256 Hash : {expected_tx_hash}")

        # 3. Kirim via eth_sendRawTransaction
        tx_hash_result = rpc_call("eth_sendRawTransaction", [raw_tx_hex], req_id=7)
        assert tx_hash_result.lower() == expected_tx_hash.lower(), (
            f"Hash mismatch: expected {expected_tx_hash}, got {tx_hash_result}"
        )
        print(f"      [+] Sukses dikirim! Transaction Hash: {tx_hash_result}")

        # 4. Verifikasi transaksi sudah mengantre di mempool lokal
        mempool_res = requests.get(f"{RPC_URL}/mempool").json()
        assert mempool_res["length"] == 1, "Transaksi harus masuk ke mempool"
        print("      [+] Transaksi terkonfirmasi berada di dalam mempool.")

        # 5. Tambang blok baru untuk membungkus transaksi MetaMask ini
        print("      Mining blok baru untuk mengonfirmasi transaksi raw...")
        mine_res = requests.get(f"{RPC_URL}/mine").json()
        print(f"      -> Blok {mine_res['index']} ditempa | Proof: {mine_res['proof']}")

        # 6. Verifikasi saldo akhir kedua akun
        sender_after_wei = int(rpc_call("eth_getBalance", [sender_address, "latest"], req_id=8), 16)
        recipient_after_wei = int(rpc_call("eth_getBalance", [recipient_address, "latest"], req_id=9), 16)
        nonce_after = int(rpc_call("eth_getTransactionCount", [sender_address, "latest"], req_id=10), 16)

        expected_sender_wei = 10**18 - transfer_value_wei
        expected_recipient_wei = transfer_value_wei

        assert sender_after_wei == expected_sender_wei, (
            f"Expected sender {expected_sender_wei}, got {sender_after_wei}"
        )
        assert recipient_after_wei == expected_recipient_wei, (
            f"Expected recipient {expected_recipient_wei}, got {recipient_after_wei}"
        )
        assert nonce_after == 1, f"Expected nonce 1, got {nonce_after}"

        print(f"      [+] Saldo Pengirim setelah transfer: {sender_after_wei / 10**18} Koin ({sender_after_wei} Wei)")
        print(f"      [+] Saldo Penerima setelah transfer: {recipient_after_wei / 10**18} Koin ({recipient_after_wei} Wei)")
        print(f"      [+] Nonce Pengirim setelah transfer: {nonce_after}")

        # 7. Uji RPC eth_getBlockByNumber
        block_data = rpc_call("eth_getBlockByNumber", ["latest", True], req_id=11)
        assert block_data is not None, "Block object tidak boleh None"
        assert int(block_data["number"], 16) == mine_res["index"]
        print(f"      [+] eth_getBlockByNumber('latest') berhasil: Block #{int(block_data['number'], 16)} terverifikasi.")

        # 8. Uji RPC eth_getTransactionReceipt
        receipt = rpc_call("eth_getTransactionReceipt", [tx_hash_result], req_id=12)
        assert receipt is not None, "Receipt tidak boleh None"
        assert receipt["status"] == "0x1", "Status transaksi harus sukses (0x1)"
        print(f"      [+] eth_getTransactionReceipt berhasil: Status 0x1 (Sukses).")

        print("\n==================================================================")
        print("   SELURUH PENGUJIAN METAMASK JSON-RPC 2.0 (100%) SUKSES!        ")
        print("==================================================================")

    finally:
        if p and p.poll() is None:
            print("\n[CLEANUP] Menghentikan proses node RPC...")
            p.terminate()
            try:
                p.wait(timeout=3)
            except subprocess.TimeoutExpired:
                p.kill()
            print("          Node RPC berhasil dimatikan.")


if __name__ == "__main__":
    run_metamask_rpc_tests()
