'use client';

import SessionReplayCard from '@/components/SessionReplayCard';

export default function DashboardLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <>
      <SessionReplayCard />
      {children}
    </>
  );
}
