# MVP para demonstração guiada aos produtores parceiros

Atualizado em 13/10/2026. Objetivo: demonstrar monitoramento de vegetação, entender a rotina do produtor e reunir referências reais para validar o produto. A fase do negócio pode ser apresentada como pré-seed; o produto é um MVP em validação.

## Mensagem de abertura

“A Alytha reúne mapas históricos e imagens de satélite para acompanhar a evolução da vegetação e mostrar onde vale investigar. Queremos comparar essa leitura com o que vocês sabem que aconteceu no campo e construir um acompanhamento útil para a operação.”

## Preparação

1. Executar `python -m app.demo_check`. O comando lê configuração e banco sem consultar fornecedores nem mostrar chaves.
2. Executar `python run.py` e abrir `http://127.0.0.1:8765/?municipio=5107925`.
3. Conferir município, ano do MapBiomas, data de corte e completude do gráfico. Resultados salvos podem ser antigos; apresentar sua data real.
4. Abrir a referência de Sorriso e conferir gráfico e acompanhamento antes da reunião. Primeiras consultas podem levar minutos; preparar previamente.
5. Testar uma pergunta ao assistente e uma camada. Se a fonte estiver indisponível, usar os resultados salvos com sua data e informar a indisponibilidade.
6. Fazer cópia do banco com o servidor parado, dos modelos e das exportações. Não usar dados fictícios como registros de manejo no banco da demonstração.

## Roteiro de 15–20 minutos

| Momento | Demonstração | Pergunta ao parceiro |
| --- | --- | --- |
| 2 min | Problema e objetivo do piloto | Como vocês acompanham áreas que precisam de atenção? |
| 3 min | Sorriso, culturas históricas e fontes | O mapa corresponde às áreas que vocês conhecem? |
| 4 min | Histórico do recorte e evolução NDVI | Quais eventos explicam os aumentos e quedas? |
| 4 min | Mudanças espaciais e comparação sazonal | Qual sinal ajudaria a decidir uma vistoria? |
| 3 min | Perguntas à Alytha | Que pergunta vocês fariam na rotina? |
| 4 min | Registro de campo e proposta de validação | Quais registros e áreas podemos comparar juntos? |

Mostrar cultura e ano no mapa; indicar se a evidência é municipal, estadual ou de um recorte. Baixo vigor pode ter diversas causas. Perfis de ML são exploratórios, sem classificação confirmada de manejo. Não prometer produtividade, diagnóstico de dano ou terra disponível.

## Dados solicitados ao parceiro

Começar com poucos talhões conhecidos. A pesquisa por cidade ou estado agora inicia uma [coleta regional automática](coleta-regional.md). O histórico de áreas pode ser consultado em outros municípios, desde que o polígono esteja dentro da malha municipal selecionada e respeite os limites de processamento. A referência de Sorriso continua disponível como material previamente coletado.

Para cada área, solicitar polígono autorizado, identificação do talhão, cultura e safra declaradas. Para cada evento conhecido, registrar data ou intervalo, etapa e referência (relato do produtor, caderno de operações, relatório de máquina ou vistoria). Fotos datadas podem ser mantidas em pasta externa, com referência no registro; anexos ainda não são suportados. Definir com o parceiro o uso autorizado dos dados e quem poderá acessá-los.

Na interface: abrir o histórico da área, expandir “Validação com o produtor”, registrar o evento e conferir a lista. A exportação JSON inclui geometria, datas e referências da mesma área. O registro precisa estar dentro do período do histórico e ter leituras suficientes; períodos sobrepostos são recusados. Situações desconhecidas devem permanecer sem rótulo.

## Critérios para avaliar o piloto

- O produtor consegue identificar corretamente sua área e entender a data, fonte e escala do resultado.
- A leitura é comparada com eventos conhecidos; acertos, divergências e falta de dados são anotados separadamente.
- A sugestão de acompanhamento resolve uma dúvida operacional real, confirmada pelo parceiro.
- Registrar tempo de espera, falhas de fontes, clareza dos textos e perguntas que o sistema não consegue responder.
- Definir metas de qualidade após formar a primeira base de referência; ainda não há acurácia agronômica comprovada.

## Pendências antes de uso autônomo

Login e isolamento por produtor, anexos e revisão/correção de registros, operação hospedada com backup, conclusão e revisão da cobertura regional e validação em áreas/safras independentes. A demonstração atual é guiada, em servidor local com dados compartilhados entre quem o acessa.

## Registro da reunião

Parceiro/código: ___ · Data: ___ · Área: ___ · Safra/cultura: ___

Problema prioritário: ___ · Resultado mostrado e data de corte: ___

O que corresponde ao campo: ___ · Divergências: ___ · Dados que faltam: ___

Dados autorizados para o piloto e condições de acesso: ___

Próxima entrega, responsável e data combinada: ___
