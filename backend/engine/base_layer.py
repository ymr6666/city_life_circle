from abc import ABC, abstractmethod


class TransportLayer(ABC):
    speed_kmh: float
    mode_name: str

    @abstractmethod
    def snap_origin(self, lat: float, lng: float) -> dict:
        pass

    @abstractmethod
    def reachable_nodes(self, start_node_id: int, time_budget_min: float) -> list:
        pass

    @abstractmethod
    def reachable_pois(self, node_ids: list[int]) -> list:
        pass
