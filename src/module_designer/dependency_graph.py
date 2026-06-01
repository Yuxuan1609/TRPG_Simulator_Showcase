"""依赖图 —— 管理 interaction/event/auto_trigger 之间的 requirement 依赖关系."""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import List, Optional
import random


@dataclass
class DependencyNode:
    entity_id: str
    entity_type: str = ""  # interaction / event / auto_trigger
    name: str = ""

    def to_dict(self) -> dict:
        return {"entity_id": self.entity_id, "entity_type": self.entity_type, "name": self.name}

    @classmethod
    def from_dict(cls, data: dict) -> "DependencyNode":
        return cls(entity_id=data["entity_id"], entity_type=data.get("entity_type", ""),
                   name=data.get("name", ""))


@dataclass(frozen=True)
class DependencyEdge:
    source: str     # 依赖方（需要满足条件才能触发）
    target: str     # 被依赖方（必须 completed 才能解除此依赖）
    dep_type: str = ""       # interaction / event / auto_trigger / item

    def to_dict(self) -> dict:
        return {"source": self.source, "target": self.target,
                "dep_type": self.dep_type}

    @classmethod
    def from_dict(cls, data: dict) -> "DependencyEdge":
        return cls(source=data["source"], target=data["target"],
                   dep_type=data.get("dep_type", ""))


class DependencyGraph:
    def __init__(self):
        self.nodes: dict[str, DependencyNode] = {}
        self.edges: List[DependencyEdge] = []
        self._circular_cut: bool = False
        self._cut_info: Optional[dict] = None

    def build(self, dependencies: list[dict]) -> None:
        for dep in dependencies:
            eid = dep["entity_id"]
            etype = ""
            if eid.startswith("I"):
                etype = "interaction"
            elif eid.startswith("AT"):
                etype = "auto_trigger"
            elif eid.startswith("E"):
                etype = "event"
            self.nodes[eid] = DependencyNode(entity_id=eid, entity_type=etype)

            for req in dep.get("requires", []):
                edge = DependencyEdge(
                    source=eid,
                    target=req.get("id", req.get("name", "")),
                    dep_type=req.get("type", ""),
                )
                self.edges.append(edge)
                target_id = edge.target
                if target_id not in self.nodes:
                    self.nodes[target_id] = DependencyNode(entity_id=target_id,
                        entity_type="item" if edge.dep_type == "item" else "")

    def detect_cycles(self) -> list[list[str]]:
        """DFS 检测所有循环。返回循环路径列表，每条路径是 entity_id 列表."""
        cycles = []
        WHITE, GRAY, BLACK = 0, 1, 2
        color = {nid: WHITE for nid in self.nodes}
        parent = {}

        def dfs(u):
            color[u] = GRAY
            for edge in self.edges:
                if edge.source == u:
                    v = edge.target
                    if v not in color:
                        color[v] = WHITE
                    if color.get(v) == GRAY:
                        path = [v, u]
                        cur = u
                        while cur in parent and parent[cur] != v:
                            cur = parent[cur]
                            path.append(cur)
                        path.append(v)
                        cycles.append(list(reversed(path)))
                    elif color.get(v) == WHITE:
                        parent[v] = u
                        dfs(v)
            color[u] = BLACK

        for nid in list(self.nodes.keys()):
            if color.get(nid) == WHITE:
                dfs(nid)
        return cycles

    def cut_edge(self, edge: DependencyEdge) -> None:
        self.edges = [e for e in self.edges if e is not edge]
        self._circular_cut = True
        self._cut_info = {"source": edge.source, "target": edge.target,
                          "dep_type": edge.dep_type}

    def cut_random_edge_in_cycles(self) -> bool:
        cycles = self.detect_cycles()
        if not cycles:
            return False
        cycle_edges = set()
        for path in cycles:
            for i in range(len(path) - 1):
                for e in self.edges:
                    if e.source == path[i + 1] and e.target == path[i]:
                        cycle_edges.add(e)
        if cycle_edges:
            self.cut_edge(random.choice(list(cycle_edges)))
            return True
        return False

    def to_dict(self) -> dict:
        return {
            "nodes": {nid: n.to_dict() for nid, n in self.nodes.items()},
            "edges": [e.to_dict() for e in self.edges],
            "_circular_cut": self._circular_cut,
            "_cut_info": self._cut_info,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "DependencyGraph":
        g = cls()
        g.nodes = {nid: DependencyNode.from_dict(nd) for nid, nd in data.get("nodes", {}).items()}
        g.edges = [DependencyEdge.from_dict(ed) for ed in data.get("edges", [])]
        g._circular_cut = data.get("_circular_cut", False)
        g._cut_info = data.get("_cut_info")
        return g
