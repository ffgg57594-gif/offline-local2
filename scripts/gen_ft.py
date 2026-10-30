#!/usr/bin/env python3
"""Phase 3: Generate fine-tuning data (template-based, 0 API cost).
Output: ft_data.jsonl  ({"instruction","input","output"})
- 70% in-scope: colloquial question + retrieved paragraphs -> colloquial reply with verbatim English quotes + book/page
- 30% refusal: out-of-scope -> "مش موجود في كتبي"
"""
import sqlite3, json, random, re

random.seed(42)
conn = sqlite3.connect("ingested.db")
paras = conn.execute("""SELECT p.id,p.text,p.page,b.title,c.title FROM paragraphs p JOIN books b ON b.id=p.book_id JOIN chapters c ON c.id=p.chapter_id""").fetchall()

ARABIC_Q_TEMPLATES = [
    "اشرحلي {topic}",
    "ما هو {topic}؟",
    " explain {topic}",
    "tell me about {topic}",
    "ما هي أعراض {topic}؟",
    "كيف نعالج {topic}؟",
]
CONNECTORS = ["حسب كتاب", "يقول", "موجود في", "من كتاب", "كما ورد في"]

def make_quote(para_text):
    # take first sentence-ish chunk (<=120 chars) verbatim
    sents = re.split(r"(?<=[.!?])\s+", para_text.strip())
    q = sents[0] if sents else para_text[:120]
    if len(q) > 140:
        q = q[:140].rsplit(" ",1)[0] + "."
    return q

examples = []
# in-scope (70%)
n_in = 700
for _ in range(n_in):
    pid, text, page, book, chap = random.choice(paras)
    topic = book.strip()[:60]
    q = random.choice(ARABIC_Q_TEMPLATES).format(topic=topic)
    quote = make_quote(text)
    connector = random.choice(CONNECTORS)
    out = f"{connector} {book} ص.{page}: \"{quote}\""
    # add a second connector sometimes
    if random.random() < 0.4:
        q2 = make_quote(text)
        if q2 != quote:
            out += f" Also: \"{q2[:80]}\" ({book} ص.{page})"
    inp = f"Retrieved paragraphs:\n[{book} ص.{page}] {text[:600]}"
    examples.append({"instruction": q, "input": inp, "output": out})

# refusal (30%)
refusal_qs = [
    "ما هو علاج السكري؟","dose of insulin for DKA","pediatric vaccine schedule",
    "treatment of hypertension","stroke thrombolysis","malaria prophylaxis",
    "HIV therapy","cancer chemotherapy","osteoporosis treatment","glaucoma drops",
    "psoriasis treatment","asthma inhaler","appendicitis surgery","fracture management",
    "renal dialysis","anemia iron","migraine triptans","GERD treatment",
]
n_ref = 300
for _ in range(n_ref):
    q = random.choice(refusal_qs) + " " + random.choice(["؟","","please"])
    examples.append({"instruction": q, "input": "Retrieved paragraphs:\n(none relevant)", "output": "مش موجود في كتبي"})

random.shuffle(examples)
with open("ft_data.jsonl","w",encoding="utf-8") as f:
    for e in examples:
        f.write(json.dumps(e, ensure_ascii=False)+"\n")
print(f"Generated {len(examples)} examples -> ft_data.jsonl")

# sample 30 random for review
sample = random.sample(examples, 30)
with open("ft_sample_30.jsonl","w",encoding="utf-8") as f:
    for e in sample:
        f.write(json.dumps(e, ensure_ascii=False)+"\n")
print("Sample 30 -> ft_sample_30.jsonl")
print("Refusal count:", sum(1 for e in examples if e["output"]=="مش موجود في كتبي"))
