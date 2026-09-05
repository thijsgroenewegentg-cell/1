# /plugins/README.md

# Plugins

Skills that JARVIS wrote for itself.

When you ask JARVIS to integrate a GitHub repository ("find a library for QR
codes and add it to yourself"), the `self_improve` module clones the repo into
`data/repos/<skill>/`, asks the local LLM to write an adapter for it, validates
that adapter, and drops the result here as `<skill>.py`.

Every `.py` file in this directory that defines a `modules.base.BaseModule`
subclass is loaded automatically at start-up and becomes a first-class skill,
exactly like the built-in modules — its tools show up in the router, in
`help`, and in `--test`.

## Rules for a file in here

* one `BaseModule` subclass, with a unique `name`
* tools declared with the `@tool` decorator, `async`, returning `ModuleResult`
* heavy third-party imports done lazily *inside* the tool, so a missing
  dependency degrades to a polite message instead of breaking start-up
* no `os.system`, `subprocess`, `eval`, `exec` or `__import__` — generated
  adapters containing those are rejected before they are ever imported

## Managing them

```
"what plugins do you have"     → list_plugins
"remove the pyzbar plugin"     → remove_plugin (deletes the file, unloads live)
"reload the pyzbar plugin"     → reload_module (after you edit it by hand)
```

Disable one without deleting it by adding `modules.<name>: false` to
`config.yaml`. Hand-written files are welcome here too — same rules apply.
