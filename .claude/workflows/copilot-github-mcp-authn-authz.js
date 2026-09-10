export const meta = {
  name: 'copilot-github-mcp-authn-authz',
  description: 'Copilot CLI com vs. sem o built-in github-mcp-server, mesmas perguntas sobre authn/authz do mke-api',
  phases: [{ title: 'Generate' }, { title: 'Validate' }],
}

// Reuses rag-vs-manual-single-call.js's Generate -> Validate (via
// confidence-analysis) core, but the axis that varies here is neither tool
// nor RAG-vs-direct-read strategy — it's whether the copilot CLI's only
// built-in MCP server (github-mcp-server, confirmed via `copilot --help`:
// "Disable all built-in MCP servers (currently: github-mcp-server)") is
// enabled or disabled for the call. rag-vs-manual-single-call.js has no
// hook for this (aitokens-exporter track always disables it, per
// exporter/internal/adapters/tracker/copilot.go's disableBuiltinMCPs
// parameter default), so this is a separate script rather than a
// parametrization of the existing one — per experiment-design's guidance to
// adapt only when the existing Generate/Validate shape still fits, which it
// does here.
//
// Content: the 3 authn/authz/OIDC questions raised while researching the
// real OIDC-integration task for mke-api (see docs/experiments/ for the
// research this drew from). Tool fixed to copilot (the only tool this flag
// applies to); reading strategy fixed to código-direto (no recall-search),
// so the only thing that varies between the two arms is the flag itself —
// mixing in a RAG arm here would confound the flag's effect with RAG's.

const COPILOT_MODEL = 'auto'

const QUESTIONS = (args && args.questions) || [
  'Como o mke-api trata a identidade do usuário que chama a API pública hoje — o token é validado, e como isso se relaciona com a autenticação que o mke-api usa para agir na MGC em nome do tenant?',
  'Quais scopes o mke-api declara no contrato da API pública, e são de fato impostos em runtime nas rotas?',
  'Quais componentes hoje recebem ServiceAccounts e roles RBAC dentro dos clusters Kubernetes provisionados pelo mke-api, e qual grupo tem admin completo por padrão?',
]

const CWD = (args && args.cwd) || '/home/alves.igor/sources/dpro/k8s/mke-api'

function withCodigoDireto(question) {
  return `${question} Responda usando SOMENTE grep/leitura direta dos arquivos deste repositório (código-fonte, mais CLAUDE.md e README.md na raiz se existirem). NÃO use a skill recall-search — a resposta deve vir exclusivamente do código-fonte e da documentação deste repositório.`
}

// Same <tool>-<contexto>-<date> session_name shape experiment-design
// prescribes, with the varying axis (github-mcp on/off) standing in for
// "estrategia" since that's what this experiment actually compares.
const ROUND_PREFIX = (args && args.roundPrefix) || '20260910-1500'

const GITHUB_MCP_STATES = [
  { id: 'github-mcp-on', disableBuiltinMCPs: false },
  { id: 'github-mcp-off', disableBuiltinMCPs: true },
]

const items = []
for (let i = 0; i < QUESTIONS.length; i++) {
  const qId = i + 1
  const question = withCodigoDireto(QUESTIONS[i])
  for (const state of GITHUB_MCP_STATES) {
    const label = `copilot-${state.id}-${ROUND_PREFIX}`
    items.push({
      tool: 'copilot',
      githubMcpState: state.id,
      disableBuiltinMCPs: state.disableBuiltinMCPs,
      questionId: qId,
      label,
      question,
    })
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
  // aitokens-exporter track --enable-builtin-mcps keeps github-mcp-server
  // enabled (the flag's absence is the default: disabled) — this is the
  // only line that differs between the two arms of this experiment.
  //
  // Uses the prebuilt binary (exporter/aitokens-exporter) rather than
  // rag-vs-manual-single-call.js's `cd exporter/ && go run ./cmd/...`
  // pattern: that pattern runs the copilot subprocess with cwd = the
  // exporter's own directory (exec.Command inherits the Go process's cwd,
  // confirmed in internal/adapters/tracker/copilot.go — no cmd.Dir is set),
  // never the target repo, since CWD in that script is only ever
  // interpolated into the prompt text, not the shell command's cd. Since
  // this experiment's whole point is copilot reading mke-api's own source,
  // `cd ${CWD} && <absolute path to the binary>` is required so the
  // subprocess actually runs from CWD.
  const mcpFlag = item.disableBuiltinMCPs ? '' : ' --enable-builtin-mcps'
  const cmd = `cd ${CWD} && /home/alves.igor/sources/goriok/ai-token-tracker/exporter/aitokens-exporter track --model ${COPILOT_MODEL} --task '${item.label}'${mcpFlag} '${escaped}'`
  return `Rode exatamente este comando via Bash, com timeout de pelo menos 180000ms (o comando pode levar 30-90s para retornar). O campo rawOutput deve conter EXATAMENTE o texto final impresso pelo comando (a resposta, não um stream de eventos), copiado literalmente — nunca um resumo do que você fez, nunca uma narração tipo "o comando executou X", nunca um cabeçalho inventado como "=== COMANDO EXECUTADO ===", nunca só o exit code. Se o comando falhar ou não produzir texto útil, rode-o de novo (até 2 vezes) antes de desistir — não retorne uma explicação no lugar da saída. Comando: ${cmd}`
}

function validatePrompt(rawOutput) {
  return `Use a skill /goriok-skills:confidence-analysis para analisar a seguinte resposta técnica, avaliando cada alegação factual segundo o critério da skill (fonte, hierarquia, label de confiança). Depois de rodar a análise, produza o resultado estruturado pedido no schema — não invente um critério próprio, use o vocabulário e a escala exatos da skill.\n\n---\nRESPOSTA A AVALIAR:\n${rawOutput}`
}

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
