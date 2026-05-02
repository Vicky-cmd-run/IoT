from __future__ import annotations

import heapq
from typing import Dict, Tuple

from network_topology import heuristic_distance
from model import RouteRequest, RouteResponse


def build_weighted_graph(
    graph: dict[str, dict[str, float]],
    congestion_penalties: dict[str, float],
) -> Dict[str, Dict[str, float]]:
    weighted_graph: Dict[str, Dict[str, float]] = {}
    for source, neighbors in graph.items():
        weighted_graph[source] = {}
        for target, base_weight in neighbors.items():
            edge_key = f"{source}->{target}"
            penalty = congestion_penalties.get(edge_key, 0.0)
            penalty_factor = 1 + penalty
            if penalty >= 1.0:
                penalty_factor += penalty * 0.75
            elif penalty >= 0.45:
                penalty_factor += penalty * 0.35
            weighted_graph[source][target] = round(base_weight * penalty_factor, 2)
    return weighted_graph


def astar_shortest_path(
    graph: dict[str, dict[str, float]],
    source: str,
    destination: str,
) -> Tuple[list[str], float]:
    queue: list[tuple[float, float, str, list[str]]] = [
        (heuristic_distance(source, destination), 0.0, source, [source])
    ]
    visited: dict[str, float] = {}

    while queue:
        _, cost, node, path = heapq.heappop(queue)
        if node == destination:
            return path, round(cost, 2)
        if node in visited and visited[node] <= cost:
            continue
        visited[node] = cost
        for neighbor, weight in graph.get(node, {}).items():
            next_cost = cost + weight
            priority = next_cost + heuristic_distance(neighbor, destination)
            heapq.heappush(queue, (priority, next_cost, neighbor, path + [neighbor]))

    return [], float("inf")


def compute_best_route(request: RouteRequest) -> RouteResponse:
    weighted_graph = build_weighted_graph(request.graph, request.congestion_penalties)
    path, total_cost = astar_shortest_path(
        weighted_graph,
        request.source,
        request.destination,
    )
    reasoning = (
        "Route selected using A* search with congestion-aware edge costs, so the path "
        "balances shortest progress toward the destination with real-time traffic penalties."
    )
    return RouteResponse(
        vehicle_id=request.vehicle_id,
        best_path=path,
        estimated_cost=total_cost,
        reasoning=reasoning,
    )
