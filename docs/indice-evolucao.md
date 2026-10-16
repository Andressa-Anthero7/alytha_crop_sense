# Índice de Evidências de Evolução Vegetal (IEV)

O acompanhamento apresenta dois índices de 0 a 100 pontos: **expansão** e **redução da vegetação**. O primeiro reúne sinais compatíveis com estabelecimento/desenvolvimento vegetal; o segundo, sinais compatíveis com colheita, dessecação, senescência ou outros eventos de redução. Não são probabilidades de manejo, porcentagens de área plantada ou estimativas de produtividade.

Os pesos e faixas são escolhas experimentais para organizar a validação do MVP. Não foram ajustados por resultados de campo. Muitos fatores são correlacionados; não são seis confirmações independentes.

| Fator | Peso | Regra inicial |
| --- | --- | --- |
| Tendência temporal | 25 | Inclinação NDVI dos últimos 30 dias no sentido analisado; contribuição máxima a 0,006 por dia. |
| Mudança espacial | 25 | Hectares de ganho menos perda, ou perda menos ganho, divididos pela área observada; máximo com saldo de 25% da área observada. |
| Sequência espacial | 20 | Fração em frentes do sinal analisado (máximo a 25%) multiplicada pela organização temporal espacial (máximo a R² 0,75). R² não é confiança agronômica. |
| Soja histórica | 15 | Interseção do polígono com recortes MapBiomas municipais de um ano anterior ao corte; máximo a 80% de interseção. Não utiliza o resumo municipal como cobertura do talhão. |
| Janela declarada | 5 | Corte dentro de uma janela de plantio informada pelo usuário. Somente no índice de expansão. Não infere calendário oficial nem calendário de colheita. |
| Qualidade e atualidade | 10 | Cobertura válida média × quantidade de leituras (máximo a seis) × atualidade da última observação (1 menos idade/30, limitado a 0–1). |

Cada contribuição é limitada entre zero e seu peso. Faixas de leitura iniciais: abaixo de 40, evidências limitadas; 40–69,9, moderadas; 70–100, elevadas. Essas faixas também precisam de validação. Uma pontuação de 80 pontos não significa 80% de chance de plantio.

## Dados ausentes

Fator ausente não aumenta o peso dos demais. A tela mostra quantos dos 100 pontos possíveis podem ser avaliados. Sem a série recente utilizável, o valor é nulo (“dados insuficientes”), mesmo que haja cobertura histórica. Ausência de direção em uma análise válida contribui zero; direção não analisada é um fator ausente. A série usa os mesmos filtros de qualidade, lacunas e disponibilidade na data de corte da comparação histórica.

Recortes municipais de soja menores que 5 ha não estão no conjunto usado para verificar cobertura histórica; essa interseção é conservadora. O fator histórico qualifica contexto anterior, não cultura atual. Sem o cache municipal de soja, fica ausente.

## Uso

Abra o histórico e use **Atualizar acompanhamento**. A seção opcional permite informar uma janela de plantio de até 180 dias fornecida pelo produtor. A declaração fica vinculada à geometria no SQLite e não é usada em cortes anteriores à data de declaração. Campos em branco reutilizam uma janela já registrada para a área; datas preenchidas substituem a janela anterior. A fonte aparece como declaração não verificada.

O relatório JSON inclui versão, data, valores, disponibilidade e razões de cada fator. As pontuações também são exportadas nas características combinadas, sem serem rótulos de treinamento. A Alytha recebe esse índice junto da evidência do mesmo recorte e deve descrevê-lo como pontos, sem convertê-lo em chance ou área plantada.

Próxima etapa de validação: comparar índices e fatores com registros conhecidos de operações em áreas e safras independentes, ajustar os pesos e verificar se o índice ajuda a priorizar acompanhamento. Uma probabilidade calibrada de manejo exigirá um modelo e uma avaliação separados.
