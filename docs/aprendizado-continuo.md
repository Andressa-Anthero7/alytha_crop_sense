# Acompanhamento contínuo e aprendizado validado

Implementado em 14/10/2026. A unidade acompanhada é o mesmo polígono ao longo do tempo. O ciclo começa pelas imagens e evolui com referências fornecidas por parceiros; não exige rótulos de campo para explorar padrões de vegetação.

**Integração regional:** todos os municípios e recortes mapeados da base existente agora podem alimentar esse ciclo. A base é consolidada antes das revisões municipais pela Alytha, incluindo dados parciais e pendências. Veja [base integrada e fila regional](base-integrada.md).

## Usar no mapa

Execute `python run.py`. Em **Histórico e leitura por satélite**, abra o histórico de uma área e clique em **Acompanhar esta área continuamente**. O painel **Aprendizado contínuo · satélite, Alytha e campo** mostra a agenda, o resultado da rodada, a revisão da Alytha e a validação de campo. Também permite pausar o acompanhamento ou somente as revisões da IA, antecipar uma consulta e abrir o histórico atualizado do mesmo recorte.

O servidor consulta a agenda a cada minuto. Cada área inscrita é consultada inicialmente e depois a cada cinco dias, com uma área processada por vez. Essa é uma cadência de consulta, não uma garantia de imagem aproveitável: nuvens e dados insuficientes continuam inconclusivos. O servidor precisa permanecer ligado. Fechar a página não interrompe a rotina; desligar o computador interrompe a execução, preservando a agenda para a próxima inicialização. Não há serviço de nuvem ou inicialização automática com o Windows nesta entrega.

## O ciclo implementado

1. A primeira rodada complementa os últimos 90 dias do histórico carregado. Rodadas seguintes releem dez dias antes da última coleta, recuperando também o intervalo de uma eventual interrupção. A agregação de cinco dias fica alinhada ao início de cada ano, como no histórico existente.
2. As observações são combinadas por data, preservando uma leitura boa quando uma releitura tiver qualidade inferior. Apenas intervalos fechados até a data da rodada entram nas características. Não há preenchimento de lacunas com valores inventados.
3. Cada rodada cria um histórico próprio e preserva observações recebidas, qualidade, características temporais, análise, padrões exploratórios e resultado da IA. Rodadas anteriores não são reescritas por novas imagens.
4. Com Gemini configurado, a rotina visual envia imagens reais e evidências numéricas, ponderando hipóteses, alternativas e verificações com o produtor. Sem imagens utilizáveis, a revisão visual permanece pendente. Sem mudança nas evidências úteis, uma revisão anterior concluída não é solicitada novamente. Falhas do provedor não descartam as observações nem produzem uma revisão fictícia. Veja [análise direta das imagens](analise-visual-gemini.md).
5. A fila de campo destaca falta de dados ou divergência entre a regra temporal e o classificador disponível. O parceiro pode confirmar ou corrigir a etapa sugerida, informando período e referência. Cultura e responsável são registrados como declarações. O sistema não verifica por conta própria a veracidade do relato.
6. As confirmações entram no cadastro de registros de campo existente. Quando há registros novos suficientes, o monitor treina e avalia uma versão candidata do classificador de manejo, usando validação por área. A candidata fica versionada e não substitui automaticamente o modelo em uso. A atualização explícita do modelo continua no botão de treinamento existente.
7. O histórico atualizado e o estado do ciclo entram nas evidências da conversação para a mesma geometria. Uma resposta anterior da IA não é tratada como medição nem como confirmação de manejo.

O agrupamento de vegetação desta área usa o histórico atualizado. A consolidação regional reúne também os agrupamentos municipais existentes, todas as observações exportadas e as pendências. As releituras são vinculadas aos recortes mapeados; não extrapolam uma referência para a cidade inteira.

## Preparar a visita e a base de ML

O formulário **Validar ou corrigir com informações de campo** começa sem etapa selecionada. Informe o que foi observado e sua origem. Não copie a hipótese da IA como confirmação. O período precisa estar contido no histórico e ter leituras suficientes; registros sobrepostos na mesma geometria são rejeitados. O identificador da rodada e a origem humana ficam vinculados ao registro. Não são enviados ao treinamento rótulos gerados automaticamente pela Alytha.

**Exportar base de aprendizado contínuo** cria uma pasta em `data/outputs/learning-cycle` com:

- `rodadas.json`: auditoria das coletas, análises e revisões.
- `janelas_ml.csv`: características congeladas, com uma janela por geometria/data e alvo vazio quando não há um registro de campo correspondente. Repetições da consulta no mesmo dia não multiplicam os exemplos de treinamento.
- `manifest.json`: contagens e origem da exportação.

As características de cada rodada usam apenas dados disponíveis naquela rodada. Os alvos podem ser acrescentados depois por validação humana. Para medir desempenho, separe áreas espacialmente independentes e safras; a validação por identificador de área ainda não resolve sobreposição espacial nem substitui avaliação temporal externa. O acompanhamento é experimental e não fornece uma acurácia agronômica validada.

## Persistência, falhas e comandos

Agenda e rodadas ficam no SQLite local, nas tabelas `learning_plans` e `learning_runs`. Os históricos de cada rodada ficam em `source_snapshots`; os registros humanos ficam em `field_events`, com metadados de origem. Modelos avaliados são preservados em `data/models/versions`. Faça backup do banco e dos modelos com o servidor parado.

Uma concessão persistente de uma hora evita processamentos concorrentes da mesma área. Uma rodada interrompida pode ser retomada por nova tentativa após essa concessão expirar. Falhas de coleta deixam uma rodada parcial: a análise e a IA podem usar a base preservada, com a pendência explícita, sem afirmar que chegaram novas imagens. A tentativa de coleta fica agendada para seis horas depois. Falhas de análise também deixam uma pendência e uma tentativa em seis horas. As revisões indisponíveis da IA são tentadas novamente na próxima rodada; a coleta continua independentemente do provedor.

```powershell
# Inscrever a referência Sorriso já existente e executar uma rodada de verdade
python -m app.learning_cycle --enroll-pilot --once

# Consultar as agendas persistidas
python -m app.learning_cycle

# Executar uma única área vencida ou exportar a base sem novas consultas
python -m app.learning_cycle --once
python -m app.learning_cycle --export
```

Não é necessário inscrever novamente uma área após reiniciar. Para outras áreas, use o botão no histórico. Chamadas da IA e do satélite seguem as credenciais, cotas e condições dos provedores já configurados no projeto.

## APIs locais

| Método e rota | Função |
| --- | --- |
| `GET /api/learning-cycle` | Listar áreas e agenda |
| `GET /api/learning-cycle/{plan_id}` | Agenda e últimas 12 rodadas |
| `POST /api/learning-cycle` | Inscrever `dataset_id`, com `name` e `ai_enabled` opcionais |
| `POST /api/learning-cycle/configure` | Atualizar `plan_id`, `enabled`, `ai_enabled` ou `refresh` |
| `POST /api/learning-cycle/review` | Registrar `run_id`, etapa, período, referência e parceiro/cultura opcionais |
| `POST /api/learning-cycle/export` | Exportar rodadas e janelas, sem consultar provedores |
