"""Deteccao de blocos de texto e do alfabeto, sem conhecer a tabela da ROM.

A ideia central: texto natural tem uma assinatura estatistica que graficos e
codigo nao tem -- um byte dominante (o espaco) que reaparece a cada 4-7 bytes
com regularidade moderada. Nenhuma outra estrutura numa ROM se parece com isso.

Os limiares abaixo foram calibrados contra a traducao PT-BR humana de Chrono
Trigger: as regioes que os tradutores da CBT alteraram sao, por definicao,
texto -- e servem de gabarito rotulado (ver scripts/validate_chrono.py).
"""

from __future__ import annotations

import statistics
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass

import numpy as np

#: frequencia relativa das letras em ingles e portugues somados -- usada para
#: reconhecer qual faixa contigua de bytes e o alfabeto
LETTER_FREQ = {
    "a": 9.5, "b": 1.4, "c": 3.5, "d": 4.6, "e": 12.5, "f": 1.8, "g": 1.6,
    "h": 3.6, "i": 7.6, "j": 0.3, "k": 0.5, "l": 3.6, "m": 3.4, "n": 6.4,
    "o": 9.0, "p": 2.4, "q": 0.6, "r": 6.4, "s": 6.7, "t": 7.2, "u": 3.6,
    "v": 1.1, "w": 1.2, "x": 0.2, "y": 1.3, "z": 0.3,
}


#: palavras curtas e frequentes em dialogo de RPG, em ingles e portugues.
#: nao precisa ser exaustiva -- basta separar o alfabeto certo dos 230 errados
COMMON_WORDS = frozenset(
    """the you and that with have this what will your from they were been
    there their would about which when them then some time just like into
    more only over take know come make want back look than very good need
    well here give find tell talk town king dark life door open name gold
    left right last will his her him its can not but for are was one all
    out who how why now say see get too new say may
    para voce com uma nao que mas por mais como tudo agora aqui bem sim
    onde quando tempo vida porta rei ouro nome cidade falar olhar dizer
    fazer ver ter estar ser meu sua seu ele ela nos eles isso essa este
    muito pouco sempre nunca ainda entao depois antes sobre""".split()
)


@dataclass
class TextRegion:
    start: int
    end: int
    score: float

    @property
    def length(self) -> int:
        return self.end - self.start


@dataclass
class AlphabetGuess:
    space: int
    lower_base: int
    upper_base: int | None
    confidence: float
    word_hits: int = 0
    runner_up_hits: int = 0

    def as_table_source(self) -> str:
        from .relsearch import build_table_source

        return build_table_source(
            base_lower=self.lower_base, base_upper=self.upper_base, space=self.space
        )


def _band(value: float, low: float, high: float, slack: float) -> float:
    """Pertinencia trapezoidal: 1.0 dentro de [low, high], caindo ate 0 no slack."""
    if low <= value <= high:
        return 1.0
    distance = low - value if value < low else value - high
    return max(0.0, 1.0 - distance / slack)


def score_window(block: bytes) -> float:
    """0.0 a 1.0 -- o quanto o bloco se parece com texto natural."""
    if len(block) < 32:
        return 0.0
    counts = Counter(block)
    dominant, top = counts.most_common(1)[0]
    top_freq = top / len(block)
    # contagem absoluta, nao razao: a razao encolheria conforme a janela cresce
    distinct = len(counts)

    positions = [i for i, value in enumerate(block) if value == dominant]
    if len(positions) < 4:
        return 0.0
    gaps = [b - a for a, b in zip(positions, positions[1:])]
    mean_gap = statistics.mean(gaps)
    cv = statistics.pstdev(gaps) / mean_gap if mean_gap else 9.9

    # faixas medidas nas regioes de dialogo de Chrono Trigger (p10-p90);
    # `distinct` cobre desde texto de alfabeto simples (~28 valores) ate texto
    # com DTE, que usa uma faixa bem mais larga (~85 valores em 256 bytes)
    return (
        _band(top_freq, 0.14, 0.24, 0.06)
        * _band(mean_gap, 3.8, 6.6, 2.5)
        * _band(cv, 0.50, 0.95, 0.45)
        * _band(distinct, 22, 120, 45)
    )


def find_text_regions(
    data: bytes,
    window: int = 256,
    stride: int = 128,
    threshold: float = 0.45,
    min_length: int = 256,
    limits: list[tuple[int, int]] | None = None,
) -> list[TextRegion]:
    """Varre a ROM e devolve as faixas que se parecem com texto."""
    regions: list[TextRegion] = []
    for lo, hi in limits or [(0, len(data))]:
        hi = min(hi, len(data))
        marks: list[tuple[int, int, float]] = []
        for start in range(lo, hi - window + 1, stride):
            score = score_window(data[start : start + window])
            if score >= threshold:
                marks.append((start, start + window, score))
        # funde janelas que se tocam ou se sobrepoem
        for start, end, score in marks:
            if regions and start <= regions[-1].end:
                last = regions[-1]
                last.end = max(last.end, end)
                last.score = max(last.score, score)
            else:
                regions.append(TextRegion(start, end, score))
    return [region for region in regions if region.length >= min_length]


def _gap_profile(blob: bytes, value: int) -> tuple[float, float]:
    """Media e coeficiente de variacao dos intervalos entre ocorrencias de `value`."""
    positions = [i for i, b in enumerate(blob) if b == value]
    if len(positions) < 8:
        return 0.0, 9.9
    gaps = [b - a for a, b in zip(positions, positions[1:])]
    mean = statistics.mean(gaps)
    return mean, (statistics.pstdev(gaps) / mean if mean else 9.9)


def _word_keys(words: Iterable[str], length: int) -> np.ndarray:
    """Palavras de um dado tamanho, codificadas como inteiros na base 26."""
    powers = 26 ** np.arange(length, dtype=np.int64)
    keys = [
        int(np.dot([ord(c) - ord("a") for c in word], powers))
        for word in words
        if len(word) == length and word.isalpha() and word.islower()
    ]
    return np.array(sorted(set(keys)), dtype=np.int64)


def _count_words(arr: np.ndarray, base: int, keys_by_length: dict[int, np.ndarray]) -> int:
    """Quantas sequencias de letras do alfabeto `base` sao palavras reais.

    Toda a contagem e vetorizada: cada trecho de letras vira um inteiro na base
    26 e a checagem no dicionario e um `isin` de array. Sem isso, testar os 231
    alfabetos possiveis levaria mais de um minuto por ROM.
    """
    mask = (arr >= base) & (arr <= base + 25)
    if not mask.any():
        return 0
    padded = np.concatenate(([False], mask, [False]))
    edges = np.diff(padded.astype(np.int8))
    starts = np.flatnonzero(edges == 1)
    ends = np.flatnonzero(edges == -1)
    lengths = ends - starts

    total = 0
    for length, keys in keys_by_length.items():
        if keys.size == 0:
            continue
        chosen = starts[lengths == length]
        if chosen.size == 0:
            continue
        letters = arr[chosen[:, None] + np.arange(length)].astype(np.int64) - base
        codes = letters @ (26 ** np.arange(length, dtype=np.int64))
        total += int(np.isin(codes, keys).sum())
    return total


def guess_alphabet(
    data: bytes,
    regions: list[TextRegion] | None = None,
    words: Iterable[str] = COMMON_WORDS,
    min_hits: int = 20,
) -> AlphabetGuess | None:
    """Descobre onde ficam o alfabeto e o espaco, sem tabela previa.

    Nao adianta procurar a faixa de bytes mais frequente: numa ROM de SNES o
    codigo e os graficos abafam qualquer histograma. O que so o texto produz sao
    *palavras* -- entao cada um dos 231 alfabetos possiveis e testado por quantas
    palavras reais ele gera, e o certo se separa do resto por larga margem.

    O espaco sai depois, de graca: e o byte que mais aparece logo apos uma
    palavra.
    """
    if regions:
        blob = b"".join(bytes(data[r.start : r.end]) for r in regions)
    else:
        blob = bytes(data)
    if len(blob) < 4096:
        return None
    arr = np.frombuffer(blob, dtype=np.uint8)

    counts = np.bincount(arr, minlength=256)
    floor = max(10, len(blob) // 20000)
    keys_by_length = {n: _word_keys(words, n) for n in (3, 4, 5, 6)}

    scored: list[tuple[int, int]] = []
    for base in range(256 - 25):
        present = int((counts[base : base + 26] >= floor).sum())
        if present < 21:
            continue  # amostras curtas podem nao ter 'j', 'x' ou 'z'; 21 ja basta
        hits = _count_words(arr, base, keys_by_length)
        if hits >= min_hits:
            scored.append((hits, base))
    if not scored:
        return None
    scored.sort(reverse=True)
    hits, lower = scored[0]
    runner_up = scored[1][0] if len(scored) > 1 else 0
    confidence = 1.0 - runner_up / hits

    # maiusculas: quase sempre os 26 bytes imediatamente antes das minusculas
    upper = lower - 26 if lower >= 26 else None
    if upper is not None and counts[upper : upper + 26].min() < floor / 4:
        upper = None

    space = _byte_after_words(arr, lower)
    return AlphabetGuess(
        space=space,
        lower_base=lower,
        upper_base=upper,
        confidence=confidence,
        word_hits=hits,
        runner_up_hits=runner_up,
    )


def _byte_after_words(arr: np.ndarray, base: int) -> int:
    """O separador de palavras e o byte que mais segue um trecho de letras."""
    mask = (arr >= base) & (arr <= base + 25)
    padded = np.concatenate(([False], mask, [False]))
    edges = np.diff(padded.astype(np.int8))
    starts = np.flatnonzero(edges == 1)
    ends = np.flatnonzero(edges == -1)
    ends = ends[(ends - starts >= 2) & (ends < len(arr))]
    if ends.size == 0:
        return -1
    return int(np.bincount(arr[ends], minlength=256).argmax())


def _correlation(xs: list[int], ys: list[float]) -> float:
    mean_x = statistics.mean(xs)
    mean_y = statistics.mean(ys)
    num = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
    den = (
        sum((x - mean_x) ** 2 for x in xs) * sum((y - mean_y) ** 2 for y in ys)
    ) ** 0.5
    return num / den if den else 0.0


VOWELS = frozenset("aeiouáéíóúâêôàãõäëïöü")


def looks_like_language(
    text: str,
    max_consonant_run: int = 4,
    min_vowel_ratio: float = 0.20,
    max_vowel_ratio: float = 0.68,
) -> bool:
    """Filtro barato contra lixo que o scanner deixou passar.

    Um bloco de graficos decodificado com a tabela certa vira algo como 'OyRf'
    -- letras validas, sequencia impossivel. Palavra de verdade tem vogais numa
    proporcao estreita e nao empilha consoantes indefinidamente.
    """
    letters = [c for c in text if c.isalpha()]
    if len(letters) < 3:
        return False
    vowels = sum(1 for c in letters if c.lower() in VOWELS)
    if not min_vowel_ratio <= vowels / len(letters) <= max_vowel_ratio:
        return False
    run = 0
    for char in text:
        if char.isalpha() and char.lower() not in VOWELS:
            run += 1
            if run > max_consonant_run:
                return False
        else:
            run = 0
    return True
