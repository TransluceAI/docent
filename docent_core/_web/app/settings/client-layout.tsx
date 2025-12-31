'use client';

import { Suspense } from 'react';
import SettingsSidebar from './components/SettingsSidebar';
import Breadcrumbs from '../components/Breadcrumbs';

export default function SettingsClientLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <div className="flex flex-col h-screen w-screen p-3 pt-2 space-y-2 min-h-0 min-w-[900px]">
      <Suspense fallback={<div className="h-7">Loading breadcrumbs...</div>}>
        <Breadcrumbs />
      </Suspense>
      <div className="flex-1 min-h-0 container mx-auto py-8 px-4 max-w-6xl">
        <div className="flex gap-8 h-full">
          <SettingsSidebar />
          <div className="flex-1 min-h-0 overflow-y-auto">{children}</div>
        </div>
      </div>
    </div>
  );
}
