# Rodada de 16/10/2026 · ciclo da soja

Solicitação: incluir Sentinel-1 e janela oficial na avaliação de plantio, pesquisar o ciclo completo e organizar o estudo dentro do sistema.

## Entrega desta rodada

Pesquisa inicial de 22 temas, do planejamento à pós-colheita, disponível em **Camadas → Ciclo da soja · estudo e planejamento**. Cada tema tem pergunta, objetivo, proposta de acompanhamento, informação de campo necessária, limites e fontes. A seção não classifica automaticamente a área selecionada. O catálogo estruturado fica em `web/soy-study.json`; a matriz consultável está em [ciclo-soja-estudo.md](ciclo-soja-estudo.md) e na aba **Ciclo soja 16-10** do [quadro](quadro-implementacao-ia.xlsx).

Tarefas IA-13, IA-17, IA-18 e IA-23 tiveram escopo/próxima ação ampliados, preservando o histórico. Novas entregas: **IA-29** (integração janela/radar na conclusão), **IA-30** (catálogo e aprofundamento do estudo) e **IA-31** (acompanhamento validado por etapa). Preparar o catálogo não conclui reconhecimento de fases nem validação agronômica. Não houve nova aquisição Sentinel, agendamento, alteração de credenciais ou treinamento de modelo.

## Janela oficial · IA-13 e IA-29

1. Identificar município pela geometria; não confiar apenas na cidade selecionada na interface. Registrar soja, safra e data pretendida.
2. Recuperar fonte oficial e vigência, preservando documento, origem, data de consulta e versão. Revisar o importador já existente em `app/regional_calendar.py`.
3. Separar calendário sanitário, janela ZARC, referência agronômica e janela declarada pelo produtor. Uma não substitui a outra.
4. Para ZARC, confirmar solo, grupo de cultivar, manejo e nível de risco aplicáveis. A tabela municipal pode ter vários intervalos; não usar apenas a primeira e a última data como intervalo contínuo.
5. Apresentar **dentro**, **fora**, **não aplicável** ou **pendente**, explicando qual condição faltou. Fonte vencida ou combinação incompatível impede conclusão automática.
6. Testar vigência, safra cruzando anos, bordas de decêndios, município vizinho, solo/cultivar ausente, intervalo descontínuo e conflito entre fontes.

Base: [MAPA/ZARC](https://www.gov.br/agricultura/pt-br/assuntos/riscos-seguro/programa-nacional-de-zoneamento-agricola-de-risco-climatico/zoneamento-agricola). A documentação anterior localizou a portaria de soja MT 2026/27, mas isso não significa que as condições do recorte estejam preenchidas ou que o quadro normativo esteja automaticamente integrado ao card.

## Sentinel-1 · IA-17 e IA-18

Plano de engenharia, a validar com dados reais:

1. Confirmar produto, cobertura, acesso, disponibilidade, limites e custo antes da retomada. Preparar contrato de evidências e testes locais; manter a restrição de aquisição existente.
2. Selecionar cenas GRD compatíveis: modo, polarizações disponíveis, direção e órbita relativa, datas, ângulo de incidência e processamento. Não comparar indiscriminadamente órbitas ascendentes e descendentes.
3. Definir coeficiente de retroespalhamento e unidades; explicitar domínio linear versus dB. Preservar nodata, bordas, ruído, correção geométrica/radiométrica e efeitos de relevo. Validar opções reais do fornecedor em vez de supor um processamento padrão universal.
4. Alinhar as cenas à mesma grade e área. Controlar speckle sem confundir suavização visual com ganho de resolução; registrar resolução efetiva e agregação.
5. Propor características temporais VV/VH apenas quando as polarizações estiverem disponíveis. Analisar mudança, persistência e posição dentro da referência local da mesma órbita. Não converter valor de radar em porcentagem de água por um limiar universal.
6. Cruzar chuva, solo/modelo, cobertura Sentinel-2 e operações de campo. Chuva, rugosidade, vegetação e manejo podem produzir mudanças de sinal parecidas.
7. Comparar duas versões: **óptico + clima** versus **óptico + clima + radar**. Medir cobertura útil, falsos alertas, inconclusivos e ganho por tarefa em áreas/safras independentes.
8. Integrar apenas evidência validada à conclusão curta. Radar ajuda a investigar a superfície; não determina calendário, fertilidade, doença, espécie ou plantio confirmado.

Fontes: [Copernicus — Sentinel-1 GRD](https://documentation.dataspace.copernicus.eu/APIs/SentinelHub/Data/S1GRD.html) e [ESA — umidade do solo](https://knowledge-hub-gda.esa.int/eo_capability/soil-moisture/). O protocolo acima é proposta de implementação, não resultado de validação ou estimativa de desempenho.

## Ordem do estudo e implementação

1. **Janela, solo e implantação:** melhorar a decisão de plantio e o registro de semeadura; manter o sinal automático “possível plantio ou rebrota”.
2. **Água, cobertura e organização espacial:** separar onde o verde aumentou, a sequência das manchas e causas alternativas.
3. **Desenvolvimento e fases reprodutivas:** relacionar estádios VE/VC, V e R a registros de campo. Não atribuir R1–R8 por uma curva NDVI sem validação específica.
4. **Manejo transversal:** amostragem de pragas, doenças, plantas daninhas, nutrição e operações, com responsável técnico e dados observados.
5. **Maturação, colheita e pós-colheita:** comparar operações reais às mudanças por satélite; qualidade do grão e armazenamento dependem de medições locais.

Cada incremento precisa de contrato de entrada, fonte aplicável, disponibilidade temporal, conclusão curta, próximo passo, alternativas e testes positivos/negativos/com lacunas. Avaliação externa separa talhões, produtores e safras; hipótese automática não vira rótulo de campo. As doses, produtos e recomendações de intervenção não são inferidos de imagem.

## Base de pesquisa e limites

[Embrapa — Tecnologias de produção de soja, 2020](https://www.infoteca.cnptia.embrapa.br/handle/doc/1123928): consulta da estrutura geral e tópicos pertinentes, incluindo capítulos de solo, instalação, diversificação, fertilidade, fixação biológica, pragas, doenças, daninhas, operações, sementes e pós-colheita. Não houve revisão exaustiva de todas as referências de cada capítulo. A publicação é base técnica, não comprovação de regra vigente em 2026.

[Embrapa — estádios fenológicos](https://bioinfo.cnpso.embrapa.br/seca/index.php?Itemid=435&catid=84&id=74:estadios-fenologicos&option=com_content&view=article): estrutura vegetativa e reprodutiva; descrição técnica não é detecção automática. [Embrapa — armazenamento, 2023](https://www.infoteca.cnptia.embrapa.br/infoteca/bitstream/doc/1155426/1/Circ-Tec-196.pdf): referência específica de pós-colheita. Revisão agronômica regional e atualização normativa permanecem necessárias.
