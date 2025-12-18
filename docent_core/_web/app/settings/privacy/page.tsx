'use client';

import { useLocalStorage } from 'usehooks-ts';
import { usePostHog } from 'posthog-js/react';
import {
  Card,
  CardContent,
  CardTitle,
  CardHeader,
  CardDescription,
} from '@/components/ui/card';
import { RadioGroup, RadioGroupItem } from '@/components/ui/radio-group';
import { ReplayPreference } from '@/app/types/userTypes';
import { SESSION_REPLAY_PREFERENCE_KEY } from '@/app/constants';
import { useRequireUserContext } from '@/app/contexts/UserContext';
import { maskInputFn } from '@/app/providers';

export default function PrivacySettingsPage() {
  const posthog = usePostHog();
  const { user } = useRequireUserContext();

  const [replayPreference, setReplayPreference] =
    useLocalStorage<ReplayPreference>(
      SESSION_REPLAY_PREFERENCE_KEY + '_' + user.id,
      'loading',
      { initializeWithValue: false }
    );

  const handleValueChange = (value: string) => {
    const preference = value as ReplayPreference;
    setReplayPreference(preference);

    const maskTextSelector =
      preference !== 'full-opt-in'
        ? '.agent-run-viewer, .metadata, .agent-run-table'
        : '';

    // Stop session recording before updating configuration to ensure changes take effect
    posthog.stopSessionRecording();

    posthog.set_config({
      session_recording: {
        maskAllInputs: true,
        maskInputFn,
        maskTextSelector,
      },
    });

    if (preference !== 'opted-out') {
      posthog.startSessionRecording();
    }
  };

  const currentValue =
    replayPreference === 'loading' || replayPreference === 'not-set'
      ? ''
      : replayPreference;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold">Privacy</h1>
        <p className="text-muted-foreground">
          Manage how we collect and use your data.
        </p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Session Replay Preferences</CardTitle>
          <CardDescription className="text-sm text-muted-foreground">
            We use PostHog to record user sessions to improve our product. This
            helps us understand how you use the application and identify issues.
            {replayPreference === 'not-set' && (
              <span className="text-sm text-muted-foreground italic">
                {' '}
                Your replay preference is not set. Defaulting to opt-out.
              </span>
            )}
          </CardDescription>
        </CardHeader>
        <CardContent>
          <RadioGroup
            value={currentValue}
            onValueChange={handleValueChange}
            disabled={replayPreference === 'loading'}
            className="space-y-2"
          >
            <div className="flex items-start space-x-3 space-y-0">
              <RadioGroupItem value="full-opt-in" id="full-opt-in" />

              <p className="text-sm">
                <span className="font-semibold">Full:</span> Record transcripts,
                metadata, and rubrics visible on your screen. Passwords, API
                keys, and emails are hidden.
              </p>
            </div>

            <div className="flex items-start space-x-3 space-y-0">
              <RadioGroupItem value="masked-opt-in" id="masked-opt-in" />

              <p className="text-sm">
                <span className="font-semibold">Masked:</span> Record which
                rubrics and which features you click. Transcripts, agent runs,
                metadata, passwords and personal data are hidden.
              </p>
            </div>

            <div className="flex items-start space-x-3 space-y-0">
              <RadioGroupItem
                value="opted-out"
                disabled={replayPreference === 'loading'}
                id="opted-out"
              />
              <p className="text-sm">
                <span className="font-semibold">Disabled</span>: Don&apos;t
                record any session data.
              </p>
            </div>
          </RadioGroup>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Data Deletion Requests</CardTitle>
          <CardDescription className="text-sm text-muted-foreground">
            You have the right to request deletion of your personal data in
            accordance with GDPR and CCPA regulations. For more details, see our{' '}
            <a
              href="https://trust.transluce.org"
              target="_blank"
              rel="noopener noreferrer"
              className="text-blue-text hover:underline font-medium"
            >
              privacy statement
            </a>
            .
          </CardDescription>
        </CardHeader>
        <CardContent>
          <p className="text-sm text-muted-foreground">
            To request deletion of your personal data, please contact us at{' '}
            <a
              href="mailto:info@transluce.org"
              className="text-blue-text hover:underline font-medium"
            >
              info@transluce.org
            </a>
            . We will process your request in accordance with applicable
            regulations.
          </p>
        </CardContent>
      </Card>
    </div>
  );
}
