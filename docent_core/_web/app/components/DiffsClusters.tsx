import { useAppDispatch, useAppSelector } from '../store/hooks';
import { cn } from '@/lib/utils';
import { DiffTheme, focusCluster } from '../store/diffSliceOld';
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
        'w-74 min-h-full p-4 border-r bg-secondary',
        'flex flex-col space-y-4'
      )}
    >
      <DiffReportConfig />
      {clusters && (
        <p className="text-xs text-muted-foreground mt-2">
          {' '}
          We looked at all the observed differences between the paired
          transcripts and found the following themes.{' '}
        </p>
      )}
      <div className="flex items-center justify-between mb-4">
        {clusters && <h3 className="font-bold text-foreground">Themes</h3>}
        {selectedCluster && (
          <button
            className={cn(
              'text-xs px-2 py-1 rounded bg-accent text-foreground hover:bg-muted transition-colors'
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
                'text-foreground',
                selectedCluster === cluster
                  ? 'bg-blue-bg font-semibold'
                  : 'hover:bg-accent'
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
