import React, { useState } from 'react';
import {
  View,
  Text,
  TextInput,
  TouchableOpacity,
  StyleSheet,
  KeyboardAvoidingView,
  Platform,
  ActivityIndicator,
  Alert,
} from 'react-native';
import { useRouter } from 'expo-router';
import { MaterialIcons } from '@expo/vector-icons';

import Colors from '@/constants/Colors';
import {
  spacing,
  borderRadius,
  fontSize,
  fontWeight,
  letterSpacing,
  dimensions,
} from '@/constants/designTokens';
import { useColorScheme } from '@/components/useColorScheme';
import { useAuth } from '@/hooks/useAuth';

export default function LoginScreen() {
  const colorScheme = useColorScheme();
  const colors = Colors[colorScheme];
  const router = useRouter();
  const { loginWithApiKey, loginWithCredentials } = useAuth();

  const [apiKey, setApiKey] = useState('');
  const [loading, setLoading] = useState(false);

  const handleLogin = async () => {
    setLoading(true);
    try {
      await loginWithApiKey(apiKey.trim());
      router.replace('/(tabs)');
    } catch (err: any) {
      Alert.alert(
        'Connection Failed',
        err.message || 'Could not authenticate. Check your API key.',
      );
    } finally {
      setLoading(false);
    }
  };

  const canSubmit = apiKey.trim().length > 0;

  return (
    <KeyboardAvoidingView
      behavior={Platform.OS === 'ios' ? 'padding' : 'height'}
      style={[styles.container, { backgroundColor: colors.background }]}>
      <View style={styles.content}>
        {/* Header */}
        <View style={styles.header}>
          <View style={[styles.iconCircle, { backgroundColor: colors.tint }]}>
            <MaterialIcons name="lock-open" size={32} color="#fff" />
          </View>
          <Text style={[styles.title, { color: colors.text }]}>
            Connect to AICORTEX
          </Text>
          <Text style={[styles.subtitle, { color: colors.secondaryText }]}>
            Enter your Open WebUI API key to get started
          </Text>
        </View>

        {/* API Key Input */}
        <View style={styles.inputGroup}>
          <Text style={[styles.label, { color: colors.secondaryText }]}>
            API Key
          </Text>
          <TextInput
            style={[
              styles.input,
              {
                backgroundColor: colors.inputBackground,
                color: colors.text,
                borderColor: colors.outline,
              },
            ]}
            value={apiKey}
            onChangeText={setApiKey}
            placeholder="sk-..."
            placeholderTextColor={colors.secondaryText}
            autoCapitalize="none"
            autoCorrect={false}
            secureTextEntry
          />
          <Text style={[styles.hint, { color: colors.tertiaryText }]}>
            Find this in Open WebUI → Settings → Account → API Keys
          </Text>
        </View>

        {/* Connect button */}
        <TouchableOpacity
          style={[
            styles.connectButton,
            { backgroundColor: canSubmit ? colors.tint : colors.surfaceHigh },
          ]}
          onPress={handleLogin}
          disabled={!canSubmit || loading}
          activeOpacity={0.8}>
          {loading ? (
            <ActivityIndicator color="#fff" />
          ) : (
            <Text style={styles.connectText}>Connect</Text>
          )}
        </TouchableOpacity>

        {/* Server info */}
        <Text style={[styles.serverInfo, { color: colors.tertiaryText }]}>
          chat.aicortex.cloud
        </Text>
      </View>
    </KeyboardAvoidingView>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    justifyContent: 'center',
  },
  content: {
    paddingHorizontal: spacing.lg + spacing.lg,
  },
  header: {
    alignItems: 'center',
    marginBottom: spacing['3xl'],
  },
  iconCircle: {
    width: 64,
    height: 64,
    borderRadius: 32,
    alignItems: 'center',
    justifyContent: 'center',
    marginBottom: spacing.lg,
  },
  title: {
    fontSize: fontSize.title1,
    fontWeight: fontWeight.bold,
    letterSpacing: letterSpacing.tight,
    marginBottom: spacing.sm,
  },
  subtitle: {
    fontSize: fontSize.subheadline,
    letterSpacing: letterSpacing.normal,
    textAlign: 'center',
    lineHeight: 20,
  },
  inputGroup: {
    marginBottom: spacing.lg,
  },
  label: {
    fontSize: fontSize.footnote,
    fontWeight: fontWeight.medium,
    marginBottom: spacing.xs,
    textTransform: 'uppercase',
    letterSpacing: 0.5,
  },
  input: {
    height: dimensions.navBarHeight,
    borderRadius: borderRadius.input,
    borderWidth: 0.5,
    paddingHorizontal: spacing.lg,
    fontSize: fontSize.body,
  },
  hint: {
    fontSize: fontSize.caption1,
    marginTop: spacing.xs,
    lineHeight: 16,
  },
  connectButton: {
    height: dimensions.navBarHeight + 6,
    borderRadius: borderRadius.button,
    alignItems: 'center',
    justifyContent: 'center',
    marginTop: spacing.lg,
  },
  connectText: {
    color: '#fff',
    fontSize: fontSize.body,
    fontWeight: fontWeight.semibold,
    letterSpacing: letterSpacing.tight,
  },
  serverInfo: {
    textAlign: 'center',
    fontSize: fontSize.caption1,
    marginTop: spacing.lg,
  },
});
