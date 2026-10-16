# Condições para plantio de soja

No painel de camadas, abra **Condições para plantio · soja**, selecione uma área e clique em **Avaliar condições para plantio**. A consulta é explícita: não inicia trabalhadores, coletas de imagens ou chamadas ao Copernicus. A barra de datas do NDVI não altera esta avaliação das condições atuais.

O endpoint `POST /api/planting-readiness` recebe `geojson` e `field_inputs`. Retorna fatores, fontes, datas, verificações declaradas, pontos de atenção e pendências. O JSON pode ser exportado na interface.

## Evidências automáticas

- Open-Meteo: precipitação nos últimos 7 e 14 dias completos, chuva prevista para os próximos 7 dias completos, temperaturas mínimas/máximas do ar, ET₀, temperatura do solo a 6 cm e umidade volumétrica entre 3 e 9 cm.
- Histórico recente é estimativa de modelo, não observação de pluviômetro. Hoje, incompleto, não entra nos totais. A média de solo usa ontem, com pelo menos 18 horas válidas. Dias são alinhados em `America/Sao_Paulo`.
- Uma célula meteorológica associada a um ponto interno do recorte; não é mapa do solo nem medição de 10 m. Extensões maiores que 0,5 grau por lado são rejeitadas.
- NDVI Sentinel-2 já salvo do mesmo polígono, com cobertura ≥ 50% e ≥ 50 pixels válidos. Não substitui o polígono por amostra contida. Leituras com mais de 15 dias não representam condição atual.
- Dados meteorológicos ficam em cache por 3 horas. Falha externa pode exibir cache antigo, marcado como desatualizado, impedindo resultado favorável. Ausências nunca viram zero.

## Critérios e limites

A temperatura média estimada do solo entre 20 e 30 °C é favorável nesse critério, conforme a [Embrapa](https://www.embrapa.br/en/web/agencia-de-informacao-tecnologica/cultivos/soja/pre-producao/instalacao-da-lavoura/aspectos-a-serem-considerados). Temperatura do ar não substitui temperatura do solo.

Alertas **exploratórios**, sem calibração agronômica regional: menos de 10 mm recentes e previstos em cada janela de 7 dias em sequeiro; previsão ≥ 50 mm em um dia ou ≥ 100 mm em 7 dias; ar ≤ 10 °C ou ≥ 35 °C. Alertas não comprovam seca no solo, alagamento ou perda da lavoura. Chuva menos ET₀ é contexto climático, não balanço hídrico do talhão. Umidade volumétrica não recebe limite universal: depende da textura, retenção e condição local do solo.

Condição física/umidade na semente, drenagem/trafegabilidade, análise/correção do solo, calendário sanitário e ZARC são **declarações do usuário**, não verificações automáticas. Campo não preenchido fica pendente. Trocar a área limpa todas as declarações e os resultados; alterar uma declaração invalida o resultado anterior. Respostas atrasadas de outra área são descartadas.

Resultados: **pontos de atenção**, **avaliação incompleta** ou **condições favoráveis nos parâmetros avaliados**. O último exige todos os fatores essenciais disponíveis, verificações declaradas favoráveis e ausência de alertas. Não constitui laudo de aptidão, recomendação definitiva, elegibilidade a seguro/crédito, autorização ambiental ou sanitária. Não se presume disponibilidade de área nem ausência de cultura apenas por NDVI baixo. A avaliação de sementes, sanidade e manejo permanece local.

Fontes: [Open-Meteo](https://open-meteo.com/en/docs), [Embrapa](https://www.embrapa.br/en/web/agencia-de-informacao-tecnologica/cultivos/soja/pre-producao/instalacao-da-lavoura/aspectos-a-serem-considerados), [ZARC/MAPA](https://www.gov.br/agricultura/pt-br/assuntos/riscos-seguro/programa-nacional-de-zoneamento-agricola-de-risco-climatico).

## Verificação

`python -m unittest discover -s tests -p test_planting_readiness.py`

Com servidor local: `python tests/verify_planting_readiness.py`. O teste de navegador usa clima simulado e bloqueia fontes externas. Não baixa imagens.
