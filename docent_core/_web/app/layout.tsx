import { ThemeProvider } from '@/components/theme-provider';
import type { Metadata } from 'next';
import { Open_Sans, JetBrains_Mono } from 'next/font/google';
import { cn } from '@/lib/utils';

import { ReduxProvider, CSPostHogProvider } from './providers';
import { Toaster } from '@/components/ui/toaster';
import ReduxToastHandler from '@/components/ReduxToastHandler';
import { TooltipProvider } from '@/components/ui/tooltip';
import { UserProvider } from './contexts/UserContext';
import { getUser } from './services/dal';

import './globals.css';

const openSans = Open_Sans({
  subsets: ['latin'],
  display: 'swap',
  variable: '--font-open-sans',
});

const jetbrainsMono = JetBrains_Mono({
  subsets: ['latin'],
  display: 'swap',
  variable: '--font-jetbrains-mono',
});

export const metadata: Metadata = {
  title: 'Docent',
  description: 'AI-powered evaluation framework',
};

export default async function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  // Get user without requiring auth - this allows login/signup pages to work
  const user = await getUser();

  return (
    <html lang="en" className="h-full" suppressHydrationWarning>
      <body
        className={`h-full ${cn(openSans.className, jetbrainsMono.variable)}`}
      >
        <ThemeProvider
          attribute="class"
          defaultTheme="system"
          enableSystem
          disableTransitionOnChange
        >
          <CSPostHogProvider>
            <ReduxProvider>
              <UserProvider user={user}>
                <TooltipProvider delayDuration={0}>
                  {children}
                  <Toaster />
                  <ReduxToastHandler />
                </TooltipProvider>
              </UserProvider>
            </ReduxProvider>
          </CSPostHogProvider>
        </ThemeProvider>
      </body>
    </html>
  );
}
