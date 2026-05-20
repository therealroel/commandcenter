import subprocess


class GitService:
    def get_status(self, project_path: str) -> dict:
        def run(cmd):
            result = subprocess.run(
                cmd, cwd=project_path, capture_output=True, text=True
            )
            return result.stdout.strip()

        branch = run(["git", "rev-parse", "--abbrev-ref", "HEAD"])
        dirty = run(["git", "status", "--porcelain"]) != ""

        ahead = 0
        behind = 0
        rev_list = run(["git", "rev-list", "--left-right", "--count", f"{branch}...@{{u}}"])
        if rev_list:
            parts = rev_list.split("\t")
            if len(parts) == 2:
                ahead = int(parts[0])
                behind = int(parts[1])

        return {
            "branch": branch,
            "dirty": dirty,
            "ahead": ahead,
            "behind": behind,
        }
