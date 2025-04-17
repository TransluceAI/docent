import { Inter, Open_Sans, JetBrains_Mono } from 'next/font/google';
import './globals.css';
import { CSPostHogProvider, ReduxProvider } from './providers';
import { cn } from '@/lib/utils';

import { Metadata } from 'next';
import { FrameGridProvider } from './contexts/FrameGridContext';
import { Toaster } from '@/components/ui/toaster';

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
            <FrameGridProvider>
              {children}
              <Toaster />
            </FrameGridProvider>
          </ReduxProvider>
        </CSPostHogProvider>
      </body>
    </html>
  );
}
