import { useAppDispatch, useAppSelector } from '../store/hooks';
import { cn } from '@/lib/utils';
import { DiffTheme, focusCluster } from '../store/diffSlice';
import { DiffReportConfig } from './DiffReportConfig';

const DiffsClusters = () => {
  const clusters = useAppSelector((state) => state.diff.diffsReport?.clusters);
  const dispatch = useAppDispatch();
  const onClusterClick = (cluster: DiffTheme) => {
    dispatch(focusCluster(cluster));
  };

  const selectedCluster = useAppSelector((state) => state.diff.selectedCluster);

  return (
    <aside
      className={cn(
        'w-64 min-h-full p-4 border-r bg-gray-50 dark:bg-gray-900/60',
        'flex flex-col space-y-4'
      )}
    >
      <DiffReportConfig />
      {clusters && (
          <p className="text-xs text-gray-500 dark:text-gray-400 mt-2">
            {' '}
            We looked at all the observed differences bewteen the paired
            transcripts and found the following themes.{' '}
          </p>
        )}
      <div className="flex items-center justify-between mb-4">
        {clusters && <h3 className="font-bold text-gray-700 dark:text-gray-200">Themes</h3>}
        {selectedCluster && (
          <button
            className={cn(
              'text-xs px-2 py-1 rounded bg-gray-200 dark:bg-gray-800 text-gray-700 dark:text-gray-200 hover:bg-gray-300 dark:hover:bg-gray-700 transition-colors'
            )}
            onClick={() => dispatch(focusCluster(null))}
          >
            Show All
          </button>
        )}

      </div>

      {clusters ? (
        <ul className="space-y-1">
          {clusters.map((cluster: DiffTheme) => (
            <li
              key={cluster.name}
              className={cn(
                'cursor-pointer py-2 px-3 rounded transition-colors text-sm',
                'text-gray-700 dark:text-gray-200',
                selectedCluster === cluster
                  ? 'bg-blue-100 dark:bg-blue-900 font-semibold'
                  : 'hover:bg-gray-200 dark:hover:bg-gray-800'
              )}
              onClick={() => onClusterClick(cluster)}
            >
              {cluster.name}
            </li>
          ))}
        </ul>
      ) : null}
    </aside>
  );
};

export default DiffsClusters;
