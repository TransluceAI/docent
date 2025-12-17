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
// import { useRouter } from 'next/navigation';

import { logout } from '../../services/authService';
import {
  useRequireUserContext,
  useUserContext,
} from '../../contexts/UserContext';
import { toast } from 'sonner';

export const UserProfile = () => {
  // User is guaranteed to be present since this component is only used in authenticated areas
  const { user } = useRequireUserContext();

  // const router = useRouter();

  // Use base useUser for logout to access setUser that accepts null
  const { setUser } = useUserContext();

  const handleLogout = async () => {
    try {
      await logout(); // Pure API call
      setUser(null); // Clear client state
      // router.push('/signup'); // Handle redirect
      window.location.href = '/signup'; // Handle redirect
    } catch (error) {
      console.error('Logout failed:', error);
      toast.error('Failed to logout. Please try again.');
    }
  };

  // Get user initials from email (first letter of email)
  const getInitials = (email: string) => {
    return email.charAt(0).toUpperCase();
  };

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <div className="bg-muted hover:bg-accent border-border h-7 w-7 border rounded-full flex items-center justify-center cursor-pointer ">
          {user.is_anonymous ? (
            <UserRoundIcon className="text-primary h-4 w-4" />
          ) : (
            <span className="text-xs font-medium text-primary">
              {getInitials(user.email)}
            </span>
          )}
        </div>
      </DropdownMenuTrigger>
      <DropdownMenuContent className="w-56" align="end" forceMount>
        <DropdownMenuLabel className="font-normal text-xs">
          <div className="flex flex-col space-y-1">
            <p className="text-sm font-medium leading-none">Account</p>
            <p className="text-[11px] leading-none text-muted-foreground">
              {user.email}
            </p>
          </div>
        </DropdownMenuLabel>
        <DropdownMenuSeparator />
        <DropdownMenuItem asChild className="text-sm">
          <a href="/settings">Settings</a>
        </DropdownMenuItem>
        <DropdownMenuItem onClick={handleLogout} className="text-sm">
          Log out
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
};
