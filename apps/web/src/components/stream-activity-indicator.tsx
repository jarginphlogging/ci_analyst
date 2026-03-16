export function StreamActivityIndicator() {
  return (
    <div className="stream-activity-indicator" aria-hidden="true">
      <span className="stream-activity-indicator__baseline" />
      <span className="stream-activity-indicator__bar stream-activity-indicator__bar-a" />
      <span className="stream-activity-indicator__bar stream-activity-indicator__bar-b" />
      <span className="stream-activity-indicator__bar stream-activity-indicator__bar-c" />
      <span className="stream-activity-indicator__bar stream-activity-indicator__bar-d" />
      <span className="stream-activity-indicator__bar stream-activity-indicator__bar-e" />
      <span className="stream-activity-indicator__scan" />
    </div>
  );
}
