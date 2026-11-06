#!/usr/bin/env python3
"""Compile tokenizer.json into binary format tokenizer.bin.

Format (Little-Endian):
Header:
  - magic: 4 bytes b"TKBN"
  - version: uint32 = 1
  - json_sha256: 32 bytes (raw sha256 bytes of tokenizer.json)
  - unk_id: int32
  - bos_id: int32
  - eos_id: int32
  - vocab_size: int32 (e.g. 250002)
  - min_score: float64
  - charsmap_len: int32
  - piece_blob_len: int32
  - trie_node_count: int32

Data Sections:
  1. charsmap_bytes: raw bytes of decoded precompiled_charsmap (length charsmap_len)
  2. vocab_scores: float32 array of shape (vocab_size,) [vocab_size * 4 bytes]
  3. piece_offsets: int32 array of shape (vocab_size + 1,) [(vocab_size + 1) * 4 bytes]
  4. piece_blob: UTF-8 bytes for all pieces concatenated [piece_blob_len bytes]
  5. trie_node_byte: int8/uint8 array of shape (trie_node_count,) [trie_node_count bytes]
  6. trie_node_vocab_id: int32 array of shape (trie_node_count,) [trie_node_count * 4 bytes]
  7. trie_node_first_child: int32 array of shape (trie_node_count,) [trie_node_count * 4 bytes]
  8. trie_node_next_sibling: int32 array of shape (trie_node_count,) [trie_node_count * 4 bytes]
"""
import sys
import os
import json
import base64
import struct
import hashlib
import time

def compile_tokenizer(json_path, bin_path):
    print(f"Reading {json_path}...")
    t0 = time.time()
    with open(json_path, "rb") as f:
        json_bytes = f.read()
    
    json_sha256 = hashlib.sha256(json_bytes).digest()
    
    data = json.loads(json_bytes.decode("utf-8"))
    
    # 1. Model & special tokens
    model = data.get("model", {})
    unk_id = model.get("unk_id", 3)
    vocab = model.get("vocab", [])
    vocab_size = len(vocab)
    
    bos_id = 0
    eos_id = 2
    for token in data.get("added_tokens", []):
        content = token.get("content")
        tid = token.get("id")
        if content == "<s>":
            bos_id = tid
        elif content == "</s>":
            eos_id = tid

    # 2. Charsmap
    charsmap_bytes = b""
    normalizer = data.get("normalizer", {})
    if normalizer.get("type") == "Precompiled":
        charsmap_bytes = base64.b64decode(normalizer.get("precompiled_charsmap", ""))
    elif normalizer.get("type") == "Sequence":
        for sub in normalizer.get("normalizers", []):
            if sub.get("type") == "Precompiled":
                charsmap_bytes = base64.b64decode(sub.get("precompiled_charsmap", ""))
                break
    
    charsmap_len = len(charsmap_bytes)

    # 3. Scores & Pieces
    min_score = 1e9
    scores = []
    piece_blob = bytearray()
    piece_offsets = []
    
    for piece, score in vocab:
        score_val = float(score)
        scores.append(score_val)
        if score_val < min_score:
            min_score = score_val
        piece_offsets.append(len(piece_blob))
        piece_blob.extend(piece.encode("utf-8"))
    piece_offsets.append(len(piece_blob))
    piece_blob_bytes = bytes(piece_blob)
    piece_blob_len = len(piece_blob_bytes)
    
    print(f"Parsed vocab: {vocab_size} pieces, blob {piece_blob_len} bytes, min_score {min_score}")

    # 4. Trie construction
    print("Building trie...")
    t_trie = time.time()
    root = {}
    for vocab_id, (piece, _) in enumerate(vocab):
        curr = root
        for b in piece.encode("utf-8"):
            if b not in curr:
                curr[b] = {}
            curr = curr[b]
        curr[-1] = vocab_id

    node_byte = bytearray([0])
    node_vocab_id = [-1]
    node_first_child = [-1]
    node_next_sibling = [-1]

    def flatten(curr_dict, node_idx):
        prev_child_idx = -1
        for b in sorted(k for k in curr_dict.keys() if k != -1):
            child_dict = curr_dict[b]
            child_idx = len(node_byte)
            node_byte.append(b)
            node_vocab_id.append(child_dict.get(-1, -1))
            node_first_child.append(-1)
            node_next_sibling.append(-1)

            if prev_child_idx == -1:
                node_first_child[node_idx] = child_idx
            else:
                node_next_sibling[prev_child_idx] = child_idx
            prev_child_idx = child_idx
            flatten(child_dict, child_idx)

    node_vocab_id[0] = root.get(-1, -1)
    flatten(root, 0)
    
    trie_node_count = len(node_byte)
    print(f"Trie built: {trie_node_count} nodes in {time.time() - t_trie:.2f}s")

    # 5. Pack binary file
    print(f"Writing binary output to {bin_path}...")
    with open(bin_path, "wb") as out:
        # Header (4 + 4 + 32 + 4*5 + 8 + 4*3 = 80 bytes)
        # magic(4s), version(I), sha256(32s), unk_id(i), bos_id(i), eos_id(i), vocab_size(i), min_score(d), charsmap_len(i), piece_blob_len(i), trie_node_count(i)
        header = struct.pack(
            "<4sI32siiiidiii",
            b"TKBN",
            1,
            json_sha256,
            unk_id,
            bos_id,
            eos_id,
            vocab_size,
            min_score,
            charsmap_len,
            piece_blob_len,
            trie_node_count
        )
        out.write(header)
        
        # 1. Charsmap
        out.write(charsmap_bytes)
        
        # 2. Vocab scores (float32 array)
        out.write(struct.pack(f"<{vocab_size}f", *scores))
        
        # 3. Piece offsets (int32 array)
        out.write(struct.pack(f"<{vocab_size + 1}i", *piece_offsets))
        
        # 4. Piece blob
        out.write(piece_blob_bytes)
        
        # 5. Trie node byte (uint8)
        out.write(node_byte)
        
        # 6. Trie node vocab id (int32)
        out.write(struct.pack(f"<{trie_node_count}i", *node_vocab_id))
        
        # 7. Trie node first child (int32)
        out.write(struct.pack(f"<{trie_node_count}i", *node_first_child))
        
        # 8. Trie node next sibling (int32)
        out.write(struct.pack(f"<{trie_node_count}i", *node_next_sibling))

    size_mb = os.path.getsize(bin_path) / (1024 * 1024)
    print(f"Successfully generated {bin_path}: {size_mb:.2f} MB in {time.time() - t0:.2f}s total.")

if __name__ == "__main__":
    src = sys.argv[1] if len(sys.argv) > 1 else "app/src/main/assets/models/embedder/tokenizer.json"
    dst = sys.argv[2] if len(sys.argv) > 2 else "app/src/main/assets/models/embedder/tokenizer.bin"
    compile_tokenizer(src, dst)
