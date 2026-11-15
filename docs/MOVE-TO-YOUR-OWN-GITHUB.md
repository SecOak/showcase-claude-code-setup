# Move it to your own GitHub

You have read-only access to this shared repository. To save your own settings, make a
**private** copy in your own GitHub account. Your copy will point at your repository as
`origin` (where you push) and at the shared one as `upstream` (where you fetch updates).

Why private: `Sync-ClaudeSeat.ps1` copies your Claude Code memory and your Git name and
email into your copy.

Pick one of the two paths below. Replace `<YOUR_GITHUB_USER>` with your GitHub user name
and `<SHARED_REPOSITORY_URL>` with the address of this shared repository.

You need Git installed. If it is not:

```powershell
winget install --id Git.Git --exact --silent
```

## Path A: the GitHub command-line tool

In PowerShell.

1. Install and sign in (skip what you already have):

   ```powershell
   winget install --id GitHub.cli --exact --silent
   gh auth login
   ```

   Close and reopen PowerShell after the install. At the sign-in prompts choose
   GitHub.com, HTTPS, "Yes" to authenticate Git, and "Login with a web browser".

2. Clone the shared repository:

   ```powershell
   git clone <SHARED_REPOSITORY_URL> "$env:USERPROFILE\repos\shared-tooling"
   Set-Location "$env:USERPROFILE\repos\shared-tooling"
   ```

3. Rename the shared remote to `upstream`:

   ```powershell
   git remote rename origin upstream
   ```

4. Create your private repository, set it as `origin`, and push, in one command:

   ```powershell
   gh repo create <YOUR_GITHUB_USER>/shared-tooling --private --source . --remote origin --push
   ```

5. Check:

   ```powershell
   git remote -v
   ```

   `origin` should show your repository and `upstream` the shared one.

## Path B: the GitHub website

1. Go to github.com, sign in, click the **+** at the top right, then **New repository**.
2. Name it `shared-tooling`. Choose **Private**. Leave "Add a README", ".gitignore" and
   "license" all **off** (the repository must be empty). Click **Create repository**.
3. In PowerShell, clone the shared repository:

   ```powershell
   git clone <SHARED_REPOSITORY_URL> "$env:USERPROFILE\repos\shared-tooling"
   Set-Location "$env:USERPROFILE\repos\shared-tooling"
   ```

4. Rename the shared remote and add yours:

   ```powershell
   git remote rename origin upstream
   git remote add origin https://github.com/<YOUR_GITHUB_USER>/shared-tooling.git
   ```

5. Push:

   ```powershell
   git push -u origin main
   ```

   The first push opens a browser window to sign in to GitHub.

6. Refresh the repository page on GitHub. The files should be there.

## Optional: turn on the secret scan

The repository ships a pre-commit hook that runs gitleaks before every commit and stops
the commit if it finds something that looks like a password or key.

1. Install gitleaks (the restore script also installs it):

   ```powershell
   winget install --id Gitleaks.Gitleaks --exact --silent
   ```

2. Turn the hook on for your copy:

   ```powershell
   git -C "$env:USERPROFILE\repos\shared-tooling" config core.hooksPath .githooks
   ```

3. Test it. This should print "no leaks found":

   ```powershell
   gitleaks git "$env:USERPROFILE\repos\shared-tooling" --no-banner
   ```

The setting is per clone, so repeat step 2 on each new computer
([NEW-COMPUTER.md](NEW-COMPUTER.md) includes it).

## Afterwards

- Push your own changes with `git push` (it goes to `origin`, your repository).
- Pull shared updates with [KEEPING-IT-UPDATED.md](KEEPING-IT-UPDATED.md).
- Never push to `upstream`. You do not have permission, and Git will refuse.
