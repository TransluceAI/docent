'use client';

import { FormEvent, useState } from 'react';
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from '@/components/ui/card';
import { Label } from '@/components/ui/label';
import { Input } from '@/components/ui/input';
import { Button } from '@/components/ui/button';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { useChangePasswordMutation } from '@/app/api/settingsApi';
import { toast } from 'sonner';

export default function ChangePasswordPage() {
  const [currentPassword, setCurrentPassword] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [formError, setFormError] = useState<string | null>(null);
  const [changePassword, { isLoading }] = useChangePasswordMutation();

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setFormError(null);

    if (newPassword !== confirmPassword) {
      setFormError('New passwords do not match.');
      return;
    }

    if (!currentPassword || !newPassword) {
      setFormError('Please fill in all fields.');
      return;
    }

    try {
      await changePassword({
        old_password: currentPassword,
        new_password: newPassword,
      }).unwrap();

      setCurrentPassword('');
      setNewPassword('');
      setConfirmPassword('');

      toast.success('Your password has been changed successfully.');
    } catch (error: unknown) {
      const message =
        (typeof error === 'object' && error && 'data' in error
          ? (error as { data?: { detail?: string } }).data?.detail
          : null) || 'Unable to change password. Please try again.';
      setFormError(message);
    }
  };

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold">Change Password</h1>
        <p className="text-muted-foreground">
          Update your password to keep your Docent account secure.
        </p>
      </div>

      <form className="max-w-xl" onSubmit={handleSubmit}>
        <Card>
          <CardHeader>
            <CardTitle>Account security</CardTitle>
            <CardDescription>
              Enter your current password and a new password to update your
              account.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="current-password">Current password</Label>
              <Input
                id="current-password"
                type="password"
                autoComplete="current-password"
                value={currentPassword}
                onChange={(event) => setCurrentPassword(event.target.value)}
                required
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="new-password">New password</Label>
              <Input
                id="new-password"
                type="password"
                autoComplete="new-password"
                value={newPassword}
                onChange={(event) => setNewPassword(event.target.value)}
                required
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="confirm-password">Confirm new password</Label>
              <Input
                id="confirm-password"
                type="password"
                autoComplete="new-password"
                value={confirmPassword}
                onChange={(event) => setConfirmPassword(event.target.value)}
                required
              />
            </div>
            {formError && (
              <Alert variant="destructive">
                <AlertDescription>{formError}</AlertDescription>
              </Alert>
            )}
          </CardContent>
          <CardFooter className="justify-end">
            <Button type="submit" disabled={isLoading}>
              {isLoading ? 'Saving...' : 'Save password'}
            </Button>
          </CardFooter>
        </Card>
      </form>
    </div>
  );
}
