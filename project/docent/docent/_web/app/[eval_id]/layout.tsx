'use client';

import Breadcrumbs from '../components/Breadcrumbs';
import React, { useEffect, Suspense, useState, useRef } from 'react';
import { useParams } from 'next/navigation';
import { RotateCcw } from 'lucide-react';
import { ZoomOut } from 'lucide-react';
import { useAppDispatch, useAppSelector } from '../store/hooks';
import { initSession, resetFrameSlice } from '../store/frameSlice';

function ResponsiveCheck({ children }: { children: React.ReactNode }) {
  const [dimensions, setDimensions] = useState<{
    width?: number;
    isPortrait?: boolean;
  }>({});

  useEffect(() => {
    // Function to update window dimensions
    const updateDimensions = () => {
      setDimensions({
        width: window.innerWidth,
        isPortrait: window.innerHeight > window.innerWidth,
      });
    };

    // Set initial dimensions and add event listener
    updateDimensions();
    window.addEventListener('resize', updateDimensions);

    // Clean up
    return () => window.removeEventListener('resize', updateDimensions);
  }, []);

  // Don't render anything during SSR or if dimensions aren't available
  if (typeof dimensions.width === 'undefined') {
    return <>{children}</>;
  }

  // If screen is wide enough, just render children
  const MIN_WIDTH = 900;
  if (dimensions.width >= MIN_WIDTH) {
    return <>{children}</>;
  }

  // Mobile detection
  const isMobile = /iPhone|iPad|iPod|Android/i.test(navigator.userAgent);
  const isPortraitMobile = isMobile && dimensions.isPortrait;

  return (
    <div className="fixed inset-0 bg-black/90 text-white flex flex-col justify-center items-center z-50 p-6 text-center">
      <div className="max-w-md space-y-4">
        <h2 className="text-xl font-semibold">Display Size Warning</h2>

        <div className="space-y-2">
          <p className="text-sm">
            This dashboard is designed for larger screens.
          </p>
          <p className="text-sm">
            {isPortraitMobile
              ? 'Please rotate your device to landscape mode for a better experience.'
              : 'Please use a device with a wider display or zoom out for a better experience.'}
          </p>
        </div>

        <div className="flex justify-center mt-4">
          {isPortraitMobile ? (
            <div className="animate-[spin_2s_ease-in-out_infinite]">
              <RotateCcw className="h-10 w-10 text-blue-400" />
            </div>
          ) : (
            <ZoomOut className="h-8 w-8 text-blue-400" />
          )}
        </div>
      </div>
    </div>
  );
}

function DocentLayoutContent({ children }: { children: React.ReactNode }) {
  const dispatch = useAppDispatch();
  const params = useParams();
  const evalId = params.eval_id as string;

  // Fetch state from the server
  const fetchRef = React.useRef(false); // Prevent double fetch
  useEffect(() => {
    if (!evalId || fetchRef.current) {
      return;
    }
    fetchRef.current = true;
    console.log(`Starting eval with ID from URL: ${evalId}`);
    dispatch(initSession(evalId));
  }, [evalId, dispatch]);

  return (
    <div className="flex flex-col h-screen p-3 pt-2 space-y-2">
      <Suspense fallback={<div className="h-6">Loading breadcrumbs...</div>}>
        <Breadcrumbs />
      </Suspense>
      <ResponsiveCheck>{children}</ResponsiveCheck>
    </div>
  );
}

export default function DocentLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return <DocentLayoutContent>{children}</DocentLayoutContent>;
}
