import { ChevronRight } from 'lucide-react';
import {
  useRouter,
  useParams,
  useSearchParams,
  usePathname,
} from 'next/navigation';
import Link from 'next/link';
import { Button } from '@/components/ui/button';
import { useEffect, useState } from 'react';
import { useFrameGrid } from '../contexts/FrameGridContext';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { BASE_DOCENT_PATH } from '@/app/constants';

interface BreadcrumbsProps {}

const Breadcrumbs: React.FC<BreadcrumbsProps> = ({}) => {
  const router = useRouter();
  const params = useParams();
  const searchParams = useSearchParams();
  const pathname = usePathname();
  const {
    evalIds,
    fetchEvalIds,
    isConnected,
    curEvalId,
    setIsApiKeyModalOpen,
  } = useFrameGrid();

  // Get the current page information
  const datapointId = params?.datapoint_id as string | undefined;
  const sampleId = params?.sample_id as string | undefined;
  const isDiffPage = pathname?.includes('/diff');
  const isForestPage = pathname?.includes('/forest');

  // For diff page
  const datapoint1 = searchParams?.get('datapoint1');
  const datapoint2 = searchParams?.get('datapoint2');

  // Handle eval ID selection
  const handleEvalIdChange = (value: string) => {
    if (isConnected) {
      // Use window.location for complete refresh instead of router.push
      window.location.href = `${BASE_DOCENT_PATH}/${value}`;
    }
  };

  return (
    <div className="text-sm flex items-center justify-between w-full">
      <div className="flex gap-x-1 items-center">
        {/* Home link */}
        {curEvalId &&
        (datapointId || sampleId || isDiffPage || isForestPage) ? (
          <Link
            href={`${BASE_DOCENT_PATH}/${curEvalId}`}
            className="text-blue-600 hover:underline"
          >
            All transcripts
          </Link>
        ) : (
          <span className="text-gray-700">All transcripts</span>
        )}

        {/* Transcript page */}
        {datapointId && (
          <>
            <ChevronRight size={18} />
            <span className="text-gray-700">Transcript {datapointId}</span>
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

      <div className="flex items-center gap-x-3">
        {/* Eval IDs dropdown */}
        {evalIds.length > 0 && (
          <div className="space-y-0 flex items-center gap-x-2">
            <span className="text-xs text-gray-600">Selected benchmark:</span>
            <Select value={curEvalId || ''} onValueChange={handleEvalIdChange}>
              <SelectTrigger className="h-7 text-xs bg-white font-mono text-gray-600 border-gray-200 w-auto min-w-[120px]">
                <SelectValue placeholder="Select evaluation" />
              </SelectTrigger>
              <SelectContent>
                {evalIds.map((evalId) => (
                  <SelectItem
                    key={evalId}
                    value={evalId}
                    className="font-mono text-xs text-gray-600"
                  >
                    {evalId}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        )}

        {/* API Key button */}
        <Button
          size="sm"
          variant="outline"
          className="h-7 text-xs whitespace-nowrap px-2 py-0"
          onClick={() => {
            setIsApiKeyModalOpen(true);
          }}
        >
          API Keys
        </Button>

        {/* Research preview button */}
        <Button
          size="sm"
          className="h-7 text-xs whitespace-nowrap px-2 py-0"
          onClick={() =>
            window.open(
              'https://docs.google.com/forms/d/e/1FAIpQLSe_vYg8UJMwZJDaYTCFkxxJxOibpkZK4llVmWoCSqiRN2Q-cQ/viewform?usp=header',
              '_blank'
            )
          }
        >
          Become an early user!
        </Button>
      </div>
    </div>
  );
};

export default Breadcrumbs;
