import subprocess


class GitStatusWidget:
    def __init__(self, term, project_path: str):
        self.term = term
        self.project_path = project_path

    def _run_git(self, args: list) -> tuple[str, int]:
        try:
            result = subprocess.run(
                ["git"] + args,
                cwd=self.project_path,
                capture_output=True,
                text=True
            )
            return result.stdout.strip(), result.returncode
        except Exception:
            return "", 1

    def render(self) -> str:
        branch_out, branch_rc = self._run_git(["rev-parse", "--abbrev-ref", "HEAD"])
        if branch_rc != 0:
            return "Branch: not a git repo"

        branch = branch_out

        status_out, _ = self._run_git(["status", "--porcelain"])
        dirty = "*" if status_out else ""

        log_out, log_rc = self._run_git(["log", "-3", "--oneline"])
        commits = log_out.split("\n") if log_out else []

        lines = [f"Branch: {branch}{dirty}"]
        lines.append(f"Dirty: {'yes' if status_out else 'no'}")
        lines.append("Last commits:")
        for commit in commits:
            if commit:
                lines.append(f"  {commit}")

        return "\n".join(lines)