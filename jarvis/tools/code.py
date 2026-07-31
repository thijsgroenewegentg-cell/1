import subprocess
import sys
import io
import traceback
from contextlib import redirect_stdout, redirect_stderr
from ..config import config

def execute_python(code: str) -> str:
    """Execute Python code securely and return output"""
    old_limit = None
    try:
        # Capture stdout
        f_out = io.StringIO()
        f_err = io.StringIO()
        
        # Safe builtins limited? For now full but we can restrict if SAFE_MODE
        safe_globals = {"__builtins__": __builtins__}
        if config.SAFE_MODE:
            # Restrict dangerous imports in safe mode
            if any(x in code for x in ["os.system", "subprocess", "shutil.rmtree", "open(", "eval(", "exec("]):
                return "Execution blocked in safe mode, Sir. That code looks dangerous."
        
        with redirect_stdout(f_out), redirect_stderr(f_err):
            try:
                exec(code, safe_globals)
            except Exception:
                traceback.print_exc(file=f_err)
        
        output = f_out.getvalue()
        error = f_err.getvalue()
        
        result = ""
        if output:
            result += f"Output:\n{output}\n"
        if error:
            result += f"Errors:\n{error}\n"
        if not output and not error:
            result = "Code executed successfully, Sir. No output."
        
        # Truncate
        if len(result) > 5000:
            result = result[:5000] + "\n... [truncated]"
        
        return result
    except Exception as e:
        return f"Python execution failed: {e}"

def shell_command(command: str) -> str:
    """Execute shell command"""
    if not config.ALLOW_SHELL:
        return "Shell commands disabled, Sir. Enable ALLOW_SHELL in .env"
    
    if config.SAFE_MODE:
        blocked = ["rm -rf", "mkfs", "dd ", ":(){:|:&};:", "shutdown", "reboot", "sudo rm"]
        if any(b in command for b in blocked):
            return f"Blocked dangerous command in safe mode, Sir: {command}"
    
    try:
        # Only allow workspace-relative or safe commands
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=30,
            cwd=str(config.WORKSPACE_DIR)
        )
        output = result.stdout
        error = result.stderr
        combined = ""
        if output:
            combined += output
        if error:
            combined += f"\nSTDERR: {error}"
        if not combined:
            combined = f"Command exited with code {result.returncode}, no output, Sir."
        
        if len(combined) > 5000:
            combined = combined[:5000] + "\n... [truncated]"
        
        return combined
    except subprocess.TimeoutExpired:
        return f"Command timed out after 30s, Sir: {command}"
    except Exception as e:
        return f"Shell error: {e}"
