# Análises verificáveis na conversa

Incremento de 15/10/2026, tarefas IA-02 a IA-12. As ferramentas locais funcionam sem saldo de provedor de linguagem e sem adquirir imagens Sentinel.

## Perguntas disponíveis

Selecione uma área com histórico já salvo:

- “Compare o histórico das safras anteriores.”
- “Qual a direção do esverdeamento?”
- “Registre minha janela de plantio de 01/09/2026 a 30/10/2026.”
- “Faça uma síntese das hipóteses e alternativas.”
- “Compare o histórico até 04/10/2026 para a safra 2026/2027.”
- “Cruze chuva e temperatura com o histórico.”
- “Pesquise referências na Embrapa sobre disponibilidade hídrica da soja.” Esta busca também funciona sem uma área selecionada.

As duas últimas perguntas autorizam consultas às fontes externas correspondentes. Uma síntese comum apenas reutiliza clima em cache; não inicia downloads. A pesquisa web é limitada ao portal oficial da Embrapa, com até três páginas recuperadas por consulta. Não há busca irrestrita na internet nem leitura automática integral de artigos.

## Contrato e trabalhos

As evidências computadas têm `contract_version`, `kind`, `area_key`, `period`, `provenance`, `quality` e `data`. A projeção de evidências antigas informa quando a versão ou a qualidade do método original não é conhecida, sem atribuir uma validação inexistente.

`POST /api/assistant` devolve um recibo `work` para cada análise local, clima ou pesquisa: ID, ferramenta, versão, início, fim e `ready`, `inconclusive` ou `error`. O registro persiste no banco; `GET /api/assistant/work/{id}` o recupera. Uma falha da fonte não se torna uma análise concluída. Na fila durável, a mesma rota retorna o estado da fila e a resposta final em `result`.

O servidor gera `conversation_id` opaco, válido por até 24 horas, e preserva apenas os campos estruturados permitidos. A resposta anterior não vira evidência. A seleção atual de geometria/município prevalece sobre a área anterior. Safra, cultura e corte declarados podem continuar entre perguntas; alterar a seleção ou os campos do cadastro limpa o contexto da interface. Este mecanismo não é autenticação nem isolamento de produtores.

## Cálculos e limites

Comparação histórica reaproveita períodos sazonais de 30 dias, com qualidade e disponibilidade temporal, sem interpolar lacunas. A referência exige três anos comparáveis. A direção usa resultados espaciais compatíveis ou recalcula exclusivamente os três rasters locais exatos, respeitando grade, máscara e período. Ausência de organização espacial permanece explícita.

A janela declarada guarda origem, datas, cultura/safra quando informadas e registro imutável de declaração. Não substitui calendário regional. Declarações feitas depois da data analisada são identificadas como retrospectivas. A síntese separa medições, hipóteses, divergências, dados ausentes e próxima verificação. Não confirma trajeto de plantadeira, linhas, cultura, semeadura ou produtividade.

## Fonte meteorológica selecionada — NASA POWER

Escolha técnica para o primeiro adaptador: dados diários regionais associados ao centro do recorte. A [metodologia oficial](https://power.larc.nasa.gov/docs/methodology/meteorology/) descreve a reanálise MERRA-2 e sua grade de 0,5° por 0,625°, com cobertura desde 1981. São estimativas de grade, distintas de estação e previsão. A disponibilidade recente depende do processamento da fonte; o adaptador mantém ausências visíveis.

O [contrato da Daily API](https://power.larc.nasa.gov/docs/services/api/temporal/daily/) permite séries diárias. Nesta integração, a resposta deve confirmar UTC e unidades `mm/day` para `PRECTOTCORR` e `C` para `T2M_MIN`/`T2M_MAX`. Cache usa célula e parâmetros canônicos; leituras recentes expiram após 24 horas e períodos com mais de 90 dias após 30 dias. A [orientação de distribuição](https://power.larc.nasa.gov/docs/services/) informa que dados recentes recebem revisões posteriores. O cache preserva a versão da API, origem e hash da resposta usada.

O [projeto oferece acesso gratuito](https://power.larc.nasa.gov/) e documenta [uso em produto comercial](https://power.larc.nasa.gov/article/smart-battery-optimization-creates-affordable-energy/). Esta implementação conserva atribuição a NASA POWER e fontes MERRA-2. Não pressupõe SLA, contrato de suporte ou licença de componentes de terceiros: verificar as condições específicas da fonte ao ampliar redistribuição e operação comercial. Nenhum plano pago foi contratado.

A [política oficial de uso de dados NASA Earthdata](https://www.earthdata.nasa.gov/engage/open-data-services-software/data-use-policy) orienta citação, distingue materiais com restrições próprias e impede sugerir endosso comercial pela NASA. O registro do adaptador identifica a origem NASA POWER/MERRA-2; não atribui uma licença de software aos dados meteorológicos.

O cruzamento apresenta precipitação disponível nos intervalos NDVI, número de dias e cobertura; não atribui causalidade nem converte a grade em medição de 10 m. Valores ausentes e sentinela `-999` nunca viram zero.

## Calendário regional — IA-13 parcial

`python -m app.regional_calendar referencia.json` importa uma referência revisada com fonte oficial, cultura, safra, região, vigência, tipo e intervalos. ZARC exige também município, classe de solo, grupo de cultivar, percentual de risco e manejo. Correspondência incompleta permanece inconclusiva; nenhum valor é preenchido por inferência.

Foi identificada a [fonte oficial das portarias de Mato Grosso](https://www.gov.br/agricultura/pt-br/assuntos/riscos-seguro/programa-nacional-de-zoneamento-agricola-de-risco-climatico/portarias/safra-vigente/mato-grosso). A página aponta a [portaria de soja da safra 2026/2027](https://www.gov.br/agricultura/pt-br/assuntos/riscos-seguro/programa-nacional-de-zoneamento-agricola-de-risco-climatico/portarias/safra-vigente/mato-grosso/PORTN202SOJAMT.ret.pdf). Nenhum intervalo foi atribuído automaticamente à área de referência: suas condições de solo/cultivar não foram confirmadas. A carga de referências aplicáveis e sua revisão continuam pendentes. Janela declarada, ZARC e calendário sanitário são tipos distintos.

## Evidências de verificação

`python -m app.offline_evaluation` salva o resultado dos testes e quatro conversas sobre o histórico real em `data/outputs/assistant/offline-evaluation.json`. Os casos automatizados incluem lacunas, baixa cobertura, direção ausente, frentes datadas, janela fora do período, mudança de área e continuidade. Fixtures não são inseridas na base agrícola real.

`python -m app.ml_experiment --dataset-id ID` gera candidatos KMeans versionados sem alterar modelo ativo. A separação é temporal, com normalização ajustada apenas no trecho inicial; janelas vizinhas se sobrepõem e as métricas são exploratórias internas. Não há rótulos de manejo gerados a partir de hipóteses.

`python -m app.ndvi_visual_experiment` compara vizinho mais próximo, bilinear e bicúbica na visualização RGB do NDVI. O manifesto verifica hashes do raster original antes/depois; não é super-resolução por IA nem validação agronômica.
