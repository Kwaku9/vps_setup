import { Pressable, StyleSheet, Text, View } from 'react-native';

interface Option {
  id: string;
  label: string;
  icon: string;
}

interface Props {
  title: string;
  options: Option[];
  selected: string;
  tintColor: string;
  textColor: string;
  secondaryColor: string;
  surfaceColor: string;
  onSelect: (id: string) => void;
}

export default function StyleSelector({ title, options, selected, tintColor, textColor, secondaryColor, surfaceColor, onSelect }: Props) {
  return (
    <View style={styles.container}>
      <Text style={[styles.title, { color: secondaryColor }]}>{title}</Text>
      {options.map((opt) => (
        <Pressable
          key={opt.id}
          onPress={() => onSelect(opt.id)}
          style={[
            styles.row,
            {
              backgroundColor: selected === opt.id ? tintColor + '18' : surfaceColor,
              borderColor: selected === opt.id ? tintColor : 'transparent',
              borderWidth: 1.5,
            },
          ]}>
          <Text style={styles.icon}>{opt.icon}</Text>
          <Text style={[styles.label, { color: textColor, fontWeight: selected === opt.id ? '600' : '400' }]}>
            {opt.label}
          </Text>
        </Pressable>
      ))}
    </View>
  );
}

const styles = StyleSheet.create({
  container: { marginBottom: 24 },
  title: { fontSize: 13, fontWeight: '600', textTransform: 'uppercase', marginBottom: 8, letterSpacing: 0.5 },
  row: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingVertical: 14,
    paddingHorizontal: 16,
    borderRadius: 12,
    marginBottom: 6,
  },
  icon: { fontSize: 18, marginRight: 12 },
  label: { fontSize: 15 },
});
