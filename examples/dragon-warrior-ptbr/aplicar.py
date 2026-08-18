#!/usr/bin/env python3
"""Casa as traducoes do YAML com as unidades de um script extraido.

Uso: python aplicar.py dw.json traducao.yaml dw-ptbr.json
"""

import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from rom_translator.core.script import Script  # noqa: E402


def main(script_path: str, glossary_path: str, output: str) -> int:
    script = Script.load(script_path)
    traducoes = yaml.safe_load(Path(glossary_path).read_text(encoding="utf-8"))

    aplicadas = estouradas = 0
    for unit in script.units:
        traducao = traducoes.get(unit.text)
        if traducao is None:
            continue
        if len(traducao) > unit.max_len:
            print(f"  nao cabe: {unit.id} precisa de {len(traducao)}, cabe {unit.max_len}")
            estouradas += 1
            continue
        unit.translation = traducao
        aplicadas += 1

    script.save(output)
    print(f"{aplicadas} traducoes aplicadas"
          + (f", {estouradas} nao couberam" if estouradas else "")
          + f" -> {output}")
    return 1 if estouradas else 0


if __name__ == "__main__":
    if len(sys.argv) != 4:
        print(__doc__)
        sys.exit(2)
    sys.exit(main(*sys.argv[1:]))
