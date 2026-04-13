import { Pressable, StyleSheet, Text } from 'react-native';
import { RoleOption } from '@/constants/types';

interface Props {
  role: RoleOption;
  selected: boolean;
  tintColor: string;
  textColor: string;
  surfaceColor: string;
  onSelect: (id: string) => void;
}

export default function RoleCard({ role, selected, tintColor, textColor, surfaceColor, onSelect }: Props) {
  return (
    <Pressable
      onPress={() => onSelect(role.id)}
      style={[
        styles.card,
        {
          backgroundColor: surfaceColor,
          borderColor: selected ? tintColor : 'transparent',
          borderWidth: 2,
        },
      ]}>
      <Text style={styles.icon}>{role.icon}</Text>
      <Text style={[styles.label, { color: textColor }]}>{role.label}</Text>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  card: {
    width: '47%',
    paddingVertical: 20,
    paddingHorizontal: 12,
    borderRadius: 16,
    alignItems: 'center',
    marginBottom: 12,
  },
  icon: { fontSize: 32, marginBottom: 8 },
  label: { fontSize: 14, fontWeight: '600', textAlign: 'center' },
});
