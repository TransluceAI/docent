import { ModeToggle } from '@/components/ui/theme-toggle';
import {
  BookText,
  ChevronRight,
  Settings,
  MessageCircle,
  Tags,
  Layers,
  type LucideIcon,
  Search,
} from 'lucide-react';
import Link from 'next/link';
import { useParams, usePathname, useSearchParams } from 'next/navigation';

import { BASE_DOCENT_PATH } from '@/app/constants';
import { Button } from '@/components/ui/button';

import { UserProfile } from './auth/UserProfile';
import ShareViewPopover from '@/lib/permissions/ShareViewPopover';
import { useGetCollectionNameQuery } from '@/app/api/collectionApi';
import { skipToken } from '@reduxjs/toolkit/query';
import { cn } from '@/lib/utils';

interface Crumb {
  title: string;
  url?: string;
  icon?: LucideIcon;
}

const Breadcrumbs: React.FC = () => {
  const searchParams = useSearchParams();
  const disableNavigation = searchParams.get('nav') === 'false';

  const { collection_id: collectionId, agent_run_id: agentRunId } = useParams<{
    collection_id?: string;
    agent_run_id?: string;
  }>();
  const pathname = usePathname();
  const { data } = useGetCollectionNameQuery(
    collectionId ? collectionId : skipToken
  );
  const collectionName = data?.name;

  const crumbs: Record<string, Crumb> = {
    agent_run: {
      title: `Run ${agentRunId?.split('-')[0]}`,
    },
    result: {
      title: 'Result',
    },
    rubric: {
      title: 'Rubric',
    },
  };

  const pageCrumbs: Record<string, Crumb> = {
    undefined: {
      title: 'Agent Runs',
      url: `${BASE_DOCENT_PATH}/${collectionId}`,
      icon: Layers,
    },
    agent_run: {
      title: 'Agent Runs',
      url: `${BASE_DOCENT_PATH}/${collectionId}`,
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
    settings: {
      title: 'Settings',
      icon: Settings,
      url: `${BASE_DOCENT_PATH}`,
    },
  };

  const isUUID = (segment: string) => {
    return /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(
      segment
    );
  };

  const getSegmentsWithRoot = (
    segments: string[],
    baseUrl: string
  ): (Crumb & { url: string })[] => {
    // Initial url and empty components array
    let url = baseUrl;
    const components: (Crumb & { url: string })[] = [];

    // Make the breadcrumb root
    const pageKey = segments[0] as keyof typeof pageCrumbs;
    components.push({
      url: `${url}/${pageKey}`,
      ...pageCrumbs[pageKey],
    });

    let pending = null;

    // Iterate over the remaining segments
    for (const segment of segments) {
      url = `${url}/${segment}`;

      if (isUUID(segment) || pending !== null) {
        components.push({
          url: url,
          ...crumbs[pending as keyof typeof crumbs],
        });

        pending = null;
      } else {
        pending = segment;
      }
    }

    if (pending !== null && segments.length > 1) {
      components.push({
        url: url,
        ...crumbs[pending as keyof typeof crumbs],
      });
    }

    return components;
  };

  const onDashboard = pathname.startsWith(BASE_DOCENT_PATH);
  const segments = !onDashboard
    ? getSegmentsWithRoot(pathname.split('/').slice(1), `${BASE_DOCENT_PATH}`)
    : getSegmentsWithRoot(
        pathname.split('/').slice(3),
        `${BASE_DOCENT_PATH}/${collectionId}`
      );

  return (
    <div className="text-sm flex items-center justify-between w-full">
      <div className="flex items-center gap-x-1">
        {collectionId && collectionName && (
          <>
            <Link
              className={cn(
                'flex items-center gap-x-2',
                disableNavigation && '!pointer-events-none'
              )}
              href={`${BASE_DOCENT_PATH}/${collectionId}`}
            >
              Collection: {collectionName}
            </Link>
            <ChevronRight className="size-3.5" />
          </>
        )}
        {segments.map(({ url, title, icon: Icon }, index) => (
          <>
            <Link
              className={cn(
                'flex items-center gap-x-2',
                disableNavigation && '!pointer-events-none'
              )}
              key={url}
              href={url}
            >
              {Icon && <Icon className="size-3.5" />}
              {title}
            </Link>
            {index < segments.length - 1 && (
              <ChevronRight className="size-3.5" />
            )}
          </>
        ))}
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
