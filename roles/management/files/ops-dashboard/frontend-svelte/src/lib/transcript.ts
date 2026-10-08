import type { TranscriptMessage } from './types';

export interface TranscriptEntry {
  id: string;
  kind: 'message' | 'command' | 'output' | 'call' | 'result' | 'thinking' | 'context';
  role: string;
  timestamp: string | null;
  text: string;
  name: string;
  preview: string;
  error: boolean;
}

type Block = Record<string, unknown>;
const record = (value: unknown): value is Block => !!value && typeof value === 'object' && !Array.isArray(value);
const calls = new Set(['tool_use', 'function_call', 'custom_tool_call']);
const results = new Set(['tool_result', 'function_call_output', 'custom_tool_call_output']);

function decode(value: unknown): unknown {
  if (typeof value !== 'string') return value;
  try { return JSON.parse(value); } catch { return value; }
}

function blocks(message: TranscriptMessage): Block[] {
  const value = decode(message.content_json);
  return Array.isArray(value) ? value.filter(record) : record(value) ? [value] : [];
}

export function plain(value: unknown): string {
  if (value == null) return '';
  if (typeof value === 'string') return value;
  if (Array.isArray(value)) return value.map(plain).filter(Boolean).join('\n');
  if (record(value)) {
    if (typeof value.text === 'string') return value.text;
    if ('output' in value) return plain(value.output);
    if ('content' in value) return plain(value.content);
    if (value.type === 'image' || value.type === 'image_url') return '[Image attachment]';
  }
  return JSON.stringify(value, null, 2);
}

export function toolPreview(input: unknown): string {
  const value = decode(input);
  if (record(value)) {
    for (const key of ['command', 'cmd', 'file_path', 'path', 'pattern', 'query', 'description', 'prompt']) {
      if (value[key] != null) return plain(value[key]).split('\n')[0];
    }
  }
  return plain(value).split('\n')[0];
}

function isContext(text: string) {
  return /^(<permissions instructions>|<environment_context>|<multi_agent_mode>|<user_instructions>|You are `\/root`)/.test(text.trim());
}

/** Preserve block order and match outputs by call ID, including interleaved tools. */
export function transcriptEntries(messages: TranscriptMessage[]): TranscriptEntry[] {
  const names = new Map<string, string>();
  for (const message of messages) {
    for (const block of blocks(message)) {
      if (calls.has(String(block.type))) {
        names.set(String(block.id ?? block.call_id), String(block.name ?? 'Tool'));
      }
    }
  }
  return messages.flatMap((message) => {
    const entries: TranscriptEntry[] = [];
    const add = (kind: TranscriptEntry['kind'], text: string, name = '', preview = '', error = false) => {
      entries.push({ id: `${message.uuid}:${entries.length}`, kind, role: message.role,
        timestamp: message.timestamp, text, name, preview, error });
    };
    const addText = (text: string) => {
      if (!text.trim()) return;
      const tag = (name: string) => text.match(new RegExp(`<${name}>([\\s\\S]*?)<\/${name}>`))?.[1];
      // Claude Code records local slash commands as XML-like user messages.
      // Present the command and its output, rather than their transport tags.
      const command = tag('command-name');
      const output = tag('local-command-stdout') ?? tag('local-command-stderr');
      const caveat = tag('local-command-caveat');
      if (command != null) {
        const line = [command.trim(), tag('command-args')?.trim()].filter(Boolean).join(' ');
        add('command', line, 'CLI command', line);
      } else if (output != null) {
        add('output', output.trim(), 'CLI output', '', tag('local-command-stderr') != null);
      } else if (caveat != null) {
        add('context', caveat.trim(), 'CLI context');
      } else {
        add(isContext(text) ? 'context' : 'message', text);
      }
    };
    let hasText = false;
    for (const block of blocks(message)) {
      const type = String(block.type);
      if (['text', 'input_text', 'output_text'].includes(type) && typeof block.text === 'string') {
        hasText = true;
        addText(block.text);
      } else if (calls.has(type)) {
        const input = decode(type === 'function_call' ? block.arguments : block.input);
        add('call', plain(input), String(block.name ?? 'Tool'), toolPreview(input));
      } else if (results.has(type)) {
        const output = type === 'tool_result' ? block.content : block.output;
        const value = decode(output);
        const text = plain(value);
        const name = names.get(String(block.tool_use_id ?? block.call_id)) ?? 'Tool';
        add('result', text || 'No text output.', name, text.split('\n').find((s) => s.trim()) ?? '',
          block.is_error === true || block.success === false);
      } else if (type === 'thinking' && typeof block.thinking === 'string') {
        add('thinking', block.thinking, 'Thinking');
      }
    }
    // Older rows have only content_text; unknown block shapes still retain their prose.
    if (!hasText && !entries.length && message.content_text?.trim()) {
      addText(message.content_text);
    }
    return entries;
  });
}

export function mergeMessages(previous: TranscriptMessage[], batch: TranscriptMessage[]) {
  const rows = new Map(previous.map((message) => [message.uuid, message]));
  for (const message of batch) rows.set(message.uuid, message);
  return [...rows.values()].sort((a, b) => {
    const timeA = Date.parse(a.timestamp ?? ''), timeB = Date.parse(b.timestamp ?? '');
    if (Number.isFinite(timeA) && Number.isFinite(timeB) && timeA !== timeB) return timeA - timeB;
    return (a.cursor ?? a.sequence_num) - (b.cursor ?? b.sequence_num);
  });
}
