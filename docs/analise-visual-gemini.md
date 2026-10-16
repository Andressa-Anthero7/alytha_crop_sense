# Gemini na análise direta das imagens

Correção de 14/10/2026: a operação agora possui uma fila visual por recorte, além da base numérica. O Gemini recebe os bytes de imagens reais do satélite, junto das medições, regras temporais e padrões de ML disponíveis. A integração segue o envio de imagens pelo [generateContent oficial](https://ai.google.dev/api/generate-content).

## Imagens e qualidade

São preparados até três períodos distintos da mesma geometria, com pelo menos dez dias entre primeiro e último. Rasters espaciais já armazenados são reutilizados quando recentes e compatíveis. Sem cache, os períodos são selecionados das leituras do histórico. Nenhuma imagem pode ultrapassar a data de análise.

Quando o Copernicus permite a aquisição, uma chamada por período obtém B04/B03/B02, NDVI e máscara de qualidade em uma grade geográfica de 10 m. A partir dela são produzidos até seis PNGs para o Gemini: três em cor natural e três mapas NDVI. A cor natural usa ganho fixo de reflectância de 2,5 em todos os períodos; NDVI usa escala fixa de -1 a 1. Pixels sem observação e fora do polígono ficam cinza. A visualização pode ser ampliada com vizinho mais próximo, sem criar detalhe físico adicional; dimensões nativas e da prévia ficam registradas.

Cada imagem precisa cobrir pelo menos 50 pixels válidos e metade da área. Nuvens e outras classes excluídas pela máscara não viram solo exposto ou ausência de vegetação. TIFFs numéricos existentes também podem produzir mapas NDVI espaciais reais: eles não são gráficos de série temporal nem fotografias de cor natural. Quando só houver NDVI, essa limitação é declarada no contexto enviado e no resultado.

Cada PNG tem geometria, período, CRS, limites, resolução nativa, qualidade, origem e SHA-256. Seu identificador inclui o conteúdo; uma imagem nova não substitui o arquivo de uma revisão anterior. Até seis PNGs são enviados em base64 no corpo da requisição ao Gemini. Chaves e conteúdo base64 não são gravados nos resultados públicos.

## O que o Gemini devolve

- Resumo e observações visuais vinculadas aos IDs das imagens.
- Indícios espaciais de vegetação irregular, ganho, redução, superfície exposta, padrões lineares grosseiros ou obstrução, com presença/ausência/incerteza explícitas.
- Hipóteses alternativas, limitações e verificações propostas para os parceiros.

O servidor rejeita referências a imagens que não foram enviadas. Uma mudança visual afirmada precisa citar duas datas distintas; mapas NDVI sozinhos não autorizam afirmar visualmente solo exposto. Não se identificam linhas individuais de plantio com pixels de 10 m, nem se confirma manejo, cultura ou produtividade por essa interpretação.

## Como entra no aprendizado

Os indícios visuais são exportados em `caracteristicas_visuais.csv` como características de origem `gemini_visual_interpretation`, com os hashes das imagens, modelo, data de disponibilidade e origem. O alvo de manejo permanece vazio até existir um registro humano para a mesma área e data.

Se a interpretação recebeu a referência humana ou uma previsão do classificador supervisionado, ela fica marcada como inelegível para entrada direta no treinamento de manejo: do contrário, a resposta correta poderia vazar para as características. Uma interpretação anterior sem essas informações é preservada para esse uso. A exportação não altera automaticamente o conjunto de características do classificador em produção; novas características exigem avaliação espacial e temporal antes da adoção.

Revisões concluídas ficam disponíveis à conversação para a mesma geometria e data, como interpretações, sem tratá-las como medição independente ou confirmação de campo.

## Operação

No mapa, abra o histórico e use **Gemini · análise direta das imagens → Analisar imagens deste recorte com Gemini**. A tela mostra os PNGs preparados, os períodos, a qualidade e a resposta ou pendência.

Na base regional, todos os recortes cadastrados têm uma entrada na fila visual. Recortes com rasters disponíveis têm prioridade. A ativação da fila da Alytha opera essa análise visual; o resumo textual municipal continua sendo uma etapa separada. Sem imagens reais, o recorte permanece em `waiting_images`, sem chamar o Gemini para simular uma análise visual.

Novas leituras do acompanhamento preparam imagens quando chegam dados. As análises respeitam a espera compartilhada do Copernicus em caso de cota esgotada e a espera do Gemini após falhas de provedor. HTTP 503 deixa `analysis_mode=not_analyzed`, preserva as imagens e agenda uma nova tentativa; não produz observações visuais fictícias.

## Estado da validação real

Em 14/10/2026, foram preparados três mapas NDVI de uma área de referência em Sorriso, dos períodos 18–22/09, 23–27/09 e 03–07/10. Eles vêm dos TIFFs Sentinel-2 já coletados, na mesma grade geográfica. A chamada multimodal real encontrou HTTP 503 do Gemini nas três tentativas. A aquisição de cor natural permaneceu bloqueada pela cota de processamento do Copernicus. Portanto, essa rodada ficou pendente, sem alegação de interpretação visual concluída.

### Diagnóstico do HTTP 503 em 14/10/2026

O teste isolado de `generateContent` no modelo configurado `gemini-3.1-flash-lite`, usando apenas o texto “Reply only OK.”, sem imagens, instruções de sistema ou esquema JSON, também retornou HTTP 503 em 2,6 segundos. O corpo da resposta trouxe `error.status=UNAVAILABLE` e a mensagem: “This model is currently experiencing high demand.” A falha de geração foi reproduzida independentemente do contexto agrícola e do envio de imagens.

Às 18:00 UTC (15:00 em São Paulo), a consulta autenticada dos metadados desse mesmo modelo retornou HTTP 200 e confirmou suporte a `generateContent` e `countTokens`. A contabilização dos três PNGs NDVI reais também retornou HTTP 200: 3.286 tokens, sendo 3.276 de imagem e 10 de texto. Isso confirma que a API recebeu as imagens nesse teste; não significa que a interpretação visual foi concluída nem valida todos os parâmetros da requisição de produção.

O diagnóstico observado é indisponibilidade de geração por alta demanda reportada pelo provedor para esse modelo, sem confirmação de uma interrupção global. O servidor agora reconhece essa mensagem e apresenta a causa em português, registrando apenas a classificação `model_high_demand`, sem copiar o corpo do erro ou credenciais para logs. As tentativas limitadas e a espera da fila permanecem em vigor, conforme a [orientação oficial de repetição com espera exponencial](https://ai.google.dev/gemini-api/docs/troubleshooting). A troca de modelo não foi aplicada. O bloqueio de processamento do Copernicus é uma pendência separada.
