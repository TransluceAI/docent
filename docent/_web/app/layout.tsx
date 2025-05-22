import { Open_Sans, JetBrains_Mono } from 'next/font/google';

import './globals.css';
import ReduxToastHandler from '@/components/ReduxToastHandler';
import { Toaster } from '@/components/ui/toaster';
import { cn } from '@/lib/utils';

import WebsocketProvider from './contexts/WebsocketContext';
import { CSPostHogProvider, ReduxProvider } from './providers';

import { Metadata } from 'next';
import { TooltipProvider } from '@radix-ui/react-tooltip';


const openSans = Open_Sans({
  subsets: ['latin'],
  display: 'swap',
});

const jetbrainsMono = JetBrains_Mono({
  subsets: ['latin'],
  variable: '--font-jetbrains-mono',
  display: 'swap',
});

export const metadata: Metadata = {
  title: 'Transluce Docent',
  description: 'Docent',
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" className="h-full">
      <body
        className={`h-full ${cn(openSans.className, jetbrainsMono.variable)}`}
      >
        <CSPostHogProvider>
          <ReduxProvider>
            <WebsocketProvider>
              <TooltipProvider>
                {children}
                <Toaster />
                <ReduxToastHandler />
              </TooltipProvider>
            </WebsocketProvider>
          </ReduxProvider>
        </CSPostHogProvider>
      </body>
    </html>
  );
}
