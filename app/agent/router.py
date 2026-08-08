"""Filesystem-based skill system with progressive disclosure.

The router reads only each skill's `description` frontmatter to choose. Only the
selected skill's full SKILL.md is loaded into the model's context. Adding a
directory under skills/ adds a role with no code change — tested in
tests/test_skills.py.

Routing is a two-stage decision:
  1. A deterministic keyword pass over the skill descriptions. Cheap, and it
     resolves the large majority of questions that name their setting.
  2. The language model, but only when stage 1 is ambiguous. This keeps the
     router measurable (role-routing accuracy is reported separately in the
     evaluation) and keeps the common case free.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from app.models import IndexKind, Role


@dataclass
class Skill:
    name: str
    description: str
    governing_agencies: list[str]
    primary_index: IndexKind
    body: str
    path: Path
    role: Role
    route_terms: list[str]
    _term_patterns: list[re.Pattern] = field(default_factory=list, repr=False)

    def matches(self, question: str) -> int:
        """Count route terms present in the question, matched on word
        boundaries. Substring matching was wrong in both directions: `school`
        matched inside `preschool`, and short terms like `pe` matched inside
        `open` and `expected`."""
        if not self._term_patterns:
            self._term_patterns = [self._compile(term) for term in self.route_terms]
        return sum(1 for pat in self._term_patterns if pat.search(question))

    @staticmethod
    def _compile(term: str) -> re.Pattern:
        """Word-boundary match, tolerating a plural on the final word.

        Operational questions pluralise freely — "take the K2s to the
        playground", "my scaffolders", "the students". Without this, `k2` failed
        to match `K2s` and the question routed to general_public, which drops the
        vulnerable-cohort posture that governs a preschool.
        """
        words = [re.escape(w) for w in term.split()]
        words[-1] += r"s?"
        return re.compile(r"\b" + r"\s+".join(words) + r"\b")

    @property
    def known_gaps(self) -> str:
        m = re.search(r"^## Known gaps\s*\n(.*?)(?=\n## |\Z)", self.body, re.S | re.M)
        return m.group(1).strip() if m else ""


class SkillRouter:
    def __init__(self, skills_dir: Path) -> None:
        self.skills_dir = skills_dir
        self.skills: dict[str, Skill] = {}
        self.reload()

    def reload(self) -> None:
        """Re-scan the skills directory. Hot-loadable by design."""
        self.skills = {}
        for skill_md in sorted(self.skills_dir.glob("*/SKILL.md")):
            skill = self._parse(skill_md)
            self.skills[skill.name] = skill

    @staticmethod
    def _parse(path: Path) -> Skill:
        raw = path.read_text(encoding="utf-8")
        end = raw.find("\n---", 3)
        meta = yaml.safe_load(raw[3:end])
        body = raw[end + 4 :].lstrip("\n")
        return Skill(
            name=meta["name"],
            description=" ".join(meta["description"].split()),
            governing_agencies=meta.get("governing_agencies", []),
            primary_index=IndexKind(meta.get("primary_index", "psi_24h")),
            body=body,
            path=path,
            role=Role(meta["role"]),
            route_terms=[t.lower() for t in meta.get("route_terms", [])],
        )

    # -- progressive disclosure --------------------------------------------

    def descriptions_only(self) -> str:
        """Stage-1 context: names and descriptions, nothing else. This is what
        'progressive disclosure' means here — the router never sees the six full
        skill bodies, only the ~30 words each needs to be chosen."""
        return "\n".join(f"- {s.name}: {s.description}" for s in self.skills.values())

    def load(self, name: str) -> Skill | None:
        return self.skills.get(name)

    def by_role(self, role: Role) -> Skill | None:
        for s in self.skills.values():
            if s.role == role:
                return s
        return None

    # -- routing ------------------------------------------------------------

    def route_deterministic(self, question: str) -> tuple[Skill | None, float]:
        """Keyword scoring over declared route terms. Returns the best skill and
        a confidence in [0, 1]. Confidence below 0.5 means stage 2 should run."""
        q = question.lower()
        scores: dict[str, int] = {}
        for name, skill in self.skills.items():
            hits = skill.matches(q)
            if hits:
                scores[name] = hits
        if not scores:
            return None, 0.0

        # general_public is the fallback role, not a peer. Any institutional
        # signal outranks it at equal hit count: "do we still take the K2s to the
        # playground" matches both `k2` (preschool) and `playground`
        # (general_public), and answering it as a member of the public drops the
        # entire vulnerable-cohort posture that governs a preschool.
        def sort_key(kv: tuple[str, int]) -> tuple[int, int, str]:
            name, hits = kv
            institutional = 0 if self.skills[name].role == Role.general_public else 1
            return (hits, institutional, name)

        ordered = sorted(scores.items(), key=sort_key, reverse=True)
        best_name, best_hits = ordered[0]
        runner_up = ordered[1][1] if len(ordered) > 1 else 0
        margin = best_hits - runner_up
        if margin > 0:
            confidence = min(1.0, 0.5 + 0.25 * margin)
        elif self.skills[best_name].role != Role.general_public:
            # Tie broken in favour of an institutional role: a real preference,
            # but a weaker one than an outright keyword margin.
            confidence = 0.6
        else:
            confidence = 0.4
        return self.skills[best_name], confidence

    def route_prompt(self, question: str) -> tuple[str, str]:
        """Stage-2 prompt. Returns (system, user)."""
        system = (
            "You classify the operational role of someone asking a question about "
            "haze in Singapore. Reply with JSON only: "
            '{"skill": "<skill name>", "confidence": <0-1>}. '
            "Choose exactly one skill from the list. If the asker is not acting "
            "in any institutional role, choose general_public."
        )
        user = (
            f"Available skills:\n{self.descriptions_only()}\n\n"
            f"Question: {question}\n\n"
            "Which skill governs this question?"
        )
        return system, user
