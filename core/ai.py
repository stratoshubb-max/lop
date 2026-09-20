"""Athar's AI layer.

A self-contained writing assistant + ranking engine that runs entirely on the
server with no mandatory third-party dependency:

* Arabic-aware tokenisation, keyword and hashtag extraction (corpus TF-IDF)
* extractive summarisation (centroid sentence scoring)
* bilingual tone / sentiment analysis and a "kindness" pre-flight check
* intent classification + template natural-language generation for smart replies
* deterministic rewriting (polish / sharpen / warm / bold / shorten / expand)
* BM25 relevance ranking powering search and "more like this"
* heuristic people, topic and writing-prompt recommendations

When ``AI_API_KEY`` (or ``OPENAI_API_KEY``) is configured the module
transparently upgrades to a hosted model through any OpenAI-compatible
endpoint and silently falls back to the local engine when the network call
fails. Nothing here requires a key to work.
"""

from __future__ import annotations

import json
import math
import os
import re
import unicodedata
import urllib.error
import urllib.request
from collections import Counter
from datetime import datetime, timezone as dt_timezone

# --------------------------------------------------------------------------- #
# Language resources
# --------------------------------------------------------------------------- #

ARABIC_RE = re.compile(r"[\u0600-\u06FF\u0750-\u077F\u08A0-\u08FF\uFB50-\uFDFF\uFE70-\uFEFF]")
TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z'’\-]*|[0-9]+|[\u0600-\u06FF\u0750-\u077F][\u0600-\u06FF\u0750-\u077F'’\-]*")
SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?؟…。])\s+|\n+")
HASHTAG_RE = re.compile(r"#([\w\u0600-\u06FF_]+)")
URL_RE = re.compile(r"https?://\S+|www\.\S+")

ARABIC_DIACRITICS_RE = re.compile(r"[\u0610-\u061A\u064B-\u065F\u0670\u06D6-\u06ED\u0640]")
ARABIC_NORMALISE = str.maketrans({
    "أ": "ا", "إ": "ا", "آ": "ا", "ٱ": "ا", "ى": "ي", "ئ": "ي", "ؤ": "و", "ة": "ه",
})

STOPWORDS_EN = {
    "a", "about", "above", "after", "again", "against", "all", "also", "am", "an", "and", "any", "are",
    "aren", "as", "at", "be", "because", "been", "before", "being", "below", "between", "both", "but",
    "by", "can", "could", "did", "do", "does", "doing", "don", "down", "during", "each", "few", "for",
    "from", "further", "get", "got", "had", "has", "have", "having", "he", "her", "here", "hers", "herself",
    "him", "himself", "his", "how", "i", "if", "in", "into", "is", "isn", "it", "its", "itself", "just",
    "like", "ll", "me", "mine", "more", "most", "my", "myself", "no", "nor", "not", "now", "of", "off",
    "on", "once", "one", "only", "or", "other", "our", "ours", "ourselves", "out", "over", "own", "re",
    "really", "s", "same", "she", "should", "so", "some", "such", "t", "than", "that", "the", "their",
    "theirs", "them", "themselves", "then", "there", "these", "they", "this", "those", "through", "to",
    "too", "under", "until", "up", "ve", "very", "was", "we", "were", "what", "when", "where", "which",
    "while", "who", "whom", "why", "will", "with", "would", "you", "your", "yours", "yourself", "think",
    "thing", "things", "much", "many", "make", "made", "way", "let", "im", "ive", "dont", "cant", "it's",
}

STOPWORDS_AR = {
    "في", "من", "على", "الى", "إلى", "عن", "مع", "هذا", "هذه", "ذلك", "تلك", "التي", "الذي", "الذين",
    "كان", "كانت", "يكون", "هو", "هي", "هم", "هن", "انا", "أنا", "نحن", "انت", "أنت", "انتم", "لكن",
    "لكي", "حتى", "كل", "بعض", "بين", "بعد", "قبل", "عند", "عندما", "اذا", "إذا", "ثم", "او", "أو",
    "و", "لا", "ما", "لم", "لن", "هل", "نعم", "جدا", "جدًا", "اي", "أي", "ايضا", "أيضا", "قد", "كما",
    "هناك", "هنا", "الان", "الآن", "شيء", "شيئا", "أكثر", "اكثر", "اكثر", "دائما", "دائماً", "ربما",
    "ان", "أن", "إن", "على_انه", "كيف", "ماذا", "لماذا", "متى", "اين", "أين", "يعني", "بشكل", "ضد",
}

POSITIVE_EN = {
    "love": 2.4, "loved": 2.2, "great": 2.0, "amazing": 2.4, "beautiful": 2.2, "grateful": 2.2,
    "thank": 1.8, "thanks": 1.8, "kind": 2.0, "calm": 1.6, "hope": 1.8, "bright": 1.6, "clear": 1.4,
    "joy": 2.2, "proud": 2.0, "excited": 2.0, "inspired": 2.2, "peace": 1.9, "gentle": 1.7, "delight": 2.0,
    "helpful": 1.9, "brilliant": 2.2, "wonderful": 2.3, "good": 1.4, "better": 1.3, "best": 2.0,
    "win": 1.7, "growth": 1.5, "learn": 1.4, "learned": 1.4, "progress": 1.6, "support": 1.5, "warm": 1.5,
    "smile": 1.8, "quiet": 1.2, "steady": 1.4, "trust": 1.6, "curious": 1.4, "possible": 1.5,
}
NEGATIVE_EN = {
    "hate": -2.6, "terrible": -2.4, "awful": -2.4, "angry": -2.2, "furious": -2.6, "sad": -2.0,
    "tired": -1.5, "exhausted": -1.9, "afraid": -2.1, "fear": -2.0, "anxious": -2.0, "worried": -1.9,
    "broken": -2.2, "fail": -2.0, "failed": -2.0, "failure": -2.0, "useless": -2.2, "stupid": -2.4,
    "idiot": -2.8, "horrible": -2.4, "pain": -2.1, "lonely": -2.0, "lost": -1.6, "stuck": -1.7,
    "stress": -1.8, "stressed": -1.9, "bad": -1.6, "worse": -1.9, "worst": -2.3, "never": -1.2,
    "disappointed": -2.1, "regret": -2.0, "hopeless": -2.6, "tiredness": -1.4, "noise": -0.8,
}
POSITIVE_AR = {
    "حب": 2.4, "أحب": 2.4, "احب": 2.4, "جميل": 2.2, "جميلة": 2.2, "رائع": 2.4, "رائعة": 2.4,
    "شكرا": 1.8, "شكرًا": 1.8, "ممتن": 2.2, "سعيد": 2.1, "فرح": 2.2, "أمل": 1.8, "امل": 1.8,
    "طمأنينة": 2.0, "هدوء": 1.7, "نجاح": 2.0, "تقدم": 1.6, "تعلمت": 1.5, "إلهام": 2.1, "الهام": 2.1,
    "لطيف": 1.9, "لطيفة": 1.9, "صبر": 1.4, "قوة": 1.5, "خير": 1.5, "ممتاز": 2.1, "ابداع": 2.0,
    "إبداع": 2.0, "مبدع": 1.9, "وفاء": 1.6, "صدق": 1.5,
}
NEGATIVE_AR = {
    "أكره": -2.6, "اكره": -2.6, "سيء": -2.3, "سيئة": -2.3, "غاضب": -2.2, "حزين": -2.0, "حزينة": -2.0,
    "تعبان": -1.8, "متعب": -1.7, "خائف": -2.1, "قلق": -2.0, "فشل": -2.0, "فاشل": -2.2, "غبي": -2.4,
    "مؤلم": -2.2, "ألم": -2.0, "الم": -2.0, "وحيد": -2.0, "ضايع": -1.6, "تائه": -1.6, "غاضبة": -2.2,
    "كره": -2.4, "يأس": -2.5, "ياس": -2.5, "خذلان": -2.2, "محبط": -2.0, "ضغط": -1.7,
}

WEAK_TAGS = {
    "following", "follow", "edited", "edit", "edits", "own", "today", "tomorrow", "yesterday",
    "day", "days", "time", "times", "people", "post", "posts", "write", "wrote", "writes",
    "thing", "things", "think", "thinks", "thought", "thoughts", "just", "now", "new", "good",
    "make", "makes", "made", "need", "needs", "want", "wants", "know", "knows", "like", "likes",
    "also", "much", "many", "one", "two", "first", "last", "next", "still", "even", "ever",
    "never", "going", "getting", "start", "started", "start", "every", "some", "more", "most",
    "here", "there", "really", "actually", "sure", "well", "back", "come", "came", "take",
}

HEDGES_EN = ["maybe", "perhaps", "i think", "i guess", "kind of", "sort of", "just", "really", "very",
             "actually", "basically", "somewhat", "a bit", "a little", "i mean", "honestly", "literally"]
FILLER_EN = ["you know", "at the end of the day", "needless to say", "in order to", "as a matter of fact",
             "it is important to note that", "what i'm trying to say is", "for what it's worth"]
HEDGES_AR = ["ربما", "اعتقد", "أعتقد", "نوعا ما", "نوعًا ما", "فقط", "جدا", "جدًا", "في الحقيقة", "بصراحة", "تقريبا", "تقريبًا"]
FILLER_AR = ["في نهاية المطاف", "من الجدير بالذكر", "تجدر الإشارة إلى أن", "ما أحاول قوله هو"]

ABBREVIATIONS = {
    "u": "you", "ur": "your", "urs": "yours", "pls": "please", "plz": "please", "thx": "thanks",
    "tho": "though", "cuz": "because", "bc": "because", "wanna": "want to", "gonna": "going to",
    "gotta": "got to", "kinda": "kind of", "sorta": "sort of", "dont": "don't", "cant": "can't",
    "wont": "won't", "isnt": "isn't", "doesnt": "doesn't", "didnt": "didn't", "wasnt": "wasn't",
    "wouldnt": "wouldn't", "couldnt": "couldn't", "shouldnt": "shouldn't", "havent": "haven't",
    "hasnt": "hasn't", "hadnt": "hadn't", "im": "I'm", "ive": "I've", "id": "I'd", "ill": "I'll",
    "youre": "you're", "youve": "you've", "theyre": "they're", "theres": "there's", "thats": "that's",
    "whats": "what's", "lets": "let's", "iam": "I am", "aint": "isn't", "ok": "okay", "abt": "about",
    "tbh": "to be honest", "imo": "in my opinion", "imho": "in my honest opinion", "rn": "right now",
    "ngl": "not going to lie", "smh": "shaking my head", "irl": "in real life", "dm": "message",
}

SHOUTY_RE = re.compile(r"\b[A-Z]{4,}\b")
MULTISPACE_RE = re.compile(r"[ \t]{2,}")
REPEATED_WORD_RE = re.compile(r"\b(\w+)(\s+\1\b)+", re.IGNORECASE)
REPEATED_PUNCT_RE = re.compile(r"([!?.,])\1{1,}")

INTENTS = {
    "question": ["how", "why", "what", "when", "where", "which", "who", "should", "can", "could", "anyone",
                 "recommend", "advice", "كيف", "لماذا", "ماذا", "متى", "اين", "أين", "هل", "نصيحة", "اقترح"],
    "celebration": ["launched", "shipped", "finished", "won", "proud", "achieved", "birthday", "anniversary",
                    "completed", "أنجزت", "انجزت", "فخور", "أطلقت", "اكملت", "أكملت", "نجحت"],
    "struggle": ["struggling", "stuck", "hard", "difficult", "tired", "exhausted", "burnout", "failed",
                 "anxious", "overwhelmed", "أعاني", "متعب", "صعب", "فشلت", "قلق", "مرهق"],
    "idea": ["idea", "concept", "thought", "wondering", "imagine", "building", "exploring", "experiment",
             "فكرة", "أفكار", "تصور", "أبني", "تجربة"],
    "thanks": ["thanks", "thank you", "grateful", "appreciate", "شكرا", "شكرًا", "ممتن", "أقدر"],
    "opinion": ["believe", "think", "believe", "opinion", "seems", "arguably", "أعتقد", "أرى", "رأي"],
}

REPLY_TEMPLATES = {
    "en": {
        "question": [
            "I have wondered the same thing. What I found most useful was {keyword} — start small and let the answer reveal itself.",
            "Short answer: it depends on what you want to protect. If {keyword} matters most, optimise for that first.",
            "Try this: write down the two options, then ask which one you'd defend a year from now. That usually settles it.",
        ],
        "celebration": [
            "This is worth celebrating — congratulations! The {keyword} part especially stands out.",
            "Love seeing this land. Moments like this deserve to be remembered.",
            "Well earned. Keeping the momentum on {keyword} is the next quiet win.",
        ],
        "struggle": [
            "Thank you for saying this out loud. When {keyword} feels heavy, shrinking the next step usually helps.",
            "That sounds genuinely hard. Be gentle with yourself — progress here rarely looks linear.",
            "I hear you. Rest is not the opposite of progress; it is part of the work.",
        ],
        "idea": [
            "This is a lovely seed of an idea. The part about {keyword} is what I'd chase first.",
            "I like where this is going — what would the smallest version of it look like?",
            "There is something here. If you build it, the {keyword} angle could be the differentiator.",
        ],
        "thanks": [
            "Glad it helped. Passing the kindness forward is the best use of it.",
            "Thank you for taking the time to say that — it means something.",
            "Anytime. Keep writing; this space is better with your voice in it.",
        ],
        "opinion": [
            "Interesting take. I see it slightly differently on {keyword}, but I'm glad you said it plainly.",
            "That is a fair reading. The nuance for me lives in how {keyword} changes with context.",
            "Agreed in spirit. Where I pause is the cost of {keyword} — worth naming out loud.",
        ],
        "general": [
            "This stayed with me. The {keyword} angle is the part I keep thinking about.",
            "Quietly a very good thought. Thank you for putting it here.",
            "I want to sit with this one. Would you say more about {keyword}?",
        ],
    },
    "ar": {
        "question": [
            "سألت نفسي السؤال ذاته. أكثر ما ساعدني هو التركيز على {keyword} — ابدأ صغيرا واترك الإجابة تتضح.",
            "الجواب القصير: يعتمد على ما تريد حمايته. إذا كان {keyword} هو الأهم، فابدأ من هناك.",
            "جرّب أن تكتب الخيارين، ثم اسأل نفسك أيهما ستدافع عنه بعد سنة. هذا غالبا يحسم الأمر.",
        ],
        "celebration": [
            "هذا يستحق الاحتفال — مبارك! خصوصا الجزء المتعلق بـ {keyword}.",
            "يسعدني أن أرى هذا يتحقق. لحظات كهذه تستحق أن تُحفظ.",
            "مستحق تماما. الاستمرار على {keyword} هو المكسب الهادئ القادم.",
        ],
        "struggle": [
            "شكرا لأنك قلت هذا بصوت مسموع. حين يثقل {keyword}، تصغير الخطوة القادمة يساعد دائما.",
            "يبدو الأمر صعبا فعلا. كن لطيفا مع نفسك — التقدم هنا نادرا ما يكون خطا مستقيما.",
            "أسمعك. الراحة ليست عكس التقدم، بل جزء من العمل.",
        ],
        "idea": [
            "فكرة واعدة. الجزء المتعلق بـ {keyword} هو ما سأتبعه أولا.",
            "يعجبني الاتجاه — كيف سيبدو أصغر شكل ممكن منها؟",
            "هناك شيء هنا. لو بنيتها، فزاوية {keyword} قد تكون الفرق الحقيقي.",
        ],
        "thanks": [
            "سعيد أن ذلك أفاد. تمرير اللطف هو أفضل استخدام له.",
            "شكرا لأنك أخذت وقتك لتقول هذا — يعني الكثير.",
            "في أي وقت. واصل الكتابة؛ هذا المكان أفضل بصوتك.",
        ],
        "opinion": [
            "قراءة مهمة. أراها مختلفة قليلا في مسألة {keyword}، لكن سعيد أنك قلت رأيك بوضوح.",
            "رأي منصف. الفرق عندي في كيف يتغير {keyword} بتغير السياق.",
            "أتفق في الروح. ما أتوقف عنده هو كلفة {keyword} — تستحق أن تُذكر.",
        ],
        "general": [
            "هذه الفكرة بقيت معي. زاوية {keyword} هي ما أفكر فيه.",
            "فكرة جيدة بهدوء. شكرا لأنك وضعتها هنا.",
            "أريد أن أتأملها. هل تحدثني أكثر عن {keyword}؟",
        ],
    },
}

PROMPTS = {
    "en": [
        "What did you change your mind about this week?",
        "Describe a small habit that quietly improved your days.",
        "What advice would you give your past self a year ago?",
        "Name one book, place, or person that reshaped how you think.",
        "What is something people around you overlook?",
    ],
    "ar": [
        "ما الفكرة التي غيّرت رأيك فيها هذا الأسبوع؟",
        "صف عادة صغيرة حسّنت أيامك بهدوء.",
        "ما النصيحة التي كنت ستقولها لنفسك قبل سنة؟",
        "اذكر كتابا أو مكانا أو شخصا غيّر طريقة تفكيرك.",
        "ما الشيء الذي يغفل عنه من حولك؟",
    ],
}

SUGGESTED_TOPICS = {
    "en": ["Slow living", "Craft", "Reading", "Design", "Focus", "Kindness", "Learning", "Cities"],
    "ar": ["الهدوء", "القراءة", "التصميم", "التركيز", "الكتابة", "التعلم", "المدينة", "الطبيعة"],
}


# --------------------------------------------------------------------------- #
# Small text utilities
# --------------------------------------------------------------------------- #

def _plain(value) -> str:
    return "" if value is None else str(value)


def detect_language(text: str) -> str:
    """Return ``"ar"`` when the text is mostly Arabic, otherwise ``"en"``."""
    text = _plain(text)
    if not text.strip():
        return "en"
    arabic = len(ARABIC_RE.findall(text))
    latin = len(re.findall(r"[A-Za-z]", text))
    if arabic == 0 and latin == 0:
        return "en"
    return "ar" if arabic >= max(2, latin * 0.35) else "en"


def strip_control(text: str) -> str:
    """Remove control characters that break JSON/templates."""
    return "".join(ch for ch in _plain(text) if unicodedata.category(ch)[0] != "C" or ch in "\n\t")


def normalise_arabic(word: str) -> str:
    return word.translate(ARABIC_NORMALISE).replace("ـ", "")


def strip_diacritics(text: str) -> str:
    return ARABIC_DIACRITICS_RE.sub("", _plain(text))


def tokens(text: str, *, keep_stopwords: bool = False) -> list[str]:
    """Arabic-aware tokeniser."""
    cleaned = strip_diacritics(URL_RE.sub(" ", _plain(text))).lower()
    words = TOKEN_RE.findall(cleaned)
    output = []
    for word in words:
        normalised = normalise_arabic(word)
        if not keep_stopwords:
            if normalised in STOPWORDS_EN or normalised in STOPWORDS_AR:
                continue
            if len(normalised) < 2 and not normalised.isdigit():
                continue
        output.append(normalised)
    return output


def sentences(text: str) -> list[str]:
    parts = [s.strip() for s in SENTENCE_SPLIT_RE.split(_plain(text)) if s and s.strip()]
    return parts


def word_count(text: str) -> int:
    return len(tokens(text, keep_stopwords=True))


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


# --------------------------------------------------------------------------- #
# Keywords, hashtags & titles
# --------------------------------------------------------------------------- #

def keywords(text: str, limit: int = 6, *, extra_corpus: list[str] | None = None) -> list[str]:
    """Frequency + position weighted keywords, damped by corpus-wide rarity."""
    corpus = [_plain(text)] + [_plain(item) for item in (extra_corpus or [])]
    document_frequency: Counter = Counter()
    for document in corpus:
        document_frequency.update(set(tokens(document)))

    counted: Counter = Counter()
    order: dict[str, int] = {}
    for index, word in enumerate(tokens(text)):
        counted[word] += 1
        order.setdefault(word, index)

    total_docs = max(1, len(corpus))
    scored: list[tuple[float, str]] = []
    for word, frequency in counted.items():
        rarity = math.log(1 + total_docs / (1 + document_frequency[word]))
        position_bonus = 1.0 + 0.35 / (1 + order[word])
        length_bonus = 1.0 + min(len(word), 12) / 40
        score = (frequency ** 0.92) * rarity * position_bonus * length_bonus
        scored.append((score, word))
    scored.sort(key=lambda item: (-item[0], item[1]))

    chosen: list[str] = []
    for _, word in scored:
        if word in chosen:
            continue
        if any(word in existing or existing in word for existing in chosen):
            continue
        chosen.append(word)
        if len(chosen) >= limit:
            break
    return chosen


SUFFIX_RULES = (
    ("izations", "ization"), ("ization", "ize"), ("isations", "isation"),
    ("ingly", ""), ("edly", ""),
    ("ies", "y"), ("sses", "ss"), ("ses", "se"), ("ches", "ch"), ("shes", "sh"), ("xes", "x"),
    ("ing", ""), ("ed", ""), ("ly", ""), ("s", ""),
)

# Words whose endings look like suffixes but are part of the word itself.
STEM_EXCEPTIONS = {
    "morning", "evening", "thing", "nothing", "something", "anything", "everything", "during",
    "spring", "string", "king", "ring", "wing", "sing", "bring", "sting", "swing", "feeling",
    "meeting", "ceiling", "sibling", "clothing", "wedding", "building", "always", "perhaps",
    "sometimes", "across", "process", "business", "happiness", "kindness", "series", "species",
    "news", "yes", "this", "was", "has", "is", "his", "its", "us", "as", "less", "class",
    "pass", "grass", "glass", "press", "address", "success", "access", "stress", "focus",
}


def canonical(word: str) -> str:
    """Very light stemming so one idea yields one tag.

    ``designing``/``designs``/``designed`` all fold back to ``design`` so the
    topic rail never shows near-duplicates of the same idea.
    """
    if not word:
        return ""
    if ARABIC_RE.search(word):
        return normalise_arabic(word)
    lowered = word.lower().strip("'")
    if len(lowered) <= 4 or lowered in STEM_EXCEPTIONS:
        return lowered
    for suffix, replacement in SUFFIX_RULES:
        if not lowered.endswith(suffix):
            continue
        if suffix in {"s", "ed", "ly"} and lowered[-2:] in {"ss", "us", "is", "as", "os"}:
            continue
        if suffix == "ly" and len(lowered) <= 5:
            continue
        if len(lowered) - len(suffix) < 3:
            continue
        candidate = lowered[: len(lowered) - len(suffix)] + replacement
        if len(candidate) >= 3:
            return candidate
    return lowered


def hashtags(text: str, limit: int = 4, *, extra_corpus: list[str] | None = None) -> list[str]:
    """Hashtags already present in the text first, then generated keywords."""
    existing = [tag for tag in HASHTAG_RE.findall(_plain(text))]
    result: list[str] = []
    for tag in existing:
        cleaned = tag.strip("_")
        if cleaned and cleaned not in result:
            result.append(cleaned)
    if len(result) >= limit:
        return result[:limit]

    seen = {canonical(item) for item in result}
    for word in keywords(text, limit=limit * 4, extra_corpus=extra_corpus):
        if word.isdigit() or len(word) < 3 or word in WEAK_TAGS:
            continue
        folded = canonical(word)
        if len(folded) < 3 or folded in seen:
            continue
        seen.add(folded)
        result.append(folded)
        if len(result) >= limit:
            break
    return result[:limit]


def explicit_tags(text: str, limit: int = 4) -> list[str]:
    """Only the hashtags the author actually typed, de-duplicated."""
    unique: list[str] = []
    for tag in HASHTAG_RE.findall(_plain(text)):
        clean = tag.strip("_")
        if not clean:
            continue
        if clean.lower() in {item.lower() for item in unique}:
            continue
        unique.append(clean)
    return unique[:limit]


def meaningful_tags(text: str, limit: int = 4, *, extra_corpus: list[str] | None = None) -> list[str]:
    """Tags worth storing on a post.

    Author-written hashtags always win; otherwise the strongest non-filler
    keywords are used so the topic rail never fills up with noise.
    """
    return explicit_tags(text, limit) or hashtags(text, limit, extra_corpus=extra_corpus)


def title_for(text: str) -> str:
    """A short headline generated from the strongest sentence."""
    parts = sentences(text)
    if not parts:
        return ""
    scored = [(sentence_score(part, text), part) for part in parts]
    scored.sort(key=lambda item: -item[0])
    headline = scored[0][1]
    headline = re.sub(r"^[^\w\u0600-\u06FF]+", "", headline).strip()
    words = headline.split()
    if len(words) > 12:
        headline = " ".join(words[:12]).rstrip(",;:") + "…"
    if headline and headline[-1] not in ".!?…؟":
        headline += ""
    return headline[:120]


def sentence_score(sentence: str, document: str) -> float:
    """Centroid similarity between a sentence and the whole document."""
    document_words = Counter(tokens(document))
    if not document_words:
        return 0.0
    sentence_words = tokens(sentence)
    if not sentence_words:
        return 0.0
    overlap = sum(document_words[word] for word in sentence_words)
    length_penalty = 1.0 / (1 + abs(len(sentence_words) - 16) / 22)
    return overlap * length_penalty


# --------------------------------------------------------------------------- #
# Summarisation
# --------------------------------------------------------------------------- #

def summarize(texts, max_sentences: int = 3, *, language: str | None = None) -> dict:
    """Extractive summary across one or many documents (centroid + position)."""
    if isinstance(texts, str):
        documents = [texts]
    else:
        documents = [_plain(item) for item in (texts or [])]
    documents = [doc for doc in documents if doc.strip()]
    if not documents:
        return {"summary": "", "bullets": [], "language": language or "en", "keywords": [], "count": 0}

    corpus = "\n".join(documents)
    language = language or detect_language(corpus)

    candidates = []
    for doc_index, document in enumerate(documents):
        for sentence_index, sentence in enumerate(sentences(document)):
            clean = sentence.strip()
            if len(tokens(clean)) < 3:
                continue
            score = sentence_score(clean, corpus)
            score += max(0.0, 1.4 - doc_index * 0.35)          # fresher posts rank higher
            score += max(0.0, 0.5 - sentence_index * 0.18)      # opening lines matter
            if clean.endswith("?"):
                score *= 0.92                                    # keep questions, rank them slightly lower
            candidates.append((score, clean))

    chosen: list[tuple[float, str]] = []
    seen_tokens: set[str] = set()
    for score, sentence in sorted(candidates, key=lambda item: -item[0]):
        signature = set(tokens(sentence))
        if not signature:
            continue
        similarity = len(signature & seen_tokens) / max(1, len(signature))
        if similarity > 0.62:
            continue
        chosen.append((score, sentence))
        seen_tokens |= signature
        if len(chosen) >= max(1, max_sentences):
            break

    ordered = [sentence for _, sentence in chosen]
    summary = " ".join(ordered)
    return {
        "summary": summary,
        "bullets": ordered,
        "language": language,
        "keywords": keywords(corpus, 6),
        "count": len(documents),
    }


def digest(posts, *, language: str | None = None) -> dict:
    """A calm, human-readable reading of the recent feed."""
    items = list(posts or [])
    texts = [_plain(getattr(post, "body", post)) for post in items]
    texts = [text for text in texts if text.strip()]
    if not texts:
        return {
            "summary": "The feed is quiet right now — a good moment to leave the first thought.",
            "bullets": [],
            "themes": [],
            "questions": [],
            "stats": {"posts": 0, "words": 0, "questions": 0, "voices": 0},
            "language": language or "en",
        }

    corpus = "\n".join(texts)
    language = language or detect_language(corpus)
    summary = summarize(texts, 3, language=language)
    raw_themes = keywords(corpus, 10)
    themes: list[str] = []
    for word in raw_themes:
        folded = canonical(word)
        if len(folded) < 4 or folded.isdigit() or word in WEAK_TAGS or folded in themes:
            continue
        themes.append(folded)
        if len(themes) >= 5:
            break
    questions = [s.strip() for s in sentences(corpus) if s.strip().endswith(("?", "؟"))][:3]
    voices = {getattr(post, "handle", "") for post in items}
    tone = analyse_tone(corpus)

    # Compose a digest that describes the feed instead of dumping raw posts.
    voice_count = len([voice for voice in voices if voice]) or 1
    word_total = word_count(corpus)
    primary = [theme for theme in themes[:3] if theme]
    mentions = {theme: sum(1 for text in texts if theme in text.lower()) for theme in primary}
    summary_parts: list[str] = []
    if len(texts) == 1:
        summary_parts.append("A single thought sits in this window, so the feed is still finding its shape.")
    else:
        summary_parts.append(
            f"{len(texts)} thoughts from {voice_count} {'voice' if voice_count == 1 else 'voices'}, "
            f"about {word_total} words in all."
        )
    if primary:
        listing = ", ".join(primary[:-1]) + f" and {primary[-1]}" if len(primary) > 1 else primary[0]
        busiest = max(mentions, key=lambda item: mentions[item])
        summary_parts.append(
            f"The conversation keeps returning to {listing}"
            + (f", with {mentions[busiest]} mentions of {busiest}" if mentions[busiest] > 1 else "") + "."
        )
    if summary["bullets"]:
        highlight = summary["bullets"][0].strip()
        if len(highlight) > 150:
            highlight = highlight[:147].rsplit(" ", 1)[0] + "…"
        summary_parts.append(f"A line that stands out: “{highlight}”")
    if questions:
        summary_parts.append(
            f"{len(questions)} open question{'s' if len(questions) != 1 else ''} waiting for a thoughtful reply."
        )

    mood_line = {
        "en": {
            "warm": "The mood is warm and generous today.",
            "curious": "Curiosity is the dominant note in the feed.",
            "reflective": "The feed is thoughtful and reflective.",
            "heavy": "There is some weight in the feed — gentle replies may help.",
            "neutral": "A steady, even-tempered day in the feed.",
        },
        "ar": {
            "warm": "المزاج العام دافئ وكريم اليوم.",
            "curious": "الفضول هو النغمة الغالبة في التدفق.",
            "reflective": "التدفق تأملي ومتأنٍ.",
            "heavy": "هناك بعض الثقل في التدفق — الردود اللطيفة قد تساعد.",
            "neutral": "يوم هادئ ومتوازن في التدفق.",
        },
    }

    return {
        "summary": " ".join(summary_parts) or summary["summary"],
        "highlights": summary["bullets"][:2],
        "bullets": summary["bullets"],
        "themes": [{"name": word, "label": f"#{word}"} for word in themes],
        "questions": questions,
        "tone": tone,
        "mood": mood_line[language].get(tone["mood"], mood_line[language]["neutral"]),
        "stats": {
            "posts": len(texts),
            "words": word_count(corpus),
            "questions": len(questions),
            "voices": len([voice for voice in voices if voice]),
        },
        "language": language,
    }


# --------------------------------------------------------------------------- #
# Tone, sentiment & moderation
# --------------------------------------------------------------------------- #

def analyse_tone(text: str) -> dict:
    """Lexicon sentiment with intensity, mood label and writing advice."""
    language = detect_language(text)
    words = tokens(text, keep_stopwords=True)
    if not words:
        return {
            "language": language, "score": 0.0, "label": "neutral", "mood": "neutral",
            "positive": [], "negative": [], "advice": "Write freely — the assistant will follow your lead.",
        }

    positive_hits, negative_hits = [], []
    score = 0.0
    for word in words:
        if word in POSITIVE_EN:
            score += POSITIVE_EN[word]
            positive_hits.append(word)
        elif word in NEGATIVE_EN:
            score += NEGATIVE_EN[word]
            negative_hits.append(word)
        elif normalise_arabic(word) in POSITIVE_AR:
            score += POSITIVE_AR[normalise_arabic(word)]
            positive_hits.append(word)
        elif normalise_arabic(word) in NEGATIVE_AR:
            score += NEGATIVE_AR[normalise_arabic(word)]
            negative_hits.append(word)

    if SHOUTY_RE.search(_plain(text)):
        score -= 0.8
    if text.count("!") > 2:
        score -= 0.4

    normalised = clamp(score / math.sqrt(max(1, len(words))) / 2.6, -1.0, 1.0)
    if normalised >= 0.18:
        label, mood = "positive", "warm"
    elif normalised <= -0.18:
        label, mood = "negative", "heavy"
    else:
        label, mood = "neutral", "neutral"
    if normalised > -0.18 and text.count("?") and label != "negative":
        mood = "curious"
    if label == "neutral" and word_count(text) > 40:
        mood = "reflective"

    advice = {
        "warm": "Your warmth comes through — keep that opening line.",
        "curious": "Genuine curiosity reads well here. One concrete example would make it land harder.",
        "reflective": "Thoughtful and unhurried. A closing line that names the takeaway would seal it.",
        "heavy": "This carries weight. Naming one thing that helped — even a little — usually helps readers.",
        "neutral": "Clear and even. A specific detail would give readers something to hold on to.",
    }[mood if mood in {"warm", "curious", "reflective", "heavy"} else "neutral"]

    return {
        "language": language,
        "score": round(normalised, 3),
        "label": label,
        "mood": mood,
        "positive": sorted(set(positive_hits))[:6],
        "negative": sorted(set(negative_hits))[:6],
        "advice": advice,
    }


def syllables(word: str) -> int:
    """Approximate syllable count from vowel groups (English), 1 otherwise."""
    if ARABIC_RE.search(word):
        return max(1, len(re.findall(r"[\u0627\u0648\u064a\u0623\u0625\u0624\u0626]", word)))
    cleaned = re.sub(r"[^a-z]", "", word.lower())
    if not cleaned:
        return 1
    groups = re.findall(r"[aeiouy]+", cleaned)
    count = len(groups)
    if cleaned.endswith("e") and not cleaned.endswith(("le", "ee", "ye", "oe")) and count > 1:
        count -= 1
    return max(1, count)


def readability(text: str) -> dict:
    words = tokens(text, keep_stopwords=True)
    parts = sentences(text) or [text]
    word_total = max(1, len(words))
    sentences_total = max(1, len(parts))
    syllable_total = sum(syllables(word) for word in words) or word_total
    syllable_density = syllable_total / word_total
    avg_sentence = word_total / sentences_total
    # Flesch-Kincaid is calibrated for paragraphs: applied to a 10-word post it
    # calls a plain sentence "very dense". Short posts get a length-aware
    # estimate instead, and full paragraphs keep the classic formula.
    if word_total < 40:
        method = "short-text estimate"
        score = 100 - (avg_sentence - 12) * 1.2 - (syllable_density - 1.4) * 35
    else:
        method = "flesch"
        score = 206.835 - 1.015 * avg_sentence - 84.6 * syllable_density
    score = clamp(score, 0, 100)
    if score >= 70:
        level = "Very easy"
    elif score >= 60:
        level = "Easy"
    elif score >= 50:
        level = "Fairly clear"
    elif score >= 35:
        level = "A little dense"
    else:
        level = "Very dense"
    return {
        "score": round(score),
        "level": level,
        "method": method,
        "words": word_total,
        "sentences": sentences_total,
        "syllables": syllable_total,
        "avg_sentence": round(avg_sentence, 1),
    }


def moderation(text: str) -> dict:
    """Kindness pre-flight: flags shouting, absolutes and hostile phrasing."""
    body = _plain(text)
    checks: list[dict] = []
    lowered = body.lower()

    hostile = [word for word in ("stupid", "idiot", "idiotic", "moron", "pathetic", "loser", "trash",
                                 "garbage", "shut up", "hate you", "useless")
               if word in lowered] + [word for word in ("غبي", "احمق", "أحمق", "تافه", "حقير", "اخرس")
                                      if word in body]
    if hostile:
        checks.append({
            "level": "warn",
            "title": "This reads harshly",
            "message": "Words like " + ", ".join(sorted(set(hostile))[:3]) + " land hard. You can disagree without them.",
        })

    if SHOUTY_RE.search(body):
        checks.append({
            "level": "warn",
            "title": "All caps",
            "message": "Shouting in caps usually loses the audience. Sentence case reads calmer and stronger.",
        })

    if len(re.findall(r"!", body)) > 3:
        checks.append({
            "level": "info",
            "title": "Tone down the exclamations",
            "message": "One exclamation is emphasis; four is noise.",
        })

    absolutes = [phrase for phrase in ("never", "always", "everyone knows", "nobody", "أبدا", "دائما", "لا أحد")
                 if phrase in lowered or phrase in body]
    if absolutes:
        checks.append({
            "level": "info",
            "title": "Absolute claims",
            "message": "Words like " + ", ".join(sorted(set(absolutes))[:3]) + " invite arguments. Softening them keeps conversation open.",
        })

    if URL_RE.search(body):
        checks.append({
            "level": "good",
            "title": "Link detected",
            "message": "Links render as plain text here — a short description of what is behind it helps.",
        })

    if body.count("#") > 4:
        checks.append({
            "level": "info",
            "title": "Many tags",
            "message": "Four hashtags or fewer keeps the thought readable.",
        })

    if not checks:
        checks.append({
            "level": "good",
            "title": "All clear",
            "message": "Nothing to flag — this reads generously.",
        })
    return {"checks": checks, "ok": all(check["level"] != "warn" for check in checks)}


# --------------------------------------------------------------------------- #
# Rewriting
# --------------------------------------------------------------------------- #

def _capitalise(sentence: str) -> str:
    stripped = sentence.lstrip()
    if not stripped:
        return sentence
    if ARABIC_RE.search(stripped[0]):
        return sentence
    if stripped[0].islower():
        prefix = sentence[: len(sentence) - len(stripped)]
        return prefix + stripped[0].upper() + stripped[1:]
    return sentence


def _expand_abbreviations(text: str) -> str:
    def replace(match: re.Match) -> str:
        word = match.group(0)
        replacement = ABBREVIATIONS.get(word.lower())
        if not replacement:
            return word
        if word.isupper() and len(word) > 1:
            return replacement
        return replacement
    return re.sub(r"\b[A-Za-z']+\b", replace, text)


def clean_text(text: str) -> str:
    """Mechanical clean-up: spacing, punctuation, casing, contractions."""
    body = strip_control(text).replace("\r\n", "\n").strip()
    body = URL_RE.sub(lambda match: match.group(0).rstrip(".,"), body)
    body = MULTISPACE_RE.sub(" ", body)
    body = REPEATED_PUNCT_RE.sub(r"\1", body)
    body = re.sub(r"\s+([,.;:!?])", r"\1", body)
    body = re.sub(r"([,;:])(?=[^\s\d])", r"\1 ", body)
    body = re.sub(r"\.{2,}", "…", body)
    body = _expand_abbreviations(body)
    body = REPEATED_WORD_RE.sub(r"\1", body)
    body = re.sub(r"\bi\b", "I", body)
    body = re.sub(r" +", " ", body)
    body = re.sub(r"\n{3,}", "\n\n", body)
    lines = []
    for line in body.split("\n"):
        line = line.strip()
        if line:
            lines.append(_capitalise(line))
    body = "\n".join(lines).strip()
    if body and body[-1] not in ".!?…؟:؛":
        body += "."
    return body


def strip_hedges(text: str, language: str) -> str:
    body = text
    hedges = HEDGES_AR if language == "ar" else HEDGES_EN
    for hedge in sorted(hedges, key=len, reverse=True):
        pattern = r"(?<![\w\u0600-\u06FF])" + re.escape(hedge) + r"(?![\w\u0600-\u06FF])\s*"
        if language == "en":
            pattern = r"(?<![A-Za-z])" + re.escape(hedge) + r"(?![A-Za-z])\s*"
        body = re.sub(pattern, "", body, flags=re.IGNORECASE if language == "en" else 0)
    body = re.sub(r"\s{2,}", " ", body)
    return _capitalise(body.strip())


def strip_filler(text: str, language: str) -> str:
    body = text
    fillers = FILLER_AR if language == "ar" else FILLER_EN
    for filler in sorted(fillers, key=len, reverse=True):
        body = re.sub(re.escape(filler) + r"[,:]?\s*", "", body, flags=re.IGNORECASE if language == "en" else 0)
    return re.sub(r"\s{2,}", " ", body).strip()


def split_long_sentences(text: str, language: str, max_words: int = 34) -> str:
    connectors = [" and ", " but ", " so ", " because ", " which ", " while "]
    if language == "ar":
        connectors = [" و", " لكن ", " لأن ", " حيث ", " بينما "]
    output: list[str] = []
    for sentence in sentences(text) or [text]:
        words = sentence.split()
        if len(words) <= max_words:
            output.append(sentence.strip())
            continue
        cut_index = None
        running = 0
        for index, word in enumerate(words):
            running += 1
            if running < max_words // 2:
                continue
            lowered = f" {word.lower()} "
            if any(connector.strip() == word.lower() for connector in connectors if len(connector.strip()) > 2):
                cut_index = index
                break
        if cut_index is None:
            output.append(sentence.strip())
            continue
        first = " ".join(words[:cut_index]).rstrip(",;:") + "."
        second = _capitalise(" ".join(words[cut_index:]).strip())
        output.append(first)
        output.append(second)
    return " ".join(output) if len(output) <= 2 else " ".join(output)


def shorten_text(text: str, language: str, limit: int = 275) -> str:
    body = strip_filler(strip_hedges(clean_text(text), language), language)
    while len(body) > limit:
        parts = sentences(body)
        if len(parts) <= 1:
            body = body[: limit - 1].rstrip(" ,;:-") + "…"
            break
        parts = parts[:-1]
        body = " ".join(parts)
    return body


def expand_text(text: str, language: str) -> str:
    base = clean_text(text)
    top = keywords(base, 3) or (["this idea"] if language == "en" else ["هذه الفكرة"])
    theme = top[0]
    if language == "ar":
        additions = [
            f"ما غيّر تفكيري هو {theme} — عندما بدأت ألاحظه، تغيّرت التفاصيل الصغيرة كذلك.",
            "الجزء الذي يغفل عنه الناس عادة هو أن الأثر يتراكم بهدوء قبل أن يظهر.",
            "لو بدأت اليوم، لبدأت بأصغر خطوة ممكنة وكررتها بدل أن أنتظر اللحظة المثالية.",
        ]
    else:
        additions = [
            f"What changed my thinking was {theme} — once I noticed it, the small details shifted too.",
            "The part people usually miss is that the effect compounds quietly long before it shows.",
            "If I started today, I would take the smallest possible step and repeat it instead of waiting for the perfect moment.",
        ]
    return base + "\n\n" + " ".join(additions)


def improve(text: str, style: str = "polish") -> str:
    """Deterministic rewrites: polish, sharpen, warm, bold, structure."""
    language = detect_language(text)
    body = clean_text(text)
    body = split_long_sentences(body, language)

    if style == "sharpen":
        body = strip_filler(body, language)
        body = re.sub(r"\b(i think that|i believe that|i feel like)\b\s*", "", body, flags=re.IGNORECASE)
        if language == "ar":
            body = re.sub(r"(أعتقد أن|أظن أن|أشعر أن)\s*", "", body)
        body = _capitalise(body.strip())
    elif style == "warm":
        closing = ("Thank you for reading — I would love to hear how this lands for you."
                   if language == "en" else
                   "شكرا لقراءتك — يسعدني أن أعرف كيف وصلت إليك هذه الفكرة.")
        if closing not in body:
            body = body.rstrip() + "\n\n" + closing
    elif style == "bold":
        body = strip_hedges(body, language)
        if language == "ar":
            opener = f"الخلاصة: {keywords(body, 1)[0] if keywords(body, 1) else 'الفكرة'} تستحق أن تُقال بوضوح."
        else:
            body = re.sub(r"\bjust\b\s*", "", body, flags=re.IGNORECASE)
            opener = "Here is the honest version:"
        if len(tokens(body)) > 8 and not body.startswith(opener):
            body = f"{opener} {body}"
    elif style == "structure":
        parts = sentences(body)
        if len(parts) >= 3:
            bullets = "\n".join(f"• {_capitalise(part.strip().rstrip('.'))}" for part in parts[:5])
            body = f"{_capitalise(parts[0].strip())}\n\n{bullets}"
    return re.sub(r"\n{3,}", "\n\n", body).strip()


def rewrite_variants(text: str) -> list[dict]:
    """A small menu of rewrites the author can accept with one click."""
    language = detect_language(text)
    base = clean_text(text)
    short = shorten_text(text, language)
    long = expand_text(text, language)
    variants = [
        {"id": "polish", "label": "Polished", "text": base, "note": "Spacing, punctuation and casing cleaned."},
        {"id": "sharpen", "label": "Sharper", "text": improve(text, "sharpen"), "note": "Filler and soft openers removed."},
        {"id": "warm", "label": "Warmer", "text": improve(text, "warm"), "note": "Adds a generous closing line."},
        {"id": "bold", "label": "Bolder", "text": improve(text, "bold"), "note": "Hedges stripped, position stated first."},
    ]
    if len(short) >= 20:
        variants.insert(1, {"id": "short", "label": "Shorter", "text": short, "note": "Trimmed to the essentials."})
    if len(long) > len(base) + 40:
        variants.append({"id": "expand", "label": "Developed", "text": long, "note": "Two reflective sentences added."})
    variants.append({"id": "structure", "label": "Structured", "text": improve(text, "structure"), "note": "Turns a ramble into a lead + bullets."})

    seen: set[str] = set()
    unique: list[dict] = []
    for variant in variants:
        fingerprint = variant["text"].strip()
        if not fingerprint or fingerprint in seen:
            continue
        seen.add(fingerprint)
        unique.append(variant)
    return unique


# --------------------------------------------------------------------------- #
# Smart replies
# --------------------------------------------------------------------------- #

def classify_intent(text: str) -> str:
    lowered = _plain(text).lower()
    scored: list[tuple[int, str]] = []
    for intent, markers in INTENTS.items():
        hits = sum(1 for marker in markers if marker in lowered)
        scored.append((hits, intent))
    scored.sort(key=lambda item: -item[0])
    best_hits, best_intent = scored[0]
    if best_hits == 0:
        return "general"
    return best_intent


def suggest_replies(text: str, limit: int = 3, *, language: str | None = None) -> dict:
    language = language or detect_language(text)
    intent = classify_intent(text)
    theme_pool = keywords(text, 4)
    if not theme_pool:
        theme_pool = ["this"] if language == "en" else ["هذا"]
    templates = REPLY_TEMPLATES.get(language, REPLY_TEMPLATES["en"]).get(intent) or REPLY_TEMPLATES[language]["general"]

    suggestions = []
    for index, template in enumerate(templates[:limit]):
        keyword = theme_pool[index % len(theme_pool)]
        suggestions.append({
            "text": template.format(keyword=keyword),
            "intent": intent,
            "label": {
                "question": "Answer", "celebration": "Celebrate", "struggle": "Support",
                "idea": "Build on it", "thanks": "Acknowledge", "opinion": "Nuance", "general": "Connect",
            }.get(intent, "Connect"),
        })
    return {"suggestions": suggestions, "intent": intent, "language": language, "themes": theme_pool}


# --------------------------------------------------------------------------- #
# Ranking: BM25 search, related posts, recommendations
# --------------------------------------------------------------------------- #

def bm25_scores(query: str, documents: list[str], *, k1: float = 1.5, b: float = 0.75) -> list[float]:
    tokenised = [tokens(document) for document in documents]
    query_tokens = tokens(query)
    if not query_tokens or not tokenised:
        return [0.0 for _ in documents]

    lengths = [len(doc) for doc in tokenised]
    average_length = sum(lengths) / max(1, len(lengths)) or 1.0
    document_frequency: Counter = Counter()
    for doc in tokenised:
        document_frequency.update(set(doc))
    total_docs = len(tokenised)

    scores: list[float] = []
    for doc in tokenised:
        term_frequency = Counter(doc)
        score = 0.0
        for term in query_tokens:
            frequency = term_frequency.get(term, 0)
            if not frequency:
                partial = [token for token in term_frequency if term in token or token in term]
                frequency = sum(term_frequency[token] for token in partial) * 0.55
            if not frequency:
                continue
            df = document_frequency.get(term, 0) or 1
            idf = math.log(1 + (total_docs - df + 0.5) / (df + 0.5))
            denominator = frequency + k1 * (1 - b + b * (len(doc) / average_length))
            score += idf * (frequency * (k1 + 1)) / (denominator or 1)
        scores.append(round(score, 4))
    return scores


def rank_documents(query: str, documents: list[dict], *, text_key: str = "text") -> list[dict]:
    """Attach a relevance score and order best-first (stable for ties)."""
    corpus = [_plain(document.get(text_key, "")) for document in documents]
    scores = bm25_scores(query, corpus)
    decorated = []
    for index, document in enumerate(documents):
        enriched = dict(document)
        enriched["score"] = scores[index]
        decorated.append((scores[index], -index, enriched))
    decorated.sort(key=lambda item: (-item[0], -item[1]))
    return [item[2] for item in decorated]


def related_posts(target_text: str, candidates: list[dict], limit: int = 3) -> list[dict]:
    """Content-based neighbours for a thought (TF-IDF cosine-ish via BM25)."""
    pool = [candidate for candidate in candidates if candidate.get("text")]
    if not pool or not _plain(target_text).strip():
        return []
    target_keywords = set(keywords(target_text, 12))
    scored = []
    for candidate in pool:
        candidate_keywords = set(keywords(candidate["text"], 12))
        overlap = len(target_keywords & candidate_keywords)
        lexical = bm25_scores(target_text, [candidate["text"]])[0]
        engagement = float(candidate.get("engagement") or 0)
        scored.append((overlap * 1.25 + lexical + math.log1p(engagement) * 0.35, candidate))
    scored.sort(key=lambda item: -item[0])
    return [candidate for score, candidate in scored[:limit] if score > 0.35]


def search_insights(query: str, results: list[dict]) -> dict:
    """Explain *why* results matched and offer follow-up angles."""
    query_tokens = set(tokens(query))
    corpus = " ".join(_plain(result.get("text", "")) for result in results)
    related_terms = [word for word in keywords(corpus, 8) if word not in query_tokens][:5]
    if results:
        sentence = ("Found {n} related thought{s}. Closest angles: {terms}.").format(
            n=len(results), s="" if len(results) == 1 else "s",
            terms=", ".join(related_terms) or "the exact wording you used",
        )
    else:
        sentence = "Nothing matched yet — try a single distinctive word, a name, or a topic tag."
    return {
        "summary": sentence,
        "query_keywords": sorted(query_tokens)[:6],
        "related_terms": related_terms,
    }


def suggest_people(actor, candidates, *, limit: int = 4, following_ids=None, affinity=None) -> list[dict]:
    """Rank accounts the viewer does not follow yet.

    ``candidates`` is an iterable of dicts with ``id``, ``handle``,
    ``display_name``, ``avatar_initial``, ``avatar_tone``, ``avatar_url``,
    ``verified``, ``followers``, ``posts``, ``topics`` (set of topic names) and
    ``reason``.  Scoring blends topic affinity, social proof, activity and a
    little serendipity so the rail never shows the same order twice.
    """
    following_ids = set(following_ids or [])
    affinity = affinity or {}
    scored = []
    for candidate in candidates:
        if candidate.get("id") in following_ids:
            continue
        if actor is not None and candidate.get("id") == getattr(actor, "id", None):
            continue
        overlap = len(set(candidate.get("topics") or []) & set(affinity.keys()))
        shared_weight = sum(affinity.get(topic, 0) for topic in (candidate.get("topics") or []))
        followers = float(candidate.get("followers") or 0)
        posts = float(candidate.get("posts") or 0)
        score = overlap * 2.4 + math.log1p(shared_weight) * 1.6 + math.log1p(followers) * 0.7 + math.log1p(posts) * 0.45
        if candidate.get("verified"):
            score += 0.25
        if score <= 0:
            score = 0.05
        reason = candidate.get("reason") or (
            "Shares your interest in " + ", ".join(list(affinity.keys())[:1]) if affinity else "Active in the space"
        )
        if overlap == 0 and not candidate.get("reason"):
            reason = "New voice in the space"
        scored.append((score, reason, candidate))
    scored.sort(key=lambda item: -item[0])
    output = []
    for score, reason, candidate in scored[:limit]:
        enriched = dict(candidate)
        enriched["reason"] = reason
        enriched["match"] = round(min(0.99, score / 8), 2)
        output.append(enriched)
    return output


def suggest_topics(posts, topics, *, limit: int = 5) -> list[dict]:
    """Rank topics by recent activity, engagement and momentum."""
    from collections import defaultdict

    stats = defaultdict(lambda: {"posts": 0, "engagement": 0, "recent": 0, "sample": []})
    now = datetime.now(dt_timezone.utc)
    for post in posts:
        topic = getattr(post, "topic", None)
        name = getattr(topic, "name", None)
        if not name:
            continue
        bucket = stats[name]
        bucket["posts"] += 1
        engagement = (getattr(post, "likes", 0) or 0) + (getattr(post, "reposts", 0) or 0) * 2 + (getattr(post, "replies", 0) or 0)
        bucket["engagement"] += engagement
        published = getattr(post, "published_at", None)
        if published and (now - published).total_seconds() < 86400:
            bucket["recent"] += 1
        if len(bucket["sample"]) < 2 and getattr(post, "body", ""):
            bucket["sample"].append(post.body)

    meta = {getattr(topic, "name", ""): topic for topic in topics}
    ranked = []
    for name, bucket in stats.items():
        topic = meta.get(name)
        score = bucket["posts"] * 1.0 + math.log1p(bucket["engagement"]) * 1.5 + bucket["recent"] * 1.4
        ranked.append((score, name, bucket, topic))
    if not ranked:
        for topic in topics:
            ranked.append((float(getattr(topic, "rank", 1)), getattr(topic, "name", ""), {"posts": 0, "engagement": 0, "recent": 0, "sample": []}, topic))
    ranked.sort(key=lambda item: -item[0])

    output = []
    for score, name, bucket, topic in ranked[:limit]:
        output.append({
            "name": name,
            "category": getattr(topic, "category", "Trending") if topic else "Trending",
            "posts": bucket["posts"],
            "engagement": bucket["engagement"],
            "momentum": "rising" if bucket["recent"] else "steady",
            "score": round(score, 2),
            "sample": bucket["sample"][0][:140] if bucket["sample"] else "",
            "meta": f"{bucket['posts']} post" if bucket["posts"] == 1 else f"{bucket['posts']} posts",
        })
    return output


# --------------------------------------------------------------------------- #
# Idea prompts & the `assist` dispatcher
# --------------------------------------------------------------------------- #

TOPIC_CATEGORIES = {
    "Design": {"design", "type", "typography", "colour", "color", "layout", "brand", "ui", "ux", "grid",
               "تصميم", "الوان", "ألوان", "خط", "تنسيق", "هوية"},
    "Technology": {"code", "coding", "software", "python", "javascript", "django", "api", "server", "ai",
                   "model", "data", "database", "app", "برمجة", "تقنية", "بيانات", "تطبيق", "ذكاء"},
    "Writing": {"write", "writing", "essay", "draft", "poem", "poetry", "book", "words", "story", "journal",
                "كتابة", "مقال", "قصيدة", "كتاب", "شعر", "مذكرات"},
    "Philosophy": {"meaning", "ethics", "truth", "stoic", "philosophy", "existence", "wisdom", "doubt",
                   "فلسفة", "معنى", "حكمة", "اخلاق", "أخلاق", "وجود"},
    "Science": {"science", "physics", "biology", "space", "research", "study", "experiment", "climate",
                "علم", "فيزياء", "بحث", "تجربة", "مناخ", "فضاء"},
    "Wellbeing": {"rest", "sleep", "health", "calm", "meditation", "walk", "breath", "healing", "therapy",
                  "راحة", "صحة", "هدوء", "تأمل", "سكينة", "شفاء"},
    "Work": {"work", "career", "team", "startup", "product", "meeting", "focus", "craft", "practice",
             "عمل", "فريق", "مشروع", "مهنة", "تركيز", "حرفة"},
    "Culture": {"music", "film", "art", "city", "cities", "history", "language", "tradition", "poetry",
                "موسيقى", "فيلم", "فن", "مدينة", "تاريخ", "لغة", "تراث"},
    "Learning": {"learn", "learning", "school", "university", "teacher", "student", "lesson", "practice",
                 "تعلم", "دراسة", "جامعة", "معلم", "طالب", "درس"},
    "Community": {"community", "kindness", "friend", "friendship", "family", "neighbour", "volunteer",
                  "مجتمع", "لطف", "صديق", "صداقة", "عائلة", "جار"},
}


def categorise_topic(name: str, text: str = "") -> str:
    """Pick a friendly category for a tag using bilingual keyword overlap."""
    haystack = f"{name} {text}".lower()
    words = set(tokens(haystack, keep_stopwords=True))
    best, best_score = "Trending", 0
    for category, markers in TOPIC_CATEGORIES.items():
        score = sum(1 for marker in markers if marker in haystack or marker in words)
        if score > best_score:
            best, best_score = category, score
    return best


def writing_prompts(recent_keywords: list[str] | None = None, language: str = "en", limit: int = 3) -> list[str]:
    language = language if language in PROMPTS else "en"
    pool = list(PROMPTS[language])
    recent_keywords = [word for word in (recent_keywords or []) if word]
    if recent_keywords:
        theme = recent_keywords[0]
        if language == "ar":
            pool.insert(0, f"اكتب عن {theme} كما لو أنك تشرحه لصديق لم يسمع به من قبل.")
        else:
            pool.insert(0, f"Write about {theme} as if you were explaining it to a friend who has never heard of it.")
    pick = pool[:limit]
    return pick


# --------------------------------------------------------------------------- #
# Live compose assistance: continuation, draft score and the inline nudge
# --------------------------------------------------------------------------- #

CONNECTOR_COMPLETIONS = {
    "and": "that is the part I want to keep.",
    "but": "the interesting part is what happens next.",
    "because": "it changes how the work feels, not just how fast it goes.",
    "so": "the next step is smaller than it looks.",
    "when": "everything else gets quieter.",
    "while": "the rest of it takes care of itself.",
    "if": "the whole thing changes shape.",
    "that": "is the version I keep returning to.",
    "which": "is why it stayed with me.",
    "then": "the obvious next question shows up.",
    "or": "nothing in between.",
    "with": "a little more care than the last time.",
    "to": "make room for the thought to finish itself.",
    "of": "the same idea, said more simply.",
    "in": "the smallest possible way.",
}

MOOD_COMPLETIONS = {
    "warm": [
        "I am keeping this one close.",
        "That is the part worth sharing.",
        "It made the day better, and I wanted to say so.",
    ],
    "curious": [
        "I would love to hear how others handle it.",
        "There is something here I have not figured out yet.",
        "If you have tried this, I want to know what happened.",
    ],
    "reflective": [
        "I am still sitting with that.",
        "It took a while to notice, and now I cannot unsee it.",
        "The quiet version of this is the one that lasted.",
    ],
    "heavy": [
        "Writing it down made it a little lighter.",
        "Naming it is the first honest step.",
        "I do not have the answer yet, only the question.",
    ],
    "neutral": [
        "Worth writing down before it fades.",
        "Small thing, but it changed the day.",
        "Still turning it over.",
    ],
}


def _last_word(text: str) -> str:
    words = re.findall(r"[A-Za-z\u0600-\u06FF']+", text or "")
    return words[-1].lower() if words else ""


def continuation(text: str, *, language: str | None = None) -> dict:
    """One suggested next sentence for a draft (accept with Tab)."""
    body = (text or "").rstrip()
    if not body:
        return {"text": "", "label": "", "reason": "Start typing and the assistant will follow your lead."}
    language = language or detect_language(body)
    tone = analyse_tone(body)
    mood = tone["mood"] if tone["mood"] in MOOD_COMPLETIONS else "neutral"
    trailing = body[-1]

    if trailing == "?":
        suggestion = "The honest answer is that I am still learning."
        label = "Continue the question"
    elif trailing == ":":
        suggestion = "First, the part nobody writes about."
        label = "Start the list"
    elif trailing == ",":
        suggestion = "and that is what made it stick."
        label = "Finish the thought"
    else:
        connector = _last_word(body)
        if connector in CONNECTOR_COMPLETIONS:
            suggestion = CONNECTOR_COMPLETIONS[connector]
            label = "Complete the sentence"
        else:
            options = MOOD_COMPLETIONS[mood]
            suggestion = options[len(body) % len(options)]
            label = "Suggested closing line"

    return {
        "text": suggestion,
        "label": label,
        "reason": f"Follows the {mood} tone of your draft.",
    }


def draft_score(text: str, tone: dict | None = None, reading: dict | None = None, tags=None) -> int:
    """A friendly, explainable 0-100 read on how ready a draft is."""
    body = (text or "").strip()
    if not body:
        return 0
    tone = tone or analyse_tone(body)
    reading = reading or readability(body)
    tags = list(tags or [])
    words = reading["words"]
    score = 48
    if 12 <= words <= 60:
        score += 14
    elif words < 12:
        score += 4
    elif words <= 120:
        score += 8
    if reading["avg_sentence"] <= 22:
        score += 10
    if body[-1:] in {".", "?", "!"}:
        score += 6
    if "?" in body:
        score += 4
    if tags:
        score += 6
    if tone["label"] == "negative":
        score -= 6
    if SHOUTY_RE.search(_plain(body)):
        score -= 8
    if len(HASHTAG_RE.findall(body)) > 4:
        score -= 4
    return int(clamp(score, 0, 100))


def compose_hints(text: str, *, extra_corpus: list[str] | None = None) -> dict:
    """Everything the composer needs for inline, as-you-type assistance."""
    body = (text or "").strip()
    language = detect_language(body)
    tone = analyse_tone(body)
    reading = readability(body)
    tags = meaningful_tags(body, 4, extra_corpus=extra_corpus)
    words = reading["words"]

    notes: list[str] = []
    if words < 8:
        notes.append("Keep going — a thought usually needs one more sentence.")
    if reading["avg_sentence"] > 26:
        notes.append("This sentence is long; a full stop would give it air.")
    if words >= 12 and not tags:
        notes.append("A single tag would help this find its circle.")
    if tone["label"] == "negative" and "!" in body:
        notes.append("Loud punctuation can swallow the point — try it calm once.")
    if not notes:
        notes.append(tone["advice"])

    return {
        "language": language,
        "tone": tone,
        "readability": reading,
        "hashtags": tags,
        "keywords": keywords(body, 6, extra_corpus=extra_corpus),
        "continuation": continuation(body, language=language),
        "notes": notes,
        "nudge": notes[0],
        "score": draft_score(body, tone, reading, tags),
        "words": words,
        "status": "empty" if not body else ("short" if words < 8 else "ready"),
    }


def coach(text: str, *, extra_corpus: list[str] | None = None) -> dict:
    """Full pre-publish read of a draft: tone, clarity, tags and checks."""
    language = detect_language(text)
    tone = analyse_tone(text)
    reading = readability(text)
    checks = moderation(text)["checks"]
    suggested_tags = hashtags(text, 4, extra_corpus=extra_corpus)
    notes = [tone["advice"]]
    if reading["avg_sentence"] > 26:
        notes.append("Some sentences are long — splitting one of them will make this easier to read.")
    if reading["words"] < 12:
        notes.append("Short and clean. One concrete detail would give readers a handle.")
    if not HASHTAG_RE.search(text) and suggested_tags:
        notes.append("Adding one or two tags helps this thought find its circle.")
    return {
        "language": language,
        "tone": tone,
        "readability": reading,
        "checks": checks,
        "hashtags": suggested_tags,
        "keywords": keywords(text, 6, extra_corpus=extra_corpus),
        "notes": notes,
        "title": title_for(text),
        "continuation": continuation(text, language=language),
        "score": draft_score(text, tone, reading, suggested_tags),
    }


def assist(action: str, text: str, *, context: dict | None = None) -> dict:
    """Single entry point used by ``/api/ai/<action>/``."""
    action = (action or "coach").strip().lower()
    context = context or {}
    extra_corpus = [str(item) for item in context.get("corpus", []) if item][:60]
    text = _plain(text)
    language = detect_language(text) or "en"

    if action in {"improve", "rewrite", "write"}:
        variants = rewrite_variants(text)
        return {
            "action": "improve",
            "language": language,
            "summary": "Rewrites that keep your voice but sharpen the delivery.",
            "suggestions": [{"id": variant["id"], "label": variant["label"], "text": variant["text"], "note": variant["note"]}
                            for variant in variants],
            "keywords": keywords(text, 6),
            "hashtags": hashtags(text, 4),
        }

    if action in {"hashtags", "tags"}:
        tags = hashtags(text, 5, extra_corpus=extra_corpus)
        return {
            "action": "hashtags",
            "language": language,
            "summary": "Tags picked from the ideas actually inside your draft.",
            "hashtags": tags,
            "keywords": keywords(text, 8, extra_corpus=extra_corpus),
            "suggestions": [{"id": f"tag-{index}", "label": f"#{tag}", "text": tag, "note": "Suggested tag"} for index, tag in enumerate(tags)],
        }

    if action in {"tone", "sentiment"}:
        tone = analyse_tone(text)
        return {
            "action": "tone",
            "language": language,
            "summary": tone["advice"],
            "tone": tone,
            "notes": [tone["advice"]],
            "suggestions": [],
        }

    if action in {"moderate", "check", "safety"}:
        result = moderation(text)
        return {
            "action": "moderate",
            "language": language,
            "summary": "Pre-flight read of your draft." if result["ok"] else "A couple of things worth softening.",
            "checks": result["checks"],
            "safe": result["ok"],
            "suggestions": [],
        }

    if action in {"shorten", "condense"}:
        shortened = shorten_text(text, language)
        return {
            "action": "shorten",
            "language": language,
            "summary": "Trimmed to the essentials.",
            "suggestions": [{"id": "short", "label": "Shortened", "text": shortened, "note": f"{len(shortened)} characters"}],
        }

    if action in {"expand", "develop"}:
        expanded = expand_text(text, language)
        return {
            "action": "expand",
            "language": language,
            "summary": "Two reflective sentences to develop the thought.",
            "suggestions": [{"id": "expand", "label": "Developed", "text": expanded, "note": "Adds depth without changing your point"}],
        }

    if action in {"title", "headline"}:
        return {
            "action": "title",
            "language": language,
            "summary": "A headline pulled from your strongest line.",
            "suggestions": [{"id": "title", "label": "Headline", "text": title_for(text), "note": "Useful for long thoughts"}],
        }

    if action in {"prompts", "ideas"}:
        prompt_list = writing_prompts(context.get("keywords"), language, 4)
        return {
            "action": "prompts",
            "language": language,
            "summary": "Prompts to help you start from somewhere real.",
            "prompts": prompt_list,
            "suggestions": [{"id": f"prompt-{index}", "label": "Prompt", "text": prompt, "note": "Tap to start writing"}
                            for index, prompt in enumerate(prompt_list)],
        }

    if action in {"reply", "replies"}:
        result = suggest_replies(text, 3, language=language)
        return {
            "action": "reply",
            "language": language,
            "summary": "Three ways to respond, matched to the mood of the thought.",
            "intent": result["intent"],
            "themes": result["themes"],
            "suggestions": [{"id": f"reply-{index}", "label": suggestion["label"], "text": suggestion["text"], "note": "Tap to use"}
                            for index, suggestion in enumerate(result["suggestions"])],
        }

    if action in {"compose", "hints", "live"}:
        hints = compose_hints(text, extra_corpus=extra_corpus)
        checks = moderation(text)["checks"]
        return {
            "action": "compose",
            "language": hints["language"],
            "summary": hints["nudge"],
            "tone": hints["tone"],
            "readability": hints["readability"],
            "checks": checks,
            "hashtags": hints["hashtags"],
            "keywords": hints["keywords"],
            "continuation": hints["continuation"],
            "notes": hints["notes"],
            "nudge": hints["nudge"],
            "score": hints["score"],
            "words": hints["words"],
            "status": hints["status"],
            "suggestions": [],
        }

    if action in {"summary", "summarise", "summarize", "digest"}:
        posts = context.get("texts") or [text]
        result = summarize(posts, 3, language=language)
        return {
            "action": "summary",
            "language": language,
            "summary": result["summary"],
            "bullets": result["bullets"],
            "keywords": result["keywords"],
            "suggestions": [],
        }

    # Default: coach — the full read-out.
    result = coach(text, extra_corpus=extra_corpus)
    return {
        "action": "coach",
        "language": result["language"],
        "summary": result["notes"][0] if result["notes"] else "Here is how this draft reads.",
        "tone": result["tone"],
        "readability": result["readability"],
        "checks": result["checks"],
        "hashtags": result["hashtags"],
        "keywords": result["keywords"],
        "notes": result["notes"],
        "title": result["title"],
        "suggestions": [],
    }


# --------------------------------------------------------------------------- #
# Optional hosted model (any OpenAI-compatible endpoint)
# --------------------------------------------------------------------------- #

def _api_key() -> str:
    return os.getenv("AI_API_KEY") or os.getenv("OPENAI_API_KEY") or ""


def _base_url() -> str:
    return (os.getenv("AI_BASE_URL") or os.getenv("OPENAI_BASE_URL") or "https://api.openai.com/v1").rstrip("/")


def _model() -> str:
    return os.getenv("AI_MODEL") or "gpt-4o-mini"


def provider_info() -> dict:
    if _api_key():
        return {"provider": "hosted", "model": _model(), "endpoint": _base_url(), "local_engine": True}
    return {"provider": "athar-local", "model": "athar-nlp-v1", "endpoint": "", "local_engine": True}


def remote_complete(system_prompt: str, user_prompt: str, *, timeout: float = 12.0, max_tokens: int = 420) -> str | None:
    """Call an OpenAI-compatible chat endpoint. Returns ``None`` on any failure."""
    key = _api_key()
    if not key:
        return None

    payload = json.dumps({
        "model": _model(),
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.6,
        "max_tokens": max_tokens,
    }).encode("utf-8")

    request = urllib.request.Request(
        f"{_base_url()}/chat/completions",
        data=payload,
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = json.loads(response.read().decode("utf-8"))
        choices = body.get("choices") or []
        if not choices:
            return None
        content = choices[0].get("message", {}).get("content")
        return content.strip() if isinstance(content, str) and content.strip() else None
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, ValueError, OSError, json.JSONDecodeError):
        return None


def hosted_rewrites(text: str, language: str) -> list[dict] | None:
    """Three hosted rewrites, or ``None`` when no hosted model is available."""
    if not _api_key() or not text.strip():
        return None
    system = (
        "You are Athar's writing assistant for a calm social space. "
        "Rewrite the user's thought three ways: polished, shorter, and warmer. "
        "Keep the author's voice, never add facts, never use hashtags, no markdown. "
        "Reply with three lines, each starting with 'POLISHED:', 'SHORTER:' or 'WARMER:', in "
        + ("Arabic." if language == "ar" else "English.")
    )
    content = remote_complete(system, text, max_tokens=500)
    if not content:
        return None
    labels = {"POLISHED": ("polish", "Polished", "Hosted model rewrite"),
              "SHORTER": ("short", "Shorter", "Hosted model rewrite"),
              "WARMER": ("warm", "Warmer", "Hosted model rewrite")}
    output = []
    for line in content.splitlines():
        line = line.strip()
        for prefix, (identifier, label, note) in labels.items():
            if line.upper().startswith(prefix + ":"):
                value = line.split(":", 1)[1].strip()
                if value:
                    output.append({"id": identifier, "label": label, "text": value, "note": note, "source": "hosted"})
    return output or None


def enrich_with_hosted(action: str, text: str, payload: dict) -> dict:
    """Optionally upgrade a local payload with hosted suggestions (best effort)."""
    if not _api_key() or not text.strip():
        payload["provider"] = "athar-local"
        return payload
    hosted = None
    if action in {"improve", "rewrite", "write", "coach"}:
        hosted = hosted_rewrites(text, payload.get("language", "en"))
    if hosted:
        existing = {suggestion["text"].strip() for suggestion in payload.get("suggestions", [])}
        merged = list(payload.get("suggestions", []))
        merged.extend(item for item in hosted if item["text"].strip() not in existing)
        payload["suggestions"] = merged
        payload["provider"] = f"hosted:{_model()}"
    else:
        payload["provider"] = "athar-local"
    return payload
