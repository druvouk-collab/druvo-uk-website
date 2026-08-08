"""Chat presentation i18n — translate replies without altering commerce facts."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

import httpx

logger = logging.getLogger(__name__)

_OPENAI_URL = "https://api.openai.com/v1/chat/completions"
_DEFAULT_LOCALE = "en-GB"

# Quick picks (examples — full catalog supports any BCP-47 code the model handles).
QUICK_LANGUAGES: list[dict[str, str]] = [
    {"code": "en-GB", "name": "English", "native": "English"},
    {"code": "ur-PK", "name": "Urdu", "native": "اردو"},
    {"code": "ar", "name": "Arabic", "native": "العربية"},
    {"code": "pa-IN", "name": "Punjabi", "native": "ਪੰਜਾਬੀ"},
    {"code": "hi-IN", "name": "Hindi", "native": "हिन्दी"},
    {"code": "bn-BD", "name": "Bengali", "native": "বাংলা"},
    {"code": "pl", "name": "Polish", "native": "Polski"},
    {"code": "ro", "name": "Romanian", "native": "Română"},
    {"code": "fr", "name": "French", "native": "Français"},
    {"code": "es", "name": "Spanish", "native": "Español"},
    {"code": "de", "name": "German", "native": "Deutsch"},
    {"code": "it", "name": "Italian", "native": "Italiano"},
    {"code": "pt", "name": "Portuguese", "native": "Português"},
    {"code": "tr", "name": "Turkish", "native": "Türkçe"},
    {"code": "zh-CN", "name": "Chinese", "native": "中文"},
]

_RTL_PREFIXES = ("ar", "ur", "he", "fa", "ps", "sd")

_TOKEN_PATTERN = re.compile(
    r"(⟦\d+⟧|" r"£[\d,]+(?:\.\d{2})?|" r"https?://[^\s]+|" r"/[a-z0-9][\w./-]*|" r"\bDRUVO-[A-Z0-9-]+\b)",
    re.IGNORECASE,
)


def normalize_locale(code: str | None) -> str:
    if not code or not str(code).strip():
        return _DEFAULT_LOCALE
    cleaned = str(code).strip().replace("_", "-")
    if cleaned.lower() in {"en", "en-gb", "en-us"}:
        return "en-GB"
    return cleaned


def is_english(locale: str) -> bool:
    return normalize_locale(locale).lower().startswith("en")


def is_rtl(locale: str) -> bool:
    base = normalize_locale(locale).split("-")[0].lower()
    return base in _RTL_PREFIXES


def language_catalog() -> list[dict[str, str | bool]]:
    """Searchable language list — quick picks first, then extended catalog."""
    seen: set[str] = set()
    rows: list[dict[str, str | bool]] = []
    for item in QUICK_LANGUAGES:
        code = item["code"]
        seen.add(code.lower())
        rows.append(
            {
                "code": code,
                "name": item["name"],
                "native": item["native"],
                "rtl": is_rtl(code),
                "quick": True,
            }
        )
    extended = [
        ("nl", "Dutch", "Nederlands"),
        ("sv", "Swedish", "Svenska"),
        ("da", "Danish", "Dansk"),
        ("no", "Norwegian", "Norsk"),
        ("fi", "Finnish", "Suomi"),
        ("cs", "Czech", "Čeština"),
        ("sk", "Slovak", "Slovenčina"),
        ("hu", "Hungarian", "Magyar"),
        ("el", "Greek", "Ελληνικά"),
        ("ru", "Russian", "Русский"),
        ("uk", "Ukrainian", "Українська"),
        ("ja", "Japanese", "日本語"),
        ("ko", "Korean", "한국어"),
        ("vi", "Vietnamese", "Tiếng Việt"),
        ("th", "Thai", "ไทย"),
        ("id", "Indonesian", "Bahasa Indonesia"),
        ("ms", "Malay", "Bahasa Melayu"),
        ("ta", "Tamil", "தமிழ்"),
        ("te", "Telugu", "తెలుగు"),
        ("mr", "Marathi", "मराठी"),
        ("gu", "Gujarati", "ગુજરાતી"),
        ("fa", "Persian", "فارسی"),
        ("he", "Hebrew", "עברית"),
        ("sw", "Swahili", "Kiswahili"),
        ("af", "Afrikaans", "Afrikaans"),
        ("sq", "Albanian", "Shqip"),
        ("bg", "Bulgarian", "Български"),
        ("hr", "Croatian", "Hrvatski"),
        ("sr", "Serbian", "Српски"),
        ("sl", "Slovenian", "Slovenščina"),
        ("lt", "Lithuanian", "Lietuvių"),
        ("lv", "Latvian", "Latviešu"),
        ("et", "Estonian", "Eesti"),
    ]
    for code, name, native in extended:
        key = code.lower()
        if key in seen:
            continue
        seen.add(key)
        rows.append({"code": code, "name": name, "native": native, "rtl": is_rtl(code), "quick": False})
    return rows


def detect_language(text: str) -> str:
    """Best-effort language detection from customer message."""
    stripped = (text or "").strip()
    if not stripped:
        return _DEFAULT_LOCALE
    try:
        from langdetect import DetectorFactory, detect

        DetectorFactory.seed = 0
        code = detect(stripped)
        mapping = {
            "en": "en-GB",
            "ur": "ur-PK",
            "ar": "ar",
            "pa": "pa-IN",
            "hi": "hi-IN",
            "bn": "bn-BD",
            "zh-cn": "zh-CN",
            "zh-tw": "zh-TW",
        }
        return mapping.get(code, code)
    except Exception:
        if re.search(r"[\u0600-\u06FF]", stripped):
            return "ar"
        if re.search(r"[\u0750-\u077F\uFB50-\uFDFF\uFE70-\uFEFF]", stripped):
            return "ur-PK"
        if re.search(r"[\u0900-\u097F]", stripped):
            return "hi-IN"
        return _DEFAULT_LOCALE


@dataclass(frozen=True)
class ProtectedText:
    text: str
    tokens: tuple[str, ...]


def protect_facts(text: str, products: list[dict] | None = None) -> ProtectedText:
    tokens: list[str] = []

    def _repl(match: re.Match[str]) -> str:
        tokens.append(match.group(0))
        return f"⟦{len(tokens) - 1}⟧"

    protected = _TOKEN_PATTERN.sub(_repl, text)
    if products:
        for product in products:
            for key in ("sku", "url"):
                value = str(product.get(key) or "").strip()
                if value and value not in tokens:
                    tokens.append(value)
    return ProtectedText(text=protected, tokens=tuple(tokens))


def restore_facts(text: str, protected: ProtectedText) -> str:
    restored = text
    for index, token in enumerate(protected.tokens):
        restored = restored.replace(f"⟦{index}⟧", token)
        restored = restored.replace(f"[[{index}]]", token)
        restored = restored.replace(f"{{{{{index}}}}}", token)
    return restored


class ChatPresentationService:
    """Translate English factual replies for the customer's locale."""

    def __init__(self, *, openai_api_key: str = "", chat_model: str = "gpt-4o-mini") -> None:
        self._openai_api_key = openai_api_key.strip()
        self._chat_model = chat_model

    def resolve_locale(self, message: str, requested: str | None) -> str:
        if requested and requested.strip() and not is_english(requested):
            return normalize_locale(requested)
        if requested and requested.strip():
            return normalize_locale(requested)
        return detect_language(message)

    async def present(
        self,
        english_text: str,
        locale: str,
        *,
        products: list[dict] | None = None,
    ) -> str:
        target = normalize_locale(locale)
        if is_english(target):
            return english_text
        protected = protect_facts(english_text, products)
        if not self._openai_api_key:
            logger.info("Chat i18n: no OpenAI key — returning English reply for locale %s", target)
            return english_text
        try:
            translated = await self._translate(protected.text, target)
            return restore_facts(translated, protected)
        except Exception as exc:
            logger.warning("Chat translation failed (%s): %s", type(exc).__name__, exc)
            return english_text

    async def _translate(self, text: str, locale: str) -> str:
        language_name = next(
            (row["name"] for row in language_catalog() if row["code"].lower() == locale.lower()),
            locale,
        )
        system = (
            f"Translate the customer's shopping assistant message into {language_name} ({locale}). "
            "Preserve every token like ⟦0⟧ exactly as-is — these are prices, SKUs, and URLs. "
            "Keep GBP prices in £ format. Do not invent facts. Return only the translation."
        )
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                _OPENAI_URL,
                headers={
                    "Authorization": f"Bearer {self._openai_api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": self._chat_model,
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": text},
                    ],
                    "temperature": 0.2,
                    "max_tokens": 600,
                },
            )
            response.raise_for_status()
            return response.json()["choices"][0]["message"]["content"].strip()
