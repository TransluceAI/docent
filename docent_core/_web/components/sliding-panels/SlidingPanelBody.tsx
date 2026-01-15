'use client';

import React from 'react';
import { cn } from '@/lib/utils';

export function SlidingPanelBody({
  children,
  className,
}: {
  children: React.ReactNode;
  className?: string;
}) {
  return <div className={cn('p-4', className)}>{children}</div>;
}
