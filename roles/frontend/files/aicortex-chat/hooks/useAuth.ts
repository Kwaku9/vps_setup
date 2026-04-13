/**
 * Authentication hook for AICORTEX Chat.
 *
 * Supports two modes:
 * 1. API Key — user pastes a key from Open WebUI settings
 * 2. Credentials — email/password sign-in (if login form is enabled)
 *
 * Persists the token in AsyncStorage and validates on mount.
 */

import { useState, useEffect, useCallback } from 'react';
import AsyncStorage from '@react-native-async-storage/async-storage';
import {
  setToken,
  setVoiceKey,
  getUser,
  signIn,
  type AuthUser,
} from '@/services/api';

const TOKEN_KEY = '@aicortex/auth_token';
const SERVER_KEY = '@aicortex/server_url';
const VOICE_KEY = '@aicortex/voice_key';

export function useAuth() {
  const [token, setAuthToken] = useState<string | null>(null);
  const [user, setUser] = useState<AuthUser | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const isAuthenticated = !!token && !!user;

  // Restore saved token on mount
  useEffect(() => {
    (async () => {
      try {
        const saved = await AsyncStorage.getItem(TOKEN_KEY);
        if (saved) {
          setToken(saved);
          const profile = await getUser();
          setAuthToken(saved);
          setUser(profile);
        }
        // Restore voice key if stored
        const savedVoiceKey = await AsyncStorage.getItem(VOICE_KEY);
        if (savedVoiceKey) {
          setVoiceKey(savedVoiceKey);
        }
      } catch {
        // Token expired or invalid — clear it
        await AsyncStorage.removeItem(TOKEN_KEY);
      } finally {
        setIsLoading(false);
      }
    })();
  }, []);

  /** Authenticate with an API key (sk-...) */
  const loginWithApiKey = useCallback(async (apiKey: string) => {
    setIsLoading(true);
    setError(null);
    try {
      setToken(apiKey);
      const profile = await getUser();
      await AsyncStorage.setItem(TOKEN_KEY, apiKey);
      setAuthToken(apiKey);
      setUser(profile);
    } catch (err: any) {
      setToken(null);
      setError(err.message || 'Invalid API key');
      throw err;
    } finally {
      setIsLoading(false);
    }
  }, []);

  /** Authenticate with email/password */
  const loginWithCredentials = useCallback(
    async (email: string, password: string) => {
      setIsLoading(true);
      setError(null);
      try {
        const { token: jwt } = await signIn(email, password);
        setToken(jwt);
        const profile = await getUser();
        await AsyncStorage.setItem(TOKEN_KEY, jwt);
        setAuthToken(jwt);
        setUser(profile);
      } catch (err: any) {
        setToken(null);
        setError(err.message || 'Sign in failed');
        throw err;
      } finally {
        setIsLoading(false);
      }
    },
    [],
  );

  /** Sign out and clear stored credentials */
  const logout = useCallback(async () => {
    setToken(null);
    setAuthToken(null);
    setUser(null);
    await AsyncStorage.removeItem(TOKEN_KEY);
  }, []);

  /** Save the server URL */
  const setServerUrl = useCallback(async (url: string) => {
    await AsyncStorage.setItem(SERVER_KEY, url);
  }, []);

  /** Get the saved server URL */
  const getServerUrl = useCallback(async (): Promise<string | null> => {
    return AsyncStorage.getItem(SERVER_KEY);
  }, []);

  /** Save a scoped voice session key (LiteLLM virtual key for Gemini Live). */
  const saveVoiceKey = useCallback(async (key: string) => {
    setVoiceKey(key);
    await AsyncStorage.setItem(VOICE_KEY, key);
  }, []);

  return {
    token,
    user,
    isAuthenticated,
    isLoading,
    error,
    loginWithApiKey,
    loginWithCredentials,
    logout,
    setServerUrl,
    getServerUrl,
    saveVoiceKey,
  };
}
