# Spec: motor de IA plugável

Data: 2026-09-19 · Status: implementado e verificado em 24/09/2026

## Contexto

Hoje o agente é fixo: o app chama o Claude Code local com o modelo Opus. Isso trouxe dois problemas medidos no uso real (19/09/2026): custo de US$ 0,11 por chamada, US$ 1,36 em 12 chamadas, e dependência de ter o Claude Code instalado e logado, o que limita quem consegue usar o app.

A decisão é deixar quem usa escolher o motor, desde que ele atenda ao mínimo que o app precisa para funcionar. O app depende de respostas em JSON seguindo um schema; modelos pequenos erram isso com frequência, então a escolha é validada antes de valer.

O limite de 5 usuários do Spotify continua valendo e não muda com esta spec: o app segue pessoal, instalado na máquina de cada um.

## Escopo

Entra: dois adaptadores de motor atrás da interface atual, presets de provedores, tela de configuração, armazenamento local da chave, teste de compatibilidade bloqueante, troca de motor sem reiniciar, eval comparativo entre motores.

Não entra: modelo diferente por tarefa (um para entender, outro para temas); hospedagem do app na internet; qualquer uso de endpoints internos do Spotify.

## Arquitetura

O agente continua falando com `contracts.ports.LLMPort`. Nada em `agent`, `organizer`, `spotify` ou `enrichment` muda.

```
services/llm/
  providers/claude_code.py      runner atual (claude -p), sem chave
  providers/openai_compatible.py runner novo: POST {base_url}/chat/completions
  registry.py                   presets: rótulo, base_url, modelo sugerido, precisa de chave, link da documentação
  factory.py                    build_runner(config) -> runner
  config_store.py               LLMConfigStore: lê e grava data/llm.json
  switchable.py                 SwitchableLLM: guarda o runner atual e permite trocar em tempo de execução
  compat.py                     check(runner) -> CompatReport (3 chamadas reais)
  api.py                        interpret / plan_theme (inalterado, recebe um runner)
```

### Adaptador compatível com OpenAI

Um único adaptador cobre Gemini, Groq, OpenRouter, Mistral, Ollama e LM Studio, porque todos expõem `/chat/completions` no formato da OpenAI e aceitam resposta com schema JSON.

Pedido: `messages` com o prompt de sistema e o do usuário, `response_format` do tipo `json_schema` com `strict: true` e o schema que o app já gera dos modelos pydantic. Resposta: o JSON vem em `choices[0].message.content` e é validado pelos mesmos modelos de hoje, com uma nova tentativa em caso de erro de validação, igual ao fluxo atual.

Sem informação de custo confiável entre provedores, `cost_usd` fica em 0 para motores compatíveis com OpenAI, e o trace passa a registrar `provider` e `model` em cada chamada. O Claude Code continua reportando o custo real.

### Presets

Cada preset é só dado: rótulo, `base_url`, modelo sugerido, se precisa de chave e link para criar a chave. Entram Gemini, Groq, OpenRouter, Mistral, Ollama e LM Studio, mais "Personalizado", que aceita qualquer endereço. Ollama e LM Studio não precisam de chave porque rodam na máquina do usuário.

## Configuração e segredo

A escolha fica em `data/llm.json` (`provider`, `base_url`, `model`, `api_key`), na mesma pasta do token do Spotify, já fora do git. A chave nunca sai do servidor: a API devolve `has_key: true|false`, nunca o valor. O README ganha um aviso de que a chave fica em texto simples nessa pasta, como o token do Spotify.

Sem configuração salva, o app usa o Claude Code local, como hoje. Se ele não estiver instalado, a tela de configuração aparece com a explicação.

Trocar de motor não exige reiniciar: o app guarda o runner atual num ponto único (`SwitchableLLM`), e salvar substitui esse ponto.

## Teste de compatibilidade

É o "padrão mínimo". Ao clicar em "Testar e salvar", o app faz 3 chamadas reais ao motor escolhido:

1. **Entender um pedido simples.** "organiza minha playlist Treino por BPM" deve voltar como reorganizar, com a playlist Treino e ao menos uma opção de BPM.
2. **Propor opções para um pedido aberto.** "arruma a Treino do jeito que você achar melhor" deve voltar como reorganizar, com pelo menos uma opção válida.
3. **Montar um tema pequeno.** Um tema com no máximo 3 posições deve voltar com nome, pelo menos 2 posições e cada uma com palavra-chave e sugestões.

Cada resposta é conferida pelo mesmo código determinístico do eval de intenção (`services/llm/evals/scoring.py`), que passa a viver junto do serviço para ser reutilizado. O relatório traz, por teste: passou ou não, o motivo da falha, o tempo e o custo quando disponível. O motor só é salvo se os três passarem. Falhas comuns ganham mensagem própria: chave recusada, limite do plano atingido, endereço inacessível, resposta fora do schema.

## Interface

A tela ganha um item "Motor de IA" no topo, mostrando o motor ativo (por exemplo, "Claude Code · opus" ou "Gemini · gemini-2.5-flash"). Ele abre um painel com: lista de provedores, campo de endereço quando for personalizado, campo de modelo, campo de chave em modo senha, o botão "Testar e salvar" e o resultado dos 3 testes, um por linha, com o motivo de cada falha. Enquanto os testes rodam, o botão fica desabilitado e mostra que está testando.

## Erros no uso

Chave recusada e limite do plano viram mensagens diretas no chat, com a sugestão de abrir a configuração e trocar de motor. Endereço inacessível idem. Resposta fora do schema depois da nova tentativa vira o erro atual, agora citando o motor em uso. Nada disso grava qualquer coisa no Spotify.

## Medição

O trace por chamada passa a gravar `provider` e `model`, e `/api/stats` mostra o gasto e a latência média por motor. Isso responde de forma objetiva se um motor gratuito serve para o uso diário.

O eval de intenção aceita o motor por variável de ambiente, então os mesmos 25 casos rodam em qualquer motor e a comparação é direta: acerto, tempo e custo.

## Testes e evals

Gate tests, sem rede, com HTTP simulado:

- adaptador compatível com OpenAI: formato do pedido (schema, `strict`, mensagens), leitura da resposta, erros 401, 429, 500, endereço inacessível e conteúdo que não é JSON;
- registry: todo preset tem rótulo, endereço e modelo, e os que não precisam de chave são os locais;
- config store: ida e volta, arquivo ausente, arquivo corrompido vira "sem configuração", e a serialização para a API nunca inclui a chave;
- compat: passa com motor bom, falha com resposta fora do formato, falha com erro de chave, e o motivo certo aparece no relatório;
- switchable: a troca passa a valer na chamada seguinte;
- rotas web: `GET /api/llm`, `POST /api/llm/test`, `POST /api/llm` (salva só se passar) e o caso de chave inválida.

Evals pagos, rodados à mão:

- `run_intent` nos motores configurados, com relatório de acerto, tempo e custo por motor;
- limiar: 90% de acerto, o mesmo de hoje.

## Verificação ponta a ponta

1. Sem configuração, o app usa o Claude Code, como hoje.
2. Configurar o Gemini com chave grátis: os 3 testes passam, a tela mostra "Gemini · gemini-2.5-flash" e o chat responde sem reiniciar o app.
3. Configurar um modelo fraco de propósito (por exemplo, um modelo pequeno no Ollama): o teste falha com o motivo, e o motor anterior continua valendo.
4. Colar uma chave errada: o teste falha com "chave recusada", e nada é salvo.
5. Rodar o eval de intenção em dois motores e comparar acerto, tempo e custo.

## Resultados medidos (24/09/2026)

- Gate tests: 270 testes, cerca de 2,5s, sem avisos.
- Teste de compatibilidade: as 3 checagens passaram no Claude Code com o modelo sonnet, escolhido pelo painel.
- Eval de interpretação, mesmos 25 casos: 100% de acerto com sonnet (`data/evals/intent-20260924-185437.json`)
  e 100% com opus (`data/evals/intent-20260919-010243.json`).
- Custo e tempo por chamada, mesmo pedido nos dois modelos: sonnet US$ 0,0236 em 12,0s; opus US$ 0,0906 em 15,3s.
  Ou seja, trocar opus por sonnet corta cerca de 3/4 do custo sem perder acerto nesses casos.
- O eval passou a registrar custo e tempo por execução, então a comparação entre motores sai direto do relatório.

## O que ficou aberto

- Nenhum provedor externo foi exercitado com chave real ainda (Gemini, Groq, Ollama). O caminho está testado com
  HTTP simulado e o teste de compatibilidade bloqueia motor ruim, mas o primeiro uso real ainda vai acontecer.
- Modelo diferente por tarefa continua fora: hoje o motor escolhido atende tanto a interpretação quanto os temas.
  Os números acima sugerem que sonnet dá conta dos dois.
