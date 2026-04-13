// Initialize OpenTelemetry tracing before anything else loads.
// Side-effect import — registers the global tracer provider.
import '@/services/tracing';

import { DarkTheme, DefaultTheme, ThemeProvider } from '@react-navigation/native';
import { useFonts } from 'expo-font';
import { Stack, useRouter } from 'expo-router';
import * as SplashScreen from 'expo-splash-screen';
import { useEffect } from 'react';
import 'react-native-reanimated';

import Colors from '@/constants/Colors';
import { useColorScheme } from '@/components/useColorScheme';
import { useOnboarding } from '@/hooks/useOnboarding';

export { ErrorBoundary } from 'expo-router';

export const unstable_settings = {
  initialRouteName: '(tabs)',
};

SplashScreen.preventAutoHideAsync();

/** Apple Liquid Glass dark theme override. */
const LiquidGlassDark = {
  ...DarkTheme,
  colors: {
    ...DarkTheme.colors,
    primary: Colors.dark.tint,
    background: Colors.dark.background,
    card: Colors.dark.surface,
    text: Colors.dark.text,
    border: Colors.dark.outline,
    notification: Colors.dark.systemRed,
  },
};

const LiquidGlassLight = {
  ...DefaultTheme,
  colors: {
    ...DefaultTheme.colors,
    primary: Colors.light.tint,
    background: Colors.light.background,
    card: Colors.light.surface,
    text: Colors.light.text,
    border: Colors.light.outline,
    notification: Colors.light.systemRed,
  },
};

export default function RootLayout() {
  const [loaded, error] = useFonts({
    SpaceMono: require('../assets/fonts/SpaceMono-Regular.ttf'),
  });
  const { isComplete, isLoading } = useOnboarding();

  useEffect(() => {
    if (error) throw error;
  }, [error]);

  useEffect(() => {
    if (loaded && !isLoading) {
      SplashScreen.hideAsync();
    }
  }, [loaded, isLoading]);

  if (!loaded || isLoading) {
    return null;
  }

  return <RootLayoutNav onboardingComplete={isComplete} />;
}

function RootLayoutNav({ onboardingComplete }: { onboardingComplete: boolean }) {
  const router = useRouter();
  const colorScheme = useColorScheme();
  const navTheme = colorScheme === 'dark' ? LiquidGlassDark : LiquidGlassLight;

  useEffect(() => {
    if (!onboardingComplete) {
      router.replace('/onboarding' as any);
    }
  }, [onboardingComplete]);

  return (
    <ThemeProvider value={navTheme}>
      <Stack
        screenOptions={{
          headerShown: false,
          contentStyle: {
            backgroundColor: Colors[colorScheme].background,
          },
          animation: 'ios_from_right',
        }}>
        <Stack.Screen name="onboarding/index" />
        <Stack.Screen name="(tabs)" />
        <Stack.Screen name="chat/[id]" />
        <Stack.Screen name="chat/group/[id]" />
        <Stack.Screen name="agent/[id]" />
        <Stack.Screen name="pipeline" />
        <Stack.Screen name="category/[id]" />
        <Stack.Screen
          name="login"
          options={{ presentation: 'modal', animation: 'slide_from_bottom' }}
        />
      </Stack>
    </ThemeProvider>
  );
}
