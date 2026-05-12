---
description: Show unified Claude Code + OpenCode token usage
---

Use the `token-usage` skill.

If the user passed arguments, map them directly to the bundled script flags.
If no arguments were provided, default to `--period today`.

Run:

```bash
python "$HOME/.config/opencode/skills/token-usage/token_usage.py" $ARGUMENTS
```

Then summarize the result briefly for the user.
