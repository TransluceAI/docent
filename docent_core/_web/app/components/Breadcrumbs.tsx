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
} from 'lucide-react';
import Link from 'next/link';
import { useParams, usePathname, useSearchParams } from 'next/navigation';

import { COLLECTIONS_DASHBOARD_PATH } from '@/app/constants';
import { Button } from '@/components/ui/button';

import { UserProfile } from './auth/UserProfile';
import ShareViewPopover from '@/lib/permissions/ShareViewPopover';
import { useGetCollectionNameQuery } from '@/app/api/collectionApi';
import { skipToken } from '@reduxjs/toolkit/query';
import { cn } from '@/lib/utils';
import UuidPill from '@/components/UuidPill';
import { SettingsSidebarItems } from '@/app/settings/components/SettingsSidebar';

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
  }: {
    collection_id?: string;
    agent_run_id?: string;
    job_id?: string;
    session_id?: string;
  } = allParams;

  const pathname = usePathname();
  const { data } = useGetCollectionNameQuery(
    collectionId ? collectionId : skipToken
  );
  const collectionName = data?.name;

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
  };

  const pageCrumbs: Record<string, Crumb> = {
    undefined: {
      title: 'Agent Runs',
      url: `${COLLECTIONS_DASHBOARD_PATH}/${collectionId}`,
      icon: Layers,
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
    .map((segment) => {
      // Only add a crumb for "identifying" segments
      // E.g. a segment that is not a UUID
      if (!isUUID(segment)) {
        url = `${url}/${segment}`;

        // Get the corresponding UUID for the segment if it exists
        // E.g. segment, current_path => uuid
        // (rubric, ".../rubric/[rubric_id]") => uuid
        // (rubric, ".../rubric") => undefined
        const uuid = getUUIDForSegment(segment);
        let crumbToAdd;

        // If there's a UUID for this segment, append it to the URL and get a normal crumb
        if (uuid) {
          url = `${url}/${uuid}`;
          crumbToAdd = crumbs[segment];
        }
        // If there is no UUID for this segment, get a crumb from the page crumbs
        else {
          crumbToAdd = pageCrumbs[segment];
        }

        // Add the crumb to the components
        return {
          url,
          uuid, // Include the UUID so we can show a pill
          ...crumbToAdd,
        };
      }
    })
    .filter((crumb) => crumb !== undefined);

  const getBreadcrumb = (
    crumb: Crumb & { url: string; uuid?: string },
    index: number
  ) => {
    const { url, title, icon: Icon, uuid } = crumb;

    if (index === 0 && collectionId && collectionName) {
      return (
        <div className="flex items-center gap-2" key={0}>
          <Link
            className={cn(
              'flex items-center gap-x-2',
              disableNavigation && '!pointer-events-none'
            )}
            href={`${COLLECTIONS_DASHBOARD_PATH}/${collectionId}`}
          >
            Collection: {collectionName}
          </Link>
          <UuidPill uuid={collectionId} />
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

  return (
    <div className="text-sm flex items-center justify-between w-full ml-1">
      <div className="flex items-center gap-x-1">
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

        {/* Share view */}
        {collectionId && <ShareViewPopover collectionId={collectionId} />}

        <ModeToggle />
        <UserProfile />
      </div>
    </div>
  );
};

export default Breadcrumbs;
