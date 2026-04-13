import React, { useCallback, useEffect, useRef, useState } from 'react';
import {
  Animated,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  View,
} from 'react-native';
import { useRouter } from 'expo-router';
import { LinearGradient } from 'expo-linear-gradient';
import { MaterialIcons } from '@expo/vector-icons';

import Colors from '@/constants/Colors';
import { useColorScheme } from '@/components/useColorScheme';
import { useAuth } from '@/hooks/useAuth';
import {
  runPipeline,
  type PipelineProgress,
  type PipelineResult,
} from '@/services/chatHistoryPipeline';
import { generateGradient, generateInitials } from '@/services/agentMapper';
import {
  spacing,
  borderRadius,
  fontSize,
  fontWeight as fw,
} from '@/constants/designTokens';

type Status = 'idle' | 'running' | 'complete' | 'error';

const PHASE_ICONS: Record<number, keyof typeof MaterialIcons.glyphMap> = {
  1: 'psychology',
  2: 'account-tree',
  3: 'smart-toy',
  4: 'rocket-launch',
};

const PHASE_LABELS = [
  '',
  'Analyzing Conversations',
  'Discovering Projects',
  'Mapping Agents',
  'Setting Up Workspace',
];

export default function PipelineScreen() {
  const colorScheme = useColorScheme();
  const colors = Colors[colorScheme];
  const router = useRouter();
  const { isAuthenticated, isLoading: authLoading } = useAuth();

  const [status, setStatus] = useState<Status>('idle');
  const [progress, setProgress] = useState<PipelineProgress>({
    phase: 0,
    phaseName: '',
    detail: '',
    percent: 0,
  });
  const [result, setResult] = useState<PipelineResult | null>(null);
  const [errorMsg, setErrorMsg] = useState('');

  const progressAnim = useRef(new Animated.Value(0)).current;
  const fadeAnim = useRef(new Animated.Value(0)).current;

  useEffect(() => {
    Animated.timing(fadeAnim, {
      toValue: 1,
      duration: 500,
      useNativeDriver: true,
    }).start();
  }, []);

  useEffect(() => {
    Animated.timing(progressAnim, {
      toValue: progress.percent / 100,
      duration: 300,
      useNativeDriver: false,
    }).start();
  }, [progress.percent]);

  const handleStart = useCallback(async () => {
    setStatus('running');
    setErrorMsg('');

    try {
      const pipelineResult = await runPipeline((p) => {
        setProgress(p);
      });
      setResult(pipelineResult);
      setStatus('complete');
    } catch (err) {
      setErrorMsg(err instanceof Error ? err.message : 'Pipeline failed');
      setStatus('error');
    }
  }, []);

  const progressWidth = progressAnim.interpolate({
    inputRange: [0, 1],
    outputRange: ['0%', '100%'],
  });

  return (
    <View style={[styles.container, { backgroundColor: colors.background }]}>
      {/* Header */}
      <View style={styles.header}>
        <Pressable onPress={() => router.back()} style={styles.backBtn}>
          <MaterialIcons name="arrow-back" size={24} color={colors.tint} />
        </Pressable>
        <Text style={[styles.headerTitle, { color: colors.text }]}>
          Chat Intelligence
        </Text>
        <View style={{ width: 40 }} />
      </View>

      <Animated.View style={[styles.content, { opacity: fadeAnim }]}>
        <ScrollView
          contentContainerStyle={styles.scrollContent}
          showsVerticalScrollIndicator={false}>

          {/* ── Idle State ───────────────────────────── */}
          {status === 'idle' && (
            <View style={styles.idleContainer}>
              <LinearGradient
                colors={[colors.tint + '30', colors.tint + '05']}
                style={styles.idleGlow}>
                <MaterialIcons name="auto-awesome" size={64} color={colors.tint} />
              </LinearGradient>
              <Text style={[styles.idleTitle, { color: colors.text }]}>
                Analyze Your Chat History
              </Text>
              <Text style={[styles.idleDesc, { color: colors.secondaryText }]}>
                We'll analyze your conversations to discover projects, organize them into
                folders, and recommend specialized AI agents tailored to your work.
              </Text>

              <View style={styles.idleSteps}>
                {[1, 2, 3, 4].map((phase) => (
                  <View key={phase} style={[styles.stepRow, { borderColor: colors.glassBorder }]}>
                    <View style={[styles.stepIcon, { backgroundColor: colors.tint + '15' }]}>
                      <MaterialIcons
                        name={PHASE_ICONS[phase]}
                        size={20}
                        color={colors.tint}
                      />
                    </View>
                    <View style={styles.stepInfo}>
                      <Text style={[styles.stepTitle, { color: colors.text }]}>
                        {PHASE_LABELS[phase]}
                      </Text>
                    </View>
                  </View>
                ))}
              </View>

              {!isAuthenticated && !authLoading && (
                <View style={[styles.authWarning, { backgroundColor: colors.systemOrange + '15' }]}>
                  <MaterialIcons name="warning" size={18} color={colors.systemOrange} />
                  <Text style={[styles.authWarningText, { color: colors.systemOrange }]}>
                    Connect to server first (Profile → Connect)
                  </Text>
                </View>
              )}

              <Pressable
                onPress={handleStart}
                disabled={!isAuthenticated || authLoading}
                style={({ pressed }) => [
                  styles.startBtn,
                  {
                    backgroundColor: colors.tint,
                    opacity: !isAuthenticated || authLoading ? 0.4 : pressed ? 0.85 : 1,
                  },
                ]}>
                <MaterialIcons name="play-arrow" size={22} color="#fff" />
                <Text style={styles.startText}>
                  {authLoading ? 'CONNECTING...' : 'START ANALYSIS'}
                </Text>
              </Pressable>
            </View>
          )}

          {/* ── Running State ────────────────────────── */}
          {status === 'running' && (
            <View style={styles.runningContainer}>
              <View style={[styles.phaseCard, { backgroundColor: colors.cardBackground, borderColor: colors.glassBorder }]}>
                <MaterialIcons
                  name={PHASE_ICONS[progress.phase] ?? 'hourglass-empty'}
                  size={32}
                  color={colors.tint}
                />
                <Text style={[styles.phaseName, { color: colors.text }]}>
                  {progress.phaseName || 'Starting...'}
                </Text>
                <Text style={[styles.phaseDetail, { color: colors.secondaryText }]}>
                  {progress.detail}
                </Text>

                {/* Progress bar */}
                <View style={[styles.progressTrack, { backgroundColor: colors.surfaceHigh }]}>
                  <Animated.View style={[styles.progressFill, { backgroundColor: colors.tint, width: progressWidth as any }]} />
                </View>

                <Text style={[styles.phasePercent, { color: colors.tint }]}>
                  Phase {progress.phase} of 4
                </Text>
              </View>

              {/* Phase indicators */}
              <View style={styles.phaseIndicators}>
                {[1, 2, 3, 4].map((p) => (
                  <View key={p} style={styles.indicator}>
                    <View
                      style={[
                        styles.indicatorDot,
                        {
                          backgroundColor:
                            p < progress.phase
                              ? colors.statusOnline
                              : p === progress.phase
                                ? colors.tint
                                : colors.surfaceHigh,
                        },
                      ]}>
                      {p < progress.phase && (
                        <MaterialIcons name="check" size={12} color="#fff" />
                      )}
                    </View>
                    <Text
                      style={[
                        styles.indicatorLabel,
                        {
                          color:
                            p <= progress.phase
                              ? colors.text
                              : colors.secondaryText,
                        },
                      ]}>
                      {PHASE_LABELS[p]}
                    </Text>
                  </View>
                ))}
              </View>
            </View>
          )}

          {/* ── Complete State ────────────────────────── */}
          {status === 'complete' && result && (
            <View style={styles.completeContainer}>
              <MaterialIcons name="check-circle" size={56} color={colors.statusOnline} />
              <Text style={[styles.completeTitle, { color: colors.text }]}>
                Analysis Complete
              </Text>

              {/* Stats grid */}
              <View style={styles.statsGrid}>
                <View style={[styles.statCard, { backgroundColor: colors.cardBackground, borderColor: colors.glassBorder }]}>
                  <Text style={[styles.statValue, { color: colors.tint }]}>
                    {result.projects.length}
                  </Text>
                  <Text style={[styles.statLabel, { color: colors.secondaryText }]}>
                    Projects
                  </Text>
                </View>
                <View style={[styles.statCard, { backgroundColor: colors.cardBackground, borderColor: colors.glassBorder }]}>
                  <Text style={[styles.statValue, { color: colors.tint }]}>
                    {result.agentsCreated.length}
                  </Text>
                  <Text style={[styles.statLabel, { color: colors.secondaryText }]}>
                    Agents Created
                  </Text>
                </View>
                <View style={[styles.statCard, { backgroundColor: colors.cardBackground, borderColor: colors.glassBorder }]}>
                  <Text style={[styles.statValue, { color: colors.tint }]}>
                    {result.foldersCreated.length}
                  </Text>
                  <Text style={[styles.statLabel, { color: colors.secondaryText }]}>
                    Folders
                  </Text>
                </View>
                <View style={[styles.statCard, { backgroundColor: colors.cardBackground, borderColor: colors.glassBorder }]}>
                  <Text style={[styles.statValue, { color: colors.tint }]}>
                    {result.chatsMoved}
                  </Text>
                  <Text style={[styles.statLabel, { color: colors.secondaryText }]}>
                    Chats Organized
                  </Text>
                </View>
              </View>

              {/* Created agents */}
              {result.agentsCreated.length > 0 && (
                <View style={styles.agentsSection}>
                  <Text style={[styles.sectionTitle, { color: colors.text }]}>
                    Your New Agents
                  </Text>
                  {result.agentsCreated.map((agent) => {
                    const grad = generateGradient(agent.id);
                    const ini = generateInitials(agent.name);
                    return (
                      <View
                        key={agent.id}
                        style={[styles.agentRow, { backgroundColor: colors.cardBackground, borderColor: colors.glassBorder }]}>
                        <LinearGradient colors={grad} style={styles.agentAvatar}>
                          <Text style={styles.agentInitials}>{ini}</Text>
                        </LinearGradient>
                        <View style={styles.agentInfo}>
                          <Text style={[styles.agentName, { color: colors.text }]}>
                            {agent.name}
                          </Text>
                          <Text style={[styles.agentDesc, { color: colors.secondaryText }]} numberOfLines={1}>
                            {agent.description || 'AI Agent'}
                          </Text>
                        </View>
                        <MaterialIcons name="check-circle" size={20} color={colors.statusOnline} />
                      </View>
                    );
                  })}
                </View>
              )}

              {/* Projects list */}
              {result.projects.length > 0 && (
                <View style={styles.agentsSection}>
                  <Text style={[styles.sectionTitle, { color: colors.text }]}>
                    Discovered Projects
                  </Text>
                  {result.projects.map((project) => (
                    <View
                      key={project.project_id}
                      style={[styles.projectRow, { backgroundColor: colors.cardBackground, borderColor: colors.glassBorder }]}>
                      <MaterialIcons name="folder" size={24} color={colors.tint} />
                      <View style={styles.agentInfo}>
                        <Text style={[styles.agentName, { color: colors.text }]}>
                          {project.project_name}
                        </Text>
                        <Text style={[styles.agentDesc, { color: colors.secondaryText }]} numberOfLines={1}>
                          {project.conversation_ids.length} conversations
                        </Text>
                      </View>
                    </View>
                  ))}
                </View>
              )}

              {/* Done button */}
              <Pressable
                onPress={() => router.back()}
                style={({ pressed }) => [
                  styles.doneBtn,
                  { backgroundColor: colors.tint, opacity: pressed ? 0.85 : 1 },
                ]}>
                <Text style={styles.doneText}>DONE</Text>
              </Pressable>
            </View>
          )}

          {/* ── Error State ──────────────────────────── */}
          {status === 'error' && (
            <View style={styles.errorContainer}>
              <MaterialIcons name="error-outline" size={56} color={colors.systemRed} />
              <Text style={[styles.errorTitle, { color: colors.text }]}>
                Analysis Failed
              </Text>
              <Text style={[styles.errorMsg, { color: colors.secondaryText }]}>
                {errorMsg}
              </Text>
              <Pressable
                onPress={handleStart}
                style={({ pressed }) => [
                  styles.retryBtn,
                  { borderColor: colors.tint, opacity: pressed ? 0.85 : 1 },
                ]}>
                <Text style={[styles.retryText, { color: colors.tint }]}>RETRY</Text>
              </Pressable>
            </View>
          )}
        </ScrollView>
      </Animated.View>
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1 },
  header: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingHorizontal: spacing.lg,
    paddingTop: 52,
    paddingBottom: spacing.md,
  },
  backBtn: {
    width: 40,
    height: 40,
    borderRadius: 20,
    alignItems: 'center',
    justifyContent: 'center',
  },
  headerTitle: {
    fontSize: fontSize.title3,
    fontWeight: fw.bold,
  },
  content: { flex: 1 },
  scrollContent: { paddingHorizontal: spacing.lg, paddingBottom: 120 },

  // Idle
  idleContainer: { alignItems: 'center', paddingTop: spacing['2xl'] },
  idleGlow: {
    width: 120,
    height: 120,
    borderRadius: 60,
    alignItems: 'center',
    justifyContent: 'center',
    marginBottom: spacing.xl,
  },
  idleTitle: { fontSize: fontSize.title2, fontWeight: fw.bold, marginBottom: spacing.sm },
  idleDesc: {
    fontSize: fontSize.subheadline,
    textAlign: 'center',
    lineHeight: 22,
    marginBottom: spacing.xl,
    paddingHorizontal: spacing.md,
  },
  idleSteps: { width: '100%', gap: spacing.sm, marginBottom: spacing['2xl'] },
  stepRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.md,
    padding: spacing.md,
    borderRadius: 16,
    borderWidth: 0.5,
  },
  stepIcon: {
    width: 36,
    height: 36,
    borderRadius: 10,
    alignItems: 'center',
    justifyContent: 'center',
  },
  stepInfo: { flex: 1 },
  stepTitle: { fontSize: fontSize.body, fontWeight: fw.semibold },
  authWarning: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
    padding: spacing.md,
    borderRadius: 12,
    marginBottom: spacing.md,
  },
  authWarningText: {
    fontSize: fontSize.caption1,
    fontWeight: fw.semibold,
    flex: 1,
  },
  startBtn: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: spacing.sm,
    width: '100%',
    paddingVertical: spacing.lg,
    borderRadius: 999,
  },
  startText: { color: '#fff', fontWeight: '700', fontSize: 12, letterSpacing: 1.5 },

  // Running
  runningContainer: { paddingTop: spacing['3xl'], gap: spacing.xl },
  phaseCard: {
    alignItems: 'center',
    padding: spacing.xl,
    borderRadius: 24,
    borderWidth: 0.5,
    gap: spacing.md,
  },
  phaseName: { fontSize: fontSize.title3, fontWeight: fw.bold },
  phaseDetail: { fontSize: fontSize.subheadline, textAlign: 'center' },
  progressTrack: { width: '100%', height: 6, borderRadius: 3, overflow: 'hidden' },
  progressFill: { height: '100%', borderRadius: 3 },
  phasePercent: { fontSize: fontSize.caption1, fontWeight: fw.semibold },
  phaseIndicators: { gap: spacing.md },
  indicator: { flexDirection: 'row', alignItems: 'center', gap: spacing.md },
  indicatorDot: {
    width: 24,
    height: 24,
    borderRadius: 12,
    alignItems: 'center',
    justifyContent: 'center',
  },
  indicatorLabel: { fontSize: fontSize.subheadline, fontWeight: fw.medium },

  // Complete
  completeContainer: { alignItems: 'center', paddingTop: spacing.xl, gap: spacing.lg },
  completeTitle: { fontSize: fontSize.title2, fontWeight: fw.bold },
  statsGrid: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: spacing.sm,
    width: '100%',
  },
  statCard: {
    width: '48%',
    padding: spacing.lg,
    borderRadius: 20,
    borderWidth: 0.5,
    alignItems: 'center',
    gap: 4,
  },
  statValue: { fontSize: 24, fontWeight: fw.extrabold },
  statLabel: { fontSize: fontSize.caption2, fontWeight: fw.semibold, textTransform: 'uppercase', letterSpacing: 1 },
  agentsSection: { width: '100%', gap: spacing.sm },
  sectionTitle: { fontSize: fontSize.body, fontWeight: fw.bold, marginBottom: spacing.xs },
  agentRow: {
    flexDirection: 'row',
    alignItems: 'center',
    padding: spacing.md,
    borderRadius: 16,
    borderWidth: 0.5,
    gap: spacing.md,
  },
  agentAvatar: {
    width: 36,
    height: 36,
    borderRadius: 18,
    alignItems: 'center',
    justifyContent: 'center',
  },
  agentInitials: { color: '#fff', fontSize: 12, fontWeight: '700' },
  agentInfo: { flex: 1 },
  agentName: { fontSize: fontSize.body, fontWeight: fw.semibold },
  agentDesc: { fontSize: fontSize.caption1 },
  projectRow: {
    flexDirection: 'row',
    alignItems: 'center',
    padding: spacing.md,
    borderRadius: 16,
    borderWidth: 0.5,
    gap: spacing.md,
  },
  doneBtn: {
    width: '100%',
    paddingVertical: spacing.lg,
    borderRadius: 999,
    alignItems: 'center',
    marginTop: spacing.md,
  },
  doneText: { color: '#fff', fontWeight: '700', fontSize: 12, letterSpacing: 1.5 },

  // Error
  errorContainer: { alignItems: 'center', paddingTop: spacing['3xl'], gap: spacing.md },
  errorTitle: { fontSize: fontSize.title3, fontWeight: fw.bold },
  errorMsg: { fontSize: fontSize.subheadline, textAlign: 'center', paddingHorizontal: spacing.lg },
  retryBtn: {
    paddingVertical: spacing.md,
    paddingHorizontal: spacing.xl,
    borderRadius: 999,
    borderWidth: 1.5,
    marginTop: spacing.md,
  },
  retryText: { fontWeight: '700', fontSize: 12, letterSpacing: 1.5 },
});
