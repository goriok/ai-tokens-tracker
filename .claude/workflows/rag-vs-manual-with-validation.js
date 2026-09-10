export const meta = {
  name: 'rag-vs-manual-with-validation',
  description: 'RAG vs manual grep, Claude Code vs agy, 3 questions — generate then score each answer with confidence-analysis',
  phases: [{ title: 'Generate' }, { title: 'Validate' }],
}

// Two previous rounds measured only cost (tokens) — never whether the
// cheaper strategy also answered worse. This workflow generates 12 answers
// (3 questions x 2 strategies x 2 tools) via real external CLI calls (not
// the workflow subagent's own reasoning — the whole point is measuring the
// actual claude/agy CLI behavior), then scores each one independently with
// the real confidence-analysis skill (not a reimplemented rubric).
//
// pipeline() (no barrier) lets validation of an early answer start while
// later answers are still generating — unlike the token-only experiment,
// there's no ordering concern here since each item is scored on its own
// merits, not compared pairwise.

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

// Round prefix disambiguates session names across runs — the same "rag-1" name
// was already reused 3x across different days/experiments, causing confusion
// when querying the SQLite store manually. new Date() throws inside Workflow
// scripts (would break resume), so the timestamp is passed in via args instead
// of generated here — pass it as args.roundPrefix (e.g. "202609081930") when
// invoking Workflow. "-" separates prefix/strategy/id/tool in the label, per
// the session_name naming convention. Falls back to a fixed literal if args
// are omitted.
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
        label: `${ROUND_PREFIX}-${strategy}-${qId}-${tool}`,
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

function generatePrompt(item) {
  const escaped = item.question.replace(/'/g, "'\\''")
  const cmd = item.tool === 'claude-code'
    ? `cd ${CWD} && claude -p -n '${item.label}' '${escaped}' --output-format json`
    : `cd ${CWD} && bash /home/alves.igor/sources/goriok/ai-token-tracker/bin/agydelegate --complexity medium --task '${item.label}' '${escaped}'`
  return `Rode exatamente este comando via Bash, com timeout de pelo menos 180000ms (o comando pode levar 30-90s para retornar) e retorne a saída bruta completa, sem resumir ou reformatar: ${cmd}`
}

function validatePrompt(rawOutput) {
  return `Use a skill /goriok-skills:confidence-analysis para analisar a seguinte resposta técnica, avaliando cada alegação factual segundo o critério da skill (fonte, hierarquia, label de confiança). Depois de rodar a análise, produza o resultado estruturado pedido no schema — não invente um critério próprio, use o vocabulário e a escala exatos da skill.\n\n---\nRESPOSTA A AVALIAR:\n${rawOutput}`
}

const results = await pipeline(
  items,
  (_prev, item) => agent(generatePrompt(item), { label: `gen:${item.label}`, phase: 'Generate' }),
  async (rawOutput, item) => {
    if (!rawOutput) {
      log(`${item.label}: generation failed, skipping validation`)
      return { ...item, rawOutput: null, validation: null }
    }
    const validation = await agent(validatePrompt(rawOutput), { label: `val:${item.label}`, phase: 'Validate', schema: VALIDATION_SCHEMA })
    return { ...item, rawOutput, validation }
  },
)

return results.filter(Boolean)
