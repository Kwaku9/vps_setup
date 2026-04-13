import React, { useMemo, useState } from 'react';
import {
  FlatList,
  Pressable,
  RefreshControl,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  View,
} from 'react-native';
import { useRouter } from 'expo-router';
import { LinearGradient } from 'expo-linear-gradient';
import { MaterialIcons } from '@expo/vector-icons';

import Colors from '@/constants/Colors';
import { useColorScheme } from '@/components/useColorScheme';
import { useAgents } from '@/hooks/useAgents';
import {
  spacing,
  borderRadius,
  fontSize,
  fontWeight as fw,
  letterSpacing,
} from '@/constants/designTokens';

export default function AgentsScreen() {
  const colorScheme = useColorScheme();
  const colors = Colors[colorScheme];
  const router = useRouter();
  const { agents, isRefreshing, connectivity, refresh } = useAgents();
  const [selectedTag, setSelectedTag] = useState('All');
  const [searchQuery, setSearchQuery] = useState('');

  // Derive unique tags from all agents for filter chips
  const allTags = useMemo(() => {
    const tags = new Set<string>();
    agents.forEach((a) => a.tags.forEach((t) => tags.add(t)));
    return ['All', ...Array.from(tags).slice(0, 8)];
  }, [agents]);

  const filteredAgents = useMemo(() => {
    const query = searchQuery.toLowerCase();
    return agents.filter((agent) => {
      const matchesSearch =
        !query ||
        agent.name.toLowerCase().includes(query) ||
        agent.description.toLowerCase().includes(query) ||
        agent.baseModelName.toLowerCase().includes(query) ||
        agent.baseModelId.toLowerCase().includes(query) ||
        agent.tags.some((t) => t.toLowerCase().includes(query));

      const matchesTag =
        selectedTag === 'All' ||
        agent.tags.some(
          (t) => t.toLowerCase() === selectedTag.toLowerCase(),
        );

      return matchesSearch && matchesTag;
    });
  }, [agents, searchQuery, selectedTag]);

  return (
    <View style={[styles.container, { backgroundColor: colors.background }]}>
      {/* Header */}
      <View style={styles.header}>
        <View style={styles.headerTop}>
          <View style={styles.logoRow}>
            <LinearGradient
              colors={[colors.tint, '#00C6FF']}
              style={styles.logoIcon}>
              <Text style={styles.logoText}>A</Text>
            </LinearGradient>
            <Text style={[styles.logoTitle, { color: colors.tint }]}>
              AICORTEX
            </Text>
          </View>
          <Pressable hitSlop={12}>
            <MaterialIcons name="settings" size={22} color={colors.secondaryText} />
          </Pressable>
        </View>
        <Text style={[styles.subtitle, { color: colors.secondaryText }]}>
          Connect with your skilled agents.
        </Text>
      </View>

      {/* Offline Banner */}
      {connectivity === 'offline' && (
        <View style={[styles.offlineBanner, { backgroundColor: colors.systemOrange + '20' }]}>
          <MaterialIcons name="cloud-off" size={14} color={colors.systemOrange} />
          <Text style={[styles.offlineText, { color: colors.systemOrange }]}>
            Showing cached agents — server unreachable
          </Text>
        </View>
      )}

      {/* Search Bar */}
      <View
        style={[
          styles.searchContainer,
          {
            backgroundColor: colors.inputBackground,
            borderColor: colors.glassBorder,
          },
        ]}>
        <MaterialIcons
          name="search"
          size={18}
          color={colors.secondaryText}
          style={styles.searchIcon}
        />
        <TextInput
          placeholder="Search agents..."
          placeholderTextColor={colors.secondaryText}
          style={[styles.searchInput, { color: colors.text }]}
          value={searchQuery}
          onChangeText={setSearchQuery}
        />
      </View>

      {/* Tag Filter Chips */}
      <ScrollView
        horizontal
        showsHorizontalScrollIndicator={false}
        contentContainerStyle={styles.chipsContainer}>
        {allTags.map((tag) => (
          <Pressable
            key={tag}
            onPress={() => setSelectedTag(tag)}
            style={[
              styles.chip,
              {
                backgroundColor:
                  selectedTag === tag ? colors.tint : colors.surfaceHigh,
              },
            ]}>
            <Text
              style={[
                styles.chipText,
                {
                  color: selectedTag === tag ? '#fff' : colors.secondaryText,
                },
              ]}>
              {tag}
            </Text>
          </Pressable>
        ))}
      </ScrollView>

      {/* Agent List */}
      <FlatList
        data={filteredAgents}
        keyExtractor={(item) => item.id}
        contentContainerStyle={styles.listContent}
        refreshControl={
          <RefreshControl
            refreshing={isRefreshing}
            onRefresh={refresh}
            tintColor={colors.tint}
          />
        }
        ListEmptyComponent={
          <View style={styles.emptyState}>
            <MaterialIcons name="smart-toy" size={48} color={colors.outline} />
            <Text style={[styles.emptyTitle, { color: colors.text }]}>
              {agents.length === 0 ? 'No agents yet' : 'No matches'}
            </Text>
            <Text style={[styles.emptySubtitle, { color: colors.secondaryText }]}>
              {agents.length === 0
                ? 'Complete onboarding or tap + to create your first agent'
                : 'Try a different search or filter'}
            </Text>
          </View>
        }
        renderItem={({ item }) => {
          const statusColor =
            item.status === 'online' ? colors.statusOnline : colors.statusOffline;
          return (
            <Pressable
              onPress={() => router.push(`/agent/${item.id}` as any)}
              style={({ pressed }) => [
                styles.agentCard,
                {
                  backgroundColor: colors.cardBackground,
                  borderColor: colors.glassBorder,
                  opacity: pressed ? 0.8 : 1,
                },
              ]}>
              <View style={styles.cardRow}>
                {/* Avatar with status dot */}
                <View style={styles.avatarContainer}>
                  <LinearGradient
                    colors={item.gradientColors}
                    style={styles.avatar}>
                    <Text style={styles.avatarText}>{item.initials}</Text>
                  </LinearGradient>
                  <View
                    style={[
                      styles.statusDot,
                      {
                        backgroundColor: statusColor,
                        borderColor: colors.cardBackground,
                      },
                    ]}
                  />
                </View>

                {/* Info */}
                <View style={styles.cardInfo}>
                  <View style={styles.nameRow}>
                    <Text
                      style={[styles.agentName, { color: colors.text }]}
                      numberOfLines={1}>
                      {item.name}
                    </Text>
                    <Text
                      style={[styles.modelText, { color: colors.secondaryText }]}>
                      {item.baseModelName}
                    </Text>
                  </View>
                  <Text
                    style={[styles.descText, { color: colors.secondaryText }]}
                    numberOfLines={1}>
                    {item.description || 'AI Agent'}
                  </Text>
                  {/* Tags */}
                  <View style={styles.tagsRow}>
                    {item.tags.slice(0, 3).map((tag, i) => (
                      <View
                        key={i}
                        style={[
                          styles.tagChip,
                          { backgroundColor: colors.surfaceHigh },
                        ]}>
                        <Text style={[styles.tagText, { color: colors.tint }]}>
                          #{tag}
                        </Text>
                      </View>
                    ))}
                  </View>
                </View>

                <MaterialIcons
                  name="chevron-right"
                  size={20}
                  color={colors.secondaryText}
                />
              </View>
            </Pressable>
          );
        }}
      />

      {/* FAB — Create Agent */}
      <Pressable
        style={[styles.fab, { backgroundColor: colors.tint }]}
        onPress={() => router.push('/agent/new' as any)}>
        <MaterialIcons name="add" size={24} color="#fff" />
      </Pressable>
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1 },
  header: {
    paddingHorizontal: spacing.lg,
    paddingTop: 56,
    paddingBottom: spacing.sm,
  },
  headerTop: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: spacing.xs,
  },
  logoRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
  },
  logoIcon: {
    width: 28,
    height: 28,
    borderRadius: 7,
    alignItems: 'center',
    justifyContent: 'center',
  },
  logoText: {
    color: '#fff',
    fontSize: 14,
    fontWeight: fw.extrabold,
  },
  logoTitle: {
    fontSize: fontSize.title3,
    fontWeight: fw.extrabold,
    letterSpacing: 2,
  },
  subtitle: {
    fontSize: fontSize.footnote,
    letterSpacing: letterSpacing.wide,
  },

  // Offline
  offlineBanner: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
    marginHorizontal: spacing.lg,
    marginBottom: spacing.sm,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.xs,
    borderRadius: borderRadius.badge,
  },
  offlineText: {
    fontSize: fontSize.caption2,
    fontWeight: fw.semibold,
  },

  // Search
  searchContainer: {
    flexDirection: 'row',
    alignItems: 'center',
    marginHorizontal: spacing.lg,
    borderRadius: borderRadius.input,
    borderWidth: 0.5,
    paddingHorizontal: spacing.md,
    height: 36,
    marginBottom: spacing.sm,
  },
  searchIcon: { marginRight: spacing.sm },
  searchInput: {
    flex: 1,
    fontSize: fontSize.subheadline,
    letterSpacing: letterSpacing.normal,
  },

  // Chips
  chipsContainer: {
    paddingHorizontal: spacing.lg,
    paddingBottom: spacing.sm,
    gap: spacing.xs,
  },
  chip: {
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.xs,
    borderRadius: borderRadius.badge,
    height: 28,
    justifyContent: 'center',
  },
  chipText: {
    fontSize: fontSize.caption1,
    fontWeight: fw.semibold,
    letterSpacing: 0.3,
  },

  // List
  listContent: {
    paddingHorizontal: spacing.lg,
    paddingBottom: 100,
  },
  agentCard: {
    borderRadius: borderRadius.card,
    borderWidth: 0.5,
    padding: spacing.md,
    marginBottom: spacing.sm,
  },
  cardRow: {
    flexDirection: 'row',
    alignItems: 'center',
  },
  avatarContainer: {
    position: 'relative',
    marginRight: spacing.md,
  },
  avatar: {
    width: 44,
    height: 44,
    borderRadius: 22,
    alignItems: 'center',
    justifyContent: 'center',
  },
  avatarText: {
    color: '#fff',
    fontSize: 14,
    fontWeight: fw.bold,
  },
  statusDot: {
    position: 'absolute',
    bottom: 0,
    right: 0,
    width: 12,
    height: 12,
    borderRadius: 6,
    borderWidth: 2,
  },
  cardInfo: {
    flex: 1,
  },
  nameRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: 1,
  },
  agentName: {
    fontSize: fontSize.body,
    fontWeight: fw.semibold,
    letterSpacing: letterSpacing.tight,
    flex: 1,
  },
  modelText: {
    fontSize: fontSize.caption2,
    marginLeft: spacing.sm,
  },
  descText: {
    fontSize: fontSize.footnote,
    marginBottom: spacing.xs,
  },
  tagsRow: {
    flexDirection: 'row',
    gap: spacing.xs,
  },
  tagChip: {
    paddingHorizontal: spacing.sm,
    paddingVertical: 2,
    borderRadius: borderRadius.badge,
  },
  tagText: {
    fontSize: fontSize.caption2,
    fontWeight: fw.semibold,
    letterSpacing: 0.3,
  },

  // Empty state
  emptyState: {
    alignItems: 'center',
    justifyContent: 'center',
    paddingTop: 80,
    gap: spacing.sm,
  },
  emptyTitle: {
    fontSize: fontSize.title3,
    fontWeight: fw.bold,
  },
  emptySubtitle: {
    fontSize: fontSize.subheadline,
    textAlign: 'center',
    paddingHorizontal: spacing.xl,
  },

  // FAB
  fab: {
    position: 'absolute',
    bottom: 96,
    right: 20,
    width: 50,
    height: 50,
    borderRadius: 25,
    alignItems: 'center',
    justifyContent: 'center',
    elevation: 4,
    shadowColor: '#000',
    shadowOffset: { width: 0, height: 2 },
    shadowOpacity: 0.25,
    shadowRadius: 4,
  },
});
