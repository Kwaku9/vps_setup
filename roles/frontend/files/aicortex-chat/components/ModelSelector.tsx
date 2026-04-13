import React, { useEffect, useMemo, useState } from 'react';
import {
  FlatList,
  Modal,
  Pressable,
  StyleSheet,
  Text,
  TextInput,
  View,
} from 'react-native';
import { MaterialIcons } from '@expo/vector-icons';
import Colors from '@/constants/Colors';
import { useColorScheme } from '@/components/useColorScheme';
import { getModels, type Model } from '@/services/api';
import { spacing, borderRadius, fontSize, fontWeight as fw } from '@/constants/designTokens';

interface Props {
  visible: boolean;
  selectedModelId: string;
  onSelect: (modelId: string, modelName: string) => void;
  onClose: () => void;
}

export default function ModelSelector({
  visible,
  selectedModelId,
  onSelect,
  onClose,
}: Props) {
  const colorScheme = useColorScheme();
  const colors = Colors[colorScheme];
  const [models, setModels] = useState<Model[]>([]);
  const [search, setSearch] = useState('');

  useEffect(() => {
    if (visible) {
      getModels().then(setModels).catch(() => {});
    }
  }, [visible]);

  const filtered = useMemo(() => {
    const q = search.toLowerCase();
    if (!q) return models;
    return models.filter(
      (m) =>
        m.name.toLowerCase().includes(q) ||
        m.id.toLowerCase().includes(q) ||
        (m.owned_by ?? '').toLowerCase().includes(q),
    );
  }, [models, search]);

  // Group by provider
  const grouped = useMemo(() => {
    const map = new Map<string, Model[]>();
    for (const m of filtered) {
      const provider = m.owned_by ?? m.id.split('/')[0] ?? 'Other';
      const list = map.get(provider) ?? [];
      list.push(m);
      map.set(provider, list);
    }
    // Flatten with section headers
    const result: Array<{ type: 'header'; label: string } | { type: 'model'; model: Model }> = [];
    for (const [provider, list] of map) {
      result.push({ type: 'header', label: provider });
      list.forEach((model) => result.push({ type: 'model', model }));
    }
    return result;
  }, [filtered]);

  return (
    <Modal visible={visible} animationType="slide" transparent>
      <View style={[styles.overlay, { backgroundColor: 'rgba(0,0,0,0.7)' }]}>
        <View
          style={[
            styles.sheet,
            {
              backgroundColor: colors.surface,
              borderColor: colors.glassBorder,
            },
          ]}>
          {/* Header */}
          <View style={styles.sheetHeader}>
            <Text style={[styles.sheetTitle, { color: colors.text }]}>
              Select Base Model
            </Text>
            <Pressable onPress={onClose} hitSlop={12}>
              <MaterialIcons name="close" size={24} color={colors.secondaryText} />
            </Pressable>
          </View>

          {/* Search */}
          <View
            style={[
              styles.searchRow,
              {
                backgroundColor: colors.inputBackground,
                borderColor: colors.glassBorder,
              },
            ]}>
            <MaterialIcons name="search" size={18} color={colors.secondaryText} />
            <TextInput
              placeholder="Search models..."
              placeholderTextColor={colors.secondaryText}
              style={[styles.searchInput, { color: colors.text }]}
              value={search}
              onChangeText={setSearch}
              autoFocus
            />
          </View>

          {/* List */}
          <FlatList
            data={grouped}
            keyExtractor={(item, idx) =>
              item.type === 'header' ? `h-${item.label}` : `m-${item.model.id}-${idx}`
            }
            contentContainerStyle={styles.listContent}
            renderItem={({ item }) => {
              if (item.type === 'header') {
                return (
                  <Text
                    style={[styles.sectionHeader, { color: colors.secondaryText }]}>
                    {item.label.toUpperCase()}
                  </Text>
                );
              }
              const m = item.model;
              const isSelected = m.id === selectedModelId;
              return (
                <Pressable
                  onPress={() => onSelect(m.id, m.name)}
                  style={[
                    styles.modelRow,
                    {
                      backgroundColor: isSelected
                        ? colors.tint + '15'
                        : 'transparent',
                      borderColor: isSelected ? colors.tint + '30' : 'transparent',
                    },
                  ]}>
                  <View style={styles.modelInfo}>
                    <Text
                      style={[
                        styles.modelName,
                        { color: isSelected ? colors.tint : colors.text },
                      ]}
                      numberOfLines={1}>
                      {m.name}
                    </Text>
                    <Text
                      style={[styles.modelId, { color: colors.secondaryText }]}
                      numberOfLines={1}>
                      {m.id}
                    </Text>
                  </View>
                  {isSelected && (
                    <MaterialIcons name="check-circle" size={20} color={colors.tint} />
                  )}
                </Pressable>
              );
            }}
          />
        </View>
      </View>
    </Modal>
  );
}

const styles = StyleSheet.create({
  overlay: {
    flex: 1,
    justifyContent: 'flex-end',
  },
  sheet: {
    maxHeight: '80%',
    borderTopLeftRadius: 24,
    borderTopRightRadius: 24,
    borderWidth: 0.5,
    borderBottomWidth: 0,
  },
  sheetHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    paddingHorizontal: spacing.lg,
    paddingTop: spacing.lg,
    paddingBottom: spacing.md,
  },
  sheetTitle: {
    fontSize: fontSize.title3,
    fontWeight: fw.bold,
  },
  searchRow: {
    flexDirection: 'row',
    alignItems: 'center',
    marginHorizontal: spacing.lg,
    borderRadius: borderRadius.input,
    borderWidth: 0.5,
    paddingHorizontal: spacing.md,
    height: 40,
    marginBottom: spacing.md,
    gap: spacing.sm,
  },
  searchInput: {
    flex: 1,
    fontSize: fontSize.subheadline,
  },
  listContent: {
    paddingHorizontal: spacing.lg,
    paddingBottom: 40,
  },
  sectionHeader: {
    fontSize: fontSize.caption2,
    fontWeight: fw.bold,
    letterSpacing: 1.5,
    marginTop: spacing.lg,
    marginBottom: spacing.xs,
    paddingHorizontal: spacing.xs,
  },
  modelRow: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingVertical: spacing.md,
    paddingHorizontal: spacing.sm,
    borderRadius: borderRadius.input,
    borderWidth: 1,
    marginBottom: 2,
  },
  modelInfo: {
    flex: 1,
  },
  modelName: {
    fontSize: fontSize.body,
    fontWeight: fw.semibold,
  },
  modelId: {
    fontSize: fontSize.caption2,
    marginTop: 1,
  },
});
