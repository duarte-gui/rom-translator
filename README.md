# romtrans

Pipeline genérico de tradução de ROMs: **extrai o texto → traduz com IA → reinsere respeitando
ponteiros e limites de espaço → gera um patch IPS/BPS**.

A ideia vem das traduções de fã dos anos 90/2000, que eram feitas à mão: dump de texto, montagem da
tabela de caracteres, reajuste de ponteiros, reinserção e distribuição em `.ips`. O romtrans automatiza
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
- **CLI**: `identify`, `apply`, `patch`, `inspect`, `scan`, `dump`, `preview`.
- **Tabela de caracteres** `.tbl` com suporte a DTE/MTE, e a garantia de que
  `decode` e `encode` são inversas exatas — byte sem mapeamento vira `[$XX]` e volta igual.
- **Descoberta automática do alfabeto**, sem tabela prévia: cada um dos 231 alfabetos possíveis é
  testado por quantas *palavras reais* produz. O certo se separa por larga margem.
- **Detecção de blocos de texto** pela assinatura estatística do espaçamento entre palavras.
- 182 testes, incluindo fuzz de round-trip dos dois formatos de patch.

## Uso

```bash
romtrans identify jogo.smc                     # plataforma, mapeamento, título interno, hashes
romtrans inspect  traducao.ips                 # o que o patch altera, sem aplicar
romtrans apply    jogo.smc traducao.ips -o jogo-ptbr.smc
romtrans patch    jogo.smc jogo-ptbr.smc -o traducao.bps

romtrans scan     jogo.smc -o projeto.yaml     # acha os blocos de texto e deduz o alfabeto
romtrans dump     projeto.yaml -o script.json  # extrai as unidades de texto
romtrans preview  script.json --longest        # amostra do que foi extraído
```

### O que o `scan` faz sozinho

Rodado no Chrono Trigger (U), sem nenhuma tabela ou conhecimento prévio do jogo:

```
$ romtrans scan "Chrono Trigger (U) [!].smc" -o ct.yaml
snes/hirom: 1699 blocos, 990.208 bytes (23,6% da ROM)
alfabeto deduzido: espaco=0xEF  a-z=0xBA  A-Z=0xA0  (483 palavras reais contra 181 do 2o lugar)

$ romtrans dump ct.yaml -o ct.json && romtrans preview ct.json --longest
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

### Um limite honesto

O diálogo do Chrono Trigger usa **DTE/MTE** — bytes que representam pares e trechos de palavras — e
a tabela DTE do jogo não é recuperável de forma genérica (depende do descompressor de cada jogo). O
`romtrans` **suporta DTE/MTE na tabela**, mas essas entradas precisam vir de um `.tbl` fornecido pelo
usuário. O que o `scan` deduz sozinho é o alfabeto; o texto não comprimido (nomes de itens e inimigos,
menus, títulos de capítulo) sai completo.

## Roteiro

| Marco | Conteúdo | Estado |
|---|---|---|
| **M0** | container de ROM, IPS/BPS ler+escrever, plugins de plataforma, CLI | ✅ |
| **M1** | tabela de caracteres (`.tbl` com DTE/MTE), relative search, detecção de blocos de texto, `scan`/`dump` | ✅ |
| **M2** | descoberta de tabelas de ponteiros, reinserção, `build`. *Critério inegociável:* `dump` + `build` sem alterar texto tem que gerar uma ROM **byte-idêntica** | — |
| **M3** | motores de tradução plugáveis (Claude, Ollama, DeepL, `dummy`), glossário e memória de tradução | — |
| **M4** | repointing, expansão de ROM e geração do patch final | — |
| **M5** | consolidar os plugins NES e GBA no pipeline completo | — |

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
provedor plugável **+** saída em patch. É o que o romtrans persegue.

## Desenvolvimento

```bash
python3 -m venv .venv && .venv/bin/pip install -e '.[dev]'
.venv/bin/python -m pytest
```

## Licença e ROMs

Código sob MIT. O projeto não contém, não baixa e não distribui ROMs — entrada é a cópia do usuário,
saída é um patch. É exatamente o modelo que as traduções de fã sempre usaram.
