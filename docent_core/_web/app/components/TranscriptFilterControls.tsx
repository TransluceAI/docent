'use client';

import React from 'react';
import { useDispatch, useSelector } from 'react-redux';
import { RootState, AppDispatch } from '../store/store';
import {
  useGetAgentRunMetadataFieldsQuery,
  useGetBaseFilterQuery,
} from '../api/collectionApi';
import { clearFilters, replaceFilters } from '../store/collectionSlice';
import { ComplexFilter } from '@/app/types/collectionTypes';
import { FilterControls } from './FilterControls';
import { useParams } from 'next/navigation';

interface TranscriptFilterControlsProps {
  metadataData?: Record<string, Record<string, unknown>>;
}

export const TranscriptFilterControls = ({
  metadataData = {},
}: TranscriptFilterControlsProps) => {
  const dispatch = useDispatch<AppDispatch>();
  // Get the filter state
  const params = useParams();
  const collectionId = params.collection_id as string;
  useGetBaseFilterQuery(collectionId!, {
    skip: !collectionId,
  });
  const baseFilter = useSelector(
    (state: RootState) => state.collection.baseFilter
  );
  const { data: metadataFieldsData } = useGetAgentRunMetadataFieldsQuery(
    collectionId!,
    {
      skip: !collectionId,
    }
  );
  const agentRunMetadataFields = metadataFieldsData?.fields;

  const handleFiltersChange = (filters: ComplexFilter | null) => {
    if (!filters) {
      dispatch(clearFilters());
      return;
    }

    dispatch(replaceFilters(filters.filters));
  };

  return (
    <FilterControls
      filters={baseFilter ?? null}
      onFiltersChange={handleFiltersChange}
      metadataFields={agentRunMetadataFields ?? []}
      collectionId={collectionId!}
      metadataData={metadataData}
    />
  );
};
