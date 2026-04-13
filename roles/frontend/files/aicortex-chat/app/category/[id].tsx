import React, { useEffect, useState } from 'react';
import {
  FlatList,
  Pressable,
  StyleSheet,
  Text,
  TextInput,
  View,
  ActivityIndicator,
  Platform,
} from 'react-native';
import { useLocalSearchParams, useRouter } from 'expo-router';
import { BlurView } from 'expo-blur';
import { MaterialIcons } from '@expo/vector-icons';

import Colors from '@/constants/Colors';
import { useColorScheme } from '@/components/useColorScheme';
import { CATEGORIES, UNCATEGORIZED, categorizeChat, type Category } from '@/constants/categories';
import { getChats, getToken, chatCompletionStream, type ChatMeta } from '@/services/api';
import { useConversations } from '@/hooks/useConversations';
import { useAgents } from '@/hooks/useAgents';
import { useAuth } from '@/hooks/useAuth';
import {
  spacing,
  borderRadius,
  fontSize,
  fontWeight as fw,
  letterSpacing,
} from '@/constants/designTokens';

export default function CategoryDetailScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const colorScheme = useColorScheme();
  const colors = Colors[colorScheme];
  const router = useRouter();

  const category = CATEGORIES.find((c) => c.id === id) ?? UNCATEGORIZED;

  const { createConversation } = useConversations();
  const { agents } = useAgents();
  const { isAuthenticated } = useAuth();
  const [chats, setChats] = useState<ChatMeta[]>([]);
  const [loading, setLoading] = useState(true);
  const [activeTab, setActiveTab] = useState<'chats' | 'sources'>('chats');
  const [inputText, setInputText] = useState('');

  useEffect(() => {
    loadChats();
  }, [id, isAuthenticated]);

  async function loadChats() {
    if (!getToken()) {
      setLoading(false);
      return;
    }
    try {
      const allChats = await getChats();
      const filtered = allChats.filter((chat) => {
        const matched = categorizeChat(chat.title);
        return matched.id === id;
      });
      setChats(filtered);
    } catch {
      // Silently fail — show empty state
    } finally {
      setLoading(false);
    }
  }

  const formatDate = (ts: number) => {
    const d = new Date(ts * 1000);
    const now = new Date();
    if (d.toDateString() === now.toDateString()) {
      return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    }
    const diff = now.getTime() - d.getTime();
    if (diff < 86400000 * 2) return 'Yesterday';
    return d.toLocaleDateString([], { month: 'short', day: 'numeric' });
  };

  return (
    <View style={[styles.container, { backgroundColor: colors.background }]}>
      {/* Glass Header */}
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
            <MaterialIcons
              name={category.icon}
              size={22}
              color={category.color}
            />
            <Text
              style={[styles.headerTitle, { color: colors.text }]}
              numberOfLines={1}>
              {category.label}
            </Text>
          </View>
          <Pressable hitSlop={12}>
            <MaterialIcons name="more-horiz" size={24} color={colors.secondaryText} />
          </Pressable>
        </View>
        {/* Separator */}
        <View style={[styles.separator, { backgroundColor: colors.outline }]} />
      </View>

      {/* Tabs: Chats / Sources */}
      <View style={styles.tabBar}>
        <Pressable
          onPress={() => setActiveTab('chats')}
          style={[
            styles.tab,
            activeTab === 'chats' && {
              backgroundColor: colors.surfaceHigh,
            },
          ]}>
          <Text
            style={[
              styles.tabText,
              {
                color: activeTab === 'chats' ? colors.text : colors.secondaryText,
              },
            ]}>
            Chats
          </Text>
        </Pressable>
        <Pressable
          onPress={() => setActiveTab('sources')}
          style={[
            styles.tab,
            activeTab === 'sources' && {
              backgroundColor: colors.surfaceHigh,
            },
          ]}>
          <Text
            style={[
              styles.tabText,
              {
                color: activeTab === 'sources' ? colors.text : colors.secondaryText,
              },
            ]}>
            Sources
          </Text>
        </Pressable>
      </View>

      {/* Category description */}
      <Text style={[styles.description, { color: colors.secondaryText }]}>
        {category.description}
      </Text>

      {/* Content */}
      {loading ? (
        <View style={styles.centered}>
          <ActivityIndicator color={colors.tint} />
        </View>
      ) : activeTab === 'chats' ? (
        <FlatList
          data={chats}
          keyExtractor={(item) => item.id}
          contentContainerStyle={styles.listContent}
          ListEmptyComponent={
            <View style={styles.centered}>
              <MaterialIcons
                name={category.icon}
                size={48}
                color={colors.outline}
              />
              <Text style={[styles.emptyText, { color: colors.secondaryText }]}>
                No chats in {category.label}
              </Text>
              <Text style={[styles.emptySubtext, { color: colors.tertiaryText }]}>
                Start a conversation to see it here
              </Text>
            </View>
          }
          renderItem={({ item }) => (
            <Pressable
              style={({ pressed }) => [
                styles.chatItem,
                {
                  backgroundColor: colors.cardBackground,
                  borderColor: colors.glassBorder,
                  opacity: pressed ? 0.8 : 1,
                },
              ]}
              onPress={() => {
                // Create a local conversation shell and pass the server
                // chat ID so the chat screen loads history from the API
                const agent = agents.find((a) =>
                  a.tags.some((t) =>
                    category.keywords.some((k) =>
                      t.toLowerCase().includes(k.toLowerCase()),
                    ),
                  ),
                ) ?? agents[0];
                if (agent) {
                  const conv = createConversation(agent.id);
                  router.push({
                    pathname: `/chat/${conv.id}`,
                    params: {
                      serverChatId: item.id,
                      serverModel: category.defaultModelId,
                    },
                  } as any);
                }
              }}>
              <View style={styles.chatItemContent}>
                <Text
                  style={[styles.chatTitle, { color: colors.text }]}
                  numberOfLines={1}>
                  {item.title}
                </Text>
                <Text
                  style={[styles.chatDate, { color: colors.secondaryText }]}>
                  {formatDate(item.updated_at)}
                </Text>
              </View>
              <MaterialIcons
                name="chevron-right"
                size={18}
                color={colors.secondaryText}
              />
            </Pressable>
          )}
        />
      ) : (
        <View style={styles.centered}>
          <MaterialIcons name="folder-open" size={48} color={colors.outline} />
          <Text style={[styles.emptyText, { color: colors.secondaryText }]}>
            Sources coming soon
          </Text>
          <Text style={[styles.emptySubtext, { color: colors.tertiaryText }]}>
            Attach files and documents to this category
          </Text>
        </View>
      )}

      {/* Functional input bar */}
      <View
        style={[
          styles.inputBar,
          {
            backgroundColor: colors.surface,
            borderTopColor: colors.glassBorder,
          },
        ]}>
        <Pressable hitSlop={8}>
          <MaterialIcons name="add" size={22} color={colors.secondaryText} />
        </Pressable>
        <TextInput
          style={[
            styles.inputField,
            {
              backgroundColor: colors.inputBackground,
              borderColor: colors.glassBorder,
              color: colors.text,
            },
          ]}
          value={inputText}
          onChangeText={setInputText}
          placeholder={`Message ${category.label}...`}
          placeholderTextColor={colors.secondaryText}
        />
        {inputText.trim() ? (
          <Pressable
            hitSlop={8}
            onPress={() => {
              // Start a new chat in this category with the message
              const matchedAgent = agents.find((a) =>
                a.tags.some((t) =>
                  category.keywords.some((k) =>
                    t.toLowerCase().includes(k.toLowerCase()),
                  ),
                ),
              ) ?? agents[0];
              if (matchedAgent) {
                const conv = createConversation(matchedAgent.id);
                setInputText('');
                router.push(`/chat/${conv.id}` as any);
              }
            }}>
            <View style={[styles.sendButton, { backgroundColor: colors.tint }]}>
              <MaterialIcons name="arrow-upward" size={16} color="#fff" />
            </View>
          </Pressable>
        ) : (
          <Pressable hitSlop={8}>
            <MaterialIcons name="mic" size={22} color={colors.secondaryText} />
          </Pressable>
        )}
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1 },

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
  },
  headerCenter: {
    flex: 1,
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
    marginLeft: spacing.sm,
  },
  headerTitle: {
    fontSize: fontSize.headline,
    fontWeight: fw.semibold,
    letterSpacing: letterSpacing.tight,
  },
  separator: {
    height: StyleSheet.hairlineWidth,
    opacity: 0.5,
  },

  // Tabs
  tabBar: {
    flexDirection: 'row',
    paddingHorizontal: spacing.lg,
    paddingTop: spacing.md,
    paddingBottom: spacing.xs,
    gap: spacing.xs,
  },
  tab: {
    paddingHorizontal: spacing.lg,
    paddingVertical: spacing.xs + 2,
    borderRadius: borderRadius.badge,
  },
  tabText: {
    fontSize: fontSize.subheadline,
    fontWeight: fw.semibold,
  },

  // Description
  description: {
    fontSize: fontSize.footnote,
    paddingHorizontal: spacing.lg,
    paddingBottom: spacing.md,
    letterSpacing: letterSpacing.wide,
  },

  // List
  listContent: {
    paddingHorizontal: spacing.lg,
    paddingBottom: 100,
  },
  chatItem: {
    flexDirection: 'row',
    alignItems: 'center',
    padding: spacing.lg,
    borderRadius: borderRadius.card,
    borderWidth: 0.5,
    marginBottom: spacing.sm,
  },
  chatItemContent: {
    flex: 1,
  },
  chatTitle: {
    fontSize: fontSize.body,
    fontWeight: fw.medium,
    letterSpacing: letterSpacing.tight,
    marginBottom: 2,
  },
  chatDate: {
    fontSize: fontSize.caption1,
  },

  // Empty
  centered: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
    gap: spacing.sm,
  },
  emptyText: {
    fontSize: fontSize.body,
    fontWeight: fw.medium,
  },
  emptySubtext: {
    fontSize: fontSize.footnote,
  },

  // Input bar
  inputBar: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingHorizontal: spacing.lg,
    paddingVertical: spacing.sm,
    borderTopWidth: 0.5,
    gap: spacing.sm,
    paddingBottom: Platform.OS === 'ios' ? 30 : spacing.md,
  },
  inputField: {
    flex: 1,
    height: 36,
    borderRadius: borderRadius.input,
    borderWidth: 0.5,
    paddingHorizontal: spacing.md,
    fontSize: fontSize.subheadline,
  },
  sendButton: {
    width: 28,
    height: 28,
    borderRadius: 14,
    alignItems: 'center',
    justifyContent: 'center',
  },
});
