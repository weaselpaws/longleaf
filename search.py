"""
Longleaf - flow search (no GUI).

Lets a tech type what they are looking at ("wifi keeps dropping") and land on
the right step instead of walking from the root. Matches the words in a step's
tags, question, note, answers, the fixes its answers end at, and the KB
articles it offers. Every word must match (prefix or simple plural); if
nothing matches them all, steps matching some of the words are offered
instead. Only steps reachable from the start are returned, best first,
nearer the start winning ties.

Plain word matching, on purpose: it is predictable for a flow author tuning
tags, needs nothing installed, and runs instantly on flows of any realistic
size. Typo tolerance would be the next step if real searches need it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from engine import Tree

W_TAG, W_QUESTION, W_NOTE, W_ANSWER, W_FIX, W_ARTICLE = 10.0, 4.0, 2.0, 2.0, 1.5, 1.5
PHRASE_BONUS = 6.0       # the whole query appears in one tag
PREFIX_FACTOR = 0.8      # a word that merely starts with the query word counts a little less than an exact match
MAX_RESULTS = 6

_WORD = re.compile(r"[a-z0-9]+")


def tokens(text: str) -> list[str]:
    return _WORD.findall((text or "").lower())


def _stem(word: str) -> str:
    return word[:-1] if len(word) > 3 and word.endswith("s") and not word.endswith("ss") else word


def _match(query_word: str, word: str) -> float:
    """1.0 for the same word (or its plural), PREFIX_FACTOR for a longer word starting with it, else 0."""
    if _stem(word) == _stem(query_word):
        return 1.0
    if len(query_word) >= 2 and word.startswith(query_word):
        return PREFIX_FACTOR
    return 0.0


@dataclass(frozen=True)
class SearchHit:
    step_id: str
    score: float
    why: str        # short, for display: which field matched best ("Tag: wifi", "Question", "Answer: …")


def _fields(tree: Tree, sid: str) -> list[tuple[str, float, str, list[str]]]:
    """(label, weight, display text, words) for everything searchable on a step."""
    step = tree.steps[sid]
    out = [(f"Tag: {t}", W_TAG, t, tokens(t)) for t in step.tags]
    out.append(("Question", W_QUESTION, step.question, tokens(step.question)))
    if step.note:
        out.append(("Note", W_NOTE, step.note, tokens(step.note)))
    for o in step.options:
        out.append((f"Answer: {o.label}", W_ANSWER, o.label, tokens(o.label)))
        if o.is_terminal:
            ending = tree.ending_for(o)
            if ending and ending.text:
                out.append(("Fix", W_FIX, ending.text, tokens(ending.text)))
    for aid in step.articles:
        art = tree.articles.get(aid)
        if art:
            out.append((f"Article: {art.title}", W_ARTICLE, art.title, tokens(art.title)))
    return out


def _depths(tree: Tree) -> dict[str, int]:
    depth, todo = {}, [(tree.root_id, 0)]
    while todo:
        sid, d = todo.pop(0)
        if sid in depth or sid not in tree.steps:
            continue
        depth[sid] = d
        todo.extend((o.next_id, d + 1) for o in tree.steps[sid].options if o.next_id)
    return depth


def search(tree: Tree, query: str, limit: int = MAX_RESULTS) -> list[SearchHit]:
    words = tokens(query)
    if not words:
        return []
    depth = _depths(tree)
    order = {sid: i for i, sid in enumerate(tree.steps)}
    scored = []     # (words matched, score, depth, order, hit)
    for sid in depth:
        fields = _fields(tree, sid)
        total, matched, best_why, best = 0.0, 0, "", 0.0
        for q in words:
            top, top_label = 0.0, ""
            for label, weight, _text, ws in fields:
                m = max((_match(q, w) for w in ws), default=0.0)
                if m * weight > top:
                    top, top_label = m * weight, label
            if top:
                matched += 1
                total += top
                if top > best:
                    best, best_why = top, top_label
        if len(words) > 1:    # the whole phrase sitting in one tag is a strong signal
            phrase = " ".join(words)
            for t in tree.steps[sid].tags:
                if phrase in " ".join(tokens(t)):
                    total += PHRASE_BONUS
                    best_why = best_why if best_why.startswith("Tag") else f"Tag: {t}"
                    break
        if matched:
            scored.append((matched, total, depth[sid], order[sid], SearchHit(sid, round(total, 2), best_why)))
    everything = [s for s in scored if s[0] == len(words)]
    pool = everything or scored          # nothing matches every word: fall back to partial matches
    pool.sort(key=lambda s: (-s[0], -s[1], s[2], s[3]))
    return [s[4] for s in pool[:limit]]
