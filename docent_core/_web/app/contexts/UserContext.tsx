'use client';

import {
  createContext,
  useContext,
  useState,
  ReactNode,
  useEffect,
} from 'react';
import type { User } from '../types/userTypes';
import posthog from 'posthog-js';

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

  useEffect(() => {
    if (user) {
      console.log('Identified user:', user);
      posthog.identify(user.id);

      // Pylon chat widget
      const pylonAppId = process.env.NEXT_PUBLIC_PYLON_APP_ID;
      const pylonEmailHash = user.pylon_email_hash;
      if (pylonAppId && pylonEmailHash) {
        (window as any).pylon = {
          chat_settings: {
            app_id: pylonAppId,
            email: user.email,
            name: user.name || user.email.split('@')[0],
            email_hash: pylonEmailHash,
          },
        };

        // Load the Pylon chat widget
        if (!document.getElementById('pylon-chat-widget')) {
          const pylonScript = document.createElement('script');
          pylonScript.src = `https://widget.usepylon.com/widget/${pylonAppId}`;
          pylonScript.id = 'pylon-chat-widget';
          pylonScript.async = true;
          document.body.appendChild(pylonScript);
        }
      } else {
        console.log('Pylon chat widget not configured.');
      }
    } else {
      // Cleanup on logout: remove Pylon widget and reset PostHog
      posthog.reset();

      if ((window as any).pylon) {
        delete (window as any).pylon;
      }

      const pylonScript = document.getElementById('pylon-chat-widget');
      if (pylonScript) {
        pylonScript.remove();
      }

      const pylonElements = document.querySelectorAll('[class^="PylonChat"]');
      pylonElements.forEach((el) => el.remove());
    }
  }, [user]);

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
