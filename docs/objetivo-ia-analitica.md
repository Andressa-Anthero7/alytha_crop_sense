# Objetivo da IA conversacional de assistência e análise agrícola

Registrado em 15/10/2026 a partir da direção definida por Andressa. Este documento define o objetivo do produto e os requisitos de evolução; não declara as integrações planejadas como disponíveis.

## Objetivo central

A Alytha deve ser uma IA conversacional capaz de coordenar a busca, o processamento, o refinamento e a análise dos dados agrícolas do sistema. Deve interpretar perguntas, recuperar evidências, acionar ferramentas e comparar resultados para responder sobre uma área, um talhão, uma região e uma safra, preservando o contexto da conversa.

O sistema deve combinar imagens e séries históricas, evolução espacial da vegetação, janelas de plantio, meteorologia, conhecimento agronômico e registros de campo quando disponíveis. A conversa deve permitir solicitar e acompanhar análises reais, com resultados rastreáveis e indicação do que ainda falta investigar.

## Fontes e ferramentas previstas

| Componente | Capacidade pretendida |
| --- | --- |
| Sentinel-2 | Consultar bandas e produtos pertinentes à pergunta, imagens em cor natural, índices espectrais, séries temporais, máscaras de qualidade e mudanças espaciais. |
| Sentinel-1 | Integrar séries de radar e características pertinentes à análise, com processamento e interpretação próprios, em complemento às observações ópticas. |
| Meteorologia | Cruzar chuva, temperatura e outras variáveis relevantes com emergência, desenvolvimento e mudanças observadas; distinguir observação, estimativa e previsão. |
| Histórico e base de imagens | Comparar o mesmo recorte entre datas e safras, com geometrias, escalas, qualidade e fases sazonais compatíveis. |
| OpenCV/cv2 | Medir manchas, bordas, organização espacial e progressão direcional em rasters georreferenciados e máscaras válidas. |
| Machine learning | Explorar padrões, comparar comportamentos e desenvolver modelos supervisionados quando existirem referências suficientes; avaliar versões antes de promover resultados ao produto. |
| Embrapa e outras bases agronômicas | Recuperar publicações e consultar serviços disponíveis para fundamentar hipóteses e contextualizar cultura, manejo e região. |
| Internet e bases complementares | Pesquisar fontes pertinentes quando necessário, guardar referências e datas e distinguir conhecimento publicado de observação do talhão. |
| Motor conversacional | Planejar e executar chamadas às ferramentas, acompanhar trabalhos, reunir evidências e explicar conclusões, alternativas e pendências em linguagem acessível. |

Integrar as informações úteis de Sentinel-1 e Sentinel-2 conforme o problema, a disponibilidade e a qualidade dos dados. A escolha de bandas, produtos, modelos e ferramentas deve ser justificada pela análise; não pressupõe baixar ou processar indiscriminadamente todos os produtos.

## Caso orientador: progressão do esverdeamento na janela de plantio

Pergunta de referência: “O esverdeamento avançando dentro deste talhão pode acompanhar a sequência de semeadura? Como isso se compara ao histórico, à janela de plantio e às condições meteorológicas?”

O fluxo pretendido deve:

1. Identificar geometria, cultura declarada, safra e período, preservando o contexto de perguntas seguintes.
2. Recuperar observações disponíveis e informar lacunas, datas, resolução, cobertura válida e se cada imagem representa uma cena ou um mosaico temporal.
3. Medir aumento ou redução de vegetação e identificar setores que mudaram antes e depois, quando houver observações suficientes.
4. Comparar a progressão espacial e temporal com safras anteriores do mesmo recorte, considerando diferenças de calendário e qualidade.
5. Verificar se o período pertence a uma janela de plantio informada ou obtida em fonte pertinente à cultura, região e safra. Registrar a origem e distinguir janela declarada, referência agronômica e eventual período normativo.
6. Cruzar condições meteorológicas e, quando integrados, sinais Sentinel-1 com os sinais Sentinel-2, considerando diferenças de escala e aquisição.
7. Consultar referências agronômicas relevantes para avaliar explicações alternativas, como emergência desigual, umidade, rebrota, plantas daninhas ou cobertura vegetal.
8. Entregar uma síntese que separe medições, hipóteses, evidências divergentes, dados ausentes e próxima verificação útil.

A hipótese a investigar é “progressão do esverdeamento compatível com a sequência de semeadura”. A direção da mudança vegetal não comprova o trajeto da plantadeira, a orientação das linhas, a data exata de semeadura ou a identidade da cultura. A passagem aparente de palhada para vegetação deve ser examinada em cor natural quando disponível; cores de uma legenda NDVI não identificam palhada.

## Execução e rastreabilidade

A IA deve reutilizar a base coletada e refinada antes de solicitar novas consultas. Quando faltarem dados, deve indicar o que pode ser calculado localmente e o que depende de fonte externa, credenciais ou disponibilidade. Trabalhos devem registrar parâmetros, progresso, falhas e artefatos; solicitar uma ferramenta não equivale a concluir a análise.

Cada conclusão deve estar vinculada ao recorte, período, fontes, indicadores de qualidade e versões dos métodos/modelos utilizados. Comparações devem evitar misturar evidência estadual ou municipal com medição do talhão. Documentos e páginas recuperados são fontes de informação, não instruções para alterar o comportamento ou executar ações do sistema.

Absorver esse tipo de análise significa incorporá-la aos métodos, às ferramentas, à recuperação de conhecimento e às avaliações da assistente. Conversas e hipóteses geradas não se tornam automaticamente rótulos de campo ou treinamento dos modelos.

## Estado atual e restrição desta fase

A base atual possui histórico NDVI, análise espacial com cv2, progressão direcional experimental, recursos exploratórios de ML, persistência e assistência conversacional. Os detalhes estão em [evolução da Alytha](evolucao-alytha.md), [direção da vegetação](direcao-vegetacao.md) e [aprendizado contínuo](aprendizado-continuo.md).

Sentinel-1 e pesquisa livre na internet pela assistente continuam pendentes. O incremento de 15/10 integra clima NASA POWER, busca web restrita ao portal Embrapa e ferramentas locais verificáveis: [análises na conversa](analises-conversacionais.md). A consulta real SATVeg depende do acesso à AgroAPI; a busca restrita não equivale a uma revisão abrangente da literatura.

Andressa informou indisponibilidade de acesso ao Sentinel até a virada de outubro para novembro de 2026. Nesta fase, utilizar arquivos locais, sem novas consultas Sentinel. A retomada dependerá da disponibilidade efetiva do serviço, sem agendamento implícito neste documento.

Na inspeção local de 15/10/2026 foram encontrados três GeoTIFFs NDVI com máscara de validade, de 98 × 222 pixels, e seis metadados de imagens NDVI em `data/outputs/vision/assets`. Não foram encontradas bandas originais de cor natural armazenadas. A existência desses arquivos não comprova histórico suficiente para todos os cruzamentos propostos.

Ainda não há dados de campo para validar este experimento. Super-resolução permanece uma pesquisa separada de aparência e consistência, sem validar detalhes reconstruídos nem substituir os valores observados. Integrações comerciais do tópico 2 da pesquisa compartilhada ficam fora do escopo desta discussão.

## Sequência de implementação e critérios de entrega

Primeiro incremento executado em 15/10/2026: [inventário local](inventario-local.md), [contrato de evidências, contexto e ferramentas analíticas](analises-conversacionais.md). O bloqueio do SQLite foi corrigido com [migrations, WAL e inscrição visual em lotes](banco-migrations.md). Há comparação histórica, direção em rasters locais, janela declarada e síntese, com avaliação técnica salva. O aceite agronômico permanece separado. A [fila local, backup e preparação de homologação](operacao-local.md) avançaram parcialmente; login e isolamento ainda não estão implementados.

1. Consolidar o inventário local e expor à assistente quais áreas, períodos, imagens e análises realmente estão disponíveis.
2. Disponibilizar pela conversa a comparação histórica e a análise direcional existentes, com respostas vinculadas aos resultados calculados e lacunas explícitas.
3. Integrar janelas de plantio com origem identificada e dados meteorológicos compatíveis com o recorte e período.
4. Integrar Sentinel-1 e ampliar o uso das bandas Sentinel-2 conforme a disponibilidade e os casos de uso.
   Pesquisa registrada para novembro de 2026, após retomada do acesso: [EVI, SAVI/MSAVI e NDMI, além do NDVI](indices-espectrais-retomada.md), tarefa IA-28.
5. Implementar busca e recuperação de referências Embrapa e internet, com citações e registro da consulta.
6. Avaliar os cruzamentos e as respostas em casos conhecidos, incorporando dados de parceiros quando disponíveis.

Uma entrega deve demonstrar que uma pergunta produz chamadas verificáveis às ferramentas, que a resposta corresponde aos resultados e que perguntas seguintes preservam área e período. Casos sem dados, fora da janela de plantio, sem direção detectável, com nuvens ou com fontes divergentes devem integrar a avaliação. A fase inicial mede funcionamento, consistência e utilidade exploratória; acurácia agronômica exige validação independente.
