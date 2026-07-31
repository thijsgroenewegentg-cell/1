# JARVIS Workspace
This is JARVIS's allowed workspace. All file operations are restricted here in safe mode.

- Put projects here
- JARVIS can read/write/list files here
- Use `file_list`, `file_read`, `file_write` tools

Example:
Sir: "Jarvis, create a python file that says hello"
JARVIS will write to workspace/hello.py

Sir: "Jarvis, what files do we have?"
-> file_list(".")
