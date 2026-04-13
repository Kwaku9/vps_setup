/**
 * Full-screen voice conversation overlay — Apple Liquid Glass design.
 *
 * Shown when the user taps the mic button. Displays a pulsing circle
 * that reflects the current voice session state, agent info, and
 * a red "End Call" button.
 */

import React, { useEffect } from 'react';
import {
  Modal,
  View,
  Text,
  Pressable,
  StyleSheet,
  useColorScheme,
  Platform,
} from 'react-native';
import { BlurView } from 'expo-blur';
import { LinearGradient } from 'expo-linear-gradient';
import { MaterialIcons } from '@expo/vector-icons';
import Animated, {
  useSharedValue,
  useAnimatedStyle,
  withRepeat,
  withTiming,
  withSequence,
  Easing,
  cancelAnimation,
} from 'react-native-reanimated';
import Colors from '@/constants/Colors';
import { spacing, fontSize, fontWeight, borderRadius } from '@/constants/designTokens';
import type { VoiceSessionState, Agent } from '@/constants/types';

interface VoiceOverlayProps {
  visible: boolean;
  agent?: Agent;
  sessionState: VoiceSessionState;
  isMuted?: boolean;
  error?: string | null;
  onEnd: () => void;
  onToggleMute?: () => void;
}

const STATE_LABELS: Record<VoiceSessionState, string> = {
  idle: 'Starting...',
  connecting: 'Connecting...',
  setup: 'Setting up...',
  ready: 'Listening',
  listening: 'Listening...',
  responding: 'Speaking...',
  error: 'Connection error',
  closed: 'Disconnected',
};

export default function VoiceOverlay({
  visible,
  agent,
  sessionState,
  isMuted = false,
  error,
  onEnd,
  onToggleMute,
}: VoiceOverlayProps) {
  const rawScheme = useColorScheme();
  const colorScheme = rawScheme === 'light' ? 'light' : 'dark';
  const colors = Colors[colorScheme];

  // ── Pulse animation ─────────────────────────────────────

  const pulseScale = useSharedValue(1);
  const pulseOpacity = useSharedValue(0.4);

  useEffect(() => {
    if (!visible) return;

    if (sessionState === 'listening' || sessionState === 'ready') {
      // Slow, calm pulse for listening
      pulseScale.value = withRepeat(
        withSequence(
          withTiming(1.15, { duration: 1200, easing: Easing.inOut(Easing.ease) }),
          withTiming(1, { duration: 1200, easing: Easing.inOut(Easing.ease) }),
        ),
        -1,
      );
      pulseOpacity.value = withRepeat(
        withSequence(
          withTiming(0.6, { duration: 1200 }),
          withTiming(0.3, { duration: 1200 }),
        ),
        -1,
      );
    } else if (sessionState === 'responding') {
      // Faster pulse for responding
      pulseScale.value = withRepeat(
        withSequence(
          withTiming(1.25, { duration: 400, easing: Easing.inOut(Easing.ease) }),
          withTiming(1.05, { duration: 400, easing: Easing.inOut(Easing.ease) }),
        ),
        -1,
      );
      pulseOpacity.value = withRepeat(
        withSequence(
          withTiming(0.7, { duration: 400 }),
          withTiming(0.3, { duration: 400 }),
        ),
        -1,
      );
    } else {
      // Static for other states
      cancelAnimation(pulseScale);
      cancelAnimation(pulseOpacity);
      pulseScale.value = withTiming(1, { duration: 300 });
      pulseOpacity.value = withTiming(0.2, { duration: 300 });
    }
  }, [sessionState, visible, pulseScale, pulseOpacity]);

  const pulseRingStyle = useAnimatedStyle(() => ({
    transform: [{ scale: pulseScale.value }],
    opacity: pulseOpacity.value,
  }));

  // ── State-dependent colors ──────────────────────────────

  const ringColor =
    sessionState === 'responding'
      ? colors.systemGreen
      : sessionState === 'error'
        ? colors.error
        : colors.tint;

  const statusLabel = error && sessionState === 'error' ? error : STATE_LABELS[sessionState];

  // ── Agent display ───────────────────────────────────────

  const agentName = agent?.name ?? 'Gemini Live';
  const agentInitials = agent?.initials ?? 'GL';
  const gradientColors = agent?.gradientColors ?? ['#4285F4', '#34A853'];

  return (
    <Modal
      visible={visible}
      animationType="slide"
      transparent
      statusBarTranslucent
    >
      <BlurView
        intensity={90}
        tint={colorScheme === 'dark' ? 'dark' : 'light'}
        style={styles.container}
      >
        {/* Agent info */}
        <View style={styles.agentSection}>
          <LinearGradient
            colors={gradientColors as [string, string]}
            start={{ x: 0, y: 0 }}
            end={{ x: 1, y: 1 }}
            style={styles.avatar}
          >
            <Text style={styles.avatarText}>{agentInitials}</Text>
          </LinearGradient>
          <Text style={[styles.agentName, { color: colors.text }]}>
            {agentName}
          </Text>
          <Text style={[styles.statusText, { color: colors.secondaryText }]}>
            Voice Conversation
          </Text>
        </View>

        {/* Pulse ring */}
        <View style={styles.pulseContainer}>
          <Animated.View
            style={[
              styles.pulseRing,
              { borderColor: ringColor },
              pulseRingStyle,
            ]}
          />
          <View
            style={[
              styles.innerCircle,
              { backgroundColor: ringColor },
            ]}
          >
            <MaterialIcons
              name={
                sessionState === 'responding'
                  ? 'graphic-eq'
                  : sessionState === 'listening' || sessionState === 'ready'
                    ? 'mic'
                    : sessionState === 'error'
                      ? 'error-outline'
                      : 'hourglass-empty'
              }
              size={48}
              color="#FFFFFF"
            />
          </View>
        </View>

        {/* Status label */}
        <Text style={[styles.stateLabel, { color: colors.secondaryText }]}>
          {statusLabel}
        </Text>

        {/* Bottom buttons */}
        <View style={styles.bottomSection}>
          <View style={styles.buttonRow}>
            {/* Mute button */}
            {onToggleMute && (
              <Pressable onPress={onToggleMute} style={styles.endButton}>
                <View style={[styles.actionButtonInner, { backgroundColor: isMuted ? colors.secondaryText : 'rgba(255,255,255,0.15)' }]}>
                  <MaterialIcons name={isMuted ? 'mic-off' : 'mic'} size={28} color="#FFFFFF" />
                </View>
                <Text style={[styles.endLabel, { color: colors.secondaryText }]}>
                  {isMuted ? 'Unmute' : 'Mute'}
                </Text>
              </Pressable>
            )}

            {/* End button */}
            <Pressable onPress={onEnd} style={styles.endButton}>
              <View style={[styles.endButtonInner, { backgroundColor: colors.error }]}>
                <MaterialIcons name="call-end" size={32} color="#FFFFFF" />
              </View>
              <Text style={[styles.endLabel, { color: colors.secondaryText }]}>
                End
              </Text>
            </Pressable>
          </View>
        </View>
      </BlurView>
    </Modal>
  );
}

// ── Styles ──────────────────────────────────────────────────

const CIRCLE_SIZE = 120;
const RING_SIZE = 160;
const END_BUTTON_SIZE = 64;

const styles = StyleSheet.create({
  container: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingTop: Platform.OS === 'ios' ? 80 : 60,
    paddingBottom: Platform.OS === 'ios' ? 60 : 40,
  },
  agentSection: {
    alignItems: 'center',
    gap: spacing.sm,
  },
  avatar: {
    width: 56,
    height: 56,
    borderRadius: borderRadius.avatar,
    alignItems: 'center',
    justifyContent: 'center',
  },
  avatarText: {
    color: '#FFFFFF',
    fontSize: fontSize.title3,
    fontWeight: fontWeight.semibold,
  },
  agentName: {
    fontSize: fontSize.title2,
    fontWeight: fontWeight.semibold,
  },
  statusText: {
    fontSize: fontSize.subheadline,
    fontWeight: fontWeight.regular,
  },
  pulseContainer: {
    width: RING_SIZE + 40,
    height: RING_SIZE + 40,
    alignItems: 'center',
    justifyContent: 'center',
  },
  pulseRing: {
    position: 'absolute',
    width: RING_SIZE,
    height: RING_SIZE,
    borderRadius: RING_SIZE / 2,
    borderWidth: 3,
  },
  innerCircle: {
    width: CIRCLE_SIZE,
    height: CIRCLE_SIZE,
    borderRadius: CIRCLE_SIZE / 2,
    alignItems: 'center',
    justifyContent: 'center',
  },
  stateLabel: {
    fontSize: fontSize.body,
    fontWeight: fontWeight.medium,
  },
  bottomSection: {
    alignItems: 'center',
  },
  buttonRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing['5xl'],
  },
  endButton: {
    alignItems: 'center',
    gap: spacing.sm,
  },
  actionButtonInner: {
    width: END_BUTTON_SIZE,
    height: END_BUTTON_SIZE,
    borderRadius: END_BUTTON_SIZE / 2,
    alignItems: 'center',
    justifyContent: 'center',
  },
  endButtonInner: {
    width: END_BUTTON_SIZE,
    height: END_BUTTON_SIZE,
    borderRadius: END_BUTTON_SIZE / 2,
    alignItems: 'center',
    justifyContent: 'center',
  },
  endLabel: {
    fontSize: fontSize.caption1,
    fontWeight: fontWeight.medium,
  },
});
