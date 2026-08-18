"""Inferencia de DTE, medida contra uma tabela conhecida.

O texto e real (dialogo de RPG), a compressao e sintetica -- entao existe
gabarito. Sem isso nao daria para saber se o algoritmo funciona: numa ROM de
verdade a tabela de compressao e justamente o que nao se conhece.
"""

import pytest

from rom_translator.core.dte import infer_dte
from rom_translator.core.table import Table

PROSA = (
    "The king will record thy deeds in his imperial scroll so thou may return "
    "later to the castle and speak with the king again about the dragon that "
    "stole the precious globe and hid it in the darkness of the mountain cave "
    "where many brave warriors have perished on this dangerous quest before "
    "thee and where the princess is held until some hero shall come to save her "
    "from the terrible monsters that guard the entrance to that dark place "
    "travel not to the south for there the monsters are fierce and terrible "
    "and thou must first battle many foes to become strong enough to face them "
)

TABELA = {0x80: "th", 0x81: "in", 0x82: "er", 0x83: "st", 0x84: "an"}


def _encode(text: str) -> tuple[bytes, Table]:
    for byte, pair in TABELA.items():
        text = text.replace(pair, chr(byte))
    mapping = {chr(0x61 + i): 0x0A + i for i in range(26)}
    mapping.update({chr(0x41 + i): 0x24 + i for i in range(26)})
    mapping[" "] = 0x5F
    mapping.update({chr(b): b for b in TABELA})
    data = bytes(mapping[c] for c in text if c in mapping)
    source = (
        "\n".join(f"{0x0A + i:02X}={chr(0x61 + i)}" for i in range(26))
        + "\n"
        + "\n".join(f"{0x24 + i:02X}={chr(0x41 + i)}" for i in range(26))
        + "\n5F= \n"
    )
    return data, Table.parse(source)


@pytest.fixture(scope="module")
def lexicon():
    return {w for w in PROSA.lower().split() if len(w) >= 3} | {
        "record", "deeds", "imperial", "scroll", "return", "castle", "speak",
        "again", "about", "dragon", "stole", "precious", "globe", "darkness",
        "mountain", "brave", "warriors", "perished", "dangerous", "quest",
        "princess", "until", "terrible", "monsters", "guard", "entrance",
        "travel", "south", "fierce", "first", "battle", "strong", "enough",
    }


def test_recovers_entries_from_a_known_table(lexicon):
    data, table = _encode(PROSA * 6)
    guesses = infer_dte(data, [(0, len(data))], table, 0x5F, lexicon=lexicon, min_hits=4)
    achado = {g.byte: g.text for g in guesses}
    corretos = [b for b, t in achado.items() if TABELA.get(b) == t]
    errados = [b for b, t in achado.items() if TABELA.get(b) != t]
    assert not errados, f"proposta errada para {[hex(b) for b in errados]}"
    assert len(corretos) >= 2, f"recuperou de menos: {achado}"


def test_never_assigns_the_same_expansion_twice(lexicon):
    data, table = _encode(PROSA * 6)
    guesses = infer_dte(data, [(0, len(data))], table, 0x5F, lexicon=lexicon, min_hits=4)
    textos = [g.text for g in guesses]
    assert len(textos) == len(set(textos))


def test_stays_quiet_without_a_lexicon(lexicon):
    """Sem lexico a inferencia nao tem como se apoiar -- e cala em vez de chutar."""
    data, table = _encode(PROSA * 6)
    guesses = infer_dte(data, [(0, len(data))], table, 0x5F, min_hits=4)
    errados = [g for g in guesses if TABELA.get(g.byte) != g.text]
    assert not errados


def test_rejects_expansions_with_internal_capitals():
    from rom_translator.core.dte import _plausible

    assert _plausible("th") and _plausible("Lo")
    assert not _plausible("ttN")  # fim de uma palavra colado no inicio da proxima
    assert not _plausible("a1") and not _plausible("")


def test_single_character_expansions_are_not_proposed(lexicon):
    """DTE existe para valer mais de um caractere; permitir 1 vira degeneracao."""
    data, table = _encode(PROSA * 6)
    guesses = infer_dte(data, [(0, len(data))], table, 0x5F, lexicon=lexicon, min_hits=4)
    assert all(len(g.text) >= 2 for g in guesses)
