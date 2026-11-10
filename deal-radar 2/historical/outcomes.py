"""Completion language in a filing that is later than the announcement.

Prospective phrases in the announcement itself are not a close.
"""
import re

from historical.text import plain_text

CLOSED = (
    "merger was consummated",
    "merger has been consummated",
    "consummated the merger",
    "merger was completed",
    "completed the merger",
    "merger became effective",
    "the merger closed",
    "merged with and into the company",
)
TERMINATED = (
    "merger agreement was terminated",
    "merger agreement has been terminated",
    "terminated the merger agreement",
    "agreement and plan of merger was terminated",
    "agreement and plan of merger has been terminated",
)
PROSPECTIVE = ("will ", "upon the", "subject to", "expected to")


def _sentence_around(text, phrase):
    low = text.lower()
    at = low.find(phrase)
    if at < 0:
        return ""
    start = max(0, text.rfind(".", 0, at) + 1)
    end = text.find(".", at)
    if end < 0:
        end = min(len(text), at + 240)
    return " ".join(text[start:end + 1].split())


def _prospective(sentence):
    low = sentence.lower()
    return any(phrase in low for phrase in PROSPECTIVE)


def outcome_from_text(raw):
    """closed, terminated, or unresolved, plus the sentence that decided it."""
    text = plain_text(raw)
    for phrase in TERMINATED:
        sentence = _sentence_around(text, phrase)
        if sentence and not _prospective(sentence):
            return "terminated", sentence[:400]
    for phrase in CLOSED:
        sentence = _sentence_around(text, phrase)
        if sentence and not _prospective(sentence):
            return "closed", sentence[:400]
    return "unresolved", None
