'use client';

import { createContext, useContext, useState, ReactNode } from 'react';
import type { User } from '../types/userTypes';

interface UserContextType {
  user: User | null;
  setUser: (user: User | null) => void;
}

const UserContext = createContext<UserContextType | undefined>(undefined);

interface UserProviderProps {
  children: ReactNode;
  user: User | null; // Can be null for non-authenticated pages
}

export const UserProvider = ({
  children,
  user: initialUser,
}: UserProviderProps) => {
  const [user, setUser] = useState<User | null>(initialUser);
  return (
    <UserContext.Provider value={{ user, setUser }}>
      {children}
    </UserContext.Provider>
  );
};

export const useUserContext = () => {
  const context = useContext(UserContext);
  if (context === undefined) {
    throw new Error('useUserContext must be used within a UserProvider');
  }
  return context;
};

export const useRequireUserContext = (): {
  user: User;
  setUser: (user: User) => void;
} => {
  const { user, setUser } = useUserContext();

  if (!user) {
    throw new Error(
      'useRequireAuth used in component without authenticated user. ' +
        'This hook should only be used in authenticated pages/components.'
    );
  }

  // Type-safe return - user is guaranteed to be non-null
  return {
    user,
    setUser: (newUser: User) => setUser(newUser), // Only allow non-null users
  };
};
