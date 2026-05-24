// Small inline badge for the admin bookings table / detail panel.
//
// Three render states:
//   - Not yet checked in (status=confirmed, checked_in_at null) → "—".
//   - Checked in (status=checked_in, checked_in_at populated) → "✓ HH:MM".
//   - Booking already promoted to COMPLETED → "✓ Complete".
//
// Pure presentational — no fetching. The parent supplies whatever the
// list/detail endpoint returned for `checked_in_at` + `status`.

import { fmtTime } from "@/components/pd-ui";

export interface CheckInBadgeProps {
  checkedInAt: string | null | undefined;
  status: string;
}

export function CheckInBadge({ checkedInAt, status }: CheckInBadgeProps) {
  if (status === "completed") {
    return (
      <span className="pd-checkin-badge pd-checkin-badge--done" data-testid="checkin-badge">
        <span className="pd-checkin-dot" />
        Complete
      </span>
    );
  }
  if (checkedInAt) {
    return (
      <span className="pd-checkin-badge pd-checkin-badge--in" data-testid="checkin-badge">
        <span className="pd-checkin-dot" />
        {fmtTime(checkedInAt)}
      </span>
    );
  }
  return (
    <span className="pd-checkin-badge pd-checkin-badge--none" data-testid="checkin-badge">
      —
    </span>
  );
}
