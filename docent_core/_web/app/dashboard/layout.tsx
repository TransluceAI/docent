'use client';

import SessionReplayCard from '@/components/SessionReplayCard';
import { MaintenanceBanner } from '@/components/MaintenanceBanner';

export default function DashboardLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <>
      <SessionReplayCard />
      <MaintenanceBanner />
      {children}
    </>
  );
}
