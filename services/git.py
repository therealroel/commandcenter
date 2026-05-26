import gevent.subprocess as subprocess


class GitService:
    def get_status(self, project_path: str) -> dict:
        def run(cmd):
            result = subprocess.run(
                cmd, cwd=project_path, capture_output=True, text=True, errors="replace"
            )
            return result.stdout.strip()

        branch = run(["git", "rev-parse", "--abbrev-ref", "HEAD"])
        if not branch:
            return {"branch": None, "dirty": False, "ahead": 0, "behind": 0, "upstream": False}

        dirty = run(["git", "status", "--porcelain"]) != ""

        upstream = run(["git", "rev-parse", "--abbrev-ref", f"{branch}@{{u}}"])
        if not upstream:
            return {
                "branch": branch,
                "dirty": dirty,
                "ahead": 0,
                "behind": 0,
                "upstream": False,
            }

        ahead = 0
        behind = 0
        rev_list = run(["git", "rev-list", "--left-right", "--count", f"{branch}...@{{u}}"])
        if rev_list:
            parts = rev_list.split("\t")
            if len(parts) == 2:
                try:
                    ahead = int(parts[0])
                    behind = int(parts[1])
                except ValueError:
                    pass

        return {
            "branch": branch,
            "dirty": dirty,
            "ahead": ahead,
            "behind": behind,
            "upstream": True,
        }