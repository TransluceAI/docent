'use client';

import React from 'react';
import Link from 'next/link';
import { ArrowLeft, FlaskConicalIcon } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { ScrollArea } from '@/components/ui/scroll-area';
import { Separator } from '@/components/ui/separator';
import { ModeToggle } from '@/components/ui/theme-toggle';
import { UserProfile } from '@/app/components/auth/UserProfile';

interface AccessDeniedPageProps {
  title?: string;
  message?: string;
  showBackButton?: boolean;
  backButtonText?: string;
  backButtonHref?: string;
}

export default function AccessDeniedPage({
  title = 'Access Denied',
  message = 'You are not authorized to access investigator features.',
  showBackButton = true,
  backButtonText = 'Back to Dashboard',
  backButtonHref = '/dashboard',
}: AccessDeniedPageProps) {
  return (
    <ScrollArea className="h-screen">
      <div className="container mx-auto py-4 px-3 max-w-screen-xl space-y-3">
        {/* Header Section */}
        <div className="space-y-1 mb-4">
          <div className="flex justify-between items-center">
            <div>
              <div className="text-lg font-semibold tracking-tight">
                {title}
              </div>
              <div className="text-xs text-muted-foreground">{message}</div>
            </div>
            <div className="flex items-center gap-2">
              <ModeToggle />
              <UserProfile />
            </div>
          </div>
        </div>
        <Separator className="my-4" />

        {/* Main Content */}
        <div className="flex flex-col items-center justify-center py-12 space-y-6">
          <FlaskConicalIcon className="h-16 w-16 text-muted-foreground" />

          <div className="text-center space-y-2">
            <h2 className="text-xl font-semibold text-primary">
              Investigator Access Required
            </h2>
            <p className="text-sm text-muted-foreground max-w-md">{message}</p>
          </div>

          <div className="bg-red-bg border-red-border rounded-sm p-4 max-w-md">
            <div className="flex items-start gap-3">
              <FlaskConicalIcon className="h-5 w-5 text-red-text mt-0.5 flex-shrink-0" />
              <div className="flex-1">
                <h3 className="font-medium text-sm mb-1 text-red-text">
                  Authorization Required
                </h3>
                <p className="text-xs text-muted-foreground">
                  Contact info@transluce.org to request access to investigator
                  features.
                </p>
              </div>
            </div>
          </div>

          {showBackButton && (
            <Link href={backButtonHref}>
              <Button variant="outline">
                <ArrowLeft className="h-4 w-4 mr-2" />
                {backButtonText}
              </Button>
            </Link>
          )}
        </div>
      </div>
    </ScrollArea>
  );
}
