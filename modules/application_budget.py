"""Confirmed-submission budget shared by every query/cycle in one invocation."""


class ApplicationBudget:
    def __init__(self, limit=None):
        if limit is not None and (type(limit) is not int or limit < 1):
            raise ValueError("max_applications_per_run must be a positive integer or None")
        self.limit = limit
        self.applied_ids = set()
        self.reserved_ids = set()
        self.stop_reason = None

    @property
    def count(self):
        return len(self.applied_ids)

    @property
    def reached(self):
        return self.limit is not None and self.count >= self.limit

    @property
    def stopped(self):
        return self.reached or self.stop_reason == "submission_uncertain"

    def record(self, job_id):
        self.applied_ids.add(str(job_id))
        self.reserved_ids.discard(str(job_id))

    def stop_if_reached(self, manifest, spec=None):
        for row in manifest.data['queries']:
            for job_id, job in row['jobs'].items():
                job_id = str(job_id)
                if job['status'] == 'applied' and job_id in self.reserved_ids:
                    self.record(job_id)
                elif job['status'] == 'submitting' and job_id not in self.applied_ids:
                    self.reserved_ids.add(job_id)
        manifest.data['invocation_reserved_count'] = len(self.reserved_ids)
        reason = None
        if self.reached:
            reason = "application_limit_reached"
        elif self.limit is not None and self.count + len(self.reserved_ids) >= self.limit:
            # A remote success without local confirmation must not permit an
            # additional submission that could exceed the configured cap.
            # An isolated unknown outcome does not consume the entire budget.
            reason = "submission_uncertain"
        if reason is None:
            return False
        self.stop_reason = reason
        if spec is not None and manifest.quota_met(spec):
            manifest.finish_query(spec, "quota_met")
        manifest.data["invocation_application_limit"] = self.limit
        manifest.data["invocation_applied_count"] = self.count
        manifest.interrupt(reason)
        return True
