export const meta = {
  name: 'rag-vs-manual-cost-to-threshold',
  description: 'RAG vs manual, cost in tokens to reach a confidence score >= 8 via generate-validate-retry loop',
  phases: [{ title: 'Generate/Retry' }, { title: 'Validate' }],
}

// The previous experiment (rag-vs-manual-with-validation.js) measured cost
// and quality of a SINGLE attempt per combination — RAG came out cheaper but
// consistently lower-quality (score ~3-4 vs ~6-7 for manual). That answers
// "which is cheaper for one shot," not "what does it cost to guarantee an
// acceptable answer." This workflow answers the second question: for each
// combination, loop generate -> validate -> (if score < threshold) retry
// with the previous validation's feedback, up to MAX_ATTEMPTS, and report
// the total token cost to reach the threshold (or the best score reached if
// it never does).
//
// This simulates a realistic workflow rather than an artificially pure one:
// starting with attempt 2, the RAG strategy is explicitly released from the
// recall-search-only constraint and may fall back to direct file reading if
// the semantic search wasn't enough (see feedbackBlock) — the same thing a
// real user/agent would do. Manual already reads files directly from
// attempt 1, so it gets no such release; it's already the "no constraint"
// baseline. usedFallbackOpportunity on the result flags when a RAG item
// reached a retry (and therefore had the option), not whether it took it.
//
// Claude Code retries resume the SAME CLI session (claude -p -r '<session_id>',
// captured from the previous attempt's JSON stream — `-n`/--name only sets a
// display label, it does not resume) so context — and cache_read — accumulates
// across attempts, same as a human iterating in one conversation. agy is
// stateless per call by design (no session to resume), so an agy "retry" is a
// fresh `agy -p` call that embeds the original question plus the previous
// attempt's feedback in the prompt itself — the same mechanism an agy retry
// would use in practice, since there's no session to continue.

const SCORE_THRESHOLD = 8
const MAX_ATTEMPTS = 3

// Fixed models on both sides — the previous run used `agydelegate
// --complexity medium`, which auto-picks a model based on remaining weekly
// quota (core/model_policy.py). That's fine for routing real work, but it's
// an uncontrolled variable in an experiment: mid-run, the Gemini quota can
// drop below the policy's threshold and silently swap the model to a
// fallback (confirmed happening during dry runs of this very script — some
// calls landed on claude-sonnet-4-6 instead of gemini-3.8-flash-medium).
// Pinning one model per side compares model categories deliberately, and
// --model on agy-delegate.py already skips its auto-pick logic entirely.
//
// This round intentionally uses the CHEAP tier on both sides (not the
// large/capable Sonnet 5 vs. Gemini 3.1 Pro High pair) — realistic routine
// usage rarely reaches for the expensive tier for Q&A-shaped questions like
// these. Risk accepted: a cheap model may never reach SCORE_THRESHOLD in
// MAX_ATTEMPTS, especially RAG (which already starts weaker) — that's a
// valid finding in itself ("cheap tier can't reach acceptable quality even
// with retries"), not a failure of the experiment design.
const CLAUDE_MODEL = 'haiku' // Claude Haiku 4.5, cheapest Claude tier
const AGY_MODEL = 'gemini-3.8-flash-medium' // same model the previous published round used

const QUESTIONS = [
  'Como o isolamento de rede por tenant funciona no cloud-emulator?',
  'Como o cloud-emulator evita acumular lixo (namespaces/interfaces órfãos) em reconciliações repetidas?',
  'Quais são os pré-requisitos de host para rodar o cloud-emulator, e por que cada um é necessário?',
]

const CWD = '/home/alves.igor/sources/dpro/k8s/dpro-k8s-ctx'
const CWD_NOTE = `Trabalhe considerando o diretório topics/cloud-emulator/ dentro do repositório de contexto dpro-k8s-ctx (caminho completo: ${CWD}/topics/cloud-emulator/).`

function withRag(question) {
  return `${question} Use a skill /goriok-skills:recall-search para responder. ${CWD_NOTE}`
}

function withManual(question) {
  return `${question} Responda usando apenas grep/leitura direta dos arquivos em topics/cloud-emulator/, sem usar a skill recall-search. ${CWD_NOTE}`
}

// Same round-prefix mechanism as the previous experiment — new Date() is
// unavailable inside Workflow scripts (would break resume), so the caller
// passes a timestamp via args.roundPrefix when invoking Workflow.
const ROUND_PREFIX = (args && args.roundPrefix) || '202609081930'

const items = []
for (let i = 0; i < QUESTIONS.length; i++) {
  const qId = i + 1
  for (const strategy of ['rag', 'manual']) {
    const question = strategy === 'rag' ? withRag(QUESTIONS[i]) : withManual(QUESTIONS[i])
    for (const tool of ['claude-code', 'agy']) {
      items.push({
        tool,
        strategy,
        questionId: qId,
        label: `${ROUND_PREFIX}${strategy}${qId}${tool.replace(/-/g, '')}`,
        question,
      })
    }
  }
}

const VALIDATION_SCHEMA = {
  type: 'object',
  properties: {
    overallScore: { type: 'number', description: 'Overall confidence 0-10 for the answer as a whole, derived from the per-claim analysis (e.g. average or the score of the weakest load-bearing claim)' },
    claims: {
      type: 'array',
      items: {
        type: 'object',
        properties: {
          claim: { type: 'string' },
          confidence: { type: 'number' },
          label: { type: 'string', description: 'One of the 7 confidence-analysis label phrases, e.g. "This is a well-supported fact (confidence: 9/10)"' },
          sourceTier: { type: 'number', description: '1-6 per the confidence-analysis source hierarchy' },
          caveat: { type: 'string' },
        },
        required: ['claim', 'confidence', 'label'],
      },
    },
  },
  required: ['overallScore', 'claims'],
}

// The goal is to simulate a realistic workflow, not an artificially pure
// one: a real user/agent starting from RAG would fall back to direct
// reading if the semantic search wasn't enough. So on retry, the RAG
// strategy is explicitly allowed to drop the recall-search-only constraint
// and read files directly — manual already had that access from attempt 1,
// so it needs no such release.
function feedbackBlock(prevValidation, strategy) {
  if (!prevValidation) return ''
  const weak = prevValidation.claims
    .filter(c => c.confidence < SCORE_THRESHOLD)
    .map(c => `- "${c.claim}" (confidence: ${c.confidence}/10${c.caveat ? `, ressalva: ${c.caveat}` : ''})`)
    .join('\n')
  const ragRelease = strategy === 'rag'
    ? ' Para esta tentativa, você não está mais restrito à skill recall-search — pode complementar com grep/leitura direta dos arquivos em topics/cloud-emulator/ se a busca semântica não tiver sido suficiente para cobrir essas lacunas.'
    : ''
  return `\n\nA tentativa anterior teve confidence score geral ${prevValidation.overallScore}/10, abaixo do aceitável (>= ${SCORE_THRESHOLD}). Estas alegações ficaram com confiança baixa e precisam de mais evidência/fonte primária antes de responder de novo:\n${weak || '(nenhuma alegação individual abaixo do limite, mas o score geral ainda ficou baixo — revise a resposta como um todo)'}\n\nMelhore a resposta reforçando essas lacunas especificamente — não repita a mesma resposta.${ragRelease}`
}

// -n/--name only sets a display label, it does NOT resume a prior session —
// each `claude -p -n '<label>'` call starts a brand new session regardless
// of whether the label repeats. To actually keep context (and cache_read)
// across attempts, retries must pass `-r '<session_id>'` (--resume) using
// the session_id captured from the previous attempt's JSON stream. agy has
// no equivalent — it's stateless per call by design — so an agy "retry" is
// just a fresh `agy -p` call with the feedback embedded in the prompt.
const GEN_SCHEMA = {
  type: 'object',
  properties: {
    rawOutput: { type: 'string', description: 'The complete raw stdout of the command, verbatim, not summarized' },
    sessionId: { type: ['string', 'null'], description: 'For claude-code: the session_id from the JSON stream (the "system"/"init" event, or the final "result" event). For agy: null, there is no session concept.' },
  },
  required: ['rawOutput'],
}

function generatePrompt(item, attempt, prevValidation, sessionId) {
  const escaped = item.question.replace(/'/g, "'\\''")
  const feedback = feedbackBlock(prevValidation, item.strategy).replace(/'/g, "'\\''")
  let cmd
  if (item.tool === 'claude-code') {
    cmd = attempt === 1
      ? `cd ${CWD} && claude -p -n '${item.label}' --model ${CLAUDE_MODEL} '${escaped}' --output-format json`
      : `cd ${CWD} && claude -p -r '${sessionId}' '${escaped}${feedback}' --output-format json`
  } else {
    cmd = `cd ${CWD} && bash /home/alves.igor/sources/goriok/ai-token-tracker/bin/agydelegate --model ${AGY_MODEL} --task '${item.label}' '${escaped}${feedback}'`
  }
  const attemptNote = attempt === 1 ? '' : ` (tentativa ${attempt}/${MAX_ATTEMPTS}, retomando a sessão anterior)`
  const sessionIdNote = item.tool === 'claude-code'
    ? ' Depois de rodar, extraia o campo "session_id" do stream JSON (aparece no evento "system"/"init" e no evento final "result" — são o mesmo valor) e retorne junto no campo sessionId.'
    : ' Não há session_id para agy — deixe sessionId null.'
  return `Rode exatamente este comando via Bash${attemptNote}, com timeout de pelo menos 180000ms (o comando pode levar 30-90s para retornar).${sessionIdNote} O campo rawOutput deve conter EXATAMENTE o texto que o comando imprimiu no terminal (stdout), copiado literalmente — nunca um resumo do que você fez, nunca uma narração tipo "o comando executou X", nunca um cabeçalho inventado como "=== COMANDO EXECUTADO ===", nunca só o exit code. Se o comando falhar ou não produzir texto útil, rode-o de novo (até 2 vezes) antes de desistir — não retorne uma explicação no lugar da saída. Comando: ${cmd}`
}

function validatePrompt(rawOutput) {
  return `Use a skill /goriok-skills:confidence-analysis para analisar a seguinte resposta técnica, avaliando cada alegação factual segundo o critério da skill (fonte, hierarquia, label de confiança). Depois de rodar a análise, produza o resultado estruturado pedido no schema — não invente um critério próprio, use o vocabulário e a escala exatos da skill.\n\n---\nRESPOSTA A AVALIAR:\n${rawOutput}`
}

// Sanity gate before spending a validation call: a generation agent can
// stray from "run the command, return its raw stdout" into narrating what
// it did instead (seen in practice: "EXIT_CODE=0", a one-line "\n", prose
// like "O comando solicitado (...)", a "=== COMANDO EXECUTADO ===" header).
// Passing that to confidence-analysis produces a technically correct but
// useless verdict — "this isn't a real answer" scored 10/10 as a claim,
// which the retry loop then misreads as reachedThreshold=true. Reject
// obviously-not-a-real-answer output here so it counts as a failed
// generation attempt (retried) instead of a validated one.
function looksLikeRealAnswer(rawOutput) {
  if (!rawOutput || rawOutput.trim().length < 200) return false
  if (/"status"\s*:\s*"ERROR"/.test(rawOutput)) return false
  const narrationPrefixes = [
    /^=== COMANDO EXECUTADO/i,
    /^O comando solicitado/i,
    /^EXIT_CODE=/i,
  ]
  return !narrationPrefixes.some(re => re.test(rawOutput.trim()))
}

// Sequential loop per item (each attempt depends on the previous one's
// validation and, for claude-code, the previous session_id), but items
// themselves run concurrently via parallel() below.
async function runItemWithRetries(item) {
  const attempts = []
  let prevValidation = null
  let sessionId = null

  for (let attempt = 1; attempt <= MAX_ATTEMPTS; attempt++) {
    const gen = await agent(generatePrompt(item, attempt, prevValidation, sessionId), {
      label: `gen:${item.label}:a${attempt}`,
      phase: 'Generate/Retry',
      schema: GEN_SCHEMA,
    })

    const rawOutput = gen ? gen.rawOutput : null
    if (!rawOutput) {
      log(`${item.label} attempt ${attempt}: generation failed, stopping`)
      attempts.push({ attempt, rawOutput: null, validation: null })
      break
    }
    if (item.tool === 'claude-code' && gen.sessionId) sessionId = gen.sessionId

    if (!looksLikeRealAnswer(rawOutput)) {
      // The generation agent returned narration/garbage instead of the
      // command's real stdout — validating it would score "this isn't a
      // real answer" as a high-confidence claim, which the loop below would
      // misread as success. Record the attempt (it spent real tokens) but
      // skip validation and move to the next attempt without a score.
      log(`${item.label} attempt ${attempt}: rawOutput doesn't look like a real answer (${rawOutput.length} chars), skipping validation`)
      attempts.push({ attempt, rawOutput, validation: null })
      continue
    }

    const validation = await agent(validatePrompt(rawOutput), {
      label: `val:${item.label}:a${attempt}`,
      phase: 'Validate',
      schema: VALIDATION_SCHEMA,
    })

    attempts.push({ attempt, rawOutput, validation })
    prevValidation = validation

    const score = validation ? validation.overallScore : null
    log(`${item.label} attempt ${attempt}: score=${score ?? 'n/a'}`)

    if (score !== null && score >= SCORE_THRESHOLD) break
    if (item.tool === 'claude-code' && !sessionId) {
      log(`${item.label} attempt ${attempt}: no session_id captured, cannot resume — stopping retries`)
      break
    }
  }

  const scored = attempts.filter(a => a.validation)
  const bestAttempt = scored.length > 0
    ? scored.reduce((best, a) => (a.validation.overallScore > best.validation.overallScore ? a : best))
    : null

  return {
    ...item,
    attempts: attempts.length,
    reachedThreshold: bestAttempt ? bestAttempt.validation.overallScore >= SCORE_THRESHOLD : false,
    bestScore: bestAttempt ? bestAttempt.validation.overallScore : null,
    finalRawOutput: bestAttempt ? bestAttempt.rawOutput : null,
    finalValidation: bestAttempt ? bestAttempt.validation : null,
    attemptScores: scored.map(a => a.validation.overallScore),
    // RAG items only get permission to fall back to direct file reading
    // starting on attempt 2 (see feedbackBlock) — this flags whether that
    // permission was ever actually granted, not whether the agent used it.
    usedFallbackOpportunity: item.strategy === 'rag' && attempts.length > 1,
  }
}

const results = await parallel(items.map(item => () => runItemWithRetries(item)))

return results.filter(Boolean)
