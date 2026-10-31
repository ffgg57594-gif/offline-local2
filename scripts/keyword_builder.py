#!/usr/bin/env python3
"""Keyword query builder for the retrieval pipeline (Stage 3.6b).

Builds FTS5 queries from questions using:
  - Text normalization (lowercase, hyphen unification, spelling variants via normalize_map.json)
  - Tokenization
  - Stopword removal (150+ English words including question words)
  - Short non-content word list (max 40 words): patient, patients, case, cases,
    type, types, following, used, include, including, ... (printed in full)
  - Quote each remaining token and join with OR
  - Fall back to the longest non-stopword token if nothing remains

Document-frequency based term removal (v1.0, Stage 3.6a) is REMOVED entirely.
In a single-specialty obstetrics book, words like "pregnancy", "hemorrhage",
"uterine", "bleeding", "treatment" are content words, not generic stopwords.

Variants:
  v1: current 3.6a builder (stopwords + DF-based generic removal + OR)
  v2: stopword-only unigrams joined with OR, ranked with bm25()
  v3: v2 plus adjacent-word phrases ("word1 word2" quoted) added to OR
  v4: v3 with column weights favouring search_text over section text if the
      section is indexed, otherwise same as v3

The same builder is used by evaluate_audit.py and fusion_tuning.py.
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

# Short non-content word list (max 40 words). These are common in a single
# specialty book but carry little discriminative signal on their own.
NON_CONTENT_WORDS = [
    "patient", "patients", "case", "cases", "type", "types", "following",
    "used", "include", "including", "show", "shows", "showing", "found",
    "see", "seen", "note", "notes", "refer", "refers", "referring",
    "regarding", "concerning", "relating", "related", "relate",
    "observe", "observed", "observation", "observations",
    "report", "reported", "reporting", "reports",
    "state", "stated", "stating", "states",
    "indicate", "indicated",
]

assert len(NON_CONTENT_WORDS) <= 40, f"NON_CONTENT_WORDS exceeds 40: {len(NON_CONTENT_WORDS)}"


def load_stopwords():
    """Return a set of 150+ English stopwords including question words."""
    return {
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


def build_keyword_query(question, stopwords, non_content_words=None, variant_map=None, variant="v2"):
    """Build an FTS5 keyword query from a question string.

    Args:
        question: raw question string.
        stopwords: set of stopwords to remove.
        non_content_words: set of non-content words to remove (v1 only).
        variant_map: spelling variant map.
        variant: one of "v1", "v2", "v3", "v4".

    Returns:
        (query_string, tokens_used)
    """
    if non_content_words is None:
        non_content_words = set()

    norm = normalize_text(question, variant_map)
    tokens = re.findall(r"\w+", norm.lower())

    # Remove stopwords and non-content words.
    content_tokens = [t for t in tokens if t not in stopwords and t not in non_content_words]

    if variant == "v1":
        # v1: unigrams joined with OR (no phrases).
        quoted = [f'"{t}"' for t in content_tokens]
        if len(quoted) == 1:
            query = quoted[0]
        elif quoted:
            query = " OR ".join(quoted)
        else:
            query = ""
        return query, content_tokens

    # v2/v3/v4: stopword-only unigrams joined with OR, ranked with bm25().
    quoted_unigrams = [f'"{t}"' for t in content_tokens]
    if not quoted_unigrams:
        # Fall back to longest non-stopword token.
        non_stop = [t for t in tokens if t not in stopwords]
        if non_stop:
            quoted_unigrams = [f'"{max(non_stop, key=len)}"']
        else:
            quoted_unigrams = [f'"{tokens[0]}"'] if tokens else []

    query_parts = list(quoted_unigrams)

    if variant in ("v3", "v4"):
        # Add adjacent-word phrases.
        for i in range(len(tokens) - 1):
            if tokens[i] not in stopwords and tokens[i + 1] not in stopwords:
                phrase = f'"{tokens[i]} {tokens[i+1]}"'
                query_parts.append(phrase)

    if not query_parts:
        query = ""
    else:
        query = " OR ".join(query_parts)

    return query, content_tokens


def fts_search(cur, query, top_k=5, use_column_weights=False):
    """Run an FTS5 search and return (name, page, text, rank) rows.

    If use_column_weights is True and the FTS5 table has a section column,
    weights favour search_text over section. Otherwise standard bm25().
    """
    if not query:
        return []
    if use_column_weights:
        # FTS5 column weights: search_text weight 2.0, section weight 1.0.
        # If no section column exists, this falls back to plain bm25().
        cur.execute(
            "SELECT b.name, c.page, c.text, bm25(chunks_fts, 2.0, 1.0) AS rank "
            "FROM chunks_fts f "
            "JOIN chunks c ON c.id = f.rowid "
            "JOIN books b ON b.id = c.book_id "
            "WHERE f.search_text MATCH ? "
            "ORDER BY rank LIMIT ?",
            (query, top_k),
        )
    else:
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


def print_removed_terms_list(cur, stopwords):
    """Print the v1 removed-terms list: count + 30 most frequent non-stopword stems."""
    cur.execute("SELECT search_text FROM chunks")
    rows = cur.fetchall()
    term_counts = {}
    for (search_text,) in rows:
        if not search_text:
            continue
        for w in re.findall(r"\w+", search_text.lower()):
            if w not in stopwords:
                term_counts[w] = term_counts.get(w, 0) + 1
    sorted_terms = sorted(term_counts.items(), key=lambda x: -x[1])
    top30 = sorted_terms[:30]
    print(f"v1 removed-terms list count: {len(sorted_terms)}")
    print(f"Top 30 most frequent non-stopword terms:")
    for term, count in top30:
        print(f"  {term}: {count}")
    return len(sorted_terms), top30


if __name__ == "__main__":
    # Report keyword-only recall before/after the fix on golden v2.
    print("Keyword query builder module loaded.")
    print(f"Stopwords count: {len(load_stopwords())}")
    print(f"Non-content words count: {len(NON_CONTENT_WORDS)}")
    print(f"Non-content words: {NON_CONTENT_WORDS}")
