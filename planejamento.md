# NeoClips — Plano de Desenvolvimento do MVP

## Versão revisada com Multimodal Observation Engine

## 1. Objetivo

O NeoClips será uma engine de descoberta, produção e preparação de cortes a partir de conteúdo audiovisual longo.

Seu objetivo inicial é transformar:

```text
podcast / entrevista / live / programa / vídeo longo
                        ↓
                     ingestão
                        ↓
                    análise
                        ↓
               descoberta de cortes
                        ↓
                 ranking editorial
                        ↓
                   renderização
                        ↓
          título / thumbnail / descrição
                        ↓
                       QA
                        ↓
                READY_FOR_REVIEW
```

O projeto deve aproveitar a infraestrutura madura do NeoVids sem duplicar responsabilidades que já foram corretamente implementadas.

---

# 2. Escopo operacional

Existirão dois modos principais.

## 2.1. `safe_automated`

Para fontes cuja utilização foi previamente verificada.

O sistema conhece:

```text
commercial_use_allowed
derivatives_allowed
monetization_allowed
allowed_platforms
max_clip_duration
embargo
attribution
outras restrições
```

Esse será futuramente o modo elegível a automação completa.

---

## 2.2. `manual_override`

O operador fornece deliberadamente um vídeo.

O NeoClips pode:

```text
analisar
descobrir cortes
renderizar
produzir thumbnails
produzir títulos
produzir descrições
executar QA
```

mesmo quando:

```text
rights_status = unverified
```

Persistindo obrigatoriamente:

```text
operator_override = true
```

O sistema nunca converte:

```text
unverified
```

em:

```text
authorized
```

automaticamente.

No MVP, ambos os modos terminam normalmente em:

```text
READY_FOR_REVIEW
```

Publicação automática fica para uma etapa posterior.

---

# 3. Decisão fundamental sobre o Media Indexer

O Media Indexer será reutilizado como serviço.

Ele continuará responsável por:

```text
MediaProject
MediaSession
MediaAsset

storage
SHA-256
ffprobe

Transcription
TranscriptSegment

word timestamps

VisualIndex
TemporalIndex
Media Search
```

quando essas capacidades forem necessárias.

O NeoClips NÃO implementará:

```text
outro Whisper
outro armazenamento audiovisual
outro ffprobe
outro sistema de identidade de mídia
```

O Media Indexer já possui jobs duráveis com heartbeat, recuperação de jobs stale, attempts limitados e PostgreSQL como fonte autoritativa do estado.

---

# 4. A questão de `notes`

O endpoint atual de ingestão exige:

```text
video
notes
```

no multipart.

Entretanto o backend apenas:

1. lê o arquivo;
2. decodifica como UTF-8;
3. persiste `raw_notes`;
4. aplica `split_note_units()`;
5. cria zero ou mais `Note`.

E o parser retorna explicitamente:

```python
[]
```

quando o conteúdo é vazio.

Portanto, no MVP:

```text
video real
+
neoclips_empty_notes.txt
```

é um contrato de compatibilidade válido.

Não há necessidade de alterar o Media Indexer imediatamente.

---

# 5. Por que NÃO devemos guardar notas de IA como `Note`

Esse detalhe é importante.

No domínio atual:

```text
MediaSession
```

representa mídia + documento exato de notas, e:

```text
Note
```

é uma unidade ordenada e imutável extraída desse documento.

Além disso:

```text
Note.raw
```

é deliberadamente imutável.

No NeoVids isso representa muito bem:

> “Bernardo observou isto durante a gameplay.”

Não devemos começar a misturar isso com:

> “Gemini acha que isto aconteceu.”

São provenances completamente diferentes.

Portanto:

```text
Human Note
≠
Machine Observation
```

---

# 6. Novo conceito: Multimodal Observation Engine

O NeoClips possuirá um subsistema:

```text
Observation Engine
```

responsável por gerar observações derivadas da mídia.

No MVP ele ficará **dentro do repositório NeoClips**, porém atrás de interfaces próprias.

Não criaremos imediatamente outro microserviço.

Motivo:

```text
NeoClips → único consumidor inicial
```

Um novo microserviço adicionaria:

```text
API
container
healthcheck
deployment
fila
persistência
cliente
recovery
observabilidade
```

antes de sabermos se precisamos dele.

Entretanto a boundary deverá permitir posteriormente extrair:

```text
neoclips/app/services/observations/
```

para:

```text
media-observer
```

sem mudar o domínio.

Isso será particularmente interessante quando o próprio NeoVids quiser gerar automaticamente observações de gameplay.

---

# 7. Arquitetura revisada

```text
                     SOURCE
                       │
                       ▼
                MEDIA INDEXER
                       │
              ┌────────┴─────────┐
              │                  │
              ▼                  ▼
         TRANSCRIPTION      VISUAL EVIDENCE
              │              opcional
              │                  │
              ▼                  │
      Transcript Discovery      │
              │                  │
              ▼                  │
        Raw Candidates           │
              │                  │
              ├──────────────────┘
              │
              ▼
      OBSERVATION ENGINE
          opcional
              │
              ▼
      Candidate Enrichment
              │
              ▼
      Ranking / Deduplication
              │
              ▼
           Selection
              │
              ▼
        VIDEO COMPOSER
              │
              ▼
      Packaging + Thumbnail
              │
              ▼
              QA
              │
              ▼
       READY_FOR_REVIEW
```

A palavra importante é:

**opcional.**

Um podcast simples não deve custar uma análise multimodal completa obrigatoriamente.

---

# 8. Estratégia de análise em cascata

Esse será um dos princípios centrais do NeoClips.

Não usar:

```text
vídeo de 2h
   ↓
Gemini olha tudo detalhadamente
   ↓
descobre cortes
```

como estratégia padrão.

Usar:

```text
vídeo de 2h
   ↓
ASR local
   ↓
análise textual barata
   ↓
100 candidatos brutos
   ↓
30 candidatos razoáveis
   ↓
análise multimodal
   ↓
10–20 candidatos fortes
```

Isso reduz:

```text
custo
latência
upload
tokens multimodais
dependência externa
```

---

# 9. Perfis de análise

Criar perfis versionados.

## `podcast_fast_v1`

```text
ASR
↓
text discovery
↓
ranking
```

Sem multimodal obrigatório.

Ideal para testar grandes volumes rapidamente.

---

## `podcast_enriched_v1`

```text
ASR
↓
text discovery
↓
Top N candidate windows
↓
multimodal observation
↓
reranking
```

Provavelmente será o melhor equilíbrio.

---

## `visual_longform_v1`

Para:

```text
gameplay
vídeo visual
conteúdo com pouca fala
stream
```

Fluxo:

```text
ASR
+
visual chunk analysis
↓
Machine Observations
↓
candidate discovery
```

Aqui a análise visual tem peso muito maior.

---

## `manual_notes_v1`

Quando o operador já possui notas:

```text
human notes
+
transcript
+
media
```

As notas humanas têm prioridade de provenance.

---

# 10. ObservationRun

Criar uma entidade persistida:

```text
ObservationRun
```

Representa uma execução específica do observador.

Campos conceituais:

```yaml
id:

clip_source_id:
media_id:
transcription_id:

strategy:
strategy_version:

provider:
model:

prompt_version:
prompt_hash:

input_mode:
  frames
  native_video
  transcript_plus_frames

configuration:

status:
  pending
  processing
  completed
  completed_with_warnings
  failed

usage:
latency:

fingerprint:

started_at:
completed_at:
```

Uma mudança em:

```text
modelo
prompt
sampling
proxy
resolution
strategy
```

gera nova identidade.

Não sobrescrever observações antigas.

---

# 11. MediaObservation

Cada observação terá provenance temporal.

Exemplo:

```yaml
id:

observation_run_id:

start_seconds:
end_seconds:

type:
  topic
  statement
  conflict
  reaction
  joke
  anecdote
  story
  emotional_peak
  visual_event
  quote
  transition
  context

summary:

subjects: []

salience:
emotional_intensity:
visual_salience:
standalone_potential:

transcript_segment_ids: []

anchors:
  - timestamp:
    description:

confidence:
```

Ela é:

```text
DERIVED EVIDENCE
```

e não:

```text
SOURCE TRUTH
```

---

# 12. Provenance

Toda observação deverá saber exatamente de onde veio.

```yaml
provenance:

  source_media_id:

  source_start_seconds:
  source_end_seconds:

  transcription_id:

  provider:
  model:

  strategy:
  prompt_version:

  analysis_proxy_identity:

  generated_at:
```

O modelo nunca pode criar:

```text
UUID
media_id
source path
```

O backend fornece e canonicaliza esses campos.

---

# 13. Observation Provider

Criar a interface:

```text
MultimodalObservationProvider
```

Conceitualmente:

```python
analyze(request) -> ObservationProviderResponse
```

Não codificar:

```python
GeminiClient
```

diretamente dentro do domínio.

Isso permite:

```text
GeminiVideoProvider
LiteLLMFrameProvider
OpenRouterMultimodalProvider
LocalVisionProvider
```

futuramente.

---

# 14. Primeiro provider recomendado

Para chegar ao MVP rapidamente, eu começaria com:

```text
LiteLLMFrameObservationProvider
```

e não diretamente com upload de vídeo Gemini.

Isso porque o NeoVids já implementou praticamente o padrão que precisamos.

O Multimodal Alignment atual já:

```text
extrai frames
marca timestamp absoluto
envia transcript
envia imagens em baixa resolução
usa JSON Schema
temperature = 0
valida output
```

através do endpoint OpenAI-compatible do LiteLLM.

E valida que timestamps retornados não escapem da janela analisada.

Esse padrão deve ser reaproveitado quase literalmente como **arquitetura**, não copiando a semântica de alignment.

---

# 15. Reutilização da estratégia multimodal do Media Indexer

O Media Indexer já faz uma coisa muito correta:

```text
candidate window
       ↓
compact JPEG sampling
       ↓
LLM multimodal
```

Em vez de enviar mídia gigante.

Ele ainda:

* aumenta espaçamento automaticamente para limitar quantidade de frames;
* restringe sampling à candidate window;
* permite refinement posterior;
* persiste metadata/checksum dos frames;
* usa base64 apenas durante transporte.

Essa arquitetura combina perfeitamente com NeoClips.

---

# 16. Gemini Native Video Provider

Depois da POC inicial, adicionar:

```text
GeminiVideoObservationProvider
```

Esse provider pode ser particularmente útil para:

```text
gameplay
reações rápidas
interação entre pessoas
humor visual
momentos onde movimento importa
```

Atualmente a API Gemini consegue analisar simultaneamente áudio e vídeo, descrever eventos e trabalhar com timestamps. A File API é recomendada para arquivos longos/reutilizáveis e suporta arquivos grandes.

---

# 17. Não cortar fisicamente o vídeo necessariamente

A ideia inicial seria:

```text
vídeo 2h
↓
FFmpeg
↓
12 vídeos de 10 min
↓
upload de 12 arquivos
```

Isso deve existir como fallback.

Mas **não deve ser a primeira opção para Gemini**.

Quando possível:

```text
original
↓
Gemini Files API
↓
file_id reutilizável
↓
análises temporais específicas
```

A API atualmente permite trabalhar com intervalos temporais da mídia, evitando criar necessariamente um novo arquivo físico para cada pedaço.

Portanto:

```text
um upload
+
vários intervalos
```

é preferível.

---

# 18. Analysis Proxy

Ainda assim vale criar um mecanismo de proxy.

Motivos:

```text
upload mais rápido
fontes gigantes
provider sem upload persistente
controle de privacidade
redução de armazenamento remoto
experimentos
```

Criar:

```text
analysis_proxy_v1
```

Conceitualmente:

```text
H.264
360p ou 480p
FPS reduzido
áudio mono
bitrate baixo
timestamps preservados
```

Mas os parâmetros serão definidos por benchmark.

Nada de assumir que:

```text
360p / 1 FPS
```

é automaticamente ideal.

---

# 19. Detalhe importante sobre redução de FPS

O próprio Gemini atualmente faz sampling visual padrão aproximadamente a **1 FPS** em vídeo e processa áudio separadamente.

Portanto reduzir:

```text
30 FPS → 15 FPS
```

localmente provavelmente economizaria principalmente:

```text
upload
storage
```

e não necessariamente tokens de inferência na mesma proporção.

Faz mais sentido experimentar:

```text
1 FPS
2 FPS
```

para conteúdo lento.

Para gameplay ou ação:

```text
2–5 FPS
```

pode preservar mais acontecimentos, dependendo do provider e da estratégia.

Gemini também oferece controle de resolução multimodal justamente para equilibrar custo, latência e detalhe.

---

# 20. Benchmark obrigatório para proxies

Criar um corpus de avaliação.

Por exemplo:

```text
20 trechos
```

com:

```text
movimento
fala normal
discussão
risada
interrupção
reação facial
texto na tela
gameplay
ação rápida
```

Testar:

```text
original
480p
360p

1 FPS
2 FPS

low media resolution
default media resolution
```

E comparar:

```text
event recall
timestamp accuracy
observation quality
latency
tokens
cost
upload bytes
```

Só então congelar:

```text
analysis_proxy_v1
```

---

# 21. Duas fases de multimodal

O melhor desenho para podcasts é:

## Pass A — discovery barato

O transcript procura:

```text
declarações fortes
histórias
controvérsias
piadas
opiniões
perguntas
respostas
conflitos
payoffs
```

## Pass B — multimodal validation

Somente os melhores candidatos recebem imagens/vídeo.

O observador procura:

```text
reação visual
interrupções
risadas
mudança de tom
gestos
expressão
contexto visual
participantes envolvidos
possível começo/fim melhores
```

---

# 22. Não pedir ao multimodal para descobrir timestamps arbitrários

O mesmo princípio do NeoVids permanece.

O provider recebe:

```text
candidate:
  1830s → 1920s
```

e pode responder somente dentro de:

```text
[1830, 1920]
```

Qualquer timestamp fora disso:

```text
InvalidObservationOutput
```

O Media Indexer já utiliza exatamente essa filosofia para alignment.

---

# 23. Human Notes como Gold Corpus

As suas notas manuais de The Witcher seriam **muito úteis**.

Mas não tanto para ensinar:

> “o que viraliza em podcast”.

Elas seriam úteis principalmente para calibrar:

```text
como um humano descreve acontecimentos
qual granularidade vale registrar
como resumir sem inventar
como preservar ordem temporal
como distinguir observação de interpretação
como identificar eventos interessantes
```

Eu criaria futuramente:

```text
observation_gold_corpus/
```

com:

```text
source clip
human observations
machine observations
human rating
```

---

# 24. Corpus específico para NeoClips

Depois, para clip discovery, precisaremos de outro benchmark.

Idealmente:

```text
10–20 vídeos longos
```

e para cada um:

```text
cortes que humanos escolheram
cortes que realmente performaram
cortes ruins
```

Assim podemos medir:

```text
candidate recall
top-k recall
ranking quality
boundary quality
```

---

# 25. Métrica-chave: Candidate Recall

Suponha que humanos tenham encontrado:

```text
20 bons momentos
```

NeoClips encontra:

```text
17
```

Temos:

```text
85% recall
```

Essa é uma métrica muito mais útil durante desenvolvimento do que:

> “o Gemini parece estar fazendo boas notas”.

---

# 26. Métrica de ranking

Também medir:

```text
Top 5 humano
```

contra:

```text
Top 5 NeoClips
```

Um ótimo momento encontrado na posição:

```text
#72
```

significa:

```text
discovery bom
ranking ruim
```

Um ótimo momento completamente ausente significa:

```text
discovery ruim
```

São problemas diferentes.

---

# 27. Modelo de domínio completo

## `SourcePolicy`

```yaml
verification_status:
commercial_use_allowed:
derivatives_allowed:
monetization_allowed:
allowed_platforms:
max_clip_duration_seconds:
attribution_required:
attribution_template:
embargo_seconds:
evidence:
verified_at:
```

---

## `ClipSource`

```yaml
mode:
  safe_automated
  manual_override

media_project_id:
media_session_id:
media_id:
transcription_id:

source_sha256:

rights_status:
operator_acknowledged:
```

---

## `ClipWorkflow`

Estados:

```text
created
ingesting
transcribing
discovering
observing
reranking
awaiting_selection
rendering
packaging
qa
ready_for_review

blocked
failed
cancelled
```

---

## `ClipAnalysisRun`

```text
strategy
strategy_version
prompt
model
configuration
fingerprint
usage
latency
status
```

---

## `ObservationRun`

```text
multimodal analysis identity
```

---

## `MediaObservation`

```text
derived temporal observations
```

---

## `ClipCandidate`

```yaml
start:
end:

transcript:

scores:
  hook_strength:
  standalone_context:
  narrative_completeness:
  payoff:
  emotional_intensity:
  novelty:
  titleability:
  visual_interest:
  short_fit:
  context_risk:

overall_score:

observation_ids: []

status:
```

---

## `ClipVariant`

```text
horizontal
vertical
```

---

## `ClipPackage`

```text
title
description
tags
hashtags
thumbnail
attribution
```

---

## `ClipQAReport`

```text
checks
warnings
failures
publication_ready
fingerprint
```

---

# 28. Clip Discovery Engine

Implementar:

```text
TranscriptFetcher
TranscriptWindowBuilder
ClipDiscoveryProvider
ClipCandidateCanonicalizer
ClipBoundaryRefiner
ClipScorer
ClipDeduplicator
```

---

# 29. Transcript Windowing

Nunca enviar duas horas de transcrição numa chamada.

Criar janelas aproximadamente:

```text
3–5 minutos
```

com overlap:

```text
30–60 segundos
```

adaptável por perfil.

Resultado:

```text
vídeo longo
    ↓
analysis windows
    ↓
raw candidates
```

---

# 30. Structured Output

Reutilizar a filosofia do Ideas Hub.

Ele já possui contratos rígidos Pydantic para JSON produzido por LLMs.

NeoClips deverá rejeitar:

```text
JSON inválido
segmento inexistente
campo extra
score fora do range
timestamp arbitrário
```

---

# 31. Prompt Architecture

Criar versões independentes:

```text
clip_discovery_prompt_v1
clip_observation_prompt_v1
clip_rerank_prompt_v1
clip_packaging_prompt_v1
clip_editorial_review_v1
```

O Ideas Hub já possui um `PromptBuilder` com composição e trace de identidade; esse padrão deve ser reproduzido.

---

# 32. Clip Score

O LLM fornece features.

O backend produz o ranking final.

Exemplo:

```text
hook
standalone
payoff
novelty
emotion
visual
titleability
context risk
```

entram em:

```text
clip_score_v1
```

Não usar simplesmente:

```text
LLM says viral_score = 0.96
```

como autoridade.

---

# 33. Multimodal Fusion

Quando existirem observações:

```text
Transcript Score
      +
Observation Score
      +
Deterministic Features
      ↓
clip_score_v1
```

Por exemplo:

```text
text candidate:
0.82

strong visual reaction:
+0.05

incomplete context:
-0.12

final:
0.75
```

Os pesos serão versionados.

---

# 34. Deduplicação

Primeira versão:

```text
temporal IoU
+
transcript similarity
```

Se:

```text
Candidate A
01:15:03–01:16:20

Candidate B
01:15:11–01:16:18
```

e representam o mesmo momento:

```text
keep best
```

Embeddings entram depois.

---

# 35. Boundary Refinement

Depois da seleção inicial:

```text
TranscriptSegment
↓
Word timestamps
↓
boundary refinement
```

Encontrar:

```text
começo natural da sentença
fim natural
pausa
payoff
```

sem inventar fala.

---

# 36. Video Composer

Reutilizar:

```text
job persistence
fingerprints
idempotency
atomic cache
source materialization
FFmpeg
Remotion
ffprobe
crash recovery
output validation
```

O Composer já reconcilia jobs após restart e não considera output completo se o arquivo final não passar na validação.

---

# 37. Novo contrato de render

Não reutilizar artificialmente `ProductionTimeline`.

O contrato atual é específico para:

```text
gameplay
narration track
ProductionTimeline v1
```

Criar:

```text
clip_render_manifest_v1
```

---

# 38. Render profiles

## Horizontal

```text
clip_horizontal_1080p30_v1

1920×1080
H.264
AAC
source audio
captions
```

## Vertical

```text
clip_vertical_1080x1920_30_v1

1080×1920
H.264
AAC
source audio
captions
```

---

# 39. Vertical MVP

Não implementar inicialmente:

```text
active speaker tracking
face detection
dynamic camera
```

Começar com:

```text
foreground source
+
blurred background
+
captions
```

Depois evoluir.

---

# 40. Captions

Geradas deterministicamente dos word timestamps.

Sem LLM.

Agrupar aproximadamente por:

```text
pausa
pontuação
número máximo de palavras
tempo máximo
```

Garantindo:

```text
safe zones
ordem temporal
sem overlaps inválidos
```

---

# 41. Packaging Engine

Inputs:

```text
clip
transcript
observations
source metadata
rights policy
```

Output estruturado:

```text
title
description
hashtags
tags
thumbnail text
editorial angle
```

---

# 42. Attribution

Nunca depender do LLM.

Se:

```text
attribution_required = true
```

o backend aplica:

```text
attribution_template
```

deterministicamente.

---

# 43. Thumbnail MVP

```text
clip
↓
frame extraction
↓
3–6 candidates
↓
frame selection
↓
template
↓
short text
↓
PNG
```

Sem geração de imagem no MVP.

---

# 44. QA

Seguir a excelente separação do NeoVids:

```text
render_completed
≠
publication_ready
```

No NeoVids, um render concluído permanece preservado mesmo quando o QA bloqueia sua liberação.

NeoClips seguirá a mesma regra.

---

# 45. QA determinístico

## Source

```text
source exists
checksum correct
```

## Rights

No safe mode:

```text
policy verified
commercial use allowed
derivatives allowed
platform allowed
duration allowed
embargo satisfied
attribution satisfied
```

## Candidate

```text
valid interval
within source
valid transcription provenance
profile duration
```

## Render

```text
ffprobe
codec
resolution
duration
audio
SHA
```

## Captions

```text
valid times
monotonic
within video
```

## Package

```text
title
description
thumbnail
attribution
```

---

# 46. Editorial QA

Separado.

Pode avaliar:

```text
context loss
misleading headline
missing payoff
weak hook
bad start
bad ending
repetition
```

É advisory.

Nunca modifica silenciosamente artefatos.

---

# 47. Resource strategy — 16 GB

O MVP deve assumir desde o início:

```text
16 GB RAM
RTX 2060 12 GB
Ryzen 5 4500
```

Portanto:

```text
heavy concurrency = 1
```

---

# 48. Stack ativa para NeoClips

Preferencialmente:

```text
PostgreSQL
Redis
Media Indexer
NeoClips
Video Composer
LiteLLM
```

Whisper carrega somente quando necessário.

---

# 49. Stack que não precisa ficar ativa

Durante processamento NeoClips:

```text
Ideas Hub
Orchestrator worker
Qwen
frontend NeoVids
modelos locais grandes
```

podem ficar desligados.

---

# 50. GPU

Nunca planejar simultaneamente:

```text
Whisper
+
Qwen
+
local multimodal LLM
```

O NeoVids já trata Faster-Whisper de forma serializada e suporta política de lifecycle explícita.

---

# 51. Swap

Configurar:

```text
zram
+
swapfile SSD
```

é desejável como margem contra OOM.

Mas o benchmark do MVP precisa passar mantendo working sets razoáveis.

Swap não será considerado substituto de RAM.

---

# 52. Plano de desenvolvimento

## ETAPA 0 — Architecture Freeze

Produzir:

```text
MVP_SCOPE.md
ARCHITECTURE.md
DOMAIN_MODEL.md
CONTRACTS.md
```

Definir:

```text
ownership
states
fingerprints
safe/manual modes
provider boundaries
non-goals
```

---

# ETAPA 1 — Foundation

Criar:

```text
neoclips/
```

com:

```text
FastAPI
SQLAlchemy async
Alembic
PostgreSQL
Celery
Redis
structured logging
health
readiness
```

Entidades:

```text
SourcePolicy
ClipSource
ClipWorkflow
WorkflowErrorHistory
```

Worker:

```text
concurrency = 1
prefetch = 1
```

---

# ETAPA 2 — Media Indexer Integration

Criar:

```text
MediaIndexerClient
```

Fluxo:

```text
video
+
empty compatibility notes
↓
Media Indexer
↓
ffprobe
↓
Transcription
↓
TranscriptSegments
```

Aceite:

* ingest;
* resume;
* ASR;
* word timestamps;
* idempotência;
* nenhuma duplicação desnecessária.

---

# ETAPA 3 — Transcript Clip Discovery

Implementar:

```text
TranscriptFetcher
WindowBuilder
DiscoveryProvider
CandidateCanonicalizer
CandidateScorer
Deduplicator
```

Resultado:

```text
Top N candidates
```

Essa etapa já deve produzir uma POC utilizável.

---

# ETAPA 4 — Observation Engine Foundation

Criar:

```text
ObservationRun
MediaObservation
MultimodalObservationProvider
ObservationPrompt
ObservationCanonicalizer
```

Inicialmente:

```text
LiteLLMFrameObservationProvider
```

reutilizando os padrões comprovados de multimodal alignment do Media Indexer.

---

# ETAPA 5 — Multimodal Candidate Enrichment

Pipeline:

```text
Top transcript candidates
↓
extract/sample visual evidence
↓
ObservationProvider
↓
MediaObservations
↓
candidate reranking
```

Comparar:

```text
text-only
vs
multimodal
```

antes de assumir que multimodal é sempre melhor.

---

# ETAPA 5B — Gemini Native Video Provider

Stretch goal do MVP ou primeira evolução.

Implementar:

```text
GeminiVideoObservationProvider
```

com:

```text
file upload reuse
temporal clipping
media resolution control
provider lifecycle
usage telemetry
```

Mantido atrás da mesma interface.

---

# ETAPA 6 — Video Composer Clip Contract

Criar sem quebrar Stage 16:

```text
ClipRenderRequest
ClipRenderManifest
ClipRenderJob
ClipComposition
ClipSourcePreparer
```

Reutilizar componentes internos existentes.

---

# ETAPA 7 — Captions + Vertical Render

Implementar:

```text
caption builder
horizontal profile
vertical profile
blur background layout
```

---

# ETAPA 8 — Packaging

Implementar:

```text
PackagingProvider
ThumbnailBuilder
ClipPackage
```

Produzir:

```text
horizontal.mp4
vertical.mp4
thumbnail.png
package.json
```

---

# ETAPA 9 — QA

Implementar:

```text
clip_qa_v1
safe_clip_qa_v1
manual_clip_qa_v1
```

Com fingerprint e persistência.

---

# ETAPA 10 — End-to-End Orchestration

State machine:

```text
INGEST
↓
TRANSCRIBE
↓
DISCOVER
↓
OBSERVE optional
↓
RERANK
↓
SELECT
↓
RENDER
↓
PACKAGE
↓
QA
↓
READY_FOR_REVIEW
```

---

# ETAPA 11 — Resource Hardening

Criar benchmark real:

```text
30 min
60 min
120 min
```

Medir:

```text
peak RAM
swap usage
VRAM
CPU
processing time
disk usage
LLM calls
tokens
provider cost
```

Aceite:

```text
zero OOM
bounded memory
recovery after restart
```

---

# ETAPA 12 — Evaluation Harness

Essa etapa é extremamente importante antes de publicação automática.

Criar corpus:

```text
known good clips
known bad clips
human notes
human candidate ranking
```

Métricas:

```text
candidate recall
top-k recall
ranking quality
boundary quality
duplicate rate
multimodal uplift
```

---

# 53. Etapas paralelizáveis

Depois das etapas 0–2:

```text
                ┌─ Stage 3 Discovery
                │
Foundation ─────┼─ Stage 4 Observation
                │
                └─ Stage 6 Composer
```

Podem ser delegadas a agentes diferentes.

Depois convergem.

---

# 54. O que NÃO entra no MVP

Explicitamente:

```text
Kafka
RabbitMQ novo
Growth Engine
YouTube Analytics
automatic trend discovery
automatic source crawling
automatic posting
face tracking
speaker diarization obrigatório
active speaker camera
generative image
generative video
Kubernetes
distributed rendering
multi-machine scheduling
full UI
```

---

# 55. Possível futura extração do Observation Engine

Quando:

```text
NeoClips
+
NeoVids
```

passarem a utilizá-lo de verdade:

```text
Observation Engine
```

pode virar:

```text
media-observer
```

Fluxo:

```text
                     Media Indexer
                          │
                          ▼
                     Media Observer
                     /            \
                    ▼              ▼
               NeoClips         NeoVids
```

Aí ele poderia gerar automaticamente:

```text
gameplay observations
podcast observations
visual events
semantic events
```

sem confundir essas observações com notas humanas.

---

# 56. Uso das notas de The Witcher

As notas manuais existentes podem virar um primeiro:

```text
Human Observation Gold Set
```

Usaremos pares:

```text
vídeo
+
notas humanas
```

para testar:

```text
Gemini
LiteLLM multimodal models
frame sampling
native video
prompts
```

Pergunta objetiva:

> Dado exatamente o mesmo trecho, o observador automático consegue registrar os acontecimentos importantes que um humano registrou?

Métricas:

```text
event recall
hallucination rate
temporal accuracy
useful-detail precision
```

Isso pode inclusive beneficiar futuramente o NeoVids principal.

---

# 57. Definition of Done do MVP

O MVP está completo quando pudermos fazer:

```text
source.mp4
    ↓
NeoClips
```

e receber sem intervenção técnica intermediária:

```text
✓ Media identity
✓ Transcription
✓ Clip discovery
✓ Optional multimodal enrichment
✓ Ranked candidates
✓ Accepted candidates
✓ Horizontal render
✓ Vertical render
✓ Captions
✓ Thumbnail
✓ Title
✓ Description
✓ Attribution
✓ QA
✓ READY_FOR_REVIEW
```

Se reiniciar o computador:

```text
resume
```

Se repetir a mesma operação:

```text
reuse
```

Se mudar:

```text
model
prompt
strategy
sampling
render profile
```

uma nova identidade versionada é criada.

---

# 58. Arquitetura final do MVP

```text
┌─────────────────────────────────────────────┐
│                  NeoClips                   │
│                                             │
│ Source Policies                             │
│ Workflows                                   │
│ Transcript Discovery                        │
│ Observation Engine                          │
│ Candidate Scoring                           │
│ Deduplication                               │
│ Selection                                   │
│ Packaging                                   │
│ QA                                          │
└─────┬───────────────────────┬───────────────┘
      │                       │
      ▼                       ▼
┌───────────────┐       ┌─────────────────┐
│ Media Indexer │       │ Video Composer  │
│               │       │                 │
│ Identity      │       │ Materialization │
│ Storage       │       │ Trim            │
│ ffprobe       │       │ Captions        │
│ ASR           │       │ Remotion        │
│ Word times    │       │ FFmpeg          │
│ Frames        │       │ Validation      │
└───────────────┘       └─────────────────┘

          │
          ▼
┌─────────────────────────┐
│ AI Provider Layer       │
│                         │
│ LiteLLM text            │
│ LiteLLM multimodal      │
│ Gemini native video     │
└─────────────────────────┘
```

---

# 59. Princípio final

O NeoClips não deve tentar ser inteligente em todas as etapas.

Ele deve gastar inteligência cara progressivamente:

```text
DETERMINÍSTICO
     ↓
LOCAL BARATO
     ↓
TEXT LLM
     ↓
MULTIMODAL
     ↓
HUMAN REVIEW
```

ou seja:

```text
FFmpeg / ASR
     ↓
transcript heuristics
     ↓
cheap LLM discovery
     ↓
candidate filtering
     ↓
expensive multimodal only where useful
     ↓
final human judgement
```

Esse desenho oferece o melhor compromisso entre:

```text
qualidade
custo
velocidade
robustez
16 GB RAM
capacidade de escalar futuramente
```

sem transformar a POC em uma arquitetura descartável.
