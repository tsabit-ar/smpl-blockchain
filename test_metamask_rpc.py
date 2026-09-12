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
    # Bersihkan berkas persistensi sebelum pengujian
    if os.path.exists("chain_5000.json"):
        try:
            os.remove("chain_5000.json")
        except OSError:
            pass

    try:
        # Jalankan Node Blockchain di port 5000
        script_path = os.path.abspath("blockchain.py")
        print("[1/7] Menjalankan Node Blockchain (Port 5000) dengan JSON-RPC Bridge...")
        p = subprocess.Popen(
            [sys.executable, script_path, "5000"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )

        if not wait_for_rpc(RPC_URL):
            raise RuntimeError("Gagal menginisialisasi node blockchain!")
        print("      [+] Node berhasil aktif dan siap melayani JSON-RPC 2.0.\n")

        # ----------------------------------------------------------------------
        # 1. Uji Penanganan CORS (OPTIONS & Header)
        # ----------------------------------------------------------------------
        print("[2/7] (1) Uji Penanganan CORS (Preflight OPTIONS & Headers)...")
        opt_res = requests.options(RPC_URL, timeout=3)
        assert opt_res.status_code == 200, f"OPTIONS request harus return 200, got {opt_res.status_code}"
        assert "Access-Control-Allow-Origin" in opt_res.headers, "Header Access-Control-Allow-Origin harus ada"
        print(f"      [+] OPTIONS / return HTTP 200 dengan Access-Control-Allow-Origin: {opt_res.headers.get('Access-Control-Allow-Origin')}")
        print("      [PASSED] Penanganan CORS aktif untuk seluruh rute.\n")

        # ----------------------------------------------------------------------
        # 2. Query eth_chainId, net_version, & eth_blockNumber
        # ----------------------------------------------------------------------
        print("[3/7] (2) Query eth_chainId & net_version...")
        chain_id = rpc_call("eth_chainId", req_id=1)
        net_ver = rpc_call("net_version", req_id=2)
        block_num = rpc_call("eth_blockNumber", req_id=3)

        assert chain_id == "0x539", f"Expected 0x539 (1337), got {chain_id}"
        assert net_ver == "1337", f"Expected '1337', got {net_ver}"

        print(f"      [+] eth_chainId    : {chain_id} (Decimal: {int(chain_id, 16)})")
        print(f"      [+] net_version    : {net_ver}")
        print(f"      [+] eth_blockNumber: {block_num} ({int(block_num, 16)} blok)")
        print("      [PASSED] Kompatibilitas Network ID MetaMask valid.\n")

        # ----------------------------------------------------------------------
        # 3. Uji Faucet Sederhana (GET /faucet/<address>)
        # ----------------------------------------------------------------------
        print("[4/7] (3) Uji Endpoint Faucet (GET /faucet/<address>)...")
        sender_wallet = Account.create()
        recipient_wallet = Account.create()

        sender_address = sender_wallet.address
        recipient_address = recipient_wallet.address

        print(f"      [i] Sender Address   : {sender_address}")
        print(f"      [i] Recipient Address: {recipient_address}")

        # Minting 10 SMPL koin ke sender_address via faucet
        faucet_res = requests.get(f"{RPC_URL}/faucet/{sender_address}")
        assert faucet_res.status_code == 200, f"Faucet error {faucet_res.status_code}: {faucet_res.text}"
        faucet_data = faucet_res.json()
        assert faucet_data["amount"] == 10
        assert faucet_data["balance"] == 10
        print(f"      [+] Faucet sukses: {faucet_data['message']} (Blok #{faucet_data['block_index']})")

        # Verifikasi via eth_getBalance
        bal_wei_hex = rpc_call("eth_getBalance", [sender_address, "latest"], req_id=4)
        assert int(bal_wei_hex, 16) == 10 * 10**18, f"Saldo harus 10 * 10^18 Wei, didapat {int(bal_wei_hex, 16)}"
        print(f"      [+] eth_getBalance terverifikasi: {bal_wei_hex} Wei (10 SMPL)")
        print("      [PASSED] Faucet endpoint bekerja secara instan.\n")

        # ----------------------------------------------------------------------
        # 4. Uji Auto-Mining pada eth_sendRawTransaction
        # ----------------------------------------------------------------------
        print("[5/7] (4) Uji Penandatanganan Kriptografis & Auto-Mining...")
        nonce_hex = rpc_call("eth_getTransactionCount", [sender_address, "latest"], req_id=5)
        nonce = int(nonce_hex, 16)
        assert nonce == 0

        # Kirim 2.5 SMPL koin ke recipient
        send_wei = int(2.5 * 10**18)
        tx_dict = {
            "nonce": nonce,
            "gasPrice": 1000000000,
            "gas": 21000,
            "to": recipient_address,
            "value": send_wei,
            "chainId": 1337
        }
        signed_tx = sender_wallet.sign_transaction(tx_dict)
        raw_tx_hex = signed_tx.raw_transaction.hex()
        expected_tx_hash = f"0x{signed_tx.hash.hex()}"

        # Eksekusi eth_sendRawTransaction (blok otomatis di-mine secara instan di sisi server)
        print("      Mengirim raw transaction ke eth_sendRawTransaction...")
        tx_hash_result = rpc_call("eth_sendRawTransaction", [raw_tx_hex], req_id=6)
        assert tx_hash_result.lower() == expected_tx_hash.lower()
        print(f"      [+] Transaksi sukses diterima & auto-mined! Hash: {tx_hash_result}")

        # Verifikasi bahwa mempool langsung bersih karena sudah auto-mined ke blok baru
        mempool_data = requests.get(f"{RPC_URL}/mempool").json()
        assert mempool_data["length"] == 0, "Mempool harus kosong karena auto-mining langsung membungkus transaksi!"
        print("      [+] Auto-mining terverifikasi: Transaksi langsung terkonfirmasi tanpa pending tak terbatas.")

        # Verifikasi saldo baru
        sender_after_wei = int(rpc_call("eth_getBalance", [sender_address, "latest"], req_id=7), 16)
        recipient_after_wei = int(rpc_call("eth_getBalance", [recipient_address, "latest"], req_id=8), 16)
        assert sender_after_wei == 10 * 10**18 - send_wei  # 7.5 SMPL
        assert recipient_after_wei == send_wei            # 2.5 SMPL

        print(f"      [+] Saldo Pengirim : {sender_after_wei / 10**18} SMPL")
        print(f"      [+] Saldo Penerima : {recipient_after_wei / 10**18} SMPL")
        print("      [PASSED] Auto-mining berhasil mengonfirmasi transaksi seketika.\n")

        # ----------------------------------------------------------------------
        # 5. Uji Handler Fallback RPC (eth_syncing, eth_feeHistory, & Unknown)
        # ----------------------------------------------------------------------
        print("[6/7] (5) Uji Handler Fallback RPC...")
        syncing = rpc_call("eth_syncing", req_id=9)
        assert syncing is False, f"eth_syncing harus False, got {syncing}"
        print(f"      [+] eth_syncing: {syncing}")

        fee_hist = rpc_call("eth_feeHistory", ["0x1", "latest", []], req_id=10)
        assert fee_hist is not None
        assert "baseFeePerGas" in fee_hist
        print(f"      [+] eth_feeHistory: baseFeePerGas = {fee_hist['baseFeePerGas']}")

        # Uji method acak / belum terdefinisi (harus mengembalikan "0x0", BUKAN HTTP 500)
        unrecognized_res = rpc_call("eth_someArbitraryMethodProbe", ["0x123"], req_id=11)
        assert unrecognized_res == "0x0", f"Unknown method harus return '0x0', got {unrecognized_res}"
        print(f"      [+] Fallback RPC untuk method tak dikenal: Mengembalikan '0x0' (Anti-Error).")
        print("      [PASSED] Handler Fallback RPC bekerja optimal.\n")

        # ----------------------------------------------------------------------
        # 6. Verifikasi Receipt Transaksi
        # ----------------------------------------------------------------------
        print("[7/7] (6) Verifikasi eth_getTransactionReceipt...")
        receipt = rpc_call("eth_getTransactionReceipt", [tx_hash_result], req_id=12)
        assert receipt is not None
        assert receipt["status"] == "0x1"
        print(f"      [+] eth_getTransactionReceipt terverifikasi: Status 0x1 (Sukses) pada Blok {receipt['blockNumber']}")
        print("      [PASSED] Receipt transaksi valid.\n")

        print("==================================================================")
        print("   SELURUH PENGUJIAN RUNTIME METAMASK (100%) SUKSES!             ")
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

        if os.path.exists("chain_5000.json"):
            try:
                os.remove("chain_5000.json")
            except OSError:
                pass


if __name__ == "__main__":
    run_metamask_rpc_tests()
