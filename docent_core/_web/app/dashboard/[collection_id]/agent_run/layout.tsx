'use client';

import React from 'react';

import { CitationNavigationProvider } from '../rubric/[rubric_id]/NavigateToCitationContext';

export default function AgentRunLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return <CitationNavigationProvider>{children}</CitationNavigationProvider>;
}
