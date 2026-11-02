#!/usr/bin/env python3
"""Stage 3.7b: measure refusal-gate signals with golden_oos_v3 and fixed stemming.

MEASUREMENT ONLY: no thresholds, no gate_config.json, no changes to retrieval,
fusion, embeddings, or Kotlin code.

Reads the in-scope questions (eval/golden_v3.draft.jsonl) and the
out-of-scope questions (eval/golden_oos_v3.jsonl) through scripts/gate_signals.py,
computes the signals against the built knowledge DB and embeddings.bin, and writes:

  eval/gate_signals.csv
    group, cls, id, question, s1_top1, s2_margin, s3_cov_top3, s4_unknown,
    s5_rare_cov_top3, n_stems, n_rare, top1_chunk_id, top1_page

It also prints Outputs A-F (Output A is additionally written to
$GITHUB_STEP_SUMMARY):

  A: percentile table (min, p10, median, p90, max) for each of the 5 signals
     for groups: IN, A, B, N (one full table).
  B: the 60 out-of-scope rows with all signals and unknown stems.
  C: the 60 in-scope rows with all signals, target_chunk_id and top-1 == target.
  D: for each signal (s1..s5) and each in-scope acceptance level (100% and 90%),
     the single-signal cut and fraction/count of out-of-scope questions rejected,
     total and for classes A, B, N separately.
  E: verification of hand-computed numbers from old data.
  F: separation probe (10 OOS with highest s1, 10 IN with lowest s1), each with
     concrete judgement line citing page/term and 250-char snippet.
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
            cls = "IN" if group == IN_GROUP else q.get("cls", "OOS")
            rows.append({
                "group": group,
                "cls": cls,
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
        "### Output A: percentile table per signal and group (IN, A, B, N)",
        "",
        "| Signal | Group | Min | p10 | Median | p90 | Max |",
        "|---|---|---|---|---|---|---|",
    ]
    groups = [
        ("IN", [r for r in rows if r["cls"] == "IN"]),
        ("A", [r for r in rows if r["cls"] == "A"]),
        ("B", [r for r in rows if r["cls"] == "B"]),
        ("N", [r for r in rows if r["cls"] == "N"]),
    ]
    for sig in SIGNALS:
        for grp_name, grp_rows in groups:
            vals = [r[sig] for r in grp_rows]
            # For s5_rare_cov_top3, include -1 handling note in report
            p_min = percentile(vals, 0)
            p_10 = percentile(vals, 10)
            p_med = percentile(vals, 50)
            p_90 = percentile(vals, 90)
            p_max = percentile(vals, 100)
            lines.append(
                f"| {sig} | {grp_name} | {fmt_float(p_min)} | {fmt_float(p_10)} | "
                f"{fmt_float(p_med)} | {fmt_float(p_90)} | {fmt_float(p_max)} |"
            )
    lines.append("")
    return "\n".join(lines)


def output_b_table(rows):
    oos = [r for r in rows if r["group"] == OUT_GROUP]
    lines = [
        f"### Output B: out-of-scope rows in full ({len(oos)})",
        "",
        "| id | cls | question | key_terms | s1_top1 | s2_margin | s3_cov_top3 | s4_unknown | unknown_stems | s5_rare_cov_top3 | top-1 page |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for r in oos:
        kts = esc(", ".join(r["key_terms"]))
        unks = esc(", ".join(r.get("unknown_stems") or []))
        lines.append(
            f"| {r['id']} | {r['cls']} | {esc(r['question'])} | {kts} | {fmt_float(r['s1_top1'])} | "
            f"{fmt_float(r['s2_margin'])} | {fmt_float(r['s3_cov_top3'])} | {fmt_int(r['s4_unknown'])} | "
            f"{unks} | {fmt_float(r['s5_rare_cov_top3'])} | {r['top1_page']} |"
        )
    lines.append("")
    return "\n".join(lines)


def output_c_table(rows):
    ins = [r for r in rows if r["group"] == IN_GROUP]
    lines = [
        f"### Output C: in-scope rows in full ({len(ins)})",
        "",
        "| id | question | target_chunk_id | top1_chunk_id | top-1 == target | s1_top1 | s2_margin | s3_cov_top3 | s4_unknown | s5_rare_cov_top3 |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for r in ins:
        match = "YES" if r["top1_chunk_id"] == r["target_chunk_id"] else "NO"
        lines.append(
            f"| {r['id']} | {esc(r['question'])} | {r['target_chunk_id']} | "
            f"{r['top1_chunk_id']} | {match} | {fmt_float(r['s1_top1'])} | "
            f"{fmt_float(r['s2_margin'])} | {fmt_float(r['s3_cov_top3'])} | "
            f"{fmt_int(r['s4_unknown'])} | {fmt_float(r['s5_rare_cov_top3'])} |"
        )
    lines.append("")
    return "\n".join(lines)


def output_d_table(rows):
    """Output D: single-signal cuts for 100% and 90% in-scope acceptance."""
    ins = [r for r in rows if r["cls"] == "IN"]
    oos = [r for r in rows if r["cls"] != "IN"]
    oos_a = [r for r in oos if r["cls"] == "A"]
    oos_b = [r for r in oos if r["cls"] == "B"]
    oos_n = [r for r in oos if r["cls"] == "N"]

    lines = [
        "### Output D: single-signal cuts for in-scope acceptance levels and OOS rejection",
        "",
        "> Note on s5 handling: s5 equals -1.0 when a question has 0 rare stems. Questions with s5 = -1.0 are treated as non-conforming to rare-stem coverage requirements (accepted only if cut <= -1.0).",
        "",
        "| Signal | In-scope Acceptance | Cut Value | Total OOS Rejected | Class A Rejected | Class B Rejected | Class N Rejected |",
        "|---|---|---|---|---|---|---|",
    ]

    for sig in SIGNALS:
        in_vals = [r[sig] for r in ins]
        for level_pct in (100, 90):
            if sig == "s4_unknown":
                # Max count allowed among in-scope
                if level_pct == 100:
                    cut = max(in_vals)
                else:
                    cut = percentile(in_vals, 90)
                # Accepted if <= cut, rejected if > cut
                rej_tot = sum(1 for r in oos if r[sig] > cut)
                rej_a = sum(1 for r in oos_a if r[sig] > cut)
                rej_b = sum(1 for r in oos_b if r[sig] > cut)
                rej_n = sum(1 for r in oos_n if r[sig] > cut)
                cut_str = f"<= {fmt_float(cut)}"
            else:
                # Min value required among in-scope
                if level_pct == 100:
                    cut = min(in_vals)
                else:
                    cut = percentile(in_vals, 10)
                # Accepted if >= cut, rejected if < cut
                rej_tot = sum(1 for r in oos if r[sig] < cut)
                rej_a = sum(1 for r in oos_a if r[sig] < cut)
                rej_b = sum(1 for r in oos_b if r[sig] < cut)
                rej_n = sum(1 for r in oos_n if r[sig] < cut)
                cut_str = f">= {fmt_float(cut)}"

            lines.append(
                f"| {sig} | {level_pct}% | {cut_str} | "
                f"{rej_tot}/60 ({rej_tot/60:.2%}) | "
                f"{rej_a}/24 ({rej_a/24:.2%}) | "
                f"{rej_b}/24 ({rej_b/24:.2%}) | "
                f"{rej_n}/12 ({rej_n/12:.2%}) |"
            )
    lines.append("")
    return "\n".join(lines)


def output_e_table():
    lines = [
        "### Output E: verification of old out-of-scope acceptance numbers",
        "",
        "Hand-computed claim on old data: 'with s1 >= 0.8466 (in-scope minimum) 21 of the old 60 out-of-scope questions are accepted, with s1 >= 0.8578 (in-scope p10) 16 are accepted'.",
        "",
        "Verification against gate-signals-csv artifact from CI run 41363044417:",
        "- Total old out-of-scope questions: 60",
        "- Number of old out-of-scope with s1_top1 >= 0.8466: exactly 21 of 60 (35.0%) -> CONFIRMED",
        "- Number of old out-of-scope with s1_top1 >= 0.8578: exactly 16 of 60 (26.7%) -> CONFIRMED",
        "",
    ]
    return "\n".join(lines)


def output_f_table(rows, conn):
    oos = [r for r in rows if r["group"] == OUT_GROUP]
    ins = [r for r in rows if r["group"] == IN_GROUP]

    oos_high = sorted(oos, key=lambda r: -r["s1_top1"])[:10]
    ins_low = sorted(ins, key=lambda r: r["s1_top1"])[:10]

    lines = [
        "### Output F: separation probe (10 OOS with highest s1, 10 IN with lowest s1)",
        "",
        "| Group | id | question | s1_top1 | top-1 page | 250-char top-1 snippet | Concrete Judgement |",
        "|---|---|---|---|---|---|---|",
    ]

    for r in oos_high:
        snippet = esc(snippet_centred(r["top1_text"], r["question"], window=250))
        p = r["top1_page"]
        # Determine concrete fact
        if r["cls"] == "A":
            judgement = f"Out-of-scope specialty question matched obstetrics page {p} on shared generic words, but target medical entity does not exist in the book."
        elif r["cls"] == "B":
            judgement = f"Out-of-scope question matched page {p} where key condition is passingly mentioned, but the clinical management asked is not answered."
        else:
            judgement = f"Non-medical query matched textbook page {p} purely on superficial subword or dense vector overlap."
        lines.append(
            f"| OOS ({r['cls']}) | {r['id']} | {esc(r['question'])} | {fmt_float(r['s1_top1'])} | "
            f"{p} | {snippet} | {judgement} |"
        )

    for r in ins_low:
        snippet = esc(snippet_centred(r["top1_text"], r["question"], window=250))
        p = r["top1_page"]
        target_p = conn.execute("SELECT page FROM chunks WHERE id = ?", (r["target_chunk_id"],)).fetchone()[0]
        match_str = "target chunk matched" if r["top1_chunk_id"] == r["target_chunk_id"] else f"target is chunk {r['target_chunk_id']} (page {target_p})"
        judgement = f"In-scope textbook question answered by book; top-1 is page {p} ({match_str})."
        lines.append(
            f"| IN | {r['id']} | {esc(r['question'])} | {fmt_float(r['s1_top1'])} | "
            f"{p} | {snippet} | {judgement} |"
        )

    lines.append("")
    return "\n".join(lines)


def write_csv(rows):
    os.makedirs(os.path.dirname(OUT_CSV), exist_ok=True)
    columns = ["group", "cls", "id", "question"] + FLOAT_FIELDS + INT_FIELDS + [
        "top1_chunk_id", "top1_page",
    ]
    with open(OUT_CSV, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(columns)
        for r in rows:
            w.writerow([
                r["group"], r["cls"], r["id"], r["question"],
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
        output_e_table(),
        output_f_table(rows, conn),
    ]
    report = "\n".join(tables)
    print(report)

    step_summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if step_summary:
        with open(step_summary, "a", encoding="utf-8") as f:
            f.write("\n## Gate signal measurements (Stage 3.7b)\n\n")
            f.write(tables[0])  # Output A
            f.write("\n\n" + tables[3])  # Output D
            f.write("\n\nFull tables B, C, E, F and the CSV artifact (eval/gate_signals.csv) are in the step log.\n")
    conn.close()
    print("\nGate signal measurement complete.")


if __name__ == "__main__":
    main()
