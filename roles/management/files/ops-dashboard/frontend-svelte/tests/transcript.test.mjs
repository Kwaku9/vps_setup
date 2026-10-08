import assert from 'node:assert/strict';
import test from 'node:test';
import { mergeMessages, transcriptEntries } from '../src/lib/transcript.ts';

const message = (uuid, content_json, content_text = null, role = 'assistant', sequence_num = 1) =>
  ({ uuid, content_json, content_text, role, type: role, sequence_num, timestamp: null });

test('Claude prose and tool activity keep their original order and full contents', () => {
  const text = 'Complete response '.repeat(300);
  const entries = transcriptEntries([
    message('a', [
      { type: 'text', text },
      { type: 'tool_use', id: 'one', name: 'Bash', input: { command: 'printf hello' } },
      { type: 'text', text: 'Checking the result.' },
    ], text),
    message('b', [{ type: 'tool_result', tool_use_id: 'one', content: [{ type: 'text', text: 'hello' }] }], null, 'user'),
  ]);
  assert.deepEqual(entries.map((entry) => entry.kind), ['message', 'call', 'message', 'result']);
  assert.equal(entries[0].text, text);
  assert.equal(entries[1].preview, 'printf hello');
  assert.equal(entries[3].name, 'Bash');
  assert.equal(entries[3].text, 'hello');
});

test('interleaved Codex outputs match the right call ID, including JSON strings', () => {
  const entries = transcriptEntries([
    message('a', JSON.stringify([{ type: 'function_call', call_id: 'one', name: 'exec_command', arguments: '{"cmd":"pwd"}' }])),
    message('b', [{ type: 'custom_tool_call', call_id: 'two', name: 'apply_patch', input: '*** Begin Patch\n...' }]),
    message('c', [{ type: 'function_call_output', call_id: 'one', output: '{"output":"/workspace","exit_code":0}' }], null, 'user'),
    message('d', [{ type: 'custom_tool_call_output', call_id: 'two', output: 'Patch rejected', success: false }], null, 'user'),
  ]);
  assert.equal(entries[0].preview, 'pwd');
  assert.equal(entries[2].name, 'exec_command');
  assert.equal(entries[2].text, '/workspace');
  assert.equal(entries[3].name, 'apply_patch');
  assert.equal(entries[3].error, true);
});

test('older rows and unknown content retain text, context is collapsible', () => {
  const entries = transcriptEntries([
    message('a', null, '## Original response'),
    message('b', 'invalid JSON', 'Fallback response'),
    message('c', [{ type: 'unknown' }], 'Still readable'),
    message('d', [{ type: 'input_text', text: '<environment_context>setup</environment_context>' }], null, 'user'),
    message('e', [{ type: 'output_text', text: 'Codex response' }]),
    message('f', [{ type: 'thinking', thinking: 'Working it out' }]),
  ]);
  assert.deepEqual(entries.map((entry) => entry.kind), ['message', 'message', 'message', 'context', 'message', 'thinking']);
  assert.equal(entries[2].text, 'Still readable');
});

test('refreshes deduplicate, preserve history, and sort by sequence', () => {
  const previous = Array.from({ length: 500 }, (_, i) => message(`m${i}`, null, `row ${i}`, 'user', i));
  const rows = mergeMessages(previous, [message('m499', null, 'Updated', 'user', 499), message('m501', null, 'Last', 'user', 501), message('m500', null, 'Next', 'user', 500)]);
  assert.equal(rows.length, 502);
  assert.equal(rows[0].content_text, 'row 0');
  assert.equal(rows[499].content_text, 'Updated');
  assert.equal(rows[501].content_text, 'Last');
});

test('local CLI wrappers become context, slash commands, and readable output', () => {
  const entries = transcriptEntries([
    message('caveat', null, '<local-command-caveat>The command was run directly.</local-command-caveat>', 'user'),
    message('command', null, '<command-name>/model</command-name>\n<command-message>model</command-message>\n<command-args>haiku</command-args>', 'user'),
    message('stdout', null, '<local-command-stdout>Set model to **Haiku 4.5**.</local-command-stdout>', 'user'),
    message('error', null, '<local-command-stderr>Command failed.</local-command-stderr>', 'user'),
    message('prompt', null, 'I am testing, what model are you running?', 'user'),
  ]);
  assert.deepEqual(entries.map((entry) => entry.kind), ['context', 'command', 'output', 'output', 'message']);
  assert.equal(entries[0].text, 'The command was run directly.');
  assert.equal(entries[1].preview, '/model haiku');
  assert.equal(entries[2].text, 'Set model to **Haiku 4.5**.');
  assert.equal(entries[3].error, true);
});

test('hook batches with restarted sequence numbers remain chronological', () => {
  const first = { ...message('first', null, 'First', 'user', 1), cursor: 101, timestamp: '2026-10-08T08:52:00Z' };
  const next = { ...message('next', null, 'Next', 'assistant', 1), cursor: 102, timestamp: '2026-10-08T08:53:00Z' };
  const backfill = { ...message('older', null, 'Earlier', 'user', 2), cursor: 103, timestamp: '2026-10-08T08:51:00Z' };
  assert.deepEqual(mergeMessages([first], [next, backfill]).map((row) => row.uuid), ['older', 'first', 'next']);
});
