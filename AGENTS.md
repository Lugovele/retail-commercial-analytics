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
