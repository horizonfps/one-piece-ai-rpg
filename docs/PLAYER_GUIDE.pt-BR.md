# Guia do Jogador — One Piece RPG

# Nota do Autor

One Piece RPG é um projeto solo feito por mim (horizon) onde você como jogador vivencia a história canon de One Piece como uma variável nova no mundo. Diferente do usual que a maioria das pessoas fazem, O bando dos Mugiwara existem nesse jogo e no momento que você estiver saindo aos mares, eles estarão saindo de Egghead. Jogue da forma que quiser, deseja ser o Rei dos Piratas antes do Luffy? Você pode. Deseja ser um vilão? Você também pode, o maior limite nesse jogo é sua imaginação. Diferente de todos os RPGs, não há rolagem de dados na sua frente, todo combate, encontro fortuito, drama é feito pelo LLM e você tem controle total sobre a sua própria história.

Meu objetivo principal foi sempre entregar uma história agradável e divertida a todos os fans de One Piece, espero que gostem e prestem bem atenção no tutorial!

## Começando

Na tela de título você cria uma campanha nova ou abre uma salva. Cada campanha é um save independente (você pode ter várias).

### Criação de personagem

Todo personagem criado terá suas caracteristicas fixadas em certos pontos.

- Todos saem do East Blue (Foosha)
- Todos saem para o mar aos 17 anos
- Bounty inicial sempre é 0

Com isso, o jogador sempre será o mais novo, 2 anos mais jovem que o Luffy

Fora essas características fixadas, temos a ficha de personagem customizada

- **Nome, gênero, arma**: Texto livre.
  - Observação: Não é recomendado a nomeação de armas já existentes no mundo de One Piece, não foi testado como o LLM reage a duplicatas no mundo. Altamente recomendado a criatividade em desenvolver uma arma original
- **Tier-alvo**: `NORMAL`, `SKILLED` ou `STRONG`. Basicamente aqui é onde você decide a dificuldade que você quer jogar no ínicio, STRONG é um nível muito alto para a maioria dos antagonistas no East Blue. Já NORMAL você terá mais momentos dramáticos e ação sempre, também ótimas cenas de powerup. 
- **Classe**: Define como você luta. Usuários de fruta quando estiverem impedidos de usar a fruta (kairoseki), caem 1/2 tiers
- **Traits**: Rolados (2 a 5, sorteio de um catálogo). Reroll ilimitado. Podem ser editados, as traits não agem pelo personagem, apenas irão dar sinais.
  - Ex: Personagem com trait Esfomeado não vai fazer seu personagem ir comer automaticamente, mas se ficar muito tempo sem comer, a barriga irá roncar involuntariamente.
- **Fruta do Diabo**: Essa é uma opção delicada e bem curada, todas as frutas originais de One Piece estão aqui. Escolhi a dedo todas que fazem sentido estarem disponíveis na pool de escolha.
  - Ex: Gomu Gomu não é possível escolher, iria acabar com todo o gancho da história do luffy relacionado à Nika por exemplo
  - Ex2: Mera Mera foi possível colocar aqui, já que ela aparece em Dressrosa, então a história muda pouco. Com Dressrosa tendo como premiação uma fruta SMILE em vez da Mera Mera, com isso Sabo ainda aparece em Dressrosa para investigar, encontra o Luffy e em troca do downgrade do Sabo, ele fica mais proeficiente no estilo de luta Ryusoken.
- **Sonho**: Texto livre. O Diretor e o Narrador improvisam ganchos a partir dele.

## Jogando um turn

Há um campo de texto e um seletor com dois tipos de ação:

### Fazer (DO)

Uma ação no mundo. Escreva na 1ª ou 3ª pessoa o que você faz; ponha **fala entre aspas** dentro
do texto:

```
Cruzo os braços e encaro o homem. "Sai da frente. Não vou repetir."
```

O Narrador renderiza exatamente o que você declarou e **não fala nem age por você**. Se você não
escreveu diálogo, seu personagem age calado.

### Meta (META)

Fora de personagem. Três usos:

- **Pergunta**: tira uma dúvida ("o que esse NPC sabe sobre mim?") sem gastar um turn.
- **Lembre**: registra uma diretiva permanente que o jogo passa a respeitar:
  `lembre: meu pai era um vice-almirante da Marinha`
  O Narrador incorpora sem fricção, a história é sua.
- **esqueça**: desativa uma diretiva registrada.
- Perguntas gerais.
  Quem é o mais forte do meu bando?
  Quem é o mais forte nessa ilha?

## O mundo reage

- **Mapa**: janela read-only da sua posição e das ilhas descobertas. Viagem se decide narrando.
- **Bounty & Nemesis**: atos públicos rendem bounty (com atraso de alguns dias, como no canon). Um
  **nemesis Marine** evolui te perseguindo ao longo da campanha. (Sorry Warner Bros)
- **News Coo**: o jornal chega de tempos em tempos com o que aconteceu no mundo (e às vezes com
  você na capa).
- **Den Den Mushi & Vivre Card**: comunicação à distância. NPCs pareados podem te ligar; a vivre
  card escurece se o dono está em perigo.
- **Navio, economia, técnicas, alianças, reputação por facção**: tudo emerge da narração e aparece
  nos painéis do HUD.

## HUD e edição (tudo editável)

O menu (☰) abre um drawer com abas: **ficha, memória, técnicas, inventário, navio, reputação,
alianças, comunicação, diretivas, jornal, tramas, final**. Quase tudo é **editável inline** — nome,
sonho, tier, alignment, técnicas, memória, até a narração de um turn. Editar **não avança o turn**
nem re-escreve a memória; o próximo turn simplesmente lê o estado novo.

Há também:

- **↻ regenerar narração** — re-roda o último turn, tem uma box onde você pode preencher algo que você quer que seja diferente do gen antigo
- **rewind narração** - volta um turn caso você queira refazer uma ação (limite de 3)
- **devtools** — trace de cada chamada de LLM do turn (input/output/uso de tokens).

## Finais

Não há game-over por morte (seu personagem nunca morre por força bruta). Conforme alignment, bounty,
caos, tier e mundo amadurecem, **finais possíveis** aparecem (Rei dos Piratas, Yonko, e outros).
Você escolhe quando encerrar — o jogo gera um epílogo cinematográfico — e pode continuar jogando
depois (continue mode).

## Se algo der errado

- **"Assinatura Claude Max no limite"**: sua quota da janela atual esgotou (reseta em horas). Nada
  se perdeu; volte mais tarde e retome de onde parou.
- **"Não consegui narrar este input"**: o modelo recusou renderizar aquela ação (filtro de
  segurança). Sua ação volta pro campo; reformule e tente de novo. A campanha fica intacta.
- **Erro genérico**: tente de novo; nada é persistido pela metade.
