/**
 * Trilha da área Aprender. Conteúdo em texto simples; **negrito** é marcado com dois asteriscos.
 * Cada aula: 3 a 5 minutos, um visual interativo quando ajuda, um "na prática" e um quiz curto.
 */

export type VisualId =
  | "long-short"
  | "cost"
  | "candle"
  | "timeframe"
  | "trend"
  | "moving-average"
  | "rsi"
  | "ema-cross"
  | "rsi-strategy"
  | "breakout"
  | "regime"
  | "risk"
  | "recovery"
  | "expectancy";

export type Block =
  | { p: string }
  | { h: string }
  | { visual: VisualId; title: string }
  | { tip: string }
  | { warn: string }
  | { list: string[] }
  | { steps: string[] }
  | { table: { head: string[]; rows: string[][] } };

export interface Question {
  q: string;
  options: string[];
  answer: number;
  why: string;
}

export interface Lesson {
  slug: string;
  title: string;
  minutes: number;
  summary: string;
  blocks: Block[];
  quiz: Question[];
  practice?: { text: string; href: string; label: string };
  sources?: { label: string; url: string }[];
}

export interface Module {
  id: string;
  title: string;
  description: string;
  lessons: Lesson[];
}

export const MODULES: Module[] = [
  {
    id: "primeiros-passos",
    title: "Primeiros passos",
    description: "O que é o mercado, como se ganha na alta e na queda e quanto custa cada operação.",
    lessons: [
      {
        slug: "o-que-e-o-mercado",
        title: "O que é o mercado (e o que um robô faz)",
        minutes: 3,
        summary: "Compradores, vendedores e por que o preço se mexe. Cripto, forex e B3 em um minuto.",
        blocks: [
          {
            p: "Mercado é o lugar onde quem quer comprar encontra quem quer vender. O preço é simplesmente o valor do último negócio fechado. Quando há mais gente com pressa para comprar, o preço sobe; quando a pressa é para vender, cai.",
          },
          { h: "Três mercados que você vai ver por aqui" },
          {
            list: [
              "**Cripto**: moedas digitais como bitcoin e ether. Funciona 24 horas, todos os dias. Na Binance, o par **BTCUSDT** mostra o preço de 1 bitcoin em USDT, uma moeda digital que acompanha o dólar.",
              "**Forex**: troca de moedas de países, como euro por dólar (**EURUSD**). Abre de domingo à noite até sexta à noite e costuma usar alavancagem. Aqui, ele chega pelas corretoras que usam a plataforma cTrader.",
              "**B3**: a bolsa brasileira. Ações e contratos como o mini-índice (**WIN**) e o mini-dólar (**WDO**), em horário comercial.",
            ],
          },
          { h: "E o robô?" },
          {
            p: "Um robô de negociação é um conjunto de regras escritas com antecedência: \"se acontecer isso, compre; se acontecer aquilo, venda\". Ele segue as regras sem medo, sem pressa e sem cansaço. Mas ele **não adivinha o futuro**: se as regras forem ruins, ele vai errar com a mesma disciplina.",
          },
          {
            tip: "Por isso o caminho no OráculoInvest é sempre o mesmo: testar as regras no passado (backtest), depois na simulação com preço real e só então, se os números convencerem, em conta real.",
          },
        ],
        quiz: [
          {
            q: "O par BTCUSDT cotado a 62.000 significa que…",
            options: ["1 bitcoin custa 62.000 USDT", "1 USDT custa 62.000 bitcoins", "O bitcoin subiu 62.000% no ano"],
            answer: 0,
            why: "O par mostra quanto da segunda moeda (USDT) é preciso para comprar 1 unidade da primeira (BTC).",
          },
          {
            q: "Qual frase descreve melhor um robô de negociação?",
            options: ["Um programa que prevê o preço de amanhã", "Regras fixas executadas sem emoção", "Um jeito garantido de ganhar no mercado"],
            answer: 1,
            why: "O robô só executa regras. A qualidade do resultado depende das regras e do mercado, não da máquina.",
          },
        ],
      },
      {
        slug: "comprado-e-vendido",
        title: "Comprado e vendido: ganhar na alta e na queda",
        minutes: 3,
        summary: "Como se ganha quando o preço cai e por que a alavancagem é uma faca de dois gumes.",
        blocks: [
          { p: "Estar **comprado** é o jeito intuitivo: você compra esperando vender mais caro depois. Ganha se o preço sobe." },
          {
            p: "Estar **vendido** é o contrário: você vende primeiro (um ativo emprestado pela corretora) e recompra depois. Se recomprar mais barato, a diferença é o seu lucro. Ganha se o preço cai.",
          },
          { visual: "long-short", title: "Mexa no preço e veja o resultado de cada lado" },
          {
            p: "**Alavancagem** é operar com mais do que você tem, usando dinheiro da corretora. Com 10x, um movimento de 1% vira 10% no seu bolso. Mas uma queda de 10% contra você leva **toda** a margem.",
          },
          {
            tip: "No OráculoInvest, robôs de cripto (Binance à vista) só operam comprados. Robôs de forex podem operar comprados e vendidos, se você ligar a opção \"Direção\" ao criar o robô.",
          },
          { warn: "Alavancagem não muda a qualidade de uma estratégia. Ela só faz o resultado, bom ou ruim, chegar mais rápido." },
        ],
        quiz: [
          {
            q: "Você está vendido em 100 e o preço cai para 90. O que aconteceu?",
            options: ["Você ganhou", "Você perdeu", "Nada, porque ainda não vendeu"],
            answer: 0,
            why: "Vendido ganha na queda: vendeu a 100 e pode recomprar a 90.",
          },
          {
            q: "Com alavancagem de 10x, o preço anda 5% contra você. Sobre a margem, você…",
            options: ["Perde 5%", "Perde 50%", "Perde 0,5%"],
            answer: 1,
            why: "A alavancagem multiplica o movimento: 5% × 10 = 50% da margem.",
          },
        ],
      },
      {
        slug: "ordens-e-custos",
        title: "Ordens, taxas e spread: o custo de cada operação",
        minutes: 4,
        summary: "Ordem a mercado, limitada e stop. E a conta que todo robô precisa vencer primeiro.",
        blocks: [
          { h: "Os três tipos de ordem que importam" },
          {
            list: [
              "**A mercado**: compra ou vende agora, pelo melhor preço disponível. Executa na hora, mas o preço pode escorregar um pouco (o chamado slippage).",
              "**Limitada**: \"só compro se chegar a 98\". Você controla o preço, mas pode não ser executada.",
              "**Stop**: vira ordem a mercado quando o preço atinge um nível. É o jeito de limitar a perda (stop loss) ou garantir o lucro (alvo).",
            ],
          },
          { h: "O custo invisível" },
          {
            p: "Toda operação paga alguma coisa: a **taxa** da corretora e o **spread**, a diferença entre o preço de compra e o de venda naquele instante. Parece pouco, uma fração de 1%, mas o robô paga isso em toda entrada e toda saída, ganhando ou perdendo.",
          },
          { visual: "cost", title: "Quanto custa operar muito" },
          {
            tip: "O backtest do OráculoInvest já desconta taxa e slippage de cada operação. Desconfie de qualquer resultado que não mostre os custos.",
          },
        ],
        quiz: [
          {
            q: "Qual ordem garante a execução, mas não o preço exato?",
            options: ["Limitada", "A mercado", "Nenhuma das duas"],
            answer: 1,
            why: "A ordem a mercado executa na hora pelo melhor preço disponível, que pode ser um pouco pior que o da tela.",
          },
          {
            q: "Um robô faz 10 operações por dia pagando 0,2% em cada. Em 22 dias, o custo é de…",
            options: ["2,2% do capital", "44% do capital", "0,2% do capital"],
            answer: 1,
            why: "10 × 0,2% × 22 = 44%. Operar demais pode tornar qualquer estratégia perdedora.",
          },
        ],
      },
    ],
  },
  {
    id: "graficos",
    title: "Lendo gráficos",
    description: "Candles, tempo gráfico, tendência e os dois indicadores que os robôs usam.",
    lessons: [
      {
        slug: "candle",
        title: "O candle: a história de um período em uma vela",
        minutes: 3,
        summary: "Abertura, fechamento, máxima e mínima. Aprenda a ler um candle em 10 segundos.",
        blocks: [
          {
            p: "O gráfico de candles (velas) é o mais usado no mercado. Cada vela resume um período, que pode ser 5 minutos, 1 hora ou 1 dia, com quatro preços: onde **abriu**, onde **fechou**, a **máxima** e a **mínima**.",
          },
          { visual: "candle", title: "Anatomia do candle" },
          {
            p: "Um candle sozinho conta pouco. O que importa é a sequência: vários corpos verdes grandes mostram compradores no controle; pavios longos mostram que o preço tentou ir e foi rejeitado.",
          },
          { tip: "Na tela de cada robô você vê o gráfico de candles do TradingView do mesmo par e tempo gráfico que o robô usa." },
        ],
        quiz: [
          {
            q: "Num candle verde, o fechamento fica…",
            options: ["Acima da abertura", "Abaixo da abertura", "Sempre na máxima"],
            answer: 0,
            why: "Verde (de alta) significa que o preço terminou o período mais alto do que começou.",
          },
          {
            q: "Um pavio longo embaixo do corpo indica que…",
            options: ["O preço nunca caiu", "O preço caiu, mas voltou a subir antes de fechar", "O mercado estava fechado"],
            answer: 1,
            why: "O pavio marca até onde o preço foi. Se ele foi longe e voltou, a queda foi rejeitada.",
          },
        ],
      },
      {
        slug: "tempo-grafico",
        title: "Tempo gráfico: o mesmo preço visto de perto e de longe",
        minutes: 3,
        summary: "Por que o robô de day trade olha candles de 5 minutos e o de swing olha de 4 horas.",
        blocks: [
          {
            p: "**Tempo gráfico** é quanto tempo cada candle representa. O mesmo mercado parece outro conforme a escolha: de perto (5 minutos, 1 hora) você vê cada oscilação; de longe (4 horas, diário) só a direção principal.",
          },
          { visual: "timeframe", title: "Os mesmos 10 dias em três tempos gráficos" },
          {
            list: [
              "**Tempo curto** (1 a 15 minutos): mais sinais e mais operações. Mais ruído e mais custo.",
              "**Tempo longo** (4 horas, diário): menos sinais, que costumam ser mais confiáveis. Operações que duram dias ou semanas.",
            ],
          },
          {
            tip: "Cada estratégia do OráculoInvest já vem com um tempo gráfico padrão: 5 minutos no cruzamento intradiário, 15 minutos na reversão por RSI, 4 horas no cruzamento swing e diário no rompimento de canal.",
          },
        ],
        quiz: [
          {
            q: "Quatro candles de 1 hora juntos formam…",
            options: ["Um candle de 4 horas", "Um candle diário", "Quatro candles de 4 horas"],
            answer: 0,
            why: "O candle de 4 horas abre na abertura do primeiro, fecha no fechamento do último e pega a máxima e a mínima dos quatro.",
          },
          {
            q: "Em tempo gráfico curto, normalmente…",
            options: ["Há menos operações e menos custo", "Há mais sinais, mais ruído e mais custo", "O preço oscila menos"],
            answer: 1,
            why: "De perto aparecem muito mais oscilações, e cada uma pode virar uma operação paga.",
          },
        ],
      },
      {
        slug: "tendencia-suporte-resistencia",
        title: "Tendência, suporte e resistência",
        minutes: 4,
        summary: "Topos e fundos dizem se o mercado sobe, cai ou anda de lado. É a pergunta mais importante.",
        blocks: [
          { p: "Antes de qualquer indicador, olhe os **topos** (pontos altos) e **fundos** (pontos baixos). Eles respondem a pergunta que decide qual estratégia faz sentido: o mercado está subindo, caindo ou de lado?" },
          { visual: "trend", title: "Os três tipos de mercado" },
          {
            p: "No mercado lateral aparecem o **suporte**, uma região onde as quedas costumam parar, e a **resistência**, onde as altas costumam parar. Quando o preço finalmente atravessa uma delas com força, chama-se **rompimento**.",
          },
          { warn: "Suporte e resistência são regiões, não linhas exatas. E todo nível um dia é rompido." },
        ],
        quiz: [
          {
            q: "Topos e fundos cada vez mais altos indicam…",
            options: ["Tendência de alta", "Tendência de queda", "Mercado lateral"],
            answer: 0,
            why: "Se cada queda para antes da anterior e cada alta vai mais longe, os compradores estão no controle.",
          },
          {
            q: "Resistência é…",
            options: ["Onde o preço costuma parar de cair", "Onde o preço costuma parar de subir", "O preço médio do dia"],
            answer: 1,
            why: "Resistência é o \"teto\": a região onde aparecem vendedores e a alta costuma parar.",
          },
        ],
      },
      {
        slug: "medias-moveis",
        title: "Médias móveis: tirando o ruído do preço",
        minutes: 4,
        summary: "O indicador mais simples e mais usado. Curta reage rápido, longa mostra a direção.",
        blocks: [
          {
            p: "A **média móvel** é a média dos últimos N fechamentos, recalculada a cada candle. Ela vira uma linha suave por cima do preço, que deixa a direção mais fácil de ver.",
          },
          { visual: "moving-average", title: "Mude o tamanho da média" },
          {
            list: [
              "Preço **acima** da média e média **subindo**: tendência de alta.",
              "Preço **abaixo** da média e média **caindo**: tendência de queda.",
              "Preço cruzando a média para cima e para baixo toda hora: mercado lateral.",
            ],
          },
          { p: "Existem dois tipos principais: a **simples (MMS)**, que dá o mesmo peso a todos os candles, e a **exponencial (MME)**, que dá mais peso aos recentes. Os robôs do OráculoInvest usam a exponencial." },
        ],
        quiz: [
          {
            q: "Uma média de 50 candles comparada a uma de 9…",
            options: ["Reage mais rápido às viradas", "É mais suave e avisa a virada com atraso", "É sempre mais alta"],
            answer: 1,
            why: "Quanto mais candles na conta, mais suave a linha e maior o atraso.",
          },
          {
            q: "Preço abaixo de uma média que está caindo sugere…",
            options: ["Tendência de alta", "Tendência de queda", "Nada"],
            answer: 1,
            why: "É o retrato clássico de tendência de queda.",
          },
        ],
      },
      {
        slug: "rsi",
        title: "RSI: o termômetro de força",
        minutes: 4,
        summary: "Um número de 0 a 100 que mostra se o preço subiu ou caiu rápido demais.",
        blocks: [
          {
            p: "O **RSI** (Índice de Força Relativa, criado por J. Welles Wilder em 1978) compara o tamanho das altas com o das quedas nos últimos 14 candles e resume tudo em um número de 0 a 100.",
          },
          { visual: "rsi", title: "O RSI no painel de baixo" },
          {
            list: [
              "**Acima de 70**: sobrecomprado. O preço subiu rápido demais e pode respirar.",
              "**Abaixo de 30**: sobrevendido. O preço caiu rápido demais e pode repicar.",
              "**Perto de 50**: equilíbrio.",
            ],
          },
          {
            warn: "Sobrevendido não quer dizer \"vai subir\". Numa tendência de queda forte, o RSI pode ficar abaixo de 30 por muito tempo, enquanto o preço continua caindo.",
          },
        ],
        quiz: [
          {
            q: "RSI em 22 indica que o preço…",
            options: ["Caiu rápido demais nos últimos candles", "Vai subir com certeza", "Está em tendência de alta"],
            answer: 0,
            why: "Abaixo de 30 é sobrevendido: a queda recente foi forte. Isso não garante repique.",
          },
          {
            q: "Em que mercado o RSI costuma funcionar melhor?",
            options: ["Lateral, oscilando entre suporte e resistência", "Tendência forte", "Tanto faz"],
            answer: 0,
            why: "Em tendência forte, o RSI fica muito tempo no extremo e engana. No lateral, os extremos costumam voltar ao meio.",
          },
        ],
      },
    ],
  },
  {
    id: "estrategias",
    title: "Estratégias",
    description: "As três famílias de estratégia usadas pelos robôs, onde cada uma ganha e onde cada uma perde.",
    lessons: [
      {
        slug: "cruzamento-de-medias",
        title: "Seguir a tendência: cruzamento de médias",
        minutes: 5,
        summary: "Compra quando a média rápida passa a lenta. Ganha muito na tendência e apanha no lateral.",
        blocks: [
          {
            p: "A ideia é pegar carona na tendência: duas médias, uma **rápida** e uma **lenta**. Quando a rápida cruza para cima da lenta, a alta ganhou força: compra. Quando cruza para baixo, vende.",
          },
          { visual: "ema-cross", title: "Teste o cruzamento de médias" },
          {
            p: "Repare no padrão: **poucos ganhos grandes e vários prejuízos pequenos**. A estratégia erra muito no lateral (o famoso \"serrote\") e compensa quando aparece uma tendência longa.",
          },
          {
            tip: "Robôs do OráculoInvest com essa estratégia: \"Cruzamento de médias (intradiário)\", com médias 9 e 21 em 5 minutos, e \"Cruzamento de médias (swing)\", com 20 e 50 em 4 horas.",
          },
        ],
        practice: { text: "Teste o cruzamento de médias no histórico real da Binance, com taxas.", href: "/painel/backtest", label: "Abrir o backtest" },
        quiz: [
          {
            q: "O cruzamento de médias costuma perder dinheiro em qual mercado?",
            options: ["Tendência forte", "Lateral", "Nenhum"],
            answer: 1,
            why: "No lateral, as médias se cruzam toda hora e cada cruzamento vira uma operação perdedora com custo.",
          },
          {
            q: "Por que uma estratégia de tendência pode ganhar acertando menos da metade das vezes?",
            options: ["Porque os ganhos são bem maiores que as perdas", "Porque a corretora devolve as taxas", "Não pode"],
            answer: 0,
            why: "Poucas tendências longas pagam muitas perdas pequenas. A taxa de acerto sozinha não diz nada.",
          },
        ],
      },
      {
        slug: "reversao-com-rsi",
        title: "Reversão à média com RSI",
        minutes: 5,
        summary: "Compra o exagero da queda e vende na volta. Ótima no lateral, perigosa na queda.",
        blocks: [
          {
            p: "Aqui a aposta é contrária: quando o preço cai rápido demais (RSI abaixo de 30), ele tende a voltar para perto da média. O robô compra o exagero e vende quando o RSI normaliza.",
          },
          { visual: "rsi-strategy", title: "Teste a reversão em cada tipo de mercado" },
          {
            p: "É o retrato oposto do cruzamento de médias: **muitos ganhos pequenos e, de vez em quando, uma perda grande**, quando a queda não para.",
          },
          {
            tip: "O robô \"Reversão por RSI\" do OráculoInvest só compra se o preço estiver acima da média de 200 candles (o filtro de tendência). Assim ele evita comprar quedas dentro de uma tendência de baixa. Use sempre um stop.",
          },
        ],
        practice: { text: "Compare a reversão com e sem filtro de tendência no backtest.", href: "/painel/backtest", label: "Abrir o backtest" },
        quiz: [
          {
            q: "Qual o maior risco de comprar quando o RSI está abaixo de 30?",
            options: ["A queda continuar (tendência de baixa)", "Pagar pouca taxa", "Nenhum, é sinal de compra garantido"],
            answer: 0,
            why: "Em tendência de queda, \"barato\" pode ficar ainda mais barato. Por isso o filtro de tendência e o stop.",
          },
          {
            q: "O perfil típico de uma estratégia de reversão é…",
            options: ["Poucos ganhos grandes e muitas perdas pequenas", "Muitos ganhos pequenos e algumas perdas grandes", "Só ganhos"],
            answer: 1,
            why: "Ela acerta muito, mas quando erra (a queda não volta) a perda costuma ser maior.",
          },
        ],
      },
      {
        slug: "rompimento-de-canal",
        title: "Rompimento de canal (Donchian)",
        minutes: 4,
        summary: "Compra quando o preço supera a máxima de N dias. A regra das famosas Tartarugas.",
        blocks: [
          {
            p: "O **canal de Donchian** marca a máxima e a mínima dos últimos N candles. Se o preço fecha acima da máxima de 20 dias, algo mudou: o robô compra e acompanha até o preço perder a mínima de 10 dias.",
          },
          { visual: "breakout", title: "Teste o rompimento" },
          {
            p: "Nos anos 1980, o trader Richard Dennis ensinou regras de rompimento parecidas, com canais de 20 e 55 dias, a um grupo de iniciantes que ficou conhecido como **as Tartarugas**. A lição continua valendo: regras simples, seguidas com disciplina e com controle de risco.",
          },
          {
            tip: "O robô \"Rompimento de canal\" do OráculoInvest usa 20 candles para entrar e 10 para sair, no gráfico diário. Em forex ele também pode operar vendido, no rompimento da mínima.",
          },
        ],
        practice: { text: "Veja o rompimento no histórico real e compare com comprar e segurar.", href: "/painel/backtest", label: "Abrir o backtest" },
        quiz: [
          {
            q: "Quando a estratégia de rompimento compra?",
            options: ["Quando o preço fecha acima da máxima dos últimos N candles", "Quando o RSI está abaixo de 30", "Quando o preço toca o suporte"],
            answer: 0,
            why: "Ela compra força: o preço superou tudo o que fez nos últimos N candles.",
          },
          {
            q: "O que costuma fazer a estratégia de rompimento perder?",
            options: ["Rompimentos falsos, que voltam para dentro do canal", "Tendências longas", "Taxas zero"],
            answer: 0,
            why: "Muitos rompimentos falham. A estratégia vive dos poucos que viram tendência.",
          },
        ],
      },
      {
        slug: "qual-a-melhor-estrategia",
        title: "Qual é a melhor estratégia?",
        minutes: 5,
        summary: "A resposta honesta: depende do mercado. E o que faz uma estratégia ser boa de verdade.",
        blocks: [
          {
            p: "Não existe uma estratégia que ganhe sempre. Cada família funciona num tipo de mercado e perde no outro. Veja as três com os mesmos parâmetros nos três mercados:",
          },
          { visual: "regime", title: "Mesmas estratégias, mercados diferentes" },
          { h: "O que a pesquisa mostra" },
          {
            list: [
              "**Seguir tendência** é das ideias mais estudadas. Um estudo publicado em 2012 por Moskowitz, Ooi e Pedersen encontrou o efeito em 58 mercados futuros (índices de ações, moedas, commodities e juros): o que subiu nos últimos 1 a 12 meses tende a continuar por um tempo. Mas há anos inteiros de resultado ruim.",
              "**Reversão à média** aparece em prazos curtos e em mercados que oscilam. Ganha com frequência, mas sofre quando surge uma tendência forte.",
              "**Day trade** com objetivo de viver disso raramente dá certo. Um estudo da FGV acompanhou quem começou a fazer day trade de mini-índice na B3 entre 2013 e 2015 e persistiu por mais de 300 pregões: **97% perderam dinheiro**.",
            ],
          },
          { h: "Como reconhecer uma estratégia boa" },
          {
            list: [
              "**Expectativa positiva depois dos custos**: ganha mais do que perde, já pagando taxas.",
              "**Queda máxima que você aguenta**: se ela cair 30% no caminho, você continuaria seguindo?",
              "**Poucos parâmetros e regras simples**: quanto mais \"ajustes finos\", maior a chance de só ter decorado o passado.",
              "**Funciona em períodos e ativos diferentes**, não só naquele gráfico escolhido a dedo.",
            ],
          },
          {
            tip: "Muita gente combina estratégias diferentes (uma de tendência e uma de reversão) com pouco dinheiro em cada uma. Quando uma vai mal, a outra costuma segurar.",
          },
          { warn: "Desconfie de quem promete a \"melhor estratégia\" ou um percentual fixo de ganho por mês. Resultado passado não garante resultado futuro." },
        ],
        sources: [
          { label: "Moskowitz, Ooi e Pedersen, Time Series Momentum (SSRN)", url: "https://papers.ssrn.com/abstract=2089463" },
          { label: "Chague, De-Losso e Giovannetti, Day trading for a living? (FGV)", url: "https://ideas.repec.org/p/fgv/eesptd/525.html" },
        ],
        quiz: [
          {
            q: "Qual é a melhor estratégia para todos os mercados?",
            options: ["Cruzamento de médias", "Reversão por RSI", "Nenhuma: cada uma funciona num tipo de mercado"],
            answer: 2,
            why: "Tendência ganha em tendência, reversão ganha no lateral. Saber em que mercado se está é metade do trabalho.",
          },
          {
            q: "No estudo da FGV, quantos day traders persistentes de mini-índice perderam dinheiro?",
            options: ["Cerca de 50%", "97%", "10%"],
            answer: 1,
            why: "97% dos que persistiram por mais de 300 pregões perderam dinheiro.",
          },
        ],
      },
      {
        slug: "day-trade-ou-swing-trade",
        title: "Day trade ou swing trade?",
        minutes: 4,
        summary: "Abrir e fechar no mesmo dia ou ficar dias na operação. Diferenças de custo, tempo e risco.",
        blocks: [
          {
            table: {
              head: ["", "Day trade", "Swing trade"],
              rows: [
                ["Duração da operação", "Minutos a horas, fecha no mesmo dia", "Dias a semanas"],
                ["Tempo gráfico", "1 a 15 minutos", "4 horas a diário"],
                ["Operações por mês", "Dezenas ou centenas", "Poucas"],
                ["Peso dos custos", "Alto", "Baixo"],
                ["Risco de gap (abrir longe do fechamento)", "Baixo", "Existe, principalmente em ações e forex no fim de semana"],
                ["Exige acompanhamento", "Constante, ou um robô", "Uma olhada por dia"],
              ],
            },
          },
          {
            p: "Para quem está começando, o swing trade costuma ser mais tranquilo: menos custo, menos ruído e mais tempo para pensar. O day trade exige uma estratégia com vantagem grande o bastante para pagar muitos custos.",
          },
          {
            tip: "No OráculoInvest, as estratégias marcadas como \"day\" usam tempo gráfico curto e encerram posições pelo prazo máximo. As marcadas como \"swing\" usam 4 horas ou diário.",
          },
        ],
        quiz: [
          {
            q: "Por que os custos pesam mais no day trade?",
            options: ["Porque a taxa por operação é maior", "Porque são muito mais operações, cada uma pagando taxa e spread", "Não pesam mais"],
            answer: 1,
            why: "A taxa é a mesma, mas multiplicada por muito mais operações.",
          },
        ],
      },
    ],
  },
  {
    id: "risco",
    title: "Risco e robôs",
    description: "Stop, tamanho da posição, como ler um backtest e o caminho seguro até a conta real.",
    lessons: [
      {
        slug: "stop-e-tamanho-da-posicao",
        title: "Stop, alvo e tamanho da posição",
        minutes: 5,
        summary: "A regra que mais protege o seu dinheiro: decidir quanto perder antes de entrar.",
        blocks: [
          {
            p: "O **stop** é o preço em que você admite que errou e sai. O **alvo** é onde você realiza o lucro. Definidos antes da entrada, eles tiram a emoção da decisão.",
          },
          {
            p: "Mas o segredo está no **tamanho da posição**. Muitos profissionais arriscam algo como 1% do capital por operação: se o stop for atingido, perdem só isso. O tamanho sai de uma conta simples: quanto você aceita perder dividido pela distância até o stop.",
          },
          { visual: "risk", title: "Calculadora de tamanho da posição" },
          { visual: "recovery", title: "Por que perder pouco importa tanto" },
          {
            tip: "Ao criar um robô no OráculoInvest, escolha o tamanho **pelo risco**: você diz quanto do saldo aceita perder no stop (ex.: 1%) e o robô faz essa conta a cada ordem. A prévia mostra o valor movimentado e a alavancagem antes de ligar, e o limite de alavancagem corta ordens grandes demais. Stop, alvo, perda máxima por dia e limite de operações também ficam no robô.",
          },
        ],
        quiz: [
          {
            q: "Capital de R$ 10.000, risco de 1% e stop a R$ 2 da entrada. Quantas unidades comprar?",
            options: ["50", "100", "500"],
            answer: 0,
            why: "1% de 10.000 = R$ 100 de risco. R$ 100 ÷ R$ 2 por unidade = 50 unidades.",
          },
          {
            q: "Quem perde 50% do capital precisa ganhar quanto para voltar ao início?",
            options: ["50%", "75%", "100%"],
            answer: 2,
            why: "Sobra metade. Para dobrar a metade, é preciso ganhar 100%.",
          },
        ],
      },
      {
        slug: "taxa-de-acerto-e-expectativa",
        title: "Taxa de acerto engana: entenda a expectativa",
        minutes: 4,
        summary: "Acertar 80% das vezes e perder dinheiro? É possível. Veja a conta que importa.",
        blocks: [
          {
            p: "A pergunta \"qual a assertividade do robô?\" é natural, mas incompleta. O que decide o resultado é a **expectativa**: quanto, em média, cada operação ganha ou perde, já contando os custos.",
          },
          { visual: "expectancy", title: "Simulador de expectativa" },
          {
            p: "Teste os dois botões. \"Acerta muito, ganha pouco\" parece ótimo até as poucas perdas grandes apagarem tudo. \"Acerta pouco, ganha muito\" passa longos períodos errando, mas a conta fecha.",
          },
          { tip: "No backtest do OráculoInvest, olhe junto a taxa de acerto, o \"ganho médio ÷ perda média\" e o fator de lucro. Nunca um sozinho." },
        ],
        quiz: [
          {
            q: "Acerta 50%, ganha 2% quando acerta e perde 1% quando erra. Sem custos, a expectativa é…",
            options: ["Negativa", "Zero", "Positiva: +0,5% por operação"],
            answer: 2,
            why: "0,5 × 2% − 0,5 × 1% = +0,5% por operação.",
          },
          {
            q: "O que mais diz sobre a qualidade de uma estratégia?",
            options: ["Só a taxa de acerto", "A expectativa depois dos custos", "O número de operações"],
            answer: 1,
            why: "A expectativa junta acerto, tamanho dos ganhos, tamanho das perdas e custos.",
          },
        ],
      },
      {
        slug: "como-ler-um-backtest",
        title: "Como ler um backtest sem se enganar",
        minutes: 5,
        summary: "Os números que importam e as armadilhas que fazem um teste parecer melhor do que é.",
        blocks: [
          { p: "O **backtest** aplica as regras da estratégia no histórico e mostra o que teria acontecido. É o melhor filtro que existe para descartar ideias ruins, desde que lido com cuidado." },
          { h: "Os números, em uma frase cada" },
          {
            list: [
              "**Resultado**: quanto o capital variou no período.",
              "**Comparação com comprar e segurar**: a estratégia fez melhor do que simplesmente comprar e esperar?",
              "**Queda máxima**: a pior sequência de perdas. É o que você teria que aguentar sem desligar o robô.",
              "**Taxa de acerto** e **ganho médio ÷ perda média**: juntos dizem se a expectativa é positiva.",
              "**Fator de lucro**: soma dos ganhos dividida pela soma das perdas. Acima de 1 ganha; abaixo de 1 perde.",
              "**Número de operações**: com menos de 30, o resultado pode ser só sorte.",
            ],
          },
          { h: "As três armadilhas" },
          {
            list: [
              "**Excesso de ajuste**: mexer nos parâmetros até o passado ficar perfeito. A estratégia decora o passado e falha no futuro. Prefira parâmetros redondos e estáveis: se 20 funciona e 22 não, desconfie.",
              "**Período escolhido a dedo**: testar só na grande alta. Teste em alta, queda e lateral.",
              "**Esquecer os custos**: sem taxa e slippage, todo day trade parece bom.",
            ],
          },
          { tip: "Uma boa prática: ajuste os parâmetros em um período (por exemplo, 2023 e 2024) e confira, sem mexer em nada, num período que você não usou (2025)." },
        ],
        practice: { text: "Rode um backtest e pratique a leitura dos números.", href: "/painel/backtest", label: "Abrir o backtest" },
        quiz: [
          {
            q: "Você ajustou os parâmetros até o backtest dar +300%. Qual o risco?",
            options: ["Nenhum, o resultado está comprovado", "Excesso de ajuste: a estratégia pode ter só decorado o passado", "Pagar imposto demais"],
            answer: 1,
            why: "Resultados perfeitos no passado costumam vir de ajuste excessivo. Confira num período que não foi usado.",
          },
          {
            q: "Fator de lucro de 0,8 significa…",
            options: ["Para cada R$ 1 perdido, ganhou R$ 0,80: perde dinheiro", "Ganhou 80%", "Acertou 80% das vezes"],
            answer: 0,
            why: "Abaixo de 1, a soma das perdas é maior que a dos ganhos.",
          },
        ],
      },
      {
        slug: "do-simulador-a-conta-real",
        title: "Do simulador à conta real",
        minutes: 3,
        summary: "O caminho seguro em quatro passos, e o que conferir antes de ligar o robô com dinheiro.",
        blocks: [
          {
            steps: [
              "**Backtest**: teste a estratégia no histórico, com custos, em mercados diferentes. Descarte o que não convence.",
              "**Simulação**: ligue o robô com saldo fictício e preço real por algumas semanas. Veja se o comportamento bate com o backtest.",
              "**Testnet ou conta demo**: mesma coisa, agora passando pela corretora de verdade, sem dinheiro real.",
              "**Conta real, pequena**: comece com uma parte do capital que você aceita perder. Aumente só depois de meses consistentes.",
            ],
          },
          { h: "Antes de ligar em conta real" },
          {
            list: [
              "A chave da API foi criada **sem permissão de saque** e com restrição de IP.",
              "Stop, perda máxima diária e limite de operações estão definidos.",
              "Você sabe qual queda máxima vai aceitar antes de desligar o robô, e vai respeitar isso.",
              "O dinheiro não fará falta para contas, emergências ou objetivos próximos.",
            ],
          },
          { warn: "Operar envolve risco de perder parte ou todo o capital. Robôs não eliminam esse risco; eles só executam as regras que você escolheu." },
        ],
        practice: { text: "Crie seu primeiro robô na simulação, sem dinheiro real.", href: "/painel/robos/novo", label: "Criar robô" },
        quiz: [
          {
            q: "Qual a ordem segura para colocar um robô em operação?",
            options: ["Conta real → simulação → backtest", "Backtest → simulação → testnet/demo → conta real pequena", "Direto na conta real com pouco dinheiro"],
            answer: 1,
            why: "Cada etapa filtra um tipo de erro antes de ele custar dinheiro.",
          },
          {
            q: "Que permissão a chave da API da corretora NUNCA deve ter?",
            options: ["Leitura", "Negociação", "Saque"],
            answer: 2,
            why: "O robô só precisa ler e negociar. Sem saque, mesmo uma chave vazada não tira dinheiro da sua conta.",
          },
        ],
      },
    ],
  },
];

export const LESSONS: Lesson[] = MODULES.flatMap((m) => m.lessons);

export function findLesson(slug: string): { lesson: Lesson; module: Module; index: number } | null {
  const index = LESSONS.findIndex((l) => l.slug === slug);
  if (index < 0) return null;
  const module = MODULES.find((m) => m.lessons.some((l) => l.slug === slug))!;
  return { lesson: LESSONS[index], module, index };
}

export const TOTAL_MINUTES = LESSONS.reduce((a, l) => a + l.minutes, 0);

/** Aula que explica cada estratégia dos robôs. */
export const STRATEGY_LESSON: Record<string, string> = {
  ema_cross_day: "cruzamento-de-medias",
  ema_cross_swing: "cruzamento-de-medias",
  rsi_reversion: "reversao-com-rsi",
  donchian_breakout: "rompimento-de-canal",
};

export const GLOSSARY: { term: string; def: string; lesson?: string }[] = [
  { term: "Alavancagem", def: "Operar com mais do que você tem, usando recursos da corretora. Multiplica ganhos e perdas.", lesson: "comprado-e-vendido" },
  { term: "Alvo (take profit)", def: "Preço em que a operação é encerrada com lucro.", lesson: "stop-e-tamanho-da-posicao" },
  { term: "Backtest", def: "Teste de uma estratégia no histórico de preços, para ver como ela teria se saído.", lesson: "como-ler-um-backtest" },
  { term: "Candle", def: "Vela do gráfico que resume um período com abertura, fechamento, máxima e mínima.", lesson: "candle" },
  { term: "Comprado", def: "Posição que ganha quando o preço sobe.", lesson: "comprado-e-vendido" },
  { term: "Comprar e segurar", def: "Comprar no início do período e só vender no fim. Serve de comparação para qualquer estratégia.", lesson: "como-ler-um-backtest" },
  { term: "Day trade", def: "Operação aberta e encerrada no mesmo dia.", lesson: "day-trade-ou-swing-trade" },
  { term: "Excesso de ajuste (overfitting)", def: "Ajustar a estratégia até ela decorar o passado. Costuma falhar no futuro.", lesson: "como-ler-um-backtest" },
  { term: "Expectativa", def: "Quanto, em média, cada operação ganha ou perde, já com custos.", lesson: "taxa-de-acerto-e-expectativa" },
  { term: "Fator de lucro", def: "Soma dos ganhos dividida pela soma das perdas. Acima de 1, a estratégia ganhou.", lesson: "como-ler-um-backtest" },
  { term: "Forex", def: "Mercado de câmbio: troca de moedas de países, como euro por dólar.", lesson: "o-que-e-o-mercado" },
  { term: "Gap", def: "Salto de preço entre o fechamento de um período e a abertura do seguinte, sem negócios no meio.", lesson: "day-trade-ou-swing-trade" },
  { term: "Lote", def: "Unidade de tamanho no forex. 1 lote padrão = 100.000 unidades da moeda base; 0,01 lote = 1.000." },
  { term: "Margem", def: "Parte do seu dinheiro que a corretora separa como garantia de uma operação alavancada.", lesson: "comprado-e-vendido" },
  { term: "Média móvel", def: "Média dos últimos N fechamentos, recalculada a cada candle. Mostra a direção do preço.", lesson: "medias-moveis" },
  { term: "Ordem a mercado", def: "Ordem executada na hora, pelo melhor preço disponível.", lesson: "ordens-e-custos" },
  { term: "Ordem limitada", def: "Ordem com preço definido. Só executa se o mercado chegar nele.", lesson: "ordens-e-custos" },
  { term: "Par", def: "Duas moedas cotadas uma na outra, como BTCUSDT ou EURUSD.", lesson: "o-que-e-o-mercado" },
  { term: "Pip", def: "Menor variação usual de um par de forex. No EURUSD, 0,0001." },
  { term: "Queda máxima (drawdown)", def: "A maior queda do capital, do pico ao fundo, durante o período.", lesson: "como-ler-um-backtest" },
  { term: "Resistência", def: "Região onde as altas costumam parar.", lesson: "tendencia-suporte-resistencia" },
  { term: "Rompimento", def: "Quando o preço atravessa com força um suporte, uma resistência ou um canal.", lesson: "rompimento-de-canal" },
  { term: "RSI", def: "Índice de Força Relativa, de 0 a 100. Acima de 70, sobrecomprado; abaixo de 30, sobrevendido.", lesson: "rsi" },
  { term: "Slippage", def: "Diferença entre o preço esperado e o preço em que a ordem foi executada.", lesson: "ordens-e-custos" },
  { term: "Spread", def: "Diferença entre o melhor preço de compra e o melhor preço de venda.", lesson: "ordens-e-custos" },
  { term: "Stop (stop loss)", def: "Preço em que a operação é encerrada para limitar a perda.", lesson: "stop-e-tamanho-da-posicao" },
  { term: "Suporte", def: "Região onde as quedas costumam parar.", lesson: "tendencia-suporte-resistencia" },
  { term: "Swing trade", def: "Operação que dura de dias a semanas.", lesson: "day-trade-ou-swing-trade" },
  { term: "Taxa de acerto", def: "Porcentagem de operações que terminaram com lucro. Sozinha, não diz se a estratégia é boa.", lesson: "taxa-de-acerto-e-expectativa" },
  { term: "Tempo gráfico", def: "Quanto tempo cada candle representa: 5 minutos, 1 hora, 1 dia…", lesson: "tempo-grafico" },
  { term: "Tendência", def: "Direção predominante do preço, vista pelos topos e fundos.", lesson: "tendencia-suporte-resistencia" },
  { term: "Testnet / conta demo", def: "Ambiente da corretora com dinheiro fictício, para testar sem risco.", lesson: "do-simulador-a-conta-real" },
  { term: "Vendido", def: "Posição que ganha quando o preço cai: vende primeiro e recompra depois.", lesson: "comprado-e-vendido" },
];
