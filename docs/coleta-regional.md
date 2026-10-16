# Coleta sistemática por cidade ou estado

Digite `Sorriso / MT`, `Sinop / MT`, `Mato Grosso` ou `MT` na busca do mapa e pressione Enter. A busca usa nomes e códigos oficiais do IBGE, com normalização de acentos; não depende de chave Google Maps. Quando há mais de uma correspondência, escolha a localidade. Estados e cidades com o mesmo nome também exigem seleção.

A seleção por URL e pelos campos estado/município usa o mesmo fluxo. Abra **Coleta automática da região** no painel para acompanhar a execução, acessar os históricos e exportar o relatório JSON. A exportação inclui todos os municípios; a interface mostra até 25 linhas, incluindo o município em coleta.

## O que é coletado

1. **IBGE:** identidade do município e malha administrativa simplificada.
2. **CONAB:** contexto estadual de soja, milho e sorgo; não vira produção municipal.
3. **MapBiomas:** cobertura municipal de 2025 em pixels nativos, com as classes agrícolas existentes.
4. **Sentinel-2:** acompanhamento de 60 dias nos recortes de soja histórica do município, usando o processamento municipal existente.
5. **Histórico desde 2018:** um recorte de referência por município, escolhido entre os recortes de soja histórica disponíveis. O menor recorte é escolhido para limitar o processamento; não é uma amostra estatisticamente representativa. Abrir o histórico mostra seu polígono e permite comparar anos e registrar referências de campo.
6. **ML exploratório:** perfis de vegetação quando existem leituras suficientes e diversas. Falta de dados para treinar perfis não apaga os dados coletados nem cria rótulos fictícios.

São consultas a APIs e arquivos oficiais das integrações existentes, sem raspagem indiscriminada de páginas. Não são incluídas novas fontes comerciais, cadastro de proprietários ou imagens de radar. Embrapa continua dependendo de acesso e consulta específica.

## Estado e retomada

Para uma cidade, executa o pipeline desse município. Para um estado, enumera seus municípios e percorre a lista sequencialmente. Dois trabalhadores regionais e uma fila de até quatro varreduras limitam os pedidos agendados. Os módulos de fontes mantêm seus próprios limites de concorrência. Estado e cidade que compartilham um município reutilizam consultas filhas equivalentes.

A varredura é persistida em SQLite com parâmetros, data de início, etapas, IDs das consultas filhas e estados por cidade. Pesquisar a mesma região no mesmo dia reutiliza a rodada pronta ou em andamento. **Retomar fontes pendentes** tenta novamente cidades incompletas e preserva cidades prontas da rodada. O trabalho continua com a página fechada enquanto o servidor estiver ligado. Depois de reiniciar, abrir a região ou consultar o ID retoma trabalhos interrompidos; não há serviço autônomo de inicialização nem agendamento periódico.

Uma fonte com falha não remove os resultados das demais cidades. A rodada fica parcial quando há pendências. “Pronto” significa processamento concluído, não validação agronômica. Nuvens e leituras inconclusivas continuam visíveis nos resultados de atividade. Não há histórico municipal integral desde 2018: esse histórico pertence ao recorte de referência. A cidade sem soja histórica não recebe uma referência inventada.

## Limites operacionais

Coletas estaduais podem levar horas ou dias e consumir a cota Copernicus. Dependem de internet, credenciais e disponibilidade das fontes. Sem credenciais, a base municipal é coletada e as imagens ficam pendentes. Datas de corte das consultas filhas são registradas separadamente: uma coleta prolongada pode atravessar dias.

Permanecem os limites existentes: 350 milhões de pixels para resumo municipal, 50 milhões para identificação municipal da soja e os limites de tamanho do histórico Sentinel-2. Municípios que excedem o processamento são apresentados como parciais, sem extrapolação de amostra para total municipal. A retomada pode refazer processamento para recompor resultados a partir do cache; não é um checkpoint a cada pixel ou recorte.

Para uma área própria: selecionar seu município, desenhar/carregar o polígono e clicar em **Analisar histórico da área selecionada**. O servidor verifica a inclusão na malha IBGE. A cultura e a safra desse polígono continuam sendo declarações do produtor.

## API

- `GET /api/locations/search?q=Sinop%20MT`: resolve nomes; não inicia a coleta.
- `POST /api/regional-scans` com `{"kind":"municipality","code":"5107909"}` ou `{"kind":"state","code":"51"}`: inicia/reutiliza a rodada.
- `GET /api/regional-scans/{id}`: consulta progresso e retoma rodada interrompida.
- `POST /api/research/history`: aceita `municipality_code` junto da geometria e dos anos. Sem esse parâmetro, mantém Sorriso como padrão de compatibilidade.

Validação técnica: testes automatizados com fontes simuladas cobrem a fila, cache, falhas, retomada, referências e geometria fora do município; teste Chromium cobre busca, ambiguidade, estado, exportação e abertura do histórico. A busca real foi confirmada para MT, Sorriso/MT e Sinop/MT. Uma varredura estadual completa com fontes reais ainda precisa de validação operacional.
