/**
 * Embedded chat UI for the Concierge onboarding conversation.
 *
 * Simplified version of the main chat screen — no attachments, no mic,
 * just a clean conversation with Cortex.
 */

import React, { useCallback, useEffect, useRef, useState } from 'react';
import {
  ActivityIndicator,
  KeyboardAvoidingView,
  Platform,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  View,
} from 'react-native';
import { BlurView } from 'expo-blur';
import { MaterialIcons } from '@expo/vector-icons';

import Colors from '@/constants/Colors';
import { useColorScheme } from '@/components/useColorScheme';
import {
  chatCompletionStream,
  chatCompletion,
  type ChatMessage,
} from '@/services/api';
import {
  CORTEX_MODEL_ID,
  buildCortexPrompt,
  isConversationComplete,
  parseConciergeOutput,
  conciergeToRecommendations,
  JSON_EXTRACTION_PROMPT,
} from '@/services/concierge';
import type { AgentRecommendation, ConciergeOutput } from '@/constants/types';
import { spacing, borderRadius, fontSize, fontWeight as fw } from '@/constants/designTokens';

interface Message {
  id: string;
  role: 'user' | 'assistant';
  content: string;
}

interface Props {
  userName: string;
  userRole: string;
  aiComfort: string;
  onComplete: (recommendations: AgentRecommendation[], output: ConciergeOutput | null) => void;
  onSkip: () => void;
}

export default function ConciergeChat({
  userName,
  userRole,
  aiComfort,
  onComplete,
  onSkip,
}: Props) {
  const colorScheme = useColorScheme();
  const colors = Colors[colorScheme];
  const scrollRef = useRef<ScrollView>(null);

  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState('');
  const [isStreaming, setIsStreaming] = useState(false);
  const [streamingContent, setStreamingContent] = useState('');
  const [conversationDone, setConversationDone] = useState(false);
  const [extractingJson, setExtractingJson] = useState(false);

  // Build the system prompt once
  const systemPrompt = useRef(
    buildCortexPrompt(userName, userRole, aiComfort),
  ).current;

  // Send Cortex's opening message on mount
  useEffect(() => {
    sendOpeningMessage();
  }, []);

  const scrollToBottom = () => {
    setTimeout(() => scrollRef.current?.scrollToEnd({ animated: true }), 100);
  };

  const buildHistory = useCallback(
    (extraMessages?: Message[]): ChatMessage[] => {
      const history: ChatMessage[] = [
        { role: 'system', content: systemPrompt },
      ];
      for (const m of [...messages, ...(extraMessages ?? [])]) {
        history.push({ role: m.role, content: m.content });
      }
      return history;
    },
    [messages, systemPrompt],
  );

  const sendOpeningMessage = async () => {
    setIsStreaming(true);
    setStreamingContent('');

    const history: ChatMessage[] = [
      { role: 'system', content: systemPrompt },
      { role: 'user', content: '(User just arrived at onboarding. Send your opening message.)' },
    ];

    const assistantId = Date.now().toString(36);
    let accumulated = '';

    try {
      await chatCompletionStream(
        CORTEX_MODEL_ID,
        history,
        (delta) => {
          accumulated += delta;
          setStreamingContent(accumulated);
          scrollToBottom();
        },
      );

      setMessages([{ id: assistantId, role: 'assistant', content: accumulated }]);
      setStreamingContent('');
    } catch {
      setMessages([
        {
          id: assistantId,
          role: 'assistant',
          content: `Hey ${userName || 'there'}. I'm Cortex — think of me as your chief of staff. I'm going to ask you a few quick questions so I can put together the right AI team for you. Should take about 2 minutes. Ready?`,
        },
      ]);
    } finally {
      setIsStreaming(false);
      scrollToBottom();
    }
  };

  const handleSend = async () => {
    const text = input.trim();
    if (!text || isStreaming || conversationDone) return;

    const userMsg: Message = {
      id: Date.now().toString(36),
      role: 'user',
      content: text,
    };
    const updatedMessages = [...messages, userMsg];
    setMessages(updatedMessages);
    setInput('');
    setIsStreaming(true);
    setStreamingContent('');
    scrollToBottom();

    const history = buildHistory([userMsg]);
    const assistantId = (Date.now() + 1).toString(36);
    let accumulated = '';

    try {
      await chatCompletionStream(
        CORTEX_MODEL_ID,
        history,
        (delta) => {
          accumulated += delta;
          setStreamingContent(accumulated);
          scrollToBottom();
        },
      );

      const newMessages = [
        ...updatedMessages,
        { id: assistantId, role: 'assistant' as const, content: accumulated },
      ];
      setMessages(newMessages);
      setStreamingContent('');

      // Check if conversation is complete
      if (isConversationComplete(newMessages)) {
        setConversationDone(true);
        await extractAndComplete(newMessages);
      }
    } catch (err) {
      const errMsg = err instanceof Error ? err.message : 'Something went wrong';
      setMessages((prev) => [
        ...prev,
        { id: assistantId, role: 'assistant', content: `Sorry, I hit a snag: ${errMsg}. Try again?` },
      ]);
    } finally {
      setIsStreaming(false);
      scrollToBottom();
    }
  };

  /** After conversation ends, extract JSON profile from Cortex. */
  const extractAndComplete = async (allMessages: Message[]) => {
    setExtractingJson(true);

    try {
      const history: ChatMessage[] = [
        { role: 'system', content: systemPrompt },
        ...allMessages.map((m) => ({ role: m.role, content: m.content })),
        { role: 'user', content: JSON_EXTRACTION_PROMPT },
      ];

      const response = await chatCompletion(CORTEX_MODEL_ID, history);
      const jsonText = response.choices?.[0]?.message?.content ?? '';
      const output = parseConciergeOutput(jsonText);

      if (output) {
        const recommendations = conciergeToRecommendations(output);
        onComplete(recommendations, output);
      } else {
        // Fallback: generate default recommendations based on role
        const fallback = getFallbackRecommendations(userRole);
        onComplete(fallback, null);
      }
    } catch {
      // Fallback on error
      const fallback = getFallbackRecommendations(userRole);
      onComplete(fallback, null);
    } finally {
      setExtractingJson(false);
    }
  };

  return (
    <KeyboardAvoidingView
      style={styles.container}
      behavior={Platform.OS === 'ios' ? 'padding' : undefined}
      keyboardVerticalOffset={100}>
      {/* Messages */}
      <ScrollView
        ref={scrollRef}
        style={styles.messageList}
        contentContainerStyle={styles.messageListContent}
        showsVerticalScrollIndicator={false}>
        {messages.map((msg) => (
          <View
            key={msg.id}
            style={[
              styles.messageBubble,
              msg.role === 'user' ? styles.userBubble : styles.assistantBubble,
              {
                backgroundColor:
                  msg.role === 'user' ? colors.tint : colors.cardBackground,
              },
            ]}>
            {msg.role === 'assistant' && (
              <Text style={[styles.senderLabel, { color: colors.tint }]}>
                Cortex
              </Text>
            )}
            <Text
              style={[
                styles.messageText,
                { color: msg.role === 'user' ? '#fff' : colors.text },
              ]}>
              {msg.content}
            </Text>
          </View>
        ))}

        {/* Streaming message */}
        {isStreaming && streamingContent && (
          <View
            style={[
              styles.messageBubble,
              styles.assistantBubble,
              { backgroundColor: colors.cardBackground },
            ]}>
            <Text style={[styles.senderLabel, { color: colors.tint }]}>
              Cortex
            </Text>
            <Text style={[styles.messageText, { color: colors.text }]}>
              {streamingContent}
            </Text>
          </View>
        )}

        {/* Typing indicator */}
        {isStreaming && !streamingContent && (
          <View
            style={[
              styles.messageBubble,
              styles.assistantBubble,
              { backgroundColor: colors.cardBackground },
            ]}>
            <View style={styles.typingRow}>
              <View style={[styles.typingDot, { backgroundColor: colors.tint }]} />
              <View style={[styles.typingDot, { backgroundColor: colors.tint, opacity: 0.6 }]} />
              <View style={[styles.typingDot, { backgroundColor: colors.tint, opacity: 0.3 }]} />
            </View>
          </View>
        )}

        {/* Extracting JSON indicator */}
        {extractingJson && (
          <View style={styles.extractingRow}>
            <ActivityIndicator size="small" color={colors.tint} />
            <Text style={[styles.extractingText, { color: colors.secondaryText }]}>
              Putting your team together...
            </Text>
          </View>
        )}
      </ScrollView>

      {/* Input Bar */}
      {!conversationDone && (
        <View style={styles.inputContainer}>
          <BlurView
            intensity={60}
            tint={colorScheme === 'dark' ? 'dark' : 'light'}
            style={styles.inputBlur}>
            <View
              style={[
                styles.inputRow,
                { borderColor: colors.glassBorder },
              ]}>
              <TextInput
                value={input}
                onChangeText={setInput}
                placeholder="Type your reply..."
                placeholderTextColor={colors.secondaryText}
                style={[styles.input, { color: colors.text }]}
                onSubmitEditing={handleSend}
                returnKeyType="send"
                editable={!isStreaming}
                multiline
              />
              <Pressable
                onPress={handleSend}
                disabled={!input.trim() || isStreaming}
                style={[
                  styles.sendBtn,
                  {
                    backgroundColor: input.trim() ? colors.tint : colors.surfaceHigh,
                  },
                ]}>
                <MaterialIcons
                  name="arrow-upward"
                  size={20}
                  color={input.trim() ? '#fff' : colors.secondaryText}
                />
              </Pressable>
            </View>
          </BlurView>

          {/* Skip button */}
          <Pressable onPress={onSkip} style={styles.skipBtn}>
            <Text style={[styles.skipText, { color: colors.secondaryText }]}>
              Skip — use defaults
            </Text>
          </Pressable>
        </View>
      )}
    </KeyboardAvoidingView>
  );
}

// ── Fallback recommendations by role ───────────────────────────

function getFallbackRecommendations(role: string): AgentRecommendation[] {
  const roleDefaults: Record<string, AgentRecommendation[]> = {
    entrepreneur: [
      { agent_type: 'business_strategy_agent', reason: 'Role default', confidence: 'medium' },
      { agent_type: 'email_triage_agent', reason: 'Role default', confidence: 'medium' },
      { agent_type: 'content_strategist_agent', reason: 'Role default', confidence: 'medium' },
    ],
    professional: [
      { agent_type: 'email_triage_agent', reason: 'Role default', confidence: 'medium' },
      { agent_type: 'meeting_prep_agent', reason: 'Role default', confidence: 'medium' },
      { agent_type: 'schedule_optimizer_agent', reason: 'Role default', confidence: 'medium' },
    ],
    developer: [
      { agent_type: 'code_assistant_agent', reason: 'Role default', confidence: 'medium' },
      { agent_type: 'devops_agent', reason: 'Role default', confidence: 'medium' },
      { agent_type: 'research_agent', reason: 'Role default', confidence: 'medium' },
    ],
    creative: [
      { agent_type: 'writing_partner_agent', reason: 'Role default', confidence: 'medium' },
      { agent_type: 'content_strategist_agent', reason: 'Role default', confidence: 'medium' },
      { agent_type: 'research_agent', reason: 'Role default', confidence: 'medium' },
    ],
    student: [
      { agent_type: 'study_coach_agent', reason: 'Role default', confidence: 'medium' },
      { agent_type: 'research_agent', reason: 'Role default', confidence: 'medium' },
      { agent_type: 'writing_partner_agent', reason: 'Role default', confidence: 'medium' },
    ],
    homemaker: [
      { agent_type: 'schedule_optimizer_agent', reason: 'Role default', confidence: 'medium' },
      { agent_type: 'meal_planning_agent', reason: 'Role default', confidence: 'medium' },
      { agent_type: 'finance_tracker_agent', reason: 'Role default', confidence: 'medium' },
    ],
  };

  return roleDefaults[role] ?? roleDefaults.professional;
}

const styles = StyleSheet.create({
  container: { flex: 1 },
  messageList: { flex: 1 },
  messageListContent: {
    paddingHorizontal: spacing.lg,
    paddingTop: spacing.md,
    paddingBottom: spacing.lg,
    gap: spacing.sm,
  },
  messageBubble: {
    maxWidth: '85%',
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
    borderRadius: 20,
  },
  userBubble: {
    alignSelf: 'flex-end',
    borderBottomRightRadius: 4,
  },
  assistantBubble: {
    alignSelf: 'flex-start',
    borderBottomLeftRadius: 4,
  },
  senderLabel: {
    fontSize: 10,
    fontWeight: fw.bold,
    letterSpacing: 0.5,
    marginBottom: 2,
  },
  messageText: {
    fontSize: fontSize.body,
    lineHeight: 22,
  },
  typingRow: {
    flexDirection: 'row',
    gap: 4,
    paddingVertical: 4,
    paddingHorizontal: 4,
  },
  typingDot: {
    width: 6,
    height: 6,
    borderRadius: 3,
  },
  extractingRow: {
    flexDirection: 'row',
    alignItems: 'center',
    alignSelf: 'center',
    gap: spacing.sm,
    paddingVertical: spacing.lg,
  },
  extractingText: {
    fontSize: fontSize.subheadline,
    fontWeight: fw.medium,
  },

  // Input
  inputContainer: {
    paddingBottom: spacing.sm,
  },
  inputBlur: {
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
  },
  inputRow: {
    flexDirection: 'row',
    alignItems: 'flex-end',
    borderWidth: 0.5,
    borderRadius: 24,
    paddingHorizontal: spacing.md,
    paddingVertical: 6,
    gap: spacing.sm,
  },
  input: {
    flex: 1,
    fontSize: fontSize.body,
    maxHeight: 100,
    paddingVertical: 4,
  },
  sendBtn: {
    width: 32,
    height: 32,
    borderRadius: 16,
    alignItems: 'center',
    justifyContent: 'center',
  },
  skipBtn: {
    alignSelf: 'center',
    paddingVertical: spacing.sm,
  },
  skipText: {
    fontSize: fontSize.caption1,
    fontWeight: fw.medium,
  },
});
