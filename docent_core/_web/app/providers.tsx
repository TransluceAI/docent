'use client';
import posthog from 'posthog-js';
import { PostHogProvider } from 'posthog-js/react';
import { Provider } from 'react-redux';

import store from './store/store';

if (typeof window !== 'undefined') {
  if (
    process.env.NEXT_PUBLIC_POSTHOG_KEY &&
    process.env.NEXT_PUBLIC_POSTHOG_HOST
  ) {
    posthog.init(process.env.NEXT_PUBLIC_POSTHOG_KEY, {
      api_host: process.env.NEXT_PUBLIC_POSTHOG_HOST,
      person_profiles: 'always', // or 'always' to create profiles for anonymous users as well
      disable_session_recording: true,
      autocapture: false,
    });
    console.log('PostHog initialized');
  }
}
export function CSPostHogProvider({ children }: { children: React.ReactNode }) {
  return <PostHogProvider client={posthog}>{children}</PostHogProvider>;
}

export function ReduxProvider({ children }: { children: React.ReactNode }) {
  return <Provider store={store}>{children}</Provider>;
}
