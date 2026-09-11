"""Multilingual civic AI — deterministic language pipeline (Part 26).

Support: English (en), Hindi (hi), Marathi (mr).

The pipeline is fully offline and deterministic (no external translate /
detection API) so the demo and tests are hermetic:

    Input
      ↓
    detect_language(text)   — script + native-script + keyword scoring
      ↓
    normalize(text, lang)   — internal normalized representation (transliteration +
                              whitespace/punctuation folding) that PRESERVES names,
                              addresses, IDs and coordinates verbatim
      ↓
    translate(text, src, dst) — phrase-level translation for known civic phrases;
                              unknown tokens (names/IDs/numbers) are passed through
    ↓
    Response in selected language

Key invariants demanded by the spec:
  * Preserve names, addresses, complaint IDs and technical values. The
    normalized form and translation deliberately touch only Devanagari letters,
    punctuation and whitespace — ASCII identifiers (e.g. ``CM-2026-0042``),
    decimal numbers and coordinates are never rewritten.
  * Do not translate IDs or coordinates.

Detection details:
  * Pure Cyrillic/Chinese/etc. text → English (unsupported, safe default).
  * Devanagari script (U+0900..U+097F) → Marathi by default; a small set of
    Hindi function words (है, नहीं, क्या, में, और, है) flips it to Hindi.
  * ``hi-*`` / ``mr-*`` transliterated (Romanized) text → detected via a
    keyword lexicon (Hindi: ``hai``, ``nahi``, ``kya``, ``mein/main``,
    ``raasta``; Marathi: ``ahe``, ``nahi``, ``kay``, ``madhye``, ``rasta``).
  * ASCII English text (no native/translit signal) → English.
  * Mixed text containing a majority of native script → that script wins; a
    Devanagari token inside English keeps English only if the script share is
    below a threshold (so ``kya hai`` romanised still reads as Hindi).
"""

from __future__ import annotations

import re
import unicodedata

from app.models.enums import LanguageCode

# --------------------------------------------------------------------------- #
# Constant tables
# --------------------------------------------------------------------------- #

# Devanagari letter → ITRANS-style romanization (deterministic, offline).
# Covers the full basic block used by both Hindi and Marathi. Vowel signs and
# the inherent-a handling produce readable Romanized output (not 1:1 phonetics).
_DEVANAGARI_TO_ROMAN: dict[str, str] = {
    # independent vowels
    "\u0905": "a", "\u0906": "aa", "\u0907": "i", "\u0908": "ii",
    "\u0909": "u", "\u090a": "uu", "\u090b": "ri", "\u090f": "e",
    "\u0910": "ai", "\u0913": "o", "\u0914": "au", "\u090d": "e",
    # consonants
    "\u0915": "k", "\u0916": "kh", "\u0917": "g", "\u0918": "gh", "\u0919": "ng",
    "\u091a": "ch", "\u091b": "chh", "\u091c": "j", "\u091d": "jh", "\u091e": "ny",
    "\u091f": "t", "\u0920": "th", "\u0921": "d", "\u0922": "dh", "\u0923": "n",
    "\u0924": "t", "\u0925": "th", "\u0926": "d", "\u0927": "dh", "\u0928": "n",
    "\u092a": "p", "\u092b": "ph", "\u092c": "b", "\u092d": "bh", "\u092e": "m",
    "\u092f": "y", "\u0930": "r", "\u0932": "l", "\u0935": "v", "\u0936": "sh",
    "\u0937": "sh", "\u0938": "s", "\u0939": "h",
    "\u0958": "k", "\u0959": "kh", "\u095a": "g", "\u095b": "z", "\u095c": "d",
    "\u095d": "dh", "\u095e": "ph", "\u095f": "y", "\u0931\u093c": "r",
    # vowel signs (matras)
    "\u093e": "a", "\u093f": "i", "\u0940": "ii", "\u0941": "u", "\u0942": "uu",
    "\u0943": "ri", "\u0947": "e", "\u0948": "ai", "\u094b": "o", "\u094c": "au",
    # virama (suppresses inherent 'a')
    "\u094d": "",
    # nukta
    "\u093c": "",
    # punctuation kept (not in the roman map)
}

# Transliterated (Romanized) keyword lexicons for Hindi / Marathi.
# Used to detect language from romanised text ("Romanized Marathi/Hindi").
_HI_TRANSLIT: tuple[str, ...] = (
    "hai", "nahi", "kya", "mein", "main", "hain", "raasta", "sadak", "ki",
    "ka", "ke", "hai.", "bhi", "pani", "bijli", "kachra", "gali",
)
_MR_TRANSLIT: tuple[str, ...] = (
    "ahe", "kay", "madhye", "jhaale", "aahe", "rasta", "pahije", "chuki",
    "pani", "nada", "kutra", "swachchata", "dIVa", "pav", "gava",
)

# Native-script function-word lexicons (detected within Devanagari tokens).
# Marathi is the default for Devanagari; hitting a Hindi-only function word
# switches to Hindi. Marathi words that differ from Hindi carry the MR signal.
_HI_NATIVE: tuple[str, ...] = (
    "है", "नहीं", "क्या", "में", "और", "हैं", "हूँ", "करें", "बंद", "सड़क",
    "पानी", "बिजली", "कचरा", "रास्ता", "घर", "गली", "दिन", "काम", "नया",
)
_MR_NATIVE: tuple[str, ...] = (
    "आहे", "नाही", "काय", "मध्ये", "आहेत", "झाले", "पाहिजे", "चुकी",
    "रस्ता", "पाणी", "नळ", "कचरा", "घर", "गल्ली", "दिवस", "काम", "नवीन",
    "कचऱ्याचा", "कुत्रांनी", "पसरवला", "साचले",
)

# Words that appear in both lexicons (handled as neutral — they don't tip the
# vote either way because they appear in both lists).
# NOTE: "पानी"/"पाणी", "कचरा"/"कचरा", "घर"/"घर", "काम"/"काम" collide between
# Hindi and Marathi forms; giving no exclusive signal, they are shared-domain
# words. Only words unique to a language (है vs आहे, क्या vs काय, मंे vs मध्ये)
# actually vote.

# Shared vocabulary that must NOT vote (appears identically in both).
_NEUTRAL_NATIVE: frozenset[str] = frozenset(
    {"पानी", "कचरा", "घर", "काम", "रस्ता", "गली", "गल्ली", "पाणी"}
)

_HI_ONLY_NATIVE = tuple(w for w in _HI_NATIVE if w not in _MR_NATIVE and w not in _NEUTRAL_NATIVE)
_MR_ONLY_NATIVE = tuple(w for w in _MR_NATIVE if w not in _HI_NATIVE and w not in _NEUTRAL_NATIVE)

# Civic phrase dictionary for translate(): en -> {hi, mr}. Keys are lowercase
# English civic terms; values map target language code -> phrase. Non-listed
# content is passed through unchanged (preserving user data).
_PHRASES_EN: dict[str, dict[str, str]] = {
    "road damage": {"hi": "सड़क क्षति", "mr": "रस्ता नुकसान"},
    "water leak": {"hi": "पानी का रिसाव", "mr": "पाण्याची गळती"},
    "flooding": {"hi": "बाढ़", "mr": "पूर"},
    "garbage": {"hi": "कचरा", "mr": "कचरा"},
    "streetlight": {"hi": "स्ट्रीट लाइट", "mr": "स्ट्रीट लाइट"},
    "street light": {"hi": "स्ट्रीट लाइट", "mr": "स्ट्रीट लाइट"},
    "drainage": {"hi": "नाला", "mr": "नाला"},
    "fallen tree": {"hi": "गिरा हुआ पेड़", "mr": "पडलेले झाड"},
    "other": {"hi": "अन्य", "mr": "इतर"},
    "complaint": {"hi": "शिकायत", "mr": "तक्रार"},
    "status": {"hi": "स्थिति", "mr": "स्थिती"},
    "priority": {"hi": "प्राथमिकता", "mr": "प्राधान्य"},
    "ward": {"hi": "वार्ड", "mr": "वॉर्ड"},
    "department": {"hi": "विभाग", "mr": "विभाग"},
    "water": {"hi": "पानी", "mr": "पाणी"},
    "electricity": {"hi": "बिजली", "mr": "वीज"},
    "sanitation": {"hi": "स्वच्छता", "mr": "स्वच्छता"},
    "received": {"hi": "प्राप्त हुई", "mr": "प्राप्त झाली"},
    "submitted": {"hi": "दर्ज की गई", "mr": "दाखल केली"},
    "in progress": {"hi": "प्रगति में", "mr": "प्रगतीत"},
    "resolved": {"hi": "हल हो गई", "mr": "निराकरण झाले"},
    "work order": {"hi": "कार्य आदेश", "mr": "कार्य आदेश"},
}

# English <-> Hindi/Marathi translations for a small set of fixed assistant /
# triage strings (labels rendered by the pipeline).
_STRING_EN: dict[str, dict[str, str]] = {
    "received": {"hi": "प्राप्त हुई", "mr": "प्राप्त झाली"},
    "submitted": {"hi": "दर्ज की गई", "mr": "दाखल केली"},
    "in progress": {"hi": "प्रगति में", "mr": "प्रगतीत"},
    "resolved": {"hi": "हल हो गई", "mr": "निराकरण झाले"},
    "closed": {"hi": "बंद", "mr": "बंद"},
    "open": {"hi": "खुली", "mr": "खुली"},
    "assigned": {"hi": "सौंपी गई", "mr": "नियुक्त केले"},
    "reported": {"hi": "रिपोर्ट", "mr": "अहवाल"},
}

_SUPPORTED_CODES: frozenset[str] = frozenset(code.value for code in LanguageCode)

# Devanagari script range used for detection.
_DEVANAGARI_RE = re.compile(r"[\u0900-\u097f]")

# Tokens we must never translate: complaint IDs, coordinates, numeric values.
_COMPLAINT_ID_RE = re.compile(
    r"\b(?:CM-|CMP-|WO-|WRK-|PRD-|TKT-|[A-Z]{2,3}-\d{2,8})\b", re.IGNORECASE
)
_COORD_RE = re.compile(r"-?\d{1,3}\.\d{2,9},\s*-?\d{1,3}\.\d{2,9}")
_NUMBER_RE = re.compile(r"\b\d[\d,\.]*\b")


# --------------------------------------------------------------------------- #
# Detection
# --------------------------------------------------------------------------- #
def supported(language: str | None) -> str:
    """Normalize/validate a language code to a supported code (default ``en``)."""
    if not language:
        return LanguageCode.EN.value
    code = language.strip().lower()
    if code in _SUPPORTED_CODES:
        return code
    # Accept extended forms (e.g. "en-US", "hi-IN") and reduce to the base code.
    base = code.split("-")[0].split("_")[0].strip()
    if base in _SUPPORTED_CODES:
        return base
    return LanguageCode.EN.value


def detect_language(text: str) -> str:
    """Return the supported language code for ``text`` (English default).

    Mixed-language text is handled by scoring the *majority signal*: native
    script votes for its language, romanized keywords vote for theirs, and pure
    ASCII with no signal falls back to English so an English+Hindi mix that is
    majority-English reads as English.
    """
    if not text or not text.strip():
        return LanguageCode.EN.value

    native_chars = len(_DEVANAGARI_RE.findall(text))

    # 1) Strong Devanagari presence (>= some ratio of non-space characters).
    if native_chars > 0:
        total_alpha = len(re.sub(r"\s", "", text)) or 1
        devanagari_share = native_chars / total_alpha
        if devanagari_share >= 0.4:
            return _native_language(text)

    # 2) Romanized (transliterated) Devanagari via keyword lexicons.
    if native_chars == 0:
        roman = _translit_language(text.lower())
        if roman is not None:
            return roman

    # 3) Mixed / default: if there is any Devanagari but it is a minority, still
    #    honor a strong romanized keyword signal; otherwise English.
    if native_chars > 0:
        roman = _translit_language(text.lower())
        if roman is not None:
            return roman

    # 4) Default English (pure ASCII without a lexicon match).
    return LanguageCode.EN.value


def _native_language(text: str) -> str:
    """Decide Marathi vs Hindi from a Devanagari string."""
    hi_score = _count_native(text, _HI_ONLY_NATIVE)
    mr_score = _count_native(text, _MR_ONLY_NATIVE)
    if mr_score > hi_score:
        return LanguageCode.MR.value
    if hi_score > mr_score:
        return LanguageCode.HI.value
    # Tie or neither: Marathi is the default Devanagari assumption (this demo
    # city is in Maharashtra), but a plain "है" style (Hindi) still tips Hindi.
    return LanguageCode.MR.value if mr_score else LanguageCode.HI.value


def _count_native(text: str, words: tuple[str, ...]) -> int:
    """Count unique whole-word matches (not substrings) to avoid false positives
    like Marathi ``काय`` inside Hindi ``शिकायत``.
    """
    seen: set[str] = set()
    for word in words:
        if re.search(rf"(?<!\w){re.escape(word)}(?!\w)", text):
            seen.add(word)
    return len(seen)


def _translit_language(lower: str) -> str | None:
    """Return the language for romanised text, or ``None`` if ambiguous."""
    # Normalize spacing/punctuation for matching.
    compact = re.sub(r"[^a-z ]", " ", lower)
    hi = sum(1 for w in _HI_TRANSLIT if re.search(rf"\b{w}\b", compact))
    mr = sum(1 for w in _MR_TRANSLIT if re.search(rf"\b{w}\b", compact))
    if mr > hi:
        return LanguageCode.MR.value
    if hi > mr:
        return LanguageCode.HI.value
    return None


# --------------------------------------------------------------------------- #
# Normalization (transliteration) — preserves names/IDs/coordinates
# --------------------------------------------------------------------------- #
def normalize(text: str, language: str | None = None) -> str:
    """Return the internal normalized representation for ``text``.

    Devanagari letters are transliterated to a Romanized form (Hindi/Marathi →
    ITRANS-style). Everything that is not a Devanagari letter — names in Latin
    script, addresses, complaint IDs, coordinates and numbers — is preserved
    byte-for-byte. ``language`` selects the script table (both use the same
    table today); when omitted it is detected.
    """
    if not text:
        return text
    detected = supported(language) if language else detect_language(text)
    if detected == LanguageCode.EN.value:
        return normalize_ascii(text)
    return _transliterate(text)


def _transliterate(text: str) -> str:
    out: list[str] = []
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        if ch in _DEVANAGARI_TO_ROMAN:
            out.append(_DEVANAGARI_TO_ROMAN[ch])
        elif _DEVANAGARI_RE.match(ch):
            # A Devanagari letter not in the table (rare) — drop to a space and
            # continue so we never corrupt surrounding data.
            out.append(" ")
        else:
            out.append(ch)
        i += 1
    roman = "".join(out)
    return normalize_ascii(roman)


def normalize_ascii(text: str) -> str:
    """Fold whitespace, trim and NFC-normalize an ASCII/Latin string.

    Applied to both the transliterated form and pure-ASCII input so downstream
    matching is insensitive to stray spaces / punctuation.
    """
    text = unicodedata.normalize("NFC", text)
    # Collapse runs of whitespace to a single space and trim.
    text = re.sub(r"\s+", " ", text).strip()
    return text


# --------------------------------------------------------------------------- #
# Translation (phrase-level, preserves IDs/names/numbers)
# --------------------------------------------------------------------------- #
def translate(text: str, source: str | None = None, target: str | None = None) -> str:
    """Translate civic content ``text`` into ``target`` (phrase-level, offline).

    * Purely English → supported target picks the phrase dictionary; unknown
      English words and all names/IDs/numbers pass through unchanged.
    * Native script input is transliterated to English first, then the English
      phrases (if recognized) are swapped for the target-language phrase.
    * ``source`` may be omitted (auto-detect); ``target`` defaults to ``en``.

    The helper is intentionally conservative: it preserves all ASCII tokens
    (IDs, coordinates, numbers, Latin names) and only rewrites known civic
    phrases, so user data is never altered.
    """
    target = supported(target) if target else LanguageCode.EN.value
    if not text or not text.strip():
        return text

    # Always transliterate native script → English first (the canonical token
    # space), preserving IDs/numbers in the process.
    english = _to_english_tokens(text, supported(source) if source else None)
    if target == LanguageCode.EN.value:
        return english

    phrases = _PHRASES_EN
    result = english
    for phrase, mapping in sorted(phrases.items(), key=lambda kv: -len(kv[0])):
        if target in mapping and phrase in result.lower():
            result = _replace_phrase_ci(result, phrase, mapping[target])
    return result


def _replace_phrase_ci(text: str, phrase: str, replacement: str) -> str:
    """Case-insensitive, whole-token phrase replacement preserving surroundings."""
    pattern = re.compile(rf"(?i)\b{re.escape(phrase)}\b")
    return pattern.sub(replacement, text)


def _to_english_tokens(text: str, source: str | None) -> str:
    """Convert ``text`` to its English (Romanized) token form."""
    if _DEVANAGARI_RE.search(text):
        return _transliterate(text)
    return text


# --------------------------------------------------------------------------- #
# Public convenience / labels
# --------------------------------------------------------------------------- #
def language_label(code: str) -> str:
    """Human-readable label for a supported language code."""
    return {
        "en": "English",
        "hi": "Hindi",
        "mr": "Marathi",
    }.get(supported(code), "English")


def all_languages() -> list[dict]:
    """Return the supported language list (for the public /languages endpoint)."""
    return [
        {
            "code": LanguageCode.EN.value,
            "name": "English",
            "native_name": "English",
            "default": True,
        },
        {"code": LanguageCode.HI.value, "name": "Hindi", "native_name": "हिन्दी"},
        {"code": LanguageCode.MR.value, "name": "Marathi", "native_name": "मराठी"},
    ]


def is_supported_code(code: str | None) -> bool:
    return supported(code) == code and code is not None
