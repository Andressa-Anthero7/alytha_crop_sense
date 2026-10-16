# Análise visual com OpenAI Luna

Em 15/10/2026, a configuração local foi alterada para `AI_PROVIDER=openai` e `OPENAI_MODEL=gpt-6-luna`. As chaves existentes foram preservadas. A configuração é lida do `.env` a cada consulta; mudanças no código Python exigem reiniciar o servidor.

A integração usa a Responses API com `store=false`. As imagens PNG reais são enviadas como `input_image`, em data URLs base64, acompanhadas dos IDs, períodos e evidências numéricas. A validação de conteúdo, SHA-256, limites de tamanho, citações, mudanças entre datas e limitações do NDVI é a mesma aplicada ao Gemini.

O Luna usa raciocínio `low` nas análises visuais, com limite de 4.096 tokens de saída incluindo raciocínio, e `none` nas respostas de texto, com limite de 1.600 tokens. Saídas incompletas ou fora do esquema JSON são rejeitadas. Não há troca automática de modelo ou provedor. Veja [modelo Luna](https://developers.openai.com/api/docs/models/gpt-6-luna) e [entrada de imagens](https://developers.openai.com/api/docs/guides/images-vision).

Resultados concluídos registram provedor, modelo, imagens enviadas e os contadores `input_tokens`, `output_tokens` e `total_tokens` retornados pela API. Características da OpenAI recebem `feature_origin=openai_visual_interpretation`; revisões Gemini existentes preservam sua origem. A interpretação continua sendo uma hipótese, sem criar rótulos humanos de manejo.

Na verificação real de 15/10/2026, foi enviada uma requisição de 182.485 bytes com os três mapas NDVI disponíveis. A OpenAI retornou HTTP 429 e a análise permaneceu inconclusa. Esse teste não confirmou acesso ao modelo nem produziu observações visuais. A última verificação específica de quota, no dia anterior, havia retornado `insufficient_quota` / `credit_balance_exhausted`. É necessário regularizar o saldo ou os limites da organização da chave e repetir a validação real.

A tela de análise visual usa a identificação genérica de IA e mostra o provedor e o modelo nos resultados concluídos. O inventário de recortes e a espera por imagens continuam sendo os mesmos; a seleção do Luna não transforma históricos numéricos em imagens disponíveis.
