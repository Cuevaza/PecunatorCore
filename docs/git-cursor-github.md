# GitHub + Cursor on Windows (push, pull, merge)

Remote: [`https://github.com/Cuevaza/PecunatorCore.git`](https://github.com/Cuevaza/PecunatorCore.git).

## Symptoms you may have hit

- **`403 Forbidden`** while pushing → wrong GitHub account logged in Credential Manager (`CuevazaArt` vs org owner `Cuevaza`).
- SSO orgs → PAT must be **authorized for SSO**.

## Prefer SSH (fewer PAT surprises)

1. Generate (PowerShell):

   ```powershell
   ssh-keygen -t ed25519 -C "your_email" -f $env:USERPROFILE\.ssh\id_ed25519_pecunator -N ""
   ```

2. Add **public** key contents to GitHub → **Settings → SSH and GPG keys** (account that owns or can push to [`Cuevaza/PecunatorCore`](https://github.com/Cuevaza/PecunatorCore)).

3. If organization uses SSO: open the SSH key entry on GitHub and click **Enable SSO**.

4. Switch remote:

   ```powershell
   cd C:\Users\lexar\Desktop\PecunatorCore
   git remote set-url origin git@github.com:Cuevaza/PecunatorCore.git
   ssh -T git@github.com
   git fetch
   ```

5. In Cursor use the **integrated terminal** for `git pull` / `git push` / `git merge` (same Git as VS Code).

## Stay on HTTPS + PAT

1. GitHub → **Settings → Developer settings → Personal access tokens** (fine-grained or classic).
2. Scope at least **Contents** read/write for `Cuevaza/PecunatorCore`.
3. For org repos: authorize token **SSO** for the organization if prompted.
4. On first `git push`, Windows Git Credential Manager opens a browser; sign in as the GitHub user that **has write access**.
5. If old wrong account is cached:

   ```powershell
   git credential-manager erase https://github.com
   ```

   Next push prompts again.

## Cursor workflow agility

- **Source Control** view: stage, commit, sync (pull/push).
- Branch / merge / rebase via UI or CLI in terminal.
- **Git Graph** extension (VS Code marketplace) improves merge visualization if desired.

Verifying connectivity:

```powershell
git ls-remote origin
```

If this succeeds, auth is OK for fetch; push additionally requires repo write permission.
