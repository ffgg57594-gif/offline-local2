#!/usr/bin/env python3
"""Stage 3.7a: measure the refusal-gate signals for all 120 golden questions.

MEASUREMENT ONLY: no thresholds, no gate_config.json, no changes to retrieval,
fusion, embeddings, or Kotlin code.

Reads the in-scope questions (eval/golden_v3.draft.jsonl) and the
out-of-scope questions (eval/golden_v2.draft.jsonl, in_scope == false) through
scripts/gate_signals.py, computes the seven signals per question against the
built knowledge DB and embeddings.bin, and writes:

  eval/gate_signals.csv
    group, id, question, s1_top1, s2_margin, s3_cov_top3, s4_unknown,
    s5_rare_cov_top3, n_stems, n_rare, top1_chunk_id, top1_page

It also prints Outputs A-E (Output A is additionally written to
$GITHUB_STEP_SUMMARY):

  A: per signal and per group (in-scope / out-of-scope): min, p10, median,
     p90, max  (one full table, 5 signals x 2 groups)
  B: the 60 out-of-scope rows in full
  C: the 60 in-scope rows in full, plus target_chunk_id and top-1 == target
  D: 10 out-of-scope questions with the highest s1_top1 and 10 in-scope
     questions with the lowest s1_top1, each with the top-1 chunk snippet
     (250 chars centred on the best-matching sentence) and a one-line
     judgement ("would be hard to separate" / "easy")
  E: per signal, the fraction of out-of-scope questions whose value is on the
     in-scope side of the in-scope median (5-row table; no conclusion beyond it)

Percentiles use numpy default linear interpolation.
"""
import csv
import json
import math
import os
import sqlite3
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gate_signals  # noqa: E402
from gate_signals import (  # noqa: E402
    compute_signals,
    dense_top_chunks,
    load_question_sets,
)
from embedding_common import embed_texts  # noqa: E402
from evaluate_golden_v3 import snippet_centred  # noqa: E402

DB_PATH = os.path.join("app", "src", "main", "assets", "books_knowledge.db")
EMBEDDINGS_BIN = os.path.join("app", "src", "main", "assets", "embeddings.bin")
EMBEDDINGS_META = os.path.join("app", "src", "main", "assets", "embeddings_meta.json")
OUT_CSV = os.path.join("eval", "gate_signals.csv")

SIGNALS = ["s1_top1", "s2_margin", "s3_cov_top3", "s4_unknown", "s5_rare_cov_top3"]
FLOAT_FIELDS = SIGNALS
INT_FIELDS = ["n_stems", "n_rare"]

IN_GROUP = "in"
OUT_GROUP = "out"


def load_embeddings():
    with open(EMBEDDINGS_META, "r", encoding="utf-8") as f:
        meta = json.load(f)
    mat = np.fromfile(EMBEDDINGS_BIN, dtype=np.float32).reshape(meta["rows"], meta["dim"])
    return mat, meta


def percentile(vals, p):
    return float(np.percentile(np.asarray(vals, dtype=float), p))


def fmt_float(v):
    return f"{v:.6f}"


def fmt_int(v):
    return str(int(v))


def esc(cell):
    """Escape a cell for a markdown table."""
    return str(cell).replace("|", "&#124;").replace("\n", " ").strip()


def build_rows(in_scope, out_of_scope, conn, embeddings, chunk_meta):
    """Measure every question; return list of row dicts."""
    in_order = list(in_scope) + list(out_of_scope)
    texts = [q["q"] for q in in_order]
    vecs = embed_texts(texts, kind="query")
    embeddings_list = embeddings.tolist()

    text_by_cid = {c[0]: c[3] for c in chunk_meta}

    target_by_id = {}
    with open(gate_signals.GOLDEN_V3, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            obj = json.loads(line)
            if obj.get("in_scope") is True:
                target_by_id[obj["id"]] = obj.get("target_chunk_id")

    rows = []
    running = 0
    for group, qs in ((IN_GROUP, in_scope), (OUT_GROUP, out_of_scope)):
        for q in qs:
            vec = vecs[running]
            running += 1
            sig = compute_signals(
                q["q"],
                conn=conn,
                embeddings=embeddings_list,
                chunk_meta=chunk_meta,
                embed_query=lambda t, v=vec: list(v),
            )
            top1 = dense_top_chunks(
                q["q"], embeddings_list, chunk_meta,
                lambda t, v=vec: list(v), top_k=1,
            )[0]
            rows.append({
                "group": group,
                "id": q["id"],
                "question": q["q"],
                **sig,
                "top1_chunk_id": top1[0],
                "top1_page": top1[2],
                "target_chunk_id": target_by_id.get(q["id"]),
                "key_terms": q.get("key_terms") or [],
                "top1_text": text_by_cid.get(top1[0], ""),
            })
    return rows


def output_a_table(rows):
    lines = [
        "### Output A: signal distributions per signal and group",
        "",
        "| Signal | Group | Min | p10 | Median | p90 | Max |",
        "|---|---|---|---|---|---|---|",
    ]
    for sig in SIGNALS:
        for group, label in ((IN_GROUP, "in-scope"), (OUT_GROUP, "out-of-scope")):
            vals = [r[sig] for r in rows if r["group"] == group]
            lines.append(
                f"| {sig} | {label} | {fmt_float(min(vals))} | {fmt_float(percentile(vals, 10))} "
                f"| {fmt_float(percentile(vals, 50))} | {fmt_float(percentile(vals, 90))} "
                f"| {fmt_float(max(vals))} |"
            )
    lines.append("")
    return "\n".join(lines)


def output_b_table(rows):
    oos = [r for r in rows if r["group"] == OUT_GROUP]
    oos.sort(key=lambda r: r["id"])
    lines = [
        "### Output B: out-of-scope rows in full (60)",
        "",
        "| id | question | key_terms | s1_top1 | s2_margin | s3_cov_top3 | s4_unknown | s5_rare_cov_top3 | top-1 page |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for r in oos:
        lines.append(
            f"| {r['id']} | {esc(r['question'])} | {esc(', '.join(r['key_terms']))} "
            f"| {fmt_float(r['s1_top1'])} | {fmt_float(r['s2_margin'])} | {fmt_float(r['s3_cov_top3'])} "
            f"| {fmt_int(r['s4_unknown'])} | {fmt_float(r['s5_rare_cov_top3'])} | {r['top1_page']} |"
        )
    lines.append("")
    return "\n".join(lines)


def output_c_table(rows):
    ins = [r for r in rows if r["group"] == IN_GROUP]
    ins.sort(key=lambda r: r["id"])
    lines = [
        "### Output C: in-scope rows in full (60)",
        "",
        "| id | question | s1_top1 | s2_margin | s3_cov_top3 | s4_unknown | s5_rare_cov_top3 | top-1 page | target_chunk_id | top-1 == target |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for r in ins:
        target = r["target_chunk_id"]
        match = "Yes" if target is not None and r["top1_chunk_id"] == target else "No"
        lines.append(
            f"| {r['id']} | {esc(r['question'])} | {fmt_float(r['s1_top1'])} | {fmt_float(r['s2_margin'])} "
            f"| {fmt_float(r['s3_cov_top3'])} | {fmt_int(r['s4_unknown'])} | {fmt_float(r['s5_rare_cov_top3'])} "
            f"| {r['top1_page']} | {target} | {match} |"
        )
    lines.append("")
    return "\n".join(lines)


def _judgement(s1, group_lo, group_hi):
    return "would be hard to separate" if group_lo <= s1 <= group_hi else "easy"


def output_d_table(rows):
    oos = [r for r in rows if r["group"] == OUT_GROUP]
    ins = [r for r in rows if r["group"] == IN_GROUP]
    oos_high = sorted(oos, key=lambda r: (-r["s1_top1"], r["id"]))[:10]
    ins_low = sorted(ins, key=lambda r: (r["s1_top1"], r["id"]))[:10]

    in_s1 = [r["s1_top1"] for r in ins]
    oos_s1 = [r["s1_top1"] for r in oos]
    in_lo, in_hi = min(in_s1), max(in_s1)
    oos_lo, oos_hi = min(oos_s1), max(oos_s1)

    lines = [
        "### Output D: separation probe (10 out-of-scope with highest s1_top1,",
        "10 in-scope with lowest s1_top1)",
        "",
        "| Group | id | question | key_terms | s1_top1 | s2_margin | s3_cov_top3 | s4_unknown |",
        "| s5_rare_cov_top3 | top-1 page | top-1 chunk snippet (250 chars) | Judgement |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for r in oos_high:
        snippet = esc(snippet_centred(r["top1_text"], r["question"], window=250))
        lines.append(
            f"| out-of-scope | {r['id']} | {esc(r['question'])} | "
            f"{esc(', '.join(r['key_terms']))} | {fmt_float(r['s1_top1'])} | {fmt_float(r['s2_margin'])} "
            f"| {fmt_float(r['s3_cov_top3'])} | {fmt_int(r['s4_unknown'])} | {fmt_float(r['s5_rare_cov_top3'])} "
            f"| {r['top1_page']} | {snippet} | {_judgement(r['s1_top1'], in_lo, in_hi)} |"
        )
    for r in ins_low:
        snippet = esc(snippet_centred(r["top1_text"], r["question"], window=250))
        lines.append(
            f"| in-scope | {r['id']} | {esc(r['question'])} | {esc(', '.join(r['key_terms']))} "
            f"| {fmt_float(r['s1_top1'])} | {fmt_float(r['s2_margin'])} | {fmt_float(r['s3_cov_top3'])} "
            f"| {fmt_int(r['s4_unknown'])} | {fmt_float(r['s5_rare_cov_top3'])} | {r['top1_page']} | "
            f"{snippet} | {_judgement(r['s1_top1'], oos_lo, oos_hi)} |"
        )
    lines.append("")
    return "\n".join(lines)


def output_e_table(rows):
    ins = [r for r in rows if r["group"] == IN_GROUP]
    oos = [r for r in rows if r["group"] == OUT_GROUP]
    lines = [
        "### Output E: out-of-scope mass on the in-scope side of the in-scope median",
        "",
        "| Signal | In-scope median | OOS fraction on in-scope side | OOS count (of 60) |",
        "|---|---|---|---|",
    ]
    for sig in SIGNALS:
        in_vals = [r[sig] for r in ins]
        median = percentile(in_vals, 50)
        if sig == "s4_unknown":
            # For s4, zero unknowns is more in-scope: the in-scope side is <= median.
            side = sum(1 for r in oos if r[sig] <= median)
        else:
            side = sum(1 for r in oos if r[sig] >= median)
        lines.append(
            f"| {sig} | {fmt_float(median)} | {side / 60:.4f} ({side}/60) | {side} |"
        )
    lines.append("")
    return "\n".join(lines)


def write_csv(rows):
    os.makedirs(os.path.dirname(OUT_CSV), exist_ok=True)
    columns = ["group", "id", "question"] + FLOAT_FIELDS + INT_FIELDS + [
        "top1_chunk_id", "top1_page",
    ]
    with open(OUT_CSV, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(columns)
        for r in rows:
            w.writerow([
                r["group"], r["id"], r["question"],
                *[fmt_float(r[s]) for s in FLOAT_FIELDS],
                *[fmt_int(r[s]) for s in INT_FIELDS],
                r["top1_chunk_id"], r["top1_page"],
            ])


def main():
    if not os.path.exists(DB_PATH):
        print(f"ERROR: {DB_PATH} not found. Run build_knowledge_db.py first.", file=sys.stderr)
        sys.exit(1)
    if not os.path.exists(EMBEDDINGS_BIN):
        print(f"ERROR: {EMBEDDINGS_BIN} not found. Run build_embeddings.py first.", file=sys.stderr)
        sys.exit(1)

    in_scope, out_of_scope = load_question_sets()
    print(f"Questions: {len(in_scope)} in-scope, {len(out_of_scope)} out-of-scope")

    conn = sqlite3.connect(DB_PATH)
    embeddings, meta = load_embeddings()
    chunk_meta = conn.execute(
        "SELECT c.id, b.name, c.page, c.text, c.search_text FROM chunks c "
        "JOIN books b ON b.id = c.book_id ORDER BY c.id"
    ).fetchall()
    if len(chunk_meta) != embeddings.shape[0]:
        print(f"ERROR: chunks ({len(chunk_meta)}) != embeddings rows ({embeddings.shape[0]}).",
              file=sys.stderr)
        sys.exit(1)

    rows = build_rows(in_scope, out_of_scope, conn, embeddings, chunk_meta)
    assert len(rows) == 120, len(rows)
    write_csv(rows)
    print(f"Wrote {OUT_CSV} with {len(rows)} rows")

    tables = [
        output_a_table(rows),
        output_b_table(rows),
        output_c_table(rows),
        output_d_table(rows),
        output_e_table(rows),
    ]
    report = "\n".join(tables)
    print(report)

    step_summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if step_summary:
        with open(step_summary, "a", encoding="utf-8") as f:
            f.write("\n## Gate signal measurements (Stage 3.7a)\n\n")
            f.write(tables[0])  # Output A
            f.write("\n\nFull tables B-E and the CSV artifact (eval/gate_signals.csv) are in the step log.\n")
    conn.close()
    print("\nGate signal measurement complete.")


if __name__ == "__main__":
    main()
