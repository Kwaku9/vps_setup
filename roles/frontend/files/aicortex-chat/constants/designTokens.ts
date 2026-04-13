/**
 * AICORTEX Liquid Glass — Apple Dynamic Type design tokens.
 *
 * Spacing uses a 4px base unit. Typography follows Apple's
 * Dynamic Type scale. Corner radii follow Apple's concentric
 * hierarchy (display > card > button > badge).
 */

export const spacing = {
  xs: 4,
  sm: 8,
  md: 12,
  lg: 16,
  xl: 20,
  '2xl': 24,
  '3xl': 32,
  '4xl': 40,
  '5xl': 48,
} as const;

export const borderRadius = {
  sm: 8,
  md: 12,
  lg: 16,
  xl: 18, // message bubbles
  '2xl': 24,
  full: 9999,
  // Apple concentric hierarchy
  card: 16,
  sheet: 16,
  button: 14,
  buttonSmall: 10,
  input: 12,
  badge: 8,
  codeBlock: 12,
  chatBubble: 18,
  chatBubbleSequential: 6,
  avatar: 9999,
} as const;

// Apple Dynamic Type scale
export const fontSize = {
  caption2: 11,
  caption1: 12,
  footnote: 13,
  subheadline: 15,
  callout: 16,
  body: 17,
  headline: 17,
  title3: 20,
  title2: 22,
  title1: 28,
  largeTitle: 34,
  // Aliases for backward compat
  xs: 11,
  sm: 12,
  md: 13,
  base: 17,
  lg: 20,
  xl: 22,
  '2xl': 28,
  '3xl': 34,
  '4xl': 34,
  '5xl': 40,
  display: 34,
} as const;

export const fontWeight = {
  regular: '400' as const,
  medium: '500' as const,
  semibold: '600' as const,
  bold: '700' as const,
  extrabold: '800' as const,
};

// Apple tracking values
export const letterSpacing = {
  tight: -0.4,
  normal: -0.2,
  wide: 0,
  wider: 0.1,
  widest: 0.1,
} as const;

// Apple-style animation durations (ms)
export const animation = {
  instant: 100,
  fast: 150,
  medium: 250,
  standard: 350,
  slow: 500,
  messageAppear: 200,
  sheetPresentation: 300,
  pageTransition: 350,
  typingIndicator: 600,
} as const;

// Touch targets (Apple minimum 44pt)
export const touchTarget = {
  minimum: 44,
  comfortable: 48,
  large: 56,
  listItem: 44,
  tabBar: 49,
  navBar: 44,
} as const;

// Component dimensions
export const dimensions = {
  tabBarHeight: 49,
  navBarHeight: 44,
  searchBarHeight: 36,
  dragHandleWidth: 36,
  dragHandleHeight: 5,
  sendButtonSize: 32,
  avatarSmall: 32,
  avatarMedium: 40,
  avatarLarge: 56,
  maxContentWidth: 672,
  sidebarWidth: 320,
} as const;
