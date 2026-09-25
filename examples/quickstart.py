import os
import subprocess
import tempfile
from pathlib import Path

from weftsh import DEFAULT_BASE_URL, Weft

weft = Weft(
    token=os.environ["WEFT_TOKEN"],
    org=os.environ["WEFT_ORG"],
    base_url=os.environ.get("WEFT_URL", DEFAULT_BASE_URL),  # optional
)

# 1. A repository of its own: a real git remote, made in well under a second.
repo = weft.create_repo()
print("created   ", repo.name)

# 2. A commit, straight over HTTP. No clone, no checkout, no disk.
result = (
    repo.create_commit(message="first commit")
    .put("hello.txt", "hello from the Weft SDK\n")
    .send()
)
print("committed ", result.commit[:7])

# 3. Read it back, at the branch tip or at any commit.
print("read back ", repr(repo.read_file("hello.txt")))

# 4. It is still git. This URL carries a credential for this repository
#    only, and it expires in an hour.
url = repo.get_remote_url()
clone = Path(tempfile.mkdtemp(prefix="weft-")) / repo.name
subprocess.run(["git", "clone", "--quiet", url, str(clone)], check=True)
print("cloned    ", (clone / "hello.txt").read_text().strip())
