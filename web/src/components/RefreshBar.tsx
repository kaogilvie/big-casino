interface RefreshBarProps {
  label: string;
  timestamp: string | null;
  onClick: () => void;
  disabled?: boolean;
  loading?: boolean;
  loadingLabel?: string;
}

export function RefreshBar({ label, timestamp, onClick, disabled, loading, loadingLabel }: RefreshBarProps) {
  return (
    <div className="flex items-center justify-end gap-3">
      {timestamp && (
        <span className="text-xs text-muted-foreground">
          Last updated {new Date(timestamp).toLocaleString()}
        </span>
      )}
      <button
        disabled={disabled || loading}
        onClick={onClick}
        className="text-sm px-3 py-1.5 rounded-md border border-foreground text-foreground bg-transparent hover:bg-foreground hover:text-background transition-colors disabled:opacity-50"
      >
        {loading ? (loadingLabel ?? "Loading…") : label}
      </button>
    </div>
  );
}
