import hashlib
import json
import sys
from time import time
from urllib.parse import urlparse
from uuid import uuid4

from flask import Flask, jsonify, request
import requests


class Blockchain:
    def __init__(self):
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
        self.append_block(genesis_block)

    def append_block(self, block):
        """
        Menambahkan blok valid ke dalam chain dan mereset antrean transaksi lokal (mempool).
        """
        self.chain.append(block)
        self.current_transactions = []
        return block

    def new_transaction(self, sender, recipient, amount):
        """
        Membuat transaksi baru yang akan masuk ke blok berikutnya yang di-mine (FR-2).
        """
        self.current_transactions.append({
            'sender': sender,
            'recipient': recipient,
            'amount': amount,
        })
        return self.last_block['index'] + 1

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
        Menambahkan node tetangga baru ke daftar node (FR-5).
        Contoh input: 'http://127.0.0.1:5001' atau '127.0.0.1:5001'
        """
        parsed_url = urlparse(address)
        if parsed_url.netloc:
            self.nodes.add(f"{parsed_url.scheme}://{parsed_url.netloc}")
        elif parsed_url.path:
            # Format tanpa skema http://
            self.nodes.add(f"http://{parsed_url.path}")

    def valid_chain(self, chain):
        """
        Menentukan apakah rantai blockchain valid (FR-6):
        - Melewati validasi pada blok index 0 (Genesis block).
        - Memverifikasi previous_hash dan PoW setiap blok mulai dari index 1.
        """
        if not chain:
            return False

        for i in range(1, len(chain)):
            prev_block = chain[i - 1]
            curr_block = chain[i]

            # 1. Periksa kesesuaian previous_hash
            if curr_block.get('previous_hash') != self.hash(prev_block):
                return False

            # 2. Periksa validitas Proof of Work blok
            if not self.valid_proof(curr_block):
                return False

        return True

    def resolve_conflicts(self):
        """
        Konsensus Longest Chain Rule (FR-6):
        Mengganti rantai lokal dengan rantai valid terpanjang di jaringan.
        """
        neighbors = self.nodes
        new_chain = None
        max_length = len(self.chain)

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
            self.chain = new_chain
            return True

        return False


# Inisialisasi Flask Node
app = Flask(__name__)

# ID Unik untuk node ini (sebagai penerima reward mining)
node_identifier = str(uuid4()).replace('-', '')

# Inisialisasi Blockchain
blockchain = Blockchain()


@app.route('/chain', methods=['GET'])
def full_chain():
    """Mengambil seluruh salinan rantai lokal."""
    response = {
        'chain': blockchain.chain,
        'length': len(blockchain.chain),
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

    index = blockchain.new_transaction(values['sender'], values['recipient'], values['amount'])
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

    # 2. Susun objek candidate_block
    last_block = blockchain.last_block
    candidate_block = {
        'index': len(blockchain.chain) + 1,
        'timestamp': time(),
        'transactions': list(blockchain.current_transactions),
        'proof': 0,
        'previous_hash': blockchain.hash(last_block)
    }

    # 3. Jalankan Proof of Work (memutasi candidate_block['proof'] in-place)
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

    response = {
        'message': 'New nodes have been added',
        'total_nodes': list(blockchain.nodes)
    }
    return jsonify(response), 201


@app.route('/nodes/resolve', methods=['GET'])
def consensus():
    """Memicu pemeriksaan konsensus Longest Chain Rule (FR-6)."""
    replaced = blockchain.resolve_conflicts()
    if replaced:
        response = {
            'message': 'Our chain was replaced',
            'new_chain': blockchain.chain
        }
    else:
        response = {
            'message': 'Our chain is authoritative',
            'chain': blockchain.chain
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
