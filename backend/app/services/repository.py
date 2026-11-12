import base64, os, re, subprocess, tempfile
from pathlib import Path
from urllib.parse import urlparse
class RepositoryError(Exception): pass
def clone_repository(url, branch, token, timeout):
    parsed=urlparse(str(url))
    if parsed.scheme not in {"https","http"} or not parsed.hostname: raise RepositoryError("Use an HTTPS/HTTP Git URL.")
    if parsed.username or parsed.password: raise RepositoryError("Do not embed credentials in URL; use the token field.")
    temp=tempfile.TemporaryDirectory(prefix="repolens_"); dest=Path(temp.name)/"repo"
    cmd=["git","clone","--depth","1","--no-tags"]
    if branch:
        if branch.startswith("-") or not re.fullmatch(r"[A-Za-z0-9._/-]+",branch):
            temp.cleanup(); raise RepositoryError("Invalid branch name.")
        cmd += ["--branch",branch]
    cmd += [str(url),str(dest)]; env=os.environ.copy()
    if token:
        auth=base64.b64encode(f"x-access-token:{token}".encode()).decode()
        env["GIT_CONFIG_COUNT"]="1"; env["GIT_CONFIG_KEY_0"]="http.extraheader"
        env["GIT_CONFIG_VALUE_0"]=f"AUTHORIZATION: basic {auth}"
    try: p=subprocess.run(cmd,capture_output=True,text=True,timeout=timeout,env=env)
    except subprocess.TimeoutExpired:
        temp.cleanup(); raise RepositoryError("Git clone timed out.")
    except FileNotFoundError:
        temp.cleanup(); raise RepositoryError("Git is not installed or unavailable on PATH.")
    if p.returncode:
        msg=(p.stderr or p.stdout or "Git clone failed").strip()
        if token: msg=msg.replace(token,"[REDACTED]")
        temp.cleanup(); raise RepositoryError(msg[-1000:])
    return temp,dest
