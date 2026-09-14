import logging
import sys


class SecretRedactingFilter(logging.Filter):
    """Best-effort backstop so nothing that looks like a credential ever
    reaches the log stream, even if a future call site accidentally
    interpolates one into a message.
    """

    MARKERS = ("api_key", "apikey", "authorization", "secret", "token")

    def filter(self, record):
        message = record.getMessage()
        lowered = message.lower()
        if any(marker in lowered for marker in self.MARKERS) and "=" in message:
            record.msg = "[redacted: log message referenced a credential-like field]"
            record.args = ()
        return True


def configure_logging(level=logging.INFO):
    root = logging.getLogger("news_research_tool")
    if root.handlers:
        return root  # already configured — avoid duplicate handlers on Streamlit reruns
    root.setLevel(level)
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)-8s %(name)s: %(message)s"))
    handler.addFilter(SecretRedactingFilter())
    root.addHandler(handler)
    root.propagate = False
    return root
