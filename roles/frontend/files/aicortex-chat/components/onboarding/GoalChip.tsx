import { Pressable, StyleSheet, Text } from 'react-native';

interface Props {
  label: string;
  selected: boolean;
  tintColor: string;
  textColor: string;
  surfaceColor: string;
  onToggle: () => void;
}

export default function GoalChip({ label, selected, tintColor, textColor, surfaceColor, onToggle }: Props) {
  return (
    <Pressable
      onPress={onToggle}
      style={[
        styles.chip,
        {
          backgroundColor: selected ? tintColor : surfaceColor,
          borderColor: selected ? tintColor : surfaceColor,
        },
      ]}>
      {selected && <Text style={styles.check}>✓ </Text>}
      <Text style={[styles.label, { color: selected ? '#fff' : textColor }]}>{label}</Text>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  chip: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingHorizontal: 16,
    paddingVertical: 10,
    borderRadius: 20,
    borderWidth: 1,
    marginRight: 8,
    marginBottom: 10,
  },
  check: { color: '#fff', fontSize: 14, fontWeight: '700' },
  label: { fontSize: 14, fontWeight: '500' },
});
