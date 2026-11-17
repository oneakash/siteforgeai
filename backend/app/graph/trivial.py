"""Trivial 2-node graph used to prove checkpoint recovery.

    START -> node_a -> node_b -> END

Every node writes a row to audit_log so we can later prove how many times
each node's side effects actually ran.
"""
import argparse
import asyncio
import os
import sys
from operator import add
from typing import Annotated, TypedDict

import psycopg
from langgraph.graph import END, START, StateGraph

from app.config import DATABASE_URL
from app.graph.checkpointer import checkpointer_pool


class ProbeState(TypedDict):
    project_id: str
    crash_in_b: bool
    steps: Annotated[list[str], add]


def _audit(project_id: str, action: str) -> None:
    with psycopg.connect(DATABASE_URL, autocommit=True) as conn:
        conn.execute(
            "INSERT INTO audit_log (project_id, actor, action, payload) "
            "VALUES (%s, 'probe', %s, '{}'::jsonb)",
            (project_id, action),
        )


async def node_a(state: ProbeState):
    _audit(state["project_id"], "node_a_executed")
    return {"steps": ["a"]}


async def node_b(state: ProbeState):
    _audit(state["project_id"], "node_b_started")
    if state.get("crash_in_b"):
        print("!! simulating hard crash inside node_b", flush=True)
        os._exit(137)  # like kill -9: no cleanup, no exception handling
    _audit(state["project_id"], "node_b_completed")
    return {"steps": ["b"]}


def build_graph(checkpointer):
    g = StateGraph(ProbeState)
    g.add_node("node_a", node_a)
    g.add_node("node_b", node_b)
    g.add_edge(START, "node_a")
    g.add_edge("node_a", "node_b")
    g.add_edge("node_b", END)
    return g.compile(checkpointer=checkpointer)


async def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("mode", choices=["start", "resume"])
    p.add_argument("--thread", required=True)
    p.add_argument("--project-id", required=True)
    p.add_argument("--crash-in-b", action="store_true")
    args = p.parse_args()

    config = {"configurable": {"thread_id": args.thread}}
    async with checkpointer_pool() as saver:
        graph = build_graph(saver)
        if args.mode == "start":
            out = await graph.ainvoke(
                {"project_id": args.project_id, "crash_in_b": args.crash_in_b, "steps": []},
                config,
                # "sync": each super-step's checkpoint is committed BEFORE the next
                # step starts. The default ("async") writes in the background, so a
                # hard kill can lose the last checkpoint and replay a finished node.
                durability="sync",
            )
        else:
            # input=None => continue from the latest checkpoint
            snap = await graph.aget_state(config)
            print(f"resuming; next nodes = {snap.next}; steps so far = {snap.values.get('steps')}")
            # Clear the crash flag in the persisted state before continuing.
            await graph.aupdate_state(config, {"crash_in_b": False}, as_node="node_a")
            out = await graph.ainvoke(None, config, durability="sync")
        print("FINAL STATE:", out)


if __name__ == "__main__":
    asyncio.run(main())
    sys.exit(0)
