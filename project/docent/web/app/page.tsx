'use client';

import { Loader2 } from 'lucide-react';
import { useEffect, useState } from 'react';
import { useFrameGrid } from './contexts/FrameGridContext';
import { BASE_DOCENT_PATH } from '@/app/constants';
import { useRouter } from 'next/navigation';

const DocentDashboard = () => {
  const { evalIds, curEvalId, fetchEvalIds } = useFrameGrid();
  const router = useRouter();
  const [isClient, setIsClient] = useState(false);

  // Set client-side flag after mount
  useEffect(() => {
    setIsClient(true);
  }, []);

  // Handle routing after data is loaded
  useEffect(() => {
    if (!isClient) return;

    if (curEvalId) {
      router.push(`${BASE_DOCENT_PATH}/${curEvalId}`);
    } else if (evalIds.length > 0) {
      router.push(`${BASE_DOCENT_PATH}/${evalIds[0]}`);
    }
  }, [curEvalId, evalIds, router, isClient]);

  return (
    <div className="flex items-center justify-center h-full">
      <Loader2 className="h-5 w-5 animate-spin text-gray-500" />
    </div>
  );
};

export default DocentDashboard;
