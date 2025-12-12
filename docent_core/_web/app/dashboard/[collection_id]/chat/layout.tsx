'use client';

import { CitationNavigationProvider } from '@/providers/CitationNavigationProvider';

export default function ChatsLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return <CitationNavigationProvider>{children}</CitationNavigationProvider>;
}
