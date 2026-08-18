# Dragon Warrior (NES) em português

A primeira tradução feita ponta a ponta com o `rom-translator`, e a prova de que a
arquitetura de plugins segura mais de um console.

O `scan` descobriu sozinho, sem nenhuma tabela prévia:

```
nes/ines-1: 25 blocos, 25.088 bytes (30,6% da ROM)
alfabeto deduzido: espaco=0x5F  a-z=0x0A  A-Z=0x24  (602 palavras reais contra 0 do 2o lugar)
```

`0x5F / 0x0A / 0x24` é o encoding real do Dragon Warrior. Repare que aqui as maiúsculas ficam
**depois** das minúsculas (`0x0A + 26 = 0x24`), enquanto no Chrono Trigger ficam antes — foi esse
jogo que obrigou o detector a parar de assumir uma ordem.

## Como reproduzir

```bash
rom-translator scan "Dragon Warrior (U) (PRG1) [!].nes" -o dw.yaml --threshold 0.35 --min-length 128
rom-translator dump dw.yaml -o dw.json --min-chars 8
python aplicar.py dw.json traducao.yaml dw-ptbr.json
rom-translator build dw.yaml dw-ptbr.json -o "Dragon Warrior PT-BR.nes"
rom-translator patch "Dragon Warrior (U) (PRG1) [!].nes" "Dragon Warrior PT-BR.nes" -o dw-ptbr.bps
```

## O que está aqui, e o que não está

`traducao.yaml` tem as 40 falas traduzidas — texto próprio, nenhum byte de ROM. O patch **não** é
distribuído aqui: quem tem a própria cópia do jogo o regenera com os comandos acima, que é o modelo
que as traduções de fã sempre usaram.

Sem acentos de propósito: a tabela que o `scan` deduz tem `a-z`, `A-Z` e espaço. Acentuar exige
editar a fonte da ROM e estender a tabela — trabalho de romhacking que a ferramenta ainda não faz.

Cada tradução coube no espaço da original (folga média de 9,8 bytes), então nenhuma precisou de
realocação.
