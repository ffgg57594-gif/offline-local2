#!/usr/bin/env python3
"""Keyword query builder for the retrieval pipeline.

Builds FTS5 queries from questions using:
  - Text normalization (lowercase, hyphen unification, spelling variants)
  - Tokenization
  - Stopword removal (150+ English words including question words)
  - Generic-term removal (stems with document frequency > 3% of chunks)
  - Quote each remaining token and join with OR
  - Fall back to the longest non-stopword token if nothing remains

The same builder is used by evaluate_dense_vs_keyword.py, fusion_tuning.py,
and failure_review.py.
"""
import json
import os
import re
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from text_normalize import normalize_text, load_variant_map  # noqa: E402

DB_PATH = os.path.join("app", "src", "main", "assets", "books_knowledge.db")
NORMALIZE_MAP_PATH = os.path.join("app", "src", "main", "assets", "normalize_map.json")

# English stopword list (150+ words including question words).
STOPWORDS = {
    "the", "a", "an", "and", "or", "but", "in", "on", "at", "to", "for", "of",
    "with", "by", "from", "as", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "will", "would", "could", "should",
    "may", "might", "can", "this", "that", "these", "those", "i", "you", "he",
    "she", "it", "we", "they", "what", "how", "which", "when", "where", "why",
    "who", "whom", "whose", "will", "would", "shall", "should", "can", "could",
    "may", "might", "must", "need", "dare", "ought", "used", "use", "using",
    "about", "above", "after", "again", "against", "all", "almost", "alone",
    "along", "already", "also", "although", "always", "among", "an", "another",
    "any", "anybody", "anyone", "anything", "anywhere", "around", "at", "ate",
    "away", "back", "became", "because", "become", "becomes", "becoming",
    "before", "beforehand", "behind", "below", "beneath", "beside", "besides",
    "between", "beyond", "bill", "both", "bottom", "but", "by", "call", "can",
    "cannot", "cant", "co", "con", "could", "couldnt", "cry", "de", "describe",
    "detail", "do", "done", "down", "due", "during", "each", "eg", "eight",
    "either", "eleven", "else", "elsewhere", "empty", "enough", "even", "ever",
    "every", "everybody", "everyone", "everything", "everywhere", "except",
    "few", "fifteen", "fify", "fill", "find", "fire", "first", "five", "for",
    "former", "formerly", "forty", "found", "four", "from", "front", "full",
    "further", "get", "give", "go", "had", "has", "hasnt", "have", "he", "hence",
    "her", "here", "hereafter", "hereby", "herein", "hereupon", "hers", "herself",
    "him", "himself", "his", "how", "however", "hundred", "i", "ie", "if", "in",
    "inc", "indeed", "interest", "into", "is", "it", "its", "itself", "keep",
    "last", "latter", "latterly", "least", "less", "just", "kg", "km", "make",
    "many", "may", "me", "meanwhile", "might", "mill", "mine", "more", "moreover",
    "most", "mostly", "move", "much", "must", "my", "myself", "name", "namely",
    "nay", "near", "nearly", "necessary", "needs", "never", "nevertheless", "next",
    "nine", "no", "nobody", "none", "noone", "nor", "not", "nothing", "now",
    "nowhere", "of", "off", "often", "on", "once", "one", "only", "onto", "or",
    "other", "others", "otherwise", "our", "ours", "ourselves", "out", "over",
    "own", "part", "per", "perhaps", "please", "put", "rather", "re", "same",
    "see", "seem", "seemed", "seeming", "seems", "serious", "several", "she",
    "should", "show", "side", "since", "sincere", "six", "sixty", "so", "some",
    "somebody", "someone", "something", "sometime", "sometimes", "somewhere",
    "still", "such", "system", "take", "ten", "than", "that", "the", "their",
    "them", "themselves", "then", "thence", "there", "thereafter", "thereby",
    "therefore", "therein", "thereupon", "these", "they", "thick", "thin",
    "third", "this", "those", "though", "three", "through", "throughout",
    "thru", "thus", "to", "together", "too", "top", "toward", "towards", "twelve",
    "twenty", "two", "un", "under", "until", "up", "upon", "us", "very", "via",
    "was", "we", "well", "were", "what", "whatever", "when", "whence", "whenever",
    "where", "whereafter", "whereas", "whereby", "wherein", "whereupon", "wherever",
    "whether", "which", "while", "whither", "who", "whoever", "whole", "whom",
    "whose", "why", "will", "with", "within", "without", "would", "yet", "you",
    "your", "yours", "yourself", "yourselves",
}


def load_stopwords():
    return set(STOPWORDS)


def compute_generic_terms(db_path, threshold_frac=0.03):
    """Compute generic terms: stems whose document frequency > threshold_frac of chunks.

    Returns (generic_terms_set, doc_count).
    """
    if not os.path.exists(db_path):
        print(f"ERROR: {db_path} not found.", file=sys.stderr)
        sys.exit(1)

    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    rows = cur.execute("SELECT search_text FROM chunks").fetchall()
    conn.close()

    total_chunks = len(rows)
    term_doc_counts = {}

    for (search_text,) in rows:
        if not search_text:
            continue
        words = set(re.findall(r"\w+", search_text.lower()))
        for w in words:
            term_doc_counts[w] = term_doc_counts.get(w, 0) + 1

    generic = set()
    threshold_count = total_chunks * threshold_frac
    for term, count in term_doc_counts.items():
        if count > threshold_count:
            generic.add(term)

    print(f"Total chunks: {total_chunks}")
    print(f"Generic threshold: > {threshold_count:.1f} documents ({threshold_frac*100:.0f}%)")
    print(f"Generic terms removed ({len(generic)}): {sorted(generic)}")
    return generic, total_chunks


def build_keyword_query(question, stopwords, generic_terms, variant_map=None):
    """Build an FTS5 keyword query from a question string.

    Returns (query_string, tokens_used).
    """
    norm = normalize_text(question, variant_map)
    tokens = re.findall(r"\w+", norm.lower())

    # Remove stopwords and generic terms.
    content_tokens = [t for t in tokens if t not in stopwords and t not in generic_terms]

    if not content_tokens:
        # Fall back to longest non-stopword token.
        non_stop = [t for t in tokens if t not in stopwords]
        if non_stop:
            content_tokens = [max(non_stop, key=len)]
        else:
            content_tokens = [tokens[0]] if tokens else []

    # Quote each token and join with OR.
    quoted = [f'"{t}"' for t in content_tokens]
    if len(quoted) == 1:
        query = quoted[0]
    elif quoted:
        query = " OR ".join(quoted)
    else:
        query = ""

    return query, content_tokens


def fts_search(cur, query, top_k=5):
    """Run an FTS5 search and return (name, page, text, rank) rows."""
    if not query:
        return []
    cur.execute(
        "SELECT b.name, c.page, c.text, bm25(chunks_fts) AS rank "
        "FROM chunks_fts f "
        "JOIN chunks c ON c.id = f.rowid "
        "JOIN books b ON b.id = c.book_id "
        "WHERE f.search_text MATCH ? "
        "ORDER BY rank LIMIT ?",
        (query, top_k),
    )
    return cur.fetchall()


def answer_terms_match(chunk_text, answer_terms, variant_map=None):
    """Check if a chunk text matches any answer_terms group.

    answer_terms is a list of groups; each group is a list of terms.
    A hit = chunk contains ALL terms of at least one group.
    Matching uses the same FTS5 tokenizer normalization (via normalize_text).
    """
    if not answer_terms:
        return False
    norm_text = normalize_text(chunk_text, variant_map)
    for group in answer_terms:
        if all(term.lower() in norm_text for term in group):
            return True
    return False


def answer_terms_match_fts(cur, chunk_id, answer_terms, variant_map=None):
    """Check answer_terms match using FTS5 MATCH restricted to chunk id.

    Each term in a group must match the chunk via FTS5.
    A hit = any group has all its terms match the chunk.
    """
    if not answer_terms:
        return False
    norm_text = None
    for group in answer_terms:
        all_match = True
        for term in group:
            # Build a phrase query for the term restricted to this chunk.
            norm_term = normalize_text(term, variant_map)
            quoted = f'"{norm_term}"'
            cur.execute(
                "SELECT COUNT(*) FROM chunks_fts f "
                "JOIN chunks c ON c.id = f.rowid "
                "WHERE c.id = ? AND f.search_text MATCH ?",
                (chunk_id, quoted),
            )
            count = cur.fetchone()[0]
            if count == 0:
                all_match = False
                break
        if all_match:
            return True
    return False


if __name__ == "__main__":
    # Report keyword-only recall before/after the fix on golden v2.
    import importlib

    # This section is invoked by CI to report keyword recall.
    print("Keyword query builder module loaded.")
    print(f"Stopwords count: {len(STOPWORDS)}")
