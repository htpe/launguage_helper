"""
Translation logic using Google Translate's public JSON endpoint.

No API key required. Uses urllib.request (stdlib) so there are no
third-party binary dependency issues.
"""

import json
import re as _re
import urllib.parse
import urllib.request

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    )
}

_GOOGLE_URL = (
    "https://translate.googleapis.com/translate_a/single"
    "?client=gtx&sl={src}&tl={tgt}&dt=t&q={q}"
)

# dt=ex + dt=md for verb/dictionary definitions — used as fallback
_GOOGLE_EXAMPLES_URL = (
    "https://translate.googleapis.com/translate_a/single"
    "?client=gtx&sl={src}&tl=en&dt=t&dt=ex&dt=md&q={q}"
)

# Tatoeba sentence corpus — free, no key, reliable, language-specific
# lang param uses ISO 639-3 codes (deu, eng, fra, zho, jpn, …)
_TATOEBA_URL = "https://tatoeba.org/api_v0/search?query={q}&from={lang}&orphans=no&unapproved=no&native=yes&limit=20"

# Map common ISO 639-1 / Google codes → Tatoeba ISO 639-3
_LANG_TO_TATOEBA: dict[str, str] = {
    "de": "deu", "en": "eng", "fr": "fra", "es": "spa", "it": "ita",
    "pt": "por", "nl": "nld", "ru": "rus", "pl": "pol", "uk": "ukr",
    "ar": "ara", "tr": "tur", "sv": "swe", "no": "nor", "da": "dan",
    "fi": "fin", "hu": "hun", "cs": "ces", "ro": "ron", "el": "ell",
    "he": "heb", "ko": "kor", "ja": "jpn",
    "zh": "cmn", "zh-cn": "cmn", "zh-tw": "cmn",
    "auto": "eng",  # fallback when auto-detect is used
}

_TERMINAL_PUNCT = set(".!?。！？…")


def _word_set(s: str) -> set[str]:
    """Return a lowercase set of word tokens from *s*."""
    return set(_re.sub(r"[^\w\s]", " ", s.lower()).split())


def _jaccard(a: str, b: str) -> float:
    """Jaccard word-overlap similarity in [0, 1]. 1 = identical word sets."""
    sa, sb = _word_set(a), _word_set(b)
    if not sa and not sb:
        return 1.0
    intersection = len(sa & sb)
    union = len(sa | sb)
    return intersection / union if union else 0.0


def _diverse_pick(candidates: list[str], max_count: int, threshold: float = 0.3) -> list[str]:
    """
    Pick up to *max_count* sentences from an already-scored (best-first)
    *candidates* list, skipping any candidate whose Jaccard word-overlap with
    a previously selected sentence exceeds *threshold* (default 50 %).
    """
    selected: list[str] = []
    for candidate in candidates:
        if all(_jaccard(candidate, s) <= threshold for s in selected):
            selected.append(candidate)
            if len(selected) >= max_count:
                break
    return selected


def _strip_html(text: str) -> str:
    """Remove simple HTML tags like <b>...</b>."""
    return _re.sub(r"<[^>]+>", "", text).strip()


def _fetch_json(url: str) -> object:
    req = urllib.request.Request(url, headers=_HEADERS)
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _google_translate(text: str, source: str, target: str) -> str:
    url = _GOOGLE_URL.format(
        src=source,
        tgt=target,
        q=urllib.parse.quote(text),
    )
    data = _fetch_json(url)
    translated = "".join(part[0] for part in data[0] if part[0])
    return translated


def _score_sentence(s: str) -> float:
    """
    Return a quality score for an example sentence (higher = better).
    Favours: complete sentences, natural length (50-180 chars), proper casing.
    Penalises: fragments, very short/long text, trailing ellipsis only.
    """
    n = len(s)
    score = 0.0

    # Length sweet-spot
    if 50 <= n <= 180:
        score += 4.0
    elif 30 <= n < 50 or 180 < n <= 240:
        score += 2.0
    elif n < 30:
        score -= 3.0
    else:                           # > 240
        score -= 2.0

    # Ends with terminal punctuation
    if s and s[-1] in _TERMINAL_PUNCT:
        score += 3.0

    # Starts with an uppercase letter (Latin scripts) or any CJK/non-ASCII char
    if s and (s[0].isupper() or ord(s[0]) > 127):
        score += 2.0

    # Has enough words (guards against 2-word fragments)
    word_count = len(s.split())
    if word_count >= 6:
        score += 2.0
    elif word_count < 4:
        score -= 2.0

    # Penalise if it looks like an enumeration or heading (no verb-like content)
    if s.endswith("…") or s.endswith("..."):
        score -= 2.0

    return score


def translate(text: str, source: str, targets: list[str]) -> dict[str, str]:
    """
    Translate *text* from *source* into each language in *targets*.
    Returns a dict mapping language code → translated string.
    """
    results: dict[str, str] = {}
    for lang in targets:
        try:
            results[lang] = _google_translate(text, source, lang)
        except Exception as exc:  # noqa: BLE001
            results[lang] = f"[Error: {exc}]"
    return results


def _examples_from_tatoeba(word: str, tatoeba_lang: str, max_count: int) -> list[str]:
    """
    Fetch example sentences from Tatoeba (tatoeba.org/api_v0).
    Returns sentences in the word's own language containing the word.
    """
    try:
        url = _TATOEBA_URL.format(
            q=urllib.parse.quote(word),
            lang=tatoeba_lang,
        )
        data = _fetch_json(url)
        results = data.get("results") or []
        candidates: list[str] = []
        for r in results:
            text = (r.get("text") or "").strip()
            if text:
                candidates.append(text)
        scored = sorted(candidates, key=_score_sentence, reverse=True)
        return _diverse_pick(scored, max_count)
    except Exception:
        return []


def _examples_from_google(word: str, src_lang: str, max_count: int) -> list[str]:
    """
    Fallback: pull example sentences from Google Translate's dt=ex/dt=md blocks.
    Works best for German/English verbs that have dictionary entries.
    """
    try:
        url = _GOOGLE_EXAMPLES_URL.format(
            src=src_lang,
            q=urllib.parse.quote(word),
        )
        data = _fetch_json(url)
        candidates: list[str] = []

        # data[12] — dt=ex dictionary block
        # Structure: [ [pos_str, [ [definition, id, example?], ... ], base_word, n], ... ]
        try:
            for pos_block in (data[12] or []):
                definitions = pos_block[1] if (pos_block and len(pos_block) > 1) else []
                for defn in (definitions or []):
                    if defn and len(defn) > 2 and isinstance(defn[2], str) and defn[2].strip():
                        candidates.append(defn[2].strip())
        except (IndexError, TypeError):
            pass

        # data[11] — dt=md meanings block (English words mainly)
        try:
            for pos_block in (data[11] or []):
                definitions = pos_block[1] if (pos_block and len(pos_block) > 1) else []
                for defn in (definitions or []):
                    if defn and len(defn) > 3 and isinstance(defn[3], str) and defn[3].strip():
                        s = defn[3].strip()
                        if s not in candidates:
                            candidates.append(s)
        except (IndexError, TypeError):
            pass

        scored = sorted(candidates, key=_score_sentence, reverse=True)
        return _diverse_pick(scored, max_count)
    except Exception:
        return []


def get_examples(word: str, source: str, max_count: int = 3) -> list[str]:
    """
    Return up to *max_count* example sentences for a single word.

    Strategy:
      1. Primary: Tatoeba sentence corpus (real sentences, language-specific,
         works for nouns/adjectives/verbs in any supported language).
      2. Fallback: Google Translate dt=ex/dt=md (works for verb dictionary
         entries in German/English when Tatoeba returns nothing).
    """
    word = word.strip()
    if not word:
        return []

    # Resolve Tatoeba language code; use "eng" for "auto" as last resort
    src_lower = source.lower().split("-")[0] if source else "auto"
    tatoeba_lang = _LANG_TO_TATOEBA.get(source.lower(),
                   _LANG_TO_TATOEBA.get(src_lower, "eng"))

    # 1. Try Tatoeba first
    examples = _examples_from_tatoeba(word, tatoeba_lang, max_count)
    if examples:
        return examples

    # 2. Fall back to Google dt=ex / dt=md
    google_src = src_lower if src_lower != "auto" else "auto"
    return _examples_from_google(word, google_src, max_count)

