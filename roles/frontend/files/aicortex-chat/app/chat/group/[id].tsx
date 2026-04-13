import React, { useState, useRef } from 'react';
import {
  FlatList,
  KeyboardAvoidingView,
  Platform,
  Pressable,
  StyleSheet,
  Text,
  TextInput,
  View,
} from 'react-native';
import { useLocalSearchParams, useRouter } from 'expo-router';
import { LinearGradient } from 'expo-linear-gradient';
import { MaterialIcons } from '@expo/vector-icons';

import Colors from '@/constants/Colors';
import { useColorScheme } from '@/components/useColorScheme';
import { useConversations } from '@/hooks/useConversations';
import { useAgents } from '@/hooks/useAgents';
import { spacing, borderRadius, fontSize } from '@/constants/designTokens';
import type { Message } from '@/constants/types';

export default function GroupChatScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const colorScheme = useColorScheme();
  const colors = Colors[colorScheme];
  const router = useRouter();
  const { getConversation, addMessage } = useConversations();
  const { getAgent, agents } = useAgents();
  const [input, setInput] = useState('');
  const flatListRef = useRef<FlatList>(null);

  const conversation = getConversation(id);
  if (!conversation) {
    return (
      <View style={[styles.container, { backgroundColor: colors.background }]}>
        <Pressable onPress={() => router.back()} style={styles.backButton}>
          <MaterialIcons name="arrow-back" size={24} color={colors.text} />
        </Pressable>
        <View style={styles.emptyState}>
          <Text style={{ color: colors.outline }}>Conversation not found</Text>
        </View>
      </View>
    );
  }

  const groupName = ('groupName' in conversation
    ? (conversation as any).groupName
    : conversation.title) || 'Group Chat';

  const activeAgents = ('expertIds' in conversation
    ? (conversation as any).expertIds
    : [conversation.agentId ?? conversation.expertId]
  ).map((eid: string) => getAgent(eid)).filter(Boolean);

  const handleSend = () => {
    if (!input.trim()) return;
    const msg: Message = {
      id: Date.now().toString(36) + Math.random().toString(36).slice(2, 7),
      role: 'user',
      content: input.trim(),
      timestamp: Date.now(),
    };
    addMessage(id, msg);
    setInput('');

    // Simulated multi-model response
    setTimeout(() => {
      const responder = activeAgents[Math.floor(Math.random() * activeAgents.length)];
      if (responder) {
        const response: Message = {
          id: Date.now().toString(36) + Math.random().toString(36).slice(2, 7),
          role: 'assistant',
          content: `Analyzing from a ${responder.description.toLowerCase()} perspective...`,
          timestamp: Date.now(),
          expertId: responder.id,
        };
        addMessage(id, response);
      }
    }, 1500);
  };

  const renderMessage = ({ item }: { item: Message }) => {
    const isUser = item.role === 'user';
    const agent = item.expertId ? getAgent(item.expertId) : activeAgents[0];

    return (
      <View style={[styles.messageContainer, isUser ? styles.messageRight : styles.messageLeft]}>
        {!isUser && agent && (
          <LinearGradient colors={agent.gradientColors} style={styles.msgAvatar}>
            <Text style={styles.msgAvatarText}>{agent.initials}</Text>
          </LinearGradient>
        )}
        <View style={styles.msgContent}>
          {!isUser && agent && (
            <View style={styles.modelAttribution}>
              <Text style={[styles.modelName, { color: agent.gradientColors[0] }]}>
                {agent.name}
              </Text>
              <View style={[styles.modelBadge, { backgroundColor: colors.surfaceHigh }]}>
                <Text style={[styles.modelBadgeText, { color: colors.onSurfaceVariant }]}>
                  {agent.description.split(' ')[0].toUpperCase()}
                </Text>
              </View>
            </View>
          )}
          <View
            style={[
              styles.bubble,
              isUser
                ? { backgroundColor: colors.messageBubbleUser }
                : { backgroundColor: colors.messageBubbleAgent },
            ]}>
            <Text
              style={[
                styles.bubbleText,
                { color: isUser ? colors.messageTextUser : colors.messageTextAgent },
              ]}>
              {item.content}
            </Text>
          </View>
        </View>
      </View>
    );
  };

  return (
    <KeyboardAvoidingView
      style={[styles.container, { backgroundColor: colors.background }]}
      behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
      {/* Header */}
      <View style={[styles.header, { backgroundColor: colors.surface }]}>
        <Pressable onPress={() => router.back()}>
          <MaterialIcons name="arrow-back" size={24} color={colors.text} />
        </Pressable>

        <View style={styles.headerCenter}>
          {/* Overlapping avatars */}
          <View style={styles.avatarStack}>
            {activeAgents.slice(0, 3).map((exp: any, i: number) => (
              <LinearGradient
                key={exp.id}
                colors={exp.gradientColors}
                style={[styles.stackAvatar, { marginLeft: i > 0 ? -10 : 0, zIndex: 3 - i }]}>
                <Text style={styles.stackAvatarText}>{exp.initials}</Text>
              </LinearGradient>
            ))}
            <View style={[styles.onlineDot, { backgroundColor: colors.statusOnline }]} />
          </View>

          <View>
            <Text style={[styles.headerTitle, { color: colors.primary }]}>
              {groupName}
            </Text>
            <Text style={[styles.headerSubtitle, { color: colors.tertiary }]}>
              {activeAgents.length} MODELS ACTIVE
            </Text>
          </View>
        </View>

        <View style={styles.headerActions}>
          <Pressable>
            <MaterialIcons name="search" size={22} color={colors.outline} />
          </Pressable>
          <Pressable>
            <MaterialIcons name="settings" size={22} color={colors.outline} />
          </Pressable>
        </View>
      </View>

      {/* System Banner */}
      <View style={[styles.systemBanner, { backgroundColor: colors.surfaceLow }]}>
        <Text style={[styles.bannerText, { color: colors.outline }]}>
          CONVERSATION INITIATED WITH SHARED CONTEXT BOARD
        </Text>
      </View>

      {/* Messages */}
      <FlatList
        ref={flatListRef}
        data={conversation.messages}
        keyExtractor={(item) => item.id}
        renderItem={renderMessage}
        contentContainerStyle={styles.messagesContent}
        onContentSizeChange={() => flatListRef.current?.scrollToEnd()}
      />

      {/* Input Bar */}
      <View style={[styles.inputBar, { backgroundColor: colors.surface }]}>
        <TextInput
          value={input}
          onChangeText={setInput}
          placeholder={`Message ${groupName}...`}
          placeholderTextColor={colors.outline}
          style={[styles.textInput, { color: colors.text, backgroundColor: colors.surfaceLow }]}
          multiline
          onSubmitEditing={handleSend}
        />
        <View style={styles.inputActions}>
          <Pressable>
            <MaterialIcons name="mic" size={22} color={colors.outline} />
          </Pressable>
          <Pressable onPress={handleSend}>
            <LinearGradient
              colors={[colors.tint, '#00C6FF']}
              style={styles.sendButton}>
              <MaterialIcons name="arrow-upward" size={20} color="#fff" />
            </LinearGradient>
          </Pressable>
        </View>
      </View>

      {/* Disclaimer */}
      <View style={[styles.disclaimer, { backgroundColor: colors.background }]}>
        <Text style={[styles.disclaimerText, { color: colors.outlineVariant }]}>
          AETHERIAL CAN MAKE MISTAKES. VERIFY IMPORTANT INFORMATION
        </Text>
      </View>
    </KeyboardAvoidingView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1 },
  backButton: { padding: spacing.lg, paddingTop: 56 },
  emptyState: { flex: 1, alignItems: 'center', justifyContent: 'center' },
  header: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingHorizontal: spacing.lg,
    paddingTop: 56,
    paddingBottom: spacing.md,
    gap: spacing.md,
  },
  headerCenter: {
    flex: 1,
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.md,
  },
  avatarStack: {
    flexDirection: 'row',
    alignItems: 'center',
    position: 'relative',
  },
  stackAvatar: {
    width: 30,
    height: 30,
    borderRadius: 15,
    alignItems: 'center',
    justifyContent: 'center',
    borderWidth: 2,
    borderColor: '#131313',
  },
  stackAvatarText: {
    color: '#fff',
    fontSize: 10,
    fontWeight: '700',
  },
  onlineDot: {
    width: 8,
    height: 8,
    borderRadius: 4,
    marginLeft: spacing.xs,
  },
  headerTitle: {
    fontSize: fontSize.base,
    fontWeight: '700',
  },
  headerSubtitle: {
    fontSize: fontSize.xs,
    fontWeight: '600',
    letterSpacing: 1.5,
  },
  headerActions: {
    flexDirection: 'row',
    gap: spacing.lg,
  },
  systemBanner: {
    paddingVertical: spacing.sm,
    paddingHorizontal: spacing.lg,
    alignItems: 'center',
  },
  bannerText: {
    fontSize: 9,
    fontWeight: '600',
    letterSpacing: 1.5,
  },
  messagesContent: {
    paddingHorizontal: spacing.lg,
    paddingVertical: spacing.md,
    paddingBottom: spacing['2xl'],
  },
  messageContainer: {
    flexDirection: 'row',
    marginBottom: spacing.lg,
    gap: spacing.sm,
  },
  messageRight: {
    justifyContent: 'flex-end',
  },
  messageLeft: {
    justifyContent: 'flex-start',
  },
  msgAvatar: {
    width: 28,
    height: 28,
    borderRadius: 14,
    alignItems: 'center',
    justifyContent: 'center',
    alignSelf: 'flex-end',
  },
  msgAvatarText: {
    color: '#fff',
    fontSize: 10,
    fontWeight: '700',
  },
  msgContent: {
    maxWidth: '75%',
  },
  modelAttribution: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
    marginBottom: spacing.xs,
  },
  modelName: {
    fontSize: fontSize.sm,
    fontWeight: '700',
  },
  modelBadge: {
    paddingHorizontal: spacing.sm,
    paddingVertical: 1,
    borderRadius: borderRadius.sm,
  },
  modelBadgeText: {
    fontSize: 8,
    fontWeight: '700',
    letterSpacing: 0.5,
  },
  bubble: {
    borderRadius: borderRadius.lg,
    paddingHorizontal: spacing.lg,
    paddingVertical: spacing.md,
  },
  bubbleText: {
    fontSize: fontSize.md,
    lineHeight: 20,
  },
  inputBar: {
    flexDirection: 'row',
    alignItems: 'flex-end',
    paddingHorizontal: spacing.lg,
    paddingVertical: spacing.md,
    gap: spacing.md,
  },
  textInput: {
    flex: 1,
    borderRadius: borderRadius.xl,
    paddingHorizontal: spacing.lg,
    paddingVertical: spacing.md,
    fontSize: fontSize.md,
    maxHeight: 100,
  },
  inputActions: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.md,
    paddingBottom: spacing.xs,
  },
  sendButton: {
    width: 36,
    height: 36,
    borderRadius: 18,
    alignItems: 'center',
    justifyContent: 'center',
  },
  disclaimer: {
    alignItems: 'center',
    paddingVertical: spacing.sm,
    paddingBottom: spacing['3xl'],
  },
  disclaimerText: {
    fontSize: 8,
    letterSpacing: 0.5,
  },
});
