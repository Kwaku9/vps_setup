import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Alert,
  Image,
  KeyboardAvoidingView,
  Platform,
  Pressable,
  ScrollView,
  StyleSheet,
  Switch,
  Text,
  TextInput,
  View,
} from 'react-native';
import { useLocalSearchParams, useRouter } from 'expo-router';
import { LinearGradient } from 'expo-linear-gradient';
import { MaterialIcons } from '@expo/vector-icons';
// ImagePicker loaded dynamically to avoid crash in Expo Go if native module unavailable
const getImagePicker = async () => {
  try {
    return await import('expo-image-picker');
  } catch {
    return null;
  }
};

import Colors from '@/constants/Colors';
import { useColorScheme } from '@/components/useColorScheme';
import { useAgents } from '@/hooks/useAgents';
import { useConversations } from '@/hooks/useConversations';
import { agentToModelForm, generateGradient, generateInitials } from '@/services/agentMapper';
import CollapsibleSection from '@/components/CollapsibleSection';
import TagInput from '@/components/TagInput';
import ModelSelector from '@/components/ModelSelector';
import type { ModelParams } from '@/constants/types';
import {
  spacing,
  borderRadius,
  fontSize,
  fontWeight as fw,
} from '@/constants/designTokens';

const DEFAULT_BASE_MODEL = 'claude-sonnet-4-6';

const CAP_LABELS: Array<{ key: string; label: string; icon: string }> = [
  { key: 'vision', label: 'Vision', icon: 'visibility' },
  { key: 'file_upload', label: 'File Upload', icon: 'upload-file' },
  { key: 'file_context', label: 'File Context', icon: 'description' },
  { key: 'web_search', label: 'Web Search', icon: 'search' },
  { key: 'image_generation', label: 'Image Generation', icon: 'image' },
  { key: 'code_interpreter', label: 'Code Interpreter', icon: 'terminal' },
  { key: 'usage', label: 'Usage', icon: 'data-usage' },
  { key: 'citations', label: 'Citations', icon: 'format-quote' },
  { key: 'status_updates', label: 'Status Updates', icon: 'update' },
  { key: 'builtin_tools', label: 'Builtin Tools', icon: 'build' },
];

const BUILTIN_TOOL_LABELS: Array<{ key: string; label: string; icon: string }> = [
  { key: 'time_calculation', label: 'Time & Calculation', icon: 'schedule' },
  { key: 'memory', label: 'Memory', icon: 'memory' },
  { key: 'chat_history', label: 'Chat History', icon: 'history' },
  { key: 'notes', label: 'Notes', icon: 'sticky-note-2' },
  { key: 'knowledge_base', label: 'Knowledge Base', icon: 'menu-book' },
  { key: 'channels', label: 'Channels', icon: 'forum' },
  { key: 'web_search', label: 'Web Search', icon: 'travel-explore' },
  { key: 'image_generation', label: 'Image Generation', icon: 'brush' },
  { key: 'code_interpreter', label: 'Code Interpreter', icon: 'code' },
];

const TTS_VOICES = [
  '', 'alloy', 'echo', 'fable', 'onyx', 'nova', 'shimmer',
];

export default function AgentProfileScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const isCreateMode = id === 'new';
  const colorScheme = useColorScheme();
  const colors = Colors[colorScheme];
  const router = useRouter();
  const { getAgent, createAgent, updateAgent, deleteAgent } = useAgents();
  const { createConversation } = useConversations();

  const existingAgent = isCreateMode ? undefined : getAgent(id);

  // ── Form state ─────────────────────────────────────────────
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [systemPrompt, setSystemPrompt] = useState('');
  const [baseModelId, setBaseModelId] = useState(DEFAULT_BASE_MODEL);
  const [baseModelName, setBaseModelName] = useState('Claude Sonnet 4.6');
  const [tags, setTags] = useState<string[]>([]);
  const [isActive, setIsActive] = useState(true);
  const [capabilities, setCapabilities] = useState<Record<string, boolean>>({
    vision: false,
    file_upload: false,
    file_context: false,
    web_search: false,
    image_generation: false,
    code_interpreter: false,
    usage: false,
    citations: false,
    status_updates: false,
    builtin_tools: false,
  });
  const [builtinTools, setBuiltinTools] = useState<Record<string, boolean>>({
    time_calculation: false,
    memory: false,
    chat_history: false,
    notes: false,
    knowledge_base: false,
    channels: false,
    web_search: false,
    image_generation: false,
    code_interpreter: false,
  });
  const [profileImageUrl, setProfileImageUrl] = useState<string | undefined>();
  const [knowledge, setKnowledge] = useState<string[]>([]);
  const [files, setFiles] = useState<string[]>([]);
  const [ttsVoice, setTtsVoice] = useState('');
  const [params, setParams] = useState<ModelParams>({
    temperature: 0.7,
    top_p: 0.9,
    top_k: 40,
    frequency_penalty: 0,
    presence_penalty: 0,
    repeat_penalty: 1.0,
    num_predict: -1,
    seed: -1,
  });

  const [modelSelectorVisible, setModelSelectorVisible] = useState(false);
  const [saving, setSaving] = useState(false);
  const [isEditing, setIsEditing] = useState(isCreateMode);

  // ── Load existing agent into form ──────────────────────────
  useEffect(() => {
    if (existingAgent) {
      setName(existingAgent.name);
      setDescription(existingAgent.description);
      setSystemPrompt(existingAgent.systemPrompt);
      setBaseModelId(existingAgent.baseModelId);
      setBaseModelName(existingAgent.baseModelName);
      setTags(existingAgent.tags);
      setIsActive(existingAgent.isActive);
      setProfileImageUrl(existingAgent.profileImageUrl);
      setCapabilities(existingAgent.capabilities);
      if (existingAgent.params) {
        setParams((prev) => ({ ...prev, ...existingAgent.params }));
      }
    }
  }, [existingAgent?.id]);

  const gradient = useMemo(
    () => (existingAgent ? existingAgent.gradientColors : generateGradient(name || 'new')),
    [existingAgent, name],
  );
  const initials = useMemo(
    () => (existingAgent ? existingAgent.initials : generateInitials(name || 'AG')),
    [existingAgent, name],
  );

  // ── Param helpers ──────────────────────────────────────────
  const setParam = useCallback(
    <K extends keyof ModelParams>(key: K, value: ModelParams[K]) => {
      setParams((prev) => ({ ...prev, [key]: value }));
    },
    [],
  );

  const toggleCapability = useCallback((key: string) => {
    setCapabilities((prev) => ({ ...prev, [key]: !prev[key] }));
  }, []);

  const toggleBuiltinTool = useCallback((key: string) => {
    setBuiltinTools((prev) => ({ ...prev, [key]: !prev[key] }));
  }, []);

  const pickAvatar = useCallback(async () => {
    if (!isEditing) return;
    const picker = await getImagePicker();
    if (!picker) {
      // Fallback: prompt for URL
      Alert.prompt?.(
        'Profile Image',
        'Enter an image URL:',
        (url: string) => { if (url?.trim()) setProfileImageUrl(url.trim()); },
      ) ?? Alert.alert(
        'Profile Image',
        'Image picker not available in this build. Set avatar via the Open WebUI web interface.',
      );
      return;
    }
    const { status } = await picker.requestMediaLibraryPermissionsAsync();
    if (status !== 'granted') {
      Alert.alert('Permission needed', 'Please allow access to your photo library.');
      return;
    }
    const result = await picker.launchImageLibraryAsync({
      mediaTypes: ['images'],
      allowsEditing: true,
      aspect: [1, 1],
      quality: 0.7,
      base64: true,
    });
    if (!result.canceled && result.assets[0]) {
      const asset = result.assets[0];
      if (asset.base64) {
        const mimeType = asset.mimeType ?? 'image/jpeg';
        setProfileImageUrl(`data:${mimeType};base64,${asset.base64}`);
      } else if (asset.uri) {
        setProfileImageUrl(asset.uri);
      }
    }
  }, [isEditing]);

  // ── Save ───────────────────────────────────────────────────
  const handleSave = async () => {
    if (!name.trim()) {
      Alert.alert('Name required', 'Please enter a name for this agent.');
      return;
    }
    if (!baseModelId) {
      Alert.alert('Base model required', 'Please select a base model.');
      return;
    }

    setSaving(true);
    try {
      const form = agentToModelForm(
        {
          id: isCreateMode ? name.trim().toLowerCase().replace(/[^a-z0-9]+/g, '-') + '-' + Math.random().toString(36).slice(2, 5) : id,
          name: name.trim(),
          baseModelId,
          description,
          systemPrompt,
          profileImageUrl,
          tags,
          capabilities,
          isActive,
          params,
        },
        params,
      );

      if (isCreateMode) {
        await createAgent(form);
      } else {
        await updateAgent(form);
      }

      setIsEditing(false);
      if (isCreateMode) {
        router.back();
      }
    } catch (err) {
      Alert.alert('Error', err instanceof Error ? err.message : 'Failed to save agent');
    } finally {
      setSaving(false);
    }
  };

  // ── Delete ─────────────────────────────────────────────────
  const handleDelete = () => {
    Alert.alert('Delete Agent', `Are you sure you want to delete "${name}"?`, [
      { text: 'Cancel', style: 'cancel' },
      {
        text: 'Delete',
        style: 'destructive',
        onPress: async () => {
          try {
            await deleteAgent(id);
            router.back();
          } catch (err) {
            Alert.alert('Error', 'Failed to delete agent');
          }
        },
      },
    ]);
  };

  // ── Start Chat ─────────────────────────────────────────────
  const handleStartChat = () => {
    const conv = createConversation(id);
    router.push(`/chat/${conv.id}` as any);
  };

  // ── Slider component ──────────────────────────────────────
  const ParamSlider = ({
    label,
    value,
    min,
    max,
    step,
    leftLabel,
    rightLabel,
    paramKey,
  }: {
    label: string;
    value: number;
    min: number;
    max: number;
    step: number;
    leftLabel?: string;
    rightLabel?: string;
    paramKey: keyof ModelParams;
  }) => {
    // Use a TextInput-based approach since Slider isn't in core RN
    const displayValue = value === -1 ? 'Auto' : value.toFixed(step < 1 ? 1 : 0);
    return (
      <View style={styles.paramRow}>
        <View style={styles.paramHeader}>
          <Text style={[styles.paramLabel, { color: colors.secondaryText }]}>
            {label}
          </Text>
          <View style={[styles.paramBadge, { backgroundColor: colors.tint + '15' }]}>
            <Text style={[styles.paramValue, { color: colors.tint }]}>
              {displayValue}
            </Text>
          </View>
        </View>
        {isEditing && (
          <View style={styles.paramControls}>
            <Pressable
              onPress={() => {
                const newVal = Math.max(min, (value as number) - step);
                setParam(paramKey, Math.round(newVal * 100) / 100);
              }}
              style={[styles.paramBtn, { backgroundColor: colors.surfaceHigh }]}>
              <MaterialIcons name="remove" size={16} color={colors.text} />
            </Pressable>
            <View style={[styles.paramTrack, { backgroundColor: colors.surfaceHigh }]}>
              <View
                style={[
                  styles.paramFill,
                  {
                    backgroundColor: colors.tint,
                    width: `${Math.min(100, Math.max(0, ((value as number) - min) / (max - min) * 100))}%`,
                  },
                ]}
              />
            </View>
            <Pressable
              onPress={() => {
                const newVal = Math.min(max, (value as number) + step);
                setParam(paramKey, Math.round(newVal * 100) / 100);
              }}
              style={[styles.paramBtn, { backgroundColor: colors.surfaceHigh }]}>
              <MaterialIcons name="add" size={16} color={colors.text} />
            </Pressable>
          </View>
        )}
        {leftLabel && rightLabel && isEditing && (
          <View style={styles.paramLabels}>
            <Text style={[styles.paramEndLabel, { color: colors.secondaryText }]}>
              {leftLabel}
            </Text>
            <Text style={[styles.paramEndLabel, { color: colors.secondaryText }]}>
              {rightLabel}
            </Text>
          </View>
        )}
      </View>
    );
  };

  return (
    <View style={[styles.container, { backgroundColor: colors.background }]}>
      {/* Top Bar */}
      <View style={styles.topBar}>
        <Pressable onPress={() => router.back()} style={styles.topBtn}>
          <MaterialIcons name="arrow-back" size={24} color={colors.tint} />
        </Pressable>
        <View style={styles.topCenter}>
          <LinearGradient colors={[colors.tint, '#00C6FF']} style={styles.topLogo}>
            <Text style={styles.topLogoText}>A</Text>
          </LinearGradient>
        </View>
        <View style={styles.topRight}>
          {!isCreateMode && !isEditing && (
            <Pressable onPress={() => setIsEditing(true)} style={styles.topBtn}>
              <MaterialIcons name="edit" size={22} color={colors.tint} />
            </Pressable>
          )}
          {!isCreateMode && (
            <Pressable onPress={handleDelete} style={styles.topBtn}>
              <MaterialIcons name="delete-outline" size={22} color={colors.systemRed} />
            </Pressable>
          )}
        </View>
      </View>

      <KeyboardAvoidingView
        style={{ flex: 1 }}
        behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
        <ScrollView
          contentContainerStyle={styles.scrollContent}
          showsVerticalScrollIndicator={false}>

          {/* ── Hero Section ────────────────────────────── */}
          <View style={styles.heroSection}>
            <View style={styles.glowWrap}>
              <LinearGradient
                colors={[gradient[0] + '40', 'transparent']}
                style={styles.glow}
              />
            </View>
            <Pressable onPress={pickAvatar} disabled={!isEditing}>
              {profileImageUrl ? (
                <Image source={{ uri: profileImageUrl }} style={styles.heroAvatar} />
              ) : (
                <LinearGradient colors={gradient} style={styles.heroAvatar}>
                  <Text style={styles.heroInitials}>{initials}</Text>
                </LinearGradient>
              )}
              {isEditing && (
                <View style={[styles.avatarEditBadge, { backgroundColor: colors.tint }]}>
                  <MaterialIcons name="camera-alt" size={14} color="#fff" />
                </View>
              )}
            </Pressable>
            {existingAgent && (
              <View
                style={[
                  styles.verifiedBadge,
                  { backgroundColor: colors.tint, borderColor: colors.background },
                ]}>
                <MaterialIcons name="verified" size={14} color="#fff" />
              </View>
            )}

            {isEditing ? (
              <TextInput
                value={name}
                onChangeText={setName}
                placeholder="Agent Name"
                placeholderTextColor={colors.secondaryText}
                style={[styles.heroNameInput, { color: colors.text, borderBottomColor: colors.glassBorder }]}
              />
            ) : (
              <Text style={[styles.heroName, { color: colors.text }]}>{name}</Text>
            )}

            {isEditing ? (
              <TextInput
                value={description}
                onChangeText={setDescription}
                placeholder="Brief description (2-3 words)"
                placeholderTextColor={colors.secondaryText}
                style={[styles.heroDescInput, { color: colors.secondaryText, borderBottomColor: colors.glassBorder }]}
              />
            ) : (
              <Text style={[styles.heroDesc, { color: colors.secondaryText }]}>
                {description || 'AI Agent'}
              </Text>
            )}

            {/* Status badges */}
            <View style={styles.badgeRow}>
              <View style={[styles.badge, { backgroundColor: (isActive ? colors.statusOnline : colors.statusOffline) + '20' }]}>
                <Text style={[styles.badgeText, { color: isActive ? colors.statusOnline : colors.statusOffline }]}>
                  {isActive ? 'ACTIVE' : 'INACTIVE'}
                </Text>
              </View>
              <Pressable
                onPress={() => isEditing && setModelSelectorVisible(true)}
                style={[styles.badge, { backgroundColor: colors.surfaceHigh }]}>
                <Text style={[styles.badgeText, { color: colors.secondaryText }]}>
                  {baseModelName}
                </Text>
                {isEditing && <MaterialIcons name="unfold-more" size={12} color={colors.secondaryText} />}
              </Pressable>
            </View>
          </View>

          {/* ── Capabilities ──────────────────────────── */}
          <View style={[styles.glassCard, { backgroundColor: colors.cardBackground, borderColor: colors.glassBorder }]}>
            <View style={styles.sectionHeader}>
              <MaterialIcons name="hub" size={18} color={colors.tint} />
              <Text style={[styles.sectionTitle, { color: colors.text }]}>
                Capabilities
              </Text>
            </View>
            {CAP_LABELS.map(({ key, label, icon }) => (
              <View key={key} style={[styles.capRow, { backgroundColor: colors.surfaceLow }]}>
                <MaterialIcons name={icon as any} size={18} color={colors.secondaryText} style={{ marginRight: spacing.sm }} />
                <View style={styles.capInfo}>
                  <Text style={[styles.capLabel, { color: colors.text }]}>{label}</Text>
                </View>
                <Switch
                  value={capabilities[key] ?? false}
                  onValueChange={() => { if (isEditing) toggleCapability(key); }}
                  disabled={!isEditing}
                  trackColor={{ false: colors.surfaceHigh, true: colors.tint + '60' }}
                  thumbColor={(capabilities[key] ?? false) ? colors.tint : colors.secondaryText}
                />
              </View>
            ))}
          </View>

          {/* ── System Prompt ───────────────────────────── */}
          <View style={[styles.glassCard, { backgroundColor: colors.cardBackground, borderColor: colors.glassBorder }]}>
            <View style={styles.sectionHeader}>
              <MaterialIcons name="psychology" size={18} color={colors.tint} />
              <Text style={[styles.sectionTitle, { color: colors.text }]}>
                System Prompt
              </Text>
            </View>
            <View style={[styles.promptBox, { backgroundColor: colors.surfaceLow, borderColor: colors.glassBorder }]}>
              <TextInput
                value={systemPrompt}
                onChangeText={setSystemPrompt}
                placeholder="Define this agent's personality, expertise, and behavior..."
                placeholderTextColor={colors.secondaryText}
                style={[styles.promptInput, { color: colors.text }]}
                multiline
                numberOfLines={8}
                textAlignVertical="top"
                editable={isEditing}
              />
            </View>
          </View>

          {/* ── Advanced Parameters (Collapsible) ───────── */}
          <CollapsibleSection title="Advanced Parameters" icon="tune">
            <View style={styles.paramsGrid}>
              <ParamSlider
                label="TEMPERATURE"
                value={params.temperature ?? 0.7}
                min={0}
                max={2}
                step={0.1}
                leftLabel="Precise"
                rightLabel="Creative"
                paramKey="temperature"
              />
              <ParamSlider
                label="TOP P"
                value={params.top_p ?? 0.9}
                min={0}
                max={1}
                step={0.05}
                paramKey="top_p"
              />
              <ParamSlider
                label="TOP K"
                value={params.top_k ?? 40}
                min={1}
                max={100}
                step={1}
                paramKey="top_k"
              />
              <ParamSlider
                label="FREQUENCY PENALTY"
                value={params.frequency_penalty ?? 0}
                min={0}
                max={2}
                step={0.1}
                paramKey="frequency_penalty"
              />
              <ParamSlider
                label="PRESENCE PENALTY"
                value={params.presence_penalty ?? 0}
                min={0}
                max={2}
                step={0.1}
                paramKey="presence_penalty"
              />
              <ParamSlider
                label="REPEAT PENALTY"
                value={params.repeat_penalty ?? 1}
                min={0}
                max={2}
                step={0.1}
                paramKey="repeat_penalty"
              />
              <ParamSlider
                label="MAX TOKENS"
                value={params.num_predict ?? -1}
                min={-1}
                max={4096}
                step={256}
                paramKey="num_predict"
              />
              <ParamSlider
                label="SEED"
                value={params.seed ?? -1}
                min={-1}
                max={9999}
                step={1}
                paramKey="seed"
              />

              {/* Stop sequences */}
              <View style={styles.paramRow}>
                <Text style={[styles.paramLabel, { color: colors.secondaryText }]}>
                  STOP SEQUENCES
                </Text>
                {isEditing && (
                  <TextInput
                    value={(params.stop ?? []).join(', ')}
                    onChangeText={(text) =>
                      setParam(
                        'stop',
                        text
                          .split(',')
                          .map((s) => s.trim())
                          .filter(Boolean),
                      )
                    }
                    placeholder="Comma-separated stop tokens..."
                    placeholderTextColor={colors.secondaryText}
                    style={[
                      styles.stopInput,
                      {
                        color: colors.text,
                        backgroundColor: colors.surfaceLow,
                        borderColor: colors.glassBorder,
                      },
                    ]}
                  />
                )}
              </View>

              {/* Active toggle */}
              <View style={[styles.toggleRow, { backgroundColor: colors.surfaceLow, borderColor: colors.glassBorder }]}>
                <View>
                  <Text style={[styles.toggleLabel, { color: colors.text }]}>
                    Agent Active
                  </Text>
                  <Text style={[styles.toggleSub, { color: colors.secondaryText }]}>
                    Available for conversations
                  </Text>
                </View>
                <Switch
                  value={isActive}
                  onValueChange={setIsActive}
                  disabled={!isEditing}
                  trackColor={{ false: colors.surfaceHigh, true: colors.tint + '60' }}
                  thumbColor={isActive ? colors.tint : colors.secondaryText}
                />
              </View>
            </View>
          </CollapsibleSection>

          {/* ── Tags ────────────────────────────────────── */}
          <View style={[styles.glassCard, { backgroundColor: colors.cardBackground, borderColor: colors.glassBorder }]}>
            <View style={styles.sectionHeader}>
              <MaterialIcons name="label" size={18} color={colors.tint} />
              <Text style={[styles.sectionTitle, { color: colors.text }]}>
                Tags
              </Text>
            </View>
            {isEditing ? (
              <TagInput tags={tags} onChange={setTags} />
            ) : (
              <View style={styles.tagsReadOnly}>
                {tags.map((t) => (
                  <View key={t} style={[styles.readTag, { backgroundColor: colors.tint + '15' }]}>
                    <Text style={[styles.readTagText, { color: colors.tint }]}>#{t}</Text>
                  </View>
                ))}
                {tags.length === 0 && (
                  <Text style={{ color: colors.secondaryText, fontSize: fontSize.footnote }}>
                    No tags
                  </Text>
                )}
              </View>
            )}
          </View>

          {/* ── Knowledge & Files (Collapsible) ──────── */}
          <CollapsibleSection title="Knowledge & Files" icon="folder-open">
            <View style={{ gap: spacing.md }}>
              <View>
                <Text style={[styles.fieldSubLabel, { color: colors.secondaryText }]}>
                  KNOWLEDGE
                </Text>
                <Text style={[styles.fieldHint, { color: colors.tertiaryText }]}>
                  Attach knowledge collections for RAG retrieval
                </Text>
                {knowledge.length > 0 ? (
                  <View style={styles.tagsReadOnly}>
                    {knowledge.map((k, i) => (
                      <View key={i} style={[styles.fileChip, { backgroundColor: colors.surfaceLow, borderColor: colors.glassBorder }]}>
                        <MaterialIcons name="menu-book" size={14} color={colors.tint} />
                        <Text style={[styles.fileChipText, { color: colors.text }]}>{k}</Text>
                        {isEditing && (
                          <Pressable onPress={() => setKnowledge(knowledge.filter((_, j) => j !== i))} hitSlop={8}>
                            <MaterialIcons name="close" size={14} color={colors.secondaryText} />
                          </Pressable>
                        )}
                      </View>
                    ))}
                  </View>
                ) : (
                  <Text style={[styles.emptyField, { color: colors.tertiaryText }]}>No knowledge attached</Text>
                )}
                {isEditing && (
                  <Pressable style={[styles.attachBtn, { borderColor: colors.glassBorder }]}>
                    <MaterialIcons name="add" size={16} color={colors.tint} />
                    <Text style={[styles.attachBtnText, { color: colors.tint }]}>Add Knowledge</Text>
                  </Pressable>
                )}
              </View>

              <View>
                <Text style={[styles.fieldSubLabel, { color: colors.secondaryText }]}>
                  FILES
                </Text>
                <Text style={[styles.fieldHint, { color: colors.tertiaryText }]}>
                  Upload documents for this agent's context
                </Text>
                {files.length > 0 ? (
                  <View style={styles.tagsReadOnly}>
                    {files.map((f, i) => (
                      <View key={i} style={[styles.fileChip, { backgroundColor: colors.surfaceLow, borderColor: colors.glassBorder }]}>
                        <MaterialIcons name="attach-file" size={14} color={colors.tint} />
                        <Text style={[styles.fileChipText, { color: colors.text }]}>{f}</Text>
                        {isEditing && (
                          <Pressable onPress={() => setFiles(files.filter((_, j) => j !== i))} hitSlop={8}>
                            <MaterialIcons name="close" size={14} color={colors.secondaryText} />
                          </Pressable>
                        )}
                      </View>
                    ))}
                  </View>
                ) : (
                  <Text style={[styles.emptyField, { color: colors.tertiaryText }]}>No files attached</Text>
                )}
                {isEditing && (
                  <Pressable style={[styles.attachBtn, { borderColor: colors.glassBorder }]}>
                    <MaterialIcons name="upload-file" size={16} color={colors.tint} />
                    <Text style={[styles.attachBtnText, { color: colors.tint }]}>Upload File</Text>
                  </Pressable>
                )}
              </View>
            </View>
          </CollapsibleSection>

          {/* ── Skills & Builtin Tools (Collapsible) ───── */}
          <CollapsibleSection title="Skills & Tools" icon="build">
            <View style={{ gap: spacing.xs }}>
              {BUILTIN_TOOL_LABELS.map(({ key, label, icon }) => (
                <View key={key} style={[styles.capRow, { backgroundColor: colors.surfaceLow }]}>
                  <MaterialIcons name={icon as any} size={18} color={colors.secondaryText} style={{ marginRight: spacing.sm }} />
                  <View style={styles.capInfo}>
                    <Text style={[styles.capLabel, { color: colors.text }]}>{label}</Text>
                  </View>
                  <Switch
                    value={builtinTools[key] ?? false}
                    onValueChange={() => { if (isEditing) toggleBuiltinTool(key); }}
                    disabled={!isEditing}
                    trackColor={{ false: colors.surfaceHigh, true: colors.tint + '60' }}
                    thumbColor={(builtinTools[key] ?? false) ? colors.tint : colors.secondaryText}
                  />
                </View>
              ))}
            </View>
          </CollapsibleSection>

          {/* ── TTS Voice (Collapsible) ────────────────── */}
          <CollapsibleSection title="Voice" icon="record-voice-over">
            <View style={{ gap: spacing.sm }}>
              <Text style={[styles.fieldSubLabel, { color: colors.secondaryText }]}>
                TTS VOICE
              </Text>
              <View style={styles.voiceGrid}>
                {TTS_VOICES.map((v) => (
                  <Pressable
                    key={v || 'default'}
                    onPress={() => { if (isEditing) setTtsVoice(v); }}
                    style={[
                      styles.voiceChip,
                      {
                        backgroundColor: ttsVoice === v ? colors.tint : colors.surfaceLow,
                        borderColor: ttsVoice === v ? colors.tint : colors.glassBorder,
                      },
                    ]}>
                    <Text
                      style={[
                        styles.voiceChipText,
                        { color: ttsVoice === v ? '#fff' : colors.text },
                      ]}>
                      {v || 'Default'}
                    </Text>
                  </Pressable>
                ))}
              </View>
            </View>
          </CollapsibleSection>

          {/* ── Action Buttons ──────────────────────────── */}
          {isEditing && (
            <View style={styles.actionRow}>
              {!isCreateMode && (
                <Pressable
                  onPress={() => {
                    setIsEditing(false);
                    // Reset form from existing agent
                    if (existingAgent) {
                      setName(existingAgent.name);
                      setDescription(existingAgent.description);
                      setSystemPrompt(existingAgent.systemPrompt);
                    }
                  }}
                  style={[styles.cancelBtn, { borderColor: colors.glassBorder }]}>
                  <Text style={[styles.cancelText, { color: colors.text }]}>Cancel</Text>
                </Pressable>
              )}
              <Pressable
                onPress={handleSave}
                disabled={saving}
                style={[styles.saveBtn, { backgroundColor: colors.tint, opacity: saving ? 0.6 : 1 }]}>
                <Text style={styles.saveText}>
                  {saving ? 'Saving...' : isCreateMode ? 'CREATE AGENT' : 'SAVE CHANGES'}
                </Text>
                {!saving && <MaterialIcons name="check" size={18} color="#fff" />}
              </Pressable>
            </View>
          )}

          {/* ── Start Conversation CTA ──────────────────── */}
          {!isCreateMode && !isEditing && (
            <Pressable
              onPress={handleStartChat}
              style={({ pressed }) => [
                styles.ctaButton,
                { backgroundColor: colors.tint, opacity: pressed ? 0.85 : 1 },
              ]}>
              <Text style={styles.ctaText}>START CONVERSATION</Text>
              <MaterialIcons name="arrow-forward" size={20} color="#fff" />
            </Pressable>
          )}
        </ScrollView>
      </KeyboardAvoidingView>

      {/* Model Selector Modal */}
      <ModelSelector
        visible={modelSelectorVisible}
        selectedModelId={baseModelId}
        onSelect={(mId, mName) => {
          setBaseModelId(mId);
          setBaseModelName(mName);
          setModelSelectorVisible(false);
        }}
        onClose={() => setModelSelectorVisible(false)}
      />
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1 },

  // Top bar
  topBar: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    paddingHorizontal: spacing.lg,
    paddingTop: 52,
    paddingBottom: spacing.sm,
  },
  topBtn: {
    width: 40,
    height: 40,
    borderRadius: 20,
    alignItems: 'center',
    justifyContent: 'center',
  },
  topCenter: { alignItems: 'center' },
  topLogo: {
    width: 30,
    height: 30,
    borderRadius: 8,
    alignItems: 'center',
    justifyContent: 'center',
  },
  topLogoText: { color: '#fff', fontSize: 14, fontWeight: '800' },
  topRight: { flexDirection: 'row', gap: spacing.xs },

  scrollContent: { paddingBottom: 120 },

  // Hero
  heroSection: {
    alignItems: 'center',
    paddingHorizontal: spacing.xl,
    paddingTop: spacing.xl,
    paddingBottom: spacing['2xl'],
  },
  glowWrap: {
    position: 'absolute',
    top: 0,
    alignItems: 'center',
  },
  glow: { width: 200, height: 200, borderRadius: 100 },
  heroAvatar: {
    width: 120,
    height: 120,
    borderRadius: 60,
    alignItems: 'center',
    justifyContent: 'center',
    marginBottom: spacing.lg,
  },
  heroInitials: { color: '#fff', fontSize: 36, fontWeight: '800' },
  avatarEditBadge: {
    position: 'absolute',
    bottom: 4,
    right: 4,
    width: 28,
    height: 28,
    borderRadius: 14,
    alignItems: 'center',
    justifyContent: 'center',
    borderWidth: 2,
    borderColor: '#000',
  },
  verifiedBadge: {
    position: 'absolute',
    top: 120,
    right: '35%',
    width: 28,
    height: 28,
    borderRadius: 14,
    alignItems: 'center',
    justifyContent: 'center',
    borderWidth: 3,
  },
  heroName: {
    fontSize: 28,
    fontWeight: '800',
    letterSpacing: -0.5,
    textAlign: 'center',
    marginBottom: spacing.xs,
  },
  heroNameInput: {
    fontSize: 28,
    fontWeight: '800',
    letterSpacing: -0.5,
    textAlign: 'center',
    marginBottom: spacing.xs,
    borderBottomWidth: 1,
    paddingBottom: 4,
    minWidth: 200,
  },
  heroDesc: {
    fontSize: fontSize.body,
    textAlign: 'center',
    marginBottom: spacing.md,
  },
  heroDescInput: {
    fontSize: fontSize.body,
    textAlign: 'center',
    marginBottom: spacing.md,
    borderBottomWidth: 1,
    paddingBottom: 4,
    minWidth: 200,
  },
  badgeRow: {
    flexDirection: 'row',
    gap: spacing.sm,
  },
  badge: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 4,
    paddingHorizontal: spacing.md,
    paddingVertical: 6,
    borderRadius: 999,
  },
  badgeText: {
    fontSize: 10,
    fontWeight: '700',
    letterSpacing: 1,
    textTransform: 'uppercase',
  },

  // Glass card
  glassCard: {
    marginHorizontal: spacing.lg,
    marginBottom: spacing.lg,
    borderRadius: 24,
    borderWidth: 0.5,
    padding: spacing.lg,
  },
  sectionHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
    marginBottom: spacing.md,
  },
  sectionTitle: {
    fontSize: fontSize.body,
    fontWeight: fw.bold,
  },

  // Capabilities
  capRow: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    padding: spacing.md,
    borderRadius: 16,
    marginBottom: spacing.xs,
  },
  capInfo: { flex: 1 },
  capLabel: { fontSize: fontSize.body, fontWeight: fw.semibold },
  addCapBtn: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 4,
    paddingTop: spacing.sm,
  },
  addCapText: { fontSize: fontSize.caption1, fontWeight: fw.semibold },

  // System prompt
  promptBox: {
    borderRadius: 16,
    borderWidth: 0.5,
    padding: spacing.md,
  },
  promptInput: {
    fontSize: fontSize.subheadline,
    lineHeight: 20,
    minHeight: 140,
  },

  // Params
  paramsGrid: { gap: spacing.lg },
  paramRow: { gap: spacing.sm },
  paramHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
  },
  paramLabel: {
    fontSize: 10,
    fontWeight: '700',
    letterSpacing: 1.5,
    textTransform: 'uppercase',
  },
  paramBadge: {
    paddingHorizontal: 8,
    paddingVertical: 2,
    borderRadius: 4,
  },
  paramValue: {
    fontSize: 12,
    fontWeight: '700',
  },
  paramControls: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
  },
  paramBtn: {
    width: 28,
    height: 28,
    borderRadius: 14,
    alignItems: 'center',
    justifyContent: 'center',
  },
  paramTrack: {
    flex: 1,
    height: 6,
    borderRadius: 3,
    overflow: 'hidden',
  },
  paramFill: {
    height: '100%',
    borderRadius: 3,
  },
  paramLabels: {
    flexDirection: 'row',
    justifyContent: 'space-between',
  },
  paramEndLabel: {
    fontSize: 8,
    fontWeight: '700',
    letterSpacing: 1,
    textTransform: 'uppercase',
  },
  stopInput: {
    borderWidth: 0.5,
    borderRadius: borderRadius.input,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
    fontSize: fontSize.subheadline,
  },
  toggleRow: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    padding: spacing.lg,
    borderRadius: 16,
    borderWidth: 0.5,
  },
  toggleLabel: { fontSize: fontSize.body, fontWeight: fw.bold },
  toggleSub: { fontSize: 8, letterSpacing: 1.5, textTransform: 'uppercase', marginTop: 2 },

  // Knowledge & Files
  fieldSubLabel: {
    fontSize: 10,
    fontWeight: '700',
    letterSpacing: 1.5,
    textTransform: 'uppercase',
    marginBottom: 4,
  },
  fieldHint: {
    fontSize: fontSize.caption2,
    marginBottom: spacing.sm,
  },
  emptyField: {
    fontSize: fontSize.footnote,
    fontStyle: 'italic',
    marginBottom: spacing.sm,
  },
  fileChip: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
    paddingHorizontal: spacing.sm,
    paddingVertical: 6,
    borderRadius: borderRadius.badge,
    borderWidth: 0.5,
  },
  fileChipText: {
    fontSize: fontSize.caption1,
    fontWeight: fw.medium,
  },
  attachBtn: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 4,
    paddingVertical: spacing.sm,
    borderRadius: borderRadius.input,
    borderWidth: 1,
    borderStyle: 'dashed',
    marginTop: spacing.xs,
  },
  attachBtnText: {
    fontSize: fontSize.caption1,
    fontWeight: fw.semibold,
  },

  // Voice
  voiceGrid: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: spacing.xs,
  },
  voiceChip: {
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
    borderRadius: borderRadius.badge,
    borderWidth: 1,
  },
  voiceChipText: {
    fontSize: fontSize.caption1,
    fontWeight: fw.semibold,
    textTransform: 'capitalize',
  },

  // Tags read-only
  tagsReadOnly: { flexDirection: 'row', flexWrap: 'wrap', gap: spacing.xs },
  readTag: {
    paddingHorizontal: spacing.sm,
    paddingVertical: 4,
    borderRadius: borderRadius.badge,
  },
  readTagText: { fontSize: fontSize.caption1, fontWeight: fw.semibold },

  // Actions
  actionRow: {
    flexDirection: 'row',
    gap: spacing.sm,
    marginHorizontal: spacing.lg,
    marginBottom: spacing.lg,
  },
  cancelBtn: {
    flex: 1,
    paddingVertical: spacing.md,
    borderRadius: 999,
    borderWidth: 1,
    alignItems: 'center',
  },
  cancelText: { fontWeight: fw.bold, fontSize: 10, letterSpacing: 1.5, textTransform: 'uppercase' },
  saveBtn: {
    flex: 1.5,
    flexDirection: 'row',
    paddingVertical: spacing.md,
    borderRadius: 999,
    alignItems: 'center',
    justifyContent: 'center',
    gap: spacing.sm,
  },
  saveText: { color: '#fff', fontWeight: '700', fontSize: 10, letterSpacing: 1.5 },

  // CTA
  ctaButton: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    marginHorizontal: spacing.lg,
    paddingVertical: spacing.lg,
    borderRadius: 999,
    gap: spacing.sm,
  },
  ctaText: {
    color: '#fff',
    fontSize: fontSize.body,
    fontWeight: '700',
    letterSpacing: 1,
  },
});
