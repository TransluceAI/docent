import { ModeToggle } from '@/components/ui/theme-toggle';
import {
  BookText,
  ChevronRight,
  Settings,
  MessageCircle,
  MessagesSquare,
  Tags,
  Layers,
  type LucideIcon,
  Search,
  Home,
  FlaskConical,
  ChartColumn,
  Eye,
  X,
} from 'lucide-react';
import { useState } from 'react';
import Link from 'next/link';
import { useParams, usePathname, useSearchParams } from 'next/navigation';

import { COLLECTIONS_DASHBOARD_PATH } from '@/app/constants';
import { Button } from '@/components/ui/button';

import { UserProfile } from './auth/UserProfile';
import ShareViewPopover from '@/lib/permissions/ShareViewPopover';
import {
  useGetCollectionNameQuery,
  useGetCollectionMetadataQuery,
} from '@/app/api/collectionApi';
import { useGetResultSetQuery } from '@/app/api/resultSetApi';
import { skipToken } from '@reduxjs/toolkit/query';
import { cn } from '@/lib/utils';
import UuidPill from '@/components/UuidPill';
import { SettingsSidebarItems } from '@/app/settings/components/SettingsSidebar';
import { CloneCollectionButton } from '@/components/CloneCollectionButton';
import { useGetCollectionPermissionsQuery } from '@/lib/permissions/collabSlice';
import { MetadataPopover } from '@/components/metadata/MetadataPopover';
import { MetadataBlock } from '@/components/metadata/MetadataBlock';

interface Crumb {
  title: string;
  url?: string;
  icon?: LucideIcon;
}

const Breadcrumbs: React.FC = () => {
  const searchParams = useSearchParams();
  const disableNavigation = searchParams.get('nav') === 'false';

  const allParams = useParams();
  const {
    collection_id: collectionId,
    agent_run_id: agentRunId,
    job_id: jobId,
    session_id: sessionId,
    result_set_id_or_name: resultSetIdOrNameParam,
  }: {
    collection_id?: string;
    agent_run_id?: string;
    job_id?: string;
    session_id?: string;
    result_set_id_or_name?: string;
  } = allParams;

  let resultSetIdOrName = resultSetIdOrNameParam;
  if (Array.isArray(resultSetIdOrNameParam)) {
    resultSetIdOrName = resultSetIdOrNameParam.join('/');
  }
  if (resultSetIdOrName) {
    resultSetIdOrName = decodeURIComponent(resultSetIdOrName);
  }

  const pathname = usePathname();
  const { data } = useGetCollectionNameQuery(
    collectionId ? collectionId : skipToken
  );
  const collectionName = data?.name;

  const { data: resultSetData } = useGetResultSetQuery(
    collectionId && resultSetIdOrName
      ? { collectionId, resultSetIdOrName }
      : skipToken
  );

  const { data: collectionMetadata } = useGetCollectionMetadataQuery(
    collectionId ?? skipToken
  );

  const { data: permissions, isLoading: permissionsLoading } =
    useGetCollectionPermissionsQuery(collectionId ?? '', {
      skip: !collectionId,
    });
  const permissionLevel =
    permissions?.collection_permissions?.[collectionId ?? ''] ?? 'none';
  const isReadOnly =
    !!collectionId && !permissionsLoading && permissionLevel === 'read';

  const [isReadOnlyBannerDismissed, setIsReadOnlyBannerDismissed] =
    useState(false);

  const crumbs: Record<string, Crumb> = {
    dashboard: {
      title: 'Collection',
    },
    agent_run: {
      title: `Agent Run`,
    },
    result: {
      title: 'Result',
    },
    rubric: {
      title: 'Rubric',
    },
    jobs: {
      title: `Job`,
    },
    chat: {
      title: 'Chat',
    },
    results: {
      title: 'Result Set',
    },
  };

  const pageCrumbs: Record<string, Crumb> = {
    undefined: {
      title: 'Agent Runs',
      url: `${COLLECTIONS_DASHBOARD_PATH}/${collectionId}/agent_run`,
      icon: Layers,
    },
    agent_run: {
      title: 'Agent Runs',
      icon: Layers,
      url: `${COLLECTIONS_DASHBOARD_PATH}/${collectionId}/agent_run`,
    },
    charts: {
      title: 'Charts',
      icon: ChartColumn,
    },
    rubric: {
      title: 'Rubrics',
      icon: Search,
    },
    labels: {
      title: 'Label Sets',
      icon: Tags,
    },
    jobs: {
      title: 'Jobs',
      icon: Layers,
    },
    chat: {
      title: 'Chats',
      icon: MessagesSquare,
      url: `${COLLECTIONS_DASHBOARD_PATH}/${collectionId}/chat`,
    },
    results: {
      title: 'Results',
      icon: FlaskConical,
      url: `${COLLECTIONS_DASHBOARD_PATH}/${collectionId}/results`,
    },
    settings: {
      title: 'Settings',
      icon: Settings,
      url: `${COLLECTIONS_DASHBOARD_PATH}`,
    },
    ...SettingsSidebarItems,
  };

  const getUUIDForSegment = (param: string): string | undefined => {
    let resolvedParam: string = param;
    if (param === 'dashboard') {
      resolvedParam = 'Collection';
    }

    // Handle plural to singular conversion for jobs -> job_id
    if (param === 'jobs') {
      resolvedParam = 'job';
    }
    // Handle chats -> session_id
    if (param === 'chat') {
      resolvedParam = 'session';
    }
    // Handle results -> result_set_id_or_name (special case: may be UUID or name)
    if (param === 'results') {
      return resultSetData?.id ?? resultSetIdOrName;
    }

    const slugLookup = resolvedParam.toLowerCase() + '_id';
    return allParams[slugLookup] as string | undefined;
  };

  const isUUID = (segment: string) => {
    return /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(
      segment
    );
  };

  let url = '';
  const segments = pathname
    .split('/')
    .slice(1)
    .flatMap((segment) => {
      // Only add a crumb for "identifying" segments
      // E.g. a segment that is not a UUID
      if (!isUUID(segment)) {
        url = `${url}/${segment}`;

        // Get the corresponding UUID for the segment if it exists
        // E.g. segment, current_path => uuid
        // (rubric, ".../rubric/[rubric_id]") => uuid
        // (rubric, ".../rubric") => undefined
        const uuid = getUUIDForSegment(segment);

        // If there's a UUID for this segment and a page crumb exists,
        // add both the page crumb (list view) and the detail crumb
        if (uuid && pageCrumbs[segment]) {
          const pageUrl = url;
          url = `${url}/${uuid}`;
          return [
            {
              url: pageCrumbs[segment].url || pageUrl,
              uuid: undefined,
              ...pageCrumbs[segment],
            },
            {
              url,
              uuid,
              ...crumbs[segment],
            },
          ];
        }

        // If there's a UUID for this segment, append it to the URL and get a normal crumb
        if (uuid) {
          url = `${url}/${uuid}`;
          return {
            url,
            uuid, // Include the UUID so we can show a pill
            ...crumbs[segment],
          };
        }

        // If there is no UUID for this segment, get a crumb from the page crumbs
        return {
          url,
          uuid: undefined,
          ...pageCrumbs[segment],
        };
      }
      return [];
    })
    .filter(
      (
        crumb
      ): crumb is {
        title: string;
        url: string;
        icon?: LucideIcon;
        uuid: string | undefined;
      } => !!crumb?.title
    );

  const isSettingsPage = pathname.startsWith('/settings');

  const getBreadcrumb = (
    crumb: Crumb & { url: string; uuid?: string },
    index: number
  ) => {
    const { url, title, icon: Icon, uuid } = crumb;

    if (index === 0 && collectionId && collectionName) {
      const hasMetadata =
        collectionMetadata && Object.keys(collectionMetadata).length > 0;
      return (
        <div className="flex items-center gap-2 min-w-0" key={0}>
          <span className="truncate min-w-[60px] max-w-[450px]">
            Collection: {collectionName}
          </span>
          <UuidPill uuid={collectionId} />
          {hasMetadata && (
            <MetadataPopover.Root>
              <MetadataPopover.DefaultTrigger />
              <MetadataPopover.Content
                side="bottom"
                align="start"
                title="Collection Metadata"
              >
                <MetadataPopover.Body metadata={collectionMetadata}>
                  {(md) => <MetadataBlock metadata={md} />}
                </MetadataPopover.Body>
              </MetadataPopover.Content>
            </MetadataPopover.Root>
          )}
          {segments.length > 1 && <ChevronRight className="size-3.5" />}
        </div>
      );
    }

    return (
      <div className="flex items-center gap-2" key={index}>
        <Link
          className={cn(
            'flex items-center gap-x-2',
            disableNavigation && '!pointer-events-none'
          )}
          href={url}
        >
          {Icon && <Icon className="size-3.5" />}
          {title}
        </Link>
        {uuid && <UuidPill uuid={uuid} />}
        {index < segments.length - 1 && <ChevronRight className="size-3.5" />}
      </div>
    );
  };

  const getHomeCrumb = () => (
    <div className="flex items-center gap-2" key="home">
      <Link
        className={cn(
          'flex items-center gap-x-2',
          disableNavigation && '!pointer-events-none'
        )}
        href={COLLECTIONS_DASHBOARD_PATH}
      >
        <Home className="size-3.5" />
      </Link>
      <ChevronRight className="size-3.5" />
    </div>
  );

  return (
    <div className="flex flex-col w-full">
      {isReadOnly && !isReadOnlyBannerDismissed && (
        <div className="flex items-center justify-between bg-indigo-bg border border-indigo-border rounded-lg px-3 py-2 mb-3 ml-1 shadow-sm">
          <div className="flex items-center gap-2">
            <div className="flex items-center justify-center size-6 rounded-full bg-indigo-muted">
              <Eye className="size-4 text-indigo-text" />
            </div>
            <div className="flex flex-col">
              <span className="text-sm font-medium text-primary">
                Read-Only Collection
              </span>
              <span className="text-xs text-muted-foreground">
                Clone this collection to search, analyze, and make changes
              </span>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <CloneCollectionButton
              variant="default"
              size="sm"
              showLabel={true}
              collectionName={collectionName}
              className="bg-indigo-600 hover:bg-indigo-700 text-white h-7"
            />
            <button
              onClick={() => setIsReadOnlyBannerDismissed(true)}
              className="p-1 rounded-md hover:bg-indigo-muted text-muted-foreground hover:text-primary transition-colors"
              aria-label="Dismiss banner"
            >
              <X className="size-4" />
            </button>
          </div>
        </div>
      )}
      <div className="text-sm flex items-center justify-between w-full ml-1">
        <div className="flex items-center gap-x-1 min-w-0">
          {isSettingsPage && getHomeCrumb()}
          {segments.map((crumb, index) => getBreadcrumb(crumb, index))}
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

          {/* Clone collection */}
          {collectionId && (
            <CloneCollectionButton
              variant="outline"
              size="sm"
              showLabel={true}
              collectionName={collectionName}
              className="gap-x-2 h-7 px-2"
            />
          )}

          {/* Share view */}
          {collectionId && <ShareViewPopover collectionId={collectionId} />}

          <ModeToggle />
          <UserProfile />
        </div>
      </div>
    </div>
  );
};

export default Breadcrumbs;
