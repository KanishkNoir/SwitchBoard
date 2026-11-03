// Configuration failures must not prevent registration of the action gate.
// Synthetic credentials only; no HTTP request or downstream tool is executed.
import assert from 'node:assert/strict'
import { mkdtemp, rm, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { SwitchboardGate } from '../.opencode/plugins/switchboard-gate.js'

const variables = ['SWITCHBOARD_AGENT_KEY', 'SWITCHBOARD_AGENT_KEY_FILE', 'SWITCHBOARD_REMOTE_URL']
const previous = Object.fromEntries(variables.map(name => [name, process.env[name]]))
const scratch = await mkdtemp(join(tmpdir(), 'switchboard-opencode-test-'))
const originalFetch = globalThis.fetch
let networkCalls = 0
globalThis.fetch = async () => { networkCalls++; throw new Error('No network allowed') }
try {
  for (const scenario of ['missing-file', 'invalid-url']) {
    delete process.env.SWITCHBOARD_AGENT_KEY
    process.env.SWITCHBOARD_AGENT_KEY_FILE = join(scratch, scenario + '.key')
    process.env.SWITCHBOARD_REMOTE_URL = scenario === 'invalid-url' ? 'invalid URL' : 'https://test.invalid'
    if (scenario === 'invalid-url') {
      await writeFile(process.env.SWITCHBOARD_AGENT_KEY_FILE, 'synthetic-test-credential')
    }
    const gate = await SwitchboardGate({ directory: scratch })
    assert.equal(typeof gate['tool.execute.before'], 'function')
    await gate['tool.execute.before']({ tool: 'read' }, { args: {} })
    await assert.rejects(gate['tool.execute.before']({ tool: 'write' }, { args: {} }),
      /not configured; the action was blocked/)
    console.log(scenario + ': gate registered, read allowed, action blocked')
  }
  assert.equal(networkCalls, 0)
} finally {
  globalThis.fetch = originalFetch
  for (const name of variables) {
    if (previous[name] === undefined) delete process.env[name]
    else process.env[name] = previous[name]
  }
  await rm(scratch, { recursive: true, force: true })
}
