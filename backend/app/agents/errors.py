class TransientAgentError(Exception):
    """Timeouts / rate limits / 5xx. Safe to retry with the same input
    (LangGraph RetryPolicy retries these)."""


class AgentOutputError(Exception):
    """The model kept returning invalid output after all corrective rounds.
    NOT transient: retrying blindly won't help. The Manager decides whether to
    retry with a different model, reassign, or ask the user."""

    def __init__(self, agent: str, problems: list[str]):
        self.agent = agent
        self.problems = problems
        super().__init__(
            f"agent '{agent}' produced invalid output after {len(problems)} attempt(s): {problems[-1][:300]}"
        )
