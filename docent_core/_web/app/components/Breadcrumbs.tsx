import { ModeToggle } from '@/components/ui/theme-toggle';
import {
  BookText,
  ChevronRight,
  Layers,
  MessageCircle,
  PanelLeftClose,
  PanelLeftOpen,
} from 'lucide-react';
import Link from 'next/link';
import { useRouter, useParams, usePathname } from 'next/navigation';
import { useSelector } from 'react-redux';

import { BASE_DOCENT_PATH } from '@/app/constants';
import { Button } from '@/components/ui/button';
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from '@/components/ui/tooltip';

import { RootState } from '../store/store';
import { useAppDispatch } from '../store/hooks';
import { UserProfile } from './auth/UserProfile';
import ShareViewPopover from '@/lib/permissions/ShareViewPopover';
import { useGetCollectionNameQuery } from '@/app/api/collectionApi';
import {
  toggleAgentRunLeftSidebar,
  toggleJudgeLeftSidebar,
} from '../store/transcriptSlice';

const Breadcrumbs: React.FC = () => {
  const router = useRouter();
  const params = useParams();
  const pathname = usePathname();
  const dispatch = useAppDispatch();

  const collectionId = useSelector(
    (state: RootState) => state.collection.collectionId
  );

  // Determine route
  const agentRunId = params?.agent_run_id as string | undefined;
  const rubricId = params?.rubric_id as string | undefined;
  const resultId = params?.result_id as string | undefined;
  const isAgentRunView = !!agentRunId && !rubricId;
  const isJudgeResultView = !!rubricId && !!resultId;

  // Select left sidebar state based on route
  const leftSidebarOpen = useSelector((state: RootState) =>
    isJudgeResultView
      ? state.transcript.judgeLeftSidebarOpen
      : state.transcript.agentRunLeftSidebarOpen
  );

  // check if we are "home", i.e. at /dashboard/[collection_id]
  const effectiveCollectionId =
    collectionId || (params?.collection_id as string | undefined);
  const { data: collectionNameResp } = useGetCollectionNameQuery(
    effectiveCollectionId as string,
    {
      skip: !effectiveCollectionId,
    }
  );
  const collectionName = collectionNameResp?.name ?? null;

  const normalizePath = (p?: string | null) => (p ? p.replace(/\/+$/, '') : '');
  const isHome =
    !!effectiveCollectionId &&
    normalizePath(pathname) ===
      normalizePath(`${BASE_DOCENT_PATH}/${effectiveCollectionId}`);

  // Get the current page information
  const refinementSessionId = params?.session_id as string | undefined;

  // Check if we're on a page that should show sidebar toggles
  const showSidebarToggles = isAgentRunView || isJudgeResultView;

  const collectionBreadcrumbText = collectionName
    ? `Collection: ${collectionName}`
    : 'Collection';

  return (
    <div className="_Breadcrumbs text-sm flex items-center justify-between w-full">
      <div className="flex items-center gap-x-3">
        {/* Go Home button */}
        <Tooltip>
          <TooltipTrigger asChild>
            <Button
              asChild
              size="sm"
              variant="outline"
              className="h-7 text-xs whitespace-nowrap px-2 py-0 flex items-center gap-x-1"
            >
              <Link href="/dashboard">
                <Layers size={14} />
              </Link>
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
              {collectionBreadcrumbText}
            </span>
          ) : (
            <Link
              href={`${BASE_DOCENT_PATH}/${effectiveCollectionId}`}
              className="text-blue-text hover:underline"
            >
              {collectionBreadcrumbText}
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

        {showSidebarToggles && (
          <Button
            variant="outline"
            size="sm"
            className="gap-x-2 h-7 cursor-default px-2"
            onClick={() =>
              dispatch(
                isJudgeResultView
                  ? toggleJudgeLeftSidebar()
                  : toggleAgentRunLeftSidebar()
              )
            }
          >
            {leftSidebarOpen ? (
              <PanelLeftClose size={14} />
            ) : (
              <PanelLeftOpen size={14} />
            )}
          </Button>
        )}

        <ModeToggle />
        <UserProfile />
      </div>
    </div>
  );
};

export default Breadcrumbs;
