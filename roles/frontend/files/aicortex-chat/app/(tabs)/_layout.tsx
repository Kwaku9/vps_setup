import React from 'react';
import { Platform, StyleSheet } from 'react-native';
import { Tabs } from 'expo-router';
import { BlurView } from 'expo-blur';
import { MaterialIcons } from '@expo/vector-icons';

import Colors from '@/constants/Colors';
import { fontSize, fontWeight } from '@/constants/designTokens';
import { useColorScheme } from '@/components/useColorScheme';
import { useOnboarding } from '@/hooks/useOnboarding';

export default function TabLayout() {
  const colorScheme = useColorScheme();
  const colors = Colors[colorScheme];
  const { isComplete, isLoading } = useOnboarding();

  if (isLoading || !isComplete) {
    return null;
  }

  return (
    <Tabs
      screenOptions={{
        tabBarActiveTintColor: colors.tint,
        tabBarInactiveTintColor: colors.tabIconDefault,
        tabBarStyle: {
          position: 'absolute',
          backgroundColor: 'transparent',
          borderTopWidth: 0,
          height: Platform.OS === 'ios' ? 85 : 70,
          paddingBottom: Platform.OS === 'ios' ? 28 : 10,
          paddingTop: 8,
          elevation: 0,
        },
        tabBarBackground: () => (
          <BlurView
            intensity={80}
            tint={colorScheme === 'dark' ? 'dark' : 'light'}
            style={StyleSheet.absoluteFill}
          />
        ),
        tabBarLabelStyle: {
          fontSize: fontSize.caption2,
          fontWeight: fontWeight.medium,
          marginTop: 2,
        },
        headerStyle: {
          backgroundColor: 'transparent',
          elevation: 0,
          shadowOpacity: 0,
          borderBottomWidth: 0,
        },
        headerTransparent: true,
        // @ts-ignore — headerBlurEffect works at runtime but isn't in expo-router's BottomTab types
        headerBlurEffect: colorScheme === 'dark' ? 'dark' : 'light',
        headerTintColor: colors.text,
        headerTitleStyle: {
          fontWeight: fontWeight.semibold,
          fontSize: fontSize.headline,
          letterSpacing: -0.4,
        },
      }}>
      <Tabs.Screen
        name="agents"
        options={{
          title: 'Agents',
          headerShown: false,
          tabBarIcon: ({ color }) => (
            <MaterialIcons name="smart-toy" size={24} color={color} />
          ),
        }}
      />
      <Tabs.Screen
        name="index"
        options={{
          title: 'Chats',
          headerShown: false,
          tabBarIcon: ({ color }) => (
            <MaterialIcons name="forum" size={24} color={color} />
          ),
        }}
      />
      <Tabs.Screen
        name="discover"
        options={{
          title: 'Projects',
          headerShown: false,
          tabBarIcon: ({ color }) => (
            <MaterialIcons name="folder" size={24} color={color} />
          ),
        }}
      />
      <Tabs.Screen
        name="profile"
        options={{
          title: 'Profile',
          headerShown: false,
          tabBarIcon: ({ color }) => (
            <MaterialIcons name="person" size={24} color={color} />
          ),
        }}
      />
    </Tabs>
  );
}
