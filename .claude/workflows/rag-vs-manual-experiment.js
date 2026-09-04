export const meta = {
  name: 'rag-vs-manual-experiment',
  description: 'Compare token usage: recall-search skill vs. manual grep, 3 questions, interleaved order',
  phases: [{ title: 'Interleaved runs' }],
}

// Design: interleave A/B (A1,B1,A2,B2,A3,B3) instead of running one group
// fully before the other — a first attempt that ran A1-A2-A3 then B1-B2-B3
// showed token usage falling monotonically across ALL 6 runs regardless of
// group, meaning "position in the sequence" was confounded with "strategy".
// Interleaving spreads any such sequence effect evenly across both groups.
//
// A plain sequential for-loop (not pipeline/parallel) is what guarantees
// strict ordering here — pipeline() and parallel() both allow concurrent
// execution, which would destroy the ordering this experiment depends on.

const QUESTIONS = [
  'Como o isolamento de rede por tenant funciona no cloud-emulator?',
  'Como o cloud-emulator evita acumular lixo (namespaces/interfaces órfãos) em reconciliações repetidas?',
  'Quais são os pré-requisitos de host para rodar o cloud-emulator, e por que cada um é necessário?',
]

const CWD_NOTE = 'Trabalhe considerando o diretório topics/cloud-emulator/ dentro do repositório de contexto dpro-k8s-ctx (caminho completo: /home/alves.igor/sources/dpro/k8s/dpro-k8s-ctx/topics/cloud-emulator/).'

function withRecall(question) {
  return `${question} Use a skill /goriok-skills:recall-search para responder. ${CWD_NOTE}`
}

function withoutRecall(question) {
  return `${question} Responda usando apenas grep/leitura direta dos arquivos em topics/cloud-emulator/, sem usar a skill recall-search. ${CWD_NOTE}`
}

phase('Interleaved runs')

const runs = []
for (let i = 0; i < QUESTIONS.length; i++) {
  runs.push({ label: `A${i + 1}`, prompt: withRecall(QUESTIONS[i]) })
  runs.push({ label: `B${i + 1}`, prompt: withoutRecall(QUESTIONS[i]) })
}

const results = []
for (const run of runs) {
  log(`Running ${run.label}...`)
  const answer = await agent(run.prompt, { label: run.label, phase: 'Interleaved runs' })
  results.push({ label: run.label, answer })
}

return results
