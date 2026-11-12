"""Bounded transport metadata for the scheduled GDELT caller."""
from .gdelt_batches import GdeltBatchError
from .gdelt_schedule import retry_after


class GdeltHTTPError(GdeltBatchError):
    def __init__(self, status, retry_header=None):
        super().__init__(f"GDELT endpoint returned HTTP {status}")
        self.status = status
        self.delay, self.unbounded = retry_after(retry_header)

    def schedule_fields(self):
        return {'http_status': self.status, 'retry_after_seconds': self.delay,
                'retry_after_unbounded': self.unbounded}
