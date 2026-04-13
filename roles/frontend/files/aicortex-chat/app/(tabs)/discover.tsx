import React, { useEffect, useState } from 'react';
import {
  FlatList,
  Pressable,
  StyleSheet,
  Text,
  View,
  ActivityIndicator,
} from 'react-native';
import { useRouter } from 'expo-router';
import { MaterialIcons } from '@expo/vector-icons';

import Colors from '@/constants/Colors';
import { useColorScheme } from '@/components/useColorScheme';
import {
  CATEGORIES,
  UNCATEGORIZED,
  categorizeChat,
  type Category,
} from '@/constants/categories';
import { getChats, getToken, type ChatMeta } from '@/services/api';
import { useAuth } from '@/hooks/useAuth';
import {
  spacing,
  borderRadius,
  fontSize,
  fontWeight as fw,
  letterSpacing,
} from '@/constants/designTokens';

interface CategoryWithCount extends Category {
  chatCount: number;
  recentChat?: string;
}

export default function ProjectsScreen() {
  const colorScheme = useColorScheme();
  const colors = Colors[colorScheme];
  const router = useRouter();

  const { isAuthenticated } = useAuth();
  const [categories, setCategories] = useState<CategoryWithCount[]>([]);
  const [loading, setLoading] = useState(true);

  // Re-fetch when auth state changes (token restored from AsyncStorage)
  useEffect(() => {
    loadAndCategorize();
  }, [isAuthenticated]);

  async function loadAndCategorize() {
    if (!getToken()) {
      // Show categories with zero counts
      setCategories(
        CATEGORIES.map((c) => ({ ...c, chatCount: 0 })),
      );
      setLoading(false);
      return;
    }

    try {
      const allChats = await getChats();

      // Count chats per category
      const counts = new Map<string, { count: number; recent?: string }>();
      for (const chat of allChats) {
        const cat = categorizeChat(chat.title);
        const existing = counts.get(cat.id);
        if (existing) {
          existing.count++;
        } else {
          counts.set(cat.id, { count: 1, recent: chat.title });
        }
      }

      // Build sorted category list (non-empty first, then by count)
      const result: CategoryWithCount[] = CATEGORIES.map((cat) => {
        const data = counts.get(cat.id);
        return {
          ...cat,
          chatCount: data?.count ?? 0,
          recentChat: data?.recent,
        };
      });

      // Add uncategorized if any
      const uncatData = counts.get('general');
      if (uncatData) {
        result.push({
          ...UNCATEGORIZED,
          chatCount: uncatData.count,
          recentChat: uncatData.recent,
        });
      }

      // Sort: categories with chats first, then by count descending
      result.sort((a, b) => {
        if (a.chatCount > 0 && b.chatCount === 0) return -1;
        if (a.chatCount === 0 && b.chatCount > 0) return 1;
        return b.chatCount - a.chatCount;
      });

      setCategories(result);
    } catch {
      setCategories(CATEGORIES.map((c) => ({ ...c, chatCount: 0 })));
    } finally {
      setLoading(false);
    }
  }

  return (
    <View style={[styles.container, { backgroundColor: colors.background }]}>
      {/* Header */}
      <View style={styles.header}>
        <Text style={[styles.title, { color: colors.text }]}>Projects</Text>
        <Text style={[styles.subtitle, { color: colors.secondaryText }]}>
          Your conversations organized by topic
        </Text>
      </View>

      {loading ? (
        <View style={styles.centered}>
          <ActivityIndicator color={colors.tint} />
          <Text style={[styles.loadingText, { color: colors.secondaryText }]}>
            Analyzing your chats...
          </Text>
        </View>
      ) : (
        <FlatList
          data={categories}
          keyExtractor={(item) => item.id}
          contentContainerStyle={styles.listContent}
          renderItem={({ item }) => (
            <Pressable
              onPress={() => router.push(`/category/${item.id}` as any)}
              style={({ pressed }) => [
                styles.categoryCard,
                {
                  backgroundColor: colors.cardBackground,
                  borderColor: colors.glassBorder,
                  opacity: pressed ? 0.8 : 1,
                },
              ]}>
              <View style={styles.cardRow}>
                <View
                  style={[
                    styles.iconCircle,
                    { backgroundColor: item.color + '18' },
                  ]}>
                  <MaterialIcons
                    name={item.icon}
                    size={22}
                    color={item.color}
                  />
                </View>
                <View style={styles.cardInfo}>
                  <Text
                    style={[styles.categoryName, { color: colors.text }]}
                    numberOfLines={1}>
                    {item.label}
                  </Text>
                  {item.chatCount > 0 ? (
                    <Text
                      style={[
                        styles.recentChat,
                        { color: colors.secondaryText },
                      ]}
                      numberOfLines={1}>
                      {item.recentChat}
                    </Text>
                  ) : (
                    <Text
                      style={[
                        styles.recentChat,
                        { color: colors.tertiaryText },
                      ]}>
                      No chats yet
                    </Text>
                  )}
                </View>
                <View style={styles.cardRight}>
                  {item.chatCount > 0 && (
                    <View
                      style={[
                        styles.countBadge,
                        { backgroundColor: item.color + '20' },
                      ]}>
                      <Text
                        style={[styles.countText, { color: item.color }]}>
                        {item.chatCount}
                      </Text>
                    </View>
                  )}
                  <MaterialIcons
                    name="chevron-right"
                    size={18}
                    color={colors.secondaryText}
                  />
                </View>
              </View>
            </Pressable>
          )}
        />
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1 },
  header: {
    paddingHorizontal: spacing.lg,
    paddingTop: 56,
    paddingBottom: spacing.md,
  },
  title: {
    fontSize: fontSize.largeTitle,
    fontWeight: fw.bold,
    letterSpacing: letterSpacing.tight,
  },
  subtitle: {
    fontSize: fontSize.subheadline,
    marginTop: spacing.xs,
    letterSpacing: letterSpacing.normal,
  },

  // Loading
  centered: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
    gap: spacing.md,
  },
  loadingText: {
    fontSize: fontSize.subheadline,
  },

  // List
  listContent: {
    paddingHorizontal: spacing.lg,
    paddingBottom: 100,
  },
  categoryCard: {
    borderRadius: borderRadius.card,
    borderWidth: 0.5,
    padding: spacing.lg,
    marginBottom: spacing.sm,
  },
  cardRow: {
    flexDirection: 'row',
    alignItems: 'center',
  },
  iconCircle: {
    width: 40,
    height: 40,
    borderRadius: 12,
    alignItems: 'center',
    justifyContent: 'center',
    marginRight: spacing.md,
  },
  cardInfo: {
    flex: 1,
  },
  categoryName: {
    fontSize: fontSize.body,
    fontWeight: fw.semibold,
    letterSpacing: letterSpacing.tight,
    marginBottom: 2,
  },
  recentChat: {
    fontSize: fontSize.footnote,
  },
  cardRight: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
  },
  countBadge: {
    paddingHorizontal: spacing.sm,
    paddingVertical: 2,
    borderRadius: borderRadius.badge,
    minWidth: 24,
    alignItems: 'center',
  },
  countText: {
    fontSize: fontSize.caption1,
    fontWeight: fw.semibold,
  },
});
