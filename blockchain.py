import hashlib
import json
import threading
from time import time
from urllib.parse import urlparse
from uuid import uuid4

from flask import Flask, jsonify, request
import requests


class Blockchain:
    def __init__(self):
        self.lock = threading.Lock()

        with self.lock:
            self.chain = []
            self.current_transactions = []
            self.nodes = set()

            # Inisialisasi Genesis Block (FR-1)
            genesis_block = {
                'index': 1,
                'timestamp': time(),
                'transactions': [],
                'proof': 100,
                'previous_hash': '1'
            }
            self.chain.append(genesis_block)

    def append_block(self, block):
        """
        Menambahkan blok valid ke dalam chain dan mereset antrean transaksi lokal (mempool).
        Dilindungi oleh self.lock untuk thread-safety.
        """
        with self.lock:
            self.chain.append(block)
            self.current_transactions = []
            return block

    @staticmethod
    def calculate_balance_for_chain(address, chain):
        """
        Menghitung total koin masuk (recipient) dikurangi koin keluar (sender) dari seluruh blok.
        Transaksi coinbase (sender: '0') dihitung sebagai penambahan saldo bagi recipient.
        """
        balance = 0.0
        for block in chain:
            for tx in block.get('transactions', []):
                sender = tx.get('sender')
                recipient = tx.get('recipient')
                amount = float(tx.get('amount', 0))

                if recipient == address:
                    balance += amount
                if sender == address:
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

    def new_transaction(self, sender, recipient, amount):
        """
        Membuat transaksi baru yang akan masuk ke blok berikutnya yang di-mine (FR-2).
        Dilindungi oleh self.lock untuk thread-safety.
        Mencegah double-spending dan transaksi defisit saldo:
        - Abaikan validasi saldo jika sender == '0' (reward coinbase).
        - Hitung total amount yang sudah dikomit oleh sender di self.current_transactions (pending_spent).
        - Jika get_balance(sender) - pending_spent < amount, tolak dengan ValueError('Saldo tidak mencukupi').
        """
        with self.lock:
            amt = float(amount)
            if amt <= 0:
                raise ValueError("Jumlah transfer harus lebih besar dari 0")

            if sender != "0":
                current_balance = self.calculate_balance_for_chain(sender, self.chain)
                pending_spent = sum(
                    float(tx.get('amount', 0))
                    for tx in self.current_transactions
                    if tx.get('sender') == sender
                )
                if current_balance - pending_spent < amt:
                    raise ValueError("Saldo tidak mencukupi")

            formatted_amt = int(amt) if amt.is_integer() else amt
            self.current_transactions.append({
                'sender': sender,
                'recipient': recipient,
                'amount': formatted_amt,
            })
            return self.chain[-1]['index'] + 1

    @property
    def last_block(self):
        with self.lock:
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

                if sender == "0":
                    # Transaksi coinbase reward: tambah saldo recipient
                    balances[recipient] = balances.get(recipient, 0.0) + amount
                else:
                    # Transaksi reguler: cek apakah saldo kumulatif sender mencukupi
                    sender_bal = balances.get(sender, 0.0)
                    if sender_bal < amount:
                        return False
                    balances[sender] = sender_bal - amount
                    balances[recipient] = balances.get(recipient, 0.0) + amount

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
                    return (tx.get('sender'), tx.get('recipient'), float(tx.get('amount', 0)))

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

            return True

        return False


# Inisialisasi Flask Node
app = Flask(__name__)

# ID Unik untuk node ini (sebagai penerima reward mining)
node_identifier = str(uuid4()).replace('-', '')

# Inisialisasi Blockchain
blockchain = Blockchain()


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
    """
    Menjalankan proses mining:
    1. Masukkan transaksi reward coinbase ke current_transactions terlebih dahulu.
    2. Susun objek candidate_block.
    3. Jalankan proof_of_work(candidate_block) yang memutasi field 'proof' in-place.
    4. Simpan ke chain via append_block.
    """
    # 1. Transaksi reward mining (FR-4)
    blockchain.new_transaction(
        sender="0",
        recipient=node_identifier,
        amount=1,
    )

    # 2. Susun objek candidate_block di bawah lock
    with blockchain.lock:
        last_block = blockchain.chain[-1]
        candidate_block = {
            'index': len(blockchain.chain) + 1,
            'timestamp': time(),
            'transactions': list(blockchain.current_transactions),
            'proof': 0,
            'previous_hash': blockchain.hash(last_block)
        }

    # 3. Jalankan Proof of Work (komputasi CPU intensif dilakukan di luar lock)
    blockchain.proof_of_work(candidate_block)

    # 4. Simpan ke chain dan reset mempool
    block = blockchain.append_block(candidate_block)

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

    # debug=False & use_reloader=False agar proses terminate berjalan bersih tanpa port terkunci
    app.run(host='0.0.0.0', port=port, debug=False, use_reloader=False)
