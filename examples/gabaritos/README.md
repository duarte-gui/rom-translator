# Gabaritos: traduções humanas usadas para medir a ferramenta

Uma tradução de fã é um dataset rotulado. Este diretório registra o que cada par
ROM + patch mediu — e, mais útil, **o que cada um quebrou**.

Nenhuma ROM e nenhum patch são distribuídos aqui. Rode você mesmo:

```bash
python scripts/validate_patch.py SUA_ROM.gba patch.ips --json metricas.json
```

## Chrono Trigger (SNES) — CBT, 1998/2010

| | |
|---|---|
| patch | IPS, 186 KB, edita **no lugar** |
| diff | 14.590 regiões, 157.853 bytes (3,8% da ROM) |
| recall do scanner | **94,1%** |
| alfabeto | `0xEF / 0xBA / 0xA0`, deduzido do zero |

A prova mais forte: o checksum interno do SNES continua válido depois da nossa aplicação —
os tradutores o recalcularam em 1998, então ele só fecha se cada byte foi para o lugar certo.

**O que ensinou:** que o gabarito existe. Foi este par que deu a primeira medida de recall.

## Golden Sun (GBA) — Kyle The Runner, 2010

| | |
|---|---|
| patch | IPS, 565 KB, **expande a ROM** |
| diff no original | 8 regiões, **69 bytes** |
| área nova | +564.913 bytes, 48% detectada como texto |
| alfabeto do texto novo | `0x20 / 0x61 / 0x41` (ASCII), 6.923 palavras contra 89 |
| acentos | 5.314 ocorrências em Latin-1: `ã á é ê ç ó í É à ú` |

Amostra lida de volta pela ferramenta:

```
Salvar sua aventura?  Sim  Não
Luvas: Aceleram Ataque
Anel: Use para recuperar 7 PP
Caveira   Rato Armad.   Cabeça Fant.
```

**O que quebrou:** a métrica de recall. O `validate_patch.py` assumia que um patch edita no
lugar — e mediu **0,0%** sobre 69 bytes, um número sem significado. Este tradutor não editou:
expandiu a ROM em 565 KB, escreveu a tradução inteira no fim em ASCII puro, e trocou **8 trechos
de código ARM** (0x015430–0x01558A) para desviar a leitura de texto para lá.

O gabarito passou a detectar expansão e a medir na área nova. E ganhou uma medida que não tinha:
bytes que aparecem no meio de palavras mas fora do alfabeto são candidatos a glifo acentuado — se
baterem com Latin-1, ele diz qual letra é.

## Faxanadu (NES) — Emu Brasil, POBRE e BR Games, 2017

| | |
|---|---|
| patch | IPS, 18 KB, edita **no lugar** |
| diff | 1.053 regiões, 16.549 bytes (6,3% da ROM) |
| regiões que são texto | 724 (15.256 bytes) — o resto é gráfico e ponteiro |
| recall do scanner | **23,4%** com a janela padrão · **61,5%** com janela de 32 bytes |
| alfabeto | `0xFD / 0x61 / 0x41` — letras em ASCII, mas o espaço **não** |

Lido de volta pela ferramenta:

```
Botão A' Sim   Botão B' Não
vire à direita e siga em frente
você consegue encontrá-las? Procu...
```

**O que quebrou:** o scanner. E não dá para culpar os gráficos — 724 das 1.053 regiões alteradas
decodificam como texto. O Faxanadu espalha falas curtas pelo banco inteiro, entre ponteiros e dados,
enquanto Chrono Trigger as guarda em blocos grandes e contíguos. A janela de 256 bytes dilui o sinal:

| janela | recall sobre texto | ROM sinalizada |
|---:|---:|---:|
| 256 | 23,4% | 10% |
| 128 | 41,9% | 17% |
| 64 | 56,0% | 25% |
| 32 | **61,5%** | 28% |

Daí o `scan` ganhar `--window` e `--stride`. Mesmo no melhor caso são 61,5% contra os 94,1% do
Chrono Trigger — a detecção por janela deslizante tem um teto quando o texto vem picado, e este
número fica registrado como a limitação que é, não como meta cumprida.

Os tradutores também remapearam pontuação para letras acentuadas — `ã` ocupa o slot `0x3B`, que no
original era `;`. É o `--sacrifice` mais uma vez, agora numa tabela própria em vez de Latin-1.

## Castlevania: Aria of Sorrow (GBA) — Trans-Center, 2017

Baixado, **não aplicável**: o patch é para a ROM europeia `(E - M3)` e a que temos é `(U)`.

Ainda assim o README rendeu uma confirmação independente. Sobre acentuação, o tradutor escreveu:

> *"como não haviam todos, ... eu troquei alguns caracteres acentuados inúteis, como `ù`, `ì`, `ö`,
> pelos que faltavam"*

É exatamente o `--sacrifice` do `font accents`, descrito por quem fez à mão em 2006 — e a mesma
conclusão a que a ferramenta chega sozinha ao encontrar 2 tiles livres onde precisa de 8.
