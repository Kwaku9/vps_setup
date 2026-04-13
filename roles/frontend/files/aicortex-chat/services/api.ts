/**
 * Open WebUI API service layer for AICORTEX Chat.
 *
 * Connects to the Open WebUI instance at chat.aicortex.cloud.
 * Supports both API key and JWT token authentication.
 */

const DEFAULT_BASE_URL = 'https://chat.aicortex.cloud';

let _baseUrl = DEFAULT_BASE_URL;
let _token: string | null = null;

/** Configure the API base URL. */
export function setBaseUrl(url: string) {
  _baseUrl = url.replace(/\/+$/, '');
}

/** Set the authentication token (API key or JWT). */
export function setToken(token: string | null) {
  _token = token;
}

/** Get the current token. */
export function getToken(): string | null {
  return _token;
}

function headers(extra?: Record<string, string>): Record<string, string> {
  const h: Record<string, string> = {
    'Content-Type': 'application/json',
    ...extra,
  };
  if (_token) {
    h['Authorization'] = `Bearer ${_token}`;
  }
  return h;
}

async function request<T>(
  path: string,
  options?: RequestInit,
): Promise<T> {
  const res = await fetch(`${_baseUrl}${path}`, {
    ...options,
    headers: headers(options?.headers as Record<string, string>),
  });
  if (!res.ok) {
    const body = await res.text().catch(() => '');
    throw new ApiError(res.status, body || res.statusText);
  }
  return res.json();
}

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
    this.name = 'ApiError';
  }
}

// ── Auth ────────────────────────────────────────────────────────

export interface AuthUser {
  id: string;
  email: string;
  name: string;
  role: string;
  profile_image_url?: string;
}

/** Sign in with email/password and receive a JWT. */
export async function signIn(
  email: string,
  password: string,
): Promise<{ token: string }> {
  return request('/api/v1/auths/signin', {
    method: 'POST',
    body: JSON.stringify({ email, password }),
  });
}

/** Get the currently authenticated user's profile. */
export async function getUser(): Promise<AuthUser> {
  return request('/api/v1/auths/');
}

// ── Models ──────────────────────────────────────────────────────

export interface Model {
  id: string;
  name: string;
  object?: string;
  owned_by?: string;
  info?: {
    description?: string;
    meta?: {
      profile_image_url?: string;
      capabilities?: Record<string, boolean>;
    };
  };
}

/** List all available models. */
export async function getModels(): Promise<Model[]> {
  const data = await request<{ data: Model[] }>('/api/models');
  return data.data ?? [];
}

// ── Conversations (Chats) ───────────────────────────────────────

export interface ChatMeta {
  id: string;
  title: string;
  updated_at: number;
  created_at: number;
}

/** List all conversations. */
export async function getChats(): Promise<ChatMeta[]> {
  return request('/api/v1/chats/');
}

/** Get a single conversation by ID, including messages. */
export async function getChat(id: string): Promise<any> {
  return request(`/api/v1/chats/${id}`);
}

/** Create a new conversation. */
export async function createChat(chat: {
  title?: string;
}): Promise<any> {
  return request('/api/v1/chats/new', {
    method: 'POST',
    body: JSON.stringify({ chat: { title: chat.title ?? 'New Chat' } }),
  });
}

/** Delete a conversation. */
export async function deleteChat(id: string): Promise<void> {
  await request(`/api/v1/chats/${id}`, { method: 'DELETE' });
}

// ── Chat Completions ────────────────────────────────────────────

export interface ChatMessage {
  role: 'user' | 'assistant' | 'system';
  content: string;
}

export interface ChatCompletionResponse {
  id: string;
  choices: Array<{
    message: ChatMessage;
    finish_reason: string;
  }>;
  model: string;
  usage?: {
    prompt_tokens: number;
    completion_tokens: number;
    total_tokens: number;
  };
}

/** Send a non-streaming chat completion request. */
export async function chatCompletion(
  model: string,
  messages: ChatMessage[],
): Promise<ChatCompletionResponse> {
  return request('/api/chat/completions', {
    method: 'POST',
    body: JSON.stringify({ model, messages, stream: false }),
  });
}

/**
 * Stream a chat completion via Server-Sent Events.
 *
 * Uses XMLHttpRequest for React Native compatibility (fetch doesn't
 * support ReadableStream in RN). Falls back to non-streaming if needed.
 *
 * Calls `onChunk` with each content delta as it arrives.
 * Returns the full accumulated response text when done.
 */
export async function chatCompletionStream(
  model: string,
  messages: ChatMessage[],
  onChunk: (delta: string) => void,
  signal?: AbortSignal,
): Promise<string> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open('POST', `${_baseUrl}/api/chat/completions`);
    xhr.setRequestHeader('Content-Type', 'application/json');
    if (_token) {
      xhr.setRequestHeader('Authorization', `Bearer ${_token}`);
    }

    let accumulated = '';
    let lastProcessed = 0;

    xhr.onprogress = () => {
      const newText = xhr.responseText.substring(lastProcessed);
      lastProcessed = xhr.responseText.length;

      const lines = newText.split('\n');
      for (const line of lines) {
        const trimmed = line.trim();
        if (!trimmed.startsWith('data: ')) continue;
        const data = trimmed.slice(6);
        if (data === '[DONE]') continue;

        try {
          const parsed = JSON.parse(data);
          const delta = parsed.choices?.[0]?.delta?.content;
          if (delta) {
            accumulated += delta;
            onChunk(delta);
          }
        } catch {
          // Skip malformed SSE lines
        }
      }
    };

    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        // Process any remaining data
        const remaining = xhr.responseText.substring(lastProcessed);
        const lines = remaining.split('\n');
        for (const line of lines) {
          const trimmed = line.trim();
          if (!trimmed.startsWith('data: ')) continue;
          const data = trimmed.slice(6);
          if (data === '[DONE]') continue;
          try {
            const parsed = JSON.parse(data);
            const delta = parsed.choices?.[0]?.delta?.content;
            if (delta) {
              accumulated += delta;
              onChunk(delta);
            }
          } catch {}
        }
        resolve(accumulated);
      } else {
        reject(new ApiError(xhr.status, xhr.responseText || xhr.statusText));
      }
    };

    xhr.onerror = () => {
      reject(new ApiError(0, 'Network error'));
    };

    xhr.onabort = () => {
      const err = new Error('Aborted');
      err.name = 'AbortError';
      reject(err);
    };

    // Wire up abort signal
    if (signal) {
      signal.addEventListener('abort', () => xhr.abort());
    }

    xhr.send(JSON.stringify({ model, messages, stream: true }));
  });
}

// ── Custom Models (Agents) CRUD ────────────────────────────────

import type {
  AgentModel,
  ModelForm,
  FolderForm,
  FolderModel,
} from '@/constants/types';

/** List custom models (agents). Returns only models with a base_model_id. */
export async function listAgentModels(): Promise<{
  items: AgentModel[];
  total: number;
}> {
  const data = await request<{ items: AgentModel[]; total: number }>(
    '/api/v1/models/list',
  );
  // Keep only custom models (base_model_id != null)
  const custom = (data.items ?? []).filter(
    (m) => m.base_model_id !== null,
  );
  return { items: custom, total: custom.length };
}

/** Get a single agent model by ID. */
export async function getAgentModel(id: string): Promise<AgentModel> {
  return request(`/api/v1/models/model?id=${encodeURIComponent(id)}`);
}

/** Create a new agent model on the server. */
export async function createAgentModel(
  form: ModelForm,
): Promise<AgentModel> {
  return request('/api/v1/models/create', {
    method: 'POST',
    body: JSON.stringify(form),
  });
}

/** Update an existing agent model. */
export async function updateAgentModel(
  form: ModelForm,
): Promise<AgentModel> {
  return request('/api/v1/models/model/update', {
    method: 'POST',
    body: JSON.stringify(form),
  });
}

/** Delete an agent model. */
export async function deleteAgentModel(id: string): Promise<void> {
  await request('/api/v1/models/model/delete', {
    method: 'POST',
    body: JSON.stringify({ id }),
  });
}

/** Toggle an agent model's active status. */
export async function toggleAgentModel(
  id: string,
): Promise<AgentModel> {
  return request(`/api/v1/models/model/toggle?id=${encodeURIComponent(id)}`, {
    method: 'POST',
  });
}

// ── Folders (Projects) CRUD ────────────────────────────────────

/** List all folders for the authenticated user. */
export async function listFolders(): Promise<FolderModel[]> {
  return request('/api/v1/folders/');
}

/** Create a new folder. */
export async function createFolder(
  form: FolderForm,
): Promise<FolderModel> {
  return request('/api/v1/folders/', {
    method: 'POST',
    body: JSON.stringify(form),
  });
}

/** Get a single folder by ID. */
export async function getFolder(id: string): Promise<FolderModel> {
  return request(`/api/v1/folders/${id}`);
}

/** Update a folder's name, data, or meta. */
export async function updateFolder(
  id: string,
  form: Partial<FolderForm>,
): Promise<FolderModel> {
  return request(`/api/v1/folders/${id}/update`, {
    method: 'POST',
    body: JSON.stringify(form),
  });
}

/** Delete a folder and optionally its contents. */
export async function deleteFolder(id: string): Promise<void> {
  await request(`/api/v1/folders/${id}`, { method: 'DELETE' });
}

/** Move a chat into a folder (or remove from folder with null). */
export async function moveChatToFolder(
  chatId: string,
  folderId: string | null,
): Promise<void> {
  await request(`/api/v1/chats/${chatId}/folder`, {
    method: 'POST',
    body: JSON.stringify({ folder_id: folderId }),
  });
}

/** Get chats in a folder (paginated list). */
export async function getChatsByFolder(
  folderId: string,
): Promise<ChatMeta[]> {
  return request(`/api/v1/chats/folder/${folderId}/list`);
}

// ── Files ───────────────────────────────────────────────────────

/** Upload a file to Open WebUI. */
export async function uploadFile(
  uri: string,
  filename: string,
  mimeType: string,
): Promise<any> {
  const formData = new FormData();
  formData.append('file', {
    uri,
    name: filename,
    type: mimeType,
  } as any);

  const res = await fetch(`${_baseUrl}/api/v1/files/`, {
    method: 'POST',
    headers: {
      ..._token ? { Authorization: `Bearer ${_token}` } : {},
    },
    body: formData,
  });

  if (!res.ok) {
    throw new ApiError(res.status, await res.text());
  }
  return res.json();
}

// ── Voice / WebSocket ───────────────────────────────────────

// Voice WebSocket connects to LiteLLM via Traefik route with scoped key
const VOICE_WS_BASE = 'wss://chat.aicortex.cloud/vertex_ai/live';
const VOICE_WS_PARAMS = 'vertex_project=aicortexi-web-search&vertex_location=us-central1';

let _voiceKey: string | null = null;

/** WebSocket URL for voice sessions (Traefik routes to LiteLLM). */
export function getVoiceWebSocketUrl(): string {
  return `${VOICE_WS_BASE}?${VOICE_WS_PARAMS}`;
}

/** Set the scoped voice session key (LiteLLM virtual key for Gemini Live only). */
export function setVoiceKey(key: string | null) {
  _voiceKey = key;
}

/** Get the voice session key. */
export function getVoiceKey(): string | null {
  return _voiceKey;
}
