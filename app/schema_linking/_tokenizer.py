"""Text tokenization for BM25 schema retrieval."""

import re
import unicodedata

_CAMEL_BOUNDARY = re.compile(
    r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])"
)
_WORD = re.compile(r"\w+", flags=re.UNICODE)


def _tokenize(text: str) -> tuple[str, ...]:
    normalized = unicodedata.normalize("NFKC", text)
    tokens: list[str] = []
    for word in _WORD.findall(normalized):
        folded_word = word.casefold()
        tokens.append(folded_word)
        for underscore_part in word.split("_"):
            if not underscore_part:
                continue
            folded_part = underscore_part.casefold()
            if folded_part != folded_word:
                tokens.append(folded_part)
            for camel_part in _CAMEL_BOUNDARY.split(underscore_part):
                folded_camel_part = camel_part.casefold()
                if folded_camel_part and folded_camel_part != folded_part:
                    tokens.append(folded_camel_part)
    return tuple(tokens)


def _weighted_tokens(
    text: str | None,
    *,
    repetitions: int = 1,
) -> tuple[str, ...]:
    if not text:
        return ()
    return _tokenize(text) * repetitions
