"""
Longleaf - layered layout for the Editor's graph view (no GUI).

Flows are graphs, not trees: answers can merge back into a shared step and
can loop. So this isn't a tree layout. It's a small Sugiyama-style layered
layout:

  1. Back edges (found by DFS from the start) are ignored for layering, so
     loops can't stretch or hang the layout.
  2. Each node's layer is its longest forward path from the start, so a
     merge point always sits to the right of every step that leads to it.
  3. Within a layer, nodes are ordered by a few barycenter sweeps to cut
     edge crossings.
  4. Nodes not reachable from the start go in a second band below, laid out
     the same way, so they're visible but clearly set apart.

Deterministic: the same input always gives the same positions.
"""

from __future__ import annotations

from dataclasses import dataclass

BARYCENTER_SWEEPS = 4


@dataclass(frozen=True)
class Placement:
    layer: int   # column, 0 = the start
    row: float   # vertical slot; the unreachable band continues below the reachable one


def _forward_layers(nodes: list[str], edges: list[tuple[str, str]], roots: list[str]):
    """(layer per node, back edges) for the nodes reachable from `roots`."""
    out: dict[str, list[str]] = {n: [] for n in nodes}
    for a, b in edges:
        if a in out and b in out:
            out[a].append(b)

    state: dict[str, int] = {}          # 1 = on the DFS stack, 2 = done
    back: set[tuple[str, str]] = set()
    post: list[str] = []
    for root in roots:
        if root in state:
            continue
        state[root] = 1
        stack = [(root, iter(out[root]))]
        while stack:
            node, it = stack[-1]
            for nxt in it:
                if nxt not in state:
                    state[nxt] = 1
                    stack.append((nxt, iter(out[nxt])))
                    break
                if state[nxt] == 1:
                    back.add((node, nxt))
            else:
                state[node] = 2
                post.append(node)
                stack.pop()

    layer = {n: 0 for n in post}
    for node in reversed(post):          # reverse postorder = topological order of the forward graph
        for nxt in out[node]:
            if (node, nxt) not in back and nxt in layer:
                layer[nxt] = max(layer[nxt], layer[node] + 1)
    return layer, back


def _order_rows(layers: dict[str, int], edges: list[tuple[str, str]], discovery: dict[str, int]) -> dict[str, float]:
    """Row index per node, ordered within each layer to reduce crossings."""
    by_layer: dict[int, list[str]] = {}
    for n in sorted(layers, key=discovery.__getitem__):
        by_layer.setdefault(layers[n], []).append(n)
    preds: dict[str, list[str]] = {n: [] for n in layers}
    succs: dict[str, list[str]] = {n: [] for n in layers}
    for a, b in edges:
        if a in layers and b in layers and a != b:
            succs[a].append(b)
            preds[b].append(a)

    pos = {n: float(i) for col in by_layer.values() for i, n in enumerate(col)}

    def sweep(cols, neighbours):
        for col in cols:
            def key(n):
                ns = neighbours[n]
                return (sum(pos[m] for m in ns) / len(ns)) if ns else pos[n]
            col.sort(key=key)     # stable, so ties keep their previous order
            for i, n in enumerate(col):
                pos[n] = float(i)

    ordered = [by_layer[k] for k in sorted(by_layer)]
    for _ in range(BARYCENTER_SWEEPS):
        sweep(ordered[1:], preds)
        sweep(reversed(ordered[:-1]), succs)
    return pos


def layout(nodes: list[str], edges: list[tuple[str, str]], start: str | None) -> dict[str, Placement]:
    """Place every node. `nodes` must be in a stable order (it breaks ties);
    edges naming unknown nodes are ignored."""
    node_set = set(nodes)
    edges = [(a, b) for a, b in edges if a in node_set and b in node_set]
    discovery = {n: i for i, n in enumerate(nodes)}

    reach_roots = [start] if start in node_set else []
    layers_a, back_a = _forward_layers(nodes, edges, reach_roots)
    reached = set(layers_a)

    # Everything else: roots are the nodes nothing (else unreached) points at, then any leftovers (pure cycles).
    rest = [n for n in nodes if n not in reached]
    pointed_at = {b for a, b in edges if a in rest and b in rest and a != b}
    rest_roots = [n for n in rest if n not in pointed_at] + rest
    layers_b, back_b = _forward_layers(rest, edges, rest_roots)

    result: dict[str, Placement] = {}
    next_row = 0.0
    for layers, back in ((layers_a, back_a), (layers_b, back_b)):
        if not layers:
            continue
        rows = _order_rows(layers, [e for e in edges if e not in back], discovery)
        for n, layer in layers.items():
            result[n] = Placement(layer, next_row + rows[n])
        next_row += max(rows.values()) + 2     # a blank row between the bands
    return result
