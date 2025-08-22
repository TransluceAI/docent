'use client';

import { Button } from '@/components/ui/button';
import { toast } from '@/hooks/use-toast';

import { logout } from '../../services/authService';
import { useUserContext } from '../../contexts/UserContext';

interface LogoutButtonProps {
  variant?:
    | 'default'
    | 'destructive'
    | 'outline'
    | 'secondary'
    | 'ghost'
    | 'link';
  size?: 'default' | 'sm' | 'lg' | 'icon';
  className?: string;
}

export const LogoutButton = ({
  variant = 'outline',
  size = 'default',
  className,
}: LogoutButtonProps) => {
  const { setUser } = useUserContext();

  const handleLogout = async () => {
    try {
      await logout(); // Pure API call
      setUser(null); // Clear client state

      toast({
        title: 'Success',
        description: 'You have been logged out successfully.',
      });

      // Redirect to login
      window.location.href = '/signup';
    } catch (error) {
      console.error('Logout failed:', error);
      toast({
        title: 'Error',
        description: 'There was an error logging out. Please try again.',
        variant: 'destructive',
      });
    }
  };

  return (
    <Button
      variant={variant}
      size={size}
      onClick={handleLogout}
      className={className}
    >
      Log Out
    </Button>
  );
};
