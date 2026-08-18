# Castlevania: Aria of Sorrow (GBA) — a terceira plataforma

Serve para uma coisa: mostrar que a arquitetura de plugins segura um console com endereçamento
completamente diferente (ponteiro de 32 bits, mapa plano em `0x08000000`) sem nada específico do jogo.

```
$ rom-translator identify "Castlevania - Aria of Sorrow (U)(GBATemp).gba"
plataforma      gba  (confianca 100%)
titulo interno  CASTLEVANIA2
game_code       A2CE

$ rom-translator scan ... -o cv.yaml --threshold 0.4 --min-length 256
gba/flat: 1225 blocos, 548.608 bytes (6,5% da ROM)
alfabeto deduzido: espaco=0x20  a-z=0x61  A-Z=0x41  (1368 palavras reais contra 27 do 2o lugar)
```

`0x20 / 0x61 / 0x41` é ASCII — e foi esta ROM que obrigou o detector de maiúsculas a parar de assumir
que as faixas são adjacentes: em ASCII há seis bytes de pontuação entre `Z` e `a`.

O dump traz 2.049 unidades legíveis, incluindo o texto **alemão** que o cartucho carrega junto do
inglês. Traduzi onze descrições de inimigo para exercitar o caminho completo; o BPS reaplica na ROM
original reproduzindo a traduzida byte a byte, com o header GBA intacto.

Sem acentos aqui: a fonte do jogo é gráfico comprimido, e `font accents` assume que o byte da tabela
é o índice do tile — o que vale no Dragon Warrior e não vale aqui.
