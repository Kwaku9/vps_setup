import { Pressable, StyleSheet, Text, View } from 'react-native';

interface Props {
  icon: string;
  label: string;
  selected: boolean;
  tintColor: string;
  textColor: string;
  surfaceColor: string;
  onToggle: () => void;
}

export default function PainPointCard({ icon, label, selected, tintColor, textColor, surfaceColor, onToggle }: Props) {
  return (
    <Pressable
      onPress={onToggle}
      style={[
        styles.card,
        {
          backgroundColor: surfaceColor,
          borderColor: selected ? tintColor : 'transparent',
          borderWidth: 2,
        },
      ]}>
      <Text style={styles.icon}>{icon}</Text>
      <Text style={[styles.label, { color: textColor }]} numberOfLines={2}>{label}</Text>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  card: {
    width: '47%',
    paddingVertical: 16,
    paddingHorizontal: 10,
    borderRadius: 14,
    alignItems: 'center',
    marginBottom: 10,
  },
  icon: { fontSize: 28, marginBottom: 6 },
  label: { fontSize: 13, fontWeight: '500', textAlign: 'center' },
});
