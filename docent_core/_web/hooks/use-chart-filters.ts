import { useCallback } from 'react';
import { v4 as uuid4 } from 'uuid';
import { PrimitiveFilter } from '../app/types/collectionTypes';
import { replaceFilters } from '../app/store/collectionSlice';
import { useGetChartMetadataQuery } from '../app/api/chartApi';
import { useAppDispatch } from '../app/store/hooks';

export function useChartFilters(collectionId: string | null | undefined) {
  const dispatch = useAppDispatch();

  const { data: chartMetadata } = useGetChartMetadataQuery(
    { collectionId: collectionId! },
    { skip: !collectionId }
  );

  const createFilter = useCallback(
    (dimId: string, value: string): PrimitiveFilter | undefined => {
      // Find the dimension in the chart metadata
      const allDimensions = [
        ...(chartMetadata?.dimensions || []),
        ...(chartMetadata?.measures || []),
      ];
      const dimension = allDimensions.find((dim) => dim.key === dimId);

      // We can't filter on anything besides run metadata (for now)
      if (dimension?.kind !== 'run_metadata') {
        return undefined;
      }

      // Build key path from dimension metadata
      const key_path = ['metadata', ...dimension.json_path.split('.')];

      return {
        type: 'primitive',
        key_path,
        value,
        op: '==',
        id: uuid4(),
        name: null,
        supports_sql: true,
      };
    },
    [chartMetadata?.dimensions, chartMetadata?.measures]
  );

  const handleCellClick = useCallback(
    (
      xKey: string,
      xValue: string,
      seriesKey?: string,
      seriesValue?: string
    ) => {
      if (seriesKey && seriesValue) {
        // 2D case: add both filters
        const xFilter = createFilter(xKey, xValue);
        const seriesFilter = createFilter(seriesKey, seriesValue);
        const validFilters = [xFilter, seriesFilter].filter(
          (f): f is PrimitiveFilter => f !== undefined
        );
        if (validFilters.length > 0) {
          dispatch(replaceFilters(validFilters));
        }
      } else {
        // 1D case: add single filter
        const filter = createFilter(xKey, xValue);
        if (filter) {
          dispatch(replaceFilters([filter]));
        }
      }
    },
    [createFilter]
  );

  const handleDimensionClick = useCallback(
    (dimKey: string, dimValue: string) => {
      const filter = createFilter(dimKey, dimValue);
      if (filter) {
        dispatch(replaceFilters([filter]));
      }
    },
    [createFilter]
  );

  return {
    createFilter,
    handleCellClick,
    handleDimensionClick,
  };
}
