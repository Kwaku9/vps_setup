import { useEffect, useRef, useState, useCallback } from 'react';
import {
  ActivityIndicator,
  FlatList,
  KeyboardAvoidingView,
  Platform,
  Pressable,
  StyleSheet,
  TextInput,
  View,
  Text,
} from 'react-native';
import { useLocalSearchParams, useRouter } from 'expo-router';
import { LinearGradient } from 'expo-linear-gradient';
import { BlurView } from 'expo-blur';
import { MaterialIcons } from '@expo/vector-icons';

import Colors from '@/constants/Colors';
import { useColorScheme } from '@/components/useColorScheme';
import { Message } from '@/constants/types';
import { useVoiceSession } from '@/hooks/useVoiceSession';
import VoiceOverlay from '@/components/VoiceOverlay';
import { useConversations } from '@/hooks/useConversations';
import { useAgents } from '@/hooks/useAgents';
import { useAuth } from '@/hooks/useAuth';
import {
  chatCompletionStream,
  getChat,
  getToken,
  type ChatMessage,
} from '@/services/api';
import AsyncStorage from '@react-native-async-storage/async-storage';
import {
  spacing,
  borderRadius,
  fontSize as fs,
  fontWeight,
  letterSpacing,
  dimensions,
} from '@/constants/designTokens';

// ── Code Block ──────────────────────────────────────────────────

function CodeBlock({ code, language }: { code: string; language?: string }) {
  const colorScheme = useColorScheme();
  const colors = Colors[colorScheme];
  return (
    <View style={[codeStyles.container, { backgroundColor: colors.surfaceHigh }]}>
      <View style={[codeStyles.header, { borderBottomColor: colors.outline }]}>
        <Text style={[codeStyles.lang, { color: colors.tint }]}>
          {language ?? 'code'}
        </Text>
        <Pressable hitSlop={8}>
          <Text style={[codeStyles.copyBtn, { color: colors.secondaryText }]}>
            Copy
          </Text>
        </Pressable>
      </View>
      <Text style={[codeStyles.code, { color: colors.onSurface }]}>{code}</Text>
    </View>
  );
}

const codeStyles = StyleSheet.create({
  container: {
    borderRadius: borderRadius.codeBlock,
    overflow: 'hidden',
    marginTop: spacing.sm,
  },
  header: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.xs + 2,
    borderBottomWidth: StyleSheet.hairlineWidth,
  },
  lang: { fontSize: fs.caption2, fontWeight: fontWeight.semibold, letterSpacing: 0.5 },
  copyBtn: { fontSize: fs.caption2 },
  code: {
    fontFamily: Platform.OS === 'ios' ? 'Menlo' : 'monospace',
    fontSize: fs.footnote,
    lineHeight: 20,
    padding: spacing.md,
  },
});

// ── Markdown-lite parser ────────────────────────────────────────

function parseMessageContent(content: string) {
  const codeBlockRegex = /```(\w*)\n([\s\S]*?)```/g;
  const parts: { type: 'text' | 'code'; content: string; language?: string }[] = [];
  let lastIndex = 0;
  let match;

  while ((match = codeBlockRegex.exec(content)) !== null) {
    if (match.index > lastIndex) {
      parts.push({ type: 'text', content: content.slice(lastIndex, match.index) });
    }
    parts.push({
      type: 'code',
      content: match[2].trim(),
      language: match[1] || undefined,
    });
    lastIndex = match.index + match[0].length;
  }
  if (lastIndex < content.length) {
    parts.push({ type: 'text', content: content.slice(lastIndex) });
  }
  return parts.length > 0 ? parts : [{ type: 'text' as const, content }];
}

// ── Chat Screen ─────────────────────────────────────────────────

export default function ChatScreen() {
  const params = useLocalSearchParams<{ id: string; serverChatId?: string; serverModel?: string }>();
  const id = params.id;
  const serverChatId = params.serverChatId;
  const serverModel = params.serverModel;
  const colorScheme = useColorScheme();
  const colors = Colors[colorScheme];
  const router = useRouter();
  const listRef = useRef<FlatList>(null);
  const abortRef = useRef<AbortController | null>(null);

  const { getConversation, addMessage, updateMessage, flush } = useConversations();
  const { getAgent, agents } = useAgents();
  const { isAuthenticated } = useAuth();
  const conversation = getConversation(id);
  const agent = getAgent(conversation?.agentId ?? conversation?.expertId ?? '') ?? agents[0];

  const [input, setInput] = useState('');
  const [isStreaming, setIsStreaming] = useState(false);
  const [streamingContent, setStreamingContent] = useState('');
  const [serverMessages, setServerMessages] = useState<Message[]>([]);
  const [loadingHistory, setLoadingHistory] = useState(!!serverChatId);
  const [showVoiceOverlay, setShowVoiceOverlay] = useState(false);
  const voice = useVoiceSession();

  // Load server chat history when resuming from Projects
  useEffect(() => {
    if (!serverChatId || !getToken()) {
      setLoadingHistory(false);
      return;
    }

    const cacheKey = `@aicortex/chat_cache/${serverChatId}`;

    (async () => {
      // Try cache first
      try {
        const cached = await AsyncStorage.getItem(cacheKey);
        if (cached) {
          const parsed = JSON.parse(cached) as Message[];
          setServerMessages(parsed);
          setLoadingHistory(false);
          // Still refresh from server in background
        }
      } catch {}

      // Fetch from server
      try {
        const fullChat = await getChat(serverChatId);
        const rawMessages = fullChat.chat?.messages ?? [];
        const mapped: Message[] = rawMessages.map((m: any) => ({
          id: m.id ?? Date.now().toString(36),
          role: m.role as 'user' | 'assistant',
          content: m.content ?? '',
          timestamp: m.timestamp ? m.timestamp * 1000 : Date.now(),
        }));
        setServerMessages(mapped);
        // Cache for next time
        await AsyncStorage.setItem(cacheKey, JSON.stringify(mapped));
      } catch {
        // Keep cached data if server fetch fails
      } finally {
        setLoadingHistory(false);
      }
    })();
  }, [serverChatId]);

  // Auto-scroll when streaming
  useEffect(() => {
    if (isStreaming) {
      const timer = setInterval(() => {
        listRef.current?.scrollToEnd({ animated: false });
      }, 200);
      return () => clearInterval(timer);
    }
  }, [isStreaming]);

  const handleSend = useCallback(async () => {
    const text = input.trim();
    if (!text || !conversation || isStreaming) return;

    // Add user message
    const userMsg: Message = {
      id: Date.now().toString(36),
      role: 'user',
      content: text,
      timestamp: Date.now(),
    };
    addMessage(conversation.id, userMsg);
    setInput('');

    // Check auth
    if (!getToken()) {
      const fallback: Message = {
        id: (Date.now() + 1).toString(36),
        role: 'assistant',
        content:
          'Not connected to Open WebUI. Go to Profile → Connect to enter your API key.',
        timestamp: Date.now(),
      };
      addMessage(conversation.id, fallback);
      return;
    }

    // Build message history — no system prompt needed, server handles it via custom model
    const history: ChatMessage[] = [];
    for (const m of conversation.messages) {
      history.push({ role: m.role, content: m.content });
    }
    history.push({ role: 'user', content: text });

    // Create placeholder assistant message for streaming
    const assistantId = (Date.now() + 1).toString(36);
    const assistantMsg: Message = {
      id: assistantId,
      role: 'assistant',
      content: '',
      timestamp: Date.now(),
      expertId: agent?.id,
    };
    addMessage(conversation.id, assistantMsg);
    setIsStreaming(true);
    setStreamingContent('');

    // Use agent's custom model ID — Open WebUI routes to base model + injects system prompt
    const modelId = serverModel ?? agent?.id ?? 'claude-sonnet-4';

    try {
      const controller = new AbortController();
      abortRef.current = controller;

      let accumulated = '';
      await chatCompletionStream(
        modelId,
        history,
        (delta) => {
          accumulated += delta;
          setStreamingContent(accumulated);
          updateMessage(conversation.id, assistantId, accumulated);
        },
        controller.signal,
      );

      // Final persist
      flush();
    } catch (err: any) {
      if (err.name !== 'AbortError') {
        const errorContent =
          err.status === 401
            ? 'Authentication failed. Please reconnect in Profile → Connect.'
            : `Error: ${err.message}`;
        updateMessage(conversation.id, assistantId, errorContent);
        flush();
      }
    } finally {
      setIsStreaming(false);
      setStreamingContent('');
      abortRef.current = null;
    }
  }, [input, conversation, agent, isStreaming, addMessage, updateMessage, flush]);

  const handleStopStreaming = useCallback(() => {
    abortRef.current?.abort();
  }, []);

  // Merge server history + local messages (local messages are new ones sent in this session)
  const localMessages = conversation?.messages ?? [];
  const messages = serverChatId
    ? [...serverMessages, ...localMessages]
    : localMessages;

  const shouldShowTimestamp = (index: number) => {
    if (index === 0) return true;
    return messages[index].timestamp - messages[index - 1].timestamp > 5 * 60 * 1000;
  };

  const shouldShowAvatar = (index: number) => {
    if (messages[index].role === 'user') return false;
    const next = messages[index + 1];
    return !next || next.role !== 'assistant';
  };

  const formatTimestamp = (ts: number) =>
    new Date(ts).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });

  return (
    <View style={[styles.container, { backgroundColor: colors.background }]}>
      {/* ── Glass Header ── */}
      <View style={styles.headerWrap}>
        <BlurView
          intensity={80}
          tint={colorScheme === 'dark' ? 'dark' : 'light'}
          style={StyleSheet.absoluteFill}
        />
        <View style={styles.header}>
          <Pressable onPress={() => router.back()} hitSlop={12}>
            <MaterialIcons name="chevron-left" size={28} color={colors.tint} />
          </Pressable>

          <View style={styles.headerCenter}>
            {agent && (
              <LinearGradient colors={agent?.gradientColors ?? ['#6C63FF', '#B794F4']} style={styles.headerAvatar}>
                <Text style={styles.headerAvatarText}>{agent?.initials ?? 'AI'}</Text>
              </LinearGradient>
            )}
            <View>
              <Text
                style={[styles.headerName, { color: colors.text }]}
                numberOfLines={1}>
                {agent?.name ?? 'AI Assistant'}
              </Text>
              <Text style={[styles.headerStatus, { color: colors.statusOnline }]}>
                {isAuthenticated ? 'Connected' : 'Offline'}
              </Text>
            </View>
          </View>

          <Pressable hitSlop={12}>
            <MaterialIcons name="more-horiz" size={24} color={colors.secondaryText} />
          </Pressable>
        </View>
        {/* Separator */}
        <View style={[styles.separator, { backgroundColor: colors.outline }]} />
      </View>

      <KeyboardAvoidingView
        style={styles.flex}
        behavior={Platform.OS === 'ios' ? 'padding' : 'height'}
        keyboardVerticalOffset={0}>
        <FlatList
          ref={listRef}
          data={loadingHistory ? [] : messages}
          keyExtractor={(item) => item.id}
          contentContainerStyle={styles.messagesList}
          onContentSizeChange={() => listRef.current?.scrollToEnd({ animated: true })}
          ListHeaderComponent={
            loadingHistory ? (
              <View style={styles.loadingHistory}>
                <ActivityIndicator color={colors.tint} size="small" />
                <Text style={[styles.loadingText, { color: colors.secondaryText }]}>
                  Loading conversation...
                </Text>
              </View>
            ) : null
          }
          renderItem={({ item, index }) => {
            const isUser = item.role === 'user';
            const showTimestamp = shouldShowTimestamp(index);
            const showAvatar = shouldShowAvatar(index);
            const parts = parseMessageContent(item.content || '...');

            return (
              <View>
                {showTimestamp && (
                  <Text style={[styles.timestamp, { color: colors.secondaryText }]}>
                    {formatTimestamp(item.timestamp)}
                  </Text>
                )}
                <View
                  style={[
                    styles.messageRow,
                    isUser ? styles.messageRowUser : styles.messageRowAgent,
                  ]}>
                  {!isUser && (
                    <View style={styles.avatarSlot}>
                      {showAvatar && agent && (
                        <LinearGradient
                          colors={agent?.gradientColors ?? ['#6C63FF', '#B794F4']}
                          style={styles.msgAvatar}>
                          <Text style={styles.msgAvatarText}>
                            {agent?.initials ?? 'AI'}
                          </Text>
                        </LinearGradient>
                      )}
                    </View>
                  )}
                  <View style={{ maxWidth: '78%' }}>
                    <View
                      style={[
                        styles.bubble,
                        isUser
                          ? {
                              backgroundColor: colors.messageBubbleUser,
                              borderBottomRightRadius: borderRadius.chatBubbleSequential,
                            }
                          : {
                              backgroundColor: colors.messageBubbleAgent,
                              borderBottomLeftRadius: borderRadius.chatBubbleSequential,
                            },
                      ]}>
                      {parts.map((part, i) =>
                        part.type === 'code' ? (
                          <CodeBlock
                            key={i}
                            code={part.content}
                            language={part.language}
                          />
                        ) : (
                          <Text
                            key={i}
                            style={{
                              color: isUser
                                ? colors.messageTextUser
                                : colors.messageTextAgent,
                              fontSize: fs.body,
                              lineHeight: 22,
                              letterSpacing: letterSpacing.tight,
                            }}>
                            {part.content}
                          </Text>
                        ),
                      )}
                    </View>
                  </View>
                </View>
              </View>
            );
          }}
          ListFooterComponent={
            isStreaming ? (
              <View style={styles.streamingFooter}>
                <Pressable
                  style={[styles.stopButton, { borderColor: colors.outline }]}
                  onPress={handleStopStreaming}>
                  <MaterialIcons name="stop" size={16} color={colors.secondaryText} />
                  <Text style={[styles.stopText, { color: colors.secondaryText }]}>
                    Stop generating
                  </Text>
                </Pressable>
              </View>
            ) : null
          }
        />

        {/* ── Glass Input Bar ── */}
        <View style={styles.inputBarWrap}>
          <BlurView
            intensity={60}
            tint={colorScheme === 'dark' ? 'dark' : 'light'}
            style={StyleSheet.absoluteFill}
          />
          <View style={styles.inputBar}>
            <Pressable hitSlop={8}>
              <MaterialIcons name="add" size={24} color={colors.secondaryText} />
            </Pressable>
            <TextInput
              style={[
                styles.input,
                {
                  color: colors.text,
                  backgroundColor: colors.inputBackground,
                  borderColor: colors.glassBorder,
                },
              ]}
              value={input}
              onChangeText={setInput}
              placeholder={`Message ${agent?.name ?? 'AI'}...`}
              placeholderTextColor={colors.secondaryText}
              multiline
              maxLength={4000}
              editable={!isStreaming}
            />
            {input.trim() ? (
              <Pressable onPress={handleSend} disabled={isStreaming}>
                <View
                  style={[styles.sendButton, { backgroundColor: colors.tint }]}>
                  <MaterialIcons name="arrow-upward" size={18} color="#fff" />
                </View>
              </Pressable>
            ) : (
              <Pressable
                hitSlop={8}
                onPress={() => {
                  setShowVoiceOverlay(true);
                  voice.startSession();
                }}
              >
                <MaterialIcons
                  name={voice.isActive ? 'mic' : 'mic-none'}
                  size={24}
                  color={voice.isActive ? colors.tint : colors.secondaryText}
                />
              </Pressable>
            )}
          </View>
        </View>

        {/* Disclaimer */}
        <View
          style={[styles.disclaimer, { backgroundColor: colors.background }]}>
          <Text style={[styles.disclaimerText, { color: colors.tertiaryText }]}>
            AI can make mistakes. Verify important information.
          </Text>
        </View>
      </KeyboardAvoidingView>

      <VoiceOverlay
        visible={showVoiceOverlay}
        agent={agent}
        sessionState={voice.sessionState}
        isMuted={voice.isMuted}
        error={voice.error}
        onEnd={() => {
          voice.endSession();
          setShowVoiceOverlay(false);
        }}
        onToggleMute={voice.toggleMute}
      />
    </View>
  );
}

// ── Styles ──────────────────────────────────────────────────────

const styles = StyleSheet.create({
  container: { flex: 1 },
  flex: { flex: 1 },

  // Glass header
  headerWrap: {
    paddingTop: Platform.OS === 'ios' ? 56 : 36,
    overflow: 'hidden',
  },
  header: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingHorizontal: spacing.lg,
    paddingVertical: spacing.sm,
    gap: spacing.sm,
  },
  separator: {
    height: StyleSheet.hairlineWidth,
    opacity: 0.5,
  },
  headerCenter: {
    flex: 1,
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.md,
  },
  headerAvatar: {
    width: 34,
    height: 34,
    borderRadius: 17,
    alignItems: 'center',
    justifyContent: 'center',
  },
  headerAvatarText: {
    color: '#fff',
    fontSize: fs.caption1,
    fontWeight: fontWeight.bold,
  },
  headerName: {
    fontSize: fs.headline,
    fontWeight: fontWeight.semibold,
    letterSpacing: letterSpacing.tight,
  },
  headerStatus: {
    fontSize: fs.caption2,
    fontWeight: fontWeight.medium,
  },

  // Loading history
  loadingHistory: {
    alignItems: 'center',
    justifyContent: 'center',
    paddingVertical: spacing['3xl'],
    gap: spacing.sm,
  },
  loadingText: {
    fontSize: fs.footnote,
  },

  // Messages
  messagesList: {
    paddingHorizontal: spacing.md,
    paddingTop: spacing.sm,
    paddingBottom: spacing.md,
  },
  timestamp: {
    textAlign: 'center',
    fontSize: fs.caption1,
    marginVertical: spacing.md,
  },
  messageRow: {
    flexDirection: 'row',
    marginBottom: spacing.sm,
    alignItems: 'flex-end',
  },
  messageRowUser: { justifyContent: 'flex-end' },
  messageRowAgent: { justifyContent: 'flex-start' },
  avatarSlot: { width: 32, marginRight: 6 },
  msgAvatar: {
    width: 28,
    height: 28,
    borderRadius: 14,
    alignItems: 'center',
    justifyContent: 'center',
  },
  msgAvatarText: {
    color: '#fff',
    fontSize: 10,
    fontWeight: fontWeight.bold,
  },
  bubble: {
    paddingHorizontal: spacing.lg,
    paddingVertical: spacing.md,
    borderRadius: borderRadius.chatBubble,
  },

  // Streaming
  streamingFooter: {
    alignItems: 'center',
    paddingVertical: spacing.md,
  },
  stopButton: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.xs,
    borderWidth: 1,
    borderRadius: borderRadius.buttonSmall,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.xs + 2,
  },
  stopText: {
    fontSize: fs.footnote,
    fontWeight: fontWeight.medium,
  },

  // Glass input bar
  inputBarWrap: {
    overflow: 'hidden',
  },
  inputBar: {
    flexDirection: 'row',
    alignItems: 'flex-end',
    paddingHorizontal: spacing.lg,
    paddingVertical: spacing.sm,
    gap: spacing.sm,
  },
  input: {
    flex: 1,
    borderRadius: borderRadius.input,
    borderWidth: 0.5,
    paddingHorizontal: spacing.lg,
    paddingVertical: spacing.sm + 2,
    fontSize: fs.body,
    maxHeight: 120,
    letterSpacing: letterSpacing.tight,
  },
  sendButton: {
    width: dimensions.sendButtonSize,
    height: dimensions.sendButtonSize,
    borderRadius: dimensions.sendButtonSize / 2,
    alignItems: 'center',
    justifyContent: 'center',
  },
  disclaimer: {
    alignItems: 'center',
    paddingVertical: spacing.xs,
    paddingBottom: Platform.OS === 'ios' ? 30 : spacing.lg,
  },
  disclaimerText: {
    fontSize: fs.caption2,
    letterSpacing: letterSpacing.wide,
  },
});
