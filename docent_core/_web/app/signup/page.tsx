'use client';

import { Loader2 } from 'lucide-react';
import { Suspense, useState } from 'react';
import { useRouter, useSearchParams } from 'next/navigation';

import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { ScrollArea } from '@/components/ui/scroll-area';
import { toast } from '@/hooks/use-toast';

import { signup } from '../services/authService';
import { useUserContext } from '../contexts/UserContext';

function SignupPageContent() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const { setUser } = useUserContext();
  const redirectParam = searchParams.get('redirect') || '';
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();

    setIsSubmitting(true);
    try {
      const userData = await signup(email.trim(), password.trim()); // Pure API call

      // Set user in context immediately to prevent race condition
      setUser(userData);

      // Force a full page navigation to ensure cookie is processed
      const redirectUrl = redirectParam || '/dashboard';
      window.location.href = redirectUrl;
    } catch (error: any) {
      console.error('Failed to sign up:', error);

      // Handle API error responses
      const message =
        error.response?.data?.detail || error.message || 'Signup failed';

      if (
        message.includes('already exists') ||
        error.response?.status === 409
      ) {
        toast({
          title: 'Account Already Exists',
          description:
            'A user with this email already exists. Please log in instead.',
          variant: 'destructive',
        });
      } else {
        toast({
          title: 'Error',
          description: message,
          variant: 'destructive',
        });
      }
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <ScrollArea className="h-screen">
      <div className="container mx-auto py-8 px-4 max-w-md">
        <div className="space-y-6">
          {/* Header */}
          <div className="text-center space-y-2">
            <h1 className="text-2xl font-bold tracking-tight">
              Create your Docent account
            </h1>
            <p className="text-sm text-gray-600">
              Enter your email and password to get started
            </p>
          </div>

          {/* Signup Form */}
          <form onSubmit={handleSubmit} className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="email">Email Address</Label>
              <Input
                id="email"
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="Enter your email address"
                disabled={isSubmitting}
                required
              />
            </div>

            <div className="space-y-2">
              <Label htmlFor="password">Password</Label>
              <Input
                id="password"
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="Enter your password"
                disabled={isSubmitting}
                required
              />
            </div>

            <Button
              type="submit"
              className="w-full"
              disabled={isSubmitting || !email.trim() || !password.trim()}
            >
              {isSubmitting ? (
                <>
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                  Creating account...
                </>
              ) : (
                'Create Account'
              )}
            </Button>
          </form>

          {/* Link to Login */}
          <div className="text-center">
            <Button
              variant="ghost"
              onClick={() => {
                const loginUrl = redirectParam
                  ? `/login?redirect=${encodeURIComponent(redirectParam)}`
                  : '/login';
                router.push(loginUrl);
              }}
              className="text-sm"
            >
              Already have an account? Sign in
            </Button>
          </div>
        </div>
      </div>
    </ScrollArea>
  );
}

const SignupPage = () => {
  return (
    <Suspense>
      <SignupPageContent />
    </Suspense>
  );
};

export default SignupPage;
