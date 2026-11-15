# New computer checklist

Do these in order. Each step says which window to use. "PowerShell" means Windows
PowerShell, the blue one that comes with Windows, unless it says PowerShell 7.
Run everything as your normal user. Nothing here needs "Run as administrator"; some
installers show a User Account Control prompt, and you click Yes.

## Before you leave the old computer

1. **Capture your configuration.** In PowerShell:

   ```powershell
   & "$env:USERPROFILE\repos\shared-tooling\scripts\Sync-ClaudeSeat.ps1" -Commit
   ```

2. **Check what was captured**, then push it to your private copy:

   ```powershell
   git -C "$env:USERPROFILE\repos\shared-tooling" show --stat
   git -C "$env:USERPROFILE\repos\shared-tooling" push
   ```

3. **Optional: back up your conversation history.** Your Claude Code folder holds past
   conversations, which are too large and too personal for git. If you use OneDrive, copy
   them there:

   ```powershell
   & "$env:USERPROFILE\repos\shared-tooling\scripts\Backup-ClaudeToOneDrive.ps1"
   ```

   Wait until the OneDrive icon says it is up to date. Write down the old computer's
   name (run `$env:COMPUTERNAME`); you need it in step 9.

## On the new computer

4. **Update Windows** and restart until Windows Update has nothing left.

5. **Sign in to OneDrive** (only if you used step 3) and let it finish syncing.

6. **Allow local scripts to run.** In PowerShell:

   ```powershell
   Set-ExecutionPolicy -Scope CurrentUser RemoteSigned -Force
   ```

7. **Install Git and the GitHub command-line tool.** In PowerShell:

   ```powershell
   winget install --id Git.Git --exact --silent
   winget install --id GitHub.cli --exact --silent
   ```

   Close PowerShell and open a new one so the new programs are found.

8. **Sign in to GitHub.** In PowerShell:

   ```powershell
   gh auth login
   ```

   Choose GitHub.com, HTTPS, "Yes" to authenticate Git, and "Login with a web browser".

9. **Run the bootstrap.** In PowerShell, replacing `<YOUR_GITHUB_USER>`:

   ```powershell
   git clone https://github.com/<YOUR_GITHUB_USER>/shared-tooling.git "$env:USERPROFILE\repos\shared-tooling"
   & "$env:USERPROFILE\repos\shared-tooling\scripts\Bootstrap-NewComputer.ps1" -RepoUrl https://github.com/<YOUR_GITHUB_USER>/shared-tooling.git
   ```

   If you made a OneDrive backup in step 3, add
   `-FromOneDrive -SourceMachine <OLD_COMPUTER_NAME>` to the second line to bring back
   your conversation history too. Add `-RegisterBackupTask` if you want the hourly
   backup on this computer as well.

   The script installs Claude Code, Node.js, Python, uv, PowerShell 7 and gitleaks,
   copies your configuration into `%USERPROFILE%\.claude`, and deploys the hooks to
   `C:\Dev\claude-hooks`. It prints a table of what it did at the end.

10. **Sign in to Claude Code.** Open a new PowerShell window and run:

    ```powershell
    claude
    ```

    Follow the browser sign-in, then type `/exit`.

11. **Finish the plugins.** Plugins cannot install before you sign in, so if the table
    in step 9 said "plugins FAILED", run the restore again without the installs:

    ```powershell
    & "$env:USERPROFILE\repos\shared-tooling\scripts\Restore-ClaudeSeat.ps1" -SkipInstalls
    ```

12. **Set your Git identity** (the restore never copies a name or email into a new
    `.gitconfig` from this shared repository):

    ```powershell
    git config --global user.name "<YOUR_NAME>"
    git config --global user.email "<YOUR_GITHUB_NOREPLY_EMAIL>"
    ```

    Your private noreply address is on GitHub under Settings, Emails.

13. **Turn on the secret scan for your copy.** In PowerShell:

    ```powershell
    git -C "$env:USERPROFILE\repos\shared-tooling" config core.hooksPath .githooks
    ```

## Check that it worked

14. **Hooks are deployed:**

    ```powershell
    & "$env:USERPROFILE\repos\shared-tooling\deploy\Deploy-Hooks.ps1"
    ```

    Every line should say "in sync".

15. **The guard answers.** Start `claude` in any folder and ask it to run
    `git push --force`. It should be blocked with a message from the guard.

16. **Hook tests pass** (optional). In PowerShell:

    ```powershell
    python "$env:USERPROFILE\repos\shared-tooling\hooks\test-guard-destructive.py"
    python "$env:USERPROFILE\repos\shared-tooling\hooks\test-context-reminders.py"
    ```

## Optional extras

17. **Weekly plugin cache clean-up** (Claude Code leaves temporary folders behind):

    ```powershell
    & "$env:USERPROFILE\repos\shared-tooling\tools\Register-CleanPluginCache.ps1"
    ```

18. **Code search servers** (gitnexus and qmd): see [OPTIONAL-SERVERS.md](OPTIONAL-SERVERS.md).
