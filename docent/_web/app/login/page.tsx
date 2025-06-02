'use client';

import { Suspense, useState, useEffect } from 'react';
import { useRouter, useSearchParams } from 'next/navigation';
import { Loader2 } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { ScrollArea } from '@/components/ui/scroll-area';
import { toast } from '@/hooks/use-toast';

import { login } from '../services/authService';
import { useUser } from '../contexts/UserContext';

function LoginPageContent() {
  const router = useRouter();
  const { setUser } = useUser();
  const searchParams = useSearchParams();
  const emailParam = searchParams.get('email') || '';

  // Form state
  const [email, setEmail] = useState(emailParam);
  const [isSubmitting, setIsSubmitting] = useState(false);

  useEffect(() => {
    setEmail(emailParam);
  }, [emailParam]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();

    if (!email.trim()) {
      toast({
        title: 'Error',
        description: 'Please enter a valid email address',
        variant: 'destructive',
      });
      return;
    }

    setIsSubmitting(true);
    try {
      const userData = await login(email.trim()); // Pure API call

      // Set user in context immediately to prevent race condition
      setUser(userData);

      toast({
        title: 'Success',
        description: 'Welcome back!',
      });

      // Redirect to dashboard after successful login
      console.log("USUKE")
      router.push('/dashboard');
    } catch (error: any) {
      console.error('Failed to log in:', error);

      // Handle API error responses
      const message =
        error.response?.data?.detail || error.message || 'Login failed';

      if (message.includes('not found') || error.response?.status === 404) {
        toast({
          title: 'User not found',
          description:
            'No account found with that email address. Please sign up first.',
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
              Sign in to Docent
            </h1>
            <p className="text-sm text-gray-600">
              Enter your email address to sign in
            </p>
          </div>

          {/* Login Form */}
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

            <Button
              type="submit"
              className="w-full"
              disabled={isSubmitting || !email.trim()}
            >
              {isSubmitting ? (
                <>
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                  Signing in...
                </>
              ) : (
                'Sign In'
              )}
            </Button>
          </form>

          {/* Link to Signup */}
          <div className="text-center">
            <Button
              variant="ghost"
              onClick={() => router.push('/signup')}
              className="text-sm"
            >
              Don&apos;t have an account? Sign up
            </Button>
          </div>
        </div>
      </div>
    </ScrollArea>
  );
}

export default function LoginPage() {
  return (
    <Suspense
      fallback={
        <div className="min-h-screen flex items-center justify-center">
          <div>Loading...</div>
        </div>
      }
    >
      <LoginPageContent />
    </Suspense>
  );
}
