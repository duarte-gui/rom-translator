# rom-translator

Traduz ROMs de videogame retro do começo ao fim: **acha o texto, descobre como o jogo o codifica,
traduz com IA, desenha as letras acentuadas que faltam na fonte e devolve um patch IPS/BPS.**

```bash
rom-translator auto "Dragon Warrior (U).nes" --to pt-BR --engine claude
```

```
· nes/ines-1
· triagem: automatica viavel -- o texto sai em frases inteiras
· extraidas 576 unidades
· round-trip: 576 unidades voltam identicas
· nomes proprios: Dragonlord Erdrick Gwaelin Lorik Tantegel Garinham e mais 11
· 30 unidades sem nenhuma palavra real ficaram de fora -- sao ruido do scanner
· 105 linhas nao voltaram do modelo -- repetindo (tentativa 1)
· traduzidas 541 unidades
· acentos: 9 necessarios, 3 tiles disponiveis (sacrificando Y)
·   desenhados: é=0x56 ã=0x57 á=0x3C
· escritas 389 unidades

pronto  389 unidades escritas, 3 acentos desenhados
  rom      Dragon Warrior (U) [pt-BR].nes
  bps      Dragon Warrior (U) [pt-BR].bps
```

Nenhuma tabela de caracteres foi fornecida. O `0x5F` do espaço, o `0x0A` do `a`, o `0x24` do `A`,
os nomes próprios do jogo e os glifos acentuados — tudo saiu da própria ROM.

> **Não distribui ROMs.** Entrada é a sua cópia do jogo, saída é um patch. É o modelo que as
> traduções de fã sempre usaram.

---

## Vale a pena tentar nesta ROM?

Essa é a pergunta que decide um projeto de tradução, e o `triage` responde em segundos, só lendo:

```
$ rom-translator triage "Dragon Warrior (U).nes"
alfabeto             espaco 0x5F · a-z 0x0A · A-Z 0x24
evidencia            595 palavras reais contra 0 do 2o candidato
tamanho das falas    mediana 17 · p90 44 · 4.5 palavras por unidade

AUTOMATICA VIAVEL -- o texto sai em frases inteiras
```

O que separa um caso do outro não é quanto texto a ROM tem, é o **comprimento** do que sai. Texto sem
compressão sai em frases; comprimido sai picado, porque cada byte que a tabela não conhece corta a
sequência. Medido em sete ROMs de três consoles — **acerta as sete**:

| ROM | mediana | veredito | e é mesmo |
|---|---:|---|---|
| Dragon Warrior (NES) | 17 | automática viável | sem compressão |
| Castlevania: Aria of Sorrow (GBA) | 11 | automática viável | ASCII puro |
| Faxanadu (NES) | 12 | automática viável | sem compressão |
| Final Fantasy III (SNES) | 8 | **parcial** | nomes legíveis, diálogo em DTE |
| Chrono Trigger (SNES) | 5 | texto comprimido | DTE |
| Illusion of Gaia (SNES) | 5 | texto comprimido | comprimido |
| Golden Sun (GBA) | 5 | texto comprimido | comprimido |

O Final Fantasy III cair em "parcial" é acerto, não empate: ele guarda nomes de item sem comprimir e
o diálogo comprimido.

---

## Como funciona

### Descobrir o alfabeto sem nenhuma tabela

Não adianta procurar a faixa de bytes mais frequente — numa ROM de SNES o código e os gráficos
abafam qualquer histograma. O que só o texto produz são **palavras**. Então cada um dos 231 alfabetos
possíveis é testado por quantas palavras reais gera, e o certo se separa por larga margem.

Três jogos, três arranjos, e cada um derrubou uma suposição:

| ROM | espaço | a-z | A-Z | arranjo |
|---|---|---|---|---|
| Chrono Trigger | `0xEF` | `0xBA` | `0xA0` | `A-Z` **antes** de `a-z` |
| Dragon Warrior | `0x5F` | `0x0A` | `0x24` | `A-Z` **depois** de `a-z` |
| Castlevania: AoS | `0x20` | `0x61` | `0x41` | ASCII (6 bytes entre `Z` e `a`) |

O critério que sobrevive aos três é o mesmo das minúsculas: **rebaixar a faixa candidata e contar
palavras reais**. Só o alinhamento certo transforma `Soma` em `soma`. Tentei antes pela vizinhança
(maiúscula é seguida de minúscula mais do que precedida) e em ASCII a janela errada pontuou mais alto.

### Desenhar as letras que a ROM não tem

Traduzir para português esbarra numa parede que não é de software: a fonte não tem `ã`, `ç` nem `õ`.
Nenhum ajuste de tabela resolve — o desenho precisa existir nos gráficos.

`font accents` compõe os glifos que faltam a partir dos que existem, aproveitando que uma minúscula
de 8×8 quase sempre deixa a linha de cima livre:

```
  a original        ã gerado
++++++++          +##+##++
+####+++          +####+++
  ++##++            ++##++
+#....            +#....
```

A parte que não dá para automatizar sem mentir é de onde vem o tile. A fonte do Dragon Warrior tem
**dois** livres e são precisos oito. Os outros vêm de reaproveitar letras — e o critério certo não é
"as que o português não usa", é **as que este jogo não usa**, ordenadas por raridade no script
inteiro. `J`, `X`, `Y` e `Z` não aparecem uma vez sequer ali: custo zero. `F` e `V` aparecem 39
vezes somadas, e essas 39 ocorrências, em falas ainda não traduzidas, passam a mostrar um acento no
lugar. A ferramenta faz a troca e diz o que custou.

Três traduções humanas confirmam o mecanismo de forma independente. O tradutor de Castlevania
escreveu em 2006:

> *"como não haviam todos, eu troquei alguns caracteres acentuados inúteis, como `ù`, `ì`, `ö`, pelos
> que faltavam"*

### Linhas coladas

Muitos jogos guardam diálogo em linhas de N caracteres coladas, sem espaço na quebra: `If you are
going` + `to see the king` vira `If you are goingto see the king` na ROM.

Tentei separar isso por dicionário e a tentativa se derrubou sozinha na medição: acerta `goingto` e
destrói `Dragonlord`, que vira `Dragon lord`. Também `Wolflord` e `Starwyvern`. **Um modelo de
linguagem lê o texto colado sem dificuldade e sabe que Dragonlord é um nome — porque lê a frase.**

O que o modelo *não* tem como saber é que a linha mede 16 caracteres: isso não está na língua, está
na tela. Então a largura continua sendo medida, pela concentração das junções numa mesma coluna
(20 de 23 no Faxanadu, nenhuma concentração no Dragon Warrior), e serve para re-quebrar a tradução
na volta.

### O portão que autoriza o resto

Antes de traduzir uma linha sequer, o `auto` reinsere o texto **original** e exige que a ROM volte
byte a byte. Se a tabela deduzida for ambígua, isso falha aqui — barato — em vez de corromper o jogo
num ponto que só aparece horas depois.

Não é decorativo: numa tabela que montei à mão, mapeei dois bytes distintos para o mesmo apóstrofo e
o portão travou a execução em 25 unidades.

---

## Medido contra traduções humanas

Uma tradução de fã é um dataset rotulado: os tradutores marcaram, byte a byte, onde o texto está.
`scripts/validate_patch.py` transforma qualquer par ROM + patch num gabarito. Quatro deles, quatro
lições — e o valor de cada um está no que **quebrou**:

| gabarito | o que mediu | o que quebrou |
|---|---|---|
| **Chrono Trigger** (SNES, CBT 1998) | recall de 94,1% | deu a primeira medida — e o viés que ela criou |
| **Golden Sun** (GBA, 2010) | 6.923 palavras na área nova | a **métrica**: expande a ROM em 565 KB em vez de editar no lugar |
| **Faxanadu** (NES, 2017) | recall de 54,1% | o **scanner**: texto picado tem teto |
| **Illusion of Gaia** (SNES, 2010) | recall de 63,4% | provou que os 94,1% eram exceção |

A janela de análise era de 256 bytes, escolhida contra o único gabarito que existia. Com mais dois
ficou claro que o Chrono Trigger é a exceção:

| janela | Chrono Trigger | Illusion of Gaia | Faxanadu |
|---:|---:|---:|---:|
| 256 (antiga) | **94,1%** | 34,5% | 23,9% |
| 64 (nova) | 93,5% | **63,4%** | **54,1%** |

O número antigo era um ajuste a um único jogo. Só apareceu como tal quando existiu um segundo ponto
de medida.

---

## O que uma tradução por LLM de verdade ensinou

Rodado contra um Hermes Agent na rede local, em Dragon Warrior. Quatro defeitos apareceram no
primeiro contato, e **nenhum era do modelo**:

**Traduzia lixo com confiança.** O `--limit` pegava as primeiras unidades, que são as de offset
baixo — gráfico que o scanner marcou como texto. O modelo traduziu `ihiyyA` para `Olá` e `wiyyyAwwy`
para `Ei você`, invenções que seriam gravadas por cima dos gráficos. Um modelo de linguagem nunca
responde "isso não é texto".

**Eu apagava hífen em silêncio.** A tabela deduzida não tem `-`, e minha limpeza removia o caractere,
produzindo `Oferecote`, `Dizse`, `trazerte`. O certo é dizer ao modelo quais caracteres existem — e
que acentos são permitidos porque os glifos serão desenhados depois, mas pontuação não.

**Ele ignora o limite de caracteres.** Uma segunda passada dizendo por quanto passou recupera só uma
fração.

**Ele engole lotes inteiros.** Uma rodada devolveu 30 de 30 linhas, a seguinte 12. Repetir as que
faltaram em lotes menores recuperou 100 de 105 numa rodada completa.

Resultado da rodada completa: **389 de 576 falas escritas, 75% dos caracteres do script**.

---

## Limites honestos

**Compressão é o muro.** Recuperar a tabela de compressão de um jogo é engenharia reversa do
descompressor dele. Nenhum atalho estatístico funcionou: a inferência aqui acerta 7 de 16 numa tabela
sintética conhecida e **zero** nas ROMs comprimidas reais. Para esses jogos, o `.tbl` vem de fora — e
verifiquei que dos cinco patches que baixei, nenhum trazia tabela junto.

**O scanner tem teto com texto picado.** 54% no Faxanadu contra 93% no Chrono Trigger. Passar disso
provavelmente exige outra abordagem, não outro ajuste de parâmetro.

**Realocação depende de ponteiro.** Mover uma fala que não coube exige saber onde ela termina e quem
aponta para ela. No Dragon Warrior o terminador foi descoberto (`0x52`), mas **não existe tabela de
ponteiros** — procurei entrelaçada e dividida, até `min_run=4`. As mensagens são achadas contando
terminadores, e aí não há ponteiro para reescrever.

**A ferramenta nunca rodou o jogo.** Todas as verificações são de bytes: round-trip, checksum interno
do SNES, patch reaplicando byte a byte. Nenhuma é comportamental.

---

## Comandos

```bash
rom-translator triage    jogo.nes                    # vale a pena tentar?
rom-translator auto      jogo.nes --to pt-BR         # a cadeia inteira

rom-translator identify  jogo.smc                    # plataforma, mapeamento, hashes
rom-translator scan      jogo.smc -o projeto.yaml    # acha o texto e deduz o alfabeto
rom-translator dump      projeto.yaml -o script.json
rom-translator preview   script.json --longest
rom-translator verify    projeto.yaml script.json    # o dump volta byte-idêntico?
rom-translator translate script.json --engine claude --to pt-BR
rom-translator build     projeto.yaml script.json -o traduzida.smc
rom-translator patch     jogo.smc traduzida.smc -o traducao.bps
rom-translator apply     jogo.smc traducao.ips -o jogo-ptbr.smc

rom-translator table gaps    projeto.yaml            # bytes que faltam na tabela, com contexto
rom-translator font  show    jogo.nes                # desenha os tiles no terminal
rom-translator font  accents projeto.yaml -o com-fonte.nes
rom-translator pointers  projeto.yaml script.json
rom-translator dte       projeto.yaml                # propõe entradas de compressão
```

### Motores de tradução

| motor | para que serve |
|---|---|
| `claude` | API da Anthropic; melhor qualidade e melhor obediência ao limite de caracteres |
| `openai` | qualquer servidor no formato OpenAI — Hermes Agent, LM Studio, vLLM, llama.cpp, `/v1` do Ollama |
| `ollama` | Ollama nativo, uma linha por vez |
| `file` | lê traduções prontas de um YAML — para traduzir à mão usando o resto do pipeline |
| `dummy` | exercita a cadeia inteira sem gastar token |

Chaves saem de `~/.config/secrets/` (`anthropic.env`, `hermes.env`) ou das variáveis de ambiente.

### De onde vem o `.tbl`

1. **O `scan` escreve um** — deduz o alfabeto e grava. Para jogo sem compressão isso basta.
2. **`table gaps` mostra o que falta** — os bytes desconhecidos que aparecem *cercados de texto
   legível*, com contexto suficiente para deduzir cada um:
   ```
   0xFE  181 ocorrencias
       Hello[$2E]<FE>Could I help youwi
   0x2E  106 ocorrencias
       p youwith anything<2E>[$FC]What[$FE]would you li
   ```
   Lendo isso: `0x2E` é o ponto final e `0xFE` a quebra de linha.
3. **Para jogo comprimido, vem de fora** — das comunidades de romhacking, que distribuem tabelas à
   parte dos patches.

---

## Instalação

```bash
git clone https://github.com/duarte-gui/rom-translator
cd rom-translator
python3 -m venv .venv && .venv/bin/pip install -e '.[dev]'
.venv/bin/python -m pytest
```

Python 3.11+. Dependências: `click`, `rich`, `numpy`, `pyyaml` — mais `anthropic` para o motor Claude.

## Exemplos

- [`examples/dragon-warrior-ptbr/`](examples/dragon-warrior-ptbr/) — NES, com acentos desenhados
- [`examples/castlevania-ptbr/`](examples/castlevania-ptbr/) — GBA, a terceira plataforma
- [`examples/gabaritos/`](examples/gabaritos/) — o que cada tradução humana mediu, e o que quebrou

## Licença

MIT. O projeto não contém, não baixa e não distribui ROMs.
