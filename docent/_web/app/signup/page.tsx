'use client';

import { Loader2 } from 'lucide-react';
import { useState } from 'react';
import { useRouter } from 'next/navigation';

import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { ScrollArea } from '@/components/ui/scroll-area';
import { toast } from '@/hooks/use-toast';

import { signup } from '../services/authService';
import { useUserContext } from '../contexts/UserContext';

const SignupPage = () => {
  const router = useRouter();
  const { setUser } = useUserContext();
  const [email, setEmail] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);

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
      const userData = await signup(email.trim()); // Pure API call

      // Set user in context immediately to prevent race condition
      setUser(userData);

      toast({
        title: 'Welcome to Docent!',
        description: 'Your account has been created successfully.',
      });

      // Redirect to dashboard after successful signup
      router.push('/dashboard');
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
              Enter your email address to get started
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

            <Button
              type="submit"
              className="w-full"
              disabled={isSubmitting || !email.trim()}
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
              onClick={() => router.push('/login')}
              className="text-sm"
            >
              Already have an account? Sign in
            </Button>
          </div>
        </div>
      </div>
    </ScrollArea>
  );
};

export default SignupPage;
