# Índices além do NDVI — retomada em novembro de 2026

Registrado em 15/10/2026 por solicitação de Andressa. Retomar em novembro de 2026, sem dia ou semana fechados, após disponibilidade efetiva do acesso às bandas Sentinel-2. Este registro não agenda consultas, downloads ou cobranças automáticas.

## Pesquisa a incorporar

| Índice | Uso a investigar |
| --- | --- |
| EVI | Complementar o NDVI no acompanhamento de vegetação densa, onde o NDVI pode saturar. |
| SAVI / MSAVI | Investigar a vegetação com cobertura ainda pequena, reduzindo a influência do solo na leitura. |
| NDMI | Complementar a análise com um indicador relacionado ao conteúdo de água na vegetação; não é medição direta de umidade do solo. |

Caso prioritário da pesquisa: comparar NDVI com SAVI/MSAVI durante o início do esverdeamento de um talhão em janela de plantio, considerando solo, palhada e evolução temporal. O efeito da palhada precisa ser avaliado, sem presumir que índices ajustados ao solo eliminam a influência dos resíduos.

## Dependências e sequência

1. Confirmar disponibilidade do acesso à fonte Sentinel-2 e suas cotas. A reposição de saldo da OpenAI libera chamadas ao modelo de linguagem, mas não fornece as bandas nem restabelece a cota do Sentinel.
2. Adquirir e preservar as bandas originais necessárias, com datas, geometria, resolução nativa e máscaras de qualidade. O NDVI já salvo não permite recuperar essas bandas nem calcular corretamente todos os outros índices.
3. Implementar os índices com reflectâncias e escalas adequadas, alinhando bandas de diferentes resoluções sem alegar ganho de detalhe observado.
4. Comparar os índices no mesmo recorte e em períodos compatíveis, registrando qualidade, diferenças e limitações.
5. Expor os resultados à Alytha como evidências rastreáveis para interpretação conjunta com histórico, direção vegetal e janela declarada.

Nesta fase, sem dados de campo, a conclusão será exploratória. Nenhum índice isolado confirma soja, semeadura, causa de falhas ou produtividade. Não substituir os dados originais por resultados de super-resolução.

## Critério de entrega

Comparação reproduzível entre NDVI e os índices adicionais escolhidos, com bandas de origem identificadas, máscaras, datas, resolução e limitações explícitas. A conversa deve indicar quais índices realmente foram calculados e quais estão indisponíveis.

Acompanhamento: tarefa IA-28 no [quadro de implementação](quadro-implementacao-ia.xlsx), dependente da aquisição de bandas prevista em IA-16.

## Referências da pesquisa

- [USGS — Enhanced Vegetation Index](https://www.usgs.gov/landsat-missions/landsat-enhanced-vegetation-index).
- [USGS — Soil Adjusted Vegetation Index](https://www.usgs.gov/landsat-missions/landsat-soil-adjusted-vegetation-index).
- [USGS — Modified Soil-Adjusted Vegetation Index: fundamentos e aplicação](https://pubs.usgs.gov/sir/2006/5145/section3.html).
- [USGS — Normalized Difference Moisture Index](https://www.usgs.gov/landsat-missions/normalized-difference-moisture-index).

As referências USGS descrevem fundamentos e produtos Landsat; a implementação na Alytha deve adaptar as bandas e o processamento ao Sentinel-2, sem copiar a numeração de bandas Landsat.
