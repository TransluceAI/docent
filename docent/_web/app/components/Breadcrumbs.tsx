import { ChevronRight, Layers } from 'lucide-react';
import Link from 'next/link';
import {
  useRouter,
  useParams,
  useSearchParams,
  usePathname,
} from 'next/navigation';
import { useEffect, useState } from 'react';
import { useSelector } from 'react-redux';

import { BASE_DOCENT_PATH } from '@/app/constants';
import { Button } from '@/components/ui/button';
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from '@/components/ui/tooltip';

import {
  addConnectionStatusListener,
  removeConnectionStatusListener,
} from '../services/socketService';
import { RootState } from '../store/store';
import { UserProfile } from './auth/UserProfile';

interface BreadcrumbsProps {}

const Breadcrumbs: React.FC<BreadcrumbsProps> = () => {
  const router = useRouter();
  const params = useParams();
  const searchParams = useSearchParams();
  const pathname = usePathname();
  const [isConnected, setIsConnected] = useState(false);

  const fgId = useSelector((state: RootState) => state.frame.frameGridId);

  // Get the current page information
  const agentRunId = params?.agent_run_id as string | undefined;
  const sampleId = params?.sample_id as string | undefined;
  const isDiffPage = pathname?.includes('/paired_transcript');
  const isForestPage = pathname?.includes('/forest');

  // For diff page
  const datapoint1 = searchParams?.get('datapoint1');
  const datapoint2 = searchParams?.get('datapoint2');

  // Listen for connection status changes
  useEffect(() => {
    const handleConnectionStatus = (status: boolean) => {
      setIsConnected(status);
    };

    addConnectionStatusListener(handleConnectionStatus);

    return () => {
      removeConnectionStatusListener(handleConnectionStatus);
    };
  }, []);

  return (
    <div className="text-sm flex items-center justify-between w-full">
      <div className="flex items-center gap-x-3">
        {/* Go Home button */}
        <Tooltip>
          <TooltipTrigger asChild>
            <Button
              size="sm"
              variant="outline"
              className="h-7 text-xs whitespace-nowrap px-2 py-0 flex items-center gap-x-1"
              onClick={() => router.push('/dashboard')}
            >
              <Layers size={16} />
            </Button>
          </TooltipTrigger>
          <TooltipContent>
            <p>See all FrameGrids</p>
          </TooltipContent>
        </Tooltip>

        {/* Breadcrumbs */}
        <div className="flex gap-x-1 items-center">
          {/* Home link */}
          {fgId && (agentRunId || sampleId || isDiffPage || isForestPage) ? (
            <Link
              href={`${BASE_DOCENT_PATH}/${fgId}`}
              className="text-blue-600 hover:underline"
            >
              All agent runs
            </Link>
          ) : (
            <span className="text-gray-700">All agent runs</span>
          )}

          {/* Transcript page */}
          {agentRunId && (
            <>
              <ChevronRight size={18} />
              <span className="text-gray-700">Agent run {agentRunId}</span>
            </>
          )}

          {/* Forest page */}
          {isForestPage && sampleId && (
            <>
              <ChevronRight size={18} />
              <span className="text-gray-700">Sample {sampleId} tree</span>
            </>
          )}

          {/* Diff page */}
          {isDiffPage && datapoint1 && datapoint2 && (
            <>
              <ChevronRight size={18} />
              <span className="text-gray-700">
                Compare: {datapoint1} vs {datapoint2}
              </span>
            </>
          )}
        </div>
      </div>

      <div className="flex items-center gap-x-2">
        {/* Connection status indicator */}
        <div className="flex items-center">
          <div className="flex items-center border rounded-md h-7 px-2 text-xs whitespace-nowrap">
            <div
              className={`w-2.5 h-2.5 rounded-full ${isConnected ? 'bg-green-500' : 'bg-red-500'} mr-1.5`}
            />
            <span>{isConnected ? 'Connected' : 'Disconnected'}</span>
          </div>
        </div>

        <UserProfile />
      </div>
    </div>
  );
};

export default Breadcrumbs;
