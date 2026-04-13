import React, { useState } from 'react';
import {
  Pressable,
  StyleSheet,
  Text,
  TextInput,
  View,
} from 'react-native';
import { MaterialIcons } from '@expo/vector-icons';
import Colors from '@/constants/Colors';
import { useColorScheme } from '@/components/useColorScheme';
import { spacing, borderRadius, fontSize, fontWeight as fw } from '@/constants/designTokens';

interface Props {
  tags: string[];
  onChange: (tags: string[]) => void;
  placeholder?: string;
}

export default function TagInput({ tags, onChange, placeholder = 'Add tag...' }: Props) {
  const colorScheme = useColorScheme();
  const colors = Colors[colorScheme];
  const [input, setInput] = useState('');

  const addTag = () => {
    const trimmed = input.trim().toLowerCase();
    if (trimmed && !tags.includes(trimmed)) {
      onChange([...tags, trimmed]);
    }
    setInput('');
  };

  const removeTag = (tag: string) => {
    onChange(tags.filter((t) => t !== tag));
  };

  return (
    <View style={styles.container}>
      <View style={styles.tagsWrap}>
        {tags.map((tag) => (
          <View
            key={tag}
            style={[styles.tag, { backgroundColor: colors.tint + '20' }]}>
            <Text style={[styles.tagLabel, { color: colors.tint }]}>
              {tag}
            </Text>
            <Pressable onPress={() => removeTag(tag)} hitSlop={8}>
              <MaterialIcons name="close" size={14} color={colors.tint} />
            </Pressable>
          </View>
        ))}
      </View>
      <View
        style={[
          styles.inputRow,
          {
            backgroundColor: colors.inputBackground,
            borderColor: colors.glassBorder,
          },
        ]}>
        <TextInput
          value={input}
          onChangeText={setInput}
          onSubmitEditing={addTag}
          placeholder={placeholder}
          placeholderTextColor={colors.secondaryText}
          style={[styles.input, { color: colors.text }]}
          returnKeyType="done"
          autoCapitalize="none"
        />
        {input.trim() ? (
          <Pressable onPress={addTag} hitSlop={8}>
            <MaterialIcons name="add-circle" size={22} color={colors.tint} />
          </Pressable>
        ) : null}
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  container: { gap: spacing.sm },
  tagsWrap: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: spacing.xs,
  },
  tag: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 4,
    paddingHorizontal: spacing.sm,
    paddingVertical: 4,
    borderRadius: borderRadius.badge,
  },
  tagLabel: {
    fontSize: fontSize.caption1,
    fontWeight: fw.semibold,
  },
  inputRow: {
    flexDirection: 'row',
    alignItems: 'center',
    borderWidth: 0.5,
    borderRadius: borderRadius.input,
    paddingHorizontal: spacing.md,
    height: 36,
  },
  input: {
    flex: 1,
    fontSize: fontSize.subheadline,
  },
});
