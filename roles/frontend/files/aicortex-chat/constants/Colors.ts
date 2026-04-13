/**
 * AICORTEX Liquid Glass — Apple-inspired color system.
 *
 * Dark mode uses Apple's exact system colors for iOS/iPadOS.
 * Light mode uses Apple's systemGroupedBackground palette.
 */

const Colors = {
  light: {
    // Core surfaces
    text: '#000000',
    secondaryText: 'rgba(60, 60, 67, 0.6)', // secondaryLabel
    tertiaryText: 'rgba(60, 60, 67, 0.3)', // tertiaryLabel
    background: '#F2F2F7', // systemGroupedBackground
    surface: '#FFFFFF', // secondarySystemGroupedBackground
    surfaceLow: '#F2F2F7', // systemGroupedBackground
    surfaceHigh: '#FFFFFF', // elevated surface
    surfaceHighest: '#E5E5EA', // systemGray5
    // Interactive
    tint: '#007AFF', // systemBlue
    tabIconDefault: '#8E8E93', // systemGray
    tabIconSelected: '#007AFF', // systemBlue
    // Messages
    messageBubbleUser: '#007AFF', // systemBlue
    messageBubbleAgent: '#FFFFFF', // elevated surface
    messageTextUser: '#FFFFFF',
    messageTextAgent: '#000000',
    // Structure
    border: 'rgba(60, 60, 67, 0.29)', // separator
    inputBackground: 'rgba(0, 0, 0, 0.04)', // glass fill
    headerBackground: 'rgba(242, 242, 247, 0.72)', // glass nav bar
    // Semantic tokens
    primary: '#007AFF', // systemBlue
    primaryContainer: '#007AFF',
    onPrimary: '#FFFFFF',
    secondary: '#5856D6', // systemIndigo
    secondaryContainer: '#5856D6',
    tertiary: '#5AC8FA', // systemTeal
    tertiaryContainer: '#5AC8FA',
    onSurface: '#000000', // label
    onSurfaceVariant: 'rgba(60, 60, 67, 0.6)', // secondaryLabel
    outline: '#C6C6C8', // separator
    outlineVariant: '#E5E5EA', // systemGray5
    // Status
    statusOnline: '#34C759', // systemGreen
    statusBusy: '#FF9F0A', // systemOrange
    statusOffline: '#8E8E93', // systemGray
    error: '#FF3B30', // systemRed
    errorContainer: '#FF3B30',
    // Components
    cardBackground: '#FFFFFF',
    sectionLabel: 'rgba(60, 60, 67, 0.6)', // secondaryLabel
    // Glass material
    glassBorder: 'rgba(0, 0, 0, 0.08)',
    glassBackground: 'rgba(255, 255, 255, 0.72)',
    // Extended system colors
    systemIndigo: '#5856D6',
    systemPurple: '#AF52DE',
    systemGreen: '#34C759',
    systemOrange: '#FF9F0A',
    systemRed: '#FF3B30',
    systemTeal: '#5AC8FA',
    // Switch
    switchTrackActive: '#34C759', // systemGreen
    switchTrackInactive: '#E5E5EA',
  },
  dark: {
    // Core surfaces
    text: '#FFFFFF',
    secondaryText: 'rgba(235, 235, 245, 0.6)', // secondaryLabel
    tertiaryText: 'rgba(235, 235, 245, 0.3)', // tertiaryLabel
    background: '#000000', // true black (OLED)
    surface: '#1C1C1E', // secondarySystemBackground
    surfaceLow: '#1C1C1E', // secondarySystemBackground
    surfaceHigh: '#2C2C2E', // tertiarySystemBackground
    surfaceHighest: '#3A3A3C', // systemGray4
    // Interactive
    tint: '#0A84FF', // systemBlue (dark)
    tabIconDefault: '#8E8E93', // systemGray
    tabIconSelected: '#0A84FF', // systemBlue (dark)
    // Messages
    messageBubbleUser: '#0A84FF', // systemBlue (dark)
    messageBubbleAgent: '#1C1C1E', // elevated surface
    messageTextUser: '#FFFFFF',
    messageTextAgent: '#FFFFFF',
    // Structure
    border: 'rgba(84, 84, 88, 0.65)', // separator (dark)
    inputBackground: 'rgba(255, 255, 255, 0.06)', // glass fill
    headerBackground: 'rgba(0, 0, 0, 0.7)', // glass nav bar
    // Semantic tokens
    primary: '#0A84FF', // systemBlue (dark)
    primaryContainer: '#0A84FF',
    onPrimary: '#FFFFFF',
    secondary: '#5E5CE6', // systemIndigo (dark)
    secondaryContainer: '#5E5CE6',
    tertiary: '#64D2FF', // systemTeal (dark)
    tertiaryContainer: '#64D2FF',
    onSurface: '#FFFFFF', // label
    onSurfaceVariant: 'rgba(235, 235, 245, 0.6)', // secondaryLabel
    outline: '#38383A', // separator (dark)
    outlineVariant: '#2C2C2E', // tertiarySystemBackground
    // Status
    statusOnline: '#30D158', // systemGreen (dark)
    statusBusy: '#FF9F0A', // systemOrange (dark)
    statusOffline: '#8E8E93', // systemGray
    error: '#FF453A', // systemRed (dark)
    errorContainer: '#FF453A',
    // Components
    cardBackground: '#1C1C1E',
    sectionLabel: 'rgba(235, 235, 245, 0.6)', // secondaryLabel
    // Glass material
    glassBorder: 'rgba(255, 255, 255, 0.12)',
    glassBackground: 'rgba(0, 0, 0, 0.7)',
    // Extended system colors
    systemIndigo: '#5E5CE6',
    systemPurple: '#BF5AF2',
    systemGreen: '#30D158',
    systemOrange: '#FF9F0A',
    systemRed: '#FF453A',
    systemTeal: '#64D2FF',
    // Switch
    switchTrackActive: '#30D158', // systemGreen (dark)
    switchTrackInactive: '#38383A',
  },
} as const;

export default Colors;
export type ColorScheme = 'light' | 'dark';
export type ThemeColors = typeof Colors.dark;
