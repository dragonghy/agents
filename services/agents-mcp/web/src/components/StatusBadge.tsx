interface StatusBadgeProps {
  status: 'idle' | 'busy' | 'no_window' | 'unknown';
}

const statusConfig = {
  idle: { label: 'Idle', color: 'bg-green-500' },
  busy: { label: 'Busy', color: 'bg-yellow-500' },
  no_window: { label: 'Offline', color: 'bg-gray-400' },
  unknown: { label: 'Unknown', color: 'bg-gray-400' },
};

export default function StatusBadge({ status }: StatusBadgeProps) {
  const config = statusConfig[status] || statusConfig.unknown;
  return (
    <span className="inline-flex items-center gap-1.5 text-sm text-gray-700 dark:text-gray-300">
      <span className={`inline-block w-2 h-2 rounded-full ${config.color}`} />
      {config.label}
    </span>
  );
}
