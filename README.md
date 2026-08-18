# rom-translator

Pipeline genérico de tradução de ROMs: **extrai o texto → traduz com IA → reinsere respeitando
ponteiros e limites de espaço → gera um patch IPS/BPS**.

A ideia vem das traduções de fã dos anos 90/2000, que eram feitas à mão: dump de texto, montagem da
tabela de caracteres, reajuste de ponteiros, reinserção e distribuição em `.ips`. O rom-translator automatiza
esse ciclo, mantendo o mesmo modelo de distribuição — a ferramenta **nunca embute nem distribui ROMs**,
só produz patches que o usuário aplica na própria cópia.

## O que já existe ✅

- **Container de ROM** com remoção automática do header de 512 bytes das copiadoras antigas (SMC/FIG).
- **IPS**: ler e escrever, incluindo registros RLE, truncamento e o caso patológico do offset `0x454F46`
  (que colide com o marcador `EOF`).
- **BPS**: ler e escrever, com verificação de CRC32 — aplicar um patch na ROM errada **falha** em vez de
  gerar silenciosamente uma ROM corrompida.
- **Plugins de plataforma**: SNES (LoROM/HiROM/ExHiROM, com cálculo e correção do checksum interno),
  NES (iNES/NES 2.0), GBA, e um fallback genérico.
- **CLI**: `identify`, `apply`, `patch`, `inspect`.
- **CLI**: `identify`, `apply`, `patch`, `inspect`, `scan`, `dump`, `preview`, `verify`, `pointers`, `translate`, `build`.
- **Tabela de caracteres** `.tbl` com suporte a DTE/MTE, e a garantia de que
  `decode` e `encode` são inversas exatas — byte sem mapeamento vira `[$XX]` e volta igual.
- **Descoberta automática do alfabeto**, sem tabela prévia: cada um dos 231 alfabetos possíveis é
  testado por quantas *palavras reais* produz. O certo se separa por larga margem. As maiúsculas
  saem de uma assimetria de vizinhança — maiúscula é *seguida* por minúscula muito mais do que
  precedida por uma — que funciona tanto onde `A-Z` vem antes de `a-z` quanto onde vem depois.
- **Detecção de blocos de texto** pela assinatura estatística do espaçamento entre palavras.
- **Descoberta de tabelas de ponteiros**, com o filtro estrutural que separa sinal de ruído:
  passo constante, alvos em ordem crescente e um mínimo de ponteiros seguidos.
- **Reinserção conservadora**: cabe → escreve; sobra → completa com espaço; não cabe → realoca para
  espaço livre e reaponta, ou **não escreve** e reporta. Uma linha em inglês é melhor que uma ROM
  que trava depois de duas horas de jogo.
- **Realocação com consciência de banco**: com ponteiro de 16 bits a string tem que ficar no mesmo
  banco — sair dele produz um endereço que aponta para o lugar certo do banco errado.
- **Motores de tradução plugáveis**: Claude (saída estruturada, cache de prompt, glossário),
  Ollama local, e `dummy` para exercitar o pipeline sem gastar token.
- **Códigos de controle como tokens opacos** — `[END]`, `[LINE]`, `[$1F]` viram marcadores
  numerados antes de chegar ao modelo. O LLM nunca vê nem inventa um byte de controle.
- 219 testes, incluindo fuzz de round-trip dos dois formatos de patch.

## Uso

```bash
rom-translator identify jogo.smc                     # plataforma, mapeamento, título interno, hashes
rom-translator inspect  traducao.ips                 # o que o patch altera, sem aplicar
rom-translator apply    jogo.smc traducao.ips -o jogo-ptbr.smc
rom-translator patch    jogo.smc jogo-ptbr.smc -o traducao.bps

rom-translator scan     jogo.smc -o projeto.yaml     # acha os blocos de texto e deduz o alfabeto
rom-translator dump     projeto.yaml -o script.json  # extrai as unidades de texto
rom-translator preview  script.json --longest        # amostra do que foi extraído

rom-translator verify   projeto.yaml script.json     # o dump volta byte-idêntico?
rom-translator pointers projeto.yaml script.json -o script.json   # acha os ponteiros
rom-translator translate script.json --engine claude --to pt-BR --glossary g.yaml --notify
rom-translator build    projeto.yaml script.json -o traduzida.smc
rom-translator patch    jogo.smc traduzida.smc -o traducao.bps
```

### O que o `scan` faz sozinho

Rodado no Chrono Trigger (U), sem nenhuma tabela ou conhecimento prévio do jogo:

```
$ rom-translator scan "Chrono Trigger (U) [!].smc" -o ct.yaml
snes/hirom: 1699 blocos, 990.208 bytes (23,6% da ROM)
alfabeto deduzido: espaco=0xEF  a-z=0xBA  A-Z=0xA0  (483 palavras reais contra 181 do 2o lugar)

$ rom-translator dump ct.yaml -o ct.json && rom-translator preview ct.json --longest
0x3FD117    The Village of Magic
0x3FD103    The End of Time
0x3FD1A7    Forward to the Past
0x3FD1D0    The Magic Kingdom
0x3FD488    Save Battle Cursor
```

Os valores `0xEF/0xBA/0xA0` são o encoding real do Chrono Trigger, confirmado à mão — e foram
deduzidos do zero.

## Validação contra gabarito humano

O projeto usa a tradução PT-BR de **Chrono Trigger** feita pelo grupo CBT em 1998 (revisão 2010) como
gabarito. Aplicar aquele IPS produz um par *(ROM em inglês, ROM em português)* feito por tradutores
humanos — um dataset rotulado de graça, que mostra quais regiões da ROM contêm texto, como a tabela de
caracteres foi estendida para acentos e quais ponteiros precisaram ser reajustados.

```bash
python scripts/validate_chrono.py "Chrono Trigger (U) [!].smc" traducao.ips
```

A prova mais forte aí é que o **checksum interno do SNES da ROM traduzida continua válido** depois da
nossa aplicação — uma verificação independente de que os bytes foram para os lugares certos.

Resultado atual:

```
1. aplicação do patch                                            OK
2. round-trip de geração de patch (IPS e BPS)                    OK
3. dataset rotulado: 14.590 regiões, 157.853 bytes (3,8% da ROM)
4. scanner: recall de 94,1% sobre o que o tradutor humano alterou OK   (meta: 80%)
5. alfabeto deduzido sem tabela prévia: 0xEF / 0xBA / 0xA0        OK
```

### Limites honestos

**Realocação exige terminador.** `build --relocate` move para espaço livre o que não couber e
reescreve os ponteiros — mas só se a unidade terminar num token de fim. Sem terminador o jogo leria
além da string nova até topar com um byte de fim por acaso, então a ferramenta **recusa** em vez de
arriscar. Expansão de ROM ainda não existe.



O diálogo do Chrono Trigger usa **DTE/MTE** — bytes que representam pares e trechos de palavras — e
a tabela DTE do jogo não é recuperável de forma genérica (depende do descompressor de cada jogo). O
`rom-translator` **suporta DTE/MTE na tabela**, mas essas entradas precisam vir de um `.tbl` fornecido pelo
usuário. O que o `scan` deduz sozinho é o alfabeto; o texto não comprimido (nomes de itens e inimigos,
menus, títulos de capítulo) sai completo.

## Roteiro

| Marco | Conteúdo | Estado |
|---|---|---|
| **M0** | container de ROM, IPS/BPS ler+escrever, plugins de plataforma, CLI | ✅ |
| **M1** | tabela de caracteres (`.tbl` com DTE/MTE), relative search, detecção de blocos de texto, `scan`/`dump` | ✅ |
| **M2** | descoberta de tabelas de ponteiros, reinserção, `build`. *Critério inegociável:* `dump` + `build` sem alterar texto gera uma ROM **byte-idêntica** | ✅ |
| **M3** | motores de tradução plugáveis (Claude, Ollama, `dummy`), glossário e memória de tradução | ✅ |
| **M4** | geração do patch final e **realocação com reapontamento** ✅ · expansão de ROM ainda não | parcial |
| **M5** | NES validado ponta a ponta com uma tradução real (ver `examples/`) · GBA ainda só em teste unitário | parcial |

## Princípios de projeto

- **O core só conhece offsets de arquivo.** Todo mapeamento CPU↔arquivo, banco e formato de ponteiro
  mora no `PlatformPlugin`. Adicionar um console = adicionar um plugin, sem tocar no core.
- **Códigos de controle são tokens opacos**, nunca texto. `[END] [WAIT] [NAME]` viram placeholders antes
  de irem para o LLM e são restaurados depois — o modelo não vê nem inventa bytes de controle.
- **Orçamento de tamanho é restrição dura.** Cada unidade de texto carrega seu `max_len`; tradução que
  estoura é re-pedida com o limite explícito, e só então parte para repointing.
- **Escrita conservadora**: cabe no lugar → reaponta para espaço livre → expande a ROM (último recurso,
  com aviso de incompatibilidade).
- **Falhar alto.** Compressão não suportada é reportada como não suportada, nunca "traduzida" em lixo.

## Prior art

| Projeto | O que faz | Lacuna |
|---|---|---|
| [FamiLator](https://github.com/Matt-Retrogamer/FamiLator) | extrai → traduz (Ollama) → reinsere, com ponteiros | só NES/Famicom |
| [Meowth-GBA-Translator](https://github.com/Olcmyk/Meowth-GBA-Translator) | GBA extract→traduz→build via LLM | só Pokémon (depende do decomp) |
| [GameStringer](https://github.com/rouges78/GameStringer) | detecta engine, extrai, traduz, repatcheia | jogos de PC, não ROM de console |
| [UniPatcher](https://github.com/btimofeev/UniPatcher) · [rombp](https://github.com/blakesmith/rombp) · [PyPatcherGBA](https://github.com/jarrowsmith123/PyPatcherGBA) | aplicam IPS/BPS/UPS/xdelta | não traduzem |
| [retroarch-ai-translator](https://github.com/CrazyKitty357/retroarch-ai-translator) | OCR da tela em tempo real | não toca na ROM, não gera patch |
| [Kruptar](https://romhack.github.io/doc/kruptarPlugins/) | dump/insert com recálculo de ponteiros e DTE/MTE | manual, Windows, sem IA |

O espaço vazio: multi-plataforma por plugin **+** descoberta automática de tabela/ponteiros **+** LLM com
provedor plugável **+** saída em patch. É o que o rom-translator persegue.

## O pipeline completo, verificado

Com `--engine dummy`, sem gastar um token, no Chrono Trigger real:

```
ROM → scan → dump → translate → build → patch → apply → byte-idêntico à ROM construída
```

E o marco de segurança do M2, que autoriza tudo o que vem depois:

```
$ rom-translator verify ct.yaml ct-script.json
ok 6.116 unidades sobrevivem ao round-trip intactas

$ rom-translator build ct.yaml ct-script.json -o rebuild.smc   # sem nenhuma tradução
$ cmp "Chrono Trigger (U) [!].smc" rebuild.smc            # idêntica, byte a byte
```

Se `encode(decode(bytes))` não devolvesse os mesmos bytes, qualquer tradução construída em cima
corromperia a ROM em algum ponto que só apareceria horas depois de jogo.

## Segunda plataforma: Dragon Warrior (NES) em português

Um NES, um encoding diferente, e a mesma ferramenta — sem uma linha específica do jogo:

```
$ rom-translator scan "Dragon Warrior (U) (PRG1) [!].nes" -o dw.yaml
nes/ines-1: 25 blocos, 25.088 bytes (30,6% da ROM)
alfabeto deduzido: espaco=0x5F  a-z=0x0A  A-Z=0x24  (602 palavras reais contra 0 do 2o lugar)
```

Depois de traduzir 40 falas e reconstruir:

| | |
|---|---|
| EN | `King Lorik will record thy deeds in his Imperial Scroll so thou may return to thy quest later` |
| PT | `O Rei Lorik registrara teus feitos no Pergaminho Imperial para que retornes depois` |
| EN | `Then came the Dragonlord who stole the precious globe and hid it in the darkness` |
| PT | `Entao veio o Dragonlord que roubou a preciosa esfera e a escondeu nas trevas` |

Header iNES preservado, gráficos intactos, 3,22% dos bytes alterados, e o patch (IPS e BPS) reaplica
na ROM original reproduzindo a traduzida byte a byte. O material está em
[`examples/dragon-warrior-ptbr/`](examples/dragon-warrior-ptbr/).

Esse jogo também consertou um erro de projeto: o detector de maiúsculas assumia que `A-Z` precede
`a-z`, como no Chrono Trigger. Dragon Warrior faz o contrário. O critério passou a ser a assimetria
de vizinhança, que vale nos dois.

## Desenvolvimento

```bash
python3 -m venv .venv && .venv/bin/pip install -e '.[dev]'
.venv/bin/python -m pytest
```

Para usar o motor Claude, a chave vai em `~/.config/secrets/anthropic.env` (mode 600) como
`ANTHROPIC_API_KEY=...`, ou na variável de ambiente. Rodadas longas aceitam `--notify`, que avisa
no Telegram ao terminar.

## Licença e ROMs

Código sob MIT. O projeto não contém, não baixa e não distribui ROMs — entrada é a cópia do usuário,
saída é um patch. É exatamente o modelo que as traduções de fã sempre usaram.
