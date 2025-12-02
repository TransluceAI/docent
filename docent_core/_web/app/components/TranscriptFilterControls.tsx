'use client';

import React, { useState } from 'react';
import { useDispatch } from 'react-redux';
import { AppDispatch } from '../store/store';
import {
  useGetAgentRunMetadataFieldsQuery,
  useGetBaseFilterQuery,
} from '../api/collectionApi';
import { clearFilters, replaceFilters } from '../store/collectionSlice';
import { ComplexFilter, PrimitiveFilter } from '@/app/types/collectionTypes';
import { FilterControls } from './FilterControls';
import { FilterChips } from './FilterChips';
import { useParams } from 'next/navigation';
import { skipToken } from '@reduxjs/toolkit/query';

interface TranscriptFilterControlsProps {
  metadataData?: Record<string, Record<string, unknown>>;
}

export const TranscriptFilterControls = ({
  metadataData = {},
}: TranscriptFilterControlsProps) => {
  const dispatch = useDispatch<AppDispatch>();
  const params = useParams();
  const collectionId = params.collection_id as string;
  const { data: baseFilter } = useGetBaseFilterQuery(
    collectionId ? collectionId : skipToken
  );
  const { data: metadataFieldsData } = useGetAgentRunMetadataFieldsQuery(
    collectionId!,
    {
      skip: !collectionId,
    }
  );
  const agentRunMetadataFields = metadataFieldsData?.fields;

  const [editingFilter, setEditingFilter] = useState<PrimitiveFilter | null>(
    null
  );

  const handleFiltersChange = (filters: ComplexFilter | null) => {
    if (!filters) {
      dispatch(clearFilters());
    } else {
      dispatch(replaceFilters(filters.filters));
    }
    setEditingFilter(null);
  };

  return (
    <div className="space-y-1.5">
      <FilterControls
        filters={baseFilter ?? null}
        onFiltersChange={handleFiltersChange}
        metadataFields={agentRunMetadataFields ?? []}
        collectionId={collectionId!}
        metadataData={metadataData}
        initialFilter={editingFilter}
      />
      <FilterChips
        filters={baseFilter ?? null}
        onFiltersChange={handleFiltersChange}
        onRequestEdit={setEditingFilter}
        className="mb-1.5"
      />
    </div>
  );
};
