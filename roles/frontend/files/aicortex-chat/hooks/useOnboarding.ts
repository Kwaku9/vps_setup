import { useCallback, useEffect, useSyncExternalStore } from 'react';
import { OnboardingState, OnboardingAnswers } from '@/constants/types';
import { getItem, setItem, removeItem, STORAGE_KEYS } from '@/services/storage';

let state: OnboardingState = {
  isComplete: false,
  answers: null,
  completedAt: null,
};
let isLoading = true;
let listeners = new Set<() => void>();

function emit() {
  listeners.forEach((l) => l());
}

function getSnapshot() {
  return state;
}

function subscribe(listener: () => void) {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

async function loadFromStorage() {
  const stored = await getItem<OnboardingState>(STORAGE_KEYS.onboarding);
  if (stored) {
    state = stored;
  }
  isLoading = false;
  emit();
}

// Kick off loading immediately (guard for SSR/web)
if (typeof window !== 'undefined') {
  loadFromStorage();
}

export function useOnboarding() {
  const data = useSyncExternalStore(subscribe, getSnapshot, getSnapshot);

  useEffect(() => {
    loadFromStorage();
  }, []);

  const completeOnboarding = useCallback(async (answers: OnboardingAnswers) => {
    state = {
      isComplete: true,
      answers,
      completedAt: Date.now(),
    };
    emit();
    await setItem(STORAGE_KEYS.onboarding, state);
  }, []);

  const resetOnboarding = useCallback(async () => {
    state = { isComplete: false, answers: null, completedAt: null };
    isLoading = false;
    emit();
    await removeItem(STORAGE_KEYS.onboarding);
    await removeItem(STORAGE_KEYS.experts);
    await removeItem(STORAGE_KEYS.agents_cache);
    await removeItem(STORAGE_KEYS.conversations);
  }, []);

  return {
    isComplete: data.isComplete,
    answers: data.answers,
    isLoading,
    completeOnboarding,
    resetOnboarding,
  };
}
