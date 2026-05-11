from core.logger import log


class EventProcessor:

    def process(self, event: dict):

        if "trace_id" not in event:
            raise ValueError("trace_id missing")

        return event