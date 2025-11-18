'use client';

import { CitationNavigationProvider } from '@/providers/CitationNavigationProvider';

export default function ChatLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return <CitationNavigationProvider>{children}</CitationNavigationProvider>;
}
