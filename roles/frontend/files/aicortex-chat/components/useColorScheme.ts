import { useColorScheme as useColorSchemeCore } from 'react-native';

export const useColorScheme = (): 'light' | 'dark' => {
  // Force dark theme to match Figma designs
  return 'dark';
};
