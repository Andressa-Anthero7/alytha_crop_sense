# Layout da aplicação: mapa e conversa com a Alytha

Direção atualizada por Andressa em 15/10/2026: iniciar no modo I.A, com mapa em destaque e um prompt convidativo como entrada principal da aplicação.

O espaço de trabalho abre com o assistente visível e os filtros recolhidos. No notebook, o mapa ocupa o centro, em uma superfície com cantos arredondados. Um cartão de conversa flutua na parte inferior com boas-vindas, campo de texto amplo e sugestões: dados salvos, mudanças de vegetação e exploração de soja. A paleta combina branco, tons suaves de verde e verde escuro nos controles principais.

A busca de localidades permanece no cabeçalho, junto da identificação e do acesso à base de dados. A faixa lateral dá acesso ao modo I.A, camadas, desenho, importação e gráfico. Os filtros e os gráficos continuam redimensionando o mapa no notebook, preservando o centro. A barra de período fica recolhida na abertura e volta ao abrir ferramentas ou sair do modo I.A.

Ao enviar uma pergunta, a conversa ocupa o lugar das boas-vindas; o prompt permanece acessível. Enter envia e Shift + Enter insere uma linha. O campo cresce até um limite e depois oferece rolagem. Recolher e reabrir a conversa preserva seu conteúdo; a abertura inicial não força o teclado no celular. As sugestões preenchem o campo, sem executar consultas automaticamente.

Em telas menores, o cartão se ajusta à largura, o placeholder é mais curto e as ferramentas alternam com a conversa para evitar sobreposição. O botão I.A retorna ao prompt. Telas de pouca altura usam uma composição compacta. Isso adapta o fluxo de entrada e conversa; não representa revisão de todas as ferramentas científicas no celular.

A base anterior de notebook está em `web/notebook-layout.css`; a nova apresentação está em `web/ai-workspace.css`. O redimensionamento dos mapas, o comportamento do prompt e os controles de conversa ficam em `web/workspace-layout.js` e `web/index.html`.

Verificação com Playwright em 1366 × 768, 1440 × 900, 390 × 844, 320 × 740 e 844 × 390, cobrindo abertura, sugestões, Enter/Shift+Enter, resposta, recolher/reabrir e retorno das ferramentas. APIs são simuladas; nenhum dado de produtor é escrito e nenhuma consulta Sentinel ou a um provedor de IA é executada. A inspeção visual usa Leaflet; mapas Google mantêm a integração existente, sem uma nova verificação visual específica nesta entrega. Screenshots ficam em `data/outputs/layout-ai/`. Os cenários existentes de ações e contexto conversacional também foram conferidos.
