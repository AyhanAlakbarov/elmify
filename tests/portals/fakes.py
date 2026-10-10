from apps.portals.session import FieldAction


class FakePortalSession:
    """In-memory PortalSession. Counts observe() calls so tests can assert
    that the replay path makes no LLM call at all."""

    def __init__(
        self,
        observed: list[FieldAction] | None = None,
        elements: dict[str, dict[str, str]] | None = None,
    ) -> None:
        self._observed = observed or []
        #: selector -> attributes. Present keys exist; absent keys do not.
        self.elements = elements or {}
        self.observe_calls = 0
        self.observe_variables: list[dict[str, str] | None] = []
        self.values: dict[str, str] = {}
        self.visited: list[str] = []
        self.enter_presses = 0

    def goto(self, url: str) -> None:
        self.visited.append(url)

    def observe(
        self, instruction: str, variables: dict[str, str] | None = None
    ) -> list[FieldAction]:
        self.observe_calls += 1
        self.observe_variables.append(variables)
        return list(self._observed)

    def act(self, action: FieldAction, variables: dict[str, str]) -> None:
        self.values[action.selector] = variables["value"]

    def read_value(self, selector: str) -> str:
        return self.values.get(selector, "")

    def exists(self, selector: str) -> bool:
        return selector in self.elements or selector in self.values

    def query_attribute(self, selector: str, attribute: str) -> str | None:
        return self.elements.get(selector, {}).get(attribute)

    def press_enter(self) -> None:
        self.enter_presses += 1
