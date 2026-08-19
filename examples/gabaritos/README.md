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

## Illusion of Gaia (SNES) — Hyllian, 2010

A segunda medição de SNES, feita para responder uma pergunta: os 94,1% do Chrono Trigger eram
regra ou sorte?

**Eram sorte.**

| | |
|---|---|
| patch | IPS, 111 KB, edita **no lugar** (o zip traz versão com e sem header) |
| diff | 5.458 regiões, 99.471 bytes (4,7% da ROM) |
| escrito em espaço livre | 138 regiões (5.256 bytes) — o resto sobrescreveu conteúdo |
| recall do scanner | **34,5%** com a janela antiga · **63,4%** com a nova |
| alfabeto | `0xAC / 0x80`, maiúsculas não detectadas (texto comprimido) |

Illusion of Gaia espalha o texto como o Faxanadu, não como o Chrono Trigger. Foi este par que,
somado ao Faxanadu, forçou a mudança de padrão abaixo.

O checksum interno **não** ficou válido depois de aplicar — ao contrário do Chrono Trigger, onde a
CBT o recalculou. Nem todo grupo faz isso, então o teste continua útil como sinal, mas não serve
como critério de falha.

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

Daí o `scan` ganhar `--window` e `--stride` — e, depois da segunda medição de SNES, daí a mudança
de padrão descrita abaixo. Mesmo assim a detecção por janela deslizante tem um teto quando o texto
vem picado, e esse número fica registrado como a limitação que é, não como meta cumprida.

Os tradutores também remapearam pontuação para letras acentuadas — `ã` ocupa o slot `0x3B`, que no
original era `;`. É o `--sacrifice` mais uma vez, agora numa tabela própria em vez de Latin-1.

## Castlevania: Aria of Sorrow (GBA) — Trans-Center, 2017

Baixado, **não aplicável**: o patch é para a ROM europeia `(E - M3)` e a que temos é `(U)`.

Ainda assim o README rendeu uma confirmação independente. Sobre acentuação, o tradutor escreveu:

> *"como não haviam todos, ... eu troquei alguns caracteres acentuados inúteis, como `ù`, `ì`, `ö`,
> pelos que faltavam"*

É exatamente o `--sacrifice` do `font accents`, descrito por quem fez à mão em 2006 — e a mesma
conclusão a que a ferramenta chega sozinha ao encontrar 2 tiles livres onde precisa de 8.


## O padrão mudou por causa destes gabaritos

A janela de análise era de 256 bytes. Ela tinha sido escolhida contra o Chrono Trigger — o único
gabarito que existia — que guarda o diálogo em blocos grandes e contíguos. Com mais dois pares,
ficou claro que isso é a exceção:

| janela | Chrono Trigger | Illusion of Gaia | Faxanadu |
|---:|---:|---:|---:|
| 256 (antiga) | **94,1%** | 34,5% | 23,9% |
| 64 (nova) | 93,5% | **63,4%** | **54,1%** |

O Chrono Trigger perde meio ponto; os outros dois quase dobram. O custo é sinalizar mais ROM
(24% → 40% no Chrono Trigger) e rodar cerca de duas vezes mais devagar — o filtro linguístico do
`dump` limpa o excesso depois. A dedução de alfabeto não só sobreviveu como ficou mais forte:
Faxanadu foi de 213 para 526 palavras reais, Illusion of Gaia de 264 para 520.

Vale dizer o que isso significa: **o número antigo era um ajuste a um único jogo.** Só apareceu como
tal quando existiu um segundo e um terceiro ponto de medida.

Dois dos três continuam abaixo da meta de 80%. Está registrado como limitação em aberto.
