"""Normalização de títulos para casar temas: acentos, caixa, números por extenso e ordinais viram a mesma forma."""

from __future__ import annotations

import re
import unicodedata

_ORDINALS = {
    "primeiro": 1, "primeira": 1, "segundo": 2, "segunda": 2, "terceiro": 3, "terceira": 3,
    "quarto": 4, "quarta": 4, "quinto": 5, "quinta": 5, "sexto": 6, "sexta": 6,
    "setimo": 7, "setima": 7, "oitavo": 8, "oitava": 8, "nono": 9, "nona": 9,
    "decimo": 10, "decima": 10,
    "first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5,
    "sixth": 6, "seventh": 7, "eighth": 8, "ninth": 9, "tenth": 10,
}
_CARDINALS = {
    "um": 1, "uma": 1, "dois": 2, "duas": 2, "tres": 3, "quatro": 4, "cinco": 5,
    "seis": 6, "sete": 7, "oito": 8, "nove": 9, "dez": 10,
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
}
# "1o", "2a", "3rd", "4th": NFKD já transformou "º"/"ª" em "o"/"a".
_NUMBER_SUFFIX = re.compile(r"^(\d+)(o|a|st|nd|rd|th)$")


def normalize_tokens(text: str) -> list[str]:
    decomposed = unicodedata.normalize("NFKD", text.lower())
    ascii_text = "".join(c for c in decomposed if not unicodedata.combining(c))
    tokens: list[str] = []
    for token in re.findall(r"[a-z0-9]+", ascii_text):
        if token.isdigit():
            tokens.append(str(int(token)))
            continue
        suffixed = _NUMBER_SUFFIX.match(token)
        if suffixed:
            tokens.append(str(int(suffixed.group(1))))
            continue
        number = _ORDINALS.get(token) or _CARDINALS.get(token)
        tokens.append(str(number) if number else token)
    return tokens


def contains_phrase(title: str, keyword: str) -> bool:
    haystack, needle = normalize_tokens(title), normalize_tokens(keyword)
    if not needle:
        return False
    size = len(needle)
    return any(haystack[i : i + size] == needle for i in range(len(haystack) - size + 1))


def matches_any(title: str, keywords: list[str]) -> bool:
    return any(contains_phrase(title, k) for k in keywords)
