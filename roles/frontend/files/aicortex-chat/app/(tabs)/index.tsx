import React from 'react';
import {
  FlatList,
  Pressable,
  StyleSheet,
  View,
  Text,
} from 'react-native';
import { useRouter } from 'expo-router';
import { LinearGradient } from 'expo-linear-gradient';
import { MaterialIcons } from '@expo/vector-icons';

import Colors from '@/constants/Colors';
import { useColorScheme } from '@/components/useColorScheme';
import { useAgents } from '@/hooks/useAgents';
import { useConversations } from '@/hooks/useConversations';
import { spacing, borderRadius, fontSize } from '@/constants/designTokens';

export default function ChatsScreen() {
  const colorScheme = useColorScheme();
  const colors = Colors[colorScheme];
  const router = useRouter();
  const { agents } = useAgents();
  const { conversations, createConversation } = useConversations();

  const handleNewChat = () => {
    const defaultAgent = agents[0];
    if (!defaultAgent) return;
    const conv = createConversation(defaultAgent.id);
    router.push(`/chat/${conv.id}` as any);
  };

  const getAgent = (agentId?: string) =>
    agents.find((a) => a.id === agentId);

  const formatTime = (ts: number) => {
    const d = new Date(ts);
    const now = new Date();
    if (d.toDateString() === now.toDateString()) {
      return d.toLocaleTimeString([], {
        hour: '2-digit',
        minute: '2-digit',
      });
    }
    return d.toLocaleDateString([], { month: 'short', day: 'numeric' });
  };

  return (
    <View style={[styles.container, { backgroundColor: colors.background }]}>
      {/* Header */}
      <View style={styles.header}>
        <Text style={[styles.headerTitle, { color: colors.text }]}>Chats</Text>
      </View>

      {conversations.length === 0 ? (
        <View style={styles.empty}>
          <MaterialIcons
            name="chat-bubble-outline"
            size={64}
            color={colors.outlineVariant}
          />
          <Text style={[styles.emptyTitle, { color: colors.text }]}>
            No conversations yet
          </Text>
          <Text style={[styles.emptySubtitle, { color: colors.onSurfaceVariant }]}>
            Go to Contacts to start chatting with an AI agent
          </Text>
        </View>
      ) : (
        <FlatList
          data={conversations}
          keyExtractor={(item) => item.id}
          contentContainerStyle={styles.listContent}
          renderItem={({ item }) => {
            const agent = getAgent(item.agentId ?? item.expertId);
            if (!agent) return null;
            const lastMsg = item.messages[item.messages.length - 1];
            const isUnread = lastMsg?.role === 'assistant';
            const preview = lastMsg
              ? lastMsg.role === 'user'
                ? `You: ${lastMsg.content}`
                : lastMsg.content
              : 'New conversation';

            return (
              <Pressable
                onPress={() => router.push(`/chat/${item.id}` as any)}
                style={({ pressed }) => [
                  styles.row,
                  { opacity: pressed ? 0.7 : 1 },
                ]}>
                <View style={styles.avatarContainer}>
                  <LinearGradient
                    colors={agent.gradientColors}
                    style={styles.avatar}>
                    <Text style={styles.avatarText}>{agent.initials}</Text>
                  </LinearGradient>
                  <View
                    style={[
                      styles.statusDot,
                      {
                        backgroundColor:
                          agent.status === 'online'
                            ? colors.statusOnline
                            : colors.statusOffline,
                      },
                    ]}
                  />
                </View>

                <View style={styles.rowContent}>
                  <View style={styles.rowHeader}>
                    <Text
                      style={[
                        styles.rowTitle,
                        {
                          color: colors.text,
                          fontWeight: isUnread ? '700' : '500',
                        },
                      ]}
                      numberOfLines={1}>
                      {agent.name}
                    </Text>
                    <Text style={[styles.rowTime, { color: colors.outline }]}>
                      {formatTime(item.lastMessageAt)}
                    </Text>
                  </View>
                  <View style={styles.rowPreviewRow}>
                    <Text
                      style={[
                        styles.rowPreview,
                        {
                          color: isUnread
                            ? colors.onSurfaceVariant
                            : colors.outline,
                        },
                      ]}
                      numberOfLines={1}>
                      {preview}
                    </Text>
                    {lastMsg?.role === 'user' && (
                      <MaterialIcons
                        name="done"
                        size={16}
                        color={colors.tint}
                      />
                    )}
                  </View>
                </View>

                <MaterialIcons
                  name="chevron-right"
                  size={20}
                  color={colors.outlineVariant}
                />
              </Pressable>
            );
          }}
        />
      )}

      {/* FAB */}
      <Pressable
        onPress={handleNewChat}
        style={({ pressed }) => [
          styles.fab,
          {
            backgroundColor: colors.tint,
            opacity: pressed ? 0.85 : 1,
          },
        ]}>
        <MaterialIcons name="edit" size={22} color="#fff" />
      </Pressable>
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1 },
  header: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    paddingHorizontal: spacing.xl,
    paddingTop: 60,
    paddingBottom: spacing.md,
  },
  headerTitle: {
    fontSize: fontSize['2xl'],
    fontWeight: '700',
  },
  empty: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
    padding: 40,
  },
  emptyTitle: {
    fontSize: fontSize.lg,
    fontWeight: '600',
    marginTop: spacing.lg,
    marginBottom: spacing.sm,
  },
  emptySubtitle: {
    fontSize: fontSize.md,
    textAlign: 'center',
  },
  listContent: {
    paddingBottom: 100,
  },
  row: {
    flexDirection: 'row',
    paddingHorizontal: spacing.xl,
    paddingVertical: spacing.md,
    alignItems: 'center',
  },
  avatarContainer: {
    position: 'relative',
    marginRight: spacing.md,
  },
  avatar: {
    width: 50,
    height: 50,
    borderRadius: 25,
    alignItems: 'center',
    justifyContent: 'center',
  },
  avatarText: {
    color: '#fff',
    fontWeight: '700',
    fontSize: 16,
  },
  statusDot: {
    position: 'absolute',
    bottom: 0,
    right: 0,
    width: 14,
    height: 14,
    borderRadius: 7,
    borderWidth: 2,
    borderColor: '#000',
  },
  rowContent: {
    flex: 1,
    marginRight: spacing.sm,
  },
  rowHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    marginBottom: 3,
  },
  rowTitle: {
    fontSize: fontSize.base,
    flex: 1,
  },
  rowTime: {
    fontSize: fontSize.sm,
    marginLeft: spacing.sm,
  },
  rowPreviewRow: {
    flexDirection: 'row',
    alignItems: 'center',
  },
  rowPreview: {
    fontSize: fontSize.md,
    flex: 1,
  },
  fab: {
    position: 'absolute',
    bottom: 100,
    right: 24,
    width: 56,
    height: 56,
    borderRadius: 28,
    alignItems: 'center',
    justifyContent: 'center',
    elevation: 6,
    shadowColor: '#000',
    shadowOffset: { width: 0, height: 3 },
    shadowOpacity: 0.3,
    shadowRadius: 6,
  },
});
