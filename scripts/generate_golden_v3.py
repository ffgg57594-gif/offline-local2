#!/usr/bin/env python3
"""Generate eval/golden_v3.draft.jsonl from the built books_knowledge.db.

Selects 60 in-scope chunks with fixed seed (7), stratified over the whole book
(one from every consecutive block of ~19 chunks), excluding chunks under 60
words and chunks that are mostly lists of numbers or figure captions.

For each selected chunk, writes a natural question that the chunk answers
directly (question generated from the chunk's first sentence / key terms).

Also includes 60 out-of-scope questions.

Fields per line:
  id, q, target_chunk_id, alt_chunk_ids, page, chunk_preview, in_scope, key_terms

Output: eval/golden_v3.draft.jsonl
"""
import json
import os
import re
import sqlite3
import sys

DB_PATH = os.path.join("app", "src", "main", "assets", "books_knowledge.db")
OUT_PATH = os.path.join("eval", "golden_v3.draft.jsonl")
SEED = 7
N_IN_SCOPE = 60
N_OUT_OF_SCOPE = 60
MIN_WORDS = 60


def is_figure_caption(text):
    """True if the chunk looks like a figure caption (starts with 'Fig' or 'Figure')."""
    return bool(re.match(r"^(Fig|Figure|TABLE|Table)\s*\d", text.strip()))


def is_number_list(text):
    """True if the chunk is mostly numbers/symbols (letter ratio < 0.6)."""
    letters = sum(1 for c in text if c.isalpha())
    non_space = sum(1 for c in text if not c.isspace())
    if non_space == 0:
        return True
    return letters / non_space < 0.6


def make_question(text, page):
    """Generate a natural question from a chunk's text.

    Uses the first meaningful sentence or key noun phrase to form a question.
    """
    text = text.strip()
    sentences = re.split(r"(?<=[.!?])\s+", text)
    first_sent = sentences[0] if sentences else text

    words = re.findall(r"\b[A-Z][a-z]+\b", first_sent)
    key_term = words[0] if words else "this"
    key_term = key_term.rstrip(".")

    lower = first_sent.lower()
    if any(w in lower for w in ["is", "are", "was", "were", "defined"]):
        q = f"What is {key_term}?"
    elif any(w in lower for w in ["cause", "causes", "due to", "result of"]):
        q = f"What causes {key_term}?"
    elif any(w in lower for w in ["treat", "treatment", "manage", "management", "therapy"]):
        q = f"How is {key_term} treated or managed?"
    elif any(w in lower for w in ["diagnos", "detect", "identify", "screen"]):
        q = f"How is {key_term} diagnosed?"
    elif any(w in lower for w in ["complicat", "risk", "risk of"]):
        q = f"What are the complications of {key_term}?"
    elif any(w in lower for w in ["classif", "type", "kind", "category"]):
        q = f"What are the types or classification of {key_term}?"
    elif any(w in lower for w in ["mechanism", "how", "process", "occurs", "happens"]):
        q = f"How does {key_term} occur?"
    else:
        q = f"What is {key_term}?"

    return q


OUT_OF_SCOPE = [
    "What is myocardial infarction and how is it diagnosed?",
    "What are the symptoms of psoriasis vulgaris?",
    "How is osteoporosis diagnosed in postmenopausal women?",
    "What are the types of cataract surgery in adults?",
    "What is the correct antibiotic dose for a 5-year-old child with pneumonia?",
    "How is dental caries managed in pediatric patients?",
    "What are the diagnostic criteria for schizophrenia in adults?",
    "What causes brain tumor and how is it treated?",
    "What are the complications of liver cirrhosis in end-stage disease?",
    "How is chronic kidney disease staged and when is dialysis needed?",
    "What are the symptoms of chronic gastritis and h pylori infection?",
    "How is adrenal gland disorder diagnosed and treated?",
    "What are the types of bronchial pneumonia in children?",
    "What causes rheumatoid arthritis and which joints are affected?",
    "How is type 1 diabetes treated in adults?",
    "What are the symptoms of Alzheimer's disease and how is it diagnosed?",
    "What is the appropriate treatment for hypertension?",
    "How are epileptic seizures treated in children?",
    "What are the causes and treatment of chronic kidney failure?",
    "What is the capital of France?",
    "How do you bake a chocolate cake?",
    "What is the best programming language for web development?",
    "Who won the World Cup in 2018?",
    "What is the recipe for pasta carbonara?",
    "What is photosynthesis and how does it work?",
    "What is quantum computing and what is it used for?",
    "How do airplanes fly?",
    "What is the boiling point of water?",
    "What is the plot of Romeo and Juliet?",
    "What is the speed of light?",
    "Who wrote Pride and Prejudice?",
    "What is the tallest mountain in the world?",
    "What is the chemical formula for water?",
    "How many planets are in the solar system?",
    "What is the largest ocean on Earth?",
    "Who painted the Mona Lisa?",
    "What is the currency of Japan?",
    "What is the capital of Australia?",
    "What is the chemical symbol for gold?",
    "What is the largest desert in the world?",
    "What is the smallest country in the world?",
    "What is the chemical formula for salt?",
    "What is the largest planet in the solar system?",
    "What is the longest river in the world?",
    "What is the chemical symbol for iron?",
    "What is the tallest building in the world?",
    "What is the chemical formula for carbon dioxide?",
    "What is the smallest continent in the world?",
    "What is the chemical symbol for silver?",
    "What is the largest country in the world?",
    "What is the chemical formula for methane?",
    "What is the tallest waterfall in the world?",
    "What is the chemical symbol for copper?",
    "What is the largest lake in the world?",
    "What is the chemical formula for ammonia?",
    "What is the tallest mountain in Africa?",
    "What is the chemical symbol for mercury?",
    "What is the longest wall in the world?",
    "What is the chemical formula for glucose?",
    "What is the tallest tower in the world?",
    "What is the chemical symbol for lead?",
    "What is the longest bridge in the world?",
    "What is the chemical formula for alcohol?",
]


def main():
    if not os.path.exists(DB_PATH):
        print(f"ERROR: {DB_PATH} not found. Run build_knowledge_db.py first.", file=sys.stderr)
        sys.exit(1)

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    # Get all chunks ordered by id, with word_count >= MIN_WORDS, not figure captions, not number lists.
    rows = cur.execute(
        "SELECT c.id, b.name, c.page, c.section, c.text, c.word_count "
        "FROM chunks c JOIN books b ON b.id = c.book_id "
        "WHERE c.word_count >= ? ORDER BY c.id",
        (MIN_WORDS,),
    ).fetchall()

    # Filter out figure captions and number lists.
    eligible = []
    for cid, bname, page, section, text, wc in rows:
        if is_figure_caption(text):
            continue
        if is_number_list(text):
            continue
        eligible.append((cid, bname, page, section, text, wc))

    print(f"Eligible chunks (>= {MIN_WORDS} words, not caption/list): {len(eligible)}")

    if len(eligible) < N_IN_SCOPE:
        print(f"ERROR: Only {len(eligible)} eligible chunks, need {N_IN_SCOPE}.", file=sys.stderr)
        sys.exit(1)

    # Stratified selection: one chunk from every consecutive block of ~19 chunks.
    block_size = len(eligible) // N_IN_SCOPE
    import random
    rng = random.Random(SEED)
    selected = []
    for i in range(N_IN_SCOPE):
        start = i * block_size
        end = min((i + 1) * block_size, len(eligible))
        block = eligible[start:end]
        chosen = rng.choice(block)
        selected.append(chosen)

    # Sort by chunk id for deterministic output.
    selected.sort(key=lambda x: x[0])

    # Build golden v3 lines.
    lines = []
    for idx, (cid, bname, page, section, text, wc) in enumerate(selected, start=1):
        q = make_question(text, page)
        preview = text[:200]
        line = json.dumps({
            "id": idx,
            "q": q,
            "target_chunk_id": cid,
            "alt_chunk_ids": [],
            "page": page,
            "chunk_preview": preview,
            "in_scope": True,
        }, ensure_ascii=False)
        lines.append(line)

    # Add out-of-scope questions.
    oos_questions = OUT_OF_SCOPE[:N_OUT_OF_SCOPE]
    if len(oos_questions) < N_OUT_OF_SCOPE:
        print(f"WARNING: Only {len(oos_questions)} out-of-scope questions, need {N_OUT_OF_SCOPE}.", file=sys.stderr)

    for i, q in enumerate(oos_questions):
        line = json.dumps({
            "id": N_IN_SCOPE + 1 + i,
            "q": q,
            "target_chunk_id": None,
            "alt_chunk_ids": [],
            "page": None,
            "chunk_preview": "",
            "in_scope": False,
            "key_terms": [],
        }, ensure_ascii=False)
        lines.append(line)

    # Write the file.
    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        for line in lines:
            f.write(line + "\n")

    print(f"Wrote {OUT_PATH} with {len(lines)} questions ({N_IN_SCOPE} in-scope, {len(oos_questions)} out-of-scope)")

    # Print the in-scope listing for review.
    print("\n=== In-scope questions (golden v3) ===")
    for line in lines[:N_IN_SCOPE]:
        q = json.loads(line)
        print(f"{q['id']} | {q['q']} | target_chunk={q['target_chunk_id']} | page={q['page']} | preview={q['chunk_preview'][:80]}...")

    conn.close()


if __name__ == "__main__":
    main()
