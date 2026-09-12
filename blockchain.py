import hashlib
import json
import os
import threading
from time import time
from urllib.parse import urlparse
from uuid import uuid4

from eth_account import Account
from eth_account.typed_transactions import TypedTransaction
from flask import Flask, jsonify, request
from flask_cors import CORS
import requests
import rlp
from web3 import Web3


class Blockchain:
    WEI_PER_COIN = 10**18

    def __init__(self, port=5000):
        self.port = port
        self.storage_file = f"chain_{port}.json" if port is not None else None
        self.lock = threading.Lock()

        with self.lock:
            self.chain = []
            self.current_transactions = []
            self.nodes = set()
            self.account_nonces = {}

            # Muat rantai dari storage JSON jika ada di disk, atau buat Genesis Block
            self.load_chain()

    def save_chain(self):
        """
        Menulis self.chain ke self.storage_file secara rapi (json.dump dengan indent=2).
        """
        if not self.storage_file:
            return
        try:
            with open(self.storage_file, 'w', encoding='utf-8') as f:
                json.dump(self.chain, f, indent=2, sort_keys=True)
        except Exception as e:
            print(f"Error menyimpan berkas {self.storage_file}: {e}")

    def load_chain(self):
        """
        Jika self.storage_file ada di disk, baca JSON, validasi format, dan tetapkan ke self.chain.
        Jika belum ada, buat Genesis Block lalu panggil save_chain().
        """
        if self.storage_file and os.path.exists(self.storage_file):
            try:
                with open(self.storage_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                if isinstance(data, list) and len(data) > 0:
                    self.chain = data
                    return
            except Exception as e:
                print(f"Peringatan: Gagal membaca {self.storage_file}, inisialisasi Genesis Block baru: {e}")

        # Inisialisasi Genesis Block (FR-1)
        genesis_block = {
            'index': 1,
            'timestamp': time(),
            'transactions': [],
            'proof': 100,
            'previous_hash': '1'
        }
        self.chain = [genesis_block]
        self.save_chain()

    def append_block(self, block):
        """
        Menambahkan blok valid ke dalam chain dan mereset antrean transaksi lokal (mempool).
        Dilindungi oleh self.lock untuk thread-safety.
        Menyimpan perubahan ke disk secara otomatis.
        """
        with self.lock:
            self.chain.append(block)
            self.current_transactions = []
            self.save_chain()
            return block

    @staticmethod
    def _normalize_address(addr):
        """Menormalisasi alamat Ethereum (0x...) menjadi lowercase."""
        if isinstance(addr, str) and addr.startswith("0x"):
            return addr.lower()
        return addr

    @classmethod
    def calculate_balance_for_chain(cls, address, chain):
        """
        Menghitung total koin masuk (recipient) dikurangi koin keluar (sender) dari seluruh blok.
        Transaksi coinbase (sender: '0') dihitung sebagai penambahan saldo bagi recipient.
        """
        balance = 0.0
        norm_target = cls._normalize_address(address)
        for block in chain:
            for tx in block.get('transactions', []):
                sender = cls._normalize_address(tx.get('sender'))
                recipient = cls._normalize_address(tx.get('recipient'))
                amount = float(tx.get('amount', 0))

                if recipient == norm_target:
                    balance += amount
                if sender == norm_target:
                    balance -= amount

        if balance.is_integer():
            return int(balance)
        return balance

    def get_balance(self, address):
        """
        Mengambil saldo akun dari self.chain dengan thread-safety.
        """
        with self.lock:
            return self.calculate_balance_for_chain(address, self.chain)

    def get_nonce(self, address):
        """
        Menghitung jumlah transaksi keluar yang sudah terkonfirmasi di rantai
        ditambah yang masih pending di mempool.
        """
        with self.lock:
            norm_addr = self._normalize_address(address)
            count = 0
            for block in self.chain:
                for tx in block.get('transactions', []):
                    sender = self._normalize_address(tx.get('sender'))
                    if sender == norm_addr:
                        count += 1
            for tx in self.current_transactions:
                sender = self._normalize_address(tx.get('sender'))
                if sender == norm_addr:
                    count += 1

            self.account_nonces[norm_addr] = count
            return count

    def new_transaction(self, sender, recipient, amount, tx_hash=None):
        """
        Membuat transaksi baru yang akan masuk ke blok berikutnya yang di-mine (FR-2).
        Dilindungi oleh self.lock untuk thread-safety.
        Mencegah double-spending dan transaksi defisit saldo:
        - Abaikan validasi saldo jika sender == '0' (reward coinbase / minting).
        - Hitung total amount yang sudah dikomit oleh sender di self.current_transactions (pending_spent).
        - Jika get_balance(sender) - pending_spent < amount, tolak dengan ValueError('Saldo tidak mencukupi').
        """
        with self.lock:
            amt = float(amount)
            if amt <= 0:
                raise ValueError("Jumlah transfer harus lebih besar dari 0")

            norm_sender = self._normalize_address(sender)
            if sender != "0":
                current_balance = self.calculate_balance_for_chain(norm_sender, self.chain)
                pending_spent = sum(
                    float(tx.get('amount', 0))
                    for tx in self.current_transactions
                    if self._normalize_address(tx.get('sender')) == norm_sender
                )
                if current_balance - pending_spent < amt:
                    raise ValueError("Saldo tidak mencukupi")

            formatted_amt = int(amt) if amt.is_integer() else amt
            tx_data = {
                'sender': sender,
                'recipient': recipient,
                'amount': formatted_amt,
            }
            if tx_hash:
                tx_data['hash'] = tx_hash

            self.current_transactions.append(tx_data)
            return self.chain[-1]['index'] + 1

    @property
    def last_block(self):
        return self.chain[-1]

    @staticmethod
    def hash(block):
        """
        Menghasilkan SHA-256 hash deterministik dari sebuah blok (NFR-2).
        Urutan key di-sort secara alfabetis (sort_keys=True).
        """
        block_string = json.dumps(block, sort_keys=True).encode()
        return hashlib.sha256(block_string).hexdigest()

    @staticmethod
    def valid_proof(block):
        """
        Memvalidasi proof kandidat blok:
        Apakah SHA256(block) memiliki 4 leading zeros ('0000')? (FR-3, NFR-3)
        """
        return Blockchain.hash(block).startswith('0000')

    def proof_of_work(self, candidate_block):
        """
        Algoritma Proof of Work:
        Memutasi field candidate_block['proof'] secara in-place sampai
        hash blok memenuhi kriteria tingkat kesulitan ('0000').
        """
        candidate_block['proof'] = 0
        while not self.valid_proof(candidate_block):
            candidate_block['proof'] += 1
        return candidate_block['proof']

    def register_node(self, address):
        """
        Menambahkan node tetangga baru ke daftar node unik (FR-5).
        Dilindungi oleh self.lock untuk thread-safety.
        """
        parsed_url = urlparse(address)
        node_url = None
        if parsed_url.netloc:
            node_url = f"{parsed_url.scheme}://{parsed_url.netloc}"
        elif parsed_url.path:
            node_url = f"http://{parsed_url.path}"

        if node_url:
            with self.lock:
                self.nodes.add(node_url)

    def valid_chain(self, chain):
        """
        Menentukan apakah rantai blockchain valid (FR-6):
        - Melewati validasi pada blok index 0 (Genesis block).
        - Memverifikasi previous_hash dan PoW setiap blok mulai dari index 1.
        - Simulasi state saldo akun mulai dari index 1:
          Jika ditemukan transaksi reguler di mana pengirim mentransfer dana
          melampaui saldo kumulatifnya pada titik blok tersebut, valid_chain() return False.
        """
        if not chain:
            return False

        balances = {}

        for i in range(1, len(chain)):
            prev_block = chain[i - 1]
            curr_block = chain[i]

            # 1. Periksa kesesuaian previous_hash
            if curr_block.get('previous_hash') != self.hash(prev_block):
                return False

            # 2. Periksa validitas Proof of Work blok
            if not self.valid_proof(curr_block):
                return False

            # 3. Simulasi state saldo akun untuk seluruh transaksi pada blok ini
            for tx in curr_block.get('transactions', []):
                sender = tx.get('sender')
                recipient = tx.get('recipient')
                amount = float(tx.get('amount', 0))

                if amount <= 0:
                    return False

                norm_sender = self._normalize_address(sender)
                norm_recipient = self._normalize_address(recipient)

                if sender == "0":
                    # Transaksi coinbase reward / minting
                    balances[norm_recipient] = balances.get(norm_recipient, 0.0) + amount
                else:
                    # Transaksi reguler
                    sender_bal = balances.get(norm_sender, 0.0)
                    if sender_bal < amount:
                        return False
                    balances[norm_sender] = sender_bal - amount
                    balances[norm_recipient] = balances.get(norm_recipient, 0.0) + amount

        return True

    def resolve_conflicts(self):
        """
        Konsensus Longest Chain Rule (FR-6) dengan Rekonsiliasi Mempool:
        1. Mengambil salinan node tetangga tanpa menahan lock selama network I/O.
        2. Jika rantai valid terpanjang ditemukan:
           a. Kumpulkan signature transaksi (sender, recipient, amount) pada new_chain (kecuali reward sender '0').
           b. Kumpulkan transaksi non-reward dari blok rantai lama yang terbuang jika belum ada di new_chain.
           c. Saring self.current_transactions lokal untuk membuang transaksi yang sudah tercatat di new_chain.
           d. Ganti self.chain dengan new_chain di bawah proteksi self.lock.
        """
        with self.lock:
            neighbors = list(self.nodes)
            max_length = len(self.chain)

        new_chain = None

        # Network I/O di luar self.lock agar tidak memblokir thread lain
        for node in neighbors:
            try:
                response = requests.get(f"{node}/chain", timeout=5)
                if response.status_code == 200:
                    data = response.json()
                    length = data.get('length')
                    chain = data.get('chain')

                    if length and chain and length > max_length and self.valid_chain(chain):
                        max_length = length
                        new_chain = chain
            except requests.RequestException:
                continue

        if new_chain:
            with self.lock:
                def tx_sig(tx):
                    return (
                        self._normalize_address(tx.get('sender')),
                        self._normalize_address(tx.get('recipient')),
                        float(tx.get('amount', 0))
                    )

                # a. Seluruh signature transaksi non-reward pada new_chain
                new_chain_tx_sigs = set()
                for block in new_chain:
                    for tx in block.get('transactions', []):
                        if tx.get('sender') != "0":
                            new_chain_tx_sigs.add(tx_sig(tx))

                # b. Kumpulkan transaksi non-reward dari blok rantai lokal lama yang terbuang
                orphaned_txs = []
                seen_orphaned_sigs = set()
                for block in self.chain:
                    for tx in block.get('transactions', []):
                        if tx.get('sender') != "0":
                            sig = tx_sig(tx)
                            if sig not in new_chain_tx_sigs and sig not in seen_orphaned_sigs:
                                orphaned_txs.append(tx)
                                seen_orphaned_sigs.add(sig)

                # c. Saring antrean transaksi lokal (mempool)
                reconciled_mempool = []
                seen_mempool_sigs = set()

                # Masukkan kembali transaksi yatim dari rantai lama yang belum masuk new_chain
                for tx in orphaned_txs:
                    sig = tx_sig(tx)
                    reconciled_mempool.append(tx)
                    seen_mempool_sigs.add(sig)

                # Pertahankan transaksi mempool lokal yang benar-benar belum di-mine
                for tx in self.current_transactions:
                    sig = tx_sig(tx)
                    if sig not in new_chain_tx_sigs and sig not in seen_mempool_sigs:
                        reconciled_mempool.append(tx)
                        seen_mempool_sigs.add(sig)

                self.current_transactions = reconciled_mempool
                self.chain = new_chain
                self.save_chain()

            return True

        return False


# Inisialisasi Flask Node
app = Flask(__name__)

# Mengaktifkan CORS untuk seluruh route agar MetaMask & browser web dapat mengakses API
CORS(app)

# ID Unik untuk node ini (sebagai penerima reward mining)
node_identifier = str(uuid4()).replace('-', '')

# Inisialisasi Blockchain (in-memory default saat di-import; ditimpa di __main__ dengan port)
blockchain = Blockchain(port=None)


# ------------------------------------------------------------------------------
# Helper Mining Blok Baru
# ------------------------------------------------------------------------------
def mine_block(reward_recipient=node_identifier, reward_amount=1):
    """
    Menjalankan proses mining untuk membungkus transaksi antrean:
    1. Masukkan transaksi reward coinbase.
    2. Susun candidate_block.
    3. Jalankan proof_of_work.
    4. Simpan ke chain via append_block.
    """
    blockchain.new_transaction(
        sender="0",
        recipient=reward_recipient,
        amount=reward_amount,
    )

    with blockchain.lock:
        last_block = blockchain.chain[-1]
        candidate_block = {
            'index': len(blockchain.chain) + 1,
            'timestamp': time(),
            'transactions': list(blockchain.current_transactions),
            'proof': 0,
            'previous_hash': blockchain.hash(last_block)
        }

    blockchain.proof_of_work(candidate_block)
    block = blockchain.append_block(candidate_block)
    return block


# ------------------------------------------------------------------------------
# Helper Parsing Raw Transaction Ethereum
# ------------------------------------------------------------------------------
def parse_raw_transaction(raw_bytes):
    """
    Melakukan decode pada raw byte transaksi Ethereum (Legacy RLP atau EIP-2718 Typed).
    Mengembalikan tuple: (to_address, value_in_wei, nonce)
    """
    if raw_bytes[0] in (1, 2, 3):
        typed_tx = TypedTransaction.from_bytes(raw_bytes)
        tx_dict = typed_tx.as_dict()
        to_addr = tx_dict.get('to')
        if hasattr(to_addr, 'hex'):
            to_addr = '0x' + to_addr.hex()
        elif isinstance(to_addr, bytes):
            to_addr = '0x' + to_addr.hex()
        else:
            to_addr = str(to_addr) if to_addr else None
        value = int(tx_dict.get('value', 0))
        nonce = int(tx_dict.get('nonce', 0))
        return to_addr, value, nonce
    else:
        decoded = rlp.decode(raw_bytes)
        nonce = int.from_bytes(decoded[0], 'big') if decoded[0] else 0
        to_addr = ('0x' + decoded[3].hex()) if decoded[3] else None
        value = int.from_bytes(decoded[4], 'big') if decoded[4] else 0
        return to_addr, value, nonce


# ------------------------------------------------------------------------------
# Ethereum JSON-RPC 2.0 Bridge Handler (POST & OPTIONS /)
# ------------------------------------------------------------------------------
@app.route('/', methods=['POST', 'OPTIONS'])
def json_rpc():
    """
    Lapisan JSON-RPC 2.0 Bridge untuk MetaMask:
    Mendukung CORS preflight (OPTIONS), eth_chainId, net_version, eth_blockNumber,
    eth_getBalance, eth_getTransactionCount, eth_estimateGas, eth_gasPrice,
    eth_sendRawTransaction, eth_getBlockByNumber, eth_getTransactionReceipt,
    serta fallback RPC handler default ("0x0").
    """
    if request.method == 'OPTIONS':
        return jsonify({}), 200

    data = request.get_json(force=True, silent=True)
    if not data:
        return jsonify({
            "jsonrpc": "2.0",
            "id": None,
            "error": {"code": -32700, "message": "Parse error"}
        }), 400

    def handle_request(req):
        if not isinstance(req, dict):
            return {
                "jsonrpc": "2.0",
                "id": None,
                "error": {"code": -32600, "message": "Invalid Request"}
            }

        req_id = req.get('id')
        method = req.get('method')
        params = req.get('params', [])

        try:
            if method == 'eth_chainId':
                # Chain ID 1337 -> 0x539
                return {"jsonrpc": "2.0", "id": req_id, "result": "0x539"}

            elif method == 'net_version':
                return {"jsonrpc": "2.0", "id": req_id, "result": "1337"}

            elif method == 'eth_blockNumber':
                with blockchain.lock:
                    height = len(blockchain.chain)
                return {"jsonrpc": "2.0", "id": req_id, "result": hex(height)}

            elif method == 'eth_getBalance':
                address = params[0] if params else "0x0"
                balance_coins = blockchain.get_balance(address)
                balance_wei = int(float(balance_coins) * blockchain.WEI_PER_COIN)
                return {"jsonrpc": "2.0", "id": req_id, "result": hex(balance_wei)}

            elif method == 'eth_getTransactionCount':
                address = params[0] if params else "0x0"
                nonce = blockchain.get_nonce(address)
                return {"jsonrpc": "2.0", "id": req_id, "result": hex(nonce)}

            elif method == 'eth_estimateGas':
                # Standar 21000 gas -> 0x5208
                return {"jsonrpc": "2.0", "id": req_id, "result": "0x5208"}

            elif method in ('eth_gasPrice', 'eth_maxPriorityFeePerGas'):
                return {"jsonrpc": "2.0", "id": req_id, "result": "0x0"}

            elif method == 'eth_sendRawTransaction':
                raw_hex = params[0]
                raw_bytes = bytes.fromhex(raw_hex[2:] if raw_hex.startswith("0x") else raw_hex)

                # 1. Recover public address pengirim secara kriptografis (secp256k1)
                sender = Account.recover_transaction(raw_bytes)

                # 2. Parse nilai to, value (Wei), dan nonce
                to_addr, value_wei, nonce = parse_raw_transaction(raw_bytes)

                # 3. Validasi nonce sesuai get_nonce(sender)
                expected_nonce = blockchain.get_nonce(sender)
                if nonce != expected_nonce:
                    return {
                        "jsonrpc": "2.0",
                        "id": req_id,
                        "error": {
                            "code": -32000,
                            "message": f"Nonce mismatch: expected {expected_nonce}, got {nonce}"
                        }
                    }

                # 4. Konversi nilai Wei ke unit koin
                value_coins = value_wei / blockchain.WEI_PER_COIN
                tx_hash = f"0x{Web3.keccak(raw_bytes).hex()}"

                # 5. Masukkan ke mempool via new_transaction
                blockchain.new_transaction(sender, to_addr, value_coins, tx_hash=tx_hash)

                # 6. Auto-mining untuk interaksi UI: langsung picu penambangan blok baru
                mine_block()

                return {"jsonrpc": "2.0", "id": req_id, "result": tx_hash}

            elif method in ('eth_getBlockByNumber', 'eth_getBlockByHash'):
                tag = params[0] if params else "latest"
                full_tx = params[1] if len(params) > 1 else False

                with blockchain.lock:
                    if method == 'eth_getBlockByHash':
                        hash_target = str(tag).lower()
                        if hash_target.startswith("0x"):
                            hash_target = hash_target[2:]
                        matched = [b for b in blockchain.chain if blockchain.hash(b).lower() == hash_target]
                        block = matched[0] if matched else None
                    elif tag in ("latest", "pending"):
                        block = blockchain.chain[-1] if blockchain.chain else None
                    else:
                        try:
                            num = int(tag, 16) if isinstance(tag, str) and tag.startswith("0x") else int(tag)
                            matched = [b for b in blockchain.chain if b['index'] == num]
                            block = matched[0] if matched else None
                        except Exception:
                            block = None

                if not block:
                    return {"jsonrpc": "2.0", "id": req_id, "result": None}

                block_hash = "0x" + blockchain.hash(block)
                parent_hash = block['previous_hash']
                if not parent_hash.startswith("0x"):
                    parent_hash = "0x" + parent_hash.zfill(64)

                tx_list = []
                for idx, tx in enumerate(block.get('transactions', [])):
                    th = tx.get('hash') or ("0x" + hashlib.sha256(json.dumps(tx, sort_keys=True).encode()).hexdigest())
                    if full_tx:
                        tx_list.append({
                            "hash": th,
                            "nonce": hex(0),
                            "blockHash": block_hash,
                            "blockNumber": hex(block['index']),
                            "transactionIndex": hex(idx),
                            "from": tx.get('sender'),
                            "to": tx.get('recipient'),
                            "value": hex(int(float(tx.get('amount', 0)) * blockchain.WEI_PER_COIN)),
                            "gas": "0x5208",
                            "gasPrice": "0x0",
                            "input": "0x"
                        })
                    else:
                        tx_list.append(th)

                block_obj = {
                    "number": hex(block['index']),
                    "hash": block_hash,
                    "parentHash": parent_hash,
                    "nonce": hex(block['proof']),
                    "sha3Uncles": "0x1dcc4de8dec75d7aab85b567b6ccd41ad312451b948a7413f0a142fd40d49347",
                    "logsBloom": "0x" + "0" * 512,
                    "transactionsRoot": "0x56e81f171bcc55a6ff8345e692c0f86e5b48e01b996cadc001622fb5e363b421",
                    "stateRoot": "0x56e81f171bcc55a6ff8345e692c0f86e5b48e01b996cadc001622fb5e363b421",
                    "receiptsRoot": "0x56e81f171bcc55a6ff8345e692c0f86e5b48e01b996cadc001622fb5e363b421",
                    "miner": "0x0000000000000000000000000000000000000000",
                    "difficulty": "0x1",
                    "totalDifficulty": hex(block['index']),
                    "extraData": "0x",
                    "size": hex(1024),
                    "gasLimit": "0x1fffffffffffff",
                    "gasUsed": "0x0",
                    "timestamp": hex(int(block['timestamp'])),
                    "transactions": tx_list,
                    "uncles": []
                }
                return {"jsonrpc": "2.0", "id": req_id, "result": block_obj}

            elif method == 'eth_getTransactionReceipt':
                tx_hash = params[0] if params else None
                found_block = None
                tx_index = 0
                with blockchain.lock:
                    for b in blockchain.chain:
                        for idx, t in enumerate(b.get('transactions', [])):
                            th = t.get('hash') or ("0x" + hashlib.sha256(json.dumps(t, sort_keys=True).encode()).hexdigest())
                            if th.lower() == str(tx_hash).lower():
                                found_block = b
                                tx_index = idx
                                break
                        if found_block:
                            break

                if not found_block:
                    return {"jsonrpc": "2.0", "id": req_id, "result": None}

                receipt = {
                    "transactionHash": tx_hash,
                    "transactionIndex": hex(tx_index),
                    "blockHash": "0x" + blockchain.hash(found_block),
                    "blockNumber": hex(found_block['index']),
                    "cumulativeGasUsed": "0x5208",
                    "gasUsed": "0x5208",
                    "status": "0x1",
                    "logs": []
                }
                return {"jsonrpc": "2.0", "id": req_id, "result": receipt}

            elif method == 'eth_syncing':
                return {"jsonrpc": "2.0", "id": req_id, "result": False}

            elif method == 'net_listening':
                return {"jsonrpc": "2.0", "id": req_id, "result": True}

            elif method == 'web3_clientVersion':
                return {"jsonrpc": "2.0", "id": req_id, "result": "SMPL-Blockchain/v1.0"}

            elif method == 'eth_feeHistory':
                return {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "oldestBlock": "0x1",
                        "baseFeePerGas": ["0x0", "0x0"],
                        "gasUsedRatio": [0.0],
                        "reward": [["0x0"]]
                    }
                }

            elif method == 'eth_accounts':
                return {"jsonrpc": "2.0", "id": req_id, "result": []}

            elif method in ('eth_call', 'eth_getCode'):
                return {"jsonrpc": "2.0", "id": req_id, "result": "0x"}

            else:
                # Default fallback: jika ada method yang belum dikenali,
                # kembalikan "0x0" bukan HTTP 500
                return {"jsonrpc": "2.0", "id": req_id, "result": "0x0"}

        except Exception as e:
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {"code": -32000, "message": str(e)}
            }

    if isinstance(data, list):
        return jsonify([handle_request(item) for item in data]), 200
    else:
        return jsonify(handle_request(data)), 200


# ------------------------------------------------------------------------------
# Faucet Endpoint Sederhana
# ------------------------------------------------------------------------------
@app.route('/faucet/<address>', methods=['GET'])
def faucet(address):
    """
    Mencetak dan mengirim 10 koin SMPL ke alamat heksadesimal yang diminta,
    langsung menambang bloknya, dan mengembalikan HTTP 200.
    """
    if not address or not isinstance(address, str):
        return jsonify({'message': 'Invalid address'}), 400

    # Masukkan transaksi minting 10 koin dari sistem ('0')
    blockchain.new_transaction(
        sender="0",
        recipient=address,
        amount=10
    )

    # Langsung picu penambangan blok baru
    block = mine_block()

    return jsonify({
        'status': 'success',
        'message': f'10 SMPL successfully minted to {address}',
        'address': address,
        'amount': 10,
        'block_index': block['index'],
        'balance': blockchain.get_balance(address)
    }), 200


# ------------------------------------------------------------------------------
# REST API Endpoints Standar
# ------------------------------------------------------------------------------
@app.route('/node/id', methods=['GET'])
def get_node_id():
    """Mengembalikan identifier unik dari node ini."""
    return jsonify({'node_identifier': node_identifier}), 200


@app.route('/chain', methods=['GET'])
def full_chain():
    """Mengambil seluruh salinan rantai lokal dengan thread-safety."""
    with blockchain.lock:
        chain_copy = list(blockchain.chain)
        length = len(chain_copy)
    response = {
        'chain': chain_copy,
        'length': length,
    }
    return jsonify(response), 200


@app.route('/balance/<address>', methods=['GET'])
def get_account_balance(address):
    """Mengembalikan saldo terkini dari alamat yang diberikan."""
    balance = blockchain.get_balance(address)
    return jsonify({'address': address, 'balance': balance}), 200


@app.route('/mempool', methods=['GET'])
def mempool():
    """Mengambil daftar transaksi di antrean sementara (mempool) dengan thread-safety."""
    with blockchain.lock:
        mempool_copy = list(blockchain.current_transactions)
        length = len(mempool_copy)
    response = {
        'mempool': mempool_copy,
        'length': length,
    }
    return jsonify(response), 200


@app.route('/transactions/new', methods=['POST'])
def new_transaction():
    """Menambahkan transaksi baru ke mempool lokal."""
    values = request.get_json()
    if not values:
        return jsonify({'message': 'Missing request body'}), 400

    required = ['sender', 'recipient', 'amount']
    if not all(k in values for k in required):
        return jsonify({'message': 'Missing values in transaction payload'}), 400

    try:
        index = blockchain.new_transaction(values['sender'], values['recipient'], values['amount'])
    except ValueError as e:
        return jsonify({'message': str(e)}), 400

    response = {'message': f'Transaction will be added to Block {index}'}
    return jsonify(response), 201


@app.route('/mine', methods=['GET'])
def mine():
    """Menjalankan proses mining via endpoint REST."""
    block = mine_block()
    response = {
        'message': 'New Block Forged',
        'index': block['index'],
        'transactions': block['transactions'],
        'proof': block['proof'],
        'previous_hash': block['previous_hash']
    }
    return jsonify(response), 200


@app.route('/nodes/register', methods=['POST'])
def register_nodes():
    """Mendaftarkan node tetangga baru (FR-5)."""
    values = request.get_json()
    if not values:
        return jsonify({'message': 'Missing request body'}), 400

    nodes = values.get('nodes')
    if not nodes or not isinstance(nodes, list):
        return jsonify({'message': 'Error: Please supply a valid list of nodes'}), 400

    for node in nodes:
        blockchain.register_node(node)

    with blockchain.lock:
        total_nodes = list(blockchain.nodes)

    response = {
        'message': 'New nodes have been added',
        'total_nodes': total_nodes
    }
    return jsonify(response), 201


@app.route('/nodes/resolve', methods=['GET'])
def consensus():
    """Memicu pemeriksaan konsensus Longest Chain Rule (FR-6)."""
    replaced = blockchain.resolve_conflicts()
    with blockchain.lock:
        chain_copy = list(blockchain.chain)

    if replaced:
        response = {
            'message': 'Our chain was replaced',
            'new_chain': chain_copy
        }
    else:
        response = {
            'message': 'Our chain is authoritative',
            'chain': chain_copy
        }
    return jsonify(response), 200


if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description='Run SMPL Blockchain Node')
    parser.add_argument('port', nargs='?', default=5000, type=int, help='Port to listen on (default: 5000)')
    parser.add_argument('-p', '--port_flag', dest='port_flag', type=int, help='Alternative port flag')
    args = parser.parse_args()

    port = args.port_flag if args.port_flag else args.port

    # Pastikan Blockchain diinisialisasi dengan menyertakan argumen port dari CLI
    blockchain = Blockchain(port=port)

    # debug=False & use_reloader=False agar proses terminate berjalan bersih tanpa port terkunci
    app.run(host='0.0.0.0', port=port, debug=False, use_reloader=False)
