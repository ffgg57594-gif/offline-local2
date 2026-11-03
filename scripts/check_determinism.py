#!/usr/bin/env python3
"""Stage 3.7d-check: Determinism, CPU flags, and silent change verification.

Task 1: Print lscpu "Model name" and "Flags" (detect avx2, avx512f, avx512_vnni),
        onnxruntime version, and intra_op thread count used.
Task 2: Embed the 24 reference texts and 120 golden questions twice:
        - once in same process
        - once in fresh process
        - with intra_op_num_threads 1 and 4
        Print min and mean cosine between repeated embeddings, and maximum
        absolute difference in s1 for the 120 questions.
"""
import hashlib
import json
import os
import subprocess
import sys
import numpy as np
import onnxruntime as ort
from tokenizers import Tokenizer

MODEL_DIR = os.path.join("app", "src", "main", "assets", "models", "embedder")
MODEL_PATH = os.path.join(MODEL_DIR, "model_quantized.onnx")
TOKENIZER_PATH = os.path.join(MODEL_DIR, "tokenizer.json")
DB_PATH = os.path.join("app", "src", "main", "assets", "books_knowledge.db")
EMBEDDINGS_BIN = os.path.join("app", "src", "main", "assets", "embeddings.bin")
EMBEDDINGS_META = os.path.join("app", "src", "main", "assets", "embeddings_meta.json")
REF_PATH = os.path.join("app", "src", "main", "assets", "embedder_reference.json")

GOLDEN_V3 = os.path.join("eval", "golden_v3.draft.jsonl")
GOLDEN_OOS_V3 = os.path.join("eval", "golden_oos_v3.jsonl")

MAX_LENGTH = 384
EMBED_DIM = 384
PASSAGE_PREFIX = "passage: "
QUERY_PREFIX = "query: "


def print_cpu_info():
    print("=== TASK 1: CPU INFO & ONNX CONFIG ===")
    model_name = "Unknown"
    flags = []
    try:
        out = subprocess.check_output(["lscpu"], text=True)
        for line in out.splitlines():
            if "Model name:" in line:
                model_name = line.split(":", 1)[1].strip()
                print(f"Model name: {model_name}")
            elif line.startswith("Flags:"):
                flags = line.split(":", 1)[1].strip().split()
                print(f"Flags line present: yes ({len(flags)} flags)")
    except Exception as e:
        print(f"Error reading lscpu: {e}")

    checked_flags = ["avx2", "avx512f", "avx512_vnni"]
    for fl in checked_flags:
        present = "PRESENT" if fl in flags else "ABSENT"
        print(f"  Flag {fl}: {present}")

    print(f"onnxruntime version: {ort.__version__}")
    
    # Check default intra_op threads
    so = ort.SessionOptions()
    print(f"Default session intra_op_num_threads: {so.intra_op_num_threads} (0 = engine auto-select)")


def tokenize_batch(tokenizer, texts):
    encodings = tokenizer.encode_batch(texts)
    max_len = min(MAX_LENGTH, max(len(e.ids) for e in encodings))
    input_ids = []
    attention_masks = []
    for enc in encodings:
        ids = enc.ids[:max_len]
        mask = [1] * len(ids)
        pad_len = max_len - len(ids)
        ids += [0] * pad_len
        mask += [0] * pad_len
        input_ids.append(ids)
        attention_masks.append(mask)
    return np.array(input_ids, dtype=np.int64), np.array(attention_masks, dtype=np.int64)


def mean_pool(last_hidden, attention_mask):
    mask = attention_mask.astype(np.float64)
    mask_sum = np.clip(np.sum(mask, axis=1, keepdims=True), 1e-9, None)
    masked = last_hidden.astype(np.float64) * mask[:, :, None]
    return np.sum(masked, axis=1) / mask_sum


def l2_normalize(vectors):
    norms = np.clip(np.linalg.norm(vectors, axis=1, keepdims=True), 1e-12, None)
    return vectors / norms


def embed_batch(session, tokenizer, texts, kind="query"):
    prefix = QUERY_PREFIX if kind == "query" else PASSAGE_PREFIX
    prefixed = [prefix + t for t in texts]
    input_ids, attention_mask = tokenize_batch(tokenizer, prefixed)
    outputs = session.run(
        None,
        {
            "input_ids": input_ids,
            "attention_mask": attention_mask,
            "token_type_ids": np.zeros_like(input_ids),
        },
    )
    pooled = mean_pool(outputs[0], attention_mask)
    normed = l2_normalize(pooled)
    return normed.astype(np.float32)


def load_golden_120():
    texts = []
    with open(GOLDEN_V3, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                texts.append(json.loads(line)["q"])
    with open(GOLDEN_OOS_V3, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                texts.append(json.loads(line)["q"])
    assert len(texts) == 120, f"Expected 120 questions, got {len(texts)}"
    return texts


def load_ref_24():
    with open(REF_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
    entries = data["entries"] if "entries" in data else data
    assert len(entries) == 24, f"Expected 24 entries, got {len(entries)}"
    return entries


def compute_s1_for_all(query_vecs, chunk_embeddings):
    # chunk_embeddings: [N, 384] float32
    # query_vecs: [120, 384] float32
    # s1 = max cosine (dot product since normalized)
    dots = np.dot(query_vecs, chunk_embeddings.T)  # [120, N]
    s1_vals = np.max(dots, axis=1)
    return s1_vals


def run_determinism_test():
    print("\n=== TASK 2: DETERMINISM TEST ===")
    ref_entries = load_ref_24()
    golden_questions = load_golden_120()

    with open(EMBEDDINGS_META, "r", encoding="utf-8") as f:
        meta = json.load(f)
    chunk_embeddings = np.fromfile(EMBEDDINGS_BIN, dtype=np.float32).reshape(meta["rows"], meta["dim"])

    tokenizer = Tokenizer.from_file(TOKENIZER_PATH)

    # We test:
    # A) threads=1 vs threads=1 (same process, repeated)
    # B) threads=4 vs threads=4 (same process, repeated)
    # C) threads=1 vs threads=4
    # D) fresh process execution

    def get_embeddings(threads):
        so = ort.SessionOptions()
        so.intra_op_num_threads = threads
        sess = ort.InferenceSession(MODEL_PATH, sess_options=so, providers=["CPUExecutionProvider"])
        
        # Embed ref 24
        ref_vecs = []
        for e in ref_entries:
            v = embed_batch(sess, tokenizer, [e["input"]], kind=e["kind"])[0]
            ref_vecs.append(v)
        ref_arr = np.array(ref_vecs)

        # Embed golden 120
        golden_arr = embed_batch(sess, tokenizer, golden_questions, kind="query")
        return ref_arr, golden_arr

    print("Running Pass 1 (threads=1)...")
    ref_t1_p1, g_t1_p1 = get_embeddings(threads=1)
    print("Running Pass 2 (threads=1, same process)...")
    ref_t1_p2, g_t1_p2 = get_embeddings(threads=1)

    print("Running Pass 1 (threads=4)...")
    ref_t4_p1, g_t4_p1 = get_embeddings(threads=4)
    print("Running Pass 2 (threads=4, same process)...")
    ref_t4_p2, g_t4_p2 = get_embeddings(threads=4)

    # Comparisons
    comparisons = [
        ("Same process, threads=1 (Pass 1 vs Pass 2)", ref_t1_p1, g_t1_p1, ref_t1_p2, g_t1_p2),
        ("Same process, threads=4 (Pass 1 vs Pass 2)", ref_t4_p1, g_t4_p1, ref_t4_p2, g_t4_p2),
        ("Cross-threads (threads=1 vs threads=4)", ref_t1_p1, g_t1_p1, ref_t4_p1, g_t4_p1),
    ]

    for name, r1, g1, r2, g2 in comparisons:
        # Ref cosine
        cos_ref = np.sum(r1 * r2, axis=1)  # dot product of normalized
        # Golden cosine
        cos_g = np.sum(g1 * g2, axis=1)

        all_cos = np.concatenate([cos_ref, cos_g])
        min_cos = float(np.min(all_cos))
        mean_cos = float(np.mean(all_cos))

        s1_1 = compute_s1_for_all(g1, chunk_embeddings)
        s1_2 = compute_s1_for_all(g2, chunk_embeddings)
        diff_s1 = np.abs(s1_1 - s1_2)
        max_diff_s1 = float(np.max(diff_s1))
        mean_diff_s1 = float(np.mean(diff_s1))

        print(f"\nCondition: {name}")
        print(f"  Cosine (24 ref + 120 golden): min = {min_cos:.9f}, mean = {mean_cos:.9f}")
        print(f"  s1 absolute difference (120 questions): max = {max_diff_s1:.9f}, mean = {mean_diff_s1:.9f}")

    # Fresh process test
    print("\nRunning Fresh Process test (threads=1 in subprocess)...")
    # Save g_t1_p1 to /tmp
    np.save("/tmp/g_t1_p1.npy", g_t1_p1)
    sub_code = """
import json, os, numpy as np, onnxruntime as ort
from tokenizers import Tokenizer
import check_determinism as cd

meta = json.load(open(cd.EMBEDDINGS_META))
chunk_emb = np.fromfile(cd.EMBEDDINGS_BIN, dtype=np.float32).reshape(meta['rows'], meta['dim'])
so = ort.SessionOptions()
so.intra_op_num_threads = 1
sess = ort.InferenceSession(cd.MODEL_PATH, sess_options=so, providers=['CPUExecutionProvider'])
tok = Tokenizer.from_file(cd.TOKENIZER_PATH)
g_qs = cd.load_golden_120()
g_vecs = cd.embed_batch(sess, tok, g_qs, kind='query')
ref_entries = cd.load_ref_24()
ref_vecs = np.array([cd.embed_batch(sess, tok, [e['input']], kind=e['kind'])[0] for e in ref_entries])

g_t1_p1 = np.load('/tmp/g_t1_p1.npy')
cos_g = np.sum(g_vecs * g_t1_p1, axis=1)
s1_old = cd.compute_s1_for_all(g_t1_p1, chunk_emb)
s1_new = cd.compute_s1_for_all(g_vecs, chunk_emb)
diff_s1 = np.abs(s1_old - s1_new)
print(f"Fresh process vs parent (threads=1):")
print(f"  Cosine (120 golden): min = {np.min(cos_g):.9f}, mean = {np.mean(cos_g):.9f}")
print(f"  s1 absolute diff (120 golden): max = {np.max(diff_s1):.9f}, mean = {np.mean(diff_s1):.9f}")
"""
    cmd = [sys.executable, "-c", sub_code]
    subprocess.run(cmd, env={**os.environ, "PYTHONPATH": "scripts"})


def check_schema_and_silent_changes():
    print("\n=== TASK 4: SCHEMA & SILENT CHANGES INSPECTION ===")
    import sqlite3
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    if not os.path.exists(DB_PATH):
        print(f"Database {DB_PATH} not found.")
        return
    schema_ver = cur.execute("PRAGMA schema_version").fetchone()[0]
    user_ver = cur.execute("PRAGMA user_version").fetchone()[0]
    tables = [r[0] for r in cur.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
    if 'chunks' not in tables:
        print(f"Table 'chunks' not yet built in {DB_PATH}. Tables present: {tables}")
        conn.close()
        return
    cols = [r[1] for r in cur.execute("PRAGMA table_info(chunks)").fetchall()]
    chunk_count = cur.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
    
    cur.execute("SELECT id, text FROM chunks ORDER BY id")
    all_text = "".join(r[1] for r in cur.fetchall())
    db_chunk_hash = hashlib.sha256(all_text.encode("utf-8")).hexdigest()
    conn.close()

    print(f"Database: {DB_PATH}")
    print(f"  schema_version: {schema_ver}, user_version: {user_ver}")
    print(f"  chunks table columns: {cols}")
    print(f"  chunk count: {chunk_count}")
    print(f"  db chunk_texts_sha256: {db_chunk_hash}")

    if os.path.exists(EMBEDDINGS_META):
        with open(EMBEDDINGS_META, "r", encoding="utf-8") as f:
            meta = json.load(f)
        meta_chunk_hash = meta.get("chunk_texts_sha256", "none")
        print(f"embeddings_meta.json chunk_texts_sha256: {meta_chunk_hash}")
        print(f"  MATCH: {db_chunk_hash == meta_chunk_hash}")

    if os.path.exists(REF_PATH):
        with open(REF_PATH, "r", encoding="utf-8") as f:
            ref_data = json.load(f)
        entries = ref_data.get("entries", ref_data)
        count = len(entries)
        dim = len(entries[0]["vector"]) if count > 0 and "vector" in entries[0] else 0
        has_full_vectors = all(len(e.get("vector", [])) == 384 for e in entries)
        print(f"embedder_reference.json:")
        print(f"  number of entries: {count}")
        print(f"  vector dimension: {dim}")
        print(f"  all 24 entries have full 384-float vectors: {has_full_vectors}")


def main():
    print_cpu_info()
    check_schema_and_silent_changes()
    if os.path.exists(MODEL_PATH) and os.path.exists(EMBEDDINGS_BIN):
        run_determinism_test()
    else:
        print("\nNote: MODEL_PATH or EMBEDDINGS_BIN not found locally; determinism test will run in CI.")


if __name__ == "__main__":
    main()
