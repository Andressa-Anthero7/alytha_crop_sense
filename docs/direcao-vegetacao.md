# Direção experimental da evolução da vegetação

Abra um histórico e use **Atualizar acompanhamento**, ou selecione um polígono e use **Evolução da vegetação · manchas e direção → Analisar mudanças e direção**. As setas no mapa apontam do centro dos setores que mudaram antes para o centro dos setores que mudaram depois. Verde representa sequência de ganho; rosado, sequência de perda.

O processamento usa três janelas Sentinel-2 em uma grade UTM de 10 m e somente pixels válidos nas três janelas. São mosaicos por intervalos de até cinco dias, não fotografias simultâneas de toda a área. A análise exige cobertura comum de pelo menos 50% do polígono e 50 pixels, além dos limites existentes de tamanho e datas.

## Critérios experimentais

Para ganho, pixels começam com NDVI ≤ 0,25 e chegam a ≥ 0,35; para perda, começam em ≥ 0,35 e chegam a ≤ 0,25. A diferença líquida precisa alcançar 0,15. Uma parcela muda entre a primeira e a segunda janela e mantém o novo estado; outra parcela muda entre a segunda e a terceira. Tolera-se uma oscilação de 0,05 na regra temporal. Mudanças temporárias, simultâneas ou sem dois grupos cronológicos suficientes não geram direção.

O OpenCV identifica componentes contíguos na união dos grupos de mudança. Cada componente precisa conter pelo menos 1 ha que mudou antes e 1 ha que mudou depois. Centros separados por menos de 30 m são descartados. Uma regressão espacial do grupo temporal contra coordenadas métricas exige R² ≥ 0,35 e alinhamento ≥ 0,8 entre gradiente temporal e vetor dos centros. O ajuste usa no máximo 10 mil pixels amostrados deterministicamente por componente.

Esses critérios descrevem uma organização espacial aparente. Não são limiares agronômicos validados. R² não é probabilidade de acerto. Distância entre centros não é deslocamento de máquina nem velocidade de plantio. A seta resume uma direção dominante e pode não acompanhar curvas ou múltiplas frentes.

## Interpretação

- Ganho em sequência: compatível com estabelecimento/desenvolvimento vegetal; pode acompanhar plantio em setores, rebrota ou diferenças de umidade. A semeadura antecede o sinal de vegetação e não é diretamente observada.
- Perda em sequência: compatível com colheita, dessecação, senescência ou outros eventos de redução. Não identifica qual operação ocorreu.
- Sem direção: falta de uma sequência espacial que satisfaça os critérios; não comprova ausência de manejo.

Não identifica linhas individuais, cultura atual, abandono, danos confirmados ou produtividade. Para validar, comparar setores e datas com registros do produtor. Mudanças residuais de nuvens, posicionamento e qualidade das imagens podem afetar os sinais.

## Persistência e assistente

A versão espacial 3 adiciona `progression` ao resultado, com critérios, frentes, setas e períodos. `direcao.geojson` e `progressao.json` ficam no pacote de análise espacial. O acompanhamento integrado também recebe a progressão e exporta suas setas. O contexto da Alytha inclui as métricas e hipóteses disponíveis do mesmo recorte, sem tratar essas hipóteses como confirmação.

Resultados antigos continuam válidos para seus métodos, mas não possuem direção. Execute uma nova análise para habilitar a versão 3; os rasters compatíveis já baixados são reutilizados. A varredura municipal do Centro-Oeste continua independente: não calcula direção automaticamente em todas as áreas.
