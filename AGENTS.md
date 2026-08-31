# Git Commit Convention

All future commits in this repository must use this format:

```text
<type>: <short lowercase imperative/description>
```

Allowed primary types:

```text
feat:
fix:
refine:
test:
docs:
chore:
refactor:
```

Subject rules:

- use lowercase after `type:`;
- keep the subject short and specific;
- do not end with a period;
- do not use Title Case;
- do not use vague subjects such as `updates`, `changes`, or `cleanup`;
- describe the concrete scope of the change;
- prefer roughly 72 characters or less when possible.

Type guidance:

- `feat:` for a new user-facing or product capability;
- `fix:` for a real defect or incorrect behavior;
- `refine:` for improving existing behavior or visuals without adding a feature or fixing a functional defect;
- `refactor:` for internal restructuring without behavior changes;
- `test:` for test-only changes;
- `docs:` for documentation-only changes;
- `chore:` for repository, process, or tooling maintenance.

Before every `git commit`, run this self-check:

1. Does the message have a conventional type and colon?
2. Is the subject lowercase?
3. Is the subject specific?
4. Does the type match the nature of the change?
5. Is there no period at the end?
6. Is there no Title Case?
7. Is the commit scoped and not mixing independent tasks?

If any check fails, fix the commit message before committing.

Independent tasks must be committed independently. Do not combine unrelated UI,
business-rule, metric, documentation, or process changes into one commit simply
because they were performed consecutively.

## Git Branch and Worktree Hygiene

`main` is the only persistent production branch by default. Temporary
`codex/*` branches and worktrees exist only while they are actively useful, and
must not become an archive of completed tasks.

Create a separate temporary `codex/*` branch or worktree only when isolation is
actually needed, such as for parallel work, experimental changes, risky
refactors, isolation from a dirty `main`, independent reviewer or remediation
flows, read-only audits that need an immutable filesystem context, or an
explicit user request. For short, sequential, scoped tasks, a separate worktree
is not required when `main` is clean and synced and no parallel conflict exists.
Do not create branches or worktrees by habit when isolation is unnecessary.

After a temporary branch has been fully integrated into `main`, the reviewer
lifecycle is approved and complete, relevant tests or browser acceptance have
passed, `main` has been pushed and is clean/synced, the temporary worktree is
clean, the branch contains no unique commits or patches, and the branch is not
used by an active task, remove it as a housekeeping step or explicitly retain it
with a reason.

Preferred cleanup order:

1. Confirm the worktree is clean.
2. Confirm the branch is merged into or patch-equivalent with `main`.
3. Confirm the task is inactive.
4. Remove the worktree.
5. Remove the local branch with `git branch -d`.
6. Remove the remote branch if it is no longer needed.

Do not use `git branch -D` when ordinary `git branch -d` should work.

Never automatically delete a branch or worktree when the worktree is dirty,
there are staged files, there are untracked files, there are unique commits or
patches, the branch has diverged, the branch may be used by an active task, or
there is uncertainty that the work is already integrated. Classify those cases
as `DIRTY_REVIEW_REQUIRED`, `KEEP_UNMERGED`, `KEEP_ACTIVE_OR_RECENT`, or
`UNKNOWN`, and stop until the user makes a separate decision.

Before deleting a temporary branch or worktree, run at least:

```text
git status --short --branch
git worktree list --porcelain
git log main..branch
git log branch..main
git cherry main branch
```

Check patch equivalence when changes may have been cherry-picked under
different SHAs. Do not rely only on `git branch --merged`.

Active worktrees are protected. Do not delete worktrees or branches that were
updated very recently and may be used by a parallel task, are locked, have
modified files, or are tied to the current Codex workflow. If activity cannot be
ruled out with evidence, do not delete them.

Stashes are separate from branch cleanup. Branch and worktree housekeeping must
not automatically run `stash pop`, `stash apply`, `stash drop`, move stash
contents, or classify a stash as safe to delete. Existing stashes must not be
touched without a separate explicit user request.

Do not use destructive cleanup such as `git reset --hard`, force push,
destructive checkout, implicit discard of local changes, or history rewrite
without separate explicit user permission.

The desired normal repository state after tasks finish is `main` plus only
temporary branches and worktrees that are genuinely active. Do not leave a
collection of completed `codex/*` branches just in case.

If a task used a temporary branch or worktree, the final report must explicitly
state the branch/worktree, whether it was integrated into `main`, whether unique
work remains, whether the worktree is clean, whether it is safe to remove,
whether it was removed or intentionally retained, and the retention reason when
applicable.
