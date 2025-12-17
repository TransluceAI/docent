'use client';

import { useEffect, useRef, useState } from 'react';
import { toast } from 'sonner';
import { PERSISTENT_TOASTER_ID } from '@/components/ui/sonner';
import { Info } from 'lucide-react';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from '@/components/ui/dialog';
import { ReplayPreference } from '@/app/types/userTypes';
import { useLocalStorage } from 'usehooks-ts';
import { SESSION_REPLAY_PREFERENCE_KEY } from '@/app/constants';
import { usePostHog as usePostHogClient } from 'posthog-js/react';
import { useRequireUserContext } from '@/app/contexts/UserContext';

export default function SessionReplayCard() {
  const posthog = usePostHogClient();
  const { user } = useRequireUserContext();
  const [dialogOpen, setDialogOpen] = useState(false);
  const toastShownRef = useRef(false);

  const [replayPreference, setReplayPreference] =
    useLocalStorage<ReplayPreference>(
      SESSION_REPLAY_PREFERENCE_KEY + '_' + user.id,
      'loading',
      { initializeWithValue: false }
    );

  const handleFullOptIn = () => {
    setReplayPreference('full-opt-in');
    posthog.startSessionRecording();
    setDialogOpen(false);
    toast.dismiss('session-replay');
  };

  const handleMaskedOptIn = () => {
    setReplayPreference('masked-opt-in');
    posthog.startSessionRecording();
    setDialogOpen(false);
    toast.dismiss('session-replay');
  };

  const handleOptOut = () => {
    setReplayPreference('opted-out');
    posthog.stopSessionRecording();
    setDialogOpen(false);
    toast.dismiss('session-replay');
  };

  useEffect(() => {
    if (replayPreference === 'not-set' && !toastShownRef.current) {
      toastShownRef.current = true;
      toast.custom(
        (t) => (
          <div className="w-full max-w-md p-4 bg-blue-bg border border-blue-border rounded-lg shadow-lg">
            <div className="flex flex-col gap-3">
              <p className="text-sm text-primary">
                We use session recording to catch bugs and understand which
                features you enjoy. As a small team, we find these insights
                really helpful for prioritizing what to build next. We anonymize
                all analytics and mask sensitive data.
              </p>
              <div className="flex items-center justify-end gap-2">
                <Button onClick={handleFullOptIn} size="sm">
                  Accept All
                </Button>
                <Button onClick={handleOptOut} size="sm">
                  Decline All
                </Button>
                <Button
                  size="sm"
                  variant="ghost"
                  className="text-primary px-2"
                  onClick={() => setDialogOpen(true)}
                >
                  <Info className="h-4 w-4" />
                  <span>Manage Settings</span>
                </Button>
              </div>
            </div>
          </div>
        ),
        {
          id: 'session-replay',
          duration: Infinity,
          toasterId: PERSISTENT_TOASTER_ID,
        }
      );
    }
  }, [replayPreference]);

  return (
    <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle>Manage Settings</DialogTitle>
        </DialogHeader>
        <div className="space-y-4 text-sm">
          <p>
            We use session recording to see how you work with Docent and make it
            better for you.
          </p>

          <p>
            <strong>Privacy:</strong> All session recordings are anonymous. Only
            the Docent team sees your data. We will never sell your data or
            track you outside of Docent. All session recordings are deleted
            within 90 days. Change your preference anytime in Settings /
            Privacy.
          </p>

          <div className="space-y-2">
            <p className="font-bold">Full Session Recording</p>
            <ul className="list-disc pl-5 space-y-1">
              <li>
                Included: transcripts, metadata, and rubrics visible on your
                screen
              </li>
              <li>Hidden: passwords, API keys, emails</li>
            </ul>
          </div>

          <div className="space-y-2">
            <p className="font-bold">Masked Session Recording</p>
            <ul className="list-disc pl-5 space-y-1">
              <li>Included: rubrics and which features you click</li>
              <li>
                Hidden: transcripts, agent runs, metadata, passwords and
                personal data
              </li>
            </ul>
          </div>

          <p>
            Working with sensitive data? Email{' '}
            <a
              href="mailto:docent@transluce.org"
              className="underline hover:text-primary"
            >
              docent@transluce.org
            </a>{' '}
            and we&apos;ll help you self-host.
          </p>
        </div>
        <DialogFooter className="sm:justify-start border-t pt-4">
          <Button onClick={handleFullOptIn} size="sm">
            Accept Full Recording
          </Button>
          <Button onClick={handleMaskedOptIn} size="sm">
            Accept Masked Recording
          </Button>
          <Button onClick={handleOptOut} size="sm">
            Decline All
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
