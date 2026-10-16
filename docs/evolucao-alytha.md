# Evolução da Alytha

Atualizado em 14/10/2026. Esta entrega melhora recuperação de dados, comandos e respostas. Não altera os pesos do Gemini/OpenAI nem transforma os modelos de vegetação em modelos de linguagem.

## Capacidades disponíveis

- Recuperar a consulta municipal mais recente salva, mesmo sem abrir o gráfico; respeitar a data selecionada e o município.
- Consultar os perfis treinados do município, com recortes, grupos, dados usados e comportamentos atípicos. Um modelo posterior à data selecionada não entra nessa leitura histórica.
- Responder conceitos sem exigir uma cidade ou assumir Sorriso como contexto.
- Buscar uma localidade oficial: “abra Sinop MT” ou “mostre soja em Sinop MT”. Localidades ambíguas exigem nome e UF. A navegação utiliza a busca IBGE existente e inicia o fluxo regional normal.
- Nomes oficiais sozinhos, como “Palestina de Goiás”, também navegam. A busca exige correspondência exata, preserva as culturas marcadas e não transforma perguntas de acompanhamento em navegação. Um enquadramento que ultrapasse a faixa brasileira é recortado antes do processamento de culturas quando há estado ou município definido; a malha administrativa continua limitando as manchas.
- Pedidos curtos como “soja em Goiás” e “oja em goias” abrem o estado e exibem soja histórica recortada pela divisa estadual. Se o nome corresponder a estado e município, o nome estadual tem prioridade; “na cidade de Goiás” escolhe explicitamente o município. O mapa estadual usa a visão geral existente: aproxime para conferir manchas menores, sem tratar essa visualização como censo de hectares.
- Abrir o histórico da área selecionada, atualizar seu acompanhamento, mostrar atividade vegetativa ou abrir o mapa da coleta. As consultas continuam sujeitas às credenciais, cotas e limites existentes.
- Responder perguntas frequentes de resumo municipal e dos modelos diretamente a partir dos resultados calculados, sem atribuir causas ao baixo vigor.

Comandos são limitados aos pedidos explícitos atuais. Uma resposta interpretativa do provedor não executa ações por conta própria. Trocar município descarta o contexto da conversa anterior. O mapa confirma o carregamento; uma solicitação não é apresentada como análise já concluída.

Depois de navegar por um comando da Alytha, a pergunta e a confirmação executada permanecem na conversa. Estado, município, culturas marcadas e ano do mapa seguem na próxima consulta. “Soja em Goiás” seguido de “e comparado com a safra anterior?” preserva Goiás e soja, sem usar o histórico antigo de Sorriso como evidência estadual. Se o usuário trocar o estado, a nova seleção prevalece. A memória não cria uma comparação estadual de vigor que ainda não existe.

“Não apareceu no mapa” solicita uma nova tentativa da cultura marcada ou mencionada na conversa. A aplicação verifica se a camada foi adicionada ao mapa antes de confirmar o resultado e mostra o erro da fonte quando houver falha. Na nova tentativa, aproxima o enquadramento das manchas carregadas. O provedor não pode anunciar uma navegação cuja ação foi recusada pelo servidor.

O mapa apresenta um indicador sobreposto durante o carregamento de localidades e culturas, com a etapa em andamento. A conclusão aparece brevemente; erros ficam visíveis até serem fechados ou uma nova consulta começar. O indicador não bloqueia zoom ou movimento. Consultas antigas não encerram o aviso de uma consulta mais recente.

Cada aba identifica suas consultas de culturas. Um novo enquadramento substitui o trabalho antigo da mesma cultura que ainda está na fila, sem interromper leituras já iniciadas ou consultas de outras abas. Se não houver vaga, o pedido atual fica aguardando e o navegador tenta agendá-lo automaticamente ao consultar o andamento. Consultas substituídas não voltam à fila por causa de um polling antigo. Ao encher a fila, pedidos novos também podem substituir trabalhos legados ainda não iniciados.

## Reutilização da visão estadual

As malhas oficiais consultadas são persistidas no SQLite. Quando o enquadramento cobre toda a malha do estado, seus limites são normalizados ao mesmo recorte oficial, compartilhando o trabalho por estado, ano e cultura. Resultados preparados anteriormente que cobrem o estado inteiro podem ser reaproveitados sem novas leituras do raster. Recortes parciais e anos/culturas diferentes continuam separados; a visão geral não substitui um detalhe local.

Uma verificação local com resultados já preparados de GO e MS recuperou dois enquadramentos completos de cada estado em aproximadamente um segundo por par no servidor. Isso mede cache local aquecido, não a primeira coleta nem o tempo completo de renderização no navegador. Consultas novas registram tempos de leitura do raster, processamento das manchas e tempo total. Os dois workers permanecem: essa mudança reduz trabalho repetido antes de aumentar concorrência.

A visualização seleciona até 200 maiores manchas do recorte visível, preservando o limite de memória da lista. Antes, as primeiras 200 manchas encontradas podiam se concentrar em uma borda e deixar a visão estadual pouco legível. Essa seleção prioriza a visualização; não representa todas as áreas de soja ou uma estimativa de área plantada. A malha administrativa e o ano histórico continuam valendo.

## Conhecimento agrícola inicial

Quatro referências resumidas são recuperadas por assunto: plantio direto, água e solo, fenologia e duração do ciclo da soja. Os links aparecem nas fontes das respostas. Esta biblioteca ainda é pequena e sua recuperação usa termos, não embeddings. Não existe pesquisa livre na internet em tempo real pela Alytha.

Fontes lidas:

- [Embrapa Soja — manejo do solo e disponibilidade de água](https://bioinfo.cnpso.embrapa.br/seca/index.php?Itemid=478&id=75&option=com_content&view=article).
- [Embrapa Agropecuária Oeste — Documentos 103, 2010, páginas 9–12](https://www.infoteca.cnptia.embrapa.br/bitstream/doc/697293/1/DOC2010103.pdf), somente conceitos de desenvolvimento; não recomendações atuais de cultivares ou calendários.

## Avaliação e evolução

Execute `python -m app.assistant_eval` para cinco perguntas reais com o provedor configurado. O comando usa a API e pode consumir sua cota. Salva perguntas, respostas, referências e critérios de revisão em `data/outputs/assistant/`. Responder cinco casos não significa acurácia agronômica comprovada.

O primeiro ensaio revelou uma associação indevida de baixo vigor a preparo/pousio. A entrega passou a gerar o resumo municipal diretamente dos dados e ajustou a explicação de fenologia. O segundo ensaio respondeu aos cinco casos, com causas não confirmadas mantidas como desconhecidas. O relatório conserva a revisão humana como pendente.

A avaliação segue a abordagem de casos e critérios específicos descrita na [documentação oficial OpenAI](https://developers.openai.com/api/docs/guides/evaluation-best-practices).

Próximos incrementos: ampliar as referências por cultura; obter exemplos reais revisados pelos parceiros; adicionar casos difíceis de interpretação e de navegação; medir respostas corretas, omissões, tempo e falhas de execução. Só utilizar perguntas e respostas aprovadas como exemplos de aprendizado. Um ajuste dos pesos do modelo exige uma base revisada e avaliação independente, além da escolha do provedor e do custo. Conversas não viram treinamento automático.
