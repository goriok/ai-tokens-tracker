export const meta = {
  name: 'rag-vs-manual-single-call',
  description: 'Claude Code vs agy vs Copilot CLI, single call per item, código-direto vs contexto+RAG+código',
  phases: [{ title: 'Generate' }, { title: 'Validate' }],
}

// Predecessor (rag-vs-manual-cost-to-threshold.js) compared two separate
// strategy arms (rag vs manual) with a retry loop up to a score threshold.
// That conflated two different questions: "does the strategy work in one
// shot" and "does it work with iterative reinforcement." This workflow
// simplifies to a single call per item, with one hybrid instruction that
// allows both recall-search (RAG) and direct grep/file reading from the
// start — no strategy dimension, no retry loop, no session resume. It also
// adds a third tool (GitHub Copilot CLI) alongside Claude Code and agy.
//
// Copilot skill registration is a prerequisite, not part of this script:
// `copilot skill add ~/sources/goriok/my-skills/skills` was run once as
// manual setup (confirmed working via `copilot skill list` — recall-search
// and confidence-analysis both load with zero parse failures). This script
// assumes that registration already exists.
//
// The recall index for cloud-emulator was also just expanded with a new
// high-level source-code overview (topics/cloud-emulator/ai/
// overview-codigo-fonte.md, 132 chunks total after re-ingest) so RAG in
// this round has access to source-code structure, not just the prior
// operational/architecture docs — noted explicitly in the report since it's
// a real difference from earlier rounds' index content.
//
// First run of this script was cancelled mid-flight: asking the generation
// agent for "literal raw stdout" is fine for agy (prints plain text) but
// disastrous for `claude --output-format json` (~150KB event stream) and
// especially `copilot --output-format json` (JSONL with token-by-token
// deltas, ~857KB observed) — the agent burned dozens of extra tool calls
// trying to reconstruct/parse those files instead of just getting the
// answer. Fix: both claude and copilot support `--output-format text`
// (default for copilot, explicit for claude), which prints only the final
// response with no event stream — that's what we actually want to
// validate, not the raw protocol transcript.
//
// Separately, investigating Copilot's per-call token overhead (a plain "hi"
// cost ~21k input tokens) found two fixable causes, both addressed as
// one-time local setup before this script runs, not inside the script:
// (1) 162 unused custom agents under ~/.copilot/agents/ were being loaded
// into the system prompt — deleted; (2) the builtin github-mcp-server (5
// GitHub-remote tools, unused by this experiment) adds ~9.4k tokens of tool
// schemas by default — disabled via --disable-builtin-mcps, included
// explicitly in the copilot command below because subagents run in
// non-interactive shells that don't source ~/.zshrc (where a `copilot`
// alias with this flag was also added for interactive use, but that alias
// doesn't apply here). Combined, this cut Copilot's fixed overhead from
// ~21.3k to ~8.1k input tokens per call — persisting via
// ~/.copilot/mcp-config.json was tried and confirmed NOT to work in CLI
// 1.0.83, hence the explicit flag.
//
// Copilot keeps --model auto rather than a fixed model: the overhead that
// made auto look expensive was the toolset, not model variance, and no
// exact-name equivalent to Haiku 4.5/Gemini Flash was confirmed available.
// The model actually used per call is captured by copilot-track.py
// (resolved_model, from --usage-output-file's currentModel) and recorded
// straight into the ai-token-tracker SQLite store, so the comparison stays
// honest about which model answered even without pinning one — and the
// report can read it from the dashboard instead of a side-channel.
//
// Pivot (same day, later): the interesting comparison isn't "hybrid
// instruction with no declared order" anymore — it's two explicit
// strategies: read the source repo directly with no RAG/context access at
// all, vs. RAG-first (context docs + the source-code overview) falling
// back to direct reading of either repo. Reintroduces a strategy dimension
// (like the retry-loop predecessor had), but with a different split: one
// arm never leaves the source repo, the other can freely use RAG plus
// either repo. Both arms now run with cwd = the cloud-emulator SOURCE repo
// (not dpro-k8s-ctx as before) — recall-search works from any cwd (its
// config file points at dpro-k8s-ctx/topics by absolute path, confirmed),
// so this only affects direct-read fallback paths, which use CONTEXT_DIR
// as an absolute path instead of a relative one.

const CLAUDE_MODEL = 'haiku' // Claude Haiku 4.5, cheapest Claude tier
const AGY_MODEL = 'gemini-3.8-flash-medium' // same model prior rounds used
const COPILOT_MODEL = 'auto' // asymmetric vs. fixed models on the other two sides — documented in the report; actual model used is captured per call via --usage-output-file

const QUESTIONS = [
  'Como o isolamento de rede por tenant funciona no cloud-emulator?',
  'Como o cloud-emulator evita acumular lixo (namespaces/interfaces órfãos) em reconciliações repetidas?',
  'Quais são os pré-requisitos de host para rodar o cloud-emulator, e por que cada um é necessário?',
]

// Both strategies run from the source repo. CONTEXT_DIR is only referenced
// by the contexto-rag-codigo arm's direct-read fallback (absolute path,
// since it's no longer the cwd).
const CWD = '/home/alves.igor/sources/dpro/k8s/cloud-emulator'
const CONTEXT_DIR = '/home/alves.igor/sources/dpro/k8s/dpro-k8s-ctx/topics/cloud-emulator'

const STRATEGIES = ['codigo-direto', 'contexto-rag-codigo']

// Braço A: never leaves the source repo, no RAG, no context repo at all.
function withCodigoDireto(question) {
  return `${question} Responda usando SOMENTE grep/leitura direta dos arquivos deste repositório (código-fonte em src/, mais CLAUDE.md e README.md na raiz). NÃO use a skill recall-search e NÃO leia nenhum arquivo sob ${CONTEXT_DIR}/ — a resposta deve vir exclusivamente do código-fonte e da documentação deste repositório.`
}

// Braço B: RAG first, explicit order, fallback to direct reading of either repo.
function withContextoRagCodigo(question) {
  return `${question} Primeiro use a skill /goriok-skills:recall-search para buscar a resposta (a collection cloud-emulator cobre a documentação de contexto e um overview do código-fonte). Se a busca semântica não trouxer informação suficiente para responder com precisão, complemente com grep/leitura direta — tanto dos arquivos em ${CONTEXT_DIR}/ quanto do código-fonte deste repositório (src/, CLAUDE.md, README.md).`
}

function withStrategy(strategy, question) {
  return strategy === 'codigo-direto' ? withCodigoDireto(question) : withContextoRagCodigo(question)
}

// Same round-prefix mechanism as the predecessor script — new Date() is
// unavailable inside Workflow scripts (would break resume), so the caller
// passes a timestamp via args.roundPrefix when invoking Workflow.
const ROUND_PREFIX = (args && args.roundPrefix) || '202609091000'

const TOOLS = ['claude-code', 'agy', 'copilot']

const items = []
for (let i = 0; i < QUESTIONS.length; i++) {
  const qId = i + 1
  for (const strategy of STRATEGIES) {
    const question = withStrategy(strategy, QUESTIONS[i])
    for (const tool of TOOLS) {
      const label = `${ROUND_PREFIX}${qId}${strategy.replace(/-/g, '')}${tool.replace(/-/g, '')}`
      items.push({
        tool,
        strategy,
        questionId: qId,
        label,
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

const GEN_SCHEMA = {
  type: 'object',
  properties: {
    rawOutput: { type: 'string', description: 'The final answer text printed by the command, verbatim, not summarized' },
  },
  required: ['rawOutput'],
}

function generatePrompt(item) {
  const escaped = item.question.replace(/'/g, "'\\''")
  let cmd
  let extraNote = ''
  if (item.tool === 'claude-code') {
    // --output-format text prints only the final response, no event stream.
    cmd = `cd ${CWD} && claude -p -n '${item.label}' --model ${CLAUDE_MODEL} '${escaped}' --output-format text`
  } else if (item.tool === 'agy') {
    cmd = `cd ${CWD} && bash /home/alves.igor/sources/goriok/ai-token-tracker/bin/agydelegate --model ${AGY_MODEL} --task '${item.label}' '${escaped}'`
  } else {
    // copilot-track.py wraps the copilot binary (--allow-all-tools and
    // --disable-builtin-mcps baked in, same overhead-reduction rationale as
    // before) AND records the call as a TaskCall(source="copilot", ...)
    // straight into the ai-token-tracker SQLite store, so this round's
    // Copilot usage shows up on the dashboard without a manual import step.
    // It prints the response as its only stdout — that's rawOutput.
    cmd = `cd ${CWD} && python3 /home/alves.igor/sources/goriok/ai-token-tracker/scripts/copilot-track.py --model ${COPILOT_MODEL} --task '${item.label}' '${escaped}'`
  }
  return `Rode exatamente este comando via Bash, com timeout de pelo menos 180000ms (o comando pode levar 30-90s para retornar).${extraNote} O campo rawOutput deve conter EXATAMENTE o texto final impresso pelo comando (a resposta, não um stream de eventos), copiado literalmente — nunca um resumo do que você fez, nunca uma narração tipo "o comando executou X", nunca um cabeçalho inventado como "=== COMANDO EXECUTADO ===", nunca só o exit code. Se o comando falhar ou não produzir texto útil, rode-o de novo (até 2 vezes) antes de desistir — não retorne uma explicação no lugar da saída. Comando: ${cmd}`
}

function validatePrompt(rawOutput) {
  return `Use a skill /goriok-skills:confidence-analysis para analisar a seguinte resposta técnica, avaliando cada alegação factual segundo o critério da skill (fonte, hierarquia, label de confiança). Depois de rodar a análise, produza o resultado estruturado pedido no schema — não invente um critério próprio, use o vocabulário e a escala exatos da skill.\n\n---\nRESPOSTA A AVALIAR:\n${rawOutput}`
}

// Sanity gate before spending a validation call: a generation agent can
// stray from "run the command, return its raw stdout" into narrating what
// it did instead. Passing that to confidence-analysis produces a
// technically correct but useless verdict ("this isn't a real answer"
// scored 10/10 as a claim) that would misleadingly read as a high-quality
// result. No retry here (this workflow has no loop) — a failed check just
// means the item's finalValidation stays null and reachedThreshold false,
// which shows up plainly in the report as a generation failure, not a
// quality result.
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

const SCORE_THRESHOLD = 8 // reporting metric only — no loop reads this

async function runItem(item) {
  const gen = await agent(generatePrompt(item), {
    label: `gen:${item.label}`,
    phase: 'Generate',
    schema: GEN_SCHEMA,
  })

  const rawOutput = gen ? gen.rawOutput : null
  if (!rawOutput) {
    log(`${item.label}: generation failed`)
    return { ...item, rawOutput: null, validation: null, reachedThreshold: false, score: null }
  }

  if (!looksLikeRealAnswer(rawOutput)) {
    log(`${item.label}: rawOutput doesn't look like a real answer (${rawOutput.length} chars), skipping validation`)
    return { ...item, rawOutput, validation: null, reachedThreshold: false, score: null }
  }

  const validation = await agent(validatePrompt(rawOutput), {
    label: `val:${item.label}`,
    phase: 'Validate',
    schema: VALIDATION_SCHEMA,
  })

  const score = validation ? validation.overallScore : null
  log(`${item.label}: score=${score ?? 'n/a'}`)

  return {
    ...item,
    rawOutput,
    validation,
    score,
    reachedThreshold: score !== null && score >= SCORE_THRESHOLD,
  }
}

const results = await parallel(items.map(item => () => runItem(item)))

return results.filter(Boolean)
