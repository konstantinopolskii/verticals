"""The Documents desk (Inbox and Documents redesign, rounds 2–7, KK 6–7 Oct 2026): every document on one desk, in
stacks by the goal it accumulates under, the stacks grouped by value in the board's order; the documents no goal holds
first, under "No goal", one stack for each age.

A stack is a goal and every document linked anywhere in its subtree. A goal whose subtree holds more than ``CAP``
documents and has children holding some splits into its children's stacks, keeping its own links as a stack of its
own, so no stack grows into a pile nobody can browse; a value always splits, since it is the group's heading. A document lands in one stack only: the biggest pile claims it
first. Read-only, three statements; the page preview is the first ``EXCERPT`` characters of the body, the rest is
read when the document opens.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime

import psycopg

from verticals.core import vertical

CAP = 22
EXCERPT = 1500


@dataclass(frozen=True)
class DeskDoc:
    id: str
    path: str
    title: str | None
    excerpt: str
    created_at: datetime
    updated_at: datetime
    revision: int


@dataclass(frozen=True)
class Stack:
    goal_id: str
    goal_title: str
    docs: tuple[str, ...]          # newest first


@dataclass(frozen=True)
class ValueGroup:
    id: str | None                 # None: goals under no value
    title: str | None
    color: str | None
    stacks: tuple[Stack, ...]


@dataclass(frozen=True)
class Desk:
    docs: dict[str, DeskDoc]
    no_goal: tuple[str, ...]       # newest first
    values: tuple[ValueGroup, ...]


def desk(conn: psycopg.Connection, *, owner: str) -> Desk:
    goals = conn.execute(
        "SELECT id, parent_id, title, vertical, color, position FROM goals WHERE owner = %(owner)s",
        {"owner": owner},
    ).fetchall()
    links = conn.execute(
        "SELECT DISTINCT goal_id, doc_id FROM goal_doc_links WHERE owner = %(owner)s", {"owner": owner}
    ).fetchall()
    rows = conn.execute(
        "SELECT id, path, title, left(body, %(n)s), created_at, updated_at, revision FROM docs WHERE owner = %(owner)s",
        {"owner": owner, "n": EXCERPT},
    ).fetchall()
    docs = {r[0]: DeskDoc(*r) for r in rows}

    title = {g[0]: g[2] for g in goals}
    parent = {g[0]: g[1] for g in goals}
    kids: dict[str, list[str]] = defaultdict(list)
    for g in sorted(goals, key=lambda g: (g[5], g[0])):
        if g[1]:
            kids[g[1]].append(g[0])
    own: dict[str, set[str]] = defaultdict(set)
    for goal_id, doc_id in links:
        if goal_id in title and doc_id in docs:
            own[goal_id].add(doc_id)

    under: dict[str, set[str]] = {}

    def subtree(i: str) -> set[str]:
        if i not in under:
            s = set(own[i])
            for k in kids[i]:
                s |= subtree(k)
            under[i] = s
        return under[i]

    piles: list[tuple[str, set[str]]] = []

    def split(i: str, heading: bool = False) -> None:
        """heading: a value is its group's heading, never a stack of its own name, so it always splits."""
        s = subtree(i)
        if not s:
            return
        holding = [k for k in kids[i] if subtree(k)]
        if (len(s) > CAP or heading) and holding:
            if own[i]:
                piles.append((i, set(own[i])))
            for k in holding:
                split(k)
        else:
            piles.append((i, s))

    roots = sorted((g for g in goals if g[1] is None), key=lambda g: (not vertical.is_value_scale(g[3]), g[5], g[0]))
    for r in roots:
        split(r[0], heading=vertical.is_value_scale(r[3]))

    seen: set[str] = set()
    claimed: dict[str, list[str]] = {}
    for i, s in sorted(piles, key=lambda p: -len(p[1])):
        new = s - seen
        seen |= s
        if new:
            claimed[i] = sorted(new, key=lambda d: docs[d].updated_at, reverse=True)

    order: dict[str, int] = {}

    def walk(i: str) -> None:
        order[i] = len(order)
        for k in kids[i]:
            walk(k)

    for r in roots:
        walk(r[0])

    def root_of(i: str) -> str:
        while parent[i]:
            i = parent[i]
        return i

    by_root: dict[str, list[Stack]] = defaultdict(list)
    for i in sorted(claimed, key=lambda i: order.get(i, 0)):
        by_root[root_of(i)].append(Stack(goal_id=i, goal_title=title[i], docs=tuple(claimed[i])))

    values: list[ValueGroup] = []
    others: list[Stack] = []
    for r in roots:
        stacks = by_root.get(r[0])
        if not stacks:
            continue
        if vertical.is_value_scale(r[3]):
            values.append(ValueGroup(id=r[0], title=r[2], color=r[4], stacks=tuple(stacks)))
        else:
            others.extend(stacks)
    if others:
        values.append(ValueGroup(id=None, title=None, color=None, stacks=tuple(others)))

    linked = {d for _, d in links}
    no_goal = tuple(sorted((d for d in docs if d not in linked), key=lambda d: docs[d].created_at, reverse=True))
    return Desk(docs=docs, no_goal=no_goal, values=tuple(values))
