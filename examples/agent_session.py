"""One repository per agent session: every step is a commit, a bad step is one
reset away, and the whole session is a git repository at the end.

    WEFT_TOKEN=weft_… WEFT_ORG=acme python examples/agent_session.py
"""

from __future__ import annotations

import os

from weftsh import DEFAULT_BASE_URL, Weft, WeftConflictError


def main() -> None:
    with Weft(
        token=os.environ["WEFT_TOKEN"],
        org=os.environ.get("WEFT_ORG", "acme"),
        base_url=os.environ.get("WEFT_URL", DEFAULT_BASE_URL),
    ) as weft:
        repo = weft.create_repo(description="agent session")
        print("session repository:", repo.name)

        # Step 1: the agent writes a first draft.
        step1 = (
            repo.create_commit(
                message="step 1: scaffold", expected_parent=None, context={"step": 1}
            )
            .put("greet.py", 'def greet():\n    return "hello"\n')
            .put("README.md", "# greeter\n")
            .send()
        )

        # Step 2: the agent goes sideways.
        step2 = (
            repo.create_commit(
                message="step 2: rewrite everything",
                expected_parent=step1.commit,
                context={"step": 2},
            )
            .delete("greet.py")
            .put("greet.js", 'console.log("hello")\n')
            .send()
        )

        # Review what step 2 did.
        diff = repo.get_diff(from_=step1.commit, to=step2.commit)
        print("step 2 changed:", ", ".join(f"{c.status} {c.path}" for c in diff.changes))

        # Undo it. Step 2 stays reachable by SHA for the audit trail.
        repo.reset(to=step1.commit, expected_head=step2.commit)
        print("after undo:", repo.read_file("greet.py"))

        # A stale writer is told where the branch really is.
        try:
            repo.create_commit(message="late", expected_parent=step2.commit).put("x", "y").send()
        except WeftConflictError as e:
            print("conflict; branch is at", e.current_tip)

        # Hand a sandbox a read-only remote for ten minutes.
        print("git clone", repo.get_remote_url(access="read", ttl=600))


if __name__ == "__main__":
    main()
