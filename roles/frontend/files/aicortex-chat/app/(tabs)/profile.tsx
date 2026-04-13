import React, { useState } from 'react';
import {
  Alert,
  SectionList,
  StyleSheet,
  Text,
  TextInput,
  View,
  Pressable,
} from 'react-native';
import { useRouter } from 'expo-router';
import { LinearGradient } from 'expo-linear-gradient';
import { MaterialIcons } from '@expo/vector-icons';

import Colors from '@/constants/Colors';
import { useColorScheme } from '@/components/useColorScheme';
import { useConversations } from '@/hooks/useConversations';
import { useAgents } from '@/hooks/useAgents';
import { getVoiceKey } from '@/services/api';
import { useOnboarding } from '@/hooks/useOnboarding';
import { useAuth } from '@/hooks/useAuth';
import { spacing, borderRadius, fontSize, fontWeight as fw } from '@/constants/designTokens';

function groupByDate(conversations: any[]) {
  const now = Date.now();
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const todayMs = today.getTime();
  const yesterdayMs = todayMs - 86400000;
  const weekMs = todayMs - 7 * 86400000;

  const sections: { title: string; data: any[] }[] = [
    { title: 'TODAY', data: [] },
    { title: 'YESTERDAY', data: [] },
    { title: 'PREVIOUS 7 DAYS', data: [] },
    { title: 'OLDER', data: [] },
  ];

  conversations.forEach((conv: any) => {
    const ts = conv.lastMessageAt || conv.createdAt;
    if (ts >= todayMs) sections[0].data.push(conv);
    else if (ts >= yesterdayMs) sections[1].data.push(conv);
    else if (ts >= weekMs) sections[2].data.push(conv);
    else sections[3].data.push(conv);
  });

  return sections.filter((s) => s.data.length > 0);
}

function formatTimeAgo(timestamp: number) {
  const diff = Date.now() - timestamp;
  const hours = Math.floor(diff / 3600000);
  const mins = Math.floor(diff / 60000);
  if (mins < 60) return `${mins}M AGO`;
  if (hours < 24) return `${hours}H AGO`;
  const days = Math.floor(hours / 24);
  return `${days}D AGO`;
}

export default function ProfileScreen() {
  const colorScheme = useColorScheme();
  const colors = Colors[colorScheme];
  const router = useRouter();
  const { conversations } = useConversations();
  const { getAgent } = useAgents();
  const { resetOnboarding } = useOnboarding();
  const { isAuthenticated, user, logout, saveVoiceKey } = useAuth();
  const [voiceKeyInput, setVoiceKeyInput] = useState('');
  const [voiceKeySaved, setVoiceKeySaved] = useState(!!getVoiceKey());

  const sections = groupByDate(
    [...conversations].sort(
      (a, b) => (b.lastMessageAt || b.createdAt) - (a.lastMessageAt || a.createdAt)
    )
  );

  const getIconForConv = (conv: any): keyof typeof MaterialIcons.glyphMap => {
    const agent = getAgent(conv.agentId ?? conv.expertId);
    if (!agent) return 'chat';
    const sp = agent.description.toLowerCase();
    if (sp.includes('code') || sp.includes('engineer')) return 'code';
    if (sp.includes('design') || sp.includes('ux')) return 'brush';
    if (sp.includes('data') || sp.includes('analyt')) return 'bar-chart';
    if (sp.includes('writing') || sp.includes('commun')) return 'edit';
    if (sp.includes('finance') || sp.includes('invest')) return 'account-balance';
    return 'chat';
  };

  return (
    <View style={[styles.container, { backgroundColor: colors.background }]}>
      {/* Header */}
      <View style={styles.header}>
        <View style={styles.headerRow}>
          <View>
            <Text style={[styles.title, { color: colors.text }]}>History</Text>
            <Text style={[styles.subtitle, { color: colors.onSurfaceVariant }]}>
              Review your recent neural activities.
            </Text>
          </View>
          <LinearGradient
            colors={['#0084FF', '#00C6FF']}
            style={styles.headerLogo}>
            <Text style={styles.headerLogoText}>A</Text>
          </LinearGradient>
        </View>
      </View>

      <SectionList
        sections={sections}
        keyExtractor={(item) => item.id}
        contentContainerStyle={styles.listContent}
        renderSectionHeader={({ section }) => (
          <Text style={[styles.sectionHeader, { color: colors.outline }]}>
            {section.title}
          </Text>
        )}
        renderItem={({ item }) => {
          const agent = getAgent(item.agentId ?? item.expertId);
          const iconName = getIconForConv(item);
          return (
            <Pressable
              onPress={() => router.push(`/chat/${item.id}` as any)}
              style={({ pressed }) => [
                styles.historyItem,
                {
                  backgroundColor: colors.cardBackground,
                  opacity: pressed ? 0.8 : 1,
                },
              ]}>
              <View
                style={[
                  styles.historyIcon,
                  { backgroundColor: colors.surfaceHigh },
                ]}>
                <MaterialIcons
                  name={iconName}
                  size={20}
                  color={colors.tint}
                />
              </View>
              <View style={styles.historyInfo}>
                <Text
                  style={[styles.historyTitle, { color: colors.text }]}
                  numberOfLines={1}>
                  {item.title || 'New conversation'}
                </Text>
                <Text
                  style={[
                    styles.historySubtitle,
                    { color: colors.onSurfaceVariant },
                  ]}
                  numberOfLines={1}>
                  {agent?.description ?? 'AI Assistant'}
                </Text>
              </View>
              <View style={styles.historyMeta}>
                <Text style={[styles.timeAgo, { color: colors.outline }]}>
                  {formatTimeAgo(item.lastMessageAt || item.createdAt)}
                </Text>
                {agent && (
                  <View
                    style={[
                      styles.modelTag,
                      { backgroundColor: colors.surfaceHigh },
                    ]}>
                    <Text
                      style={[
                        styles.modelTagText,
                        { color: colors.onSurfaceVariant },
                      ]}>
                      {agent.name.toUpperCase().slice(0, 10)}
                    </Text>
                  </View>
                )}
              </View>
            </Pressable>
          );
        }}
        ListEmptyComponent={
          <View style={styles.emptyState}>
            <MaterialIcons
              name="history"
              size={64}
              color={colors.outlineVariant}
            />
            <Text style={[styles.emptyText, { color: colors.outline }]}>
              No activity yet
            </Text>
            <Text
              style={[styles.emptySubtext, { color: colors.outlineVariant }]}>
              Your conversations will appear here
            </Text>
          </View>
        }
      />

      {/* Server Connection */}
      <View style={styles.bottomActions}>
        {isAuthenticated ? (
          <View style={[styles.connectionCard, { backgroundColor: colors.cardBackground }]}>
            <View style={styles.connectionInfo}>
              <View style={[styles.statusDot, { backgroundColor: colors.statusOnline }]} />
              <View>
                <Text style={[styles.connectionName, { color: colors.text }]}>
                  {user?.name ?? 'Connected'}
                </Text>
                <Text style={[styles.connectionServer, { color: colors.secondaryText }]}>
                  chat.aicortex.cloud
                </Text>
              </View>
            </View>
            <Pressable
              onPress={logout}
              style={({ pressed }) => [
                styles.disconnectButton,
                { opacity: pressed ? 0.7 : 1 },
              ]}>
              <Text style={[styles.disconnectText, { color: colors.error }]}>
                Disconnect
              </Text>
            </Pressable>
          </View>
        ) : (
          <Pressable
            onPress={() => router.push('/login' as any)}
            style={({ pressed }) => [
              styles.connectButton,
              { backgroundColor: colors.tint, opacity: pressed ? 0.8 : 1 },
            ]}>
            <MaterialIcons name="link" size={20} color="#fff" />
            <Text style={styles.connectText}>Connect to Server</Text>
          </Pressable>
        )}

        {/* Voice Key */}
        {isAuthenticated && (
          <View style={[styles.voiceKeyCard, { backgroundColor: colors.cardBackground }]}>
            <View style={styles.voiceKeyHeader}>
              <MaterialIcons name="mic" size={18} color={voiceKeySaved ? colors.statusOnline : colors.secondaryText} />
              <Text style={[styles.voiceKeyTitle, { color: colors.text }]}>
                Voice Key {voiceKeySaved ? '(Active)' : ''}
              </Text>
            </View>
            {!voiceKeySaved ? (
              <>
                <TextInput
                  value={voiceKeyInput}
                  onChangeText={setVoiceKeyInput}
                  placeholder="sk-..."
                  placeholderTextColor={colors.secondaryText}
                  style={[styles.voiceKeyInput, { color: colors.text, backgroundColor: colors.surfaceLow, borderColor: colors.glassBorder }]}
                  autoCapitalize="none"
                  autoCorrect={false}
                />
                <Pressable
                  onPress={async () => {
                    if (!voiceKeyInput.trim()) return;
                    await saveVoiceKey(voiceKeyInput.trim());
                    setVoiceKeySaved(true);
                    setVoiceKeyInput('');
                  }}
                  style={[styles.voiceKeySaveBtn, { backgroundColor: colors.tint }]}>
                  <Text style={styles.voiceKeySaveText}>Save Voice Key</Text>
                </Pressable>
              </>
            ) : (
              <Pressable onPress={() => setVoiceKeySaved(false)}>
                <Text style={[styles.voiceKeyChange, { color: colors.tint }]}>Change key</Text>
              </Pressable>
            )}
          </View>
        )}

        {/* Pipeline */}
        {isAuthenticated && (
          <Pressable
            onPress={() => router.push('/pipeline' as any)}
            style={({ pressed }) => [
              styles.pipelineButton,
              { backgroundColor: colors.cardBackground, opacity: pressed ? 0.7 : 1 },
            ]}>
            <MaterialIcons name="auto-awesome" size={20} color={colors.tint} />
            <Text style={[styles.pipelineText, { color: colors.tint }]}>
              Analyze Chat History
            </Text>
          </Pressable>
        )}

        {/* Dev: Reset Onboarding */}
        <Pressable
          onPress={async () => {
            await resetOnboarding();
            router.replace('/onboarding' as any);
          }}
          style={({ pressed }) => [
            styles.resetButton,
            { backgroundColor: colors.surfaceHigh, opacity: pressed ? 0.7 : 1 },
          ]}>
          <MaterialIcons name="restart-alt" size={20} color={colors.error ?? '#FF453A'} />
          <Text style={[styles.resetText, { color: colors.error ?? '#FF453A' }]}>
            Reset Onboarding
          </Text>
        </Pressable>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1 },
  header: {
    paddingHorizontal: spacing.xl,
    paddingTop: 60,
    paddingBottom: spacing.lg,
  },
  headerRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'flex-start',
  },
  title: {
    fontSize: fontSize['2xl'],
    fontWeight: '700',
  },
  subtitle: {
    fontSize: fontSize.md,
    marginTop: spacing.xs,
  },
  headerLogo: {
    width: 36,
    height: 36,
    borderRadius: 10,
    alignItems: 'center',
    justifyContent: 'center',
  },
  headerLogoText: {
    color: '#fff',
    fontSize: 18,
    fontWeight: '800',
  },
  listContent: {
    paddingHorizontal: spacing.xl,
    paddingBottom: 100,
  },
  sectionHeader: {
    fontSize: fontSize.xs,
    fontWeight: '700',
    letterSpacing: 2,
    marginTop: spacing.xl,
    marginBottom: spacing.md,
  },
  historyItem: {
    flexDirection: 'row',
    alignItems: 'center',
    borderRadius: borderRadius.md,
    padding: spacing.lg,
    marginBottom: spacing.sm,
  },
  historyIcon: {
    width: 40,
    height: 40,
    borderRadius: borderRadius.sm,
    alignItems: 'center',
    justifyContent: 'center',
    marginRight: spacing.md,
  },
  historyInfo: {
    flex: 1,
  },
  historyTitle: {
    fontSize: fontSize.md,
    fontWeight: '600',
  },
  historySubtitle: {
    fontSize: fontSize.sm,
    marginTop: 2,
  },
  historyMeta: {
    alignItems: 'flex-end',
    gap: spacing.xs,
  },
  timeAgo: {
    fontSize: fontSize.xs,
    fontWeight: '500',
  },
  modelTag: {
    paddingHorizontal: spacing.sm,
    paddingVertical: 2,
    borderRadius: borderRadius.sm,
  },
  modelTagText: {
    fontSize: 8,
    fontWeight: '700',
    letterSpacing: 0.5,
  },
  emptyState: {
    alignItems: 'center',
    justifyContent: 'center',
    paddingTop: 80,
  },
  emptyText: {
    fontSize: fontSize.lg,
    fontWeight: '600',
    marginTop: spacing.lg,
  },
  emptySubtext: {
    fontSize: fontSize.md,
    marginTop: spacing.sm,
  },
  bottomActions: {
    paddingHorizontal: spacing.xl,
    paddingBottom: 100,
    gap: spacing.sm,
  },
  connectionCard: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    padding: spacing.lg,
    borderRadius: borderRadius.lg,
  },
  connectionInfo: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.md,
  },
  statusDot: {
    width: 10,
    height: 10,
    borderRadius: 5,
  },
  connectionName: {
    fontSize: fontSize.base,
    fontWeight: fw.semibold,
  },
  connectionServer: {
    fontSize: fontSize.sm,
    marginTop: 1,
  },
  disconnectButton: {
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.xs,
  },
  disconnectText: {
    fontSize: fontSize.base,
    fontWeight: fw.medium,
  },
  connectButton: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: spacing.sm,
    paddingVertical: spacing.lg,
    borderRadius: borderRadius.lg,
  },
  connectText: {
    color: '#fff',
    fontSize: fontSize.base,
    fontWeight: fw.semibold,
  },
  voiceKeyCard: {
    padding: spacing.lg,
    borderRadius: borderRadius.md,
    gap: spacing.sm,
  },
  voiceKeyHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
  },
  voiceKeyTitle: {
    fontSize: fontSize.md,
    fontWeight: fw.semibold,
  },
  voiceKeyInput: {
    borderWidth: 0.5,
    borderRadius: borderRadius.sm,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
    fontSize: fontSize.base,
  },
  voiceKeySaveBtn: {
    alignItems: 'center',
    paddingVertical: spacing.sm,
    borderRadius: borderRadius.full,
  },
  voiceKeySaveText: {
    color: '#fff',
    fontWeight: '600',
    fontSize: fontSize.sm,
  },
  voiceKeyChange: {
    fontSize: fontSize.sm,
    fontWeight: '600',
  },
  pipelineButton: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: spacing.sm,
    paddingVertical: spacing.lg,
    borderRadius: borderRadius.md,
  },
  pipelineText: {
    fontSize: fontSize.md,
    fontWeight: '600',
  },
  resetButton: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: spacing.sm,
    paddingVertical: spacing.lg,
    borderRadius: borderRadius.md,
  },
  resetText: {
    fontSize: fontSize.md,
    fontWeight: '600',
  },
});
