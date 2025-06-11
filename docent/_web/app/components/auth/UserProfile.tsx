'use client';

import { UserRoundIcon } from 'lucide-react';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';

import { logout } from '../../services/authService';
import {
  useRequireUserContext,
  useUserContext,
} from '../../contexts/UserContext';
import { toast } from '@/hooks/use-toast';

export const UserProfile = () => {
  // User is guaranteed to be present since this component is only used in authenticated areas
  const { user } = useRequireUserContext();

  // Use base useUser for logout to access setUser that accepts null
  const { setUser } = useUserContext();

  const handleLogout = async () => {
    try {
      await logout(); // Pure API call
      setUser(null); // Clear client state
      window.location.href = '/login'; // Handle redirect
    } catch (error) {
      console.error('Logout failed:', error);
      toast({
        title: 'Logout Error',
        description: 'Failed to logout. Please try again.',
        variant: 'destructive',
      });
    }
  };

  // Get user initials from email (first letter of email)
  const getInitials = (email: string) => {
    return email.charAt(0).toUpperCase();
  };

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <div className="bg-gray-100 hover:bg-gray-200 border-gray-300 h-7 w-7 border rounded-full flex items-center justify-center cursor-pointer ">
          {user.is_anonymous ? (
            <UserRoundIcon className="text-black h-4 w-4" />
          ) : (
            <span className="text-xs font-medium text-gray-700">
              {getInitials(user.email)}
            </span>
          )}
        </div>
      </DropdownMenuTrigger>
      <DropdownMenuContent className="w-56" align="end" forceMount>
        <DropdownMenuLabel className="font-normal">
          <div className="flex flex-col space-y-1">
            <p className="text-sm font-medium leading-none">Account</p>
            <p className="text-xs leading-none text-muted-foreground">
              {user.email}
            </p>
          </div>
        </DropdownMenuLabel>
        <DropdownMenuSeparator />
        <DropdownMenuItem onClick={handleLogout}>Log out</DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
};
