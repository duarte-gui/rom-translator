"""Deteccao de blocos de texto e do alfabeto."""

import random

from rom_translator.core.scanner import (
    find_text_regions,
    guess_alphabet,
    looks_like_language,
    score_window,
)

PROSE = (
    "the king of guardia would not have known that the frog and the girl "
    "were about to open the door and find what they were looking for "
    "voce nao vai saber o que ele quer dizer com isso agora mas o tempo "
    "sempre mostra tudo para quem tem paciencia de esperar mais um pouco "
)


def _encode(text: str, base: int = 0xBA, space: int = 0xEF) -> bytes:
    return bytes(
        space if c == " " else base + (ord(c) - ord("a")) for c in text if c.isalpha() or c == " "
    )


def test_score_window_prefers_text_over_noise():
    rng = random.Random(0)
    text = _encode(PROSE * 4)[:512]
    noise = bytes(rng.randrange(256) for _ in range(512))
    zeros = bytes(512)
    # prosa sintetica pontua abaixo de dialogo real: as palavras aqui tem
    # comprimento uniforme demais, e a regularidade dos espacos e parte do sinal
    assert score_window(text) > 0.5
    assert score_window(noise) < 0.3
    assert score_window(zeros) == 0.0


def test_finds_text_buried_in_noise():
    rng = random.Random(1)
    text = _encode(PROSE * 6)
    data = (
        bytes(rng.randrange(256) for _ in range(4096))
        + text
        + bytes(rng.randrange(256) for _ in range(4096))
    )
    regions = find_text_regions(data, threshold=0.5)
    assert regions, "nao achou o bloco de texto"
    best = max(regions, key=lambda r: r.length)
    # a regiao encontrada tem que se sobrepor ao texto real
    assert best.start < 4096 + len(text) and best.end > 4096


def test_guess_alphabet_recovers_encoding_without_a_table():
    data = _encode(PROSE * 40)
    guess = guess_alphabet(data)
    assert guess is not None
    assert guess.lower_base == 0xBA
    assert guess.space == 0xEF
    assert guess.word_hits > guess.runner_up_hits


def test_guess_alphabet_works_for_a_different_encoding():
    """O detector nao pode ter decorado o alfabeto do Chrono Trigger."""
    data = _encode(PROSE * 40, base=0x41, space=0x20)  # ASCII
    guess = guess_alphabet(data)
    assert guess is not None
    assert (guess.lower_base, guess.space) == (0x41, 0x20)


def test_guess_alphabet_gives_up_on_pure_noise():
    rng = random.Random(2)
    assert guess_alphabet(bytes(rng.randrange(256) for _ in range(20000))) is None


def test_language_filter_keeps_words_and_drops_garbage():
    assert looks_like_language("The Magic Kingdom")
    assert looks_like_language("Break the Seal")
    assert looks_like_language("cidade")
    assert not looks_like_language("ab")
    assert not looks_like_language("qwrtpsdfghk")  # consoantes demais
    assert not looks_like_language("aeioaeioaeia")  # vogais demais
