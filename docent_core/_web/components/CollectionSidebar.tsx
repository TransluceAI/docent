'use client';

import {
  Home,
  Tags,
  Layers,
  PanelLeftOpen,
  PanelLeftClose,
  Scale,
} from 'lucide-react';
import Link from 'next/link';
import { useParams, usePathname } from 'next/navigation';
import { useGetCollectionNameQuery } from '@/app/api/collectionApi';
import { Button } from '@/components/ui/button';
import { cn } from '@/lib/utils';
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from '@/components/ui/tooltip';

import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarGroup,
  SidebarGroupContent,
  SidebarGroupLabel,
  SidebarHeader,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  useSidebar,
} from '@/components/ui/sidebar';

export function CollectionSidebar() {
  const params = useParams();
  const pathname = usePathname();
  const collectionId = params.collection_id as string;
  const { state, toggleSidebar } = useSidebar();

  const { data: collectionNameResp } = useGetCollectionNameQuery(collectionId, {
    skip: !collectionId,
  });
  const collectionName = collectionNameResp?.name ?? 'Collection';
  const isCollapsed = state === 'collapsed';

  // Menu items.
  const items = [
    {
      title: 'Agent Runs',
      url: `/dashboard/${collectionId}`,
      icon: Layers,
    },
    {
      title: 'Rubrics',
      url: `/dashboard/${collectionId}/rubric`,
      icon: Scale,
    },
    {
      title: 'Label Sets',
      url: `/dashboard/${collectionId}/labels`,
      icon: Tags,
    },
  ];

  return (
    <TooltipProvider delayDuration={0}>
      <Sidebar variant="inset" collapsible="icon" className="pt-0">
        <SidebarHeader
          className={cn(
            'flex items-center',
            isCollapsed ? 'justify-center' : 'justify-start'
          )}
        >
          {/* Home button */}
          <div className="flex m-2 h-7 items-center">
            {isCollapsed ? (
              <Tooltip>
                <TooltipTrigger asChild>
                  <Button
                    asChild
                    variant="outline"
                    size="icon"
                    className="h-8 w-8"
                  >
                    <Link href="/dashboard">
                      <Home className="h-4 w-4" />
                    </Link>
                  </Button>
                </TooltipTrigger>
                <TooltipContent side="right">Home</TooltipContent>
              </Tooltip>
            ) : (
              <Button asChild variant="outline" size="icon" className="h-8 w-8">
                <Link href="/dashboard">
                  <Home className="h-4 w-4" />
                </Link>
              </Button>
            )}
          </div>

          {/* Collection name */}
          <div
            className={cn(
              'flex flex-col pl-4 items-start w-full',
              isCollapsed
                ? 'opacity-0 pointer-events-none transition-opacity duration-200'
                : 'opacity-100'
            )}
          >
            <SidebarGroupLabel className="w-full truncate pl-0 pb-2">
              Current Collection:
            </SidebarGroupLabel>
            <span
              className={cn(
                'text-sm font-semibold truncate w-full',
                'group-data-[collapsible=icon]:hidden'
              )}
            >
              {collectionName}
            </span>
          </div>
        </SidebarHeader>

        <SidebarContent>
          <SidebarGroup>
            <SidebarGroupContent>
              <SidebarMenu>
                {items.map((item) => {
                  // For the root item (Agent Runs), only match exactly
                  // For other items, match if on that route or any subroute
                  const isRootItem = item.url === `/dashboard/${collectionId}`;
                  const isActive = isRootItem
                    ? pathname === item.url
                    : pathname === item.url ||
                      pathname.startsWith(item.url + '/');
                  return (
                    <SidebarMenuItem key={item.title}>
                      {isCollapsed ? (
                        <Tooltip>
                          <TooltipTrigger asChild>
                            <SidebarMenuButton asChild isActive={isActive}>
                              <Link href={item.url}>
                                <item.icon />
                                <span>{item.title}</span>
                              </Link>
                            </SidebarMenuButton>
                          </TooltipTrigger>
                          <TooltipContent side="right">
                            {item.title}
                          </TooltipContent>
                        </Tooltip>
                      ) : (
                        <SidebarMenuButton asChild isActive={isActive}>
                          <Link href={item.url}>
                            <item.icon />
                            <span>{item.title}</span>
                          </Link>
                        </SidebarMenuButton>
                      )}
                    </SidebarMenuItem>
                  );
                })}
              </SidebarMenu>
            </SidebarGroupContent>
          </SidebarGroup>
        </SidebarContent>
        <SidebarFooter className="p-2 pb-3 text-muted-foreground">
          {isCollapsed ? (
            <Tooltip>
              <TooltipTrigger asChild>
                <Button
                  className="h-8 w-8"
                  variant="ghost"
                  size="icon"
                  onClick={toggleSidebar}
                >
                  <PanelLeftOpen size={16} />
                </Button>
              </TooltipTrigger>
              <TooltipContent side="right">Expand sidebar</TooltipContent>
            </Tooltip>
          ) : (
            <Button
              className="h-8 w-8"
              variant="ghost"
              size="icon"
              onClick={toggleSidebar}
            >
              <PanelLeftClose size={16} />
            </Button>
          )}
        </SidebarFooter>
      </Sidebar>
    </TooltipProvider>
  );
}
