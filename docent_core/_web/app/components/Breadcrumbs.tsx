import { ModeToggle } from '@/components/ui/theme-toggle';
import {
  BookText,
  ChevronRight,
  Layers,
  MessageCircle,
  PanelLeft,
  PanelRight,
} from 'lucide-react';
import Link from 'next/link';
import { useRouter, useParams, usePathname } from 'next/navigation';
import { useSelector } from 'react-redux';
import { useAppDispatch } from '../store/hooks';

import { BASE_DOCENT_PATH } from '@/app/constants';
import { Button } from '@/components/ui/button';
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from '@/components/ui/tooltip';

import { RootState } from '../store/store';
import { UserProfile } from './auth/UserProfile';
import ShareViewPopover from '@/lib/permissions/ShareViewPopover';
import { useGetCollectionsQuery } from '@/app/api/collectionApi';
import {
  toggleLeftSidebar,
  toggleRightSidebar,
} from '../store/transcriptSlice';
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group';

const Breadcrumbs: React.FC = () => {
  const router = useRouter();
  const params = useParams();
  const pathname = usePathname();
  const dispatch = useAppDispatch();

  const collectionId = useSelector(
    (state: RootState) => state.collection.collectionId
  );

  const leftSidebarOpen = useSelector(
    (state: RootState) => state.transcript.leftSidebarOpen ?? false
  );

  const rightSidebarOpen = useSelector(
    (state: RootState) => state.transcript.rightSidebarOpen ?? true
  );

  // check if we are "home", i.e. at /dashboard/[collection_id]
  const effectiveCollectionId =
    collectionId || (params?.collection_id as string | undefined);
  const { collectionName } = useGetCollectionsQuery(undefined, {
    skip: !effectiveCollectionId,
    selectFromResult: ({ data }) => ({
      collectionName:
        data?.find((c) => c.id === effectiveCollectionId)?.name ?? null,
    }),
  });

  const normalizePath = (p?: string | null) => (p ? p.replace(/\/+$/, '') : '');
  const isHome =
    !!effectiveCollectionId &&
    normalizePath(pathname) ===
      normalizePath(`${BASE_DOCENT_PATH}/${effectiveCollectionId}`);

  // Get the current page information
  const agentRunId = params?.agent_run_id as string | undefined;
  const rubricId = params?.rubric_id as string | undefined;
  const resultId = params?.result_id as string | undefined;
  const refinementSessionId = params?.session_id as string | undefined;

  // Check if we're on a page that should show sidebar toggles
  const showSidebarToggles = !!(agentRunId && !rubricId);

  // Determine if left sidebar should be disabled (no run/result selected)
  const leftSidebarDisabled =
    showSidebarToggles && !agentRunId && !(rubricId && resultId);

  return (
    <div className="_Breadcrumbs text-sm flex items-center justify-between w-full">
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
              <Layers size={14} />
            </Button>
          </TooltipTrigger>
          <TooltipContent>
            <p>See all Collections</p>
          </TooltipContent>
        </Tooltip>

        {/* Breadcrumbs */}
        <div className="flex gap-x-1 items-center">
          {/* Home link */}
          {isHome ? (
            <span className="text-muted-foreground">
              {collectionName ? `Collection: ${collectionName}` : 'Collection'}
            </span>
          ) : (
            <Link
              href={`${BASE_DOCENT_PATH}/${effectiveCollectionId}`}
              className="text-blue-text hover:underline"
            >
              {collectionName ? `Collection: ${collectionName}` : 'Collection'}
            </Link>
          )}

          {/* Transcript page */}
          {agentRunId && (
            <>
              <ChevronRight size={18} />
              <span className="text-muted-foreground">
                Agent run {agentRunId.split('-')[0]}
              </span>
            </>
          )}

          {rubricId && (
            <>
              <ChevronRight size={18} />
              {resultId ? (
                <Link
                  href={`${BASE_DOCENT_PATH}/${effectiveCollectionId}/rubric/${rubricId}`}
                  className="text-blue-text hover:underline"
                >
                  Rubric
                </Link>
              ) : (
                <span className="text-muted-foreground">Rubric</span>
              )}
            </>
          )}

          {refinementSessionId && (
            <>
              <ChevronRight size={18} />
              <span className="text-muted-foreground">Refinement session</span>
            </>
          )}

          {/* Rubric result */}
          {rubricId && resultId && (
            <>
              <ChevronRight size={18} />
              <span className="text-muted-foreground">Result</span>
            </>
          )}
        </div>
      </div>

      <div className="flex items-center gap-x-2">
        <Button
          variant="outline"
          size="sm"
          className="gap-x-2 h-7 cursor-default px-2"
        >
          <Link
            href="https://docs.transluce.org"
            target="_blank"
            className="flex items-center gap-x-2"
          >
            <BookText size={14} />
            Docs
          </Link>
        </Button>

        <Button
          variant="outline"
          size="sm"
          className="gap-x-2 h-7 cursor-default px-2"
        >
          <Link
            href="https://transluce.org/docent/slack"
            target="_blank"
            className="flex items-center gap-x-2"
          >
            <MessageCircle size={14} />
            Slack
          </Link>
        </Button>

        {/* Share view */}
        {effectiveCollectionId && (
          <ShareViewPopover collectionId={effectiveCollectionId} />
        )}

        {/* Sidebar toggles */}
        {showSidebarToggles && (
          <ToggleGroup
            className="h-7"
            type="multiple"
            value={[
              ...(!leftSidebarDisabled && leftSidebarOpen ? ['left'] : []),
              ...(rightSidebarOpen ? ['right'] : []),
            ]}
            onValueChange={(value) => {
              const newLeftOpen = value.includes('left');
              const newRightOpen = value.includes('right');

              if (newLeftOpen !== leftSidebarOpen && !leftSidebarDisabled) {
                dispatch(toggleLeftSidebar());
              }
              if (newRightOpen !== rightSidebarOpen) {
                dispatch(toggleRightSidebar());
              }
            }}
          >
            <Tooltip>
              <TooltipTrigger asChild>
                <ToggleGroupItem
                  value="left"
                  data-state={
                    (leftSidebarDisabled ? false : leftSidebarOpen)
                      ? 'on'
                      : 'off'
                  }
                  disabled={leftSidebarDisabled}
                  segment="left"
                >
                  <PanelLeft size={14} />
                </ToggleGroupItem>
              </TooltipTrigger>
              <TooltipContent>
                <p>
                  {leftSidebarOpen ? 'Hide left sidebar' : 'Show left sidebar'}
                </p>
              </TooltipContent>
            </Tooltip>

            <Tooltip>
              <TooltipTrigger asChild>
                <ToggleGroupItem
                  value="right"
                  data-state={rightSidebarOpen ? 'on' : 'off'}
                  disabled={false}
                  segment="right"
                >
                  <PanelRight size={14} />
                </ToggleGroupItem>
              </TooltipTrigger>
              <TooltipContent>
                <p>
                  {rightSidebarOpen
                    ? 'Hide right sidebar'
                    : 'Show right sidebar'}
                </p>
              </TooltipContent>
            </Tooltip>
          </ToggleGroup>
        )}

        <ModeToggle />
        <UserProfile />
      </div>
    </div>
  );
};

export default Breadcrumbs;
