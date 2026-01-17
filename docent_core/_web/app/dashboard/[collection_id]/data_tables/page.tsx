'use client';

import React from 'react';
import { useParams } from 'next/navigation';

import DataTableExplorer from '@/app/components/DataTableExplorer';
import { useHasCollectionWritePermission } from '@/lib/permissions/hooks';

export default function DataTablesPage() {
  const params = useParams();
  const collectionId = params.collection_id as string | undefined;
  const canEdit = useHasCollectionWritePermission();

  return (
    <div className="flex-1 flex min-h-0 min-w-0 shrink-0">
      <DataTableExplorer
        collectionId={collectionId ?? undefined}
        canEdit={canEdit}
      />
    </div>
  );
}
