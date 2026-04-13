/**
 * Sequential agent creation with animated progress.
 *
 * Shows agents being created one by one with fade+slide animation,
 * progress bar, and a "Your team is ready" final state.
 */

import React, { useEffect, useRef, useState } from 'react';
import {
  Animated,
  Pressable,
  StyleSheet,
  Text,
  View,
} from 'react-native';
import { LinearGradient } from 'expo-linear-gradient';
import { MaterialIcons } from '@expo/vector-icons';

import Colors from '@/constants/Colors';
import { useColorScheme } from '@/components/useColorScheme';
import { createAgentsFromRecommendations } from '@/services/agentFactory';
import { generateGradient, generateInitials } from '@/services/agentMapper';
import { AGENT_CATALOG } from '@/constants/agentCatalog';
import type { AgentContext, AgentRecommendation } from '@/constants/types';
import { spacing, fontSize, fontWeight as fw } from '@/constants/designTokens';

interface CreatedAgent {
  name: string;
  description: string;
  gradientColors: [string, string];
  initials: string;
}

interface Props {
  recommendations: AgentRecommendation[];
  context?: AgentContext;
  onComplete: () => void;
}

export default function AgentCreationProgress({
  recommendations,
  context,
  onComplete,
}: Props) {
  const colorScheme = useColorScheme();
  const colors = Colors[colorScheme];

  const [status, setStatus] = useState<'creating' | 'done' | 'error'>('creating');
  const [current, setCurrent] = useState(0);
  const [currentName, setCurrentName] = useState('');
  const [createdAgents, setCreatedAgents] = useState<CreatedAgent[]>([]);
  const [failedCount, setFailedCount] = useState(0);

  const progressAnim = useRef(new Animated.Value(0)).current;
  const fadeAnims = useRef<Animated.Value[]>([]).current;

  const total = recommendations.length;

  useEffect(() => {
    startCreation();
  }, []);

  useEffect(() => {
    Animated.timing(progressAnim, {
      toValue: total > 0 ? current / total : 0,
      duration: 400,
      useNativeDriver: false,
    }).start();
  }, [current, total]);

  const startCreation = async () => {
    try {
      const { created, failed } = await createAgentsFromRecommendations(
        recommendations,
        context,
        (cur, tot, name) => {
          setCurrent(cur);
          setCurrentName(name);

          // Build created agent card
          const template = Object.values(AGENT_CATALOG).find(
            (t) => t.name === name,
          );
          const agentCard: CreatedAgent = {
            name,
            description: template?.meta?.description ?? 'AI Agent',
            gradientColors: generateGradient(name),
            initials: generateInitials(name),
          };

          setCreatedAgents((prev) => {
            const updated = [...prev, agentCard];
            // Create fade animation for new card
            const anim = new Animated.Value(0);
            fadeAnims.push(anim);
            Animated.timing(anim, {
              toValue: 1,
              duration: 500,
              useNativeDriver: true,
            }).start();
            return updated;
          });
        },
      );

      setFailedCount(failed.length);
      setStatus('done');
    } catch {
      setStatus('error');
    }
  };

  const progressWidth = progressAnim.interpolate({
    inputRange: [0, 1],
    outputRange: ['0%', '100%'],
  });

  return (
    <View style={styles.container}>
      {/* Status header */}
      <View style={styles.statusSection}>
        {status === 'creating' && (
          <>
            <Text style={[styles.title, { color: colors.text }]}>
              Building Your Team
            </Text>
            <Text style={[styles.subtitle, { color: colors.secondaryText }]}>
              {currentName ? `Creating ${currentName}...` : 'Starting...'}
            </Text>

            {/* Progress bar */}
            <View style={[styles.progressTrack, { backgroundColor: colors.surfaceHigh }]}>
              <Animated.View
                style={[
                  styles.progressFill,
                  { backgroundColor: colors.tint, width: progressWidth as any },
                ]}
              />
            </View>
            <Text style={[styles.progressLabel, { color: colors.secondaryText }]}>
              {current} of {total}
            </Text>
          </>
        )}

        {status === 'done' && (
          <>
            <View style={styles.doneIcon}>
              <MaterialIcons name="check-circle" size={48} color={colors.statusOnline} />
            </View>
            <Text style={[styles.title, { color: colors.text }]}>
              Your Team is Ready
            </Text>
            <Text style={[styles.subtitle, { color: colors.secondaryText }]}>
              {createdAgents.length} agent{createdAgents.length !== 1 ? 's' : ''} created
              {failedCount > 0 ? ` (${failedCount} failed)` : ''}
            </Text>
          </>
        )}

        {status === 'error' && (
          <>
            <MaterialIcons name="error-outline" size={48} color={colors.systemRed} />
            <Text style={[styles.title, { color: colors.text }]}>
              Something Went Wrong
            </Text>
            <Text style={[styles.subtitle, { color: colors.secondaryText }]}>
              We couldn't create your agents. You can retry or skip.
            </Text>
          </>
        )}
      </View>

      {/* Agent cards */}
      <View style={styles.agentList}>
        {createdAgents.map((agent, index) => {
          const anim = fadeAnims[index];
          return (
            <Animated.View
              key={agent.name + index}
              style={[
                styles.agentCard,
                {
                  backgroundColor: colors.cardBackground,
                  borderColor: colors.glassBorder,
                  opacity: anim ?? 1,
                  transform: [
                    {
                      translateY: anim
                        ? anim.interpolate({
                            inputRange: [0, 1],
                            outputRange: [20, 0],
                          })
                        : 0,
                    },
                  ],
                },
              ]}>
              <LinearGradient
                colors={agent.gradientColors}
                style={styles.agentAvatar}>
                <Text style={styles.agentInitials}>{agent.initials}</Text>
              </LinearGradient>
              <View style={styles.agentInfo}>
                <Text style={[styles.agentName, { color: colors.text }]}>
                  {agent.name}
                </Text>
                <Text
                  style={[styles.agentDesc, { color: colors.secondaryText }]}
                  numberOfLines={1}>
                  {agent.description}
                </Text>
              </View>
              <MaterialIcons name="check-circle" size={20} color={colors.statusOnline} />
            </Animated.View>
          );
        })}
      </View>

      {/* CTA */}
      {status === 'done' && (
        <Pressable
          onPress={onComplete}
          style={({ pressed }) => [
            styles.ctaButton,
            { backgroundColor: colors.tint, opacity: pressed ? 0.85 : 1 },
          ]}>
          <Text style={styles.ctaText}>START CHATTING</Text>
          <MaterialIcons name="arrow-forward" size={20} color="#fff" />
        </Pressable>
      )}

      {status === 'error' && (
        <View style={styles.errorActions}>
          <Pressable
            onPress={startCreation}
            style={[styles.retryBtn, { backgroundColor: colors.tint }]}>
            <Text style={styles.ctaText}>RETRY</Text>
          </Pressable>
          <Pressable onPress={onComplete} style={styles.skipErrorBtn}>
            <Text style={[styles.skipErrorText, { color: colors.secondaryText }]}>
              Skip for now
            </Text>
          </Pressable>
        </View>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    paddingHorizontal: spacing.lg,
  },
  statusSection: {
    alignItems: 'center',
    paddingTop: spacing.xl,
    paddingBottom: spacing.xl,
    gap: spacing.sm,
  },
  title: {
    fontSize: 24,
    fontWeight: fw.extrabold,
    letterSpacing: -0.5,
  },
  subtitle: {
    fontSize: fontSize.subheadline,
    textAlign: 'center',
  },
  progressTrack: {
    width: '100%',
    height: 6,
    borderRadius: 3,
    overflow: 'hidden',
    marginTop: spacing.md,
  },
  progressFill: {
    height: '100%',
    borderRadius: 3,
  },
  progressLabel: {
    fontSize: fontSize.caption1,
    fontWeight: fw.medium,
  },
  doneIcon: {
    marginBottom: spacing.xs,
  },

  // Agent cards
  agentList: {
    gap: spacing.sm,
    flex: 1,
  },
  agentCard: {
    flexDirection: 'row',
    alignItems: 'center',
    padding: spacing.md,
    borderRadius: 16,
    borderWidth: 0.5,
    gap: spacing.md,
  },
  agentAvatar: {
    width: 40,
    height: 40,
    borderRadius: 20,
    alignItems: 'center',
    justifyContent: 'center',
  },
  agentInitials: {
    color: '#fff',
    fontSize: 14,
    fontWeight: '700',
  },
  agentInfo: {
    flex: 1,
  },
  agentName: {
    fontSize: fontSize.body,
    fontWeight: fw.semibold,
  },
  agentDesc: {
    fontSize: fontSize.caption1,
    marginTop: 1,
  },

  // CTA
  ctaButton: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    paddingVertical: spacing.lg,
    borderRadius: 999,
    gap: spacing.sm,
    marginTop: spacing.xl,
    marginBottom: spacing.xl,
  },
  ctaText: {
    color: '#fff',
    fontWeight: '700',
    fontSize: 12,
    letterSpacing: 1.5,
  },
  errorActions: {
    gap: spacing.md,
    marginTop: spacing.xl,
  },
  retryBtn: {
    alignItems: 'center',
    paddingVertical: spacing.lg,
    borderRadius: 999,
  },
  skipErrorBtn: {
    alignItems: 'center',
    paddingVertical: spacing.sm,
  },
  skipErrorText: {
    fontSize: fontSize.caption1,
    fontWeight: fw.medium,
  },
});
