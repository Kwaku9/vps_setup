/**
 * Phase 1: Per-conversation extraction.
 *
 * Sends batches of conversations to the LLM with the Chat Conversation
 * Analyzer prompt. Extracts structured metadata (domain, project_signal,
 * intent, tools, agent_signals, etc.) and caches results in AsyncStorage.
 */

import type { ConversationExtraction } from '@/constants/types';
import { chatCompletion, getChat, getChats, type ChatMessage } from '@/services/api';
import { getItem, setItem } from '@/services/storage';

const CACHE_KEY = '@aicortex/pipeline_extractions';

// Cost-effective model for extraction (high volume, structured output)
const EXTRACTION_MODEL = 'claude-haiku-4-5';

const EXTRACTION_SYSTEM_PROMPT = `You are a conversation analyst for AiCortex, an AI agent platform. Your job is to analyze chat conversations and extract structured metadata that will be used to organize the user's work into projects and recommend AI agents.

You are NOT summarizing the conversation. You are classifying it and extracting signals.

For each conversation provided, output a JSON object with the following fields:

{
  "conversation_id": "string — the original conversation ID",
  "title": "string — a clean, descriptive title (rewrite vague titles like 'New Chat' into something meaningful)",
  "domain": "string — ONE from: business_strategy, marketing, sales, finance, coding, devops, data_analysis, writing, research, design, personal_productivity, health_wellness, education, legal, hiring_hr, customer_support, project_management, creative, cooking, travel, home_management, career, relationships, other",
  "subdomain": "string — more specific category within the domain",
  "project_signal": "string — your best inference of what ongoing project this relates to. Be specific. Write 'standalone' if it's a one-off question.",
  "intent": "string — ONE from: build_something, fix_something, learn_something, write_something, analyze_something, plan_something, decide_something, automate_something, brainstorm, get_advice, other",
  "complexity": "string — low, medium, or high",
  "tools_mentioned": ["string array — tools, platforms, technologies mentioned"],
  "skills_demonstrated": ["string array — skills or knowledge areas the user showed"],
  "recurring_theme": "boolean — does this seem like part of an ongoing effort?",
  "emotional_valence": "string — neutral, frustrated, excited, confused, urgent, or exploratory",
  "delegation_potential": "string — none, partial, or high",
  "agent_signals": ["string array — what types of AI agents would be useful? e.g. code_assistant_agent, writing_partner_agent"],
  "key_entities": ["string array — important proper nouns mentioned"],
  "user_role_signals": ["string array — clues about the user's role"]
}

RULES:
- Be aggressive about inferring project_signal. Most medium/high complexity conversations belong to a project.
- For agent_signals, think about what agent would PREVENT the user from needing this conversation in the future.
- If a conversation covers multiple topics, extract the DOMINANT topic.
- title should be human-readable and specific. "Python Script Help" is bad. "Building Shopify Inventory Sync Script" is good.
- Ignore system messages and tool-use artifacts. Focus on user messages and substance.

When given multiple conversations, return a JSON array of extraction objects.`;

// ── Cache management ───────────────────────────────────────────

interface CacheEntry {
  chatId: string;
  updatedAt: number;
  extraction: ConversationExtraction;
}

async function loadCache(): Promise<Map<string, CacheEntry>> {
  const cached = await getItem<CacheEntry[]>(CACHE_KEY);
  const map = new Map<string, CacheEntry>();
  if (cached) {
    for (const entry of cached) {
      map.set(entry.chatId, entry);
    }
  }
  return map;
}

async function saveCache(cache: Map<string, CacheEntry>): Promise<void> {
  await setItem(CACHE_KEY, Array.from(cache.values()));
}

// ── Core extraction ────────────────────────────────────────────

interface ChatWithContent {
  id: string;
  title: string;
  updated_at: number;
  messages: Array<{ role: string; content: string }>;
}

/** Fetch full chat content (messages) for a chat ID. */
async function fetchChatContent(chatId: string): Promise<ChatWithContent | null> {
  try {
    const chat = await getChat(chatId);
    if (!chat?.chat?.messages) return null;

    // Extract messages from Open WebUI chat format
    const messages: Array<{ role: string; content: string }> = [];
    const msgMap = chat.chat.messages ?? {};

    // Messages may be in a history object or flat array
    const history = chat.chat.history?.messages ?? {};
    const allMsgs = Object.values({ ...msgMap, ...history }) as any[];

    for (const msg of allMsgs) {
      if (msg?.role && msg?.content) {
        messages.push({ role: msg.role, content: String(msg.content).slice(0, 500) });
      }
    }

    return {
      id: chat.id,
      title: chat.title ?? 'Untitled',
      updated_at: chat.updated_at ?? 0,
      messages,
    };
  } catch {
    return null;
  }
}

/** Condense a chat into a text block for the LLM prompt. */
function condenseChatForPrompt(chat: ChatWithContent): string {
  const msgText = chat.messages
    .slice(0, 10) // First 10 messages for context
    .map((m) => `${m.role}: ${m.content}`)
    .join('\n');

  return `--- CONVERSATION ID: ${chat.id} ---\nTitle: ${chat.title}\n${msgText}\n--- END ---`;
}

/** Parse JSON from LLM response, handling markdown code blocks. */
function parseExtractionResponse(text: string): ConversationExtraction[] {
  // Strip markdown code fences if present
  let cleaned = text.trim();
  if (cleaned.startsWith('```')) {
    cleaned = cleaned.replace(/^```(?:json)?\n?/, '').replace(/\n?```$/, '');
  }

  try {
    const parsed = JSON.parse(cleaned);
    return Array.isArray(parsed) ? parsed : [parsed];
  } catch {
    // Try to find JSON array in the response
    const match = cleaned.match(/\[[\s\S]*\]/);
    if (match) {
      try {
        return JSON.parse(match[0]);
      } catch {
        return [];
      }
    }
    // Try single object
    const objMatch = cleaned.match(/\{[\s\S]*\}/);
    if (objMatch) {
      try {
        return [JSON.parse(objMatch[0])];
      } catch {
        return [];
      }
    }
    return [];
  }
}

/** Extract metadata from a batch of conversations via LLM. */
async function extractBatch(
  chats: ChatWithContent[],
): Promise<ConversationExtraction[]> {
  const userContent = chats.map(condenseChatForPrompt).join('\n\n');

  const messages: ChatMessage[] = [
    { role: 'system', content: EXTRACTION_SYSTEM_PROMPT },
    {
      role: 'user',
      content: `Analyze the following ${chats.length} conversation(s) and return a JSON array of extraction objects:\n\n${userContent}`,
    },
  ];

  const response = await chatCompletion(EXTRACTION_MODEL, messages);
  const content = response.choices?.[0]?.message?.content ?? '';
  return parseExtractionResponse(content);
}

// ── Public API ─────────────────────────────────────────────────

const BATCH_SIZE = 3;

/**
 * Extract structured metadata from all user chats.
 *
 * - Fetches chat list from server
 * - Checks cache to skip unchanged chats
 * - Batches remaining chats for LLM extraction
 * - Returns all extractions (cached + new)
 */
export async function extractConversations(
  onProgress?: (current: number, total: number) => void,
): Promise<ConversationExtraction[]> {
  // 1. Get all chats from server
  const allChats = await getChats();
  if (!allChats.length) return [];

  // 2. Load cache
  const cache = await loadCache();

  // 3. Separate cached vs needs-extraction
  const needsExtraction: typeof allChats = [];
  const cachedResults: ConversationExtraction[] = [];

  for (const chat of allChats) {
    const cached = cache.get(chat.id);
    if (cached && cached.updatedAt === chat.updated_at) {
      cachedResults.push(cached.extraction);
    } else {
      needsExtraction.push(chat);
    }
  }

  const total = needsExtraction.length;
  let processed = 0;

  if (total === 0) {
    onProgress?.(allChats.length, allChats.length);
    return cachedResults;
  }

  // 4. Fetch full content and batch-extract
  const newExtractions: ConversationExtraction[] = [];

  for (let i = 0; i < needsExtraction.length; i += BATCH_SIZE) {
    const batch = needsExtraction.slice(i, i + BATCH_SIZE);

    // Fetch full content for each chat in batch
    const chatContents: ChatWithContent[] = [];
    for (const chat of batch) {
      const content = await fetchChatContent(chat.id);
      if (content) chatContents.push(content);
    }

    if (chatContents.length === 0) {
      processed += batch.length;
      onProgress?.(cachedResults.length + processed, allChats.length);
      continue;
    }

    // LLM extraction
    try {
      const extractions = await extractBatch(chatContents);

      for (const ext of extractions) {
        newExtractions.push(ext);

        // Update cache
        const chatContent = chatContents.find((c) => c.id === ext.conversation_id);
        if (chatContent) {
          cache.set(ext.conversation_id, {
            chatId: ext.conversation_id,
            updatedAt: chatContent.updated_at,
            extraction: ext,
          });
        }
      }
    } catch (err) {
      console.warn('Extraction batch failed:', err);
    }

    processed += batch.length;
    onProgress?.(cachedResults.length + processed, allChats.length);
  }

  // 5. Persist updated cache
  await saveCache(cache);

  return [...cachedResults, ...newExtractions];
}
