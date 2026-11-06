"""Language list (taken from the browser extension).

The configured AI model decides what it can really translate, so the user can
also type any language name; it is stored as a "custom:" language code.
"""
from __future__ import annotations

import re
import unicodedata
from typing import NamedTuple

AUTO = "auto"
NONE = "none"  # target meaning "do not translate, only apply the tone"
CUSTOM_PREFIX = "custom:"


class Language(NamedTuple):
    code: str
    name: str
    native: str


_RAW = [
    ("af", "Afrikaans", "Afrikaans"),
    ("sq", "Albanian", "Shqip"),
    ("am", "Amharic", "አማርኛ"),
    ("ar", "Arabic", "العربية"),
    ("hy", "Armenian", "Հայերեն"),
    ("as", "Assamese", "অসমীয়া"),
    ("az", "Azerbaijani", "Azərbaycan"),
    ("eu", "Basque", "Euskara"),
    ("be", "Belarusian", "Беларуская"),
    ("bn", "Bengali", "বাংলা"),
    ("bs", "Bosnian", "Bosanski"),
    ("bg", "Bulgarian", "Български"),
    ("my", "Burmese", "မြန်မာ"),
    ("ca", "Catalan", "Català"),
    ("ceb", "Cebuano", "Cebuano"),
    ("zh-CN", "Chinese (Simplified)", "简体中文"),
    ("zh-TW", "Chinese (Traditional)", "繁體中文"),
    ("hr", "Croatian", "Hrvatski"),
    ("cs", "Czech", "Čeština"),
    ("da", "Danish", "Dansk"),
    ("nl", "Dutch", "Nederlands"),
    ("en", "English", "English"),
    ("eo", "Esperanto", "Esperanto"),
    ("et", "Estonian", "Eesti"),
    ("fil", "Filipino", "Filipino"),
    ("fi", "Finnish", "Suomi"),
    ("fr", "French", "Français"),
    ("gl", "Galician", "Galego"),
    ("ka", "Georgian", "ქართული"),
    ("de", "German", "Deutsch"),
    ("el", "Greek", "Ελληνικά"),
    ("gu", "Gujarati", "ગુજરાતી"),
    ("ht", "Haitian Creole", "Kreyòl ayisyen"),
    ("ha", "Hausa", "Hausa"),
    ("haw", "Hawaiian", "ʻŌlelo Hawaiʻi"),
    ("he", "Hebrew", "עברית"),
    ("hi", "Hindi", "हिन्दी"),
    ("hu", "Hungarian", "Magyar"),
    ("is", "Icelandic", "Íslenska"),
    ("ig", "Igbo", "Igbo"),
    ("id", "Indonesian", "Bahasa Indonesia"),
    ("ga", "Irish", "Gaeilge"),
    ("it", "Italian", "Italiano"),
    ("ja", "Japanese", "日本語"),
    ("jv", "Javanese", "Basa Jawa"),
    ("kn", "Kannada", "ಕನ್ನಡ"),
    ("kk", "Kazakh", "Қазақша"),
    ("km", "Khmer", "ខ្មែរ"),
    ("rw", "Kinyarwanda", "Kinyarwanda"),
    ("ko", "Korean", "한국어"),
    ("ku", "Kurdish", "Kurdî"),
    ("ky", "Kyrgyz", "Кыргызча"),
    ("lo", "Lao", "ລາວ"),
    ("la", "Latin", "Latina"),
    ("lv", "Latvian", "Latviešu"),
    ("lt", "Lithuanian", "Lietuvių"),
    ("lb", "Luxembourgish", "Lëtzebuergesch"),
    ("mk", "Macedonian", "Македонски"),
    ("mg", "Malagasy", "Malagasy"),
    ("ms", "Malay", "Bahasa Melayu"),
    ("ml", "Malayalam", "മലയാളം"),
    ("mt", "Maltese", "Malti"),
    ("mi", "Maori", "Māori"),
    ("mr", "Marathi", "मराठी"),
    ("mn", "Mongolian", "Монгол"),
    ("ne", "Nepali", "नेपाली"),
    ("no", "Norwegian", "Norsk"),
    ("or", "Odia", "ଓଡ଼ିଆ"),
    ("ps", "Pashto", "پښتو"),
    ("fa", "Persian", "فارسی"),
    ("pl", "Polish", "Polski"),
    ("pt-BR", "Portuguese (Brazil)", "Português (Brasil)"),
    ("pt-PT", "Portuguese (Portugal)", "Português (Portugal)"),
    ("pa", "Punjabi", "ਪੰਜਾਬੀ"),
    ("ro", "Romanian", "Română"),
    ("ru", "Russian", "Русский"),
    ("sm", "Samoan", "Gagana Samoa"),
    ("gd", "Scottish Gaelic", "Gàidhlig"),
    ("sr", "Serbian", "Српски"),
    ("sn", "Shona", "chiShona"),
    ("sd", "Sindhi", "سنڌي"),
    ("si", "Sinhala", "සිංහල"),
    ("sk", "Slovak", "Slovenčina"),
    ("sl", "Slovenian", "Slovenščina"),
    ("so", "Somali", "Soomaali"),
    ("es", "Spanish", "Español"),
    ("su", "Sundanese", "Basa Sunda"),
    ("sw", "Swahili", "Kiswahili"),
    ("sv", "Swedish", "Svenska"),
    ("tg", "Tajik", "Тоҷикӣ"),
    ("ta", "Tamil", "தமிழ்"),
    ("tt", "Tatar", "Татарча"),
    ("te", "Telugu", "తెలుగు"),
    ("th", "Thai", "ไทย"),
    ("tr", "Turkish", "Türkçe"),
    ("tk", "Turkmen", "Türkmen"),
    ("uk", "Ukrainian", "Українська"),
    ("ur", "Urdu", "اردو"),
    ("ug", "Uyghur", "ئۇيغۇرچە"),
    ("uz", "Uzbek", "Oʻzbek"),
    ("vi", "Vietnamese", "Tiếng Việt"),
    ("cy", "Welsh", "Cymraeg"),
    ("xh", "Xhosa", "isiXhosa"),
    ("yi", "Yiddish", "ייִדיש"),
    ("yo", "Yoruba", "Yorùbá"),
    ("zu", "Zulu", "isiZulu"),
]

LANGUAGES: list[Language] = [Language(*row) for row in _RAW]
_BY_CODE = {lang.code: lang for lang in LANGUAGES}

LANGUAGE_CODE_RE = re.compile(r"^(auto|[A-Za-z]{2,3}(-[A-Za-z0-9]{2,8})*|custom:.{1,40})$")


def is_valid_language_code(code: object) -> bool:
    return isinstance(code, str) and LANGUAGE_CODE_RE.match(code) is not None


def is_valid_target_code(code: object) -> bool:
    """A target may also be NONE ("No translation"), but never AUTO."""
    return code == NONE or (is_valid_language_code(code) and code != AUTO)


def make_custom_language_code(name: str) -> str:
    return CUSTOM_PREFIX + name.strip()[:40]


def find_language(code: str) -> Language | None:
    return _BY_CODE.get(code)


def language_name(code: str) -> str:
    """English display name (this is also what is sent to the model)."""
    if code == AUTO:
        return "Detect language"
    if code == NONE:
        return "No translation"
    if code.startswith(CUSTOM_PREFIX):
        return code[len(CUSTOM_PREFIX):]
    lang = _BY_CODE.get(code)
    return lang.name if lang else code


def _normalize(s: str) -> str:
    decomposed = unicodedata.normalize("NFD", s)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch)).lower()


def search_languages(query: str, pool: list[Language] | None = None) -> list[Language]:
    pool = LANGUAGES if pool is None else pool
    q = _normalize(query.strip())
    if not q:
        return list(pool)
    starts: list[Language] = []
    contains: list[Language] = []
    for lang in pool:
        name = _normalize(lang.name)
        native = _normalize(lang.native)
        code = lang.code.lower()
        if name.startswith(q) or native.startswith(q) or code == q:
            starts.append(lang)
        elif q in name or q in native or code.startswith(q):
            contains.append(lang)
    return starts + contains


def default_target_for_locale(locale: str | None) -> str:
    """English for non-English locales, Spanish for English locales."""
    base = (locale or "en").strip().replace("_", "-").split("-")[0].lower()
    return "es" if base == "en" else "en"
