import { useRef, useState } from 'react';
import {
  Animated,
  Platform,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  useWindowDimensions,
  View,
} from 'react-native';
import { useRouter } from 'expo-router';
import { LinearGradient } from 'expo-linear-gradient';
import { MaterialIcons } from '@expo/vector-icons';

import Colors from '@/constants/Colors';
import { useColorScheme } from '@/components/useColorScheme';
import { ROLES } from '@/constants/onboardingData';
import { useOnboarding } from '@/hooks/useOnboarding';
import { useAuth } from '@/hooks/useAuth';
import { ensureCortexModel } from '@/services/concierge';
import ProgressBar from '@/components/onboarding/ProgressBar';
import ConciergeChat from '@/components/onboarding/ConciergeChat';
import AgentCreationProgress from '@/components/onboarding/AgentCreationProgress';
import type { AgentRecommendation, ConciergeOutput } from '@/constants/types';
import { spacing, borderRadius, fontSize as fs } from '@/constants/designTokens';

const COMFORT_OPTIONS = [
  { id: 'beginner', label: 'Beginner', desc: 'New to AI tools' },
  { id: 'some_experience', label: 'Some Experience', desc: 'Used ChatGPT/Claude' },
  { id: 'power_user', label: 'Power User', desc: 'Build with AI daily' },
];

// 5 pages: 0=intro, 1=quick setup, 2=connect, 3=concierge chat, 4=agent creation
const PROGRESS_VALUES = [0, 0.2, 0.4, 0.7, 1.0];
const TOTAL_PAGES = 5;

export default function OnboardingScreen() {
  const colorScheme = useColorScheme();
  const colors = Colors[colorScheme];
  const router = useRouter();
  const { width: screenWidth } = useWindowDimensions();

  const { completeOnboarding } = useOnboarding();
  const { loginWithApiKey, isAuthenticated } = useAuth();

  const [page, setPage] = useState(0);
  const slideAnim = useRef(new Animated.Value(0)).current;

  // Page 1: Quick Setup
  const [role, setRole] = useState('');
  const [displayName, setDisplayName] = useState('');
  const [aiComfort, setAiComfort] = useState('some_experience');

  // Page 2: Connect
  const [apiKey, setApiKey] = useState('');
  const [connecting, setConnecting] = useState(false);
  const [connectError, setConnectError] = useState('');

  // Page 3→4: Concierge output
  const [recommendations, setRecommendations] = useState<AgentRecommendation[]>([]);

  const goToPage = (nextPage: number) => {
    Animated.timing(slideAnim, {
      toValue: -nextPage * screenWidth,
      duration: 300,
      useNativeDriver: true,
    }).start();
    setPage(nextPage);
  };

  const handleConnect = async () => {
    if (!apiKey.trim()) return;
    setConnecting(true);
    setConnectError('');

    try {
      await loginWithApiKey(apiKey.trim());
      // Ensure Cortex model exists on server
      try {
        await ensureCortexModel();
      } catch {
        // Non-fatal — Concierge can still work with fallback
      }
      goToPage(3);
    } catch (err) {
      setConnectError(err instanceof Error ? err.message : 'Connection failed');
    } finally {
      setConnecting(false);
    }
  };

  const handleSkipConnect = () => {
    // Skip to concierge — will use fallback if not authenticated
    goToPage(3);
  };

  const handleConciergeComplete = (
    recs: AgentRecommendation[],
    _output: ConciergeOutput | null,
  ) => {
    setRecommendations(recs);
    goToPage(4);
  };

  const handleConciergeSkip = () => {
    // Generate role-based defaults
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
    setRecommendations(roleDefaults[role] ?? roleDefaults.professional);
    goToPage(4);
  };

  const handleGetStarted = async () => {
    await completeOnboarding({
      role: role || 'professional',
      goals: [],
      painPoints: [],
      tone: 'balanced',
      detailLevel: 'brief',
      proactive: false,
      displayName,
      aiComfort: aiComfort as any,
    });
    router.replace('/(tabs)' as any);
  };

  const canContinue = () => {
    switch (page) {
      case 0: return true;
      case 1: return role !== '';
      case 2: return true; // can skip
      default: return false;
    }
  };

  return (
    <View style={[styles.container, { backgroundColor: colors.background }]}>
      {/* Progress bar — pages 1-2 only */}
      {page > 0 && page < 3 && (
        <View style={[styles.header, { paddingTop: Platform.OS === 'ios' ? 56 : 36 }]}>
          <ProgressBar
            progress={PROGRESS_VALUES[page]}
            color={colors.tint}
            trackColor={colors.surfaceHigh}
          />
          {page > 1 && (
            <Pressable onPress={() => goToPage(page - 1)} style={styles.backButton}>
              <Text style={[styles.backText, { color: colors.tint }]}>← Back</Text>
            </Pressable>
          )}
        </View>
      )}

      {/* Pages container */}
      <View style={styles.pagesClip}>
        <Animated.View
          style={[styles.pages, { transform: [{ translateX: slideAnim }] }]}>

          {/* ═══════════════════════════════════════════════ */}
          {/* PAGE 0: INTRO SPLASH                           */}
          {/* ═══════════════════════════════════════════════ */}
          <View style={[styles.page, { width: screenWidth }]}>
            <View style={styles.introContainer}>
              <View style={styles.brainContainer}>
                <LinearGradient
                  colors={['#6C63FF', '#B794F4', '#FF6B9D']}
                  style={styles.brainGlow}
                  start={{ x: 0.2, y: 0 }}
                  end={{ x: 0.8, y: 1 }}
                />
                <LinearGradient
                  colors={['#4B0082', '#6C63FF', '#B794F4']}
                  style={styles.brainCore}
                  start={{ x: 0.3, y: 0.2 }}
                  end={{ x: 0.7, y: 0.8 }}
                />
                <View style={styles.brainOverlay}>
                  <MaterialIcons name="psychology" size={80} color="rgba(255,255,255,0.3)" />
                </View>
              </View>
              <Text style={styles.introTitle}>AICORTEX</Text>
              <Text style={[styles.introTagline, { color: colors.outline }]}>
                YOUR AI BRAIN IN THE CLOUD
              </Text>
              <Text style={[styles.introSubtext, { color: colors.onSurfaceVariant }]}>
                Meet Cortex — your concierge. A quick conversation and your personalized AI team is ready.
              </Text>
            </View>
            <View style={styles.introFooter}>
              <Pressable
                onPress={() => goToPage(1)}
                style={({ pressed }) => [
                  styles.introCta,
                  { backgroundColor: colors.tint, opacity: pressed ? 0.85 : 1 },
                ]}>
                <Text style={styles.introCtaText}>GET STARTED</Text>
                <MaterialIcons name="arrow-forward" size={20} color="#fff" />
              </Pressable>
            </View>
          </View>

          {/* ═══════════════════════════════════════════════ */}
          {/* PAGE 1: QUICK SETUP (role + name + comfort)    */}
          {/* ═══════════════════════════════════════════════ */}
          <View style={[styles.page, { width: screenWidth }]}>
            <ScrollView contentContainerStyle={styles.pageContent} showsVerticalScrollIndicator={false}>
              <Text style={[styles.sectionLabel, { color: colors.sectionLabel }]}>
                QUICK SETUP
              </Text>
              <Text style={[styles.pageTitle, { color: colors.text }]}>
                Tell us about yourself
              </Text>

              {/* Role selection */}
              <Text style={[styles.fieldLabel, { color: colors.secondaryText }]}>
                What best describes you?
              </Text>
              <View style={styles.roleGrid}>
                {ROLES.map((r) => (
                  <Pressable
                    key={r.id}
                    onPress={() => setRole(r.id)}
                    style={[
                      styles.roleCard,
                      {
                        backgroundColor: colors.surfaceLow,
                        borderColor: role === r.id ? colors.tint : 'transparent',
                        borderWidth: 2,
                      },
                    ]}>
                    <Text style={styles.roleIcon}>{r.icon}</Text>
                    <Text
                      style={[
                        styles.roleLabel,
                        { color: role === r.id ? colors.tint : colors.text },
                      ]}>
                      {r.label}
                    </Text>
                  </Pressable>
                ))}
              </View>

              {/* Display name */}
              <Text style={[styles.fieldLabel, { color: colors.secondaryText, marginTop: spacing.lg }]}>
                What should we call you?
              </Text>
              <TextInput
                value={displayName}
                onChangeText={setDisplayName}
                placeholder="Your name or nickname"
                placeholderTextColor={colors.secondaryText}
                style={[
                  styles.nameInput,
                  {
                    color: colors.text,
                    backgroundColor: colors.surfaceLow,
                    borderColor: colors.glassBorder,
                  },
                ]}
              />

              {/* AI Comfort */}
              <Text style={[styles.fieldLabel, { color: colors.secondaryText, marginTop: spacing.lg }]}>
                AI experience level
              </Text>
              <View style={styles.comfortRow}>
                {COMFORT_OPTIONS.map((opt) => (
                  <Pressable
                    key={opt.id}
                    onPress={() => setAiComfort(opt.id)}
                    style={[
                      styles.comfortCard,
                      {
                        backgroundColor:
                          aiComfort === opt.id ? colors.tint : colors.surfaceLow,
                        borderColor:
                          aiComfort === opt.id ? colors.tint : colors.surfaceHigh,
                        borderWidth: 1,
                      },
                    ]}>
                    <Text
                      style={[
                        styles.comfortLabel,
                        { color: aiComfort === opt.id ? '#fff' : colors.text },
                      ]}>
                      {opt.label}
                    </Text>
                    <Text
                      style={[
                        styles.comfortDesc,
                        {
                          color: aiComfort === opt.id
                            ? 'rgba(255,255,255,0.7)'
                            : colors.secondaryText,
                        },
                      ]}>
                      {opt.desc}
                    </Text>
                  </Pressable>
                ))}
              </View>
            </ScrollView>
          </View>

          {/* ═══════════════════════════════════════════════ */}
          {/* PAGE 2: CONNECT TO SERVER                      */}
          {/* ═══════════════════════════════════════════════ */}
          <View style={[styles.page, { width: screenWidth }]}>
            <View style={styles.connectContainer}>
              <View style={[styles.connectIconWrap, { backgroundColor: colors.tint + '15' }]}>
                <MaterialIcons name="vpn-key" size={40} color={colors.tint} />
              </View>
              <Text style={[styles.pageTitle, { color: colors.text }]}>
                Connect to AICORTEX
              </Text>
              <Text style={[styles.connectDesc, { color: colors.secondaryText }]}>
                Enter your API key to connect. Cortex will use the server to build your agent team.
              </Text>

              <TextInput
                value={apiKey}
                onChangeText={setApiKey}
                placeholder="sk-..."
                placeholderTextColor={colors.secondaryText}
                style={[
                  styles.apiKeyInput,
                  {
                    color: colors.text,
                    backgroundColor: colors.surfaceLow,
                    borderColor: connectError ? colors.systemRed : colors.glassBorder,
                  },
                ]}
                autoCapitalize="none"
                autoCorrect={false}
                secureTextEntry
              />

              {connectError ? (
                <Text style={[styles.errorText, { color: colors.systemRed }]}>
                  {connectError}
                </Text>
              ) : null}

              <Pressable
                onPress={handleConnect}
                disabled={connecting || !apiKey.trim()}
                style={({ pressed }) => [
                  styles.connectBtn,
                  {
                    backgroundColor: colors.tint,
                    opacity: connecting || !apiKey.trim() ? 0.5 : pressed ? 0.85 : 1,
                  },
                ]}>
                <Text style={styles.connectBtnText}>
                  {connecting ? 'Connecting...' : 'CONNECT'}
                </Text>
              </Pressable>

              <Pressable onPress={handleSkipConnect} style={styles.skipBtn}>
                <Text style={[styles.skipText, { color: colors.secondaryText }]}>
                  Skip — connect later in settings
                </Text>
              </Pressable>
            </View>
          </View>

          {/* ═══════════════════════════════════════════════ */}
          {/* PAGE 3: CONCIERGE CHAT                         */}
          {/* ═══════════════════════════════════════════════ */}
          <View style={[styles.page, { width: screenWidth }]}>
            {page === 3 && (
              <ConciergeChat
                userName={displayName}
                userRole={role || 'professional'}
                aiComfort={aiComfort}
                onComplete={handleConciergeComplete}
                onSkip={handleConciergeSkip}
              />
            )}
          </View>

          {/* ═══════════════════════════════════════════════ */}
          {/* PAGE 4: AGENT CREATION PROGRESS                */}
          {/* ═══════════════════════════════════════════════ */}
          <View style={[styles.page, { width: screenWidth }]}>
            {page === 4 && (
              <AgentCreationProgress
                recommendations={recommendations}
                context={{
                  userName: displayName,
                  userRole: role,
                  aiComfort,
                }}
                onComplete={handleGetStarted}
              />
            )}
          </View>
        </Animated.View>
      </View>

      {/* Continue button — pages 1-2 only */}
      {page > 0 && page < 3 && (
        <View style={styles.footer}>
          <Pressable
            onPress={() => goToPage(page + 1)}
            disabled={!canContinue()}
            style={({ pressed }) => [
              styles.continueBtn,
              {
                backgroundColor: colors.tint,
                opacity: !canContinue() ? 0.4 : pressed ? 0.85 : 1,
              },
            ]}>
            <Text style={styles.continueBtnText}>CONTINUE</Text>
            <MaterialIcons name="arrow-forward" size={20} color="#fff" />
          </Pressable>
        </View>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1 },
  header: {
    paddingHorizontal: spacing.lg,
    paddingBottom: spacing.sm,
  },
  backButton: { marginTop: spacing.sm },
  backText: { fontSize: fs.subheadline, fontWeight: '600' },

  pagesClip: { flex: 1, overflow: 'hidden', position: 'relative' },
  pages: { flexDirection: 'row', flex: 1, position: 'absolute', top: 0, bottom: 0 },
  page: {},

  // Intro (Page 0)
  introContainer: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
    paddingHorizontal: spacing.xl,
  },
  brainContainer: {
    width: 160,
    height: 160,
    alignItems: 'center',
    justifyContent: 'center',
    marginBottom: spacing.xl,
  },
  brainGlow: {
    position: 'absolute',
    width: 160,
    height: 160,
    borderRadius: 80,
    opacity: 0.5,
  },
  brainCore: {
    position: 'absolute',
    width: 120,
    height: 120,
    borderRadius: 60,
    opacity: 0.8,
  },
  brainOverlay: {
    alignItems: 'center',
    justifyContent: 'center',
  },
  introTitle: {
    fontSize: 32,
    fontWeight: '800',
    color: '#fff',
    letterSpacing: 4,
    marginBottom: spacing.xs,
  },
  introTagline: {
    fontSize: 10,
    fontWeight: '700',
    letterSpacing: 3,
    marginBottom: spacing.xl,
  },
  introSubtext: {
    fontSize: fs.subheadline,
    textAlign: 'center',
    lineHeight: 22,
    paddingHorizontal: spacing.md,
  },
  introFooter: {
    paddingHorizontal: spacing.xl,
    paddingBottom: 40,
    width: '100%',
  },
  introCta: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    paddingVertical: 18,
    borderRadius: 999,
    gap: spacing.sm,
  },
  introCtaText: {
    color: '#fff',
    fontWeight: '700',
    fontSize: 12,
    letterSpacing: 2,
  },

  // Page content
  pageContent: {
    paddingHorizontal: spacing.xl,
    paddingTop: spacing.md,
    paddingBottom: 120,
  },
  sectionLabel: {
    fontSize: 10,
    fontWeight: '700',
    letterSpacing: 2,
    marginBottom: spacing.xs,
  },
  pageTitle: {
    fontSize: 24,
    fontWeight: '800',
    letterSpacing: -0.5,
    marginBottom: spacing.md,
  },
  fieldLabel: {
    fontSize: fs.caption1,
    fontWeight: '600',
    letterSpacing: 0.3,
    marginBottom: spacing.sm,
  },

  // Roles
  roleGrid: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: spacing.sm,
  },
  roleCard: {
    width: '47%',
    paddingVertical: spacing.lg,
    borderRadius: borderRadius.card,
    alignItems: 'center',
    gap: spacing.xs,
  },
  roleIcon: { fontSize: 28 },
  roleLabel: { fontSize: fs.subheadline, fontWeight: '600' },

  // Name input
  nameInput: {
    borderWidth: 0.5,
    borderRadius: borderRadius.input,
    paddingHorizontal: spacing.lg,
    paddingVertical: spacing.md,
    fontSize: fs.body,
  },

  // Comfort
  comfortRow: { gap: spacing.sm },
  comfortCard: {
    paddingVertical: spacing.md,
    paddingHorizontal: spacing.lg,
    borderRadius: borderRadius.card,
  },
  comfortLabel: { fontSize: fs.body, fontWeight: '600' },
  comfortDesc: { fontSize: fs.caption1, marginTop: 2 },

  // Connect (Page 2)
  connectContainer: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
    paddingHorizontal: spacing.xl,
    gap: spacing.md,
  },
  connectIconWrap: {
    width: 80,
    height: 80,
    borderRadius: 24,
    alignItems: 'center',
    justifyContent: 'center',
    marginBottom: spacing.md,
  },
  connectDesc: {
    fontSize: fs.subheadline,
    textAlign: 'center',
    lineHeight: 22,
    marginBottom: spacing.md,
  },
  apiKeyInput: {
    width: '100%',
    borderWidth: 0.5,
    borderRadius: borderRadius.input,
    paddingHorizontal: spacing.lg,
    paddingVertical: spacing.md,
    fontSize: fs.body,
  },
  errorText: {
    fontSize: fs.caption1,
    fontWeight: '600',
  },
  connectBtn: {
    width: '100%',
    paddingVertical: spacing.lg,
    borderRadius: 999,
    alignItems: 'center',
  },
  connectBtnText: {
    color: '#fff',
    fontWeight: '700',
    fontSize: 12,
    letterSpacing: 1.5,
  },
  skipBtn: { paddingVertical: spacing.sm },
  skipText: { fontSize: fs.caption1, fontWeight: '500' },

  // Footer
  footer: {
    paddingHorizontal: spacing.xl,
    paddingBottom: 40,
  },
  continueBtn: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    paddingVertical: 18,
    borderRadius: 999,
    gap: spacing.sm,
  },
  continueBtnText: {
    color: '#fff',
    fontWeight: '700',
    fontSize: 12,
    letterSpacing: 2,
  },
});
