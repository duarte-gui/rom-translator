"""Recuperacao de DTE/MTE: descobrir o que cada byte desconhecido representa.

Jogos de 8 e 16 bits comprimem dialogo trocando pares e trechos frequentes por
um unico byte -- DTE (dois caracteres) e MTE (varios). A tabela dessas trocas
mora no codigo do jogo, num formato diferente em cada cartucho, e e por isso que
ferramentas de romhacking pedem um `.tbl` pronto: recuperar essa tabela de forma
generica parece exigir engenharia reversa do descompressor.

Nao exige. O jogo repete vocabulario, e nem toda ocorrencia de uma palavra passa
pelo compressor -- "sword" aparece inteiro em algum lugar e comprimido em outro.
Entao as palavras que ja se leem por completo servem de dicionario para as que
tem buracos: se `s?rd` so casa com `sword` entre as palavras conhecidas, aquele
byte vale `wo`. Cada byte resolvido completa outras palavras, que viram
dicionario para a rodada seguinte.

O dicionario sai da propria ROM, entao isto funciona em qualquer idioma e nao
depende de lista de palavras embutida.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass

from .table import Table


@dataclass
class DteGuess:
    byte: int
    text: str
    hits: int  # palavras que esta hipotese completa
    runner_up: int  # a segunda melhor hipotese
    occurrences: int  # vezes que o byte aparece no texto

    @property
    def confidence(self) -> float:
        return 1.0 - self.runner_up / self.hits if self.hits else 0.0


@dataclass
class _Word:
    """Uma palavra do texto: pedacos conhecidos e bytes ainda por resolver."""

    parts: tuple[object, ...]  # str (conhecido) ou int (byte desconhecido)

    @property
    def unknowns(self) -> list[int]:
        return [p for p in self.parts if isinstance(p, int)]

    def render_slice(
        self, start: int, stop: int, resolved: dict[int, str]
    ) -> str | None:
        return _render(self.parts[start:stop], resolved)

    def render(self, resolved: dict[int, str]) -> str | None:
        return _render(self.parts, resolved)


def _render(parts: tuple[object, ...], resolved: dict[int, str]) -> str | None:
    """Junta os pedacos, ou None se algum byte ainda nao foi resolvido."""
    out: list[str] = []
    for part in parts:
        if isinstance(part, str):
            out.append(part)
        elif part in resolved:
            out.append(resolved[part])
        else:
            return None
    return "".join(out)


def _split_words(
    data: bytes, regions: list[tuple[int, int]], table: Table, space: int
) -> list[_Word]:
    """Quebra o texto em palavras, marcando os bytes que a tabela nao conhece."""
    letters = table.letter_bytes
    words: list[_Word] = []
    for start, end in regions:
        parts: list[object] = []
        buffer: list[str] = []

        def flush_word() -> None:
            if buffer:
                parts.append("".join(buffer))
                buffer.clear()

        def end_word() -> None:
            flush_word()
            if parts:
                words.append(_Word(tuple(parts)))
            parts.clear()

        for offset in range(start, min(end, len(data))):
            value = data[offset]
            if value == space:
                end_word()
            elif value in letters:
                buffer.append(table.entries[bytes([value])])
            else:
                flush_word()
                parts.append(value)
        end_word()
    return words


def _align(
    parts: tuple[object, ...],
    word: str,
    resolved: dict[int, str],
    min_expansion: int,
    max_expansion: int,
) -> list[dict[int, str]]:
    """Todas as formas de encaixar `word` no padrao, atribuindo os buracos.

    Um padrao como ['s', X, 'rd'] casa com "sword" atribuindo X='wo'. Com mais de
    um buraco a mesma palavra propoe as duas atribuicoes ao mesmo tempo -- e o que
    permite avancar em texto muito comprimido, onde quase nao existe palavra com um
    unico buraco.
    """
    results: list[dict[int, str]] = []

    def walk(index: int, position: int, assigned: dict[int, str]) -> None:
        if index == len(parts):
            if position == len(word):
                results.append(dict(assigned))
            return
        part = parts[index]
        if isinstance(part, str):
            piece = part.lower()
            if word.startswith(piece, position):
                walk(index + 1, position + len(piece), assigned)
            return
        fixed = assigned.get(part) or resolved.get(part)
        if fixed is not None:
            if word.startswith(fixed, position):
                walk(index + 1, position + len(fixed), assigned)
            return
        for size in range(min_expansion, max_expansion + 1):
            if position + size > len(word):
                break
            assigned[part] = word[position : position + size]
            walk(index + 1, position + size, assigned)
            del assigned[part]

    walk(0, 0, {})
    return results


def _corpus_votes(
    words: list["_Word"],
    resolved: dict[int, str],
    by_length: dict[int, list[str]],
    min_expansion: int,
    max_expansion: int,
    max_holes: int,
    max_matches: int = 40,
) -> dict[int, Counter[str]]:
    """Acumula, por byte, as expansoes que o lexico *fixa* -- nao as que ele admite.

    A distincao decide tudo. Uma palavra muito comprimida casa com centenas de
    palavras do lexico, e contar um voto por alinhamento deixa o vencedor ser o
    par mais comum do idioma, nao o par certo: na primeira versao disto o byte de
    "th" recebeu 24 mil votos para 'ma'.

    Entao cada palavra vota uma vez, e so nos bytes em que *todos* os seus
    alinhamentos concordam. Palavra ambigua nao vota, palavra que casa com coisa
    demais e descartada inteira.
    """
    votes: dict[int, Counter[str]] = defaultdict(Counter)
    for word in words:
        pending = {b for b in word.unknowns if b not in resolved}
        if not pending or len(pending) > max_holes:
            continue
        fixed = sum(
            len(p) if isinstance(p, str) else len(resolved.get(p, ""))
            for p in word.parts
        )
        holes = len(pending)
        matches: list[dict[int, str]] = []
        too_many = False
        for length in range(
            fixed + holes * min_expansion, fixed + holes * max_expansion + 1
        ):
            for candidate in by_length.get(length, ()):
                matches.extend(
                    _align(word.parts, candidate, resolved, min_expansion, max_expansion)
                )
                if len(matches) > max_matches:
                    too_many = True
                    break
            if too_many:
                break
        if too_many or not matches:
            continue
        options: dict[int, set[str]] = defaultdict(set)
        for assignment in matches:
            for byte, text in assignment.items():
                options[byte].add(text)
        for byte, texts in options.items():
            if len(texts) == 1:
                text = next(iter(texts))
                if _plausible(text):
                    votes[byte][text] += 1
    return votes


def infer_dte(
    data: bytes,
    regions: list[tuple[int, int]],
    table: Table,
    space: int,
    lexicon: set[str] | None = None,
    min_expansion: int = 2,
    max_expansion: int = 4,
    max_holes: int = 3,
    min_hits: int = 8,
    min_confidence: float = 0.60,
    rounds: int = 6,
    max_words: int = 5000,
) -> list[DteGuess]:
    """Deduz o que cada byte desconhecido representa. Ordenado por confianca.

    `min_expansion` e 2 de proposito: um byte de DTE existe justamente para valer
    mais de um caractere. Permitir expansao de tamanho 1 faz qualquer byte se
    passar por uma letra comum -- na primeira versao disto, metade da tabela do
    Chrono Trigger "resolveu" para 't'.

    `min_confidence` e a folga exigida sobre a segunda melhor hipotese. Um byte
    de controle nao tem expansao coerente e simplesmente nao alcanca a folga --
    o que e o resultado certo: melhor deixar `[$1F]` visivel do que inventar
    duas letras que nao existem.
    """
    words = _split_words(data, regions, table, space)
    lexicon = lexicon or set()

    # o custo cresce com palavras x tamanho do lexico x alinhamentos, e a analise
    # completa de uma ROM de 4 MiB nao termina em tempo util. As palavras curtas
    # sao as que mais casam com tudo e menos informam: a amostra fica com as longas.
    if len(words) > max_words:
        words = sorted(words, key=lambda w: -len(w.parts))[:max_words]
    frequency = Counter(b for word in words for b in word.unknowns)
    resolved: dict[int, str] = {}
    guesses: dict[int, DteGuess] = {}
    taken: dict[str, int] = {}  # expansao -> byte que a reivindicou

    for _ in range(rounds):
        known = _known_words(words, resolved) | lexicon
        by_length: dict[int, list[str]] = defaultdict(list)
        for word in known:
            by_length[len(word)].append(word)

        all_votes = _corpus_votes(
            words, resolved, by_length, min_expansion, max_expansion, max_holes
        )
        found_this_round = False
        for byte, occurrences in frequency.most_common():
            if byte in resolved or byte not in all_votes:
                continue
            ranked = all_votes[byte].most_common(2)
            if not ranked:
                continue
            best, hits = ranked[0]
            runner_up = ranked[1][1] if len(ranked) > 1 else 0
            guess = DteGuess(byte, best, hits, runner_up, occurrences)
            if hits < min_hits or guess.confidence < min_confidence:
                continue
            rival = taken.get(best)
            if rival is not None:
                # uma tabela de compressao nao mapeia dois bytes para o mesmo
                # trecho: o mais fraco perde, e volta a ser desconhecido
                if guesses[rival].hits >= hits:
                    continue
                resolved.pop(rival, None)
                guesses.pop(rival, None)
            taken[best] = byte
            resolved[byte] = best
            guesses[byte] = guess
            found_this_round = True
        if not found_this_round:
            break

    return sorted(guesses.values(), key=lambda g: (-g.occurrences, g.byte))


def _plausible(text: str) -> bool:
    """Descarta expansoes que nenhum jogo usaria como entrada de DTE.

    Maiuscula no meio de um trecho e o sinal mais confiavel de que a hipotese
    juntou pedacos de duas palavras diferentes -- `ttN` nao e um par de letras,
    e o fim de uma palavra colado no comeco da proxima.
    """
    if not text or not all(c.isalpha() or c == " " for c in text):
        return False
    return not any(c.isupper() for c in text[1:])


def _known_words(words: list[_Word], resolved: dict[int, str]) -> set[str]:
    out = set()
    for word in words:
        rendered = word.render(resolved)
        if rendered and len(rendered) >= 3:
            out.add(rendered.lower())
    return out
